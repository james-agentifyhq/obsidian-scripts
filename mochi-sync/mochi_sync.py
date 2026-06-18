#!/usr/bin/env python3
"""
Mochi sync CLI for the _mochi/ Obsidian folder.

Talks to the Mochi REST API (https://app.mochi.cards/api) using HTTP Basic auth,
where the username is your API key and the password is empty.

The API key is read from the MOCHI_API_KEY environment variable. Load it from the
macOS Keychain at call time so the secret never lives in the vault:

    export MOCHI_API_KEY=$(security find-generic-password -s mochi-api-key -w)

Commands:
    decks                       List the deck tree (connectivity check).
    push  <path> [--deck-path]  Push a note or folder of notes to Mochi.
    pull  --deck-id ID --out D  Pull a deck's cards into local markdown files.

The Mochi API allows only one concurrent request per account, so every request
here runs sequentially with a small delay.

Standard library only. No third-party packages required.
"""

import argparse
import base64
import json
import mimetypes
import os
import re
import ssl
import sys
import time
import urllib.request
import uuid

API_BASE = "https://app.mochi.cards/api"
REQUEST_DELAY = 0.4  # seconds between requests, to respect the single-request limit


# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------
# The CLI needs to know the Obsidian vault root so it can resolve image embeds
# by basename (push) and detect missing attachments (pull). This MUST be
# configured explicitly, because the script no longer lives inside the vault —
# it can sit anywhere (e.g. a dev/ scripts repo).
#
# Resolution order (first match wins):
#   1. --vault-root CLI flag
#   2. MOCHI_VAULT_ROOT environment variable
#   3. "vault_root" in config.json next to this script
# A "~" prefix is expanded. If none resolve to an existing directory, commands
# that need it fail with a clear message (the API-only `decks` command does not).

CONFIG_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "config.json")


def _load_config():
    if os.path.exists(CONFIG_PATH):
        try:
            with open(CONFIG_PATH, encoding="utf-8") as f:
                return json.load(f)
        except (json.JSONDecodeError, OSError) as e:
            sys.exit(f"Could not read config file {CONFIG_PATH}: {e}")
    return {}


_CONFIG = _load_config()
_VAULT_ROOT_OVERRIDE = None  # set from the --vault-root flag in main()


def vault_root(*, required=True):
    """Resolve the Obsidian vault root from flag, env, or config.json."""
    raw = _VAULT_ROOT_OVERRIDE or os.environ.get("MOCHI_VAULT_ROOT") or _CONFIG.get("vault_root")
    if raw:
        path = os.path.abspath(os.path.expanduser(raw))
        if os.path.isdir(path):
            return path
        sys.exit(f"Configured vault_root does not exist: {path!r}")
    if required:
        sys.exit(
            "Vault root is not configured. Set it one of these ways:\n"
            "  - pass --vault-root /path/to/vault\n"
            "  - export MOCHI_VAULT_ROOT=/path/to/vault\n"
            f"  - add {{\"vault_root\": \"/path/to/vault\"}} to {CONFIG_PATH}\n"
            "    (copy config.example.json to config.json and edit it)"
        )
    return None


def _build_ssl_context():
    """Build an SSL context with a working CA bundle.

    The python.org macOS build ships without CA certs, so fall back to the
    system bundle. Honors SSL_CERT_FILE, then certifi, then the macOS bundle.
    """
    cafile = os.environ.get("SSL_CERT_FILE")
    if cafile and os.path.exists(cafile):
        return ssl.create_default_context(cafile=cafile)
    try:
        import certifi
        return ssl.create_default_context(cafile=certifi.where())
    except Exception:
        pass
    if os.path.exists("/etc/ssl/cert.pem"):
        return ssl.create_default_context(cafile="/etc/ssl/cert.pem")
    return ssl.create_default_context()


_SSL_CTX = _build_ssl_context()

# Matches Obsidian embeds  ![[file.png]]  and markdown images  ![alt](path/file.png)
MEDIA_EXT = r"(?:png|jpe?g|gif|webp|svg|mp3|mp4|m4a|pdf)"
WIKI_IMG = re.compile(r"!\[\[([^\]|]+\." + MEDIA_EXT + r")(?:\|[^\]]*)?\]\]", re.I)
MD_IMG = re.compile(r"!\[[^\]]*\]\(([^)]+\." + MEDIA_EXT + r")\)", re.I)
# Pull side: markdown image with optional @media/ prefix -> capture the file path.
PULL_IMG = re.compile(r"!\[[^\]]*\]\((?:@media/)?([^)]+\." + MEDIA_EXT + r")\)", re.I)

# Card metadata that lives as Obsidian frontmatter properties but renders inside the
# Mochi card body as a leading "key: value" block followed by a --- separator.
# push re-injects these into the body; pull extracts them back into frontmatter.
CONTENT_FIELDS = ["location", "floor", "room", "loci", "System"]
CONTENT_FIELD_RE = re.compile(r"^(" + "|".join(CONTENT_FIELDS) + r"):\s*(.*)$")


def _yaml_val(v):
    v = str(v).strip()
    if re.fullmatch(r"-?\d+", v):
        return v
    return '"' + v.replace("\\", "\\\\").replace('"', '\\"') + '"'


def prepend_content_fields(fm, body):
    """Rebuild the leading 'key: value' block + separator from frontmatter, for push."""
    fields = [f"{k}: {fm[k]}" for k in CONTENT_FIELDS if fm.get(k, "") != ""]
    if not fields:
        return body
    return "\n".join(fields) + "\n---\n" + body


def extract_content_fields(content):
    """Pull the leading 'key: value' block + separator out of Mochi content, for pull."""
    lines = content.split("\n")
    collected, i = {}, 0
    while i < len(lines):
        m = CONTENT_FIELD_RE.match(lines[i])
        if m:
            collected[m.group(1)] = m.group(2).rstrip()
            i += 1
        else:
            break
    if not collected:
        return {}, content
    rest = lines[i:]
    if rest and rest[0].strip() == "---":
        rest = rest[1:]
    return collected, "\n".join(rest).lstrip("\n")


# ---------------------------------------------------------------------------
# HTTP
# ---------------------------------------------------------------------------

def _auth_header():
    key = os.environ.get("MOCHI_API_KEY")
    if not key:
        sys.exit(
            "MOCHI_API_KEY is not set.\n"
            "Load it from the Keychain first:\n"
            '  export MOCHI_API_KEY=$(security find-generic-password -s mochi-api-key -w)'
        )
    token = base64.b64encode(f"{key}:".encode()).decode()
    return f"Basic {token}"


def _request(method, path, *, params=None, body=None, multipart=None):
    """Perform one API request and return the parsed JSON response."""
    url = API_BASE + path
    if params:
        query = "&".join(f"{k}={urllib.parse.quote(str(v))}" for k, v in params.items() if v is not None)
        if query:
            url += "?" + query

    headers = {"Authorization": _auth_header()}
    data = None
    if multipart is not None:
        boundary = uuid.uuid4().hex
        field_name, filename, file_bytes = multipart
        ctype = mimetypes.guess_type(filename)[0] or "application/octet-stream"
        pre = (
            f"--{boundary}\r\n"
            f'Content-Disposition: form-data; name="{field_name}"; filename="{filename}"\r\n'
            f"Content-Type: {ctype}\r\n\r\n"
        ).encode()
        post = f"\r\n--{boundary}--\r\n".encode()
        data = pre + file_bytes + post
        headers["Content-Type"] = f"multipart/form-data; boundary={boundary}"
    elif body is not None:
        data = json.dumps(body).encode()
        headers["Content-Type"] = "application/json"

    req = urllib.request.Request(url, data=data, method=method, headers=headers)
    time.sleep(REQUEST_DELAY)
    try:
        with urllib.request.urlopen(req, context=_SSL_CTX) as resp:
            raw = resp.read().decode()
            return json.loads(raw) if raw else {}
    except urllib.error.HTTPError as e:
        sys.exit(f"API error {e.code} on {method} {path}: {e.read().decode()[:500]}")


def _paged(path, params=None):
    """Yield all docs across paginated responses using the bookmark cursor."""
    params = dict(params or {})
    seen_bookmark = None
    while True:
        page = _request("GET", path, params=params)
        for doc in page.get("docs", []):
            yield doc
        bookmark = page.get("bookmark")
        if not bookmark or bookmark == "nil" or bookmark == seen_bookmark:
            break
        seen_bookmark = bookmark
        params["bookmark"] = bookmark


# ---------------------------------------------------------------------------
# Decks
# ---------------------------------------------------------------------------

def fetch_decks():
    """Return {id: {name, parent}} and a path->id index."""
    decks = {}
    for d in _paged("/decks/"):
        decks[d["id"]] = {"name": d.get("name", ""), "parent": d.get("parent-id")}
    path_to_id = {}
    for did, info in decks.items():
        parts, cur = [], did
        while cur and cur in decks:
            parts.append(decks[cur]["name"])
            cur = decks[cur]["parent"]
        path_to_id["/".join(reversed(parts))] = did
    return decks, path_to_id


def resolve_deck(path_to_id, deck_path, *, create=False, dry_run=False):
    """Find a deck id by its full slash path, optionally creating missing levels."""
    if deck_path in path_to_id:
        return path_to_id[deck_path]
    if not create:
        sys.exit(f"Deck path not found: {deck_path!r}. Use --create-decks to create it, "
                 f"or run 'decks' to see existing paths.")
    parent_id, built = None, ""
    for part in deck_path.split("/"):
        built = f"{built}/{part}" if built else part
        if built in path_to_id:
            parent_id = path_to_id[built]
            continue
        if dry_run:
            print(f"  [dry-run] would create deck {built!r}")
            parent_id = f"<new:{built}>"
        else:
            body = {"name": part}
            if parent_id:
                body["parent-id"] = parent_id
            new = _request("POST", "/decks/", body=body)
            parent_id = new["id"]
            print(f"  created deck {built!r} -> {parent_id}")
        path_to_id[built] = parent_id
    return parent_id


# ---------------------------------------------------------------------------
# Frontmatter
# ---------------------------------------------------------------------------

def split_frontmatter(text):
    """Return (frontmatter_dict, raw_fm_lines, body). Minimal key: value parser."""
    if not text.startswith("---\n"):
        return {}, [], text
    end = text.find("\n---", 4)
    if end == -1:
        return {}, [], text
    block = text[4:end]
    body = text[end + 4:].lstrip("\n")
    fm = {}
    for line in block.splitlines():
        m = re.match(r"([A-Za-z0-9_-]+):\s*(.*)", line)
        if m:
            fm[m.group(1)] = m.group(2).strip().strip('"')
    return fm, block.splitlines(), body


def set_frontmatter_key(text, key, value):
    """Insert or update a single frontmatter key, preserving the rest."""
    if text.startswith("---\n"):
        end = text.find("\n---", 4)
        block = text[4:end]
        rest = text[end:]
        lines = block.splitlines()
        for i, line in enumerate(lines):
            if re.match(rf"{re.escape(key)}:", line):
                lines[i] = f"{key}: {value}"
                return "---\n" + "\n".join(lines) + rest
        lines.append(f"{key}: {value}")
        return "---\n" + "\n".join(lines) + rest
    return f"---\n{key}: {value}\n---\n{text}"


# ---------------------------------------------------------------------------
# Push
# ---------------------------------------------------------------------------

def find_image(note_dir, name):
    """Locate an image file referenced by a card, by basename, near the note."""
    base = os.path.basename(name)
    candidates = [
        os.path.join(note_dir, name),
        os.path.join(note_dir, base),
        os.path.join(note_dir, "_attachments", base),
    ]
    for c in candidates:
        if os.path.isfile(c):
            return c
    # fall back to a vault-wide search by basename
    vault = vault_root()
    for root, _dirs, files in os.walk(vault):
        if base in files:
            return os.path.join(root, base)
    return None


def push_file(path, deck_id, *, dry_run=False):
    with open(path, encoding="utf-8") as f:
        text = f.read()
    fm, _lines, body = split_frontmatter(text)

    # Reconstruct the leading metadata block (location/room/loci/...) that lives in
    # frontmatter locally but belongs in the card body in Mochi.
    body = prepend_content_fields(fm, body)

    # Collect referenced images and rewrite content to Mochi's @media syntax.
    note_dir = os.path.dirname(os.path.abspath(path))
    images = {}  # basename -> local file path
    def collect(m):
        ref = m.group(1)
        if ref.startswith("@media/"):
            return m.group(0)  # already rewritten by the wikilink pass
        base = os.path.basename(ref)
        local = find_image(note_dir, ref)
        if local:
            images[base] = local
        else:
            print(f"  ! image not found, left as-is: {ref}")
            return m.group(0)
        # Mochi stores and renders bare-filename refs (verified against live cards).
        return f"![]({base})"
    content = WIKI_IMG.sub(collect, body)
    content = MD_IMG.sub(collect, content)

    card_id = fm.get("mochi-id") or None
    payload = {"content": content, "deck-id": deck_id}

    if dry_run:
        action = "update" if card_id else "create"
        print(f"  [dry-run] {action} card from {os.path.basename(path)} "
              f"({len(images)} image(s)) -> deck {deck_id}")
        return

    if card_id:
        _request("POST", f"/cards/{card_id}", body=payload)
        print(f"  updated {card_id}  ({os.path.basename(path)})")
    else:
        created = _request("POST", "/cards/", body=payload)
        card_id = created["id"]
        with open(path, "w", encoding="utf-8") as f:
            f.write(set_frontmatter_key(text, "mochi-id", card_id))
        print(f"  created {card_id}  ({os.path.basename(path)})  [wrote mochi-id back]")

    for base, local in images.items():
        with open(local, "rb") as imgf:
            _request("POST", f"/cards/{card_id}/attachments/{base}",
                     multipart=("file", base, imgf.read()))
        print(f"    attached {base}")


def cmd_push(args):
    _decks, path_to_id = fetch_decks()
    if args.deck_id:
        deck_id = args.deck_id
    elif args.deck_path:
        deck_id = resolve_deck(path_to_id, args.deck_path,
                               create=args.create_decks, dry_run=args.dry_run)
    else:
        sys.exit("Provide --deck-path 'A/B' or --deck-id ID.")

    target = args.path
    files = []
    if os.path.isdir(target):
        for root, _dirs, names in os.walk(target):
            for n in sorted(names):
                if n.endswith(".md") and not n.startswith("_"):
                    files.append(os.path.join(root, n))
    else:
        files = [target]

    print(f"Pushing {len(files)} card(s) to deck {deck_id}"
          + (" [dry-run]" if args.dry_run else ""))
    for fp in files:
        push_file(fp, deck_id, dry_run=args.dry_run)


# ---------------------------------------------------------------------------
# Pull
# ---------------------------------------------------------------------------

def _vault_basenames():
    """Set of every filename present in the vault, for resolving embeds."""
    vault = vault_root()
    names = set()
    for _root, _dirs, files in os.walk(vault):
        names.update(files)
    return names


def cmd_pull(args):
    os.makedirs(args.out, exist_ok=True)
    have = _vault_basenames()
    count = 0
    missing = []
    for card in _paged("/cards/", {"deck-id": args.deck_id, "limit": 100}):
        if card.get("trashed?"):
            continue
        content = card.get("content", "")
        # Lift the leading metadata block into frontmatter properties.
        fields, content = extract_content_fields(content)
        # Image refs (bare or @media) -> Obsidian embeds, by basename.
        content = PULL_IMG.sub(lambda m: f"![[{os.path.basename(m.group(1))}]]", content)
        # Title from the card name, else first non-empty content line.
        title = (card.get("name") or "").strip()
        if not title:
            for line in content.splitlines():
                if line.strip():
                    title = line.lstrip("#").strip()
                    break
        title = re.sub(r"[\\/:*?\"<>|#^\[\]]", " ", title).strip()[:80] or card["id"]
        # The Mochi API exposes attachment metadata but not the binary. Flag any
        # attachment whose file is not already present somewhere in the vault.
        for fn in (card.get("attachments") or {}):
            if os.path.basename(fn) not in have:
                missing.append((title, fn))
        out = os.path.join(args.out, f"{title}.md")
        body = content if content.endswith("\n") else content + "\n"
        fm_lines = [f"mochi-id: {card['id']}"]
        fm_lines += [f"{k}: {_yaml_val(fields[k])}" for k in CONTENT_FIELDS if k in fields]
        fm_lines.append("tags: [mochi]")
        text = "---\n" + "\n".join(fm_lines) + "\n---\n" + body
        if args.dry_run:
            print(f"  [dry-run] would write {out}")
        else:
            with open(out, "w", encoding="utf-8") as f:
                f.write(text)
            print(f"  wrote {out}")
        count += 1
    print(f"Pulled {count} card(s).")
    if missing:
        print(f"\n  ⚠ {len(missing)} attachment(s) are not in the vault. The Mochi API "
              "cannot download\n    binaries, so the ![[ ]] embeds for these won't resolve "
              "until you add the files\n    (e.g. via Mochi's Markdown ZIP export). Missing:")
        for title, fn in missing[:20]:
            print(f"      - {fn}  (card: {title})")
        if len(missing) > 20:
            print(f"      … and {len(missing) - 20} more")


# ---------------------------------------------------------------------------
# Decks listing
# ---------------------------------------------------------------------------

def cmd_decks(_args):
    _decks, path_to_id = fetch_decks()
    for path in sorted(path_to_id):
        depth = path.count("/")
        print("  " * depth + f"- {path.split('/')[-1]}  ({path_to_id[path]})")
    print(f"\n{len(path_to_id)} deck(s).")


# ---------------------------------------------------------------------------

def main():
    p = argparse.ArgumentParser(description="Sync an Obsidian _mochi/ folder with Mochi.cards.")
    p.add_argument("--dry-run", action="store_true", help="show actions without calling the write API")
    p.add_argument("--vault-root", help="Obsidian vault root (overrides MOCHI_VAULT_ROOT and config.json)")
    sub = p.add_subparsers(dest="cmd", required=True)

    sub.add_parser("decks", help="list deck tree (connectivity check)").set_defaults(func=cmd_decks)

    pp = sub.add_parser("push", help="push a note or folder to Mochi")
    pp.add_argument("path", help="markdown file, or folder of .md files")
    pp.add_argument("--deck-path", help="full deck path, e.g. 'Mind Palaces/MemoryOS'")
    pp.add_argument("--deck-id", help="target deck id (overrides --deck-path)")
    pp.add_argument("--create-decks", action="store_true", help="create deck path if missing")
    pp.set_defaults(func=cmd_push)

    pl = sub.add_parser("pull", help="pull a deck's cards into local markdown")
    pl.add_argument("--deck-id", required=True)
    pl.add_argument("--out", required=True, help="output folder")
    pl.set_defaults(func=cmd_pull)

    args = p.parse_args()
    if args.vault_root:
        global _VAULT_ROOT_OVERRIDE
        _VAULT_ROOT_OVERRIDE = args.vault_root
    args.func(args)


if __name__ == "__main__":
    main()

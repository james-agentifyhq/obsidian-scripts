# mochi-sync

A small standard-library Python script (`mochi_sync.py`) that syncs an Obsidian
vault's `_mochi/` folder with [Mochi.cards](https://app.mochi.cards) over the REST API.
Unlike the Mochi Cards Pro plugin, it **uploads images** and can **pull** cards back.

> This script used to live inside the vault at `_mochi/_sync-cli/`. It now lives in the
> `obsidian-scripts` dev repo and reaches the vault through a configured path (see step 1).
> Nothing about the Mochi integration changed — only how it finds the vault.

## 1. Configure the vault root (once)

The script needs to know where your Obsidian vault is, so it can resolve image embeds by
basename (push) and detect missing attachments (pull). Copy the example and edit it:

```bash
cp config.example.json config.json
# config.json:
# { "vault_root": "~/src/__OBS__/vault" }
```

`config.json` is git-ignored (it's machine-local). You can also override the vault root
without a config file:

- `--vault-root /path/to/vault` (CLI flag, highest priority), or
- `export MOCHI_VAULT_ROOT=/path/to/vault` (environment variable).

Resolution order: `--vault-root` → `MOCHI_VAULT_ROOT` → `config.json`. The API-only
`decks` command works without it.

## 2. Store the API key in the Keychain (once)

The key never lives in the vault or the repo.

```bash
security add-generic-password -s mochi-api-key -a "$USER" -w
# paste your Mochi Pro API key (app.mochi.cards → Account settings → API)
```

## 3. Use it

The `sync.sh` wrapper loads the key from the Keychain and forwards arguments, so you never
handle the secret directly. Run it from this folder; pass **vault paths** to push/pull.

```bash
# connectivity check — list the deck tree with ids (no vault root needed)
./sync.sh decks

# preview a push (no writes). $VAULT is just for readable examples here.
VAULT=~/src/__OBS__/vault
./sync.sh --dry-run push "$VAULT/_mochi/MemoryOS" --deck-path "Mind Palaces/MemoryOS"

# push a single note to a deck (creates the deck path if missing)
./sync.sh push "$VAULT/_mochi/Mind Palace Tips/Active Recall.md" \
    --deck-path "Mind Palaces/Mind Palace Tips" --create-decks

# pull a deck back into a local folder
./sync.sh pull --deck-id <DECK_ID> --out "$VAULT/_mochi/_pulled"
```

You can also call the Python directly if the key is already exported:

```bash
export MOCHI_API_KEY=$(security find-generic-password -s mochi-api-key -w)
python3 mochi_sync.py decks
```

## How it works

- **Auth:** Basic auth, key as username (`Authorization: Basic base64("<key>:")`).
- **Card identity:** each note's `mochi-id` frontmatter is the Mochi card id. With an
  id it **updates** that card; without one it **creates** a card and writes the new id
  back into the note's frontmatter, so the next push updates instead of duplicating.
- **Decks:** `--deck-path "A/B/C"` is resolved against the live deck tree;
  `--create-decks` builds any missing levels.
- **Images (push):** `![[file.png]]` and `![](path/file.png)` are uploaded to the card
  via `POST /cards/:id/attachments/:filename` and the content is rewritten to the bare
  `![](file.png)` form that Mochi stores and renders. Image files are located next to the
  note, in a sibling `_attachments/`, or by basename anywhere in the **configured vault**.
- **Images (pull):** card image refs are rewritten to `![[file.png]]` embeds. The Mochi
  API exposes attachment metadata but **not the binary**, so pull resolves embeds against
  files already in the **configured vault** and reports any attachment whose file is missing.
- **Rate limit:** Mochi allows one request at a time, so calls run sequentially with a
  short delay.

## Card metadata properties

Loci cards carry a leading metadata block (`location` / `floor` / `room` / `loci` /
`System`) that, in Obsidian, lives as **frontmatter properties** but in Mochi renders as a
`key: value` block at the top of the card body. The CLI keeps both in sync automatically:

- **push** rebuilds that block from the frontmatter properties and prepends it (with the
  `---` separator) to the content sent to Mochi.
- **pull** lifts the block back out of the card body into frontmatter properties.

The managed keys are listed in `CONTENT_FIELDS` near the top of `mochi_sync.py`; add to
that list if you introduce new metadata keys.

## Running the sync (manual / on-demand)

There is **no automatic background sync** — the CLI runs only when you run it. The
`mochi-id` frontmatter makes every run idempotent (updates, never duplicates).

- **Obsidian → Mochi** (you edited cards in the vault): `push`
- **Mochi → Obsidian** (you edited/added cards in Mochi): `pull`

### Automating it (optional)

1. **Shell alias** (still manual, just shorter):
   ```bash
   alias mochi='~/src/__OBS__/dev/obsidian-scripts/mochi-sync/sync.sh'
   ```
2. **macOS `launchd`** on a timer. Only safe one-directionally — pick a single source of
   truth. Recommended: schedule **push only** (Obsidian is the source of truth) and run
   `pull` by hand when needed.

## Troubleshooting

- `CERTIFICATE_VERIFY_FAILED`: the python.org macOS build ships without CA certs. The
  script falls back to the system bundle (`/etc/ssl/cert.pem`) automatically; if your
  setup differs, set `export SSL_CERT_FILE=/path/to/cacert.pem`.
- `Vault root is not configured` / `Configured vault_root does not exist`: create
  `config.json` (step 1) or pass `--vault-root`.

## Known limits

- **Attachment binaries cannot be pulled** — a Mochi API limitation: the API returns
  attachment metadata but no download URL or data. For genuinely new Mochi-side images,
  export them via Mochi's Markdown ZIP. Push (upload) is fully working.
- Front/Back field mapping uses the card `content` directly; it does not split into a
  template's named fields. Fine for free-form cards; templated decks may need field mapping.
- Always run with `--dry-run` first on a new deck.

## Specs

Behavior is specified as BDD/Gherkin features in [`spec/`](./spec).

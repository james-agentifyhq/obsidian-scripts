# obsidian-scripts

A single repository hosting all **ad-hoc scripts** for the Obsidian vault at
`~/src/__OBS__/vault`. Rather than one repo per script, every ad-hoc script lives here
as its own folder, managed under this one repo.

## Layout

```
obsidian-scripts/
├── {meaningful-name}/     # one folder per ad-hoc script
│   ├── README.md          #   what it does / how to run it
│   └── spec/              #   BDD feature specs (Gherkin .feature files)
├── {another-script}/
└── __archive/             # scripts that have graduated into a plugin
```

- **`{meaningful-name}/`** — each ad-hoc script gets its own folder with a short
  `README.md` describing what it does and how to run it.
- **`{meaningful-name}/spec/`** — BDD specifications in Gherkin (`.feature` files) describing the
  feature(s) the script implements, so its purpose is readable without opening the code.
- **`__archive/`** — once a script graduates (see below), its folder is moved here.

## Conventions

- Keep each script self-contained inside its folder.
- TypeScript is the default; `.gitignore` covers common Node/TypeScript artifacts.
- Document each script in a local `README.md`.
- Specify each script's behavior in `spec/` as Gherkin `.feature` files (one file per cohesive
  feature, named after the feature); keep specs in sync as behavior changes.

## Graduation to a plugin

Any script can be promoted to plugin development. When a script graduates — e.g. once it
moves past alpha — it becomes a standalone repo named `obsidian-plugin-{meaningful-name}`
(see the vault's `AGENTS.md`). At that point:

1. Move the script's folder into `__archive/`.
2. Update that folder's `README.md` to note **which plugin it graduated to**
   (e.g. "Graduated to `obsidian-plugin-foo`").

This keeps history while making clear the script is no longer the active source of truth.

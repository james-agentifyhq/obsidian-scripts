#!/usr/bin/env bash
# Thin wrapper around mochi_sync.py.
# Loads the Mochi API key from the macOS Keychain so you never type or store it,
# then forwards all arguments to the Python CLI.
#
# Examples:
#   ./sync.sh decks
#   ./sync.sh --dry-run push ../MemoryOS --deck-path "Mind Palaces/MemoryOS"
#   ./sync.sh push ../MemoryOS --deck-path "Mind Palaces/MemoryOS" --create-decks
#   ./sync.sh pull --deck-id bkPT3EJx --out ../_pulled
set -euo pipefail
cd "$(dirname "$0")"

if ! MOCHI_API_KEY="$(security find-generic-password -s mochi-api-key -w 2>/dev/null)"; then
  echo "No 'mochi-api-key' in the Keychain. Add it once with:" >&2
  echo "  security add-generic-password -s mochi-api-key -a \"\$USER\" -w" >&2
  exit 1
fi
export MOCHI_API_KEY
exec python3 mochi_sync.py "$@"

#!/bin/sh
# Start-up inside the container: check the secrets, build the library once, start the app.
set -e

for name in VAULT_ENCRYPTION_KEY VAULT_INDEX_KEY OPENAI_API_KEY; do
  if [ -z "$(printenv "$name")" ]; then
    echo "Missing $name. Put it in .env next to compose.yaml (see .env.example)." >&2
    exit 1
  fi
done

# First start only: read, mask, chunk and index the documents. The vault and the
# library live in Docker volumes, so later starts reuse them.
if [ ! -f data/index/chroma.sqlite3 ]; then
  echo "First start: preparing the documents (about a minute)..."
  python scripts/ingest.py
fi

exec python -m app

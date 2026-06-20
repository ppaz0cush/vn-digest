#!/usr/bin/env bash
# Bring up the WHOLE digest locally and serve the reader app.
#   ./setup/dev_local.sh           # start stack, fetch, serve (keeps DB data)
#   ./setup/dev_local.sh --reset   # also wipe + re-apply schema and re-seed
#
# Requires: Docker running, the `supabase` CLI, and the project venv (.venv).
set -euo pipefail
cd "$(dirname "$0")/.."

set -a; . ./.env.local; set +a
PY=.venv/bin/python
PORT="${PORT:-8000}"

echo "▶ supabase start"
supabase start >/dev/null 2>&1 || supabase start

if [ "${1:-}" = "--reset" ]; then
  echo "▶ db reset (applies migrations)"
  supabase db reset >/dev/null
fi

echo "▶ ensure single user ($MY_EMAIL)"
SERVICE_KEY="$SUPABASE_SERVICE_ROLE_KEY" "$PY" setup/create_user.py >/dev/null 2>&1 || true

echo "▶ fetch sources -> local DB"
"$PY" -m fetcher.main

echo
echo "▶ serving site at http://localhost:${PORT}  (Ctrl-C to stop)"
echo "  login: $MY_EMAIL / $MY_PASSWORD"
exec "$PY" -m http.server "$PORT" --directory site

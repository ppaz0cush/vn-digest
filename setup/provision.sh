#!/usr/bin/env bash
# Cloud provisioning — run ONLY after you are happy with the local build (§16).
# Does all Supabase + GitHub provisioning from the terminal.
#
# Requires (see §4 of BUILD_SPEC.md):
#   - SUPABASE_ACCESS_TOKEN exported (Supabase Account -> Access Tokens)
#   - `supabase` and `gh` CLIs installed; `gh auth login` already done
#   - `jq` installed
set -euo pipefail
cd "$(dirname "$0")/.."

PROJECT_NAME="${PROJECT_NAME:-vn-tech-digest}"
DB_PASSWORD="${DB_PASSWORD:?set DB_PASSWORD}"
REGION="${REGION:-ap-southeast-1}"            # closest to HCMC; adjust if needed
ORG_ID="${ORG_ID:?set ORG_ID (from: supabase orgs list)}"
MY_EMAIL="${MY_EMAIL:?set MY_EMAIL}"
MY_PASSWORD="${MY_PASSWORD:?set MY_PASSWORD}"

# 1) Create the Supabase project (skip if PROJECT_REF already set)
if [ -z "${PROJECT_REF:-}" ]; then
  PROJECT_REF="$(supabase projects create "$PROJECT_NAME" \
    --org-id "$ORG_ID" --db-password "$DB_PASSWORD" --region "$REGION" \
    --output json | jq -r '.id')"
fi
echo "Project ref: $PROJECT_REF"

# 2) Apply schema + RLS + grants as a migration
supabase link --project-ref "$PROJECT_REF" --password "$DB_PASSWORD"
supabase db push                                   # applies supabase/migrations/*

# 3) Read API keys via CLI (no copy-paste from dashboard)
ANON_KEY="$(supabase projects api-keys --project-ref "$PROJECT_REF" --output json | jq -r '.[] | select(.name=="anon") | .api_key')"
SERVICE_KEY="$(supabase projects api-keys --project-ref "$PROJECT_REF" --output json | jq -r '.[] | select(.name=="service_role") | .api_key')"
SUPABASE_URL="https://${PROJECT_REF}.supabase.co"

# 4) Disable public signups + auto-confirm email via the Management API
curl -sS -X PATCH "https://api.supabase.com/v1/projects/${PROJECT_REF}/config/auth" \
  -H "Authorization: Bearer ${SUPABASE_ACCESS_TOKEN}" \
  -H "Content-Type: application/json" \
  -d '{"disable_signup": true, "mailer_autoconfirm": true}' >/dev/null \
  && echo "Auth: signups disabled, email auto-confirm on" \
  || echo "WARN: auth config PATCH failed — set 'Disable signups' once in the dashboard."

# 5) Create the single account via the Admin API (scripted, no UI)
SUPABASE_URL="$SUPABASE_URL" SERVICE_KEY="$SERVICE_KEY" \
  MY_EMAIL="$MY_EMAIL" MY_PASSWORD="$MY_PASSWORD" \
  python setup/create_user.py

# 6) Create the GitHub repo and push
gh repo create "$PROJECT_NAME" --private --source=. --remote=origin --push

# 7) Secrets (for the daily fetcher) + variables (for the Pages build).
#    The anon key + URL are client-safe, so they live as repo VARIABLES and the
#    deploy-pages workflow writes site/config.js from them. The service_role key
#    is a SECRET, used only by the daily-fetch workflow.
gh secret   set SUPABASE_SERVICE_ROLE_KEY --body "$SERVICE_KEY"
gh secret   set SUPABASE_URL              --body "$SUPABASE_URL"
gh variable set SUPABASE_URL              --body "$SUPABASE_URL"
gh variable set SUPABASE_ANON_KEY         --body "$ANON_KEY"

# Enable Pages via GitHub Actions (the pages.yml workflow deploys site/).
OWNER="$(gh api user --jq .login)"
gh api -X POST "repos/${OWNER}/${PROJECT_NAME}/pages" \
  -f "build_type=workflow" >/dev/null 2>&1 \
  || echo "If Pages didn't enable, set it once in repo Settings -> Pages -> Source: GitHub Actions."

echo
echo "Done. Trigger a first fetch:  gh workflow run daily-fetch"
echo "Site will deploy via the deploy-pages workflow on the next push to main."

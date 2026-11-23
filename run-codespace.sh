#!/usr/bin/env bash
# Run the app in a GitHub Codespace (sandbox). Defaults suit a private codespace:
#   - sign-in codes are printed in this terminal (MAIL_MODE=console) until the M365 mailbox is set up
#   - reference files live in ./data/reference, uploaded by ADMIN_EMAILS from the home page
#   - Claude API key comes from the ANTHROPIC_API_KEY codespace secret
# Keep the forwarded port Private (the default): only you can open it.
set -euo pipefail
cd "$(dirname "$0")"
export MAIL_MODE="${MAIL_MODE:-console}"
export SOURCE_MODE="${SOURCE_MODE:-local}"
export AI_MODE="${AI_MODE:-claude}"
export COOKIE_SECURE="${COOKIE_SECURE:-true}"
export DATA_DIR="${DATA_DIR:-$PWD/data}"
export LOCAL_REF_DIR="${LOCAL_REF_DIR:-$DATA_DIR/reference}"
if [ -z "${SESSION_SECRET:-}" ]; then
  SESSION_SECRET="$(python3 -c 'import secrets; print(secrets.token_urlsafe(48))')"
  export SESSION_SECRET
fi
if [ -z "${ANTHROPIC_API_KEY:-}" ]; then
  echo "ANTHROPIC_API_KEY is not set. Add it as a Codespaces secret for this repository, then rebuild the codespace."
  exit 1
fi
mkdir -p "$LOCAL_REF_DIR"
echo "Opening on port 8000. Sign-in codes appear below as 'DEV MODE sign-in code'."
exec python3 -m uvicorn app.main:app --host 0.0.0.0 --port 8000 --proxy-headers --forwarded-allow-ips='*'

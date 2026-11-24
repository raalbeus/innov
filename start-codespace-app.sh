#!/usr/bin/env bash
# Start the app in the background in a GitHub Codespace. Runs automatically when the codespace starts.
#   - With an ANTHROPIC_API_KEY codespace secret: real Claude runs (needs IT/data approval first).
#   - Without one: replay mode on SAMPLE data (invented test outputs, no API key used).
# Sign-in codes are written to data/app.log; ./signin-code.sh prints the latest one.
set -uo pipefail
cd "$(dirname "$0")"
export DATA_DIR="${DATA_DIR:-$PWD/data}"
mkdir -p "$DATA_DIR"
LOG="$DATA_DIR/app.log"

if curl -s -o /dev/null --max-time 2 http://127.0.0.1:8000/login; then
  echo "The app is already running on port 8000."
  exit 0
fi
if ! python3 -c "import fastapi, uvicorn, openpyxl" 2>/dev/null; then
  echo "Installing requirements (first start only)..."
  pip install --user -q -r requirements.txt
fi

export MAIL_MODE="${MAIL_MODE:-console}" SOURCE_MODE="${SOURCE_MODE:-local}" COOKIE_SECURE="${COOKIE_SECURE:-true}"
export LOCAL_REF_DIR="${LOCAL_REF_DIR:-$DATA_DIR/reference}"
mkdir -p "$LOCAL_REF_DIR"
# Keep the session secret across restarts so users stay signed in.
if [ -z "${SESSION_SECRET:-}" ]; then
  [ -s "$DATA_DIR/.session_secret" ] || python3 -c 'import secrets; print(secrets.token_urlsafe(48))' > "$DATA_DIR/.session_secret"
  chmod 600 "$DATA_DIR/.session_secret"
  SESSION_SECRET="$(cat "$DATA_DIR/.session_secret")"
  export SESSION_SECRET
fi
if [ -n "${ANTHROPIC_API_KEY:-}" ] && [ "${AI_MODE:-}" != "replay" ]; then
  export AI_MODE=claude
else
  export AI_MODE=replay
  python3 tests/make_sample_fixtures.py "$DATA_DIR/sample" >/dev/null
  export REPLAY_DIR="${REPLAY_DIR:-$DATA_DIR/sample/replay}"
  # Offer the sample table in step 2 ("Use the reference folder table"), so nothing has to be downloaded first.
  export SPEC_PATTERN="${SPEC_PATTERN:-SAMPLE_Specifications_Table}"
  cp -n "$DATA_DIR/sample/SAMPLE_Specifications_Table.xlsx" "$LOCAL_REF_DIR/" 2>/dev/null || true
fi

setsid nohup python3 -m uvicorn app.main:app --host 0.0.0.0 --port 8000 --proxy-headers --forwarded-allow-ips='*' \
  >> "$LOG" 2>&1 &
for _ in $(seq 60); do
  if curl -s -o /dev/null --max-time 2 http://127.0.0.1:8000/login; then
    echo "The app is running on port 8000 (AI_MODE=$AI_MODE). Open it from the Ports tab."
    [ "$AI_MODE" = "replay" ] && echo "Sample mode: in step 2 click 'Use the reference folder table' (SAMPLE data)."
    echo "Sign-in code: run ./signin-code.sh after you click 'Send code'."
    exit 0
  fi
  sleep 1
done
echo "The app did not start. Last lines of $LOG:"
tail -n 20 "$LOG"
exit 1

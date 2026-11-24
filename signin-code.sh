#!/usr/bin/env bash
# Codespace sandbox only (MAIL_MODE=console): print the latest sign-in code from the app log.
cd "$(dirname "$0")"
line=$(grep -a "DEV MODE sign-in code" "${DATA_DIR:-data}/app.log" 2>/dev/null | tail -n 1)
if [ -z "$line" ]; then
  echo "No code yet. Enter your email on the sign-in page and click 'Send code', then run this again."
else
  echo "${line#*DEV MODE }"
fi

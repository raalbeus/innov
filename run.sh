#!/usr/bin/env bash
# Start the app. Put it behind an HTTPS reverse proxy (IIS, nginx or Azure App Service) in production.
set -euo pipefail
cd "$(dirname "$0")"
exec python3 -m uvicorn app.main:app --host "${HOST:-127.0.0.1}" --port "${PORT:-8000}" --proxy-headers

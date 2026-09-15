#!/usr/bin/env bash
# Runs both halves of the app inside the one container:
#   1. the LiveKit agent worker  (outbound only, no port)
#   2. the Next.js frontend       (the web process, binds $PORT)
# If EITHER exits, we tear the whole container down so the platform restarts it.
set -uo pipefail

# 1. Agent worker in production mode (dev.sh uses `dev`; prod uses `start`).
python -m interview.voice.agent start &
AGENT_PID=$!

# 2. Frontend as the $PORT web process (0.0.0.0 so the platform can reach it).
( cd web && pnpm exec next start -p "${PORT:-3000}" -H 0.0.0.0 ) &
WEB_PID=$!

cleanup() { kill "$AGENT_PID" "$WEB_PID" 2>/dev/null || true; }
trap cleanup EXIT INT TERM

echo "▶ agent (pid $AGENT_PID) + frontend (pid $WEB_PID) running on port ${PORT:-3000}"

# Wait for whichever process exits first, then shut down.
wait -n
CODE=$?
echo "■ a process exited (code $CODE) — stopping container"
exit "$CODE"

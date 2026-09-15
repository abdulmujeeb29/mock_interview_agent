#!/usr/bin/env bash
# Run the interview agent + the web frontend together, one command.
#
#   ./dev.sh                     # avatar on (default)
#   AVATAR_ENABLED=false ./dev.sh   # audio-only (instant, no avatar)
#   INTRO_TIME_LIMIT=25 PAST_TIME_LIMIT=35 ./dev.sh   # short timers for demoing the TIMER door
#
# Ctrl-C stops both.
set -euo pipefail
cd "$(dirname "$0")"

# shellcheck disable=SC1091
source .venv/bin/activate

export AVATAR_ENABLED="${AVATAR_ENABLED:-true}"

echo "▶ starting interview agent (AVATAR_ENABLED=$AVATAR_ENABLED) ..."
python -m interview.voice.agent dev &
AGENT_PID=$!

echo "▶ starting web frontend (http://localhost:3000) ..."
( cd web && pnpm dev ) &
WEB_PID=$!

# Kill both when this script exits or you press Ctrl-C.
cleanup() {
  echo
  echo "■ stopping (agent=$AGENT_PID, web=$WEB_PID) ..."
  kill "$AGENT_PID" "$WEB_PID" 2>/dev/null || true
}
trap cleanup EXIT INT TERM

echo "✔ both running. Open http://localhost:3000 — press Ctrl-C here to stop both."
wait

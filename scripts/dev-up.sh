#!/usr/bin/env bash
# Start the three local dev services together, each with its own log file:
#   1. Node agent runtime   (apps/api/agent, :8765) — required for chat turns;
#      without it every chat turn fails with agent_runtime_unavailable.
#   2. FastAPI backend      (apps/api,       :8000)
#   3. Vite web dev server  (apps/web,       :5189)
# Logs land in runtime-data/dev/. Use scripts/dev-down.sh to stop them.
set -euo pipefail

PROJECT_ROOT="$(cd "$(dirname "$0")/.." && pwd)"
LOG_DIR="$PROJECT_ROOT/runtime-data/dev"
mkdir -p "$LOG_DIR"

start_service() {
  local name="$1" pid_file="$2" log_file="$3"
  shift 3
  if [[ -f "$pid_file" ]] && kill -0 "$(cat "$pid_file")" 2>/dev/null; then
    echo "$name already running (pid $(cat "$pid_file"))"
    return
  fi
  ( "$@" >"$log_file" 2>&1 & echo $! >"$pid_file" )
  echo "$name started (pid $(cat "$pid_file"), log $log_file)"
}

start_service "agent-runtime" "$LOG_DIR/agent.pid" "$LOG_DIR/agent.log" \
  bash -c "cd '$PROJECT_ROOT/apps/api/agent' && npm start"

start_service "backend" "$LOG_DIR/backend.pid" "$LOG_DIR/backend.log" \
  bash -c "cd '$PROJECT_ROOT/apps/api' && uv run uvicorn app.main:app --host 127.0.0.1 --port 8000"

start_service "web" "$LOG_DIR/web.pid" "$LOG_DIR/web.log" \
  bash -c "cd '$PROJECT_ROOT/apps/web' && BACKEND_ORIGIN=http://127.0.0.1:8000 npm run dev -- --port 5189"

sleep 3
echo
echo "health:"
curl -s "http://127.0.0.1:8000/api/v1/health" || echo "  backend not ready yet — check $LOG_DIR/backend.log"
echo
echo "The agent_runtime field in the health response warns when the Node"
echo "runtime is unreachable (chat turns fail until it is up)."

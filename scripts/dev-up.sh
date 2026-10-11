#!/usr/bin/env bash
# Start the three local dev services together, each with its own log file:
#   1. Node agent runtime   (apps/api/agent, :8765) — required for chat turns;
#      without it every chat turn fails with agent_runtime_unavailable.
#   2. FastAPI backend      (apps/api,       :8000)
#   3. Vite web dev server  (apps/web,       :5189)
# Logs land in runtime-data/dev/. Use scripts/dev-down.sh to stop them.
#
# Usage: scripts/dev-up.sh [--resume]
#   --resume  一键复活（服务被杀/会话中断后）：幂等拉起服务，等 backend 健康（最多 90s），
#             打印 health 与恢复说明。FastAPI lifespan 启动时自动跑执行恢复
#             （main.py: _recover_agent_canvas_executions + auto_run_dispatcher.run_once
#             + provider 轮询），无需手动 resume；本命令的职责是给出"恢复已发生"的证据。
set -euo pipefail

PROJECT_ROOT="$(cd "$(dirname "$0")/.." && pwd)"
LOG_DIR="$PROJECT_ROOT/runtime-data/dev"
mkdir -p "$LOG_DIR"

WAIT_HEALTH=0
for arg in "$@"; do
  case "$arg" in
    --resume) WAIT_HEALTH=1 ;;
    *) echo "unknown argument: $arg (supported: --resume)" >&2; exit 2 ;;
  esac
done

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

echo
echo "health:"
if [[ "$WAIT_HEALTH" -eq 1 ]]; then
  health=""
  for _ in $(seq 1 45); do
    health="$(curl -s -m 2 "http://127.0.0.1:8000/api/v1/health" 2>/dev/null || true)"
    if [[ -n "$health" ]]; then break; fi
    sleep 2
  done
  if [[ -z "$health" ]]; then
    echo "  backend did not become healthy within 90s — check $LOG_DIR/backend.log"
    exit 1
  fi
  echo "  $health"
  echo
  echo "startup recovery ran during FastAPI lifespan (executions, continuations,"
  echo "auto-run commands, provider tasks). If a canvas node still looks stale,"
  echo "reopen the canvas — unmeasured nodes re-hydrate from the execution ledger."
  exit 0
fi

sleep 3
curl -s "http://127.0.0.1:8000/api/v1/health" || echo "  backend not ready yet — check $LOG_DIR/backend.log"
echo
echo "The agent_runtime field in the health response warns when the Node"
echo "runtime is unreachable (chat turns fail until it is up)."

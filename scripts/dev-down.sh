#!/usr/bin/env bash
# Stop the dev services started by scripts/dev-up.sh.
set -euo pipefail

PROJECT_ROOT="$(cd "$(dirname "$0")/.." && pwd)"
LOG_DIR="$PROJECT_ROOT/runtime-data/dev"

for name in web backend agent-runtime; do
  pid_file="$LOG_DIR/$name.pid"
  if [[ -f "$pid_file" ]]; then
    pid="$(cat "$pid_file")"
    if kill -0 "$pid" 2>/dev/null; then
      kill "$pid" && echo "$name stopped (pid $pid)"
    else
      echo "$name not running (stale pid file)"
    fi
    rm -f "$pid_file"
  else
    echo "$name: no pid file"
  fi
done

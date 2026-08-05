#!/bin/bash
# claude-mem worker watchdog — checks health, restarts if dead
trap 'bash /home/ubuntu/.hermes/scripts/kuma_ping.sh "claude-mem watchdog" done' EXIT
set -e

HEALTH_URL="http://localhost:37777/health"
ENV_FILE="/home/ubuntu/.claude-mem/env"
BUN="/home/ubuntu/.bun/bin/bun"
WORKER="/home/ubuntu/.hermes/node/lib/node_modules/claude-mem/plugin/scripts/worker-service.cjs"

# If it's already running, we're done
if curl -sf --max-time 3 "$HEALTH_URL" > /dev/null 2>&1; then
    exit 0
fi

# Kill any stale process
pkill -f 'worker-service.cjs' 2>/dev/null || true
sleep 1

# Start
source "$ENV_FILE"
nohup "$BUN" "$WORKER" >> /home/ubuntu/.claude-mem/worker.log 2>&1 &
disown

# Wait for it
for i in $(seq 1 10); do
    sleep 2
    if curl -sf --max-time 3 "$HEALTH_URL" > /dev/null 2>&1; then
        echo "$(date -Is) worker restarted" >> /home/ubuntu/.claude-mem/watchdog.log
        exit 0
    fi
done

echo "$(date -Is) FAILED to restart" >> /home/ubuntu/.claude-mem/watchdog.log
exit 1


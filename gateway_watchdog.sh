#!/bin/bash
# Hermes Gateway Watchdog - checks if gateway is running, restarts if not
# Runs via cron every minute

LOG=/home/ubuntu/.hermes/logs/watchdog.log
GATEWAY_BIN=/home/ubuntu/.local/bin/hermes

# Check if gateway process exists
if pgrep -f "hermes gateway run" > /dev/null 2>&1; then
    # Gateway is running - also check if WeChat inbound is alive
    # by checking gateway.log modification time (should update within last 5 min)
    GATEWAY_LOG=/home/ubuntu/.hermes/logs/gateway.log
    if [ -f "$GATEWAY_LOG" ]; then
        NOW=$(date +%s)
        MOD=$(stat -c %Y "$GATEWAY_LOG" 2>/dev/null || echo 0)
        AGE=$((NOW - MOD))
        if [ $AGE -gt 600 ]; then
            # Log hasn't been touched in 10 minutes - gateway may be hung
            echo "[$(date)] WARNING: gateway.log not updated for ${AGE}s, restarting" >> "$LOG"
            pkill -9 -f "hermes gateway run"
            sleep 2
            nohup $GATEWAY_BIN gateway run --replace >> /dev/null 2>&1 &
            echo "[$(date)] Gateway restarted (log stale)" >> "$LOG"
        fi
    fi
else
    # Gateway process not found - restart
    echo "[$(date)] Gateway process not found, restarting" >> "$LOG"
    nohup $GATEWAY_BIN gateway run --replace >> /dev/null 2>&1 &
    echo "[$(date)] Gateway restarted" >> "$LOG"
fi

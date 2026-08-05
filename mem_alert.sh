#!/bin/bash
# 内存/负载监控 — 超过阈值发告警
trap 'bash /home/ubuntu/.hermes/scripts/kuma_ping.sh "内存/负载告警" done' EXIT
set -e

MEM_THRESHOLD=85    # 内存使用百分比
LOAD_THRESHOLD=6    # 1分钟负载

MEM_PCT=$(free | awk '/Mem:/ {printf "%.0f", $3/$2*100}')
LOAD_1M=$(uptime | awk -F'[,:]' '{print $6}' | tr -d ' ')

if [ "$MEM_PCT" -ge "$MEM_THRESHOLD" ]; then
    echo "⚠️ 内存告警: ${MEM_PCT}% (阈值${MEM_THRESHOLD}%)"
    exit 0
fi

LOAD_INT=$(echo "$LOAD_1M" | cut -d. -f1)
if [ "$LOAD_INT" -ge "$LOAD_THRESHOLD" ]; then
    echo "⚠️ 负载告警: ${LOAD_1M} (阈值${LOAD_THRESHOLD})"
    exit 0
fi

# 正常 → 静默
exit 0


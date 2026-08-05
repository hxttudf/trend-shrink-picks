#!/bin/bash
# kuma_ping.sh — 向 Uptime Kuma 发送 Push 心跳
# 用法: kuma_ping.sh <任务名> [status]
KUMA_HOST="http://127.0.0.1:8002"
TOKEN_FILE="/home/ubuntu/.hermes/scripts/kuma_tokens.txt"
NAME="$1"
STATUS="${2:-done}"

if [ -z "$NAME" ]; then
    echo "kuma_ping: missing monitor name" >&2
    exit 0
fi

TOKEN=$(grep "^${NAME}|" "$TOKEN_FILE" 2>/dev/null | cut -d'|' -f2)
if [ -z "$TOKEN" ]; then
    echo "kuma_ping: unknown monitor '$NAME'" >&2
    exit 0
fi

curl -fsS -m 5 "${KUMA_HOST}/api/push/${TOKEN}?status=up&msg=${STATUS}+$(date +%H:%M)" > /dev/null 2>&1 || true

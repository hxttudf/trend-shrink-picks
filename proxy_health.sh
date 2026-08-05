#!/bin/bash
# 代理健康检查 — HTTP代理（v2ray port 20171），连续失败 N 次告警
trap 'bash /home/ubuntu/.hermes/scripts/kuma_ping.sh "代理健康检查" done' EXIT
PROXY="http://127.0.0.1:20171"
TEST_URL="https://www.google.com/generate_204"
STATE_FILE="/tmp/proxy_health_state"
MAX_FAILS=12

# 测速（走代理）
if curl -sL --connect-timeout 10 --max-time 15 -x "$PROXY" -o /dev/null -w "%{http_code}" "$TEST_URL" 2>/dev/null | grep -q "204"; then
    # 成功：清零失败计数
    prev=$(cat "$STATE_FILE" 2>/dev/null || echo "0:ok")
    fail_count=$(echo "$prev" | cut -d: -f1)
    if [ "$fail_count" -ge "$MAX_FAILS" ]; then
        echo "✅ 代理已恢复"
        echo "0:ok" > "$STATE_FILE"
    else
        echo "0:ok" > "$STATE_FILE"
        # 正常时不输出（静默）
    fi
else
    # 失败：累加
    prev=$(cat "$STATE_FILE" 2>/dev/null || echo "0:ok")
    fail_count=$(echo "$prev" | cut -d: -f1)
    fail_count=$((fail_count + 1))
    echo "${fail_count}:down" > "$STATE_FILE"
    if [ "$fail_count" -eq "$MAX_FAILS" ]; then
        echo "⚠️ 代理异常：连续 ${MAX_FAILS} 次无法访问外网"
    fi
fi


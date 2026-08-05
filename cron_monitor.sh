#!/bin/bash
# cron_monitor.sh — 每15分钟跑一次，检查每日cron任务状态
cd /home/ubuntu
exec /home/ubuntu/Sequoia-X-a/.venv-host/bin/python3 /home/ubuntu/.hermes/scripts/cron_monitor.py

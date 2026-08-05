#!/bin/bash
# Wind数据每日拉取
trap 'bash /home/ubuntu/.hermes/scripts/kuma_ping.sh "Wind数据每日拉取" done' EXIT
cd /home/ubuntu/nav
/home/ubuntu/Sequoia-X-a/.venv-host/bin/python3 wind_daily_pull.py

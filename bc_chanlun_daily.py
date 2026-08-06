#!/bin/bash
# wrapper: 真身单一来源在 /home/ubuntu/trend-shrink-picks (防代码漂移)
exec /home/ubuntu/Sequoia-X-a/.venv-host/bin/python3 /home/ubuntu/trend-shrink-picks/bc_chanlun_daily.py "$@"

#!/bin/bash
# Datasette 自动发现所有项目 DB 并启动
# 扫描以下目录中的 *.db 文件（含子目录）
SCAN_DIRS=(
  /home/ubuntu/databases
  /home/ubuntu/trend-stockscope
  /home/ubuntu/trend-shrink-picks
  /home/ubuntu/Sequoia-X-a/data
)

DB_ARGS=()
EXCLUDE_PATTERNS=(
  "Sequoia选股"  # 与 sequoia_v2 重复
)

for dir in "${SCAN_DIRS[@]}"; do
  if [ -d "$dir" ]; then
    while IFS= read -r -d '' db; do
      skip=false
      for pat in "${EXCLUDE_PATTERNS[@]}"; do
        if echo "$db" | grep -q "$pat"; then skip=true; break; fi
      done
      $skip || DB_ARGS+=("$db")
    done < <(find -L "$dir" -maxdepth 2 -name '*.db' -type f -print0 2>/dev/null)
  fi
done

exec /home/ubuntu/.local/bin/datasette "${DB_ARGS[@]}" \
  --crossdb \
  --plugins-dir /home/ubuntu/nav/datasette_plugins \
  --setting base_url /data/ \
  -h 0.0.0.0 -p 8001

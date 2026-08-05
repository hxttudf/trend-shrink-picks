#!/usr/bin/env python3
"""
检测有 last_delivery_error 的 cron 任务，输出待重试的内容。
被 agent cron 调用，通过 send_message 补发。
输出格式：
  JOB_NAME|OUTPUT_FILE_PATH|CONTENT_LENGTH
每行一个任务；无待办则无输出。
"""
import json, datetime
from pathlib import Path

CRON_JOBS_PATH = Path.home() / ".hermes" / "cron" / "jobs.json"
OUTPUT_DIR = Path.home() / ".hermes" / "cron" / "output"
PENDING_STATE = Path("/tmp/pending_delivery_retried.json")

# 只看以下需要推送到微信的任务（过滤掉local递送的内部任务）
WATCHED_JOBS = {
    "ETF信号-早盘10:32",
    "ETF信号-尾盘14:41",
    "市场午盘复盘",
    "市场收盘复盘",
    "午盘复盘",
    "尾盘复盘",
    "Sequoia-X 每日选股+回测",
    "Twitter情报-全量(账户+关键词+cashtags+分析)",
    "Twitter盘前风险扫描",
    "Cron任务监控-15分钟",
    "代理健康检查",
    "内存/负载告警",
    "缠论每日信号更新",
    "底部确认每日更新",
    "D3/W30标记更新",
    "On-this-day discovery",
    "趋势缩量选股",
}

RETRY_WINDOW_MINUTES = 120  # 只重试2小时内失败的任务

def load_retried():
    if PENDING_STATE.exists():
        try:
            return json.loads(PENDING_STATE.read_text())
        except: pass
    return {}

def save_retried(data):
    PENDING_STATE.write_text(json.dumps(data))

def main():
    if not CRON_JOBS_PATH.exists():
        return

    data = json.loads(CRON_JOBS_PATH.read_text())
    jobs = data.get("jobs", []) if isinstance(data, dict) else data
    retried = load_retried()
    now = datetime.datetime.now(datetime.timezone(datetime.timedelta(hours=8)))

    for j in jobs:
        name = j.get("name", "")
        if name not in WATCHED_JOBS:
            continue

        delivery_err = j.get("last_delivery_error")
        if not delivery_err:
            continue

        last_run_raw = j.get("last_run_at")
        if not last_run_raw:
            continue

        # 解析运行时间
        try:
            run_time = datetime.datetime.fromisoformat(last_run_raw)
        except:
            continue

        # 只重试最近2小时内的失败
        age = (now - run_time).total_seconds()
        if age > RETRY_WINDOW_MINUTES * 60:
            continue

        # 已经重试过了且当前状态还是error → 跳过（等下次cron运行刷新状态）
        if retried.get(name) == last_run_raw:
            continue

        # 找到最新的输出文件
        job_id = j.get("id", "")
        if not job_id:
            continue
        job_output_dir = OUTPUT_DIR / job_id
        if not job_output_dir.exists():
            continue

        output_files = sorted(job_output_dir.iterdir(), reverse=True)
        if not output_files:
            continue

        latest = output_files[0]
        content = latest.read_text(encoding="utf-8", errors="replace")
        if not content.strip():
            continue

        # 取有效内容：跳过cron元数据和prompt头部
        lines = content.split("\n")
        body_start = 0
        
        # 策略1: 找agent响应的 ## Response 标记
        for i, line in enumerate(lines):
            if line.strip().startswith("## Response"):
                body_start = i + 1
                break
        
        if body_start == 0:
            # 策略2: no_agent 输出 ─ 找第二个 ---（第一个是cron元数据结束，第二个是正文开始）
            dash_count = 0
            for i, line in enumerate(lines):
                if line.strip() == "---":
                    dash_count += 1
                    if dash_count == 2:
                        # 从下一行开始，跳过代码块标记
                        next_line = lines[i+1].strip() if i+1 < len(lines) else ""
                        if next_line.startswith("```"):
                            body_start = i + 2
                        else:
                            body_start = i + 1
                        break
        
        if body_start == 0:
            # 策略3: fallback ─ 取文件最后80%
            body_start = max(0, len(lines) - 80)
            
        body = "\n".join(lines[body_start:]).strip()
        # 去掉skill yaml头部（agent任务可能带skill内容）
        if body.startswith("---"):
            end_idx = body.find("---", 3)
            if end_idx > 0:
                body = body[end_idx + 3:].strip()
        # 去掉首尾的代码块标记
        if body.startswith("```"):
            body = body[3:].strip()
        if body.endswith("```"):
            body = body[:-3].strip()
        
        if not body or len(body) < 50:
            continue

        # 输出：任务名|内容
        print(f"JOB|{name}|{body}")
        retried[name] = last_run_raw

    save_retried(retried)

if __name__ == "__main__":
    main()

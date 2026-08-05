#!/usr/bin/env python3
"""Hermes Cron 任务监控 — 每15分钟跑一次，检查每日任务是否按时跑成功"""
import json, datetime, subprocess, sys
from pathlib import Path

CRON_JOBS_PATH = Path.home() / ".hermes" / "cron" / "jobs.json"
TRADING_DAY_SCRIPT = "/home/ubuntu/Sequoia-X-a/.venv-host/bin/python3 /home/ubuntu/Sequoia-X-a/is_trading_day.py"
WEIXIN_SEND = False  # 有告警时设为True

# 每日任务的预期时间表 (cron schedule)
# 格式: name -> {"hour": H, "minute": M} (24小时制)
DAILY_JOBS = {
    "ETF信号-早盘10:32":      {"hour": 10, "minute": 32},
    "ETF信号-尾盘14:41":      {"hour": 14, "minute": 41},
    "市场午盘复盘":           {"hour": 11, "minute": 45},
    "市场收盘复盘":           {"hour": 15, "minute": 15},
    "Wind数据每日拉取":        {"hour": 16, "minute": 0},
    "Sequoia-X 日线数据拉取":  {"hour": 15, "minute": 30},
    "Sequoia-X 每日选股+回测":  {"hour": 16, "minute": 30},
    "Twitter盘前风险扫描":     {"hour": 20, "minute": 30},
    "Twitter情报-全量(账户+关键词+cashtags+分析)": {"hour": 9, "minute": 0},
}

ALERT_WINDOW_MINUTES = 15  # 预期时间后15分钟内未完成即告警
STATE_FILE = Path("/tmp/cron_monitor_state.json")
DEDUP_MINUTES = 60  # 相同告警1小时内不重复
# 启动时清理超过2小时的旧状态（防止跨session脏数据）
CLEANUP_THRESHOLD = 7200  # 2小时


def load_state():
    if STATE_FILE.exists():
        try:
            return json.loads(STATE_FILE.read_text())
        except:
            return {}
    return {}


def save_state(state):
    STATE_FILE.write_text(json.dumps(state, ensure_ascii=False))


def should_alert(key, now_ts, state):
    """防重复：相同告警1小时内只发一次"""
    last = state.get(key)
    if last and (now_ts - last) < DEDUP_MINUTES * 60:
        return False
    state[key] = now_ts
    return True

def is_trading_day():
    """检查今天是不是交易日"""
    result = subprocess.run(
        TRADING_DAY_SCRIPT.split(), capture_output=True, timeout=15
    )
    return result.returncode == 0

def load_jobs():
    """读取 Hermes cron jobs.json"""
    if not CRON_JOBS_PATH.exists():
        return None
    with open(CRON_JOBS_PATH) as f:
        return json.load(f)

def check_job(job_data, job_name, schedule, now, today_str):
    """检查单个任务"""
    now_dt = datetime.datetime.fromtimestamp(now)
    
    # 期望运行时间
    expected_hour = schedule["hour"]
    expected_min = schedule["minute"]
    expected_dt = now_dt.replace(hour=expected_hour, minute=expected_min, second=0, microsecond=0)
    
    # 检查窗口: [expected_time, expected_time + ALERT_WINDOW_MINUTES]
    window_end = expected_dt + datetime.timedelta(minutes=ALERT_WINDOW_MINUTES)
    
    # 如果当前时间还没到检查窗口结束时间 → 还没到告警时间
    if now_dt < window_end:
        return None  # 还没到点，跳过
    
    # 获取任务状态
    last_run_raw = job_data.get("last_run_at")
    last_status = job_data.get("last_status")
    last_error = job_data.get("last_delivery_error") or ""
    
    # 解析 last_run_at
    run_time = None
    if last_run_raw:
        try:
            run_time = datetime.datetime.fromisoformat(last_run_raw)
        except:
            pass
    
    # 任务今天跑过吗？
    ran_today = run_time and run_time.strftime("%Y-%m-%d") == today_str
    
    if not ran_today:
        return f"❌ {job_name}: 未在{expected_hour:02d}:{expected_min:02d}前运行 (最后运行: {last_run_raw or '从未'})"
    
    # 跑了但状态异常
    if last_status == "error":
        msg = f"⚠️ {job_name}: 运行失败 (last_status=error)"
        if last_error:
            msg += f" | {last_error[:100]}"
        return msg
    
    return None  # 一切正常

def send_alert(message):
    """输出告警到 stdout (Hermes cron 会自动投递到微信)"""
    print(message)

def main():
    now = datetime.datetime.now()
    now_ts = now.timestamp()
    today_str = now.strftime("%Y-%m-%d")
    
    # 不是交易日 → 跳过 (今日无任务)
    if not is_trading_day():
        return
    
    data = load_jobs()
    if not data:
        print("⚠️ cron_monitor: 无法读取 jobs.json")
        return
    
    state = load_state()
    state_changed = False
    
    # 清理超过CLEANUP_THRESHOLD的旧状态
    now_ts = now.timestamp()
    stale_keys = [k for k, v in state.items() if (now_ts - v) > CLEANUP_THRESHOLD]
    for k in stale_keys:
        del state[k]
        state_changed = True
    if stale_keys:
        print(f"  [清理{len(stale_keys)}条过期状态]", file=sys.stderr)
    
    jobs_list = data.get("jobs", []) if isinstance(data, dict) else data
    
    # 构建 name->job 映射
    job_map = {}
    for j in jobs_list:
        name = j.get("name", "")
        job_map[name] = j
    
    alerts = []
    for name, schedule in DAILY_JOBS.items():
        job_data = job_map.get(name)
        if not job_data:
            key = f"not_found:{name}"
            if should_alert(key, now_ts, state):
                state_changed = True
                alerts.append(f"⚠️ {name}: jobs.json 中未找到")
            continue
        result = check_job(job_data, name, schedule, now_ts, today_str)
        if result:
            key = f"alert:{name}"
            if should_alert(key, now_ts, state):
                state_changed = True
                alerts.append(result)
    
    if state_changed:
        save_state(state)
    
    if alerts:
        header = f"📋 Cron 任务监控 ({now.strftime('%H:%M')})"
        print(f"\n{'='*40}\n{header}\n{'='*40}")
        for a in alerts:
            print(a)
        print()

if __name__ == "__main__":
    main()

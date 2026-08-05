#!/usr/bin/env python3
"""ETF 数据拉取脚本 — 拉当日价格写入 daily_close + 记录 fetch_log
用法: python3 etf_fetch_data.py [组合名] [数据源]
数据源默认 akshare，使用腾讯 qt 实时接口拉取（3位小数精度）
"""
import json, sys, sqlite3
from pathlib import Path
from datetime import datetime
import urllib.request

GROUP = sys.argv[1] if len(sys.argv) > 1 else "价纳创黄C3"
SOURCE = sys.argv[2] if len(sys.argv) > 2 else "akshare"
DATA_DIR = Path("/data")
CONFIG_FILE = DATA_DIR / "etf_config.json"
DB_PATH = DATA_DIR / "etf.db"


def load_config():
    with open(CONFIG_FILE) as f:
        return json.load(f)


def fetch_one_qt(code: str) -> dict | None:
    """腾讯qt实时行情 — 3位小数精度，用于获取当日最新价"""
    mkt = "sh" if code.startswith("5") else "sz"
    url = f"http://qt.gtimg.cn/q={mkt}{code}"
    req = urllib.request.Request(url)
    try:
        with urllib.request.urlopen(req, timeout=10) as resp:
            raw = resp.read().decode("gbk")
    except Exception as e:
        print(f"  [{code}] 腾讯qt拉取失败: {e}")
        return None
    try:
        parts = raw.split('"')[1].split("~")
        # qt格式: 3=现价, 4=昨收, 5=今开, 30=时间
        # qt时间格式: 20260617155956 → 2026-06-17
        qt_time = parts[30]
        date = f"{qt_time[:4]}-{qt_time[4:6]}-{qt_time[6:8]}"
        return {
            "date": date,
            "close": float(parts[3]),
            "open": float(parts[5]),
        }
    except (IndexError, ValueError) as e:
        print(f"  [{code}] qt解析失败: {e}")
        return None


def fetch_prices(codes: dict) -> dict:
    """拉取所有ETF当日价格（qt接口，3位小数），返回 {code: {date, close, open}}"""
    import time
    results = {}
    for name, code in codes.items():
        result = None
        for attempt in range(3):
            result = fetch_one_qt(code)
            if result:
                break
            time.sleep(2)
        if result:
            results[code] = result
            print(f"  {name}({code}): {result['date']} close={result['close']:.3f} open={result['open']:.3f}")
        else:
            print(f"  {name}({code}): 拉取失败(3次重试)")
    return results


def write_to_db(results: dict, source: str):
    """写入 daily_close 表"""
    conn = sqlite3.connect(str(DB_PATH))
    rows = []
    for code, info in results.items():
        rows.append((code, info["date"], info["close"], source))
    conn.executemany(
        "INSERT OR REPLACE INTO daily_close (code, date, close, source) VALUES (?,?,?,?)",
        rows,
    )
    conn.commit()
    conn.close()
    print(f"  写入 {len(rows)} 条到 daily_close")


def log_fetch(source: str, group: str, data_date: str):
    """记录拉取时间到 fetch_log"""
    conn = sqlite3.connect(str(DB_PATH))
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    conn.execute(
        "INSERT INTO fetch_log (source, group_name, fetch_time, data_date) VALUES (?,?,?,?)",
        (source, group, now, data_date),
    )
    conn.commit()
    conn.close()
    return now


def get_latest_fetch(group: str, source: str) -> str | None:
    """获取最近一次拉取时间"""
    conn = sqlite3.connect(str(DB_PATH))
    row = conn.execute(
        "SELECT fetch_time FROM fetch_log WHERE group_name=? AND source=? ORDER BY fetch_time DESC LIMIT 1",
        (group, source),
    ).fetchone()
    conn.close()
    return row[0] if row else None


if __name__ == "__main__":
    cfg = load_config()
    if GROUP not in cfg.get("groups", {}):
        print(f"组合 '{GROUP}' 不存在，可用: {list(cfg.get('groups', {}).keys())}")
        sys.exit(1)

    etfs = cfg["groups"][GROUP]
    print(f"📡 拉取 {GROUP} 数据 (source={SOURCE})")

    results = fetch_prices(etfs)
    if not results:
        print("❌ 所有ETF拉取失败")
        sys.exit(1)

    data_date = list(results.values())[0]["date"]
    write_to_db(results, SOURCE)
    now = log_fetch(SOURCE, GROUP, data_date)
    print(f"✅ 完成 | 拉取时间: {now} | 数据日期: {data_date}")

#!/usr/bin/env python3
"""ETF双动量信号 - 完整版（使用现有回测模块）
用法: python3 etf_signal_full.py [组合名]
"""
import json, sys, math, subprocess, sqlite3
from pathlib import Path
from datetime import datetime

# Add app dir to path for module imports
sys.path.insert(0, "/app")

import numpy as np
import pandas as pd

# ── 参数 ──
# Filter flags from positional args
args = [a for a in sys.argv[1:] if not a.startswith("--")]
GROUP = args[0] if args else "价纳创黄C3"
NO_FETCH = "--no-fetch" in sys.argv
IMAGE_MODE = "--image" in sys.argv
MA_DAYS = 55
ROC_DAYS = 20
CRASH_SIGMA = 2.6
CRASH_WINDOW = 51
MIN_HOLD = 0       # 与 Streamlit 一致
SOURCE = "akshare"  # 历史数据从 akshare 源读取
PORTFOLIO_START = "2026-05-06"  # 建仓起点（与 ETF 轮动配置一致）

CACHE_DIR = Path("/data")
CONFIG_FILE = CACHE_DIR / "etf_config.json"


def fetch_latest_data():
    """拉取当日最新数据到 daily_close，最多重试3次，校验日期"""
    fetch_script = CACHE_DIR / "etf_fetch_data.py"
    if not fetch_script.exists():
        return False
    
    today = datetime.now().strftime("%Y-%m-%d")
    
    for attempt in range(3):
        result = subprocess.run(
            [sys.executable, str(fetch_script), GROUP, SOURCE],
            capture_output=True, timeout=60
        )
        if result.returncode == 0:
            # 校验：确认今天的数据确实入库了
            conn = sqlite3.connect(str(CACHE_DIR / "etf.db"))
            row = conn.execute(
                "SELECT COUNT(*) FROM daily_close WHERE date=? AND source=?",
                (today, SOURCE)
            ).fetchone()
            conn.close()
            if row and row[0] > 0:
                return True
            print(f"  ⚠️ fetch 成功但 daily_close 无{today}数据，重试...", file=sys.stderr)
        else:
            stderr = result.stderr.decode()[-200:] if result.stderr else ""
            print(f"  ⚠️ fetch 失败(attempt {attempt+1}/3): {stderr}", file=sys.stderr)
        
        if attempt < 2:
            import time
            time.sleep(5 * (attempt + 1))
    
    print(f"  ❌ 3次拉取均失败，将使用最近可用数据", file=sys.stderr)
    return False


def get_fetch_time():
    """从 fetch_log 获取最近一次数据拉取时间"""
    conn = sqlite3.connect(str(CACHE_DIR / "etf.db"))
    row = conn.execute(
        "SELECT fetch_time FROM fetch_log WHERE group_name=? AND source=? ORDER BY fetch_time DESC LIMIT 1",
        (GROUP, SOURCE),
    ).fetchone()
    conn.close()
    return row[0] if row else None


def load_config():
    with open(CONFIG_FILE) as f:
        return json.load(f)


def load_prices():
    """从 daily_close 表加载指定数据源"""
    import sqlite3
    cfg = load_config()
    codes = list(cfg["groups"][GROUP].values())
    code_to_name = {v: k for k, v in cfg["groups"][GROUP].items()}

    db_path = CACHE_DIR / "etf.db"
    conn = sqlite3.connect(str(db_path))
    placeholders = ",".join("?" * len(codes))

    df = pd.read_sql_query(
        f"SELECT date, code, close FROM daily_close WHERE code IN ({placeholders}) AND source=? ORDER BY date",
        conn, params=codes + [SOURCE]
    )
    conn.close()

    df["date"] = pd.to_datetime(df["date"])
    close = df.pivot(index="date", columns="code", values="close")
    close = close.rename(columns=code_to_name)
    order = [code_to_name[c] for c in codes if c in code_to_name]
    return close[order], code_to_name


# ── 信号 ──
from etf_data import calc_indicators

def calc_signal(prices):
    """返回 (best, rows, crash_excluded_set)"""
    ma = prices.rolling(MA_DAYS).mean()
    roc = prices.pct_change(ROC_DAYS, fill_method=None)
    chg = prices.pct_change(1, fill_method=None)
    rets = prices.pct_change(fill_method=None)

    dt = prices.index[-1]
    rows = []
    qualified = {}
    crash_ex = set()

    # Crash filter
    if CRASH_SIGMA and len(rets) >= CRASH_WINDOW:
        window_slice = rets.iloc[-CRASH_WINDOW:]
        for name in prices.columns:
            r = window_slice[name].dropna()
            if len(r) >= CRASH_WINDOW:
                std = r.std()
                if std > 0 and r.iloc[-1] < -CRASH_SIGMA * std:
                    crash_ex.add(name)

    for name in prices.columns:
        px = prices[name].loc[dt]
        ma_val = ma[name].loc[dt]
        roc_val = roc[name].loc[dt]
        chg_val = chg[name].loc[dt]

        above = not pd.isna(ma_val) and px > ma_val
        crashed = name in crash_ex

        rows.append({
            "name": name, "close": px, "chg": chg_val,
            "above": above, "roc": roc_val, "crashed": crashed,
            "ma55": round(ma_val, 3) if not pd.isna(ma_val) else None,
        })

        if above and not crashed and not pd.isna(roc_val):
            qualified[name] = roc_val

    best = max(qualified, key=qualified.get) if qualified else None
    return best, rows, crash_ex


# ── 回撤（使用 run_backtest_bt）──
def calc_backtest_stats(prices, best_name):
    """用现有引擎跑回测，返回 (cur_dd, max_dd_range, advice)"""
    from etf_backtrader import run_backtest_bt

    # 从建仓起点开始
    start = PORTFOLIO_START
    end = prices.index[-1].strftime("%Y-%m-%d")

    result = run_backtest_bt(
        prices, mode="daily",
        start_date=start, end_date=end,
        ma_days=MA_DAYS, roc_days=ROC_DAYS, min_hold=MIN_HOLD,
        strategy='moc', exec_mode='moc',
        crash_sigma=CRASH_SIGMA, crash_std_window=CRASH_WINDOW,
        commission=0.0001, stamp_duty=0.0, slippage=0.0005
    )

    # result: (nav, bench_nav, ret, bench_ret, trades, trade_details, daily_signals, strat)
    # or for MOO: (nav, bench_nav, ret, bench_ret, trades, trade_dates, trade_details, daily_signals, None, holding_map, strat_nav, trade_details)
    nav = result[0]

    # ── 回撤计算（与 etf_app.py 一致）──
    nav_s = nav.copy()
    cmax = nav_s.cummax()
    dd_series = nav_s / cmax - 1
    
    # 当前回撤（从历史最高点算）
    cur_dd = float(dd_series.iloc[-1])
    
    # 寻找最近一次创新高的日期（当前回撤期的起点）
    dd_start = nav_s.index[0]
    for i in range(len(nav_s) - 1, -1, -1):
        if nav_s.iloc[i] == cmax.iloc[i]:
            dd_start = nav_s.index[i]
            break
    
    # 区间最大回撤（最近一次新高到现在的区间内最深）
    if cur_dd < 0:
        in_dd = dd_series.loc[dd_start:]
        max_dd_range = float(in_dd.min())
    else:
        max_dd_range = 0.0

    # ── 加仓建议（与 etf_app.py 完全一致）──
    cur = max_dd_range
    if cur >= -0.05:
        advice = "暂无加仓机会"
    elif cur >= -0.10:
        advice = "暂无加仓机会"
    elif cur >= -0.15:
        advice = "加仓至20%仓位"
    elif cur >= -0.20:
        advice = "加仓至50%仓位"
    else:
        advice = "加仓至80%仓位，留20%现金"

    return cur_dd, max_dd_range, advice


# ── Main ──

if not NO_FETCH:
    fetch_latest_data()

prices, code_to_name = load_prices()
best, rows, crash_ex = calc_signal(prices)
cur_dd, max_dd, advice = calc_backtest_stats(prices, best)

date_str = prices.index[-1].strftime("%Y-%m-%d")
fetch_time = get_fetch_time() or datetime.now().strftime("%Y-%m-%d %H:%M:%S")
today_str = datetime.now().strftime("%Y-%m-%d")
stale_warning = "" if date_str == today_str else f" ⚠️ 数据为{date_str}（非今日）"

# ── Build rank map: rank all 4 ETFs by 20日涨幅 (1=best)
all_ranked = sorted(rows, key=lambda r: r['roc'] if not pd.isna(r['roc']) else -999, reverse=True)
rank_map = {r['name']: i + 1 for i, r in enumerate(all_ranked)}
for r in rows:
    r["rank"] = rank_map.get(r["name"], None)



if IMAGE_MODE:
    from etf_signal_image import generate_signal_image
    img_path = generate_signal_image(
        date_str, GROUP, best, rows, cur_dd, max_dd, advice, fetch_time, stale_warning
    )
    # 容器内 /data = 宿主机 /home/ubuntu/etf-backtrader/data
    # 输出宿主机路径给 cron delivery
    print(f"MEDIA:/home/ubuntu/etf-backtrader/data/etf_signal.png")
else:
    # ── Text Output ──
    print(f"📡 **{date_str} {GROUP} 信号：持有 [{best or '空仓'}]** | 数据拉取: {fetch_time}{stale_warning}")
    print()
    print("| ETF | 收盘 | MA55 | 线上 | 到MA55 | 涨跌 | 暴跌 | 20日涨幅 | 排名 |")
    print("|-----|------|------|------|--------|------|------|---------|------|")
    for r in rows:
        tag_above = "✓" if r['above'] else "✗"
        tag_crash = "💥" if r['crashed'] else "—"
        name = f"**{r['name']}**" if r['name'] == best else r['name']
        roc_s = f"{r['roc']:.2%}" if not pd.isna(r['roc']) else "N/A"
        chg_s = f"{r['chg']:+.3%}" if not pd.isna(r['chg']) else "N/A"
        rank = rank_map.get(r['name'], "—")
        # 需涨到（从昨收算起到MA55的涨幅）
        ma55_val = r['ma55']
        if ma55_val is not None and not r['above'] and not pd.isna(r['chg']):
            # 从当日涨跌幅反推昨收
            close_prev = r['close'] / (1 + r['chg']) if r['chg'] != -1 else r['close']
            need_pct = (ma55_val - close_prev) / close_prev * 100
            need_s = f"需涨{need_pct:.1f}%"
        elif ma55_val is not None:
            need_s = "✅已突破"
        else:
            need_s = "N/A"
        print(f"| {name} | {r['close']:.3f} | {ma55_val if ma55_val else 'N/A'} | {tag_above} | {need_s} | {chg_s} | {tag_crash} | {roc_s} | {rank} |")
    print()
    print(f"> 📉 当前回撤: {cur_dd:.1%}  |  区间最大回撤: {max_dd:.1%}  |  {advice}")

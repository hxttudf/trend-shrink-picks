#!/usr/bin/env python3
"""问题2: MA5/MA10 进出场回测 (对比固定T+10)
入场: V4 worth信号(80-88分/4期/底90/跌幅20-65/非ST+市场过滤)
策略A: 固定持有T+10
策略B: MA5>MA10时持有, MA5<MA10时次日卖出 (至少持有3天, 最多持有40天)
策略C: 入场加条件 MA5>MA10
"""
import sqlite3
from collections import defaultdict

SCORES_DB = "/home/ubuntu/trend-shrink-picks/bc_scores2.db"
DB = "/home/ubuntu/Sequoia-X-a/data/sequoia_v2.db"

conn = sqlite3.connect(SCORES_DB)
rows = conn.execute(
    "SELECT bt_date, symbol, score, s65, drop_pct, bottom_days FROM scores "
    "WHERE score BETWEEN 80 AND 88 AND s65>=4 AND bottom_days>=90 "
    "AND abs(drop_pct) BETWEEN 20 AND 65 AND is_st=0"
).fetchall()
conn.close()

db = sqlite3.connect(DB)
idx = [r[0] for r in db.execute(
    "SELECT date FROM stock_daily WHERE symbol='000001.SH' AND close_qfq>0 ORDER BY date")]
idx_close = [r[0] for r in db.execute(
    "SELECT close_qfq FROM stock_daily WHERE symbol='000001.SH' AND close_qfq>0 ORDER BY date")]
idx_ma60 = {}
for i in range(59, len(idx_close)):
    idx_ma60[int(idx[i].replace('-', ''))] = sum(idx_close[i-59:i+1]) / 60
idx_close_by_date = {}
for i, d in enumerate(idx):
    idx_close_by_date[int(d.replace('-', ''))] = idx_close[i]

# 市场过滤
sigs = [r for r in rows if idx_close_by_date.get(r[0], 0) > idx_ma60.get(r[0], 0)]

# 预取信号股的日线序列
sym_all = set(r[1] for r in sigs)
series = {}
for sym in sym_all:
    c = db.execute(
        "SELECT date, close_qfq FROM stock_daily WHERE symbol=? AND close_qfq>0 ORDER BY date",
        (sym,)).fetchall()
    series[sym] = [(d.replace('-', ''), v) for d, v in c]  # [(yyyymmdd_int_str, close)]

def ma_at(sym, bd_str, n):
    """信号日前一天收盘的MA(n) (入场时可用信息)"""
    c = series.get(sym, [])
    closes = [v for d, v in c if d <= bd_str]
    if len(closes) < n:
        return None
    return sum(closes[-n:]) / n

def run_strategy(sigs, mode):
    """mode: 'fixed'固定T+10 / 'ma_exit' MA5<MA10卖出 / 'ma_entry' 入场要求MA5>MA10(固定T+10)"""
    results = []
    for bd, sym, *_ in sigs:
        bd_str = f"{bd//10000}{bd%10000//100:02d}{bd%100:02d}"
        c = series.get(sym, [])
        # 信号日索引
        idx_sig = next((i for i, (d, v) in enumerate(c) if d == bd_str), None)
        if idx_sig is None or idx_sig + 1 >= len(c):
            continue
        if mode in ('ma_exit', 'ma_entry'):
            ma5 = ma_at(sym, bd_str, 5)
            ma10 = ma_at(sym, bd_str, 10)
            if ma5 is None or ma10 is None:
                continue
            if mode in ('ma_entry', 'ma_exit_comb') and ma5 <= ma10:
                continue  # 入场要求MA5>MA10
        base = c[idx_sig][1]
        if mode == 'fixed':
            if idx_sig + 10 >= len(c):
                continue
            ret = (c[idx_sig + 10][1] / base - 1) * 100
            results.append((ret, 10))
        elif mode == 'ma_exit_comb':
            exit_ret = None
            hold = None
            for k in range(1, 41):
                if idx_sig + k >= len(c):
                    break
                seg = c[idx_sig + k - 4: idx_sig + k + 1]
                if len(seg) >= 5:
                    ma5k = sum(v for _, v in seg) / 5
                else:
                    break
                seg10 = c[idx_sig + k - 9: idx_sig + k + 1]
                if len(seg10) >= 10:
                    ma10k = sum(v for _, v in seg10) / 10
                else:
                    break
                if k >= 3 and ma5k < ma10k:
                    exit_ret = (c[idx_sig + k][1] / base - 1) * 100
                    hold = k
                    break
            if exit_ret is None:
                last_k = min(40, len(c) - 1 - idx_sig)
                if last_k <= 0:
                    continue
                exit_ret = (c[idx_sig + last_k][1] / base - 1) * 100
                hold = last_k
            results.append((exit_ret, hold))
        else:  # ma_exit: 从T+1起, MA5<MA10时卖出(至少持有3天, 最多40天)
            exit_ret = None
            hold = None
            for k in range(1, 41):
                if idx_sig + k >= len(c):
                    break
                # 第k天收盘后算MA5/MA10 (用第k天及之前5/10天)
                seg = c[idx_sig + k - 4: idx_sig + k + 1]
                if len(seg) >= 5:
                    ma5k = sum(v for _, v in seg) / 5
                else:
                    break
                seg10 = c[idx_sig + k - 9: idx_sig + k + 1]
                if len(seg10) >= 10:
                    ma10k = sum(v for _, v in seg10) / 10
                else:
                    break
                if k >= 3 and ma5k < ma10k:
                    exit_ret = (c[idx_sig + k][1] / base - 1) * 100
                    hold = k
                    break
            if exit_ret is None:
                # 40天内没触发卖出 → 用最后可用价
                last_k = min(40, len(c) - 1 - idx_sig)
                if last_k <= 0:
                    continue
                exit_ret = (c[idx_sig + last_k][1] / base - 1) * 100
                hold = last_k
            results.append((exit_ret, hold))
    return results

def stat(results, label):
    if not results:
        print(f"  {label}: 无数据")
        return
    rets = [r[0] for r in results]
    w = sum(1 for v in rets if v > 0)
    avg_hold = sum(r[1] for r in results) / len(results)
    print(f"  {label} (n={len(rets)}): 胜率{w/len(rets)*100:.0f}% 均收{sum(rets)/len(rets):+.2f}% 平均持有{avg_hold:.0f}天")

print("=== 策略对比 (V4 worth信号) ===")
stat(run_strategy(sigs, 'fixed'), "A: 固定持有T+10")
stat(run_strategy(sigs, 'ma_exit'), "B: MA5<MA10卖出(3~40天)")
stat(run_strategy(sigs, 'ma_entry'), "C: 入场MA5>MA10 + 固定T+10")
pass # placeholder

# 分年度
print("\n=== 分年度 ===")
for yr in ['2023', '2024', '2025', '2026']:
    gg = [r for r in sigs if str(r[0]).startswith(yr)]
    print(f"\n-- {yr} (n={len(gg)}) --")
    stat(run_strategy(gg, 'fixed'), "A: 固定T+10")
    stat(run_strategy(gg, 'ma_exit'), "B: MA5<MA10卖出")
    stat(run_strategy(gg, 'ma_entry'), "C: 入场MA5>MA10")
    stat(run_strategy(gg, 'ma_exit_comb'), "D: 组合")

db.close()

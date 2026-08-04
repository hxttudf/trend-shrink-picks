#!/usr/bin/env python3
"""方案A: 最近3年统计 + 最近一周信号明细"""
import sqlite3

SCORES_DB = "/home/ubuntu/trend-shrink-picks/bc_scores2.db"
DB = "/home/ubuntu/Sequoia-X-a/data/sequoia_v2.db"

conn = sqlite3.connect(SCORES_DB)
all_rows = conn.execute(
    "SELECT bt_date, symbol, score, streak, drop_pct, bottom_days, vol_shrink, cur, ma20, ma60, is_st FROM scores"
).fetchall()
conn.close()

B_sigs = [r for r in all_rows if r[2] >= 75 and r[3] >= 4 and r[10] == 0]

db = sqlite3.connect(DB)
names = dict(db.execute(
    "SELECT symbol, name FROM stock_basics WHERE date=(SELECT MAX(date) FROM stock_basics)"
).fetchall())

def get_rets(bd, sym):
    bd_str = f"{bd//10000}-{bd%10000//100:02d}-{bd%100:02d}"
    fut = db.execute(
        "SELECT close_qfq FROM stock_daily WHERE symbol=? AND close_qfq>0 AND date>? ORDER BY date LIMIT 20",
        (sym, bd_str)).fetchall()
    cur = db.execute(
        "SELECT close_qfq FROM stock_daily WHERE symbol=? AND date=? AND close_qfq>0",
        (sym, bd_str)).fetchone()
    if not cur:
        return None
    base = cur[0]
    rets = {}
    for h in [5, 10, 20]:
        rets[h] = (fut[h-1][0]/base - 1)*100 if len(fut) >= h else None
    return rets

# 方案A过滤
def planA(r):
    return (r[2] >= 78 and r[3] >= 5 and r[5] >= 60
            and -55 <= r[4] <= -25 and r[7] > r[9] and r[10] == 0)

sigs = [r for r in B_sigs if planA(r)]
print(f"方案A信号总数: {len(sigs)}\n")

# ── 最近3年统计(2023-07之后) ──
print("="*78)
print("方案A 最近3年胜率与收益率 (无未来函数)")
print("="*78)
recent = [r for r in sigs if r[0] >= 20230701]
for label, group in [
    ("近3年(2023-07~2026-07)", recent),
    ("2024", [r for r in sigs if str(r[0]).startswith('2024')]),
    ("2025", [r for r in sigs if str(r[0]).startswith('2025')]),
    ("2026(至7月)", [r for r in sigs if str(r[0]).startswith('2026')]),
]:
    rets_list = []
    for r in group:
        rets = get_rets(r[0], r[1])
        if rets:
            rets_list.append(rets)
    n = len(rets_list)
    if n == 0:
        print(f"  {label}: 无信号"); continue
    parts = []
    for h in [5, 10, 20]:
        vals = [x[h] for x in rets_list if x[h] is not None]
        if not vals: continue
        wins = sum(1 for v in vals if v > 0)
        med = sorted(vals)[len(vals)//2]
        parts.append(f"T+{h}: 胜率{wins/len(vals)*100:.1f}% 均收{sum(vals)/len(vals):+.2f}% 中位{med:+.2f}%")
    print(f"  {label} (n={n}):")
    for p in parts:
        print(f"    {p}")

# ── 最近一周信号(最后4个回测日) ──
print("\n" + "="*78)
print("最近一周方案A信号明细 (最后4个回测日)")
print("="*78)
btdates = sorted(set(r[0] for r in sigs))[-4:]
for bd in btdates:
    bd_str = f"{bd//10000}-{bd%10000//100:02d}-{bd%100:02d}"
    day_sigs = [r for r in sigs if r[0] == bd]
    if not day_sigs:
        continue
    print(f"\n📅 {bd_str}  ({len(day_sigs)}个信号)")
    print(f"  {'代码':<8}{'名称':<10}{'分数':>5}{'确认':>4}{'底部':>5}{'跌幅':>7}{'现价':>7}{'MA60':>7} | T+5  | T+10 | T+20")
    for r in day_sigs:
        rets = get_rets(r[0], r[1])
        nm = names.get(r[1], r[1])
        t5 = f"{rets[5]:+.1f}%" if rets and rets[5] is not None else "--"
        t10 = f"{rets[10]:+.1f}%" if rets and rets[10] is not None else "--"
        t20 = f"{rets[20]:+.1f}%" if rets and rets[20] is not None else "--"
        print(f"  {r[1]:<8}{nm:<10}{r[2]:>5.0f}{r[3]:>4}{r[5]:>5}{r[4]:>7.1f}{r[7]:>7.2f}{r[9]:>7.2f} | {t5}  | {t10} | {t20}")

db.close()

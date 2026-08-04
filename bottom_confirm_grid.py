#!/usr/bin/env python3
"""
老高策略参数网格搜索 — 快速版(基于bt_scores.db)
维度:
  MIN_SCORE 确认阈值: 60/65/70/75/80
  确认期数: >=2/>=3/>=4/>=5
  每日选股TOP_N: 5/10/15
指标: T+5/T+10/T+20 胜率+均收, 分年度稳健性
"""
import sqlite3, time
from collections import defaultdict
from itertools import product

SCORES_DB = "/home/ubuntu/trend-shrink-picks/bt_scores.db"
DB = "/home/ubuntu/Sequoia-X-a/data/sequoia_v2.db"

t0 = time.time()
btdb = sqlite3.connect(SCORES_DB)
conn = sqlite3.connect(DB)

btdates = [r[0] for r in btdb.execute("SELECT DISTINCT bt_date FROM scores ORDER BY bt_date")]
names = dict(conn.execute("SELECT symbol, name FROM stock_basics WHERE date=(SELECT MAX(date) FROM stock_basics)").fetchall())

# 预取全部评分(内存)
all_scores = btdb.execute("SELECT bt_date, symbol, score, is_oneword FROM scores").fetchall()
print(f"评分记录: {len(all_scores)}, {len(btdates)}个回测日", flush=True)

# 收益缓存: (bt_date, symbol) -> rets  (只对Top候选计算)
# 预计算所有需要收益的: 对所有score>=60的记录算收益(约19万太多, 只对每日Top20算)
# 先取每日Top20(按分数), 再算收益
top20 = {}
for bd in btdates:
    rows = btdb.execute(
        "SELECT symbol, score, is_oneword FROM scores WHERE bt_date=? ORDER BY score DESC LIMIT 20",
        (bd,)).fetchall()
    top20[bd] = rows
print(f"每日Top20已取, 开始算收益缓存...", flush=True)

# 收益缓存
ret_cache = {}
for bd, rows in top20.items():
    bd_str = f"{bd//10000}-{bd%10000//100:02d}-{bd%100:02d}"
    for sym, score, ow in rows:
        fut = conn.execute(
            "SELECT close_qfq FROM stock_daily WHERE symbol=? AND close_qfq>0 AND date>? ORDER BY date LIMIT 20",
            (sym, bd_str)).fetchall()
        cur = conn.execute(
            "SELECT close_qfq FROM stock_daily WHERE symbol=? AND date=? AND close_qfq>0",
            (sym, bd_str)).fetchone()
        if not cur:
            continue
        base = cur[0]
        rets = {}
        for h in [5, 10, 20]:
            rets[h] = (fut[h-1][0]/base - 1)*100 if len(fut) >= h else None
        ret_cache[(bd, sym)] = rets
print(f"收益缓存完成 {time.time()-t0:.0f}s", flush=True)

# 预计算确认期数: 对每个MIN_SCORE阈值
def build_consec(min_score):
    sym_dates = defaultdict(set)
    for bd, sym, sc, ow in all_scores:
        if sc >= min_score:
            sym_dates[sym].add(bd)
    consec = {}
    for sym, ds in sym_dates.items():
        streak = 0
        for bd in reversed(btdates):
            if bd in ds:
                streak += 1
                consec[(bd, sym)] = streak
            else:
                streak = 0
    return consec

def evaluate(min_score, need_streak, top_n, year=None):
    """返回 (n, t5_w, t5_r, t10_w, t10_r, t20_w, t20_r)"""
    consec = build_consec(min_score)
    sigs = []
    for bd in btdates:
        if year and not str(bd).startswith(year):
            continue
        picked = 0
        for sym, score, ow in top20[bd]:
            if picked >= top_n:
                break
            if 'ST' in names.get(sym, '').upper():
                continue
            streak = consec.get((bd, sym), 0)
            if streak < need_streak:
                continue
            rets = ret_cache.get((bd, sym))
            if not rets:
                continue
            sigs.append(rets)
            picked += 1
    n = len(sigs)
    if n == 0:
        return (0, 0, 0, 0, 0, 0, 0)
    out = [n]
    for h in [5, 10, 20]:
        vals = [s[h] for s in sigs if s.get(h) is not None]
        if not vals:
            out += [0, 0]
        else:
            wins = sum(1 for v in vals if v > 0)
            out += [wins/len(vals)*100, sum(vals)/len(vals)]
    return tuple(out)

# ═══ 网格搜索 ═══
print("\n网格搜索: 阈值×期数×TopN ...", flush=True)
results = []
for min_score, need_streak, top_n in product([60, 65, 70, 75, 80], [2, 3, 4, 5], [5, 10, 15]):
    r = evaluate(min_score, need_streak, top_n)
    if r[0] >= 50:  # 至少50个信号
        results.append((min_score, need_streak, top_n, r))
        # 年度稳健性
        y26 = evaluate(min_score, need_streak, top_n, year='2026')
        results[-1] = results[-1] + (y26,)

print(f"网格搜索完成 {time.time()-t0:.0f}s, {len(results)}个有效组合\n", flush=True)

# 按T+10综合排序: 胜率×均收 综合分 = t10_w + t10_r*5
def combo(r):
    n, t5w, t5r, t10w, t10r, t20w, t20r = r
    return t10w + t10r * 5

results.sort(key=lambda x: -(combo(x[3]) if x[3][0] > 0 else -999))

print("="*100)
print("Top 15 组合 (按T+10综合分排序)")
print("="*100)
print(f"{'阈值':>4}{'期数':>4}{'TopN':>5} | {'n':>4} | {'T5胜率':>7}{'T5均收':>7} | {'T10胜率':>7}{'T10均收':>8} | {'T20胜率':>7}{'T20均收':>8} | 2026(n/胜率/均收)")
print("-"*100)
for ms, ns, tn, r, y26 in results[:15]:
    n, t5w, t5r, t10w, t10r, t20w, t20r = r
    y26s = f"{y26[0]}/{y26[3]:.0f}%/{y26[4]:+.1f}%" if y26 and y26[0] > 0 else "无"
    print(f"{ms:>4}{ns:>4}{tn:>5} | {n:>4} | {t5w:>6.1f}%{t5r:>+6.2f} | {t10w:>6.1f}%{t10r:>+7.2f} | {t20w:>6.1f}%{t20r:>+7.2f} | {y26s}")

# 单独按2026表现排序
print("\n" + "="*100)
print("按2026熊市T+10综合分排序 Top 10 (稳健性优先)")
print("="*100)
results.sort(key=lambda x: -(combo(x[4]) if x[4] and x[4][0] > 0 else -999))
for ms, ns, tn, r, y26 in results[:10]:
    n, t5w, t5r, t10w, t10r, t20w, t20r = r
    y26s = f"n={y26[0]}, T10={y26[3]:.0f}%/{y26[4]:+.1f}%" if y26 and y26[0] > 0 else "无信号"
    print(f"阈值{ms} 期数{ns} TopN{tn}: 全期T10 {t10w:.1f}%/{t10r:+.2f}% | 2026 {y26s}")

conn.close(); btdb.close()

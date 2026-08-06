#!/usr/bin/env python3
"""全量重算 chanlun_signals 买点信号的 strength/strength_score — 新打分公式(缩量温和+超跌)
卖点(一卖/二卖/三卖)保持旧值; 特征全部取信号日及之前数据, 无未来函数"""
import sqlite3, sys, time
sys.path.insert(0, '/home/ubuntu/trend-shrink-picks')
from score_new import calc_strength, calc_score

PICKS = '/home/ubuntu/databases/trend_picks.db'
SEQ = '/home/ubuntu/Sequoia-X-a/data/sequoia_v2.db'
t0 = time.time()
picks = sqlite3.connect(PICKS, timeout=30)
seq = sqlite3.connect(SEQ)

rows = picks.execute(
    "SELECT symbol, signal_type, signal_date, ref_zd, ref_zg FROM chanlun_signals "
    "WHERE signal_type IN ('一买','二买','三买')").fetchall()
print(f"买点信号: {len(rows)}", flush=True)

cache = {}
n_ok = n_skip = 0
for sym, typ, sdate, zd, zg in rows:
    if sym not in cache:
        k = seq.execute(
            "SELECT date, open, high, low, close, close_qfq, volume FROM stock_daily "
            "WHERE symbol=? AND close_qfq>0 ORDER BY date", (sym,)).fetchall()
        if len(k) < 60:
            cache[sym] = None
            continue
        cache[sym] = ([r[5] for r in k], [r[6] for r in k], [r[2] for r in k],
                      [r[3] for r in k], {r[0]: i for i, r in enumerate(k)})
    pc = cache[sym]
    if pc is None:
        n_skip += 1
        continue
    closes, vols, highs, lows, d2i = pc
    idx = d2i.get(sdate)
    if idx is None or idx < 20:
        n_skip += 1
        continue
    st = calc_strength(typ, zd, zg, closes, vols, highs, lows, idx)
    sc = calc_score(typ, zd, zg, closes, vols, highs, lows, idx)
    picks.execute(
        "UPDATE chanlun_signals SET strength=?, strength_score=? "
        "WHERE symbol=? AND signal_date=? AND signal_type=?",
        (st, sc, sym, sdate, typ))
    n_ok += 1
    if n_ok % 20000 == 0:
        picks.commit()
        print(f"  ...{n_ok}条", flush=True)
picks.commit()
print(f"✅ 重算 {n_ok} 条 (跳过 {n_skip}, 耗时{time.time()-t0:.0f}s)", flush=True)

print("\n=== 新分数分布(买点) ===")
for r in picks.execute(
        "SELECT strength, COUNT(*), ROUND(AVG(strength_score),1) FROM chanlun_signals "
        "WHERE signal_type IN ('一买','二买','三买') AND strength_score>0 GROUP BY strength"):
    print(f"  {r[0]}: {r[1]}条 均分{r[2]}")
print("\n=== 2026年 强信号(双达标) ===")
for r in picks.execute(
        "SELECT signal_date, COUNT(*) FROM chanlun_signals "
        "WHERE signal_date>='2026-01-01' AND signal_type IN ('一买','二买','三买') "
        "AND strength='strong' GROUP BY signal_date ORDER BY signal_date DESC LIMIT 8"):
    print(f"  {r[0]}: {r[1]}个强")

#!/usr/bin/env python3
"""rescore_signals.py — 用修复后的volume重算受影响信号的strength_score
范围: chanlun_signals signal_date>='2026-08-18' 且 symbol在7天内volume被修复的651只
方法: 完全复刻chanlun_full数据准备(qf_rows同构), 调原始calc_score(纯函数, 只用≤信号日数据, 无未来函数)
只UPDATE strength_score/strength — 不碰confirmed_date/confirmed_later/overturned_*/status/price"""
import sqlite3
import sys

sys.path.insert(0, "/home/ubuntu/trend-shrink-picks")
from chanlun_full import calc_score, calc_strength

SEQ_DB = "/home/ubuntu/Sequoia-X-a/data/sequoia_v2.db"
PICKS_DB = "/home/ubuntu/databases/trend_picks.db"
BAK = '/home/ubuntu/databases/Sequoia选股.db.bak_vol2_20260827_234134'
CUTOFF = '2026-08-18'

seq = sqlite3.connect(SEQ_DB)
seq.execute(f"ATTACH '{BAK}' AS bak")

# 1) 7天内volume被修的symbol
vol_syms = {r[0] for r in seq.execute("""
    SELECT DISTINCT c.symbol FROM stock_daily c
    JOIN bak.stock_daily b ON c.symbol=b.symbol AND c.date=b.date
    WHERE IFNULL(c.volume,-1)!=IFNULL(b.volume,-1) AND c.date>='2026-08-20'""").fetchall()}
print(f'volume被修symbol: {len(vol_syms)}只')

# 2) 受影响信号
picks = sqlite3.connect(PICKS_DB, timeout=60)
sigs = [r for r in picks.execute(
    "SELECT symbol, signal_type, signal_date, strength_score FROM chanlun_signals WHERE signal_date>=?",
    (CUTOFF,)).fetchall() if r[0] in vol_syms]
print(f'受影响信号: {len(sigs)}条')

# 3) 逐symbol重算
done = changed = 0
sym_cache = {}
for sym, typ, sdate, old_sc in sigs:
    if sym not in sym_cache:
        rows = seq.execute(
            "SELECT date, open, high, low, close, close_qfq, volume FROM stock_daily "
            "WHERE symbol=? AND close_qfq>0 ORDER BY date", (sym,)).fetchall()
        if len(rows) < 150:
            sym_cache[sym] = None
            continue
        qf_rows = []
        for r in rows:
            ratio = r[5] / r[4] if r[4] else 1
            qf_rows.append([r[0], r[2] * ratio, r[3] * ratio, r[5]])
        closes_qf = [r[3] for r in qf_rows]
        highs_qf = [r[1] for r in qf_rows]
        lows_qf = [r[2] for r in qf_rows]
        vols_qf = [r[6] for r in rows]
        dates_qf = [r[0] for r in qf_rows]
        sym_cache[sym] = (dates_qf, closes_qf, highs_qf, lows_qf, vols_qf)
    data = sym_cache[sym]
    if not data:
        continue
    dates_qf, closes_qf, highs_qf, lows_qf, vols_qf = data
    if sdate not in dates_qf:
        continue
    di = dates_qf.index(sdate)
    try:
        sc = calc_score(typ, 0, 0, closes_qf, highs_qf, lows_qf, vols_qf, di)
        st = calc_strength(sc)
    except Exception:
        continue
    done += 1
    if old_sc is None or abs((old_sc or 50.0) - sc) > 0.05:
        picks.execute(
            "UPDATE chanlun_signals SET strength=?, strength_score=? WHERE symbol=? AND signal_type=? AND signal_date=?",
            (st, sc, sym, typ, sdate))
        changed += 1

picks.commit()
print(f'重算完成: 计算{done}条, 分数变化{changed}条(已UPDATE)')
picks.close()
seq.close()

#!/usr/bin/env python3
"""补打分: 回放INSERT的信号(7/17-8/5) strength_score=50(DEFAULT) — 重新计算
只处理 score IS NULL 或 =50 的(保留D3已打的真分); 三买zg=0用10日涨幅近似"""
import sqlite3, time

PICKS = '/home/ubuntu/databases/trend_picks.db'
SEQ = '/home/ubuntu/Sequoia-X-a/data/sequoia_v2.db'
t0 = time.time()

def calc_strength(typ, zd, zg, closes, vols, i):
    if i < 20 or i >= len(closes):
        return 'neutral'
    c0 = closes[i]
    avg = sum(vols[i - 20:i]) / 20 if i >= 20 else 1
    vr = vols[i] / avg if avg else 0
    if typ == '三买' and zg and zg > 0:
        brk = (c0 - zg) / zg * 100
        if brk > 5 and vr > 1.5:
            return 'strong'
        if brk < 3:
            return 'weak'
        return 'neutral'
    if typ in ('一买', '二买'):
        c10 = closes[i - 10]
        drop10 = (c0 - c10) / c10 * 100 if c10 else 0
        if drop10 < -20:
            return 'strong'
        if vr < 0.6 and drop10 > -20:
            return 'weak'
        return 'neutral'
    return 'neutral'

def calc_score(typ, zd, zg, closes, vols, i):
    if i < 20 or i >= len(closes):
        return 50.0
    c0 = closes[i]
    avg = sum(vols[i - 20:i]) / 20 if i >= 20 else 1
    vr = vols[i] / avg if avg else 0
    s = 50.0
    s += max(-20.0, min(20.0, (vr - 1) * 15))
    if typ == '三买':
        c10 = closes[i - 10]
        rise10 = (c0 - c10) / c10 * 100 if c10 else 0
        brk = (c0 - zg) / zg * 100 if (zg and zg > 0) else rise10  # 无中枢用10日涨幅近似
        s += max(-25.0, min(25.0, brk * 1.5))
    else:
        c10 = closes[i - 10]
        chg = (c0 - c10) / c10 * 100 if c10 else 0
        s += max(-25.0, min(25.0, -chg * 0.8))
    return round(max(0.0, min(100.0, s)), 1)

picks = sqlite3.connect(PICKS, timeout=30)
seq = sqlite3.connect(SEQ)
rows = picks.execute(
    "SELECT symbol, signal_type, signal_date, ref_zd, ref_zg FROM chanlun_signals "
    "WHERE signal_date BETWEEN '2026-07-17' AND '2026-08-05' "
    "AND (strength_score IS NULL OR strength_score=50)").fetchall()
print(f"待补打分: {len(rows)}条")

cache = {}
done = 0
for sym, typ, sdate, zd, zg in rows:
    if sym not in cache:
        cache[sym] = seq.execute(
            "SELECT date, open_qfq, close_qfq, volume FROM stock_daily "
            "WHERE symbol=? ORDER BY date", (sym,)).fetchall()
    kl = cache[sym]
    dates = [r[0] for r in kl]
    if sdate not in dates:
        continue
    i = dates.index(sdate)
    if i < 20 or i >= len(kl):
        continue
    closes = [r[2] or 0 for r in kl]
    vols = [r[3] or 0 for r in kl]
    st = calc_strength(typ, zd, zg, closes, vols, i)
    sc = calc_score(typ, zd, zg, closes, vols, i)
    picks.execute(
        "UPDATE chanlun_signals SET strength=?, strength_score=? "
        "WHERE symbol=? AND signal_type=? AND signal_date=?",
        (st, sc, sym, typ, sdate))
    done += 1
picks.commit()
print(f"✅ 补打分完成: {done}条 (耗时{time.time()-t0:.0f}s)")

# 汇总
for r in picks.execute(
        "SELECT signal_date, strength, COUNT(*), ROUND(AVG(strength_score),1) FROM chanlun_signals "
        "WHERE signal_date BETWEEN '2026-07-17' AND '2026-08-05' GROUP BY signal_date, strength "
        "ORDER BY signal_date, strength"):
    print(f"  {r[0]} {r[1]}: {r[2]}条 均分{r[3]}")

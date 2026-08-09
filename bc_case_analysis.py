#!/usr/bin/env python3
"""二买/三买典型案例分析: 有效(20日>+8%) vs 无效(<-8%) 信号的结构特征对比
输出: 每组典型个股的因子明细 + 两组因子均值差 — 归纳有效/无效逻辑
"""
import sqlite3, random
from collections import defaultdict

PICKS_DB = "/home/ubuntu/databases/trend_picks.db"
SEQ_DB = "/home/ubuntu/Sequoia-X-a/data/sequoia_v2.db"

def feat(closes, highs, lows, vols, i):
    ma20 = sum(closes[i-20:i+1]) / 21
    L60 = min(lows[i-60:i+1]); H60 = max(highs[i-60:i+1]); H40 = max(highs[i-40:i+1])
    H40p = max(highs[i-80:i-40]) if i >= 80 else H40
    c0 = closes[i]
    b5 = (c0/ma20 - 1) * 100 if ma20 > 0 else 0
    t1 = (c0 - H40)/H40 * 100 if H40 > 0 else 0
    pos60 = (c0 - L60)/(H60-L60) * 100 if H60 > L60 else 50
    dist_lo = (c0/L60 - 1) * 100 if L60 > 0 else 0
    t2 = (H40/H40p - 1) * 100 if H40p > 0 else 0
    t5 = (H40 - L60)/L60 * 100 if L60 > 0 else 0
    vr = vols[i] / max(sum(vols[i-20:i])/20, 1) if i >= 20 else 1   # 量能比(当日/20日均量)
    vtrend = (sum(vols[i-5:i])/5 / max(sum(vols[i-60:i])/60, 1) - 1) * 100  # 5日量能趋势
    chg5 = (c0/closes[i-5] - 1) * 100 if i >= 5 else 0
    return {'站上MA20(b5)': round(b5, 1), '距40日高%(-t1)': round(-t1, 1), '60日位置(pos60)': round(pos60, 1),
            '距60日低(dist_lo)': round(dist_lo, 1), '突破力度(t2)': round(t2, 1), '箱体高(t5)': round(t5, 1),
            '量能比(vr)': round(vr, 2), '5日量能趋势': round(vtrend, 1), '5日涨幅%': round(chg5, 1)}

def main():
    picks = sqlite3.connect(PICKS_DB)
    seq = sqlite3.connect(SEQ_DB)
    rows = picks.execute(
        "SELECT symbol, signal_type, signal_date FROM chanlun_signals "
        "WHERE signal_type IN ('二买','三买') AND confirmed_later=0").fetchall()
    px_cache = {}
    for sym in set(r[0] for r in rows):
        px = seq.execute(
            "SELECT date, open, high, low, close, close_qfq, volume FROM stock_daily WHERE symbol=? AND close_qfq>0 ORDER BY date",
            (sym,)).fetchall()
        if len(px) > 80:
            px_cache[sym] = px
    cases = defaultdict(lambda: {'ok': [], 'bad': []})
    for sym, typ, sd in rows:
        if sym not in px_cache:
            continue
        px = px_cache[sym]
        dates = [r[0] for r in px]; closes = [r[5] for r in px]
        highs = [r[2] for r in px]; lows = [r[3] for r in px]; vols = [r[6] for r in px]
        try:
            i = dates.index(sd)
        except ValueError:
            continue
        if i < 80 or i + 22 >= len(closes) or closes[i+2] <= 0:
            continue
        ret20 = (closes[i+22]/closes[i+2] - 1) * 100
        f = feat(closes, highs, lows, vols, i)
        rec = (ret20, sym, sd, round(closes[i], 2), f)
        if ret20 > 8:
            cases[typ]['ok'].append(rec)
        elif ret20 < -8:
            cases[typ]['bad'].append(rec)
    picks.close(); seq.close()
    KEYS = ['站上MA20(b5)', '距40日高%(-t1)', '60日位置(pos60)', '距60日低(dist_lo)',
            '突破力度(t2)', '箱体高(t5)', '量能比(vr)', '5日量能趋势', '5日涨幅%']
    for typ in ('二买', '三买'):
        ok = cases[typ]['ok']; bad = cases[typ]['bad']
        print(f"══════ {typ}: 有效(>+8%) {len(ok)}个 / 无效(<-8%) {len(bad)}个 ══════")
        # 因子均值对比
        print(f"\n【因子均值对比】  {'因子':<16}{'有效组':<10}{'无效组':<10}{'差异':<10}")
        okm = {k: sum(r[4][k] for r in ok)/len(ok) for k in KEYS}
        bdm = {k: sum(r[4][k] for r in bad)/len(bad) for k in KEYS}
        for k in KEYS:
            print(f"  {k:<16}{okm[k]:<10.2f}{bdm[k]:<10.2f}{okm[k]-bdm[k]:<+10.2f}")
        # 典型案例(各3个)
        for grp, rs in (('有效案例', ok), ('无效案例', bad)):
            print(f"\n【{grp}】")
            for ret20, sym, sd, px, f in rs[:3]:
                print(f"  {sym} {sd} 价格{px} 20日收益{ret20:+.1f}% | " +
                      " ".join(f"{k}={f[k]}" for k in KEYS[:6]))
        print()

if __name__ == "__main__":
    main()

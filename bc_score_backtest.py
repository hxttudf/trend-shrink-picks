#!/usr/bin/env python3
"""一二三买/一二三卖 当时信号全量 + 分数(strength_score)分层回测
口径: T+2买入 → T+2+5/20卖出; 复权; 当时确认(confirmed_later IN (0,NULL))
"""
import sqlite3
from collections import defaultdict

PICKS_DB = "/home/ubuntu/databases/trend_picks.db"
SEQ_DB = "/home/ubuntu/Sequoia-X-a/data/sequoia_v2.db"
TYPES = ('一买', '二买', '三买', '一卖', '二卖', '三卖')

def band(score):
    if score is None:
        return '无分'
    if score < 50: return '<50'
    if score < 60: return '50-60'
    if score < 70: return '60-70'
    if score < 80: return '70-80'
    if score < 90: return '80-90'
    return '≥90'

def main():
    picks = sqlite3.connect(PICKS_DB)
    seq = sqlite3.connect(SEQ_DB)
    rows = picks.execute(
        "SELECT symbol, signal_type, signal_date, strength_score FROM chanlun_signals "
        "WHERE signal_type IN ('一买','二买','三买','一卖','二卖','三卖') "
        "AND (confirmed_later IS NULL OR confirmed_later=0)").fetchall()
    px_cache = {}
    for sym in set(r[0] for r in rows):
        px = seq.execute(
            "SELECT date, close_qfq FROM stock_daily WHERE symbol=? AND close_qfq>0 ORDER BY date",
            (sym,)).fetchall()
        if px:
            px_cache[sym] = ([d for d, _ in px], [c for _, c in px])
    res = defaultdict(lambda: {5: [], 20: []})  # (typ, band) -> {N: [rets]}
    for sym, typ, sd, sc in rows:
        if sym not in px_cache:
            continue
        dates, closes = px_cache[sym]
        try:
            i = dates.index(sd)
        except ValueError:
            continue
        key = (typ, band(sc))
        for N in (5, 20):
            bi, si = i + 2, i + 2 + N
            if si < len(closes) and closes[bi] > 0:
                res[key][N].append(closes[si] / closes[bi] - 1)
    picks.close()
    seq.close()
    bands = ['<50', '50-60', '60-70', '70-80', '80-90', '≥90', '无分']
    print(f"{'类型':<6}{'分层':<8}{'样本':<9}{'胜率5':<8}{'收益5':<8}{'胜率20':<8}{'收益20':<8}")
    print("-" * 58)
    for typ in TYPES:
        for b in bands:
            d = res[(typ, b)]
            n = len(d[5])
            if not n:
                continue
            cells = []
            for N in (5, 20):
                rs = d[N]
                win = sum(1 for r in rs if r > 0) / len(rs) * 100
                avg = sum(rs) / len(rs) * 100
                cells.append(f"{win:<8.1f}{avg:<8.2f}")
            print(f"{typ:<6}{b:<8}{n:<9}" + "".join(cells))
        print()

if __name__ == "__main__":
    main()

#!/usr/bin/env python3
"""全面回测: 一二三买 新打分机制(一买v1 + 二买/三买v3) 分数分层胜率/收益率
口径: T+2买入→T+2+5/20卖出; 复权; 当时确认(confirmed_later IN (0,NULL)); DB strength_score
"""
import sqlite3
from collections import defaultdict

PICKS_DB = "/home/ubuntu/databases/trend_picks.db"
SEQ_DB = "/home/ubuntu/Sequoia-X-a/data/sequoia_v2.db"
TYPES = ('一买', '二买', '三买')

def main():
    picks = sqlite3.connect(PICKS_DB)
    seq = sqlite3.connect(SEQ_DB)
    rows = picks.execute(
        "SELECT symbol, signal_type, signal_date, strength_score FROM chanlun_signals "
        "WHERE signal_type IN ('一买','二买','三买') AND (confirmed_later IS NULL OR confirmed_later=0)").fetchall()
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
        sc = sc or 0
        bands = ['全部']
        if sc >= 60: bands.append('≥60')
        if sc >= 70: bands.append('≥70')
        if sc >= 80: bands.append('≥80')
        for b in bands:
            key = (typ, b)
            for N in (5, 20):
                bi, si = i + 2, i + 2 + N
                if si < len(closes) and closes[bi] > 0:
                    res[key][N].append(closes[si] / closes[bi] - 1)
    picks.close()
    seq.close()
    print(f"{'类型':<6}{'分层':<8}{'样本':<9}{'胜率5':<8}{'收益5':<9}{'胜率20':<8}{'收益20':<9}")
    print("-" * 60)
    for typ in TYPES:
        for b in ('全部', '≥60', '≥70', '≥80'):
            d = res[(typ, b)]
            n = len(d[5])
            if not n:
                print(f"{typ:<6}{b:<8}0         -        -        -        -")
                continue
            cells = []
            for N in (5, 20):
                rs = d[N]
                win = sum(1 for r in rs if r > 0) / len(rs) * 100
                avg = sum(rs) / len(rs) * 100
                cells.append(f"{win:<8.1f}{avg:<9.2f}")
            print(f"{typ:<6}{b:<8}{n:<9}" + "".join(cells))
        print()

if __name__ == "__main__":
    main()

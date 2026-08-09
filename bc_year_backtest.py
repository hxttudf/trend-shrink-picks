#!/usr/bin/env python3
"""一买二买三买 当时确认信号 按年回测胜率/收益率
口径: T+2买入 → T+2+N卖出(N=5/10/20); 复权价; 当时确认(confirmed_later IN (0,NULL))
"""
import sqlite3
from collections import defaultdict

PICKS_DB = "/home/ubuntu/databases/trend_picks.db"
SEQ_DB = "/home/ubuntu/Sequoia-X-a/data/sequoia_v2.db"

def main():
    picks = sqlite3.connect(PICKS_DB)
    seq = sqlite3.connect(SEQ_DB)
    rows = picks.execute(
        "SELECT symbol, signal_type, signal_date FROM chanlun_signals "
        "WHERE signal_type IN ('一买','二买','三买') AND (confirmed_later IS NULL OR confirmed_later=0)").fetchall()
    px_cache = {}
    for sym in set(r[0] for r in rows):
        px = seq.execute(
            "SELECT date, close_qfq FROM stock_daily WHERE symbol=? AND close_qfq>0 ORDER BY date",
            (sym,)).fetchall()
        if px:
            px_cache[sym] = ([d for d, _ in px], [c for _, c in px])
    res = defaultdict(lambda: {5: [], 10: [], 20: []})  # (typ, year) -> {N: [rets]}
    for sym, typ, sd in rows:
        if sym not in px_cache:
            continue
        dates, closes = px_cache[sym]
        try:
            i = dates.index(sd)
        except ValueError:
            continue
        key = (typ, sd[:4])
        for N in (5, 10, 20):
            bi, si = i + 2, i + 2 + N
            if si >= len(closes) or closes[bi] <= 0:
                continue
            res[key][N].append(closes[si] / closes[bi] - 1)
    picks.close()
    seq.close()
    years = sorted({k[1] for k in res})
    print(f"{'类型':<6}{'年份':<8}{'样本':<8}{'胜率5':<8}{'收益5':<9}{'胜率10':<8}{'收益10':<9}{'胜率20':<8}{'收益20':<9}")
    print("-" * 76)
    for typ in ('一买', '二买', '三买'):
        for y in years:
            d = res[(typ, y)]
            n = len(d[5])
            if not n:
                continue
            cells = []
            for N in (5, 10, 20):
                rs = d[N]
                win = sum(1 for r in rs if r > 0) / len(rs) * 100
                avg = sum(rs) / len(rs) * 100
                cells.append(f"{win:<8.1f}{avg:<9.2f}")
            print(f"{typ:<6}{y:<8}{n:<8}" + "".join(cells))
        print()

if __name__ == "__main__":
    main()

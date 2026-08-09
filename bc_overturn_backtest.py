#!/usr/bin/env python3
"""推翻率统计 + 被推翻信号(status=error)的胜率/收益率回测(对照ok信号)
口径: T+2买入(信号日收盘后2日) → T+2+N卖出; 复权价
"""
import sqlite3

PICKS_DB = "/home/ubuntu/databases/trend_picks.db"
SEQ_DB = "/home/ubuntu/Sequoia-X-a/data/sequoia_v2.db"

def main():
    picks = sqlite3.connect(PICKS_DB)
    seq = sqlite3.connect(SEQ_DB)
    rows = picks.execute(
        "SELECT symbol, signal_type, signal_date, status, confirmed_later FROM chanlun_signals "
        "WHERE signal_type IN ('一买','二买','三买')").fetchall()
    # 推翻率(按类型+确认时机)
    print("=" * 60)
    print("推翻率(被推翻error / 全部)")
    print("=" * 60)
    from collections import defaultdict
    cnt = defaultdict(lambda: [0, 0])  # (typ, group) -> [error, total]
    for sym, typ, sd, st, later in rows:
        grp = '事后' if later == 1 else '当时'
        cnt[(typ, grp)][1] += 1
        if st == 'error':
            cnt[(typ, grp)][0] += 1
    print(f"{'类型':<6}{'确认时机':<8}{'总数':<10}{'被推翻':<10}{'推翻率':<10}")
    for typ in ('一买', '二买', '三买'):
        for grp in ('当时', '事后'):
            e, t = cnt[(typ, grp)]
            print(f"{typ:<6}{grp:<8}{t:<10}{e:<10}{e/t*100 if t else 0:<10.1f}%")
        print()
    # 价格缓存
    px_cache = {}
    for sym in set(r[0] for r in rows):
        px = seq.execute(
            "SELECT date, close_qfq FROM stock_daily WHERE symbol=? AND close_qfq>0 ORDER BY date",
            (sym,)).fetchall()
        if px:
            px_cache[sym] = ([d for d, _ in px], [c for _, c in px])
    # error vs ok 信号回测
    print("=" * 60)
    print("被推翻信号(error) vs 有效信号(ok) 回测")
    print("=" * 60)
    res = {}  # (typ, status) -> {N: [rets]}
    for sym, typ, sd, st, later in rows:
        if sym not in px_cache:
            continue
        dates, closes = px_cache[sym]
        try:
            i = dates.index(sd)
        except ValueError:
            continue
        key = (typ, '被推翻' if st == 'error' else '有效')
        if key not in res:
            res[key] = {5: [], 10: [], 20: []}
        for N in (5, 10, 20):
            bi, si = i + 2, i + 2 + N
            if si >= len(closes) or closes[bi] <= 0:
                continue
            res[key][N].append(closes[si] / closes[bi] - 1)
    print(f"{'类型':<6}{'状态':<8}{'持有':<6}{'样本':<8}{'胜率':<8}{'平均收益':<10}{'中位收益':<10}")
    for typ in ('一买', '二买', '三买'):
        for st in ('被推翻', '有效'):
            for N in (5, 10, 20):
                rs = res.get((typ, st), {}).get(N, [])
                if not rs:
                    print(f"{typ:<6}{st:<8}{N:<6}0        -        -        -")
                    continue
                win = sum(1 for r in rs if r > 0) / len(rs) * 100
                avg = sum(rs) / len(rs) * 100
                med = sorted(rs)[len(rs) // 2] * 100
                print(f"{typ:<6}{st:<8}{N:<6}{len(rs):<8}{win:<8.1f}{avg:<10.2f}{med:<10.2f}")
        print()
    picks.close()
    seq.close()

if __name__ == "__main__":
    main()

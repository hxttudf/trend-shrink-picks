#!/usr/bin/env python3
"""回测: 一二三买 当时确认 vs 事后确认 信号的胜率与收益率(被推翻的也包含)
口径(承前): T收盘生成信号 → T+1确认 → T+2买入(收盘价) → T+2+N收盘卖出 (N=5/10/20)
分组: confirmed_later=1 事后确认; 0/NULL 当时确认(滚动T+1=当时)
"""
import sqlite3, sys

PICKS_DB = "/home/ubuntu/databases/trend_picks.db"
SEQ_DB = "/home/ubuntu/Sequoia-X-a/data/sequoia_v2.db"

def main():
    picks = sqlite3.connect(PICKS_DB)
    seq = sqlite3.connect(SEQ_DB)
    # 全部一二三买信号(ok+error都算)
    rows = picks.execute(
        "SELECT symbol, signal_type, signal_date, confirmed_later FROM chanlun_signals "
        "WHERE signal_type IN ('一买','二买','三买')").fetchall()
    # 每只股票的复权收盘价序列+日期索引
    px_cache = {}
    for sym in set(r[0] for r in rows):
        px = seq.execute(
            "SELECT date, close_qfq FROM stock_daily WHERE symbol=? AND close_qfq>0 ORDER BY date",
            (sym,)).fetchall()
        if px:
            px_cache[sym] = ([d for d, _ in px], [c for _, c in px])
    res = {}  # (type, group) -> {n5: [rets], n10: [...], n20: [...]}
    skipped = 0
    for sym, typ, sd, later in rows:
        if sym not in px_cache:
            continue
        dates, closes = px_cache[sym]
        try:
            i = dates.index(sd)
        except ValueError:
            skipped += 1
            continue
        group = '事后确认' if later == 1 else '当时确认'
        key = (typ, group)
        if key not in res:
            res[key] = {5: [], 10: [], 20: []}
        for N in (5, 10, 20):
            bi, si = i + 2, i + 2 + N  # T+2买入, T+2+N卖出
            if si >= len(closes):
                continue
            if closes[bi] <= 0:
                continue
            ret = closes[si] / closes[bi] - 1
            res[key][N].append(ret)
    picks.close()
    seq.close()
    # 输出
    print(f"{'信号类型':<8}{'确认时机':<10}{'持有':<6}{'样本':<8}{'胜率':<8}{'平均收益':<10}{'中位收益':<10}")
    print("-" * 62)
    for typ in ('一买', '二买', '三买'):
        for group in ('当时确认', '事后确认'):
            for N in (5, 10, 20):
                rs = res.get((typ, group), {}).get(N, [])
                if not rs:
                    print(f"{typ:<8}{group:<10}{N:<6}0        -          -          -")
                    continue
                win = sum(1 for r in rs if r > 0) / len(rs) * 100
                avg = sum(rs) / len(rs) * 100
                med = sorted(rs)[len(rs) // 2] * 100
                print(f"{typ:<8}{group:<10}{N:<6}{len(rs):<8}{win:<8.1f}{avg:<10.2f}{med:<10.2f}")
            print()

if __name__ == "__main__":
    main()

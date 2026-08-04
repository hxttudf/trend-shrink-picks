#!/usr/bin/env python3
"""二三买(同股同日二买+三买重合)历史胜率与收益率回测
数据源: trend_picks.db 滚动确认版(ok信号)
买入: 信号日+2开盘(T+2) | 卖出: T+10/T+20/止盈8%止损5%/对称卖点(后续卖点+1收盘)"""
import sqlite3

PICKS_DB = "/home/ubuntu/databases/trend_picks.db"
SEQ_DB = "/home/ubuntu/Sequoia-X-a/data/sequoia_v2.db"
HOLD10, HOLD20 = 10, 20
TP, SL = 1.08, 0.95


def main():
    picks = sqlite3.connect(PICKS_DB)
    seq = sqlite3.connect(SEQ_DB)
    # 2+3买重合信号(滚动版, ok)
    rows = picks.execute(
        "SELECT a.symbol, a.name, a.signal_date, a.price FROM chanlun_signals a "
        "JOIN chanlun_signals b ON a.symbol=b.symbol AND a.signal_date=b.signal_date "
        "WHERE a.signal_type='二买' AND b.signal_type='三买' AND a.status='ok' "
        "ORDER BY a.signal_date").fetchall()
    print(f"2+3买重合信号: {len(rows)}条")
    print(f"日期范围: {rows[0][2] if rows else '-'} ~ {rows[-1][2] if rows else '-'}")

    cache = {}
    results = []  # (year, r10, r20, rtp, rsym)
    for sym, name, sdate, sprice in rows:
        if sym not in cache:
            k = seq.execute(
                "SELECT date, open, high, low, close, close_qfq FROM stock_daily "
                "WHERE symbol=? AND close_qfq>0 ORDER BY date", (sym,)).fetchall()
            cache[sym] = ([[r[0], r[1] * (r[5] / r[4]), r[2] * (r[5] / r[4]), r[3] * (r[5] / r[4]), r[5]] for r in k],
                          {r[0]: i for i, r in enumerate(k)}, len(k))
        qf, d2i, n = cache[sym]
        idx = d2i.get(sdate)
        if idx is None or idx + 2 >= n:
            continue
        buy_i = idx + 2
        buy_p = qf[buy_i][1]
        if buy_p <= 0:
            continue
        c10 = qfq_close(qf, buy_i + HOLD10 - 1, n)
        c20 = qfq_close(qf, buy_i + HOLD20 - 1, n)
        r10 = c10 / buy_p - 1 if c10 is not None else None
        r20 = c20 / buy_p - 1 if c20 is not None else None
        # 止盈8/5
        rtp = None
        for i in range(buy_i, min(buy_i + HOLD20, n)):
            if qf[i][2] >= buy_p * TP:
                rtp = TP - 1
                break
            if qf[i][3] <= buy_p * SL:
                rtp = SL - 1
                break
        if rtp is None:
            rtp = r20
        # 对称卖点(后续最近卖点+1收盘)
        rsym = None
        sell_dates = sorted(sd for t, sd in cache_sells(sym, sdate, picks) if sd > sdate)
        for sd in sell_dates:
            si = d2i.get(sd)
            if si is not None and si + 1 < n and si + 1 > buy_i:
                rsym = qf[si + 1][4] / buy_p - 1
                break
        if rsym is None:
            c60 = qfq_close(qf, buy_i + 59, n)
            rsym = c60 / buy_p - 1 if c60 is not None else None
        results.append((sdate[:4], r10, r20, rtp, rsym))

    if not results:
        print("无结果")
        return
    print(f"\n有效回测: {len(results)}条")
    for rname, idx in [("T+10", 1), ("T+20", 2), ("止盈8/5", 3), ("对称卖点", 4)]:
        rs = [r[idx] for r in results if r[idx] is not None]
        win = sum(1 for x in rs if x > 0) / len(rs) * 100
        print(f"  {rname}: n={len(rs)} 胜率{win:.1f}% 均收益{sum(rs)/len(rs)*100:+.2f}% 中位{ sorted(rs)[len(rs)//2]*100:+.2f}%")
    # 分年
    print("\n分年度(对称卖点):")
    years = sorted(set(r[0] for r in results))
    for y in years:
        rs = [r[4] for r in results if r[0] == y and r[4] is not None]
        if rs:
            win = sum(1 for x in rs if x > 0) / len(rs) * 100
            print(f"  {y}: n={len(rs)} 胜率{win:.1f}% 均收益{sum(rs)/len(rs)*100:+.2f}%")


def qfq_close(qf, i, n):
    if i >= n:
        return None
    return qf[i][4]


_sell_cache = {}


def cache_sells(sym, sdate, picks):
    if sym not in _sell_cache:
        _sell_cache[sym] = {(t, d) for t, d in picks.execute(
            "SELECT signal_type, signal_date FROM chanlun_signals WHERE symbol=? AND signal_type LIKE '%卖%' AND status='ok'",
            (sym,)).fetchall()}
    return _sell_cache[sym]


if __name__ == "__main__":
    main()

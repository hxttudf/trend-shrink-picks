#!/usr/bin/env python3
"""二三买重合信号回测(标准严格口径)
重合 = 同股同日同时有二买+三买 (缠论最强买点)
口径: 信号T+1确认 → T+2开盘买入(qfq); 卖点信号次日收盘卖出; 对称卖点=T+60兜底"""
import sqlite3

SEQ_DB = "/home/ubuntu/Sequoia-X-a/data/sequoia_v2.db"
PICKS_DB = "/home/ubuntu/databases/trend_picks.db"
START = "2020-01-01"


def main():
    seq = sqlite3.connect(SEQ_DB)
    picks = sqlite3.connect(PICKS_DB)
    overlap = picks.execute('''
        SELECT a.symbol, a.signal_date, a.price FROM chanlun_signals a
        JOIN chanlun_signals b ON a.symbol=b.symbol AND a.signal_date=b.signal_date
        WHERE a.signal_type='二买' AND b.signal_type='三买' AND a.signal_date>=?
        ORDER BY a.signal_date''', (START,)).fetchall()
    print(f"二三买重合信号: {len(overlap)}个")

    from collections import Counter
    print("按年:", dict(sorted(Counter(d[:4] for _, d, _ in overlap).items())))

    rows = seq.execute("SELECT symbol, date, open, close, close_qfq FROM stock_daily "
                       "WHERE close_qfq>0 ORDER BY symbol, date").fetchall()
    per = {}
    for r in rows:
        per.setdefault(r[0], []).append(r)
    sell_sigs = {}
    for r in picks.execute("SELECT symbol, signal_date FROM chanlun_signals "
                           "WHERE signal_date>=? AND signal_type LIKE '%卖' ORDER BY symbol, signal_date",
                           (START,)):
        sell_sigs.setdefault(r[0], []).append(r[1])

    res10, res20, res_sym, hold, rets = [], [], [], [], []
    for sym, sdate, sprice in overlap:
        bars = per.get(sym)
        if not bars or len(bars) < 30:
            continue
        d2i = {r[1]: i for i, r in enumerate(bars)}
        bi = d2i.get(sdate)
        if bi is None or bi + 2 >= len(bars):
            continue
        buy_i = bi + 2  # 信号T+1确认, T+2开盘买入(标准口径)
        buy_p = bars[buy_i][2] * (bars[buy_i][4] / bars[buy_i][3])  # open_qfq
        if buy_p <= 0:
            continue
        if buy_i + 9 < len(bars):
            res10.append(bars[buy_i + 9][4] / buy_p - 1)
        if buy_i + 19 < len(bars):
            res20.append(bars[buy_i + 19][4] / buy_p - 1)
        sold = None
        for sd in sell_sigs.get(sym, []):
            si = d2i.get(sd)
            if si is not None and si > buy_i:
                sold = (bars[si + 1][4] / buy_p - 1, si + 1 - buy_i)  # 卖点次日收盘(标准口径)
                break
        if sold is None:
            if buy_i + 60 >= len(bars):
                continue
            sold = (bars[buy_i + 60][4] / buy_p - 1, 60)
        res_sym.append(sold[0])
        hold.append(sold[1])
        rets.append(sold[0])

    def stat(name, arr):
        n = len(arr)
        win = sum(1 for x in arr if x > 0) / n * 100
        avg = sum(arr) / n * 100
        print(f"  {name}: n={n} 胜率{win:.1f}% 均收益{avg:+.2f}%")

    print(f"\n── 重合信号回测(严格口径: T+2开盘买入) ──")
    stat("T+10", res10)
    stat("T+20", res20)
    stat("对称卖点", res_sym)
    avg_hold = sum(hold) / len(hold)
    avg_ret = sum(rets) / len(rets)
    ann = (1 + avg_ret / 100) ** (250 / avg_hold) - 1
    print(f"  对称卖点: 均持有{avg_hold:.0f}天 年化{ann*100:.0f}%")

    # 对比: 单独二买 / 单独三买
    print(f"\n── 对照组(单独信号, 对称卖点) ──")
    for typ in ["二买", "三买"]:
        sigs = picks.execute("SELECT symbol, signal_date FROM chanlun_signals "
                             "WHERE signal_date>=? AND signal_type=? ORDER BY symbol, signal_date",
                             (START, typ)).fetchall()
        rs = []
        for sym, sdate in sigs:
            bars = per.get(sym)
            if not bars or len(bars) < 30:
                continue
            d2i = {r[1]: i for i, r in enumerate(bars)}
            bi = d2i.get(sdate)
            if bi is None or bi + 2 >= len(bars):
                continue
            buy_i = bi + 2  # 信号T+1确认, T+2开盘买入(标准口径)
            buy_p = bars[buy_i][2] * (bars[buy_i][4] / bars[buy_i][3])
            if buy_p <= 0:
                continue
            sold = None
            for sd in sell_sigs.get(sym, []):
                si = d2i.get(sd)
                if si is not None and si > buy_i:
                    sold = bars[si + 1][4] / buy_p - 1  # 标准口径
                    break
            if sold is None:
                if buy_i + 60 >= len(bars):
                    continue
                sold = bars[buy_i + 60][4] / buy_p - 1
            rs.append(sold)
        stat(f"{typ}(单独)", rs)

    seq.close()
    picks.close()


if __name__ == "__main__":
    main()

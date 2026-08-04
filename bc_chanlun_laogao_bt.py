#!/usr/bin/env python3
"""缠论买点 + 老高底部确认 结合回测
组A: 全部缠论买点(ok, 滚动版) — 基线
组B: 缠论买点 ∩ 老高worth窗口(信号日T ∈ [老高确认日W, W+10])
规则: T+2开盘买 | T+10/T+20/止盈8/5/对称卖点"""
import sqlite3

PICKS_DB = "/home/ubuntu/databases/trend_picks.db"
SEQ_DB = "/home/ubuntu/Sequoia-X-a/data/sequoia_v2.db"
HOLD10, HOLD20 = 10, 20
TP, SL = 1.08, 0.95
WINDOW = 10  # 老高确认后N天内出现缠论买点


def main():
    picks = sqlite3.connect(PICKS_DB)
    seq = sqlite3.connect(SEQ_DB)
    # 老高worth: {symbol: [确认日期...]}
    lg = {}
    for r in picks.execute("SELECT date, symbol FROM bottom_confirm_picks WHERE status='worth'").fetchall():
        lg.setdefault(r[1], []).append(r[0])
    # 缠论买点(ok)
    buys = picks.execute(
        "SELECT symbol, name, signal_type, signal_date, price FROM chanlun_signals "
        "WHERE status='ok' AND signal_type LIKE '%买%' ORDER BY signal_date").fetchall()
    print(f"缠论买点: {len(buys)}条 | 老高worth股票: {len(lg)}只")

    # 老高worth日期集合(用于查窗口)
    import datetime
    def within_lg_win(sym, sdate):
        for w in lg.get(sym, []):
            d0 = datetime.date.fromisoformat(w)
            d1 = datetime.date.fromisoformat(sdate)
            if 0 <= (d1 - d0).days <= WINDOW:
                return True
        return False

    cache = {}
    resA, resB = [], []
    for sym, name, typ, sdate, sprice in buys:
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
        c10 = qf[buy_i + HOLD10 - 1][4] if buy_i + HOLD10 - 1 < n else None
        c20 = qf[buy_i + HOLD20 - 1][4] if buy_i + HOLD20 - 1 < n else None
        r10 = c10 / buy_p - 1 if c10 else None
        r20 = c20 / buy_p - 1 if c20 else None
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
        rsym = None
        for sd in sell_dates(sym, sdate, picks):
            si = d2i.get(sd)
            if si is not None and si + 1 < n and si + 1 > buy_i:
                rsym = qf[si + 1][4] / buy_p - 1
                break
        if rsym is None:
            c60 = qf[buy_i + 59][4] if buy_i + 59 < n else None
            rsym = c60 / buy_p - 1 if c60 else None
        row = (sdate[:4], r10, r20, rtp, rsym)
        resA.append(row)
        if within_lg_win(sym, sdate):
            resB.append(row)

    print(f"\n===== 组A 全部缠论买点: n={len(resA)} =====")
    report(resA)
    print(f"\n===== 组B 缠论买点+老高确认(10天内): n={len(resB)} =====")
    report(resB)


_sell_cache = {}


def sell_dates(sym, sdate, picks):
    if sym not in _sell_cache:
        _sell_cache[sym] = sorted(sd for (t, sd) in picks.execute(
            "SELECT signal_type, signal_date FROM chanlun_signals "
            "WHERE symbol=? AND signal_type LIKE '%卖%' AND status='ok' AND signal_date>?",
            (sym, sdate)).fetchall())
    return _sell_cache[sym]


def report(arr):
    for rname, idx in [("T+10", 1), ("T+20", 2), ("止盈8/5", 3), ("对称卖点", 4)]:
        rs = [r[idx] for r in arr if r[idx] is not None]
        if not rs:
            print(f"  {rname}: 无数据")
            continue
        win = sum(1 for x in rs if x > 0) / len(rs) * 100
        print(f"  {rname}: n={len(rs)} 胜率{win:.1f}% 均收益{sum(rs)/len(rs)*100:+.2f}%")
    years = sorted(set(r[0] for r in arr))
    print("  分年(对称卖点): ", end="")
    for y in years:
        rs = [r[4] for r in arr if r[0] == y and r[4] is not None]
        if rs:
            win = sum(1 for x in rs if x > 0) / len(rs) * 100
            print(f"{y}:{len(rs)}条/{win:.0f}%/{sum(rs)/len(rs)*100:+.1f}% ", end="")
    print()


if __name__ == "__main__":
    main()

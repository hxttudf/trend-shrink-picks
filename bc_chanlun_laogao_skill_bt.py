#!/usr/bin/env python3
"""缠论买点 + 老高skill思想(7条件) 结合回测
老高条件(信号日检查):
  r1: cur > ma20 > ma60          均线多头
  r2: 2% <= 距ma20 <= 15%        回踩不追高
  r3: 量比 > 0.8                  无暴量
  r4: 底部盘整 >= 120天           长期底部
  r5: ma20 > ma20(5日前)          均线上翘
  r6: 近5天无放量大跌(<-3%且量>1.2x)
  r7: 近10天有放量大涨(>=3%且量>=1.5x)  启动迹象
组A: 全部缠论买点 | 组B: 全部7条 | 组C: 核心5条(r1,r2,r4,r5,r7)
规则: T+2开盘买 | T+10/T+20/止盈8/5/对称卖点"""
import sqlite3

PICKS_DB = "/home/ubuntu/databases/trend_picks.db"
SEQ_DB = "/home/ubuntu/Sequoia-X-a/data/sequoia_v2.db"
HOLD10, HOLD20 = 10, 20
TP, SL = 1.08, 0.95


def main():
    picks = sqlite3.connect(PICKS_DB)
    seq = sqlite3.connect(SEQ_DB)
    buys = picks.execute(
        "SELECT symbol, name, signal_type, signal_date, price FROM chanlun_signals "
        "WHERE status='ok' AND signal_type LIKE '%买%' ORDER BY signal_date").fetchall()
    print(f"缠论买点: {len(buys)}条", flush=True)

    cache = {}
    resA, resB, resC = [], [], []

    for bi, (sym, name, typ, sdate, sprice) in enumerate(buys):
        if sym not in cache:
            k = seq.execute(
                "SELECT date, open, high, low, close, close_qfq, volume FROM stock_daily "
                "WHERE symbol=? AND close_qfq>0 ORDER BY date", (sym,)).fetchall()
            if len(k) < 120:
                cache[sym] = None
                continue
            qf = [[r[0], r[1] * (r[5] / r[4]), r[2] * (r[5] / r[4]), r[3] * (r[5] / r[4]), r[5]] for r in k]
            cache[sym] = (qf, {r[0]: i for i, r in enumerate(k)}, len(k),
                          [r[4] for r in k], [r[6] for r in k])
        pc = cache[sym]
        if pc is None:
            continue
        qf, d2i, n, closes, vols = pc
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

        # 老高7条件(信号日, 按需计算O(250))
        conds = laogao_conds(closes, vols, idx)
        if conds is None:
            continue
        r1, r2, r3, r4, r5, r6, r7 = conds
        if r1 and r2 and r3 and r4 and r5 and r6 and r7:
            resB.append(row)
        if r1 and r2 and r4 and r5 and r7:
            resC.append(row)

        if (bi + 1) % 20000 == 0:
            print(f"  {bi+1}/{len(buys)} | A:{len(resA)} B:{len(resB)} C:{len(resC)}", flush=True)

    print(f"\n===== 组A 全部缠论买点: n={len(resA)} =====")
    report(resA)
    print(f"\n===== 组B 缠论+老高7条件全中: n={len(resB)} =====")
    report(resB)
    print(f"\n===== 组C 核心5条件(r1,r2,r4,r5,r7): n={len(resC)} =====")
    report(resC)


def precomp(k):
    n = len(k)
    closes = [r[4] for r in k]
    vols = [r[6] for r in k]
    qf = [[r[0], r[1] * (r[5] / r[4]), r[2] * (r[5] / r[4]), r[3] * (r[5] / r[4]), r[5]] for r in k]
    d2i = {r[0]: i for i, r in enumerate(k)}
    ma20 = [None] * n
    ma60 = [None] * n
    ma20_5 = [None] * n
    for i in range(n):
        if i >= 19:
            ma20[i] = sum(closes[i - 19:i + 1]) / 20
        if i >= 59:
            ma60[i] = sum(closes[i - 59:i + 1]) / 60
        if i >= 24:
            ma20_5[i] = sum(closes[i - 24:i - 4]) / 20
    # 量比: 当日量/前20日均量
    vr = [0.0] * n
    for i in range(n):
        if i >= 20:
            av = sum(vols[i - 20:i]) / 20
            vr[i] = vols[i] / av if av else 0
    # 底部天数: 近250日最低点距今
    bd = [0] * n
    for i in range(n):
        lo = min(closes[max(0, i - 249):i + 1])
        li = closes[max(0, i - 249):i + 1].index(lo) + max(0, i - 249)
        bd[i] = i - li
    # r6: 近5天无放量大跌 | r7: 近10天有放量大涨
    r6ok = [True] * n
    r7ok = [False] * n
    for i in range(1, n):
        chg = (closes[i] / closes[i - 1] - 1) * 100
        av20 = sum(vols[max(0, i - 20):i]) / min(20, i) if i > 0 else 1
        vratio = vols[i] / av20 if av20 else 1
        if chg < -3 and vratio > 1.2:
            r6ok[i] = False
    for i in range(1, n):
        chg = (closes[i] / closes[i - 1] - 1) * 100
        av20 = sum(vols[max(0, i - 20):i]) / min(20, i) if i > 0 else 1
        vratio = vols[i] / av20 if av20 else 1
        if chg >= 3 and vratio >= 1.5:
            for j in range(i, min(i + 10, n)):
                r7ok[j] = True
    return (qf, d2i, n, ma20, ma60, ma20_5, vr, bd, r6ok, r7ok)


def laogao_conds(closes, vols, i):
    """老高7条件(信号日i按需计算, O(250)): 返回(r1..r7)或None(数据不足)"""
    n = len(closes)
    if i < 60 or i < 20:
        return None
    cur = closes[i]
    ma20 = sum(closes[i - 19:i + 1]) / 20
    ma60 = sum(closes[i - 59:i + 1]) / 60
    ma20_5 = sum(closes[i - 24:i - 4]) / 20
    if ma60 <= 0:
        return None
    r1 = cur > ma20 > ma60
    dist = (cur - ma20) / ma20 * 100
    r2 = 2 <= dist <= 15
    av = sum(vols[i - 20:i]) / 20
    vr = vols[i] / av if av else 0
    r3 = vr > 0.8
    lo = min(closes[max(0, i - 249):i + 1])
    li = closes[max(0, i - 249):i + 1].index(lo) + max(0, i - 249)
    r4 = (i - li) >= 120
    r5 = ma20 > ma20_5
    r6 = True
    for k in range(1, 6):
        if i - k < 1:
            break
        chg = (closes[i - k] / closes[i - k - 1] - 1) * 100
        a = sum(vols[max(0, i - k - 20):i - k]) / min(20, i - k) if i - k > 0 else 1
        if chg < -3 and (vols[i - k] / a if a else 0) > 1.2:
            r6 = False
            break
    r7 = False
    for k in range(1, 11):
        if i - k < 1:
            break
        chg = (closes[i - k] / closes[i - k - 1] - 1) * 100
        a = sum(vols[max(0, i - k - 20):i - k]) / min(20, i - k) if i - k > 0 else 1
        if chg >= 3 and (vols[i - k] / a if a else 0) >= 1.5:
            r7 = True
            break
    return (r1, r2, r3, r4, r5, r6, r7)


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

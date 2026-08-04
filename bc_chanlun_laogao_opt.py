#!/usr/bin/env python3
"""缠论+老高思想 参数扫描优化
一次遍历102,133买点, 预计算条件向量, 评估20+组合变体
输出: 各组合的对称卖点胜率/收益 + T+10, 排序找最优"""
import sqlite3

PICKS_DB = "/home/ubuntu/databases/trend_picks.db"
SEQ_DB = "/home/ubuntu/Sequoia-X-a/data/sequoia_v2.db"
HOLD10 = 10
TP, SL = 1.08, 0.95


def main():
    picks = sqlite3.connect(PICKS_DB)
    seq = sqlite3.connect(SEQ_DB)
    buys = picks.execute(
        "SELECT symbol, signal_type, signal_date FROM chanlun_signals "
        "WHERE status='ok' AND signal_type LIKE '%买%' ORDER BY signal_date").fetchall()
    print(f"买点: {len(buys)}条", flush=True)

    cache = {}
    recs = []  # (year, typ, r10, rsym, rtp, r1,r2a,r2b,r4_60,r4_120,r4_180,r5,r7,r7s,r6, cur_ma20)
    for bi, (sym, typ, sdate) in enumerate(buys):
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
        r10 = c10 / buy_p - 1 if c10 else None
        rtp = None
        for i in range(buy_i, min(buy_i + 20, n)):
            if qf[i][2] >= buy_p * TP:
                rtp = TP - 1
                break
            if qf[i][3] <= buy_p * SL:
                rtp = SL - 1
                break
        if rtp is None:
            rtp = c10 / buy_p - 1 if c10 else None
        rsym = None
        for sd in sell_dates(sym, sdate, picks):
            si = d2i.get(sd)
            if si is not None and si + 1 < n and si + 1 > buy_i:
                rsym = qf[si + 1][4] / buy_p - 1
                break
        if rsym is None:
            c60 = qf[buy_i + 59][4] if buy_i + 59 < n else None
            rsym = c60 / buy_p - 1 if c60 else None
        # 条件向量
        i = idx
        cur = closes[i]
        ma20 = sum(closes[i - 19:i + 1]) / 20 if i >= 19 else None
        ma60 = sum(closes[i - 59:i + 1]) / 60 if i >= 59 else None
        ma20_5 = sum(closes[i - 24:i - 4]) / 20 if i >= 24 else None
        if None in (ma20, ma60, ma20_5) or ma60 <= 0:
            continue
        dist = (cur - ma20) / ma20 * 100
        lo = min(closes[max(0, i - 249):i + 1])
        li = closes[max(0, i - 249):i + 1].index(lo) + max(0, i - 249)
        bd = i - li
        r6 = True
        for k in range(1, 6):
            if i - k < 1:
                break
            chg = (closes[i - k] / closes[i - k - 1] - 1) * 100
            a = sum(vols[max(0, i - k - 20):i - k]) / min(20, i - k) if i - k > 0 else 1
            if chg < -3 and (vols[i - k] / a if a else 0) > 1.2:
                r6 = False
                break
        r7, r7s = False, False
        for k in range(1, 11):
            if i - k < 1:
                break
            chg = (closes[i - k] / closes[i - k - 1] - 1) * 100
            a = sum(vols[max(0, i - k - 20):i - k]) / min(20, i - k) if i - k > 0 else 1
            vrk = vols[i - k] / a if a else 0
            if chg >= 3 and vrk >= 1.5:
                r7 = True
            if chg >= 5 and vrk >= 2.0:
                r7s = True
        recs.append((sdate[:4], typ, r10, rsym, rtp,
                     cur > ma20 > ma60,          # r1
                     cur > ma20,                 # r1b 只站上ma20
                     2 <= dist <= 15,            # r2
                     0 <= dist <= 20,            # r2b 放宽
                     bd >= 60, bd >= 120, bd >= 180,  # r4变体
                     ma20 > ma20_5,              # r5
                     r7, r7s, r6, dist))
        if (bi + 1) % 20000 == 0:
            print(f"  {bi+1}/{len(buys)} recs={len(recs)}", flush=True)

    print(f"有效记录: {len(recs)}", flush=True)
    # 组合定义
    combos = {
        "A 全部":              lambda r: True,
        "C 核心5(基准)":        lambda r: r[5] and r[7] and r[10] and r[12] and r[13],
        "C2 无r5":             lambda r: r[5] and r[7] and r[10] and r[13],
        "C3 r2放宽":           lambda r: r[5] and r[8] and r[10] and r[12] and r[13],
        "C4 底部60":           lambda r: r[5] and r[7] and r[9] and r[12] and r[13],
        "C5 底部180":          lambda r: r[5] and r[7] and r[11] and r[12] and r[13],
        "C6 启动加强":          lambda r: r[5] and r[7] and r[10] and r[12] and r[14],
        "C7 r1只站ma20":       lambda r: r[6] and r[7] and r[10] and r[12] and r[13],
        "C8 加r6防御":          lambda r: r[5] and r[7] and r[10] and r[12] and r[13] and r[15],
        "C9 强势+回踩+启动":     lambda r: r[5] and r[7] and r[8] and r[13],
        "D1 三买+核心5":        lambda r: r[1] == '三买' and r[5] and r[7] and r[10] and r[12] and r[13],
        "D2 一买+核心5":        lambda r: r[1] == '一买' and r[5] and r[7] and r[10] and r[12] and r[13],
        "D3 二买+核心5":        lambda r: r[1] == '二买' and r[5] and r[7] and r[10] and r[12] and r[13],
        "D4 三买+强势回踩启动":   lambda r: r[1] == '三买' and r[5] and r[8] and r[13],
    }
    print(f"\n{'组合':<22}{'n':>6}{'对称胜率':>9}{'对称收益':>9}{'T+10胜率':>9}{'T+10收益':>9}")
    results = []
    for cname, fn in combos.items():
        arr = [r for r in recs if fn(r)]
        if len(arr) < 50:
            results.append((cname, len(arr), None, None, None, None))
            continue
        rs = [r[3] for r in arr if r[3] is not None]
        r10s = [r[2] for r in arr if r[2] is not None]
        w1 = sum(1 for x in rs if x > 0) / len(rs) * 100
        m1 = sum(rs) / len(rs) * 100
        w2 = sum(1 for x in r10s if x > 0) / len(r10s) * 100
        m2 = sum(r10s) / len(r10s) * 100
        results.append((cname, len(arr), w1, m1, w2, m2))
    for cname, n, w1, m1, w2, m2 in sorted(results, key=lambda x: (x[2] or 0) + (x[3] or 0) / 10, reverse=True):
        if w1 is None:
            print(f"{cname:<22}{n:>6}  样本不足")
        else:
            print(f"{cname:<22}{n:>6}{w1:>8.1f}%{m1:>+8.2f}%{w2:>8.1f}%{m2:>+8.2f}%")


_sell_cache = {}


def sell_dates(sym, sdate, picks):
    if sym not in _sell_cache:
        _sell_cache[sym] = sorted(sd for (t, sd) in picks.execute(
            "SELECT signal_type, signal_date FROM chanlun_signals "
            "WHERE symbol=? AND signal_type LIKE '%卖%' AND status='ok' AND signal_date>?",
            (sym, sdate)).fetchall())
    return _sell_cache[sym]


if __name__ == "__main__":
    main()

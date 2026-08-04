#!/usr/bin/env python3
"""底部确认每日增量更新
1. 对最新交易日全市场算 score(复用bc_build_scores评分) + streak(往前30自然日每5日一点)
2. worth判定: 80<=score<=88 AND bottom>=90 AND 20<=drop<=65
   watch判定: s65>=4 AND score>=65 AND 非worth
3. 写 bc_scores2.db scores表 + trend_picks.db bottom_confirm_picks
用法: python3 bc_daily_bottom.py [YYYY-MM-DD]  (缺省=最新交易日)
stdout输出当日worth/watch摘要"""
import sqlite3, sys, time
import numpy as np

SEQ_DB = "/home/ubuntu/Sequoia-X-a/data/sequoia_v2.db"
SCORES_DB = "/home/ubuntu/trend-shrink-picks/bc_scores2.db"
TREND_DB = "/home/ubuntu/databases/trend_picks.db"
BATCH = 400


def load_batch(conn, symbols):
    out = {}
    for sym in symbols:
        rows = conn.execute(
            "SELECT date, open, high, low, close, close_qfq, volume "
            "FROM stock_daily WHERE symbol=? AND close_qfq>0 AND date>='2018-01-01' ORDER BY date",
            (sym,)).fetchall()
        if len(rows) < 300:
            continue
        arr = []
        for d, o, h, l, c, cq, v in rows:
            ratio = (cq / c) if (c and c > 0) else 1.0
            arr.append((int(d.replace("-", "")), o * ratio, h * ratio, l * ratio, cq, v))
        a = np.array(arr, dtype=np.float64)
        nrow = conn.execute(
            "SELECT name FROM stock_basics WHERE symbol=? ORDER BY date DESC LIMIT 1", (sym,)).fetchone()
        is_st = 'ST' in (nrow[0] if nrow else sym)
        out[sym] = (a[:, 0].astype(np.int64), a[:, 1:5], a[:, 5], is_st)
    return out


def score_at(closes, ohlc, vols, t):
    """完整版评分, 返回 (score, drop_pct, bottom_days, vol_shrink, cur, ma20, ma60, bounce_pct) 或 None"""
    if t < 250:
        return None
    w_c = closes[t - 249:t + 1]
    w_o = ohlc[t - 249:t + 1, 0]
    w_v = vols[t - 249:t + 1]
    cur = w_c[-1]
    if cur < 1.0:
        return None
    high_250 = w_c.max()
    hi = w_c.argmax()
    if hi >= len(w_c) - 20:
        return None
    drop_pct = (cur / high_250 - 1) * 100
    after = w_c[hi:]
    low = after.min()
    li = after.argmin()
    bottom_days = int(len(after) - 1 - li)
    bounce_pct = (cur / low - 1) * 100
    ma10 = w_c[-10:].mean()
    ma20 = w_c[-20:].mean()
    ma60 = w_c[-60:].mean()
    bottom_vol = w_v[-20:].mean()
    ds = max(0, hi - 20)
    decline_vol = w_v[ds:ds + 20].mean() if ds + 20 <= len(w_v) else bottom_vol
    vol_shrink = bottom_vol / decline_vol if decline_vol > 0 else 1.0
    launch = False
    for i in range(1, 21):
        prev_c = w_c[-i - 1]
        chg = (w_c[-i] / prev_c - 1) * 100 if prev_c else 0
        if w_c[-i] > w_o[-i] and chg >= 3:
            v5 = w_v[-i - 5:-i].mean() if i >= 5 else w_v[-i:].mean()
            if v5 > 0 and w_v[-i] / v5 >= 1.5:
                launch = True
                break
    score = 0
    d = abs(drop_pct)
    if 20 <= d <= 65: score += 20
    elif 15 <= d < 20: score += 14
    elif 65 < d <= 80: score += 10
    elif 10 <= d < 15: score += 8
    else: score += 3
    if bottom_days >= 120: score += 20
    elif bottom_days >= 60: score += 15
    elif bottom_days >= 30: score += 8
    elif bottom_days >= 15: score += 2
    if vol_shrink < 0.5: score += 20
    elif vol_shrink < 0.7: score += 14
    elif vol_shrink < 1.0: score += 7
    else: score += 2
    if launch: score += 20
    elif cur > ma20: score += 8
    if cur > ma20: score += 10
    elif cur > ma10: score += 5
    if 5 <= bounce_pct <= 40: score += 10
    elif 0 <= bounce_pct < 5: score += 5
    elif 40 < bounce_pct <= 60: score += 5
    elif bounce_pct > 60: score += 2
    if cur <= ma20:
        return None
    return (score, round(drop_pct, 2), bottom_days, round(vol_shrink, 3), round(cur, 3), round(ma20, 3), round(ma60, 3), round(bounce_pct, 2))


def main():
    t0 = time.time()
    conn = sqlite3.connect(SEQ_DB)
    ref = conn.execute(
        "SELECT date FROM stock_daily WHERE symbol='000001.SH' AND close_qfq>0 ORDER BY date").fetchall()
    all_dates = [r[0].replace("-", "") for r in ref]
    if len(sys.argv) > 1:
        target = sys.argv[1].replace("-", "")
        if target not in all_dates:
            print(f"目标日 {target} 不在交易日历")
            return
    else:
        # 个股最新交易日(指数000001.SH可能滞后)
        tgt_row = conn.execute(
            "SELECT MAX(date) FROM stock_daily WHERE symbol NOT LIKE '%.SH' AND close_qfq>0").fetchone()
        target = tgt_row[0].replace("-", "") if tgt_row and tgt_row[0] else all_dates[-1]
    # 已算过?
    sc = sqlite3.connect(SCORES_DB)
    has = sc.execute("SELECT COUNT(*) FROM scores WHERE bt_date=?", (int(target),)).fetchone()[0]
    if has > 0:
        print(f"目标日 {target} scores已存在({has}条), 跳过评分")
    # 最新交易日(不含target) 用于streak的"s65参照"不需要 — streak用内存重算

    symbols = [r[0] for r in conn.execute(
        "SELECT DISTINCT symbol FROM stock_daily WHERE close_qfq>0 AND date>='2018-01-01'")]
    print(f"全市场 {len(symbols)} 只 | 目标日 {target}", flush=True)

    new_rows = []  # scores行
    worth_rows = []  # bottom_confirm worth
    watch_rows = []
    names = {}
    for b in range(0, len(symbols), BATCH):
        data = load_batch(conn, symbols[b:b + BATCH])
        for sym, (dates, ohlc, vols, is_st) in data.items():
            closes = ohlc[:, 3]
            pos = np.searchsorted(dates, int(target))
            if pos < len(dates) and dates[pos] == int(target):
                di = pos
            elif pos > 0:
                di = pos - 1
            else:
                continue
            if di < 250:
                continue
            r = score_at(closes, ohlc, vols, di)
            if r is None:
                continue
            score, drop, bd_days, vs, cur, ma20, ma60, bounce = r
            # streak: 往前30自然日每5日一点, 各阈值连续
            streaks = {th: 0 for th in [50, 55, 60, 65, 70]}
            for k in range(0, 31, 5):
                q = score_at(closes, ohlc, vols, di - k)
                if q is None:
                    continue
                for th in streaks:
                    if q[0] >= th:
                        streaks[th] += 1
            new_rows.append((int(target), sym, round(score, 2), streaks[50], streaks[55], streaks[60],
                             streaks[65], streaks[70], drop, bd_days, vs, round(cur, 3), round(ma20, 3),
                             round(ma60, 3), bounce, 1 if is_st else 0))
            if is_st:
                continue
            nm = conn.execute("SELECT name FROM stock_basics WHERE symbol=? ORDER BY date DESC LIMIT 1",
                              (sym,)).fetchone()
            nm = nm[0] if nm else sym
            names[sym] = nm
            if 80 <= score <= 88 and bd_days >= 90 and 20 <= abs(drop) <= 65 and streaks[65] >= 4:
                worth_rows.append((target, sym, nm, score, drop, bd_days, vs, streaks[65], cur, ma20, ma60))
            elif streaks[65] >= 4 and score >= 65:
                watch_rows.append((target, sym, nm, score, drop, bd_days, vs, streaks[65], cur, ma20, ma60))
        if (b // BATCH) % 2 == 0:
            print(f"  批{b//BATCH+1}: {time.time()-t0:.0f}s", flush=True)

    # 写scores
    if new_rows:
        sc.executemany("INSERT OR REPLACE INTO scores (bt_date, symbol, score, s50, s55, s60, s65, s70, "
                       "drop_pct, bottom_days, vol_shrink, cur, ma20, ma60, bounce, is_st) "
                       "VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)", new_rows)
        sc.commit()
        print(f"scores写入: {len(new_rows)}条")
    sc.close()

    # 写bottom_confirm_picks
    tp = sqlite3.connect(TREND_DB)
    for st, rows in [("worth", worth_rows), ("watch", watch_rows)]:
        for r in rows:
            tgt, sym, nm, score, drop, bd_days, vs, streak, cur, ma20, ma60 = r
            tp.execute(
                "INSERT OR REPLACE INTO bottom_confirm_picks "
                "(date, symbol, name, status, score, stage, drop_pct, bottom_days, vol_shrink, streak, close_qfq, ma20, ma60, created_at) "
                "VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,datetime('now'))",
                (tgt[:4] + "-" + tgt[4:6] + "-" + tgt[6:], sym, nm, st, score, "底部确认",
                 drop, bd_days, vs, streak, cur, ma20, ma60))
    tp.commit()
    nw, nw2 = len(worth_rows), len(watch_rows)
    tp.close()
    conn.close()
    print(f"\n✅ {target}: worth {nw}只 / watch {nw2}只 | 总耗时{time.time()-t0:.0f}s")
    for r in worth_rows:
        print(f"  WORTH {r[0][:4]}-{r[0][4:6]}-{r[0][6:]} {r[1]} {r[2]} score={r[3]}")


if __name__ == "__main__":
    main()

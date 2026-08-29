#!/usr/bin/env python3
"""
底部确认策略 — 评分数据库构建(无未来函数)
一次性扫描全市场, 保存每只股票每个回测日的:
  score(完整评分) streak(往前30自然日完整评分>=60连续期数, 无未来函数)
  drop_pct / bottom_days / vol_shrink / cur / ma20 / ma60 / is_st
→ bc_scores2.db, 供参数扫描快速过滤
"""
import sqlite3, time
import numpy as np

DB = "/home/ubuntu/Sequoia-X-a/data/sequoia_v2.db"
OUT = "/home/ubuntu/trend-shrink-picks/bc_scores2.db"
BATCH = 400

def load_batch(conn, symbols):
    out = {}
    for sym in symbols:
        rows = conn.execute(
            "SELECT date, open, high, low, close, close_qfq, volume "
            "FROM stock_daily WHERE symbol=? AND close_qfq>0 AND date>='2018-01-01' ORDER BY date",
            (sym,)
        ).fetchall()
        if len(rows) < 300:
            continue
        arr = []
        for d, o, h, l, c, cq, v in rows:
            ratio = (cq / c) if (c and c > 0) else 1.0
            arr.append((int(d.replace("-", "")), o*ratio, h*ratio, l*ratio, cq, v))
        a = np.array(arr, dtype=np.float64)
        nrow = conn.execute(
            "SELECT name FROM stock_basics WHERE symbol=? ORDER BY date DESC LIMIT 1", (sym,)
        ).fetchone()
        is_st = 'ST' in (nrow[0] if nrow else sym)
        out[sym] = (a[:, 0].astype(np.int64), a[:, 1:5], a[:, 5], is_st)
    return out

def score_at(closes, ohlc, vols, t):
    """完整版评分, 返回 (score, drop_pct, bottom_days, vol_shrink, cur, ma20, ma60, bounce_pct) 或 None"""
    if t < 250:
        return None
    w_c = closes[t-249:t+1]
    w_o = ohlc[t-249:t+1, 0]
    w_v = vols[t-249:t+1]
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
    decline_vol = w_v[ds:ds+20].mean() if ds + 20 <= len(w_v) else bottom_vol
    vol_shrink = bottom_vol / decline_vol if decline_vol > 0 else 1.0
    launch = False
    for i in range(1, 21):
        prev_c = w_c[-i-1]
        chg = (w_c[-i] / prev_c - 1) * 100 if prev_c else 0
        if w_c[-i] > w_o[-i] and chg >= 3:
            v5 = w_v[-i-5:-i].mean() if i >= 5 else w_v[-i:].mean()
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
    conn = sqlite3.connect(DB)
    ref = conn.execute(
        "SELECT date FROM stock_daily WHERE symbol='000001.SH' AND close_qfq>0 ORDER BY date"
    ).fetchall()
    all_dates = [int(r[0].replace("-", "")) for r in ref]
    bt_dates = all_dates[300::5]
    print(f"回测区间: {bt_dates[0]} ~ {bt_dates[-1]}, {len(bt_dates)}个回测日", flush=True)

    symbols = [r[0] for r in conn.execute(
        "SELECT DISTINCT symbol FROM stock_daily WHERE close_qfq>0 AND date>='2018-01-01' AND symbol NOT LIKE '%.%'"
    )]
    print(f"全市场 {len(symbols)} 只", flush=True)

    out_conn = sqlite3.connect(OUT)
    out_conn.execute("DROP TABLE IF EXISTS scores")
    out_conn.execute("""CREATE TABLE scores(
        bt_date INTEGER, symbol TEXT, score REAL, streak INTEGER,
        s50 INTEGER, s55 INTEGER, s60 INTEGER, s65 INTEGER, s70 INTEGER,
        drop_pct REAL, bottom_days INTEGER, vol_shrink REAL,
        cur REAL, ma20 REAL, ma60 REAL, bounce REAL, is_st INTEGER)""")
    out_conn.execute("CREATE INDEX idx_bd ON scores(bt_date)")
    out_conn.execute("CREATE INDEX idx_sym ON scores(symbol)")

    total = 0
    for b in range(0, len(symbols), BATCH):
        data = load_batch(conn, symbols[b:b+BATCH])
        rows = []
        for sym, (dates, ohlc, vols, is_st) in data.items():
            closes = ohlc[:, 3]
            for bd in bt_dates:
                pos = np.searchsorted(dates, bd)
                if pos < len(dates) and dates[pos] == bd:
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
                # 多阈值连续期数(往前30自然日, 每5日一点)
                streaks = {th: 0 for th in [50, 55, 60, 65, 70]}
                for k in range(0, 31, 5):
                    q = score_at(closes, ohlc, vols, di - k)
                    if q is None:
                        break
                    qs = q[0]
                    for th in list(streaks):
                        if qs >= th:
                            streaks[th] += 1
                        else:
                            del streaks[th]
                    if not streaks:
                        break
                rows.append((bd, sym, score,
                             streaks.get(60, 0), streaks.get(50, 0), streaks.get(55, 0),
                             streaks.get(60, 0), streaks.get(65, 0), streaks.get(70, 0),
                             drop, bd_days, vs, cur, ma20, ma60, bounce, int(is_st)))
        out_conn.executemany("INSERT INTO scores VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)", rows)
        out_conn.commit()
        total += len(rows)
        del data
        print(f"  批次 {b//BATCH+1}/{(len(symbols)+BATCH-1)//BATCH} 累计{total}条 ({time.time()-t0:.0f}s)", flush=True)
    out_conn.close()
    conn.close()
    print(f"完成: {total}条评分记录 ({time.time()-t0:.0f}s)", flush=True)

if __name__ == "__main__":
    main()

#!/usr/bin/env python3
"""
底部确认框架选股策略回测 (低内存版)
阶段1: 分批加载股票(每批400只), 计算全部回测日评分 → 写入bt_scores.db
阶段2: 每回测日取Top10, 按需查询未来收益, 统计胜率
内存峰值 < 300MB
"""
import sqlite3, time, os
import numpy as np

DB = "/home/ubuntu/Sequoia-X-a/data/sequoia_v2.db"
SCORES_DB = "/home/ubuntu/trend-shrink-picks/bt_scores.db"
BATCH = 400
TOP_N = 10
STEP = 5

def load_batch(conn, symbols):
    """加载一批股票数据: {sym: (dates_int, ohlc, vols)} 全部前复权"""
    out = {}
    for sym in symbols:
        rows = conn.execute(
            "SELECT date, open, high, low, close, close_qfq, volume "
            "FROM stock_daily WHERE symbol=? AND close_qfq>0 AND date>='2023-06-01' "
            "ORDER BY date", (sym,)
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

def score_at(closes, ohlc, vols, t, is_st):
    if t < 250:
        return None
    w_c = closes[t-249:t+1]
    w_o = ohlc[t-249:t+1, 0]
    w_h = ohlc[t-249:t+1, 1]
    w_l = ohlc[t-249:t+1, 2]
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
    bottom_days = len(after) - 1 - li
    bounce_pct = (cur / low - 1) * 100
    
    ma5 = w_c[-5:].mean()
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
    
    is_ow = False
    prev_c = w_c[-2]
    if prev_c > 0:
        chg = (cur / prev_c - 1) * 100
        amp = (w_h[-1] - w_l[-1]) / prev_c * 100
        th = 4.0 if is_st else 9.0
        if chg > th and amp < 0.5:
            is_ow = True
    
    if cur <= ma20:
        return None
    return score, is_ow

def main():
    t0 = time.time()
    conn = sqlite3.connect(DB)
    
    # 回测日历
    ref = conn.execute(
        "SELECT date FROM stock_daily WHERE symbol='000001.SH' AND close_qfq>0 ORDER BY date"
    ).fetchall()
    all_dates = [int(r[0].replace("-", "")) for r in ref]
    bt_dates = all_dates[300::STEP]
    print(f"回测区间: {bt_dates[0]} ~ {bt_dates[-1]}, {len(bt_dates)}个回测日", flush=True)
    
    # 阶段1: 分批评分
    if os.path.exists(SCORES_DB):
        os.remove(SCORES_DB)
    btdb = sqlite3.connect(SCORES_DB)
    btdb.execute("CREATE TABLE scores (bt_date INTEGER, symbol TEXT, score REAL, is_oneword INT)")
    btdb.execute("CREATE INDEX idx_bt ON scores(bt_date, score DESC)")
    
    symbols = [r[0] for r in conn.execute(
        "SELECT DISTINCT symbol FROM stock_daily WHERE close_qfq>0 AND date>='2023-06-01'"
    )]
    print(f"全市场 {len(symbols)} 只, 分批加载(每批{BATCH})...", flush=True)
    
    total_scores = 0
    for b in range(0, len(symbols), BATCH):
        batch = symbols[b:b+BATCH]
        data = load_batch(conn, batch)
        for sym, (dates, ohlc, vols, is_st) in data.items():
            closes = ohlc[:, 3]
            for bd in bt_dates:
                # searchsorted返回第一个>=bd的位置; 若命中bd则用bd, 否则用前一个交易日
                pos = np.searchsorted(dates, bd)
                if pos < len(dates) and dates[pos] == bd:
                    di = pos
                elif pos > 0:
                    di = pos - 1
                else:
                    continue
                if di < 250:
                    continue
                r = score_at(closes, ohlc, vols, di, is_st)
                if r:
                    btdb.execute(
                        "INSERT INTO scores VALUES (?,?,?,?)",
                        (bd, sym, r[0], 1 if r[1] else 0)
                    )
                    total_scores += 1
        btdb.commit()
        del data
        print(f"  批次 {b//BATCH+1}/{(len(symbols)+BATCH-1)//BATCH} 完成, 累计信号{total_scores} ({time.time()-t0:.0f}s)", flush=True)
    
    # 阶段2: 取Top + 算收益
    print(f"\n阶段2: 计算收益...", flush=True)
    signals = []
    for bd in bt_dates:
        bd_str = f"{bd//10000}-{bd%10000//100:02d}-{bd%100:02d}"
        top = btdb.execute(
            "SELECT symbol, score, is_oneword FROM scores WHERE bt_date=? ORDER BY score DESC LIMIT ?",
            (bd, TOP_N)
        ).fetchall()
        for sym, score, is_ow in top:
            fut = conn.execute(
                "SELECT close_qfq FROM stock_daily WHERE symbol=? AND close_qfq>0 AND date>? "
                "ORDER BY date LIMIT 20",
                (sym, bd_str)
            ).fetchall()
            cur = conn.execute(
                "SELECT close_qfq FROM stock_daily WHERE symbol=? AND date=? AND close_qfq>0",
                (sym, bd_str)
            ).fetchone()
            if not cur:
                continue
            base = cur[0]
            rets = {}
            for h in [1, 5, 10, 20]:
                if len(fut) >= h:
                    rets[h] = (fut[h-1][0] / base - 1) * 100
                else:
                    rets[h] = None
            signals.append((bd_str, sym, score, rets, bool(is_ow)))
    
    btdb.close()
    conn.close()
    print(f"总信号数: {len(signals)}  总用时{time.time()-t0:.0f}s", flush=True)
    print()
    
    def stat(group, label):
        if not group:
            print(f"  {label}: 无信号"); return
        print(f"  {label} (n={len(group)}):")
        for h in [1, 5, 10, 20]:
            vals = [s[3][h] for s in group if s[3].get(h) is not None]
            if not vals: continue
            wins = sum(1 for v in vals if v > 0)
            avg = sum(vals) / len(vals)
            med = sorted(vals)[len(vals)//2]
            print(f"    T+{h:>2}: 胜率{wins/len(vals)*100:5.1f}% 均收{avg:+6.2f}% 中位{med:+6.2f}%")
    
    print("="*62)
    print("📊 全部信号 (含一字板, 理论上限)")
    print("="*62)
    stat(signals, "全部")
    
    non_ow = [s for s in signals if not s[4]]
    print("\n" + "="*62)
    print("🎯 真实可交易 (排除一字板)")
    print("="*62)
    stat(non_ow, "排除一字板")
    
    for yr in ['2024', '2025', '2026']:
        g = [s for s in non_ow if s[0].startswith(yr)]
        print(f"\n  --- {yr}年 ---")
        stat(g, yr)
    
    print("\n" + "="*62)
    print("📈 分数分层 (排除一字板)")
    print("="*62)
    stat([s for s in non_ow if s[2] >= 85], ">=85分")
    stat([s for s in non_ow if 75 <= s[2] < 85], "75-84分")
    stat([s for s in non_ow if s[2] < 75], "<75分")

if __name__ == "__main__":
    main()

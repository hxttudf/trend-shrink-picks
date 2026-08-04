#!/usr/bin/env python3
"""
底部确认策略 — 口径对比回测
口径A(原回测): 每回测日 Top20高分内 streak>=4, 取Top15, 非ST
口径B(daily脚本): 全市场 score>=75 且 streak>=4(简化评分连续期数), 无数量上限, 非ST
对比: 信号数 / T+5,T+10,T+20 胜率+均收 / 分年度
"""
import sqlite3, time
import numpy as np

DB = "/home/ubuntu/Sequoia-X-a/data/sequoia_v2.db"
BATCH = 400
TOP_N = 15

def load_batch(conn, symbols):
    out = {}
    for sym in symbols:
        rows = conn.execute(
            "SELECT date, open, high, low, close, close_qfq, volume "
            "FROM stock_daily WHERE symbol=? AND close_qfq>0 AND date>='2023-06-01' ORDER BY date",
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

def score_at(closes, ohlc, vols, t, is_st):
    """完整版评分(100分制, 含启动信号) — 与原回测一致"""
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
    ma5 = w_c[-5:].mean(); ma10 = w_c[-10:].mean()
    ma20 = w_c[-20:].mean(); ma60 = w_c[-60:].mean()
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
    return score

def quick_score_at(closes, ohlc, vols, t):
    """简化版评分(无启动信号, 最高80分) — daily脚本streak口径"""
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
    dp = (cur / high_250 - 1) * 100
    after = w_c[hi:]
    low = after.min()
    li = after.argmin()
    bd = len(after) - 1 - li
    bp = (cur / low - 1) * 100
    m20 = w_c[-20:].mean()
    m5 = w_c[-5:].mean()
    bv = w_v[-20:].mean()
    ds = max(0, hi - 20)
    dv = w_v[ds:ds+20].mean() if ds + 20 <= len(w_v) else bv
    vs = bv / dv if dv > 0 else 1.0
    s = 0
    d = abs(dp)
    if 20 <= d <= 65: s += 20
    elif 15 <= d < 20: s += 14
    elif 65 < d <= 80: s += 10
    elif 10 <= d < 15: s += 8
    else: s += 3
    if bd >= 120: s += 20
    elif bd >= 60: s += 15
    elif bd >= 30: s += 8
    elif bd >= 15: s += 2
    if vs < 0.5: s += 20
    elif vs < 0.7: s += 14
    elif vs < 1.0: s += 7
    else: s += 2
    if cur > m20: s += 10
    elif cur > m5: s += 5
    if 5 <= bp <= 40: s += 10
    elif 0 <= bp < 5: s += 5
    elif 40 < bp <= 60: s += 5
    elif bp > 60: s += 2
    return s

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
        "SELECT DISTINCT symbol FROM stock_daily WHERE close_qfq>0 AND date>='2023-06-01'"
    )]
    print(f"全市场 {len(symbols)} 只", flush=True)

    sigA, sigB = [], []  # (bd, sym, score, streak) — 确认池
    all_scores = {}      # bd -> [(sym, score, streak)] — 全部评分(含streak)
    for b in range(0, len(symbols), BATCH):
        data = load_batch(conn, symbols[b:b+BATCH])
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
                score = score_at(closes, ohlc, vols, di, is_st)
                if score is None:
                    continue
                # streak: 完整版评分>=60 连续期数(每5日) — 与回测consec口径一致
                streak = 0
                for k in range(0, 31, 5):
                    q = score_at(closes, ohlc, vols, di - k, is_st)
                    if q is not None and q >= 60:
                        streak += 1
                    else:
                        break
                if is_st:
                    continue
                all_scores.setdefault(bd, []).append((sym, score, streak))
                if streak >= 4:
                    sigA.append((bd, sym, score, streak))
                    if score >= 75:
                        sigB.append((bd, sym, score, streak))
        del data
        print(f"  批次 {b//BATCH+1}/{(len(symbols)+BATCH-1)//BATCH} ({time.time()-t0:.0f}s)", flush=True)
    print(f"评分完成: A候选{len(sigA)}, B候选{len(sigB)} ({time.time()-t0:.0f}s)", flush=True)

    # 组装每日信号
    def build(sig_pool, mode):
        """mode='A': 确认池内每日Top15; 'B': 全部; 'C': 当日全市场评分Top20∩确认>=4"""
        if mode == 'C':
            out = []
            for bd, items in all_scores.items():
                items.sort(key=lambda x: -x[1])
                top20 = items[:20]
                bd_str = f"{bd//10000}-{bd%10000//100:02d}-{bd%100:02d}"
                for sym, score, streak in top20:
                    if streak < 4:
                        continue
                    fut = conn.execute(
                        "SELECT close_qfq FROM stock_daily WHERE symbol=? AND close_qfq>0 AND date>? "
                        "ORDER BY date LIMIT 20", (sym, bd_str)
                    ).fetchall()
                    cur = conn.execute(
                        "SELECT close_qfq FROM stock_daily WHERE symbol=? AND date=? AND close_qfq>0",
                        (sym, bd_str)
                    ).fetchone()
                    if not cur:
                        continue
                    base = cur[0]
                    rets = {}
                    for h in [5, 10, 20]:
                        rets[h] = (fut[h-1][0]/base - 1)*100 if len(fut) >= h else None
                    out.append((bd_str, sym, score, rets))
            return out
        by_date = {}
        for bd, sym, score, streak in sig_pool:
            by_date.setdefault(bd, []).append((sym, score, streak))
        out = []
        for bd, items in by_date.items():
            items.sort(key=lambda x: -x[1])
            if mode == 'A':
                items = items[:TOP_N]
            bd_str = f"{bd//10000}-{bd%10000//100:02d}-{bd%100:02d}"
            for sym, score, streak in items:
                fut = conn.execute(
                    "SELECT close_qfq FROM stock_daily WHERE symbol=? AND close_qfq>0 AND date>? "
                    "ORDER BY date LIMIT 20", (sym, bd_str)
                ).fetchall()
                cur = conn.execute(
                    "SELECT close_qfq FROM stock_daily WHERE symbol=? AND date=? AND close_qfq>0",
                    (sym, bd_str)
                ).fetchone()
                if not cur:
                    continue
                base = cur[0]
                rets = {}
                for h in [5, 10, 20]:
                    rets[h] = (fut[h-1][0]/base - 1)*100 if len(fut) >= h else None
                out.append((bd_str, sym, score, rets))
        return out

    print("组装口径A(原回测: Top15)...", flush=True)
    sigA_full = build(sigA, 'A')
    print("组装口径B(daily: score>=75无上限)...", flush=True)
    sigB_full = build(sigB, 'B')
    print("组装口径C(当日全市场评分Top20∩确认>=4)...", flush=True)
    sigC_full = build([], 'C')
    conn.close()

    def stat(group, label):
        if not group:
            print(f"  {label}: 无信号"); return
        print(f"  {label} (n={len(group)}):")
        for h in [5, 10, 20]:
            vals = [s[3][h] for s in group if s[3].get(h) is not None]
            if not vals: continue
            wins = sum(1 for v in vals if v > 0)
            avg = sum(vals)/len(vals)
            med = sorted(vals)[len(vals)//2]
            print(f"    T+{h:>2}: 胜率{wins/len(vals)*100:5.1f}% 均收{avg:+6.2f}% 中位{med:+6.2f}%")

    print("\n" + "="*60)
    print("口径A: 原回测 (每回测日Top15高分内streak>=4)")
    print("="*60)
    stat(sigA_full, "全部")
    for yr in ['2024', '2025', '2026']:
        stat([s for s in sigA_full if s[0].startswith(yr)], yr)

    print("\n" + "="*60)
    print("口径B: daily脚本 (全市场 score>=75 + streak>=4, 无上限)")
    print("="*60)
    stat(sigB_full, "全部")
    for yr in ['2024', '2025', '2026']:
        stat([s for s in sigB_full if s[0].startswith(yr)], yr)

    print("\n" + "="*60)
    print("口径C: 当日全市场评分Top20 ∩ 确认>=4 (网格搜索口径)")
    print("="*60)
    stat(sigC_full, "全部")
    for yr in ['2024', '2025', '2026']:
        stat([s for s in sigC_full if s[0].startswith(yr)], yr)

    print(f"\n总用时 {time.time()-t0:.0f}s")

if __name__ == "__main__":
    main()

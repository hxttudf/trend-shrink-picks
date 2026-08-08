#!/usr/bin/env python3
"""一买胜率/收益统计 — 同口径(T+2开盘买入, 10/20日), 按当前一买分数(深跌公式)分组"""
import sqlite3, numpy as np, time

t0 = time.time()
seq = sqlite3.connect("/home/ubuntu/Sequoia-X-a/data/sequoia_v2.db")
picks = sqlite3.connect("/home/ubuntu/databases/trend_picks.db")

sigs = picks.execute(
    "SELECT symbol, signal_date, price FROM chanlun_signals "
    "WHERE signal_type='一买' AND status='ok' AND price>0 AND signal_date>='2021-01-01'").fetchall()
print(f"一买信号: {len(sigs)}")

def open_qfq(r):
    return r[2] * r[6] / r[5] if r[5] else r[2]

def calc(sym, date):
    rows = seq.execute(
        "SELECT symbol, date, open, high, low, close, close_qfq, volume FROM stock_daily "
        "WHERE symbol=? AND close_qfq>0 ORDER BY date", (sym,)).fetchall()
    if not rows:
        return None
    dates = [r[1] for r in rows]
    try:
        i = dates.index(date)
    except ValueError:
        return None
    j = i + 1
    if j < 25 or j + 22 >= len(rows):
        return None
    close = np.array([r[6] for r in rows], float)
    vol = np.array([r[7] for r in rows], float)
    oq = np.array([open_qfq(r) for r in rows], float)
    c0 = close[j]
    if c0 <= 0:
        return None
    # 一买分数(生产公式: 50+量能±20+深跌±25)
    avg = vol[j-20:j].mean()
    vr = vol[j] / avg if avg else 1
    s = 50.0 + max(-20.0, min(20.0, (vr - 1) * 15))
    c10 = close[j-10]
    chg = (c0 - c10) / c10 * 100 if c10 else 0
    s += max(-25.0, min(25.0, -chg * 0.8))
    s = round(max(0.0, min(100.0, s)), 1)
    # 收益
    p0 = oq[i+2]
    if p0 <= 0:
        return None
    return {'score': s, 'r10': (close[i+2+10] / p0 - 1) * 100, 'r20': (close[i+2+20] / p0 - 1) * 100}

out = []
for k, (sym, date, price) in enumerate(sigs):
    r = calc(sym, date)
    if r:
        out.append(r)
    if k % 5000 == 0:
        print(f"  {k}/{len(sigs)} {time.time()-t0:.0f}s", flush=True)
print(f"有效样本: {len(out)} {time.time()-t0:.0f}s")

r10 = np.array([r['r10'] for r in out])
r20 = np.array([r['r20'] for r in out])
sc = np.array([r['score'] for r in out])
print(f"\n=== 一买 基准: 胜率10={(r10>0).mean()*100:.1f}% 收益10={r10.mean():.2f}% 中位={np.median(r10):.2f}% | 胜率20={(r20>0).mean()*100:.1f}% 收益20={r20.mean():.2f}%")
for th in (75, 70, 65, 60):
    idx = np.where(sc >= th)[0]
    if len(idx) < 50:
        print(f"  ≥{th}分: n={len(idx)} (样本不足)")
        continue
    print(f"  ≥{th}分: n={len(idx)} 胜率10={(r10[idx]>0).mean()*100:.1f}% 收益10={r10[idx].mean():.2f}% | 胜率20={(r20[idx]>0).mean()*100:.1f}% 收益20={r20[idx].mean():.2f}%")
# 5分组
idx = np.argsort(sc); n = len(idx); q = n // 5
print("  5分组(按分数):")
for g in range(5):
    seg = idx[g*q:(g+1)*q if g < 4 else n]
    print(f"    组{g+1}: 胜率10={(r10[seg]>0).mean()*100:.1f}% 收益10={r10[seg].mean():.2f}%")
# top20%
k = len(sc) // 5
top = np.argsort(-sc)[:k]
print(f"  top20%: 胜率10={(r10[top]>0).mean()*100:.1f}% 收益10={r10[top].mean():.2f}% | 胜率20={(r20[top]>0).mean()*100:.1f}% 收益20={r20[top].mean():.2f}%")

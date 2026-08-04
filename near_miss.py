#!/usr/bin/env python3
"""Analyze premium_b near-misses"""
import sqlite3, os, sys
os.environ["HTTP_PROXY"] = ""
os.environ["HTTPS_PROXY"] = ""

today = "2026-07-27"
conn = sqlite3.connect('/home/ubuntu/databases/Sequoia选股.db')

# Build temp table
conn.executescript(f"""
    DROP TABLE IF EXISTS sig_today;
    CREATE TEMP TABLE sig_today AS
    WITH base AS (
        SELECT symbol, date, close_qfq AS price, volume
        FROM stock_daily WHERE close_qfq > 0
          AND date >= date('{today}', '-120 days')
    ),
    mavgs AS (
        SELECT symbol, date, price, volume,
            AVG(price) OVER (PARTITION BY symbol ORDER BY date ROWS BETWEEN 19 PRECEDING AND CURRENT ROW) AS ma20,
            AVG(price) OVER (PARTITION BY symbol ORDER BY date ROWS BETWEEN 59 PRECEDING AND CURRENT ROW) AS ma60,
            AVG(volume) OVER (PARTITION BY symbol ORDER BY date ROWS BETWEEN 19 PRECEDING AND 1 PRECEDING) AS avg_vol_20,
            LAG(price, 20) OVER (PARTITION BY symbol ORDER BY date) AS price_20ago
        FROM base
    )
    SELECT symbol, price, ma20, ma60, volume, avg_vol_20,
           ROUND((price / ma20 - 1) * 100, 2) AS dist_ma20,
           ROUND(volume / NULLIF(avg_vol_20, 0), 2) AS vol_ratio,
           ROUND((price - price_20ago) / NULLIF(price_20ago, 0) * 100, 2) AS pct_20d
    FROM mavgs
    WHERE date = '{today}'
      AND ma20 IS NOT NULL AND avg_vol_20 IS NOT NULL AND avg_vol_20 > 0
      AND price > ma20 AND price_20ago IS NOT NULL
""")

n = conn.execute("SELECT COUNT(*) FROM sig_today").fetchone()[0]
print(f"今日趋势票（价在MA20上）: {n}只")
print()

rows = conn.execute("""
    SELECT s.symbol, COALESCE(n.name, ''), s.price, s.ma20, s.ma60,
           s.dist_ma20, s.vol_ratio, s.pct_20d
    FROM sig_today s
    LEFT JOIN stock_basics n ON n.symbol = s.symbol
    ORDER BY s.dist_ma20
""").fetchall()

def check_premium_b(r):
    sym, name, price, ma20, ma60, dist, vr, pct20 = r
    if name is None: name = ''
    dist = dist or 0
    vr = vr or 99
    pct20 = pct20 if pct20 is not None else -999
    
    fails = []
    d_pass = 12 <= dist < 25
    if not d_pass:
        fails.append(f"dist={dist:.1f}%")
    
    v_pass = 0 <= vr < 0.3
    if not v_pass:
        fails.append(f"vr={vr:.2f}")
    
    p_pass = 3 <= pct20 < 15
    if not p_pass:
        fails.append(f"20d={pct20:.1f}%")
    
    m_pass = bool(ma60 and price > ma20 > ma60)
    if not m_pass:
        fails.append("MA60破位" if not (ma20 > ma60) else "非多头")
    
    pc = sum([d_pass, v_pass, p_pass, m_pass])
    return pc, fails, d_pass, v_pass, p_pass, m_pass

# Find near misses
print(f"{'股票':<10s}{'代码':>6s}{'收盘':>7s}{'MA20':>7s}{'MA60':>7s}{'dist':>7s}{'量比':>5s}{'20日涨':>7s}{'PB分':>4s}{'差距'}")

near = []
for r in rows:
    sym, name, price, ma20, ma60, dist, vr, pct20 = r
    pc, fails, dp, vp, pp, mp = check_premium_b(r)
    name_clean = (name or '')[:8]
    
    if pc >= 3:
        near.append(r)
        print(f"{name_clean:<8s} {sym:>6s} {price:>7.3f} {ma20:>7.3f} {ma60:>7.3f} {dist:>+6.1f}% {vr:>4.2f} {pct20:>+6.2f}% {pc:>3d}/4 | 差在{'|'.join(fails)}")
    
if not near:
    print("\n无通过3/4条件的。放宽到2/4：")
    candidates = []
    for r in rows:
        sym, name, price, ma20, ma60, dist, vr, pct20 = r
        pc, fails, dp, vp, pp, mp = check_premium_b(r)
        if pc >= 2:
            total_off = 0
            if not dp:
                if dist < 12: total_off += 12 - dist
                else: total_off += dist - 25
            if not vp:
                total_off += (vr - 0.3) * 5
            if not pp:
                if pct20 < 3: total_off += 3 - pct20
                else: total_off += pct20 - 15
            candidates.append((total_off, r, fails))
    
    candidates.sort()
    for off, r, fails in candidates[:20]:
        sym, name, price, ma20, ma60, dist, vr, pct20 = r
        name_clean = (name or '')[:8]
        print(f"{name_clean:<8s} {sym:>6s} {price:>7.3f} {dist:>+6.1f}% {vr:>4.2f} {pct20:>+6.2f}% off={off:.1f} | 差在{'|'.join(fails)}")

conn.close()

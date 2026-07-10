#!/usr/bin/env python3
"""每日多策略趋势选股 — 每个策略独立MA60配置"""
import sqlite3, json, sys, os
from datetime import date, datetime
from collections import defaultdict

os.environ["HTTP_PROXY"] = ""
os.environ["HTTPS_PROXY"] = ""

SRC_DB = "/home/ubuntu/databases/Sequoia选股.db"
OUT_DB = "/home/ubuntu/databases/trend_picks.db"

STRATEGIES = {
    'original':     {'dl':10,'dh':20,'vl':0,'vh':0.3,'pl':5,'ph':25, 'ma60':False},
    'premium_a':    {'dl':12,'dh':25,'vl':0.1,'vh':0.3,'pl':3,'ph':15, 'ma60':True},
    'premium_b':    {'dl':12,'dh':25,'vl':0,'vh':0.3,'pl':3,'ph':15, 'ma60':True},
    'ultra_shrink': {'dl':10,'dh':20,'vl':0,'vh':0.15,'pl':3,'ph':15, 'ma60':True},
}

def log(msg):
    print(f"[{datetime.now().strftime('%H:%M:%S')}] {msg}", flush=True)

def calc_ret(fp, bp):
    return round((fp/bp - 1)*100, 2) if fp and bp and bp > 0 else None

def run_picks(today_str):
    conn = sqlite3.connect(SRC_DB)
    c = conn.cursor()
    
    has_data = c.execute("SELECT 1 FROM stock_daily WHERE date=? LIMIT 1", (today_str,)).fetchone()
    if not has_data:
        log("无数据（非交易日或数据未更新）")
        conn.close()
        return None
    
    log(f"扫描 {today_str}")
    
    c.executescript(f"""
        DROP TABLE IF EXISTS sig_today;
        CREATE TEMP TABLE sig_today AS
        WITH base AS (
            SELECT symbol, date, close_qfq AS price, close AS close_raw, volume, turnover, open
            FROM stock_daily WHERE close_qfq > 0
        ),
        mavgs AS (
            SELECT symbol, date, price, close_raw, volume, turnover, open,
                AVG(price) OVER (PARTITION BY symbol ORDER BY date ROWS BETWEEN 19 PRECEDING AND CURRENT ROW) AS ma20,
                AVG(price) OVER (PARTITION BY symbol ORDER BY date ROWS BETWEEN 59 PRECEDING AND CURRENT ROW) AS ma60,
                AVG(volume) OVER (PARTITION BY symbol ORDER BY date ROWS BETWEEN 19 PRECEDING AND 1 PRECEDING) AS avg_vol_20,
                LAG(price, 20) OVER (PARTITION BY symbol ORDER BY date) AS price_20ago,
                LEAD(open, 1) OVER (PARTITION BY symbol ORDER BY date) AS f1_open,
                LEAD(close_raw, 1) OVER (PARTITION BY symbol ORDER BY date) AS f1_close_raw,
                LEAD(price, 1) OVER (PARTITION BY symbol ORDER BY date) AS f1_close,
                LEAD(price, 2) OVER (PARTITION BY symbol ORDER BY date) AS f2_close,
                LEAD(price, 3) OVER (PARTITION BY symbol ORDER BY date) AS f3_close,
                LEAD(price, 5) OVER (PARTITION BY symbol ORDER BY date) AS f5_close,
                LEAD(price, 10) OVER (PARTITION BY symbol ORDER BY date) AS f10_close,
                LEAD(price, 15) OVER (PARTITION BY symbol ORDER BY date) AS f15_close,
                LEAD(price, 20) OVER (PARTITION BY symbol ORDER BY date) AS f20_close,
                LEAD(price, 25) OVER (PARTITION BY symbol ORDER BY date) AS f25_close,
                LEAD(price, 30) OVER (PARTITION BY symbol ORDER BY date) AS f30_close,
                LEAD(price, 35) OVER (PARTITION BY symbol ORDER BY date) AS f35_close,
                LEAD(price, 40) OVER (PARTITION BY symbol ORDER BY date) AS f40_close,
                LEAD(price, 45) OVER (PARTITION BY symbol ORDER BY date) AS f45_close,
                LEAD(price, 50) OVER (PARTITION BY symbol ORDER BY date) AS f50_close,
                LEAD(price, 55) OVER (PARTITION BY symbol ORDER BY date) AS f55_close,
                LEAD(price, 60) OVER (PARTITION BY symbol ORDER BY date) AS f60_close,
                LEAD(price, 100) OVER (PARTITION BY symbol ORDER BY date) AS f100_close,
                LEAD(price, 150) OVER (PARTITION BY symbol ORDER BY date) AS f150_close,
                LEAD(price, 200) OVER (PARTITION BY symbol ORDER BY date) AS f200_close
            FROM base
        )
        SELECT symbol, date, price, close_raw, ma20, ma60, volume, avg_vol_20,
               ROUND((price / ma20 - 1) * 100, 2) AS dist_ma20,
               ROUND(volume / NULLIF(avg_vol_20, 0), 2) AS vol_ratio,
               ROUND((price - price_20ago) / NULLIF(price_20ago, 0) * 100, 2) AS pct_20d,
               f1_open, f1_close_raw, f1_close, f2_close, f3_close, f5_close, f10_close, f15_close, f20_close,
               f25_close, f30_close, f35_close, f40_close, f45_close, f50_close, f55_close, f60_close,
               f100_close, f150_close, f200_close
        FROM mavgs
        WHERE date = '{today_str}'
          AND ma20 IS NOT NULL AND avg_vol_20 IS NOT NULL AND avg_vol_20 > 0
          AND price > ma20 AND price_20ago IS NOT NULL
    """)
    
    n_trend = c.execute("SELECT COUNT(*) FROM sig_today").fetchone()[0]
    log(f"今日趋势票: {n_trend}")
    
    rows = c.execute("""
        SELECT symbol, date, price, close_raw, ma20, ma60, volume, avg_vol_20,
               dist_ma20, vol_ratio, pct_20d,
               f1_open, f1_close_raw, f1_close, f2_close, f3_close, f5_close, f10_close, f15_close, f20_close,
               f25_close, f30_close, f35_close, f40_close, f45_close, f50_close, f55_close, f60_close,
               f100_close, f150_close, f200_close
        FROM sig_today
    """).fetchall()
    
    syms = [r[0] for r in rows]
    name_map = {}
    for i in range(0, len(syms), 500):
        batch = syms[i:i+500]
        ph = ",".join("?" * len(batch))
        for r2 in c.execute(f"SELECT symbol, name FROM stock_basics WHERE symbol IN ({ph}) GROUP BY symbol", batch):
            name_map[r2[0]] = r2[1]
    conn.close()
    
    picks = []
    for r in rows:
        sym, dt, price, cr, ma20, ma60, vol, avgv, dist, vr, p20, f1o, f1cr, f1c, f2c, f3c, f5c, f10c, f15c, f20c, f25c, f30c, f35c, f40c, f45c, f50c, f55c, f60c, f100c, f150c, f200c = r
        
        if f1cr and f1cr > 0:
            bp = round(f1o * (f1c / f1cr), 4)
        else:
            bp = f1c
        
        rets = (calc_ret(f1c, bp), calc_ret(f2c, bp), calc_ret(f3c, bp),
                calc_ret(f5c, bp), calc_ret(f10c, bp), calc_ret(f15c, bp), calc_ret(f20c, bp),
                calc_ret(f25c, bp), calc_ret(f30c, bp), calc_ret(f35c, bp),
                calc_ret(f40c, bp), calc_ret(f45c, bp), calc_ret(f50c, bp),
                calc_ret(f55c, bp), calc_ret(f60c, bp),
                calc_ret(f100c, bp), calc_ret(f150c, bp), calc_ret(f200c, bp))
        
        for sid, s in STRATEGIES.items():
            if not (s['dl'] <= dist < s['dh']): continue
            if not (s['vl'] <= vr < s['vh']): continue
            if p20 is None or not (s['pl'] <= p20 < s['ph']): continue
            if s['ma60'] and (not ma60 or not (price > ma20 > ma60)): continue
            
            picks.append((dt, sid, sym, name_map.get(sym, ''),
                         price, ma20, ma60, dist, vr, p20,
                         vol, avgv, bp,
                         rets[0], rets[1], rets[2], rets[3], rets[4], rets[5], rets[6],
                         rets[7], rets[8], rets[9], rets[10], rets[11], rets[12], rets[13], rets[14],
                         rets[15], rets[16], rets[17]))
    return picks

def save_picks(picks):
    if not picks:
        return
    out = sqlite3.connect(OUT_DB)
    dates = set(p[0] for p in picks)
    for dt in dates:
        out.execute("DELETE FROM daily_picks WHERE date=?", (dt,))
        out.execute("DELETE FROM daily_summary WHERE date=?", (dt,))
    
    out.executemany("""
        INSERT INTO daily_picks 
        (date, strategy_id, symbol, name, close_qfq, ma20, ma60, dist_ma20, vol_ratio, pct_20d,
         volume, avg_vol_20d, buy_price, ret_t1, ret_t2, ret_t3, ret_t5, ret_t10, ret_t15, ret_t20,
         ret_t25, ret_t30, ret_t35, ret_t40, ret_t45, ret_t50, ret_t55, ret_t60,
         ret_100, ret_150, ret_200)
        VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
    """, picks)
    
    by_dt_sid = defaultdict(list)
    for p in picks:
        by_dt_sid[(p[0], p[1])].append(p[3])
    for (dt, sid), syms_list in sorted(by_dt_sid.items()):
        out.execute("INSERT OR REPLACE INTO daily_summary (date, strategy_id, pick_count, symbols) VALUES (?,?,?,?)",
                    (dt, sid, len(syms_list), ", ".join(syms_list)))
    out.commit()
    out.close()

def main():
    today_str = date.today().strftime("%Y-%m-%d")
    log(f"=== 多策略趋势缩量选股 {today_str} ===")
    picks = run_picks(today_str)
    if picks:
        save_picks(picks)
        by_sid = defaultdict(list)
        for p in picks:
            by_sid[p[1]].append(p)
        for sid, plist in sorted(by_sid.items()):
            log(f"  {sid:>15}: {len(plist)}只")
        log(f"总计: {len(picks)}信号")
    else:
        log("无信号")
    return {"date": today_str, "picks": len(picks) if picks else 0}

if __name__ == "__main__":
    result = main()
    print(json.dumps(result, ensure_ascii=False))

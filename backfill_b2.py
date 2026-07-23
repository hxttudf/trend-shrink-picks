#!/usr/bin/env python3
"""回测写入 premium_b2 (极品B2 vh=0.5) 历史信号到 trend_picks.db"""
import sqlite3, json, sys
from collections import defaultdict
from datetime import datetime, timedelta

TREND_DB = "/home/ubuntu/databases/trend_picks.db"
SRC_DB = "/home/ubuntu/databases/Sequoia选股.db"

def log(msg):
    print(f"[{datetime.now().strftime('%H:%M:%S')}] {msg}", flush=True)

def run():
    conn = sqlite3.connect(SRC_DB)
    c = conn.cursor()
    
    # 获取历史所有交易日
    dates = [r[0] for r in c.execute(
        "SELECT DISTINCT date FROM stock_daily WHERE close_qfq>0 AND date BETWEEN '2020-01-01' AND '2026-07-21' ORDER BY date"
    ).fetchall()]
    log(f"交易日: {len(dates)}天")
    
    # 一次扫描所有数据，用 window functions 计算出所有候选
    log("扫描全量数据计算指标...")
    rows = c.execute("""
        SELECT date, symbol, close_qfq AS price,
            close AS close_raw, ma20, ma60, volume, avg_vol_20, dist_ma20, vol_ratio, pct_20d
        FROM (
            SELECT date, symbol, close_qfq, close,
                AVG(close_qfq) OVER (PARTITION BY symbol ORDER BY date ROWS BETWEEN 19 PRECEDING AND CURRENT ROW) AS ma20,
                AVG(close_qfq) OVER (PARTITION BY symbol ORDER BY date ROWS BETWEEN 59 PRECEDING AND CURRENT ROW) AS ma60,
                volume,
                AVG(volume) OVER (PARTITION BY symbol ORDER BY date ROWS BETWEEN 19 PRECEDING AND 1 PRECEDING) AS avg_vol_20,
                ROUND((close_qfq / AVG(close_qfq) OVER (PARTITION BY symbol ORDER BY date ROWS BETWEEN 19 PRECEDING AND CURRENT ROW) - 1) * 100, 2) AS dist_ma20,
                ROUND(volume * 1.0 / NULLIF(AVG(volume) OVER (PARTITION BY symbol ORDER BY date ROWS BETWEEN 19 PRECEDING AND 1 PRECEDING), 0), 2) AS vol_ratio,
                ROUND((close_qfq - LAG(close_qfq, 20) OVER (PARTITION BY symbol ORDER BY date)) / NULLIF(LAG(close_qfq, 20) OVER (PARTITION BY symbol ORDER BY date), 0) * 100, 2) AS pct_20d
            FROM stock_daily WHERE close_qfq>0 AND date>='2020-01-01'
        )
        WHERE date BETWEEN '2020-06-01' AND '2026-07-21'
          AND price > ma20 AND ma20 > ma60 AND ma60 IS NOT NULL
          AND dist_ma20 BETWEEN 12 AND 25
          AND pct_20d IS NOT NULL
          AND pct_20d BETWEEN 3 AND 15
          AND vol_ratio < 0.5
        ORDER BY date, symbol
    """).fetchall()
    log(f"原始候选: {len(rows)}行")
    
    if not rows:
        log("无数据")
        conn.close()
        return
    
    # 按日期分组
    by_date = defaultdict(list)
    for r in rows:
        by_date[r[0]].append(r)
    log(f"有信号的交易日: {len(by_date)}天")
    
    # 获取所有股票名称
    all_symbols = list(set(r[1] for r in rows))
    name_map = {}
    for i in range(0, len(all_symbols), 500):
        batch = all_symbols[i:i+500]
        ph = ",".join("?" * len(batch))
        for r2 in c.execute(f"SELECT symbol, name FROM stock_basics WHERE symbol IN ({ph}) GROUP BY symbol", batch):
            name_map[r2[0]] = r2[1]
    
    # 写入 trend_picks.db
    out = sqlite3.connect(TREND_DB)
    sid = 'premium_b2'
    
    total = 0
    for dt, picks in sorted(by_date.items()):
        # 删旧数据
        out.execute("DELETE FROM daily_picks WHERE date=? AND strategy_id=?", (dt, sid))
        out.execute("DELETE FROM daily_summary WHERE date=? AND strategy_id=?", (dt, sid))
        
        symbols = []
        for r in picks:
            date, sym, price, cr, ma20, ma60, vol, avgv, dist, vr, p20 = r
            name = name_map.get(sym, "")
            symbols.append(name)
            out.execute("""
                INSERT INTO daily_picks 
                (date, strategy_id, symbol, name, close_qfq, ma20, ma60,
                 dist_ma20, vol_ratio, pct_20d, buy_price)
                VALUES (?,?,?,?,?,?,?,?,?,?,?)
            """, (date, sid, sym, name, price, ma20, ma60, dist, vr, p20, price))
            total += 1
        
        out.execute("INSERT OR REPLACE INTO daily_summary (date, strategy_id, pick_count, symbols) VALUES (?,?,?,?)",
                    (dt, sid, len(picks), ", ".join(symbols)))
    
    out.commit()
    out.close()
    conn.close()
    log(f"写入完成: 共{total}条信号, {len(by_date)}天")

if __name__ == '__main__':
    run()

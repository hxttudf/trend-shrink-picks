#!/usr/bin/env python3
"""回填历史信号到模拟盘（带进度）"""
import sqlite3, sys, os, time
sys.path.insert(0, '/home/ubuntu/trend-shrink-picks')
from sim_trade import *

DB_TRADE = '/home/ubuntu/databases/sim_trade.db'
if os.path.exists(DB_TRADE):
    os.remove(DB_TRADE)

conn_trade = init_db()
conn_trend = sqlite3.connect(DB_TREND)
conn_sequoia = sqlite3.connect(DB_SEQUOIA)

trade_dates = get_trade_dates(conn_sequoia, '2025-01-01', '2026-07-10')
print(f"交易日: {trade_dates[0]} ~ {trade_dates[-1]} ({len(trade_dates)}天)")

signal_dates = conn_trend.execute("""
    SELECT DISTINCT dp.date FROM daily_picks dp
    JOIN strategies s ON dp.strategy_id = s.id
    WHERE s.name = '极品B' AND dp.date >= '2025-01-01'
    ORDER BY dp.date
""").fetchall()
signal_dates = [r[0] for r in signal_dates]
print(f"信号日: {len(signal_dates)}天")

total = len(trade_dates)
start_time = time.time()
last_print = 0

for i, dt in enumerate(trade_dates):
    # 进度打印（每50天或信号日）
    now = time.time()
    if i % 50 == 0 or now - last_print > 5:
        elapsed = now - start_time
        pct = (i/total)*100
        print(f"\r[{i}/{total}] {dt} ({pct:.0f}%) elapsed={elapsed:.0f}s", end='', flush=True)
        last_print = now
    
    execute_sells(conn_trade, conn_sequoia, dt)
    
    if dt in signal_dates:
        buy_signals = process_signals(conn_trade, conn_trend, conn_sequoia, dt)
        execute_buys(conn_trade, conn_sequoia, buy_signals, dt)
    
    snapshot(conn_trade, conn_sequoia, dt)

# 只在最后commit一次，大幅提速
conn_trade.commit()
elapsed = time.time() - start_time
print(f"\n\n回填完成! 耗时{elapsed:.0f}s")

cash = get_cash(conn_trade)
total_val = conn_trade.execute("SELECT total_value FROM sim_daily ORDER BY date DESC LIMIT 1").fetchone()
if total_val:
    total_val = total_val[0]
    cum_ret = (total_val / INIT_CASH - 1) * 100
    print(f"总资产: {total_val:.2f}  现金: {cash:.2f}  累计收益: {cum_ret:+.2f}%")

trades = conn_trade.execute("SELECT * FROM sim_trades ORDER BY buy_date").fetchall()
cols = [d[1] for d in conn_trade.execute("PRAGMA table_info(sim_trades)").fetchall()]
sold = [dict(zip(cols, t)) for t in trades if t[cols.index('status')] == 'sold']
holding = [dict(zip(cols, t)) for t in trades if t[cols.index('status')] == 'holding']

print(f"\n已完结: {len(sold)}笔  持仓: {len(holding)}笔")
for t in sold[:5]:
    print(f"  {t['buy_date']} {t['symbol']} {t['name']} {t['buy_price']:.2f}→{t['sell_price']:.2f} {t['return_pct']:+.2f}%")

conn_trade.close()
conn_trend.close()
conn_sequoia.close()

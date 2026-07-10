#!/usr/bin/env python3
"""
极品B模拟盘 — 每日选股、买卖执行、收益记录
每天跑一次（收盘后），维护持仓状态并输出操作
"""
import sqlite3
import os
import sys
from datetime import datetime, timedelta

DB_TREND = '/home/ubuntu/databases/trend_picks.db'
DB_SEQUOIA = '/home/ubuntu/databases/Sequoia选股.db'
DB_TRADE = '/home/ubuntu/databases/sim_trade.db'

# 模拟盘参数
INIT_CASH = 200000          # 初始资金20万
POSITION_PCT = 0.25         # 每只25%
MAX_POSITIONS = 4            # 上限4只
HOLD_DAYS = 20               # 持有20个交易日

def init_db():
    conn = sqlite3.connect(DB_TRADE)
    c = conn.cursor()
    c.executescript("""
        CREATE TABLE IF NOT EXISTS sim_config (
            key TEXT PRIMARY KEY,
            value REAL
        );
        CREATE TABLE IF NOT EXISTS sim_trades (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            signal_date TEXT,
            symbol TEXT NOT NULL,
            name TEXT DEFAULT '',
            buy_date TEXT,
            buy_price REAL,
            buy_amount REAL,
            buy_volume INTEGER,
            sell_date TEXT,
            sell_price REAL,
            sell_amount REAL,
            hold_days_actual INTEGER,
            return_pct REAL,
            profit REAL,
            status TEXT DEFAULT 'holding'
        );
        CREATE TABLE IF NOT EXISTS sim_daily (
            date TEXT PRIMARY KEY,
            cash REAL,
            positions_value REAL,
            total_value REAL,
            pos_count INTEGER,
            daily_pnl REAL,
            cum_return_pct REAL
        );
    """)
    c.execute("INSERT OR IGNORE INTO sim_config VALUES ('cash', ?)", (INIT_CASH,))
    c.execute("INSERT OR IGNORE INTO sim_config VALUES ('total_start', ?)", (INIT_CASH,))
    conn.commit()
    return conn

def get_trade_dates(conn_sequoia, start_date, end_date=None):
    """获取交易日列表"""
    if end_date:
        sql = "SELECT DISTINCT date FROM stock_daily WHERE date >= ? AND date <= ? ORDER BY date"
        params = [start_date, end_date]
    else:
        sql = "SELECT DISTINCT date FROM stock_daily WHERE date >= ? ORDER BY date"
        params = [start_date]
    rows = conn_sequoia.execute(sql, params).fetchall()
    return [r[0] for r in rows]

def next_trade_date(conn_sequoia, date):
    """获取下一个交易日"""
    row = conn_sequoia.execute(
        "SELECT MIN(date) FROM stock_daily WHERE date > ?", (date,)
    ).fetchone()
    return row[0] if row and row[0] else None

def get_price(conn_sequoia, symbol, date, field='close_qfq'):
    """获取某股票某日价格"""
    row = conn_sequoia.execute(
        f"SELECT {field} FROM stock_daily WHERE symbol = ? AND date = ?",
        (symbol, date)
    ).fetchone()
    return row[0] if row else None

def get_holdings(conn_trade):
    """获取当前持仓"""
    rows = conn_trade.execute(
        "SELECT * FROM sim_trades WHERE status = 'holding' ORDER BY buy_date"
    ).fetchall()
    cols = [d[1] for d in conn_trade.execute("PRAGMA table_info(sim_trades)").fetchall()]
    return [dict(zip(cols, r)) for r in rows]

def get_cash(conn_trade):
    row = conn_trade.execute("SELECT value FROM sim_config WHERE key='cash'").fetchone()
    return row[0] if row else INIT_CASH

def update_cash(conn_trade, new_cash):
    conn_trade.execute("UPDATE sim_config SET value = ? WHERE key = 'cash'", (new_cash,))

def process_signals(conn_trade, conn_trend, conn_sequoia, today):
    """处理新信号"""
    # 查询当天的极品B信号（去重）
    signals = conn_trend.execute("""
        SELECT DISTINCT dp.symbol, dp.name, dp.close_qfq, dp.date
        FROM daily_picks dp
        JOIN strategies s ON dp.strategy_id = s.id
        WHERE s.name = '极品B' AND dp.date = ?
    """, (today,)).fetchall()
    
    if not signals:
        print(f"[{today}] 无新信号")
        return []
    
    # 检查已持有中再次命中的（续期）
    holdings = get_holdings(conn_trade)
    holding_symbols = {h['symbol'] for h in holdings}
    
    buy_trades = []
    for sig in signals:
        sym, name, price, sig_date = sig
        if sym in holding_symbols:
            # 续期：重置持有日
            conn_trade.execute(
                "UPDATE sim_trades SET hold_days_actual = 0 WHERE symbol = ? AND status = 'holding'",
                (sym,)
            )
            print(f"  ↻ 续期 {sym} {name}")
            continue
        
        # 新股，准备买入
        buy_trades.append(sig)
    
    return buy_trades

def execute_buys(conn_trade, conn_sequoia, buy_signals, today):
    """在下一个交易日开盘买入"""
    cash = get_cash(conn_trade)
    holdings = get_holdings(conn_trade)
    current_pos = len(holdings)
    slots = MAX_POSITIONS - current_pos
    
    if slots <= 0 or not buy_signals:
        return
    
    # 上一个交易日收盘的总资产 = cash + 持仓市值
    total_value = cash
    for h in holdings:
        total_value += h['buy_amount']  # 近似
    
    target_per_pos = total_value * POSITION_PCT
    
    print(f"\n[{today}] 信号日，下一个交易日买入:")
    print(f"  现金: {cash:.2f}, 当前持仓: {current_pos}, 仓位上限: {slots}")
    print(f"  NAV: {total_value:.2f}, 每只目标: {target_per_pos:.2f}")
    
    for sig in buy_signals[:slots]:
        sym, name, price, sig_date = sig
        
        buy_date = next_trade_date(conn_sequoia, today)
        if not buy_date:
            print(f"  ⚠ 无法找到买入日（{today}之后无交易日）")
            continue
        
        # 买入价 = 信号日的close_qfq（近似次日开盘）
        buy_price = price
        if not buy_price or buy_price <= 0:
            print(f"  ⚠ {sym} {name} 买入价异常: {buy_price}")
            continue
        
        available = min(target_per_pos, cash)
        if available < 1000:
            print(f"  ⚠ 现金不足（{cash:.2f}），跳过 {sym} {name}")
            continue
        
        # 计算买入股数（100股整数倍）
        volume = int(available / buy_price / 100) * 100
        if volume < 100:
            print(f"  ⚠ 不够一手，跳过 {sym} {name}")
            continue
        
        buy_amount = volume * buy_price
        cash -= buy_amount
        
        conn_trade.execute("""
            INSERT INTO sim_trades (signal_date, symbol, name, buy_date, buy_price, 
                                   buy_amount, buy_volume, status)
            VALUES (?, ?, ?, ?, ?, ?, ?, 'holding')
        """, (sig_date, sym, name, buy_date, buy_price, buy_amount, volume))
        
        print(f"  ✅ 买入 {sym} {name} {volume}股 @ {buy_price:.2f} = {buy_amount:.2f}")
    
    update_cash(conn_trade, cash)

def execute_sells(conn_trade, conn_sequoia, today):
    """检查到期卖出"""
    holdings = get_holdings(conn_trade)
    cash = get_cash(conn_trade)
    
    for h in holdings:
        # 计算已持有天数（从买入日到今天之间的交易日数）
        trade_days = len(get_trade_dates(conn_sequoia, h['buy_date'], today))
        if trade_days <= 0:
            trade_days = 1  # 当天
        
        # 更新持有天数
        conn_trade.execute(
            "UPDATE sim_trades SET hold_days_actual = ? WHERE id = ?",
            (trade_days, h['id'])
        )
        
        if trade_days >= HOLD_DAYS:
            # 到期卖出
            sell_date = today
            sell_price = get_price(conn_sequoia, h['symbol'], today)
            if not sell_price:
                # 如果当天没数据，找下一个有数据的交易日
                sell_date = next_trade_date(conn_sequoia, today)
                if not sell_date:
                    continue
                sell_price = get_price(conn_sequoia, h['symbol'], sell_date)
            
            if not sell_price:
                continue
            
            sell_amount = h['buy_volume'] * sell_price
            return_pct = (sell_price / h['buy_price'] - 1) * 100
            profit = sell_amount - h['buy_amount']
            
            conn_trade.execute("""
                UPDATE sim_trades SET 
                    sell_date = ?, sell_price = ?, sell_amount = ?,
                    return_pct = ?, profit = ?, status = 'sold'
                WHERE id = ?
            """, (sell_date, sell_price, sell_amount, return_pct, profit, h['id']))
            
            cash += sell_amount
            print(f"  🔴 卖出 {h['symbol']} {h['name']} ({h['buy_volume']}股 @ {sell_price:.2f}) "
                  f"收益{return_pct:+.2f}% 盈亏{profit:+.2f}")
    
    update_cash(conn_trade, cash)

def snapshot(conn_trade, conn_sequoia, today):
    """记录每日快照"""
    cash = get_cash(conn_trade)
    holdings = get_holdings(conn_trade)
    
    pos_value = 0
    for h in holdings:
        price = get_price(conn_sequoia, h['symbol'], today)
        if price:
            pos_value += h['buy_volume'] * price
        else:
            pos_value += h['buy_amount']  # fallback
    
    total = cash + pos_value
    
    # 计算累计收益率
    start_value = INIT_CASH
    cum_return = (total / start_value - 1) * 100
    
    # 上一日数据
    yesterday = None
    row = conn_trade.execute(
        "SELECT date FROM sim_daily ORDER BY date DESC LIMIT 1"
    ).fetchone()
    if row:
        yesterday = row[0]
        prev = conn_trade.execute(
            "SELECT total_value FROM sim_daily WHERE date = ?", (yesterday,)
        ).fetchone()
        prev_total = prev[0] if prev else start_value
    else:
        prev_total = start_value
    
    daily_pnl = total - prev_total
    
    conn_trade.execute("""
        INSERT OR REPLACE INTO sim_daily 
        (date, cash, positions_value, total_value, pos_count, daily_pnl, cum_return_pct)
        VALUES (?, ?, ?, ?, ?, ?, ?)
    """, (today, cash, pos_value, total, len(holdings), daily_pnl, cum_return))
    
    return total, cum_return

def print_summary(today, total, cum_return, cash):
    print(f"\n{'='*60}")
    print(f"  极品B模拟盘 | {today}")
    print(f"{'='*60}")
    print(f"  总资产: {total:>10.2f}")
    print(f"  现金:   {cash:>10.2f}")
    print(f"  累计收益: {cum_return:>+8.2f}%")
    print(f"{'='*60}\n")

def run():
    today = datetime.now().strftime('%Y-%m-%d')
    
    # 如果命令行提供了日期，就用它
    if len(sys.argv) > 1:
        today = sys.argv[1]
    
    conn_trade = init_db()
    conn_trend = sqlite3.connect(DB_TREND)
    conn_sequoia = sqlite3.connect(DB_SEQUOIA)
    
    print(f"\n=== 极品B模拟盘 [{today}] ===")
    
    # 1. 到期卖出
    execute_sells(conn_trade, conn_sequoia, today)
    
    # 2. 处理新信号
    buy_signals = process_signals(conn_trade, conn_trend, conn_sequoia, today)
    
    # 3. 次日开盘买入
    execute_buys(conn_trade, conn_sequoia, buy_signals, today)
    
    # 4. 每日快照
    total, cum_return = snapshot(conn_trade, conn_sequoia, today)
    cash = get_cash(conn_trade)
    
    conn_trade.commit()
    
    # 5. 输出汇总
    print_summary(today, total, cum_return, cash)
    
    # 6. 输出持仓
    holdings = get_holdings(conn_trade)
    if holdings:
        print("  当前持仓:")
        for h in holdings:
            print(f"    {h['symbol']} {h['name']} {h['buy_volume']}股 "
                  f"成本{h['buy_price']:.2f} 持有{h.get('hold_days_actual',0)}天")
    else:
        print("  当前空仓")
    
    conn_trade.close()
    conn_trend.close()
    conn_sequoia.close()

if __name__ == '__main__':
    run()

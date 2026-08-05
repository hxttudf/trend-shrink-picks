#!/usr/bin/env python3
"""从 wind_data.db 读取数据，输出结构化JSON供agent写复盘报告"""
import sqlite3, json, sys
from datetime import date, timedelta

DB = '/home/ubuntu/databases/wind_data.db'
today = date.today().strftime('%Y%m%d')
yesterday = (date.today() - timedelta(days=1)).strftime('%Y%m%d')

def q(sql, params=()):
    conn = sqlite3.connect(DB)
    rows = conn.execute(sql, params).fetchall()
    conn.close()
    return rows

# 1. 指数
idx_rows = q("SELECT index_name, price, change_pct FROM wind_index_snapshots WHERE trade_date=? ORDER BY wind_code", (today,))
indices = {r[0]: {'price': r[1], 'chg': r[2]} for r in idx_rows}

# 2. 涨停数
zt_today = q("SELECT COUNT(*) FROM wind_zt_pool WHERE trade_date=?", (today,))[0][0]
dt_today = q("SELECT COUNT(*) FROM wind_dt_pool WHERE trade_date=?", (today,))[0][0]
# 最近一个交易日
last_td = q("SELECT MAX(trade_date) FROM wind_zt_pool WHERE trade_date < ?", (today,))[0][0]
zt_yest = q("SELECT COUNT(*) FROM wind_zt_pool WHERE trade_date=?", (last_td,))[0][0] if last_td else 0

# 3. 涨跌比
br = q("SELECT up_count, down_count FROM wind_market_breadth WHERE trade_date=? ORDER BY id DESC LIMIT 1", (today,))
up, down = br[0] if br else ('?', '?')

def normalize_net(net_val):
    """Wind DB net_flow 归一化 → 亿元"""
    if net_val is None or net_val == 0:
        return 0
    av = abs(net_val)
    if av > 1000000:
        return net_val / 100000000
    elif av > 1000:
        return net_val / 10000000
    else:
        return net_val / 10000

# 4. 行业资金流（前5流入+流出）
inflows_raw = q("""SELECT industry_name, net_flow FROM wind_all_industry_flows 
               WHERE trade_date=? AND net_flow IS NOT NULL 
               ORDER BY net_flow DESC LIMIT 5""", (today,))
outflows_raw = q("""SELECT industry_name, net_flow FROM wind_all_industry_flows 
                WHERE trade_date=? AND net_flow IS NOT NULL 
                ORDER BY net_flow ASC LIMIT 5""", (today,))
inflows = [(r[0], normalize_net(r[1])) for r in inflows_raw if abs(normalize_net(r[1])) >= 0.5]
outflows = [(r[0], normalize_net(r[1])) for r in outflows_raw if abs(normalize_net(r[1])) >= 0.5]

# 5. 连板
streaks = q("""SELECT stock_name, streak_days FROM wind_streak 
               WHERE trade_date=? AND streak_days >= 3 
               ORDER BY streak_days DESC LIMIT 5""", (today,))

# 6. 成交额
amt = q("SELECT total_amount FROM wind_market_breadth WHERE trade_date=? ORDER BY id DESC LIMIT 1", (today,))
total_amt = f"{amt[0][0]/1e8:.0f}亿" if amt and amt[0][0] else '?'

data = {
    'date': today,
    'indices': indices,
    'zt_count': zt_today,
    'dt_count': dt_today,
    'zt_change': f"{'↑' if zt_today > zt_yest else '↓'}{abs(zt_today - zt_yest)}",
    'up_stocks': up,
    'down_stocks': down,
    'total_amount': total_amt,
    'top_inflows': [{'industry': r[0], 'net': f"{r[1]:.1f}亿" if r[1] else '?'} for r in inflows],
    'top_outflows': [{'industry': r[0], 'net': f"{abs(r[1]):.1f}亿" if r[1] else '?'} for r in outflows],
    'top_streaks': [{'name': r[0], 'boards': r[1]} for r in streaks],
}
print(json.dumps(data, ensure_ascii=False))

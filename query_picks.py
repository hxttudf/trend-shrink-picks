#!/usr/bin/env python3
"""查询trend_picks.db多策略选股结果 — 排版优化版"""
import sqlite3, sys
from datetime import date

DB = "/home/ubuntu/databases/trend_picks.db"

def list_picks(date_str=None, strategy=None, top=30):
    conn = sqlite3.connect(DB)
    conn.row_factory = sqlite3.Row
    
    where = []
    params = []
    if date_str:
        where.append("dp.date=?")
        params.append(date_str)
    if strategy:
        where.append("dp.strategy_id=?")
        params.append(strategy)
    
    where_sql = " AND ".join(where) if where else "1=1"
    
    rows = conn.execute(f"""
        SELECT dp.date, s.name as strategy, dp.symbol, dp.name as stock_name,
               dp.close_qfq, dp.dist_ma20, dp.vol_ratio, dp.pct_20d,
               dp.buy_price, dp.ret_t5, dp.ret_t10, dp.ret_t20
        FROM daily_picks dp
        JOIN strategies s ON dp.strategy_id=s.id
        WHERE {where_sql}
        ORDER BY dp.date DESC, dp.strategy_id
        LIMIT ?
    """, (*params, top)).fetchall()
    
    if not rows:
        print("📭 今日无信号")
        return
    
    # Group by date and strategy
    from collections import OrderedDict
    groups = OrderedDict()
    for r in rows:
        key = (r['date'], r['strategy'])
        if key not in groups:
            groups[key] = []
        groups[key].append(r)
    
    total = len(rows)
    print(f"📊 趋势缩量选股 · {date_str or '最新'}    共计 {total} 个信号")
    print()
    
    for (dt, strat), items in groups.items():
        # Strategy header
        emoji = {"premium_b": "🏆", "premium_a": "🥈", "original": "📌", 
                 "ultra_shrink": "🔍", "premium_b2": "⭐"}
        e = emoji.get(strat, "•")
        print(f"  {e} {strat} · {len(items)}只")
        print(f"  {'代码':>8} {'名称':>6} {'距MA20':>7} {'量比':>5} {'20日涨':>7} {'买入价':>8}")
        print(f"  {'─'*8} {'─'*6} {'─'*7} {'─'*5} {'─'*7} {'─'*8}")
        
        for r in items:
            # Format signals
            dist_s = f"{r['dist_ma20']:+.1f}%"
            vr_s = f"{r['vol_ratio']:.2f}"
            p20_s = f"{r['pct_20d']:+.1f}%"
            bp_s = f"{r['buy_price']:.2f}" if r['buy_price'] else "—"
            
            print(f"  {r['symbol']:>8} {r['stock_name']:>6} {dist_s:>7} {vr_s:>5} {p20_s:>7} {bp_s:>8}")
        print()

    conn.close()

def stats():
    conn = sqlite3.connect(DB)
    conn.row_factory = sqlite3.Row
    rows = conn.execute("""
        SELECT s.name, s.id as sid,
               COUNT(*) as cnt,
               COUNT(DISTINCT dp.date) as days,
               ROUND(AVG(dp.ret_t20),2) as avg_t20,
               ROUND(SUM(CASE WHEN dp.ret_t20>0 THEN 1 ELSE 0 END)*100.0/COUNT(*),1) as win,
               ROUND(SUM(CASE WHEN dp.ret_t20>10 THEN 1 ELSE 0 END)*100.0/COUNT(*),1) as win10
        FROM daily_picks dp
        JOIN strategies s ON dp.strategy_id=s.id
        WHERE dp.ret_t20 IS NOT NULL
        GROUP BY dp.strategy_id
        ORDER BY cnt DESC
    """).fetchall()
    
    print("📊 策略统计")
    print(f"  {'策略':>12} {'信号':>5} {'天数':>5} {'T20胜率':>8} {'T20均':>7} {'赢10%+':>7}")
    print(f"  {'─'*12} {'─'*5} {'─'*5} {'─'*8} {'─'*7} {'─'*7}")
    for r in rows:
        avg_day = r['cnt']/r['days'] if r['days'] else 0
        print(f"  {r['name']:>12} {r['cnt']:>5} {r['days']:>5} {r['win']:>7.1f}% {r['avg_t20']:>+6.2f}% {r['win10']:>6.1f}%")
    
    total = conn.execute("SELECT COUNT(*) FROM daily_picks").fetchone()[0]
    days = conn.execute("SELECT COUNT(DISTINCT date) FROM daily_picks").fetchone()[0]
    print(f"  {'─'*12} {'─'*5} {'─'*5} {'─'*8} {'─'*7} {'─'*7}")
    print(f"  {'合计':>12} {total:>5} {days:>5}")
    conn.close()

if __name__ == "__main__":
    cmd = sys.argv[1] if len(sys.argv) > 1 else "today"
    if cmd == "list":
        date_arg = sys.argv[2] if len(sys.argv) > 2 else None
        strat_arg = sys.argv[3] if len(sys.argv) > 3 else None
        list_picks(date_arg, strat_arg)
    elif cmd == "today":
        list_picks(date.today().strftime("%Y-%m-%d"))
    elif cmd == "stats":
        stats()
    else:
        list_picks(cmd)

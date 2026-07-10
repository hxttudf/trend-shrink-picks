"""查询trend_picks.db多策略选股结果"""
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
               dp.ret_t5, dp.ret_t10, dp.ret_t20
        FROM daily_picks dp
        JOIN strategies s ON dp.strategy_id=s.id
        WHERE {where_sql}
        ORDER BY dp.date DESC, dp.strategy_id
        LIMIT ?
    """, (*params, top)).fetchall()
    
    if not rows:
        print("无数据")
        return
    
    print(f"{'日期':>10} {'策略':>6} {'代码':>8} {'名称':>8} {'价':>8} {'距MA20':>7} {'量比':>5} {'20日涨':>6} {'T5':>6} {'T10':>7} {'T20':>7}")
    print("-"*85)
    for r in rows:
        print(f"{r['date']:>10} {r['strategy']:>6} {r['symbol']:>8} {r['stock_name']:>8} {r['close_qfq']:>8.2f} {r['dist_ma20']:>6.1f}% {r['vol_ratio']:>4.2f} {r['pct_20d']:>5.1f}% {r['ret_t5'] or '':>6} {r['ret_t10'] or '':>7} {r['ret_t20'] or '':>7}")
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
    
    print(f"{'策略':>8} | {'信号':>5} | {'天数':>5} | {'日均':>5} | {'T20avg':>7} | {'涨率':>5} | {'>10%':>6}")
    print("-"*55)
    for r in rows:
        avg_day = r['cnt']/r['days'] if r['days'] else 0
        print(f"{r['name']:>8} | {r['cnt']:>5} | {r['days']:>5} | {avg_day:>4.1f} | {r['avg_t20']:>+6.2f}% | {r['win']:>4.1f}% | {r['win10']:>4.1f}%")
    
    total = conn.execute("SELECT COUNT(*) FROM daily_picks").fetchone()[0]
    days = conn.execute("SELECT COUNT(DISTINCT date) FROM daily_picks").fetchone()[0]
    print("-"*55)
    print(f"{'合计':>8} | {total:>5} | {days:>5} | {total/max(days,1):>4.1f} |")
    conn.close()

if __name__ == "__main__":
    cmd = sys.argv[1] if len(sys.argv) > 1 else "stats"
    if cmd == "list":
        date_arg = sys.argv[2] if len(sys.argv) > 2 else None
        strat_arg = sys.argv[3] if len(sys.argv) > 3 else None
        list_picks(date_arg, strat_arg)
    elif cmd == "today":
        list_picks(date.today().strftime("%Y-%m-%d"))
    else:
        stats()

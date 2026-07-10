"""查询trend_picks.db选股结果"""
import sqlite3, sys

DB = "/home/ubuntu/databases/trend_picks.db"

def list_picks(date_str=None, strategy=None, top=20):
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
        SELECT dp.date, s.name as strategy, dp.symbol, dp.name, 
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
    
    print(f"{'日期':>10} {'策略':>8} {'代码':>8} {'名称':>8} {'价':>8} {'距MA20':>7} {'量比':>5} {'20日涨':>6} {'T5':>6} {'T10':>7} {'T20':>7}")
    print("-"*85)
    for r in rows:
        print(f"{r['date']:>10} {r['strategy']:>8} {r['symbol']:>8} {r['name']:>8} {r['close_qfq']:>8.2f} {r['dist_ma20']:>6.1f}% {r['vol_ratio']:>4.2f} {r['pct_20d']:>5.1f}% {r['ret_t5'] or '':>6} {r['ret_t10'] or '':>7} {r['ret_t20'] or '':>7}")

def stats():
    conn = sqlite3.connect(DB)
    rows = conn.execute("""
        SELECT s.name, 
               COUNT(*) as cnt,
               ROUND(AVG(dp.ret_t20),2) as avg_t20,
               ROUND(SUM(CASE WHEN dp.ret_t20>0 THEN 1 ELSE 0 END)*100.0/COUNT(*),1) as win,
               ROUND(SUM(CASE WHEN dp.ret_t20>10 THEN 1 ELSE 0 END)*100.0/COUNT(*),1) as win10
        FROM daily_picks dp
        JOIN strategies s ON dp.strategy_id=s.id
        WHERE dp.ret_t20 IS NOT NULL
        GROUP BY dp.strategy_id
        ORDER BY cnt DESC
    """).fetchall()
    
    print(f"{'策略名':>8} | {'信号':>5} | {'T20avg':>7} | {'涨率':>5} | {'>10%':>6}")
    print("-"*38)
    for r in rows:
        print(f"{r['name']:>8} | {r['cnt']:>5} | {r['avg_t20']:>+6.2f}% | {r['win']:>4.1f}% | {r['win10']:>4.1f}%")

if __name__ == "__main__":
    cmd = sys.argv[1] if len(sys.argv) > 1 else "stats"
    if cmd == "list":
        date_arg = sys.argv[2] if len(sys.argv) > 2 else None
        strat_arg = sys.argv[3] if len(sys.argv) > 3 else None
        list_picks(date_arg, strat_arg)
    elif cmd == "today":
        from datetime import date
        list_picks(date.today().strftime("%Y-%m-%d"))
    else:
        stats()

#!/usr/bin/env python3
"""
回测：premium_b 策略 vol_ratio 阈值对比 (0.3 vs 0.5)
优化版：一次性预计算所有指标然后逐日过滤
"""
import sqlite3
from collections import defaultdict
import json

DB = '/home/ubuntu/databases/Sequoia选股.db'

def backtest(conn, vol_threshold, signal_dates, future_dates_set):
    """vol_threshold=0.3 or 0.5"""
    sql = """
        SELECT date, symbol, close_qfq AS price,
            ROUND((close_qfq/ma20-1)*100,2) AS dist_ma20,
            ROUND(volume*1.0/avg_vol_20,2) AS vol_ratio,
            ROUND((close_qfq-p20)/p20*100,2) AS pct_20d
        FROM (
            SELECT date, symbol, close_qfq,
                AVG(close_qfq) OVER (PARTITION BY symbol ORDER BY date ROWS BETWEEN 19 PRECEDING AND CURRENT ROW) AS ma20,
                AVG(close_qfq) OVER (PARTITION BY symbol ORDER BY date ROWS BETWEEN 59 PRECEDING AND CURRENT ROW) AS ma60,
                volume,
                AVG(volume) OVER (PARTITION BY symbol ORDER BY date ROWS BETWEEN 19 PRECEDING AND 1 PRECEDING) AS avg_vol_20,
                LAG(close_qfq, 20) OVER (PARTITION BY symbol ORDER BY date) AS p20
            FROM stock_daily WHERE close_qfq>0 AND date>='2025-12-01'
        )
        WHERE date BETWEEN '2026-01-01' AND '2026-06-23'
          AND price > ma20
          AND ma20 > ma60
          AND ma60 IS NOT NULL
          AND dist_ma20 BETWEEN 12 AND 25
          AND p20 IS NOT NULL
          AND ROUND((close_qfq-p20)/p20*100,2) BETWEEN 3 AND 15
          AND vol_ratio < ?
    """
    rows = conn.execute(sql, (vol_threshold,)).fetchall()
    print(f"  {vol_threshold}: 原始符合条件的信号: {len(rows)}")
    
    # 按日期分组
    by_date = defaultdict(list)
    for r in rows:
        by_date[r[0]].append(r)
    
    # 逐日计算后续收益
    # 先预加载所有 future prices
    all_symbols = set(r[1] for r in rows)
    print(f"  涉及股票数: {len(all_symbols)}")
    
    # 预先获取所有所需后续价格
    future_prices = {}  # (symbol, date) -> future close at various offsets
    for sym in all_symbols:
        fp_rows = conn.execute(
            "SELECT date, close_qfq FROM stock_daily WHERE symbol=? AND close_qfq>0 ORDER BY date",
            (sym,)
        ).fetchall()
        fp_dates = [r[0] for r in fp_rows]
        fp_values = [r[1] for r in fp_rows]
        fp_dict = {}
        for i, d in enumerate(fp_dates):
            for offset in [5, 10, 20]:
                if i + offset < len(fp_dates):
                    fp_dict[(d, offset)] = fp_values[i + offset]
        future_prices.update({(sym, k[0], k[1]): v for k, v in fp_dict.items()})
    
    print(f"  预加载 future prices: {len(future_prices)}条")
    
    picks_count = 0
    returns = {5: [], 10: [], 20: []}
    
    for dt in sorted(by_date.keys()):
        for r in by_date[dt]:
            sym = r[1]
            price = r[2]
            picks_count += 1
            for offset in [5, 10, 20]:
                fp = future_prices.get((sym, dt, offset))
                if fp and price > 0:
                    ret = (fp / price - 1) * 100
                    returns[offset].append(ret)
    
    print(f"\n  总选股数: {picks_count}")
    print(f"         数量   平均收益  中位数  胜率    最大    最小")
    for offset in [5, 10, 20]:
        rs = returns[offset]
        if rs:
            avg = sum(rs) / len(rs)
            med = sorted(rs)[len(rs)//2]
            wins = sum(1 for r in rs if r > 0)
            wr = wins / len(rs) * 100
            mx = max(rs)
            mn = min(rs)
            print(f"  T+{offset:2d}  {len(rs):4d}  {avg:+7.2f}%  {med:+6.2f}%  {wr:4.0f}%  {mx:+7.2f}%  {mn:+7.2f}%")
        else:
            print(f"  T+{offset:2d}      0     N/A     N/A   N/A     N/A     N/A")

def main():
    conn = sqlite3.connect(DB)
    
    for vh in [0.3, 0.5]:
        print(f"\n{'='*70}")
        print(f"  vol_ratio < {vh}")
        print(f"{'='*70}")
        backtest(conn, vh, None, None)
    
    conn.close()

if __name__ == '__main__':
    main()

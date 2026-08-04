#!/usr/bin/env python3
"""优化版：一次预计算所有数据，分批并行处理"""
import sqlite3, sys
from collections import defaultdict

DB = '/home/ubuntu/databases/Sequoia选股.db'

STRATEGIES = {
    '原版':        {'dl':10,'dh':20,'vl':0,'vh':0.3,'pl':5,'ph':25, 'ma60':False},
    '极品A':       {'dl':12,'dh':25,'vl':0.1,'vh':0.3,'pl':3,'ph':15, 'ma60':True},
    '极品B':       {'dl':12,'dh':25,'vl':0,'vh':0.3,'pl':3,'ph':15, 'ma60':True},
    '超缩量':      {'dl':10,'dh':20,'vl':0,'vh':0.15,'pl':3,'ph':15, 'ma60':True},
}

# 候选 vh 值
vh_candidates = [0.3, 0.5]  # 超缩量额外测 0.15

def run_backtest(conn, name, s, vh_override):
    dl, dh = s['dl'], s['dh']
    vl = s['vl']
    vh = vh_override
    pl, ph = s['pl'], s['ph']
    ma60 = s['ma60']
    
    ma60_clause = "AND price > ma20 AND ma20 > ma60 AND ma60 IS NOT NULL" if ma60 else ""
    
    sql = f"""
        SELECT date, symbol, close_qfq AS price
        FROM (
            SELECT date, symbol, close_qfq,
                AVG(close_qfq) OVER (PARTITION BY symbol ORDER BY date ROWS BETWEEN 19 PRECEDING AND CURRENT ROW) AS ma20,
                AVG(close_qfq) OVER (PARTITION BY symbol ORDER BY date ROWS BETWEEN 59 PRECEDING AND CURRENT ROW) AS ma60,
                volume,
                AVG(volume) OVER (PARTITION BY symbol ORDER BY date ROWS BETWEEN 19 PRECEDING AND 1 PRECEDING) AS avg_vol_20,
                LAG(close_qfq, 20) OVER (PARTITION BY symbol ORDER BY date) AS p20
            FROM stock_daily WHERE close_qfq>0 AND date>='2020-01-01'
        )
        WHERE date BETWEEN '2020-06-01' AND '2026-06-01'
          AND price > ma20
          AND ROUND((price/ma20-1)*100,2) BETWEEN {dl} AND {dh}
          AND p20 IS NOT NULL
          AND ROUND((price-p20)/p20*100,2) BETWEEN {pl} AND {ph}
          AND ROUND(volume*1.0/avg_vol_20,2) >= {vl}
          AND ROUND(volume*1.0/avg_vol_20,2) < {vh}
          {ma60_clause}
    """
    return conn.execute(sql).fetchall()

def calc_returns(conn, signals):
    """批量计算后续收益"""
    if not signals:
        return {5:[],10:[],20:[]}
    
    # 按 symbol 分组
    by_sym = defaultdict(list)
    for r in signals:
        by_sym[r[1]].append((r[0], r[2]))
    
    returns = {5:[],10:[],20:[]}
    
    for sym, s_dates in by_sym.items():
        # 一次取所有 future prices
        fp_rows = conn.execute(
            "SELECT date, close_qfq FROM stock_daily WHERE symbol=? AND date>? AND close_qfq>0 ORDER BY date",
            (sym, min(r[0] for r in s_dates))
        ).fetchall()
        fp_dates = [r[0] for r in fp_rows]
        fp_vals = [r[1] for r in fp_rows]
        
        for sig_date, price in s_dates:
            # 找 sig_date 在 fp_dates 中的位置
            try:
                idx = fp_dates.index(sig_date)
            except ValueError:
                continue
            for offset in [5,10,20]:
                if idx + offset < len(fp_vals):
                    ret = (fp_vals[idx+offset] / price - 1) * 100
                    returns[offset].append(ret)
    
    return returns

def print_results(results, label):
    print(f"\n  {label}")
    for name, vh, r in results:
        line = f"  {name:>8}  vh={vh:<5} 信号{r['picks']:>6} 天数{r['days']:>5} |"
        for off in [5,10,20]:
            rr = r['returns'].get(off)
            if rr and rr['n'] > 0:
                line += f" T+{off}:{rr['avg']:+6.2f}%({rr['wr']:>4.0f}%)"
            else:
                line += f" T+{off}:  N/A"
        print(line)

def main():
    conn = sqlite3.connect(DB)
    conn.execute("PRAGMA temp_store = MEMORY")
    
    print(f"{'='*100}")
    print(f"  多策略趋势缩量选股 — 回测对比 (2020-06 ~ 2026-06, 约6年)")
    print(f"{'='*100}")
    
    all_results = []
    
    for name, s in STRATEGIES.items():
        vh_list = vh_candidates[:]
        if name == '超缩量':
            vh_list = [0.15] + vh_list  # 额外测原版0.15
        
        for vh_actual in vh_list:
            print(f"\n  ▶ {name} vh={vh_actual} ... ", end="", flush=True)
            rows = run_backtest(conn, name, s, vh_actual)
            picks = len(rows)
            print(f"原始信号{picks}个, 计算收益... ", end="", flush=True)
            
            returns = calc_returns(conn, rows)
            
            by_date = set(r[0] for r in rows)
            result = {
                'picks': picks,
                'days': len(by_date),
                'returns': {}
            }
            for offset in [5,10,20]:
                rs = returns[offset]
                if rs:
                    avg = sum(rs)/len(rs)
                    med = sorted(rs)[len(rs)//2]
                    wins = sum(1 for r in rs if r>0)
                    result['returns'][offset] = {
                        'n': len(rs), 'avg': round(avg,2), 'med': round(med,2),
                        'wr': round(wins/len(rs)*100,1)
                    }
            
            all_results.append((name, vh_actual, result))
            print("OK")
    
    print(f"\n{'='*100}")
    print_results(all_results, "结果汇总")
    print(f"\n{'='*100}")
    print(f"  参数说明:")
    print(f"  原版:   dist 10~20%, vol 0~vh, pct 5~25%, 无MA60")
    print(f"  极品A:  dist 12~25%, vol 0.1~vh, pct 3~15%, ma60")
    print(f"  极品B:  dist 12~25%, vol 0~vh, pct 3~15%, ma60")
    print(f"  超缩量: dist 10~20%, vol 0~vh, pct 3~15%, ma60")
    print(f"{'='*100}")
    
    conn.close()

if __name__ == '__main__':
    main()

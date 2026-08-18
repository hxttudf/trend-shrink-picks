#!/usr/bin/env python3
"""重建缠论日期统计缓存(chanlun_dates_cache): 日期+类型+ETF口径的信号数
在 bc_chanlun_daily.py 每日计算完成后调用, 供 /api/chanlun/dates 直接读表(毫秒级)"""
import sqlite3, sys
from datetime import datetime

TREND_DB = '/home/ubuntu/databases/trend_picks.db'
TYPES = ['', '一买', '二买', '三买', '二三买', '二三卖', '一卖', '二卖', '三卖', 'd3', 'w30']
ETF_COND = "(symbol LIKE '5%' OR symbol LIKE '15%' OR symbol LIKE '16%')"


def main():
    conn = sqlite3.connect(TREND_DB, timeout=60)
    conn.execute("CREATE TABLE IF NOT EXISTS chanlun_dates_cache "
                 "(signal_date TEXT, typ TEXT, etf INTEGER, total INTEGER, updated_at TEXT, "
                 "PRIMARY KEY(signal_date, typ, etf))")
    now = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
    total_rows = 0
    for etf in (0, 1):
        cond = ETF_COND if etf else f"NOT {ETF_COND}"
        jcond = "(a.symbol LIKE '5%' OR a.symbol LIKE '15%' OR a.symbol LIKE '16%')" if etf \
            else "NOT (a.symbol LIKE '5%' OR a.symbol LIKE '15%' OR a.symbol LIKE '16%')"
        for typ in TYPES:
            if typ == '二三买':
                sql = (f"SELECT a.signal_date, COUNT(DISTINCT a.symbol) FROM chanlun_signals a "
                       f"JOIN chanlun_signals b ON a.symbol=b.symbol AND a.signal_date=b.signal_date "
                       f"WHERE a.status='ok' AND b.status='ok' AND a.signal_type='二买' AND b.signal_type='三买' "
                       f"AND {jcond} GROUP BY a.signal_date")
            elif typ == '二三卖':
                sql = (f"SELECT a.signal_date, COUNT(DISTINCT a.symbol) FROM chanlun_signals a "
                       f"JOIN chanlun_signals b ON a.symbol=b.symbol AND a.signal_date=b.signal_date "
                       f"WHERE a.status='ok' AND b.status='ok' AND a.signal_type='二卖' AND b.signal_type='三卖' "
                       f"AND {jcond} GROUP BY a.signal_date")
            elif typ == 'd3':
                sql = (f"SELECT signal_date, COUNT(*) FROM chanlun_signals WHERE d3=1 AND status='ok' AND {cond} "
                       f"GROUP BY signal_date")
            elif typ == 'w30':
                sql = (f"SELECT signal_date, COUNT(*) FROM chanlun_signals WHERE w30=1 AND status='ok' AND {cond} "
                       f"GROUP BY signal_date")
            elif typ:
                sql = (f"SELECT signal_date, COUNT(*) FROM chanlun_signals WHERE signal_type=? AND status='ok' "
                       f"AND {cond} GROUP BY signal_date")
                rows = conn.execute(sql, (typ,)).fetchall()
                conn.executemany("INSERT OR REPLACE INTO chanlun_dates_cache VALUES (?,?,?,?,?)",
                                 [(d, typ, etf, n, now) for d, n in rows])
                total_rows += len(rows)
                continue
            else:
                sql = (f"SELECT signal_date, COUNT(*) FROM chanlun_signals WHERE status='ok' AND {cond} "
                       f"GROUP BY signal_date")
            rows = conn.execute(sql).fetchall()
            conn.executemany("INSERT OR REPLACE INTO chanlun_dates_cache VALUES (?,?,?,?,?)",
                             [(d, typ, etf, n, now) for d, n in rows])
            total_rows += len(rows)
    conn.commit()
    conn.close()
    print(f'日期统计缓存重建完成: {total_rows} 行 (11类型×2口径)')


if __name__ == '__main__':
    main()

#!/usr/bin/env python3
"""全市场历史缠论信号扫描: 所有股票全部历史一二三买/一二三卖 → 落DB
用法: python3 bc_chanlun_history.py [--recreate]
"""
import sqlite3
import sys
import time

sys.path.insert(0, "/home/ubuntu/trend-shrink-picks")
from chanlun_full import merge_inclusion, calc_bi, calc_segments, calc_zhongshu_bi, macd_data, find_all_signals

SEQ_DB = "/home/ubuntu/Sequoia-X-a/data/sequoia_v2.db"
PICKS_DB = "/home/ubuntu/databases/trend_picks.db"
BATCH = 300
MIN_BARS = 150


def get_conn():
    conn = sqlite3.connect(PICKS_DB, timeout=30)
    conn.execute("""CREATE TABLE IF NOT EXISTS chanlun_signals (
        symbol TEXT NOT NULL,
        name TEXT,
        signal_type TEXT NOT NULL,
        signal_date TEXT NOT NULL,
        price REAL,
        ref_zd REAL,
        ref_zg REAL,
        PRIMARY KEY (symbol, signal_type, signal_date))""")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_chanlun_date ON chanlun_signals(signal_date)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_chanlun_type ON chanlun_signals(signal_type)")
    conn.commit()
    return conn


def main():
    recreate = "--recreate" in sys.argv
    seq = sqlite3.connect(SEQ_DB)
    syms = [r[0] for r in seq.execute(
        "SELECT DISTINCT symbol FROM stock_daily WHERE close_qfq>0 AND date>='2019-01-01'").fetchall()]
    names = {}
    for r in seq.execute("SELECT symbol, name FROM stock_basics WHERE date=(SELECT MAX(date) FROM stock_basics)"):
        names[r[0]] = r[1]

    picks = get_conn()
    if recreate:
        picks.execute("DELETE FROM chanlun_signals")
        picks.commit()
        print("已清空旧信号", flush=True)

    print(f"扫描 {len(syms)} 只 (全历史买卖点)...", flush=True)
    t0 = time.time()
    total = 0
    for batch_i in range(0, len(syms), BATCH):
        batch = syms[batch_i:batch_i + BATCH]
        rows = seq.execute(
            "SELECT symbol, date, high, low, close, close_qfq FROM stock_daily "
            f"WHERE symbol IN ({','.join('?' * len(batch))}) AND close_qfq>0 ORDER BY symbol, date",
            batch).fetchall()
        per = {}
        for r in rows:
            per.setdefault(r[0], []).append(r)
        for sym in batch:
            data = per.get(sym, [])
            if len(data) < MIN_BARS:
                continue
            qf = []
            for r in data:
                ratio = r[5] / r[4] if r[4] else 1
                qf.append([r[1], r[2] * ratio, r[3] * ratio, r[5]])
            try:
                merged = merge_inclusion(qf)
                bi = calc_bi(merged)
                if len(bi) < 8:
                    continue
                zs_list = calc_zhongshu_bi(bi)
                dif, dea, hist = macd_data([r[3] for r in qf])
                sigs = find_all_signals(bi, zs_list, dif, merged)
            except Exception:
                continue
            if not sigs:
                continue
            nm = names.get(sym, "?")
            if 'ST' in nm.upper():
                continue
            cur = []
            for typ, d, p, zd, zg in sigs:
                cur.append((sym, nm, typ, d, p, zd, zg))
            picks.executemany(
                "INSERT OR REPLACE INTO chanlun_signals "
                "(symbol, name, signal_type, signal_date, price, ref_zd, ref_zg) "
                "VALUES (?,?,?,?,?,?,?)", cur)
            total += len(cur)
        picks.commit()
        if batch_i % (BATCH * 5) == 0:
            print(f"  批{batch_i//BATCH+1}: 累计{total} 条, {time.time()-t0:.0f}s", flush=True)
    picks.commit()
    picks.close()
    seq.close()
    print(f"完成: {total} 条信号, 耗时 {time.time()-t0:.0f}s")


if __name__ == "__main__":
    main()

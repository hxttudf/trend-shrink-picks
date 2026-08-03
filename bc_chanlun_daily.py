#!/usr/bin/env python3
"""每日缠论信号更新(增量): 扫描最近N日全市场信号 → 写chanlun_signals表
先删最近窗口内的旧信号(笔会随新K线修正), 再写入新计算信号
用法: python3 bc_chanlun_daily.py [window]
stdout输出当日摘要(供cron no_agent交付)"""
import sqlite3
import sys
import time

sys.path.insert(0, "/home/ubuntu/trend-shrink-picks")
from chanlun_full import analyze

SEQ_DB = "/home/ubuntu/Sequoia-X-a/data/sequoia_v2.db"
PICKS_DB = "/home/ubuntu/databases/trend_picks.db"
BATCH = 300
WINDOW = int(sys.argv[1]) if len(sys.argv) > 1 else 7


def main():
    seq = sqlite3.connect(SEQ_DB)
    syms = [r[0] for r in seq.execute(
        "SELECT DISTINCT symbol FROM stock_daily WHERE close_qfq>0 AND date>='2024-01-01'").fetchall()]
    names = {}
    for r in seq.execute("SELECT symbol, name FROM stock_basics WHERE date=(SELECT MAX(date) FROM stock_basics)"):
        names[r[0]] = r[1]

    picks = sqlite3.connect(PICKS_DB, timeout=30)
    picks.execute("""CREATE TABLE IF NOT EXISTS chanlun_signals (
        symbol TEXT NOT NULL, name TEXT, signal_type TEXT NOT NULL, signal_date TEXT NOT NULL,
        price REAL, ref_zd REAL, ref_zg REAL,
        PRIMARY KEY (symbol, signal_type, signal_date))""")
    picks.execute("CREATE INDEX IF NOT EXISTS idx_chanlun_date ON chanlun_signals(signal_date)")

    # 窗口内旧信号清空(笔修正后可能变化)
    rows = seq.execute("SELECT MAX(date) FROM stock_daily").fetchone()
    last_date = rows[0] if rows and rows[0] else ""
    picks.execute("DELETE FROM chanlun_signals WHERE signal_date > date(?, '-20 day')", (last_date,))
    picks.commit()

    t0 = time.time()
    total = 0
    by_type = {}
    for batch_i in range(0, len(syms), BATCH):
        batch = syms[batch_i:batch_i + BATCH]
        for sym in batch:
            try:
                d = analyze(sym, window_days=WINDOW)
            except Exception:
                continue
            if d.get("error"):
                continue
            nm = names.get(sym, "?")
            if 'ST' in nm.upper():
                continue
            cur = []
            for bs in d.get("buy_sell", []):
                cur.append((sym, nm, bs['type'], bs['time'], bs['price'], 0, 0))
                by_type[bs['type']] = by_type.get(bs['type'], 0) + 1
            if cur:
                picks.executemany(
                    "INSERT OR REPLACE INTO chanlun_signals "
                    "(symbol, name, signal_type, signal_date, price, ref_zd, ref_zg) "
                    "VALUES (?,?,?,?,?,?,?)", cur)
                total += len(cur)
        picks.commit()
        if batch_i % (BATCH * 5) == 0:
            print(f"  批{batch_i//BATCH+1}: 累计{total}条, {time.time()-t0:.0f}s", flush=True)

    picks.commit()
    picks.close()
    seq.close()
    # 摘要(交付内容)
    parts = " ".join(f"{k}{v}" for k, v in sorted(by_type.items()))
    print(f"📐 缠论每日更新完成: {total}条信号 ({parts}) 耗时{time.time()-t0:.0f}s")


if __name__ == "__main__":
    main()

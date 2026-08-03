#!/usr/bin/env python3
"""全市场扫描(完整缠论·日线级别): 最近N交易日出现 二买/三买 的股票
输出: 信号 + 中枢 + 结构链(一买/二买历史, 验证完整性)"""
import sqlite3
import sys
sys.path.insert(0, "/home/ubuntu/trend-shrink-picks")
from chanlun_full import analyze

DB = "/home/ubuntu/Sequoia-X-a/data/sequoia_v2.db"
BATCH = 300
WINDOW = int(sys.argv[1]) if len(sys.argv) > 1 else 7

def main():
    conn = sqlite3.connect(DB)
    syms = [r[0] for r in conn.execute(
        "SELECT DISTINCT symbol FROM stock_daily WHERE close_qfq>0 "
        "AND date>='2024-01-01' AND symbol NOT LIKE '%.SH' AND symbol NOT LIKE '%.BJ'").fetchall()]
    names = {}
    for r in conn.execute("SELECT symbol, name FROM stock_basics WHERE date=(SELECT MAX(date) FROM stock_basics)"):
        names[r[0]] = r[1]
    print(f"扫描 {len(syms)} 只 (完整缠论, {WINDOW}日窗口)...", flush=True)

    all_hits = []
    for batch_i in range(0, len(syms), BATCH):
        batch = syms[batch_i:batch_i + BATCH]
        for sym in batch:
            try:
                d = analyze(sym, window_days=WINDOW)
            except Exception:
                continue
            if d.get("error"):
                continue
            for bs in d.get("buy_sell", []):
                nm = names.get(sym, "?")
                if 'ST' in nm.upper():
                    continue
                chain = ",".join(f"{c['type']}{c['time']}@{c['price']}" for c in d.get('chain', []))
                zs = d.get('last_zhongshu') or {}
                all_hits.append((sym, nm, bs['type'], bs['time'], bs['price'],
                                 f"{zs.get('zd', 0):.2f}~{zs.get('zg', 0):.2f}", chain))
        print(f"  批{batch_i//BATCH+1}: 累计{len(all_hits)}", flush=True)

    conn.close()
    all_hits.sort(key=lambda x: (x[3], x[0]))
    print(f"\n===== 最近{WINDOW}交易日 二买/三买 (完整缠论·日线级别): {len(all_hits)}个 =====")
    for sym, name, typ, date, price, zs, chain in all_hits:
        print(f"  {sym} {name:8s} {typ} {date} @{price:.2f} | 中枢{zs} | 链:{chain}")

if __name__ == "__main__":
    main()

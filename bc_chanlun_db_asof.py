#!/usr/bin/env python3
"""DB信号替换为"滚动确认版"(无未来函数):
对每只股票每个笔端点, 只用截止确认日(端点+2)的数据滚动重算笔/中枢/信号
→ 只保留"当时可见"的信号(买卖点不知道未来K线)
→ DELETE该股全部旧信号 + INSERT滚动集
备份: trend_picks.db.bak_pre_asof (已手动cp)
运行约15-20分钟, 不停服(WAL安全)"""
import sqlite3
import sys
from datetime import datetime

sys.path.insert(0, "/home/ubuntu/trend-shrink-picks")
from chanlun_full import merge_inclusion, calc_bi, calc_zhongshu_bi, macd_data, find_all_signals

SEQ_DB = "/home/ubuntu/Sequoia-X-a/data/sequoia_v2.db"
PICKS_DB = "/home/ubuntu/databases/trend_picks.db"
START = "2020-01-01"
BATCH = 400


def ts():
    return datetime.now().strftime("%H:%M:%S")


def main():
    seq = sqlite3.connect(SEQ_DB)
    picks = sqlite3.connect(PICKS_DB)
    syms = [r[0] for r in seq.execute(
        "SELECT DISTINCT symbol FROM stock_daily WHERE close_qfq>0 AND date>='2019-01-01'").fetchall()]
    print(f"[{ts()}] 全市场 {len(syms)} 只, 滚动重建开始", flush=True)

    kept, deleted, skipped = 0, 0, 0
    t0 = datetime.now()
    for bi_i in range(0, len(syms), BATCH):
        batch = syms[bi_i:bi_i + BATCH]
        rows_all = seq.execute(
            "SELECT symbol, date, open, high, low, close, close_qfq FROM stock_daily "
            f"WHERE symbol IN ({','.join('?' * len(batch))}) AND close_qfq>0 ORDER BY symbol, date",
            batch).fetchall()
        per = {}
        for r in rows_all:
            per.setdefault(r[0], []).append(r)

        for sym in batch:
            rows = per.get(sym, [])
            if len(rows) < 100:
                skipped += 1
                continue
            qf = [[r[1], r[2] * (r[6] / r[5]), r[3] * (r[6] / r[5]), r[4] * (r[6] / r[5]), r[6]] for r in rows]
            dates = [r[1] for r in rows]
            d2i = {d: i for i, d in enumerate(dates)}
            n = len(rows)

            merged_all = merge_inclusion([[x[0], x[2], x[3], x[4]] for x in qf])
            bi_all = calc_bi(merged_all)
            endpoints = sorted({merged_all[b[0]][0] for b in bi_all if merged_all[b[0]][0] >= START})

            rolling = set()  # (type, date, price)
            for d in endpoints:
                idx = d2i.get(d)
                if idx is None or idx + 2 > n:
                    continue
                cut = idx + 2
                if cut < 30:
                    continue
                sub = qf[:cut]
                try:
                    m2 = merge_inclusion([[x[0], x[2], x[3], x[4]] for x in sub])
                    b2 = calc_bi(m2)
                    z2 = calc_zhongshu_bi(b2)
                    df2 = macd_data([x[4] for x in sub])[0]
                    s2 = find_all_signals(b2, z2, df2, m2)
                except Exception:
                    continue
                for t, sd, p, _, _ in s2:
                    if sd == d:
                        rolling.add((t, sd, round(p, 2)))

            # 替换该股信号(保留原name)
            row = picks.execute("SELECT name FROM chanlun_signals WHERE symbol=? LIMIT 1", (sym,)).fetchone()
            nm = row[0] if row else sym
            picks.execute("DELETE FROM chanlun_signals WHERE symbol=?", (sym,))
            if rolling:
                picks.executemany(
                    "INSERT INTO chanlun_signals (symbol, name, signal_type, signal_date, price) "
                    "VALUES (?, ?, ?, ?, ?)",
                    [(sym, nm, t, sd, p) for t, sd, p in rolling])
            picks.commit()
            kept += len(rolling)
            deleted += len(rolling)

        el = (datetime.now() - t0).total_seconds()
        print(f"[{ts()}] 批{bi_i//BATCH+1}: {min(bi_i+BATCH,len(syms))}/{len(syms)}只 | 累计保留{kept} | 耗时{el/60:.0f}分", flush=True)

    seq.close()
    picks.close()
    print(f"[{ts()}] 完成: 保留{kept}条滚动信号, 跳过{skipped}只(数据不足)")


if __name__ == "__main__":
    main()

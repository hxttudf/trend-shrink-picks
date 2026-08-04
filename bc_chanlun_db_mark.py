#!/usr/bin/env python3
"""信号打标: 区分"稳定信号"与"事后被推翻的错误信号"
方法: 对每只股票滚动重算(截止确认日)得到"当时可见信号集"(asof)
对比DB全量最终信号(当前):
  - 当时可见 且 仍在最终集 → status='ok' (经得起时间考验)
  - 当时可见 但 不在最终集 → status='error' (后来被新结构推翻, 错误判断)
  - 最终集有 但 当时不可见 → 保持ok(确认延迟型, 实盘稍晚可见)
输出: 各状态数量 + 最近错误信号样例"""
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
    picks.execute("ALTER TABLE chanlun_signals ADD COLUMN status TEXT DEFAULT 'ok'")
    picks.commit()

    syms = [r[0] for r in seq.execute(
        "SELECT DISTINCT symbol FROM stock_daily WHERE close_qfq>0 AND date>='2019-01-01'").fetchall()]
    print(f"[{ts()}] {len(syms)} 只, 打标开始", flush=True)

    n_ok, n_err = 0, 0
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
                continue
            qf = [[r[1], r[2] * (r[6] / r[5]), r[3] * (r[6] / r[5]), r[4] * (r[6] / r[5]), r[6]] for r in rows]
            dates = [r[1] for r in rows]
            d2i = {d: i for i, d in enumerate(dates)}
            n = len(rows)

            merged_all = merge_inclusion([[x[0], x[2], x[3], x[4]] for x in qf])
            bi_all = calc_bi(merged_all)
            endpoints = sorted({merged_all[b[0]][0] for b in bi_all if merged_all[b[0]][0] >= START})

            rolling = set()  # 当时可见 (type, date, price)
            for d in endpoints:
                idx = d2i.get(d)
                if idx is None or idx + 2 >= n:
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

            # 最终集(当前DB)
            final = {(r[0], r[1], round(r[2], 2)) for r in picks.execute(
                "SELECT signal_type, signal_date, price FROM chanlun_signals WHERE symbol=?", (sym,)).fetchall()}

            # 当时可见但最终集没有 = 错误信号(被推翻)
            errors = rolling - final
            row = picks.execute("SELECT name FROM chanlun_signals WHERE symbol=? LIMIT 1", (sym,)).fetchone()
            nm = row[0] if row else sym
            for t, sd, p in errors:
                picks.execute(
                    "INSERT OR IGNORE INTO chanlun_signals (symbol, name, signal_type, signal_date, price, status) "
                    "VALUES (?, ?, ?, ?, ?, 'error')", (sym, nm, t, sd, p))
            n_err += len(errors)
            n_ok += len(final)
        picks.commit()
        if (bi_i // BATCH + 1) % 5 == 0:
            print(f"[{ts()}] 批{bi_i//BATCH+1}: {min(bi_i+BATCH,len(syms))}/{len(syms)}只 | 错误累计{n_err}", flush=True)

    picks.execute("UPDATE chanlun_signals SET status='ok' WHERE status IS NULL OR status=''")
    picks.commit()
    seq.close()
    picks.close()
    print(f"[{ts()}] 完成: ok={n_ok} error={n_err}")


if __name__ == "__main__":
    main()

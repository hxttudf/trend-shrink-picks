#!/usr/bin/env python3
"""DB = 滚动确认版(当时可见信号) + 全量信号验证打标
逻辑(用户确认的方案):
  1. 滚动算(截止确认日) → rolling_set: 当时报过的信号(无未来函数, 可能出错)
  2. 全量算(全部数据)   → final_set:   事后真相
  3. DB存入 rolling_set (当时报过的全部保留)
  4. errors = rolling_set - final_set → status='error' (当时判断错误, 被推翻)
     ok    = rolling_set ∩ final_set  → status='ok'   (经得起验证)
  5. stockscope: 看到"当时报的" + 哪些后来被推翻(红标)
运行约20分钟, 不停服"""
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
    try:
        picks.execute("ALTER TABLE chanlun_signals ADD COLUMN status TEXT DEFAULT 'ok'")
        picks.commit()
    except Exception:
        pass  # 已存在

    syms = [r[0] for r in seq.execute(
        "SELECT DISTINCT symbol FROM stock_daily WHERE close_qfq>0 AND date>='2019-01-01'").fetchall()]
    print(f"[{ts()}] {len(syms)} 只: 滚动确认版+全量打标 开始", flush=True)

    n_total, n_err = 0, 0
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
            # r: date, open, high, low, close, close_qfq
            qf = [[r[1], r[2] * (r[6] / r[5]), r[3] * (r[6] / r[5]), r[4] * (r[6] / r[5]), r[6]] for r in rows]
            dates = [r[1] for r in rows]
            d2i = {d: i for i, d in enumerate(dates)}
            n = len(rows)

            # 1) 全量最终信号(事后真相)
            merged_all = merge_inclusion([[x[0], x[2], x[3], x[4]] for x in qf])
            bi_all = calc_bi(merged_all)
            zs_all = calc_zhongshu_bi(bi_all)
            dif_all = macd_data([x[4] for x in qf])[0]
            sigs_all = find_all_signals(bi_all, zs_all, dif_all, merged_all)
            final_set = {(t, sd, round(p, 2)) for t, sd, p, _, _ in sigs_all if sd >= START}

            # 2) 滚动确认信号(当时可见)
            endpoints = sorted({merged_all[b[0]][0] for b in bi_all if merged_all[b[0]][0] >= START})
            rolling = set()
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

            # 3) DB存滚动版 + 打标
            row = picks.execute("SELECT name FROM chanlun_signals WHERE symbol=? LIMIT 1", (sym,)).fetchone()
            nm = row[0] if row else sym
            picks.execute("DELETE FROM chanlun_signals WHERE symbol=?", (sym,))
            for t, sd, p in rolling:
                status = 'ok' if (t, sd, p) in final_set else 'error'
                picks.execute(
                    "INSERT INTO chanlun_signals (symbol, name, signal_type, signal_date, price, status) "
                    "VALUES (?, ?, ?, ?, ?, ?)", (sym, nm, t, sd, p, status))
                if status == 'error':
                    n_err += 1
                n_total += 1
        picks.commit()
        if (bi_i // BATCH + 1) % 5 == 0:
            print(f"[{ts()}] 批{bi_i//BATCH+1}: {min(bi_i+BATCH,len(syms))}/{len(syms)}只 | 累计{n_total} 错误{n_err}", flush=True)

    seq.close()
    picks.close()
    print(f"[{ts()}] 完成: 滚动信号{n_total}条, 其中被推翻(error)={n_err}")


if __name__ == "__main__":
    main()

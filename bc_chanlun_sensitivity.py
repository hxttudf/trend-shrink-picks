#!/usr/bin/env python3
"""参数敏感性扫描(轻量版): 抽样800只, 分批加载, 内存<1GB
max_gap(时效) × amp_lim(幅度) 对胜率的影响
结论: 各组合胜率差<2pp=稳健(当前值合理); >3pp=敏感(需重定)"""
import sqlite3
import sys
import time
import random

sys.path.insert(0, "/home/ubuntu/trend-shrink-picks")
from chanlun_full import merge_inclusion, calc_bi, calc_zhongshu_bi, macd_data, find_all_signals

SEQ_DB = "/home/ubuntu/Sequoia-X-a/data/sequoia_v2.db"
START = "2020-01-01"
SAMPLE = 800
BATCH = 200

COMBOS = [(40, 1.5), (60, 2.0), (90, 2.5), (100000, 100.0)]


def main():
    random.seed(42)
    seq = sqlite3.connect(SEQ_DB)
    syms = [r[0] for r in seq.execute(
        "SELECT DISTINCT symbol FROM stock_daily WHERE close_qfq>0 AND date>='2019-01-01'").fetchall()]
    sample = random.sample(syms, min(SAMPLE, len(syms)))
    print(f"抽样 {len(sample)} 只", flush=True)

    results = {}
    for mg, al in COMBOS:
        t0 = time.time()
        sigs_all = []
        for batch_i in range(0, len(sample), BATCH):
            batch = sample[batch_i:batch_i + BATCH]
            rows = seq.execute(
                "SELECT symbol, date, open, high, low, close, close_qfq FROM stock_daily "
                f"WHERE symbol IN ({','.join('?' * len(batch))}) AND close_qfq>0 ORDER BY symbol, date",
                batch).fetchall()
            per = {}
            for r in rows:
                per.setdefault(r[0], []).append(r)
            for sym in batch:
                bars = per.get(sym, [])
                if len(bars) < 30:
                    continue
                qf = []
                for r in bars:
                    ratio = r[6] / r[5] if r[5] else 1
                    qf.append([r[1], r[2] * ratio, r[3] * ratio, r[4] * ratio, r[6]])
                try:
                    merged = merge_inclusion([[x[0], x[2], x[3], x[4]] for x in qf])
                    bi = calc_bi(merged)
                    if len(bi) < 8:
                        continue
                    zs = calc_zhongshu_bi(bi)
                    dif = macd_data([x[4] for x in qf])[0]
                    sigs = find_all_signals(bi, zs, dif, merged, max_gap=mg, amp_lim=al)
                except Exception:
                    continue
                if not sigs:
                    continue
                dates = [r[1] for r in bars]
                d2i = {d: i for i, d in enumerate(dates)}
                qfq_close = [x[4] for x in qf]
                qfq_open = [x[1] for x in qf]
                for typ, sdate, price, zd, zg in sigs:
                    if sdate < START:
                        continue
                    bi2 = d2i.get(sdate)
                    if bi2 is None or bi2 + 1 >= len(bars):
                        continue
                    buy_i = bi2 + 1
                    bp = qfq_open[buy_i]
                    if bp <= 0:
                        continue
                    r10 = qfq_close[buy_i + 9] / bp - 1 if buy_i + 9 < len(bars) else None
                    sigs_all.append((typ, r10))
        line = f"max_gap={mg:>6} amp={al:<5}: "
        for typ in ["一买", "二买", "三买"]:
            rs = [x[1] for x in sigs_all if x[0] == typ and x[1] is not None]
            if rs:
                win = sum(1 for v in rs if v > 0) / len(rs) * 100
                avg = sum(rs) / len(rs) * 100
                line += f" | {typ} n={len(rs):5d} 胜{win:4.1f}% 均{avg:+5.2f}%"
        results[(mg, al)] = line
        print(line, f"({time.time()-t0:.0f}s)", flush=True)

    print("\n===== 结论 =====")
    print("各组合胜率差<2pp=稳健(当前值60/2.0合理); >3pp=敏感(数字需重定)")
    seq.close()


if __name__ == "__main__":
    main()

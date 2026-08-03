#!/usr/bin/env python3
"""未来函数检验: 最终信号 vs 滚动(asof)信号
对每个最终信号, 用截止其确认日的数据重算, 看该信号"当时是否存在"
输出: ①事后修正率 ②"当时存在"信号的胜率 vs 全部信号胜率(差异=未来函数影响)
抽样100只(2020年后信号), 约2-4分钟"""
import sqlite3
import random
import sys

sys.path.insert(0, "/home/ubuntu/trend-shrink-picks")
from chanlun_full import merge_inclusion, calc_bi, calc_zhongshu_bi, macd_data, find_all_signals

SEQ_DB = "/home/ubuntu/Sequoia-X-a/data/sequoia_v2.db"
START = "2020-01-01"
SAMPLE = 100
HOLD10 = 10


def main():
    random.seed(7)
    seq = sqlite3.connect(SEQ_DB)
    syms = [r[0] for r in seq.execute(
        "SELECT DISTINCT symbol FROM stock_daily WHERE close_qfq>0 AND date>='2019-01-01'").fetchall()]
    sample = random.sample(syms, min(SAMPLE, len(syms)))
    print(f"抽样 {len(sample)} 只", flush=True)

    existed, missing = [], []
    for si, sym in enumerate(sample):
        rows = seq.execute(
            "SELECT date, open, high, low, close, close_qfq FROM stock_daily "
            "WHERE symbol=? AND close_qfq>0 ORDER BY date", (sym,)).fetchall()
        if len(rows) < 60:
            continue
        dates = [r[0] for r in rows]
        d2i = {d: i for i, d in enumerate(dates)}
        # r: date, open, high, low, close, close_qfq
        qfq_open = [r[1] * (r[5] / r[4]) for r in rows]
        qfq_close = [r[5] for r in rows]
        qf = [[r[0], r[1] * (r[5] / r[4]), r[2] * (r[5] / r[4]), r[3] * (r[5] / r[4]), r[5]] for r in rows]
        merged = merge_inclusion([[x[0], x[2], x[3], x[4]] for x in qf])
        bi = calc_bi(merged)
        zs = calc_zhongshu_bi(bi)
        dif = macd_data([x[4] for x in qf])[0]
        sigs = find_all_signals(bi, zs, dif, merged)
        sigs = [s for s in sigs if s[1] >= START]

        for typ, sdate, price, zd, zg in sigs:
            if typ not in ("一买", "二买", "三买"):
                continue  # 只统计买点(卖点收益为负会污染混合胜率)
            bi2 = d2i.get(sdate)
            if bi2 is None or bi2 + 1 >= len(rows):
                continue
            buy_i = bi2 + 2  # 严格T+2
            if buy_i >= len(rows):
                continue
            r10 = qfq_close[buy_i + HOLD10 - 1] / qfq_open[buy_i] - 1 if buy_i + HOLD10 - 1 < len(rows) else None
            # 滚动重算: 只用截止确认日(信号日+1)的数据
            cut = bi2 + 2  # 截止确认日后1根(含确认日及之后1根, 保证分型确认完整)
            if cut < 30:
                continue
            sub = qf[:cut]
            try:
                m2 = merge_inclusion([[x[0], x[2], x[3], x[4]] for x in sub])
                b2 = calc_bi(m2)
                z2 = calc_zhongshu_bi(b2)
                d2 = macd_data([x[4] for x in sub])[0]
                s2 = find_all_signals(b2, z2, d2, m2)
            except Exception:
                continue
            hit = any(t == typ and d == sdate and abs(p - price) < 0.01 for t, d, p, _, _ in s2)
            if hit:
                existed.append(r10)
            else:
                missing.append(r10)
        if (si + 1) % 25 == 0:
            print(f"  已处理{si+1}只", flush=True)

    def stat(name, arr):
        n = len([x for x in arr if x is not None])
        win = sum(1 for x in arr if x is not None and x > 0) / n * 100
        avg = sum(x for x in arr if x is not None) / n * 100
        print(f"  {name}: n={n} 胜率{win:.1f}% 均收益{avg:+.2f}%")

    print("\n===== 未来函数检验结果 (T+10, 严格T+2买入) =====")
    stat("当时存在的信号(无未来函数)", existed)
    stat("事后才出现的信号(被修正)", missing)
    tot = [x for x in existed + missing if x is not None]
    stat("全部最终信号(含修正)", tot)
    miss_rate = len([x for x in missing if x is not None]) / len([x for x in existed + missing if x is not None]) * 100
    print(f"\n事后修正率: {miss_rate:.1f}% (最终信号中当时不存在的比例)")
    seq.close()


if __name__ == "__main__":
    main()

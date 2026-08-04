#!/usr/bin/env python3
"""严格滚动回测(无未来函数): 每个信号只用"截止其确认日"的K线重算笔/中枢/信号
- 对每只股票每个笔端点: 用 qf[:端点+2] 滚动重算 → 收集"当时可见"的信号
- 买卖点两端都是滚动确认的(中枢/笔绝不看未来K线)
- 买入: 信号日+2开盘(严格T+2) | 卖出: T+10/T+20/止盈8%止损5%/对称卖点(滚动卖点)
输出: 对比DB最终信号回测 → 未来函数影响的真实幅度
抽样400只, 约15-25分钟"""
import sqlite3
import random
import sys
from datetime import datetime

sys.path.insert(0, "/home/ubuntu/trend-shrink-picks")
from chanlun_full import merge_inclusion, calc_bi, calc_zhongshu_bi, macd_data, find_all_signals

SEQ_DB = "/home/ubuntu/Sequoia-X-a/data/sequoia_v2.db"
START = "2020-01-01"
SAMPLE = 400
HOLD10, HOLD20 = 10, 20
TP, SL = 1.08, 0.95


def ts():
    return datetime.now().strftime("%H:%M:%S")


def main():
    random.seed(11)
    seq = sqlite3.connect(SEQ_DB)
    syms = [r[0] for r in seq.execute(
        "SELECT DISTINCT symbol FROM stock_daily WHERE close_qfq>0 AND date>='2019-01-01'").fetchall()]
    sample = random.sample(syms, min(SAMPLE, len(syms)))
    print(f"[{ts()}] 抽样 {len(sample)} 只, 滚动回测开始(无未来函数)", flush=True)

    rolling_results = []   # (type, year, r10, r20, rtp, rsym)
    db_results = []        # 对照组: DB最终信号(同股票)

    for si, sym in enumerate(sample):
        rows = seq.execute(
            "SELECT date, open, high, low, close, close_qfq FROM stock_daily "
            "WHERE symbol=? AND close_qfq>0 ORDER BY date", (sym,)).fetchall()
        if len(rows) < 100:
            continue
        # r: date, open, high, low, close, close_qfq
        qf = [[r[0], r[1] * (r[5] / r[4]), r[2] * (r[5] / r[4]), r[3] * (r[5] / r[4]), r[5]] for r in rows]
        dates = [r[0] for r in rows]
        d2i = {d: i for i, d in enumerate(dates)}
        qfq_open = [x[1] for x in qf]
        qfq_close = [x[4] for x in qf]
        n = len(rows)

        # 全量笔(拿所有端点日期)
        merged_all = merge_inclusion([[x[0], x[2], x[3], x[4]] for x in qf])
        bi_all = calc_bi(merged_all)
        endpoints = sorted({merged_all[b[0]][0] for b in bi_all if merged_all[b[0]][0] >= START})

        # 滚动收集: 对每个端点, 用截止端点+2的数据重算
        rolling_sigs = set()  # (type, date)
        for d in endpoints:
            idx = d2i.get(d)
            if idx is None or idx + 2 > n:
                continue
            cut = idx + 2  # 截止确认日(端点日+1)的收盘后
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
                if sd == d:  # 该端点当日触发的信号, 当时可见
                    rolling_sigs.add((t, sd))

        # DB最终信号(对照组)
        db_sigs = set()
        try:
            picks = sqlite3.connect("/home/ubuntu/databases/trend_picks.db")
            db_sigs = {(r[0], r[1]) for r in picks.execute(
                "SELECT signal_type, signal_date FROM chanlun_signals WHERE symbol=? AND signal_date>=?",
                (sym, START)).fetchall()}
            picks.close()
        except Exception:
            pass

        # 回测函数
        def backtest(sigset, tag):
            out = []
            for typ, sdate in sigset:
                bi = d2i.get(sdate)
                if bi is None or bi + 2 >= n:
                    continue
                buy_i = bi + 2
                buy_p = qfq_open[buy_i]
                if buy_p <= 0:
                    continue
                if buy_i + HOLD10 - 1 < n:
                    r10 = qfq_close[buy_i + HOLD10 - 1] / buy_p - 1
                else:
                    r10 = None
                if buy_i + HOLD20 - 1 < n:
                    r20 = qfq_close[buy_i + HOLD20 - 1] / buy_p - 1
                else:
                    r20 = None
                # 止盈8/止损5
                rtp = None
                end_i = min(buy_i + HOLD20, n)
                for i in range(buy_i, end_i):
                    if qf[i][2] >= buy_p * TP:
                        rtp = TP - 1
                        break
                    if qf[i][3] <= buy_p * SL:
                        rtp = SL - 1
                        break
                if rtp is None and buy_i + HOLD20 - 1 < n:
                    rtp = qfq_close[buy_i + HOLD20 - 1] / buy_p - 1
                # 对称卖点: 后续最近卖点信号(滚动集合里, 卖出日+1收盘)
                rsym = None
                sell_dates = sorted(sd for t, sd in sigset if '卖' in t and sd > sdate)
                for sd in sell_dates:
                    si = d2i.get(sd)
                    if si is not None and si + 1 < n and si + 1 > buy_i:
                        rsym = qfq_close[si + 1] / buy_p - 1
                        break
                if rsym is None and buy_i + 60 < n:
                    rsym = qfq_close[buy_i + 59] / buy_p - 1
                out.append((typ, sdate[:4], r10, r20, rtp, rsym))
            return out

        for r in backtest(rolling_sigs, "rolling"):
            if r[2] is not None or r[3] is not None or r[4] is not None or r[5] is not None:
                rolling_results.append(r)
        for r in backtest(db_sigs, "db"):
            if r[2] is not None or r[3] is not None or r[4] is not None or r[5] is not None:
                db_results.append(r)

        if (si + 1) % 50 == 0:
            print(f"[{ts()}] {si+1}/{len(sample)}只 | 滚动{len(rolling_results)} 对照组{len(db_results)}", flush=True)

    seq.close()
    report("滚动信号(无未来函数)", rolling_results)
    report("DB最终信号(含未来修正)", db_results)


def report(name, results):
    print(f"\n===== {name}: n={len(results)} =====")
    buy = [r for r in results if '买' in r[0]]
    sell = [r for r in results if '卖' in r[0]]
    for label, arr, is_sell in [("买点", buy, False), ("卖点", sell, True)]:
        for rname, idx in [("T+10", 2), ("T+20", 3), ("止盈8/5", 4), ("对称卖点", 5)]:
            rs = [r[idx] for r in arr if r[idx] is not None]
            if not rs:
                continue
            if is_sell:
                win = sum(1 for x in rs if x < 0) / len(rs) * 100  # 卖点: 下跌=正确
                print(f"  {label}-{rname}: n={len(rs)} 下跌胜率{win:.1f}% 均收益{sum(rs)/len(rs)*100:+.2f}%")
            else:
                win = sum(1 for x in rs if x > 0) / len(rs) * 100
                print(f"  {label}-{rname}: n={len(rs)} 胜率{win:.1f}% 均收益{sum(rs)/len(rs)*100:+.2f}%")


if __name__ == "__main__":
    main()

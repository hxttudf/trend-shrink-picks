#!/usr/bin/env python3
"""缠论买卖信号回测: 胜率/收益率
规则: 信号日次日开盘买入(qfq), 各卖出规则对比
卖出规则:
  hold10/hold20: 固定持有N交易日收盘
  tp8sl5: T+20内 止盈+8%/止损-5% (日内触及), 否则第20日收盘
  symsell: 该股后续最近卖点信号日收盘卖出(无则T+60收盘)
统计: 按信号类型/年度/大盘(上证MA60)分组
"""
import sqlite3
import sys

SEQ_DB = "/home/ubuntu/Sequoia-X-a/data/sequoia_v2.db"
PICKS_DB = "/home/ubuntu/databases/trend_picks.db"
BATCH = 300
START = "2020-01-01"
HOLD10, HOLD20, HOLD60 = 10, 20, 60
TP, SL = 1.08, 0.95
# 信号确认延迟(缠论: 分型需右侧K线确认) — 标准口径=严格版:
# BUY_LAG=2 信号T+1确认, T+2开盘买入(真实可成交)
# SELL_LAG=1 卖点信号次日收盘卖出
# (旧版BUY_LAG=1/SELL_LAG=0为理想口径, 高估6~10pp, 已弃用)
BUY_LAG = int(sys.argv[1]) if len(sys.argv) > 1 else 2
SELL_LAG = int(sys.argv[2]) if len(sys.argv) > 2 else 1


def main():
    seq = sqlite3.connect(SEQ_DB)
    picks = sqlite3.connect(PICKS_DB)

    syms = [r[0] for r in picks.execute(
        "SELECT DISTINCT symbol FROM chanlun_signals WHERE signal_date>=?", (START,)).fetchall()]
    print(f"回测 {len(syms)} 只股票, 信号期 {START}~", flush=True)

    # 上证指数(大盘过滤)
    sh = {}
    try:
        for r in seq.execute("SELECT date, close FROM stock_daily WHERE symbol='000001.SH' ORDER BY date"):
            sh[r[0]] = r[1]
    except Exception:
        sh = {}

    results = []  # (type, date, ret_hold10, ret_hold20, ret_tp, ret_sym, ret60, sh_above)
    n_skip = 0
    for batch_i in range(0, len(syms), BATCH):
        batch = syms[batch_i:batch_i + BATCH]
        rows = seq.execute(
            "SELECT symbol, date, open, high, low, close, close_qfq FROM stock_daily "
            f"WHERE symbol IN ({','.join('?' * len(batch))}) AND close_qfq>0 ORDER BY symbol, date",
            batch).fetchall()
        per = {}
        for r in rows:
            per.setdefault(r[0], []).append(r)
        sig_rows = picks.execute(
            "SELECT symbol, signal_type, signal_date FROM chanlun_signals "
            f"WHERE signal_date>=? AND symbol IN ({','.join('?' * len(batch))}) ORDER BY symbol, signal_date",
            [START] + batch).fetchall()
        sig_per = {}
        for r in sig_rows:
            sig_per.setdefault(r[0], []).append((r[1], r[2]))

        for sym in batch:
            bars = per.get(sym, [])
            if len(bars) < 30:
                continue
            dates = [r[1] for r in bars]
            d2i = {d: i for i, d in enumerate(dates)}
            qfq_open = [r[2] * (r[6] / r[5]) for r in bars]
            qfq_high = [r[3] * (r[6] / r[5]) for r in bars]
            qfq_low = [r[4] * (r[6] / r[5]) for r in bars]
            qfq_close = [r[6] for r in bars]
            # 该股卖点信号日期集合(用于symsell)
            sell_dates = [d for t, d in sig_per.get(sym, []) if '卖' in t]

            for typ, sdate in sig_per.get(sym, []):
                bi = d2i.get(sdate)
                if bi is None or bi + BUY_LAG >= len(bars):
                    n_skip += 1
                    continue
                buy_i = bi + BUY_LAG  # 次日开盘(1) / 确认后次日开盘(2)
                buy_p = qfq_open[buy_i]
                if buy_p <= 0:
                    continue
                # 大盘过滤: 信号日上证是否>MA60
                sh_above = None
                if sh:
                    sh_dates = sorted(sh.keys())
                    sd = [d for d in sh_dates if d <= sdate]
                    if len(sd) >= 60:
                        cur = sh[sd[-1]]
                        ma60 = sum(sh[sd[-1-i]] for i in range(60)) / 60
                        sh_above = 1 if cur > ma60 else 0
                # hold10
                r10 = qfq_close[buy_i + HOLD10 - 1] / buy_p - 1 if buy_i + HOLD10 - 1 < len(bars) else None
                r20 = qfq_close[buy_i + HOLD20 - 1] / buy_p - 1 if buy_i + HOLD20 - 1 < len(bars) else None
                r60 = qfq_close[buy_i + HOLD60 - 1] / buy_p - 1 if buy_i + HOLD60 - 1 < len(bars) else None
                # tp8sl5: T+20内 触及止盈/止损
                rtp = None
                end_i = min(buy_i + HOLD20, len(bars))
                for i in range(buy_i, end_i):
                    if qfq_high[i] >= buy_p * TP:
                        rtp = TP - 1
                        break
                    if qfq_low[i] <= buy_p * SL:
                        rtp = SL - 1
                        break
                if rtp is None and buy_i + HOLD20 - 1 < len(bars):
                    rtp = qfq_close[buy_i + HOLD20 - 1] / buy_p - 1
                # symsell: 后续最近卖点信号收盘卖(SELL_LAG=0信号日/1次日)
                rsym = None
                for sd in sell_dates:
                    if sd > sdate:
                        si = d2i.get(sd)
                        if si is not None and si + SELL_LAG < len(bars) and si + SELL_LAG > buy_i:
                            rsym = qfq_close[si + SELL_LAG] / buy_p - 1
                            break
                if rsym is None and r60 is not None:
                    rsym = r60
                results.append((typ, sdate[:4], r10, r20, rtp, rsym, r60, sh_above))
        if batch_i % (BATCH * 5) == 0:
            print(f"  批{batch_i//BATCH+1}: 累计{len(results)}笔, 跳过{n_skip}", flush=True)

    seq.close()
    picks.close()
    report(results)


def report(results):
    print(f"\n===== 缠论买卖信号回测: {len(results)}笔 ({START}~) =====")
    rules = [("T+10", 2), ("T+20", 3), ("止盈8/止损5", 4), ("对称卖点", 5), ("T+60", 6)]
    for label, col in rules:
        print(f"\n── {label} ──")
        for typ in ["一买", "二买", "三买", "一卖", "二卖", "三卖"]:
            rs = [r[col] for r in results if r[0] == typ and r[col] is not None]
            if not rs:
                continue
            win = sum(1 for x in rs if x > 0) / len(rs)
            avg = sum(rs) / len(rs)
            # 卖点信号: 收益为负=下跌=正确, 胜率=下跌比例
            if '卖' in typ:
                win = sum(1 for x in rs if x < 0) / len(rs)
            print(f"  {typ}: n={len(rs):6d} 胜率{win*100:5.1f}% 均收益{avg*100:6.2f}%")
        # 汇总
        rs = [r[col] for r in results if r[col] is not None and '买' in r[0]]
        if rs:
            win = sum(1 for x in rs if x > 0) / len(rs)
            avg = sum(rs) / len(rs)
            print(f"  [买点合计]: n={len(rs):6d} 胜率{win*100:5.1f}% 均收益{avg*100:6.2f}%")
        rs = [r[col] for r in results if r[col] is not None and '卖' in r[0]]
        if rs:
            win = sum(1 for x in rs if x < 0) / len(rs)
            avg = sum(rs) / len(rs)
            print(f"  [卖点合计]: n={len(rs):6d} 下跌胜率{win*100:5.1f}% 均收益{avg*100:6.2f}%")

    # 年度(买点T+20)
    print(f"\n── 分年度 (买点, T+20) ──")
    for yr in ["2020", "2021", "2022", "2023", "2024", "2025", "2026"]:
        rs = [r[3] for r in results if r[1] == yr and '买' in r[0] and r[3] is not None]
        if not rs:
            continue
        win = sum(1 for x in rs if x > 0) / len(rs)
        avg = sum(rs) / len(rs)
        print(f"  {yr}: n={len(rs):6d} 胜率{win*100:5.1f}% 均收益{avg*100:6.2f}%")

    # 大盘过滤(买点T+20)
    print(f"\n── 大盘过滤 (买点, T+20) ──")
    for lbl, cond in [("上证>MA60", 1), ("上证<MA60", 0)]:
        rs = [r[3] for r in results if '买' in r[0] and r[3] is not None and r[7] == cond]
        if not rs:
            print(f"  {lbl}: 无数据")
            continue
        win = sum(1 for x in rs if x > 0) / len(rs)
        avg = sum(rs) / len(rs)
        print(f"  {lbl}: n={len(rs):6d} 胜率{win*100:5.1f}% 均收益{avg*100:6.2f}%")


if __name__ == "__main__":
    main()

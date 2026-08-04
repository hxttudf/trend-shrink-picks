#!/usr/bin/env python3
"""基础信号(底部确认worth / 趋势daily_picks) + 缠论信号 买卖回测
买入: 信号日T+2开盘 (变体B: 信号后10天内出现缠论买点→买点日+2买)
卖出: 缠论对称卖点(后续卖点+1收盘) / T+10 / T+20 / 止盈8%止损5%
输出: 每个基础信号类型 × 每个变体的 胜率/收益"""
import sqlite3

PICKS_DB = "/home/ubuntu/databases/trend_picks.db"
SEQ_DB = "/home/ubuntu/Sequoia-X-a/data/sequoia_v2.db"
HOLD10, HOLD20 = 10, 20
TP, SL = 1.08, 0.95
WIN = 10  # 缠论确认窗口(基础信号后N天内)


def main():
    picks = sqlite3.connect(PICKS_DB)
    seq = sqlite3.connect(SEQ_DB)
    # 缠论买/卖点(ok)
    buy_sigs = {}
    for r in picks.execute(
            "SELECT symbol, signal_date FROM chanlun_signals WHERE status='ok' AND signal_type LIKE '%买%'").fetchall():
        buy_sigs.setdefault(r[0], set()).add(r[1])
    sell_sigs = {}
    for r in picks.execute(
            "SELECT symbol, signal_date FROM chanlun_signals WHERE status='ok' AND signal_type LIKE '%卖%'").fetchall():
        sell_sigs.setdefault(r[0], set()).add(r[1])

    # 基础信号: (name, list[(symbol, date)])
    base = {}
    for r in picks.execute(
            "SELECT strategy_id, symbol, date FROM daily_picks ORDER BY date").fetchall():
        base.setdefault(f"趋势-{r[0]}", []).append((r[1], r[2]))
    for r in picks.execute(
            "SELECT status, symbol, date FROM bottom_confirm_picks WHERE status='worth' ORDER BY date").fetchall():
        base.setdefault("底部确认-worth", []).append((r[1], r[2]))
    # 趋势合并组
    all_trend = []
    for k, v in base.items():
        if k.startswith("趋势"):
            all_trend += v
    base["趋势-全部"] = all_trend

    cache = {}
    print(f"{'信号类型':<22}{'n':>5}{'变体':<8}{'n':>5}{'对称胜率':>8}{'对称收益':>9}{'T+10胜率':>9}{'止盈8/5胜率':>9}")
    for bname, sigs in base.items():
        if bname == "趋势-全部":
            continue
        # 先跑全部, 再跑各变体
        for variant in ["纯基础", "缠论确认"]:
            res = []
            for sym, sdate in sigs:
                if sym not in cache:
                    k = seq.execute(
                        "SELECT date, open, high, low, close, close_qfq FROM stock_daily "
                        "WHERE symbol=? AND close_qfq>0 ORDER BY date", (sym,)).fetchall()
                    if len(k) < 100:
                        cache[sym] = None
                        continue
                    qf = [[r[0], r[1] * (r[5] / r[4]), r[2] * (r[5] / r[4]), r[3] * (r[5] / r[4]), r[5]] for r in k]
                    cache[sym] = (qf, {r[0]: i for i, r in enumerate(k)}, len(k))
                pc = cache[sym]
                if pc is None:
                    continue
                qf, d2i, n = pc
                idx = d2i.get(sdate)
                if idx is None or idx + 2 >= n:
                    continue
                # 买入日: 纯基础=T+2 | 缠论确认=信号后WIN天内最早缠论买点+2
                buy_i = idx + 2
                if variant == "缠论确认":
                    bs = buy_sigs.get(sym, set())
                    found = None
                    for j in range(idx + 1, min(idx + WIN + 1, n)):
                        if qf[j][0] in bs:
                            found = j
                            break
                    if found is None:
                        continue
                    if found + 2 >= n:
                        continue
                    buy_i = found + 2
                buy_p = qf[buy_i][1]
                if buy_p <= 0:
                    continue
                # 对称卖点(后续缠论卖点+1收盘)
                rsym = None
                ss = sorted(x for x in sell_sigs.get(sym, set()) if x > qf[buy_i][0])
                for sd in ss:
                    si = d2i.get(sd)
                    if si is not None and si + 1 < n and si + 1 > buy_i:
                        rsym = qf[si + 1][4] / buy_p - 1
                        break
                if rsym is None:
                    c60 = qf[buy_i + 59][4] if buy_i + 59 < n else None
                    rsym = c60 / buy_p - 1 if c60 else None
                c10 = qf[buy_i + 9][4] if buy_i + 9 < n else None
                r10 = c10 / buy_p - 1 if c10 else None
                rtp = None
                for i in range(buy_i, min(buy_i + HOLD20, n)):
                    if qf[i][2] >= buy_p * TP:
                        rtp = TP - 1
                        break
                    if qf[i][3] <= buy_p * SL:
                        rtp = SL - 1
                        break
                if rtp is None:
                    rtp = r10
                res.append((rsym, r10, rtp))
            if len(res) < 20:
                print(f"{bname:<22}{len(sigs):>5}{variant:<8}{len(res):>5}  样本不足")
                continue
            rs = [r[0] for r in res if r[0] is not None]
            r10s = [r[1] for r in res if r[1] is not None]
            rtps = [r[2] for r in res if r[2] is not None]
            w1 = sum(1 for x in rs if x > 0) / len(rs) * 100
            m1 = sum(rs) / len(rs) * 100
            w2 = sum(1 for x in r10s if x > 0) / len(r10s) * 100
            w3 = sum(1 for x in rtps if x > 0) / len(rtps) * 100
            print(f"{bname:<22}{len(sigs):>5}{variant:<8}{len(res):>5}{w1:>7.1f}%{m1:>+8.2f}%{w2:>8.1f}%{w3:>8.1f}%")


if __name__ == "__main__":
    main()

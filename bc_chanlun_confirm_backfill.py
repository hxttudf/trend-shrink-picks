#!/usr/bin/env python3
"""一次性回放: 对每只有信号的股票, 逐日回放最近N个交易日, 追溯信号的历史确认
当时判定出的信号(如6/24一买在6/30才确认)补录进chanlun_signals(confirmed_date=首次确认日, confirmed_later=1)
之后状态由daily的当前结构验证决定(ok/error)
用法: python3 bc_chanlun_confirm_backfill.py [days]
"""
import sqlite3
import sys
import time

sys.path.insert(0, "/home/ubuntu/trend-shrink-picks")
import chanlun_full as cf

SEQ_DB = "/home/ubuntu/Sequoia-X-a/data/sequoia_v2.db"
PICKS_DB = "/home/ubuntu/databases/trend_picks.db"
DAYS = int(sys.argv[1]) if len(sys.argv) > 1 else 90


def gen_all_signals(rows_all, D):
    """用截至D的数据重算全历史信号(与analyze同源)"""
    rows = [r for r in rows_all if r[0] <= D]
    if len(rows) < 60:
        return []
    qf_rows = [r for r in rows if r[5] > 0]
    closes_qf = [r[5] for r in qf_rows]
    # rows_all字段: 0=date 1=open 2=high 3=low 4=close 5=close_qfq 6=volume
    k = [[r[0], r[2], r[3]] for r in qf_rows]  # [date, high, low] — 修正: 之前误用close/high导致结构失真
    merged = cf.merge_inclusion(k)
    bi = cf.calc_bi(merged)
    if len(bi) < 8:
        return []
    zs_list = cf.calc_zhongshu_bi(bi)
    dif, dea, macd = cf.macd_data(closes_qf)
    sigs = cf.find_all_signals(bi, zs_list, dif, merged)
    return [(t, dt, p) for t, dt, p, _, _ in sigs]


def main():
    seq = sqlite3.connect(SEQ_DB)
    picks = sqlite3.connect(PICKS_DB, timeout=30)
    names = {}
    for r in seq.execute("SELECT symbol, name FROM stock_basics WHERE date=(SELECT MAX(date) FROM stock_basics)"):
        names[r[0]] = r[1]

    tds = [r[0] for r in seq.execute(
        "SELECT DISTINCT date FROM stock_daily ORDER BY date DESC LIMIT ?", (DAYS,))]
    tds = list(reversed(tds))
    print(f"回放窗口: {tds[0]} ~ {tds[-1]} ({len(tds)}个交易日)", flush=True)

    syms = [r[0] for r in seq.execute(
        "SELECT DISTINCT symbol FROM stock_daily WHERE close_qfq>0 AND date>='2024-01-01'")]
    t0 = time.time()
    done = added = 0
    for sym in syms:
        rows_all = seq.execute(
            "SELECT date, open, high, low, close, close_qfq, volume FROM stock_daily "
            "WHERE symbol=? AND close_qfq>0 ORDER BY date", (sym,)).fetchall()
        if not rows_all:
            continue
        nm = names.get(sym, "?")
        if 'ST' in nm.upper():
            continue
        # 当前结构有无信号(快速过滤)
        cur = gen_all_signals(rows_all, tds[-1])
        if not cur:
            continue
        td_idx = {d: i for i, d in enumerate(tds)}
        for D in tds:
            sigs = gen_all_signals(rows_all, D)
            ci = td_idx.get(D, -1)
            for typ, dt, p in sigs:
                # 事后确认判定: 确认日与信号日相隔>=2个交易日才算事后(次日确认=正常确认流程)
                si = td_idx.get(dt, -1)
                # 窗口起点(ci=0)出现的信号可能窗口前已确认, 默认当时; 窗口内首次出现且延迟>=2交易日=事后确认
                later = 1 if (si >= 0 and ci >= 1 and ci - si >= 2) else 0
                picks.execute(
                    "INSERT INTO chanlun_signals (symbol, name, signal_type, signal_date, price, status, confirmed_date, confirmed_later) "
                    "VALUES (?,?,?,?,?,'ok',?,?) "
                    "ON CONFLICT(symbol, signal_type, signal_date) DO UPDATE SET price=excluded.price",
                    (sym, nm, typ, dt, p, D, later))
                added += 1
        done += 1
        if done % 100 == 0:
            picks.commit()
            print(f"  {done}只股票, 新增/更新{added}条, {time.time()-t0:.0f}s", flush=True)
    picks.commit()
    picks.close()
    seq.close()
    print(f"✅ 回放完成: {done}只股票, 累计写入{added}条, 耗时{time.time()-t0:.0f}s")


if __name__ == "__main__":
    main()

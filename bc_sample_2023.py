#!/usr/bin/env python3
"""抽样回放2023年: 统计"全量当时信号"(首次出现≤T+1交易日)的一买胜率
对比DB旧快照(2023 NULL信号胜率64.8%) — 判断快照是否有选择偏差
口径: T+2买入 → T+2+5/20卖出; 复权
"""
import sqlite3, random, sys, time
sys.path.insert(0, '/home/ubuntu/trend-shrink-picks')
import bc_chanlun_confirm_backfill as bf

SEQ_DB = "/home/ubuntu/Sequoia-X-a/data/sequoia_v2.db"
YEAR = 2023
N_SAMPLE = int(sys.argv[1]) if len(sys.argv) > 1 else 500

def main():
    t0 = time.time()
    seq = sqlite3.connect(SEQ_DB)
    syms = [r[0] for r in seq.execute(
        "SELECT DISTINCT symbol FROM stock_daily WHERE date BETWEEN '2023-01-01' AND '2023-12-31' AND close_qfq>0")]
    random.seed(42)
    random.shuffle(syms)
    sample = syms[:N_SAMPLE]
    print(f"抽样 {len(sample)} 只回放 {YEAR} 全年", flush=True)
    rets5, rets20 = [], []
    n_sig = 0
    for si, sym in enumerate(sample):
        rows_all = seq.execute(
            "SELECT date, open, high, low, close, close_qfq, volume FROM stock_daily WHERE symbol=? AND close_qfq>0 ORDER BY date",
            (sym,)).fetchall()
        if len(rows_all) < 120:
            continue
        dates = [r[0] for r in rows_all]
        closes = [r[5] for r in rows_all]
        year_idx = [i for i, d in enumerate(dates) if d.startswith(str(YEAR))]
        if len(year_idx) < 60:
            continue
        # 逐日回放: 记录每个信号(一买)的首次出现日
        first_seen = {}
        for i in year_idx:
            D = dates[i]
            sigs = bf.gen_all_signals(rows_all, D)
            for t, dt, p in sigs:
                if t == '一买' and dt not in first_seen:
                    first_seen[dt] = D
        # 当时确认: 首次出现日与信号日交易日差<=1; 统计买入收益
        for dt, fsd in first_seen.items():
            try:
                si_ = dates.index(dt)
            except ValueError:
                continue
            try:
                fi_ = dates.index(fsd)
            except ValueError:
                continue
            if fi_ - si_ > 1:  # 事后确认, 跳过
                continue
            n_sig += 1
            for N, out in ((5, rets5), (20, rets20)):
                bi, sl = si_ + 2, si_ + 2 + N
                if sl < len(closes) and closes[bi] > 0:
                    out.append(closes[sl] / closes[bi] - 1)
        if (si + 1) % 100 == 0:
            print(f"  {si+1}/{len(sample)} 只, {time.time()-t0:.0f}s", flush=True)
    seq.close()
    for N, rs in ((5, rets5), (20, rets20)):
        if rs:
            win = sum(1 for r in rs if r > 0) / len(rs) * 100
            avg = sum(rs) / len(rs) * 100
            print(f"{YEAR}年 全量当时信号 一买 持有{N}日: 样本{len(rs)} 胜率{win:.1f}% 平均收益{avg:.2f}%")
        else:
            print(f"{YEAR}年 持有{N}日: 无样本")
    print(f"总信号数: {n_sig}, 耗时{time.time()-t0:.0f}s")

if __name__ == "__main__":
    main()

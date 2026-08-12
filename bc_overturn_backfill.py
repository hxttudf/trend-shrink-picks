#!/usr/bin/env python3
"""补录 overturned_date/overturned_later: 回放窗口内逐日状态跟踪
逻辑(与daily一致): 每天结构在=ok/不在=error; 首次不在结构日=推翻日; 交易日差>=2=事后推翻(1)/<=1=当时(0)
范围: ①窗口内confirmed的error信号 ②窗口外error信号(窗口起点D0时仍在结构的, 可追溯窗口内推翻)
窗口起点前已error的无法追溯(保持NULL, 诚实留空)
"""
import sqlite3, sys, time
sys.path.insert(0, '/home/ubuntu/trend-shrink-picks')
from bc_chanlun_confirm_backfill import gen_all_signals

PICKS_DB = "/home/ubuntu/databases/trend_picks.db"
SEQ_DB = "/home/ubuntu/Sequoia-X-a/data/sequoia_v2.db"
DAYS = 90

def main():
    seq = sqlite3.connect(SEQ_DB)
    picks = sqlite3.connect(PICKS_DB, timeout=60)
    tds = [r[0] for r in seq.execute(
        "SELECT DISTINCT date FROM stock_daily ORDER BY date DESC LIMIT ?", (DAYS,))]
    tds = list(reversed(tds))
    d0 = tds[0]
    print(f"补录窗口: {d0} ~ {tds[-1]} ({len(tds)}个交易日)", flush=True)

    # 所有待补录的error信号(按股票分组)
    rows = picks.execute(
        "SELECT symbol, signal_type, signal_date, confirmed_date FROM chanlun_signals "
        "WHERE status='error' AND overturned_date IS NULL").fetchall()
    by_sym = {}
    for sym, typ, sd, cd in rows:
        by_sym.setdefault(sym, []).append((typ, sd, cd))
    print(f"待补录: {len(rows)}条, {len(by_sym)}只股票", flush=True)

    t0 = time.time()
    n_fill = n_skip = 0
    for si, (sym, recs) in enumerate(by_sym.items()):
        rows_all = seq.execute(
            "SELECT date, open, high, low, close, close_qfq, volume FROM stock_daily "
            "WHERE symbol=? AND close_qfq>0 ORDER BY date", (sym,)).fetchall()
        if not rows_all:
            continue
        dates = [r[0] for r in rows_all]
        d_idx = {d: i for i, d in enumerate(dates)}
        # 窗口起点D0时在结构的窗口外信号(可追溯); 不在的跳过(起点前已error)
        cur_d0 = {x[1] for x in gen_all_signals(rows_all, d0)} if any(cd is None for _, _, cd in recs) else None
        # 待跟踪: (typ, sd, 信号日索引, 判定起点日期) — 起点=max(D0, confirmed_date)或D0, 信号确认后才可能被推翻
        track = []
        for typ, sd, cd in recs:
            si_idx = d_idx.get(sd, -1)
            if si_idx < 0:
                continue
            if cd is not None:
                # 窗口内确认: 从确认日开始判定(确认后才可能被推翻; 信号日当天结构可能不含信号, 不能从信号日判定)
                track.append((typ, sd, si_idx, cd))
            elif cur_d0 is not None and (typ, sd) in cur_d0:
                track.append((typ, sd, si_idx, d0))  # 窗口外信号, D0时仍在结构: 从D0跟踪
            else:
                n_skip += 1                            # 窗口起点前已error: 无法追溯
        if not track:
            continue
        for D in tds:
            sigs = gen_all_signals(rows_all, D)
            sig_set = {(x[0], x[1]) for x in sigs}
            new_track = []
            for typ, sd, si_idx, start_d in track:
                if D < start_d:
                    # 判定起点(确认日/D0)之前: 信号尚未确认, 不可能被推翻 — 跳过判定
                    new_track.append((typ, sd, si_idx, start_d))
                    continue
                if (typ, sd) not in sig_set:
                    # 首次不在结构 = 推翻日
                    oi = d_idx.get(D, -1)
                    ov_later = 1 if (oi >= 0 and oi - si_idx >= 2) else (0 if oi >= 0 else None)
                    picks.execute(
                        "UPDATE chanlun_signals SET overturned_date=?, overturned_later=? "
                        "WHERE symbol=? AND signal_type=? AND signal_date=?",
                        (D, ov_later, sym, typ, sd))
                    n_fill += 1
                else:
                    new_track.append((typ, sd, si_idx, start_d))
            track = new_track
            if not track:
                break
        picks.commit()
        if (si + 1) % 300 == 0:
            print(f"  {si+1}只, 已补{n_fill}, 跳过{n_skip}, {time.time()-t0:.0f}s", flush=True)
    picks.commit()
    picks.close()
    seq.close()
    print(f"✅ 补录完成: 填充{n_fill}, 无法追溯{n_skip}, 耗时{time.time()-t0:.0f}s")

if __name__ == "__main__":
    main()

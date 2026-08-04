#!/usr/bin/env python3
"""
底部确认策略 — 每日选股入库
- 全市场扫描(六维评分+底部连续确认)
- 买入线: 确认>=4期 且 站上MA20 → status='worth'
- 观察线: 确认>=3期 → status='watch'
- 写入 trend_picks.db 的 bottom_confirm_picks 表(独立表, 不影响daily_picks)
"""
import sqlite3, sys, os, time
from datetime import date

sys.path.insert(0, '/home/ubuntu/trend-shrink-picks')
from bottom_confirm_screener import load_all_data, load_names, analyze

TREND_DB = "/home/ubuntu/databases/trend_picks.db"
SEQUOIA_DB = "/home/ubuntu/Sequoia-X-a/data/sequoia_v2.db"
# ── 最优参数(V4, 2026-07-31定稿) ──
# V4 = 分数80-88 + 期数4 + 底部>=90天 + 每日Top3 + 市场过滤(上证>MA60)
#   精简扫描发现: TopN按分数取会破坏牛市(分数最高≠最好), 但市场过滤效果惊人
#   V4效果: 四年全部正收益, 年信号50-110个(每周1-2个), 不再泛滥
MIN_SCORE_WORTH = 80    # 完整评分下限
MAX_SCORE_WORTH = 88    # 完整评分上限(过滤"完美信号"陷阱)
MIN_STREAK_WORTH = 4    # 确认期数(4期=20个交易日, 避免涨幅末端)
MIN_BOTTOM_WORTH = 90   # 底部天数
DROP_LO, DROP_HI = 20, 65  # 跌幅范围(正数, 即-65%~-20%)
STREAK_THRESHOLD = 65   # 确认评分阈值(quick_score_at>=65算一期)
TOP_N_WORTH = 3         # 每日最多3个买入信号(按分数取前3)
MKT_FILTER = True       # 市场过滤: 上证指数收盘>MA60才出信号
MIN_STREAK_WATCH = 3    # 观察线(确认>=3期即可进观察)

def market_filter_ok():
    """市场状态过滤: 上证指数收盘 > MA60 才允许买入信号"""
    conn = sqlite3.connect(SEQUOIA_DB)
    rows = conn.execute(
        "SELECT date, close_qfq FROM stock_daily WHERE symbol='000001.SH' AND close_qfq>0 "
        "ORDER BY date DESC LIMIT 60").fetchall()
    conn.close()
    if len(rows) < 60:
        return True
    rows = rows[::-1]
    ma60 = sum(r[1] for r in rows) / 60
    return rows[-1][1] > ma60

def init_table(conn):
    conn.execute("""
        CREATE TABLE IF NOT EXISTS bottom_confirm_picks(
          id INTEGER PRIMARY KEY AUTOINCREMENT,
          date TEXT,
          symbol TEXT,
          name TEXT,
          status TEXT,
          score REAL,
          stage TEXT,
          drop_pct REAL,
          bottom_days INTEGER,
          vol_shrink REAL,
          streak INTEGER,
          close_qfq REAL,
          ma20 REAL,
          ma60 REAL,
          created_at TEXT DEFAULT (datetime('now','localtime'))
        )
    """)
    conn.execute("CREATE UNIQUE INDEX IF NOT EXISTS idx_bc_unique ON bottom_confirm_picks(date, symbol, status)")

def main():
    today = date.today().isoformat()
    t0 = time.time()
    
    conn_seq = sqlite3.connect(SEQUOIA_DB)
    all_data = load_all_data(conn_seq)
    names = load_names(conn_seq)
    conn_seq.close()
    print(f"数据加载完成: {len(all_data)} 只 ({time.time()-t0:.0f}s)", flush=True)
    
    worth, watch = [], []
    for i, (sym, bars) in enumerate(all_data.items()):
        name = names.get(sym, sym)
        r = analyze(sym, bars, name, min_streak=MIN_STREAK_WORTH, min_score=STREAK_THRESHOLD)
        if r:
            score, d = r
            rec = (sym, name, score, d)
            drop = abs(float(d["跌幅"].rstrip("%")))
            # worth: V3全部条件(含分数上限, 过滤"完美信号"陷阱)
            if (score >= MIN_SCORE_WORTH and score <= MAX_SCORE_WORTH
                    and d["确认次数"] >= MIN_STREAK_WORTH
                    and d["底部天数"] >= MIN_BOTTOM_WORTH
                    and DROP_LO <= drop <= DROP_HI
                    and d["现价"] > d["ma20_val"]):
                worth.append(rec)
            elif d["确认次数"] >= MIN_STREAK_WATCH and score >= 65:
                watch.append(rec)
        if (i+1) % 2000 == 0:
            print(f"  进度 {i+1}/{len(all_data)} ({time.time()-t0:.0f}s)", flush=True)
    
    worth.sort(key=lambda x: -x[2])
    watch.sort(key=lambda x: -x[2])

    # V4: 市场过滤(上证指数收盘 > MA60) + 每日Top3
    mkt_ok = True
    if MKT_FILTER:
        mkt_ok = market_filter_ok()
        if not mkt_ok:
            print("⚠️ 市场状态: 上证指数 < MA60(空头), 暂停买入信号", flush=True)
    if mkt_ok:
        worth = worth[:TOP_N_WORTH]
    else:
        worth = []
    print(f"扫描完成: worth={len(worth)}, watch={len(watch)} ({time.time()-t0:.0f}s)", flush=True)
    
    # 写入DB
    conn = sqlite3.connect(TREND_DB)
    init_table(conn)
    # 删除当日旧数据(重跑覆盖)
    conn.execute("DELETE FROM bottom_confirm_picks WHERE date=?", (today,))
    for sym, name, score, d in worth:
        conn.execute("""
            INSERT OR REPLACE INTO bottom_confirm_picks(date, symbol, name, status, score, stage,
                drop_pct, bottom_days, vol_shrink, streak, close_qfq, ma20, ma60)
            VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)
        """, (today, sym, name, 'worth', score, d['阶段'],
              float(d['跌幅'].rstrip('%')), d['底部天数'],
              float(d['量能萎缩'].rstrip('x')), d['确认次数'],
              d['现价'], d['ma20_val'], float(d['MA60'])))
    for sym, name, score, d in watch:
        conn.execute("""
            INSERT OR REPLACE INTO bottom_confirm_picks(date, symbol, name, status, score, stage,
                drop_pct, bottom_days, vol_shrink, streak, close_qfq, ma20, ma60)
            VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)
        """, (today, sym, name, 'watch', score, d['阶段'],
              float(d['跌幅'].rstrip('%')), d['底部天数'],
              float(d['量能萎缩'].rstrip('x')), d['确认次数'],
              d['现价'], d['ma20_val'], float(d['MA60'])))
    conn.commit()
    conn.close()
    
    # 输出
    print(f"\n{'='*72}")
    print(f"底部确认策略 {today} | 值得买 {len(worth)} 只 | 观察 {len(watch)} 只")
    print(f"{'='*72}")
    print(f"{'代码':<8}{'名称':<10}{'现价':>6}{'阶段':<8}{'跌幅':>6}{'底部':>5}{'确认':>4}{'分':>4}")
    for sym, name, score, d in worth[:15]:
        print(f"{sym:<8}{name:<10}{d['现价']:>6.2f}{d['阶段']:<8}{d['跌幅']:>6}{d['底部天数']:>4}天{d['确认次数']:>4}{score:>4}")
    print(f"\n已写入 {TREND_DB} 表 bottom_confirm_picks (当日 {len(worth)+len(watch)} 条)")

if __name__ == "__main__":
    main()

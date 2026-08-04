#!/usr/bin/env python3
"""
底部确认框架增强回测 — 多重确认
对比:
  A. 原版(基线): 单次Top10信号
  B. 多次确认: 股票连续≥2期/≥3期出现在评分表(底部反复出现信号)
  C. +MACD金叉确认
  D. B+C 组合
"""
import sqlite3, time
import numpy as np

SCORES_DB = "/home/ubuntu/trend-shrink-picks/bt_scores.db"
DB = "/home/ubuntu/Sequoia-X-a/data/sequoia_v2.db"
TOP_N = 10
MIN_SCORE = 70  # 计入"连续出现"的分数门槛

def macd(closes, fast=12, slow=26, signal=9):
    """返回DIF, DEA数组"""
    closes = np.asarray(closes, dtype=np.float64)
    def ema(n):
        k = 2/(n+1)
        out = np.empty(len(closes))
        out[0] = closes[0]
        for i in range(1, len(closes)):
            out[i] = closes[i]*k + out[i-1]*(1-k)
        return out
    dif = ema(fast) - ema(slow)
    dea = np.empty(len(dif))
    k = 2/(signal+1)
    dea[0] = dif[0]
    for i in range(1, len(dif)):
        dea[i] = dif[i]*k + dea[i-1]*(1-k)
    return dif, dea

def main():
    t0 = time.time()
    btdb = sqlite3.connect(SCORES_DB)
    conn = sqlite3.connect(DB)
    
    # 所有回测日(排序)
    btdates = [r[0] for r in btdb.execute("SELECT DISTINCT bt_date FROM scores ORDER BY bt_date")]
    # 每期Top10
    top_by_date = {}
    for bd in btdates:
        top_by_date[bd] = btdb.execute(
            "SELECT symbol, score, is_oneword FROM scores WHERE bt_date=? ORDER BY score DESC LIMIT ?",
            (bd, TOP_N)
        ).fetchall()
    
    # 每只股票每期是否出现(>=MIN_SCORE) — 全量内存处理
    from collections import defaultdict
    all_scores = btdb.execute("SELECT bt_date, symbol, score FROM scores").fetchall()
    sym_dates = defaultdict(set)
    for bd, sym, sc in all_scores:
        if sc >= MIN_SCORE:
            sym_dates[sym].add(bd)
    
    # 计算"连续期数"
    consec = {}  # (bd, symbol) -> 连续出现期数
    bd_set_all = set(btdates)
    for sym, date_set in sym_dates.items():
        streak = 0
        for bd in reversed(btdates):
            if bd in date_set:
                streak += 1
                consec[(bd, sym)] = streak
            else:
                streak = 0
    
    print(f"预计算完成 {time.time()-t0:.0f}s, 共{len(top_by_date)}期", flush=True)
    
    # 拉取每只Top股票在信号日的K线(前复权)+MACD
    kline_cache = {}
    def get_kline(sym, bd_str):
        key = sym
        if key in kline_cache:
            return kline_cache[key]
        rows = conn.execute(
            "SELECT date, close_qfq FROM stock_daily WHERE symbol=? AND close_qfq>0 "
            "AND date<='2026-07-30' ORDER BY date", (sym,)
        ).fetchall()
        kline_cache[key] = rows
        return rows
    
    # 构建信号集
    signals = []  # (bd_str, sym, score, streak, macd_gold, rets, is_ow)
    for bd in btdates:
        bd_str = f"{bd//10000}-{bd%10000//100:02d}-{bd%100:02d}"
        for sym, score, is_ow in top_by_date[bd]:
            streak = consec.get((bd, sym), 0)
            
            # MACD金叉判断(信号日前20日内出现金叉)
            klines = get_kline(sym, bd_str)
            closes = [r[1] for r in klines]
            dates = [r[0] for r in klines]
            macd_gold = False
            if len(closes) >= 40:
                # 找到信号日在K线中的位置
                idx = None
                for i in range(len(dates)-1, -1, -1):
                    if dates[i] <= bd_str:
                        idx = i
                        break
                if idx and idx >= 30:
                    dif, dea = macd(closes[:idx+1])
                    # 近5日内金叉: DIF上穿DEA
                    for j in range(max(1, idx-4), idx+1):
                        if dif[j] > dea[j] and dif[j-1] <= dea[j-1]:
                            macd_gold = True
                            break
                    # 或DIF>DEA且都在0轴上方(多头)
                    if dif[idx] > dea[idx] and dif[idx] > 0:
                        macd_gold = True
            
            # 未来收益
            fut = conn.execute(
                "SELECT close_qfq FROM stock_daily WHERE symbol=? AND close_qfq>0 AND date>? "
                "ORDER BY date LIMIT 20", (sym, bd_str)
            ).fetchall()
            cur = conn.execute(
                "SELECT close_qfq FROM stock_daily WHERE symbol=? AND date=? AND close_qfq>0",
                (sym, bd_str)
            ).fetchone()
            if not cur:
                continue
            base = cur[0]
            rets = {}
            for h in [1, 5, 10, 20]:
                rets[h] = (fut[h-1][0]/base - 1)*100 if len(fut) >= h else None
            signals.append((bd_str, sym, score, streak, macd_gold, rets, bool(is_ow)))
    
    print(f"信号构建完成 {time.time()-t0:.0f}s, 共{len(signals)}个", flush=True)
    
    def stat(group, label):
        if not group:
            print(f"  {label}: 无信号"); return
        print(f"  {label} (n={len(group)}):")
        for h in [1, 5, 10, 20]:
            vals = [s[5][h] for s in group if s[5].get(h) is not None]
            if not vals: continue
            wins = sum(1 for v in vals if v > 0)
            avg = sum(vals)/len(vals)
            med = sorted(vals)[len(vals)//2]
            print(f"    T+{h:>2}: 胜率{wins/len(vals)*100:5.1f}% 均收{avg:+6.2f}% 中位{med:+6.2f}%")
    
    print("="*62)
    print("A. 原版基线(全部Top10)")
    print("="*62)
    stat(signals, "基线")
    
    print("\n" + "="*62)
    print("B. 多次确认 (连续出现期数分层)")
    print("="*62)
    for n, name in [(1, "连续1期(首次)"), (2, "连续>=2期"), (3, "连续>=3期")]:
        g = [s for s in signals if s[3] >= n]
        stat(g, name)
    
    print("\n" + "="*62)
    print("C. MACD金叉/多头确认")
    print("="*62)
    stat([s for s in signals if s[4]], "MACD确认")
    stat([s for s in signals if not s[4]], "无MACD确认")
    
    print("\n" + "="*62)
    print("D. 组合: 连续>=2期 + MACD确认")
    print("="*62)
    stat([s for s in signals if s[3] >= 2 and s[4]], "2期+MACD")
    stat([s for s in signals if s[3] >= 3 and s[4]], "3期+MACD")
    
    # 2026年单独看组合效果
    print("\n" + "="*62)
    print("2026年(熊市)组合效果")
    print("="*62)
    g26 = [s for s in signals if s[0].startswith('2026')]
    stat(g26, "2026全部")
    stat([s for s in g26 if s[3] >= 2 and s[4]], "2026 2期+MACD")
    
    btdb.close()
    conn.close()

if __name__ == "__main__":
    main()

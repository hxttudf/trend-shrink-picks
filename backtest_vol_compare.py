
import sqlite3

TREND_DB = "/home/ubuntu/databases/trend_picks.db"
STOCK_DB = "/home/ubuntu/databases/Sequoia选股.db"

tc = sqlite3.connect(TREND_DB)
sc = sqlite3.connect(STOCK_DB)
tc.row_factory = sqlite3.Row
sc.row_factory = sqlite3.Row

# 三策略
STRATEGIES = {"premium_a": "极品A", "premium_b": "极品B", "ultra_shrink": "超缩量"}

# 预加载数据
all_data = {}
for sid, sname in STRATEGIES.items():
    signals = tc.execute("""
        SELECT dp.symbol, dp.date, COALESCE(dp.name,"") as name
        FROM daily_picks dp WHERE dp.strategy_id = ?
        ORDER BY dp.date
    """, (sid,)).fetchall()
    
    syms = set(s["symbol"] for s in signals)
    klines = {}
    for sym in syms:
        rows = sc.execute("""
            SELECT date, close_qfq, volume, open_qfq, high_qfq, low_qfq
            FROM stock_daily WHERE symbol=? AND close_qfq>0 ORDER BY date
        """, (sym,)).fetchall()
        if rows:
            klines[sym] = rows
    
    di = {}
    for sym, rows in klines.items():
        di[sym] = {r["date"]: i for i, r in enumerate(rows)}
    
    all_data[sid] = {"signals": signals, "klines": klines, "date_idx": di}

def get_nth(sym, ds, n, kls, di):
    rows = kls.get(sym, [])
    idx = di.get(sym, {}).get(ds)
    if idx is None or idx+n >= len(rows): return None
    return rows[idx+n]

def avg_vol(sym, ds, kls, di, days):
    rows = kls.get(sym, [])
    idx = di.get(sym, {}).get(ds)
    if idx is None or idx < days: return None
    vs = [rows[i]["volume"] for i in range(idx-days, idx) if rows[i]["volume"] and rows[i]["volume"]>0]
    return sum(vs)/len(vs) if vs else None

def backtest(sid, drop, mult, avg_days):
    kls = all_data[sid]["klines"]
    di = all_data[sid]["date_idx"]
    trades, filtered = [], []
    for sig in all_data[sid]["signals"]:
        sym, ds = sig["symbol"], sig["date"]
        rows = kls.get(sym, [])
        si = di.get(sym, {}).get(ds)
        if si is None: continue
        t1 = get_nth(sym, ds, 1, kls, di)
        if t1 is None: continue
        # T+1当日涨跌幅
        if si < 1: continue
        prev_c = rows[si-1]["close_qfq"]
        t1_ret = (t1["close_qfq"]/prev_c-1)*100 if prev_c>0 else 0
        # 量比(用不同天数)
        av = avg_vol(sym, t1["date"], kls, di, avg_days)
        t1_vr = t1["volume"]/av if av and av>0 else 0
        
        sell_idx = si + 21
        if sell_idx >= len(rows): continue
        bp = t1["close_qfq"]
        sp = rows[sell_idx]["close_qfq"]
        base_ret = (sp/bp-1)*100
        
        if t1_ret <= drop and t1_vr >= mult:
            filtered.append((sym, ds, t1_ret, t1_vr, base_ret))
        else:
            trades.append((base_ret, sym, ds))
    return trades, filtered

# 对比: 5日均量 vs 20日均量
thresholds = [(-2.0, 1.5, "跌≥-2%+量≥1.5x"), (-3.0, 1.5, "跌≥-3%+量≥1.5x")]

for avg_label, avg_days in [("5日均量(同花顺)", 5), ("20日均量(DB)", 20)]:
    print(f"\n{'='*80}")
    print(f"【{avg_label}】")
    print(f"{'='*80}")
    
    # 三策略合并
    all_base_rets, all_base_n = [], 0
    all_filtered_count, all_f_losers, all_f_winners = 0, 0, 0
    all_f_rets = []
    
    for drop, mult, desc in thresholds:
        total_base = 0
        total_trades_rets = []
        total_filtered = []
        
        for sid in STRATEGIES:
            # 基准
            bt, _ = backtest(sid, -999, 999, avg_days)
            b_rets = [t[0] for t in bt]
            # 过滤后
            trades, filt = backtest(sid, drop, mult, avg_days)
            total_trades_rets.extend([t[0] for t in trades])
            total_filtered.extend(filt)
            total_base += len(b_rets)
        
        b_avg = sum(total_trades_rets)/len(total_trades_rets) if total_trades_rets else 0
        b_wr = sum(1 for r in total_trades_rets if r>0)/len(total_trades_rets)*100 if total_trades_rets else 0
        
        # 计算基准(全量无过滤)
        all_base = []
        for sid in STRATEGIES:
            bt, _ = backtest(sid, -999, 999, avg_days)
            all_base.extend([t[0] for t in bt])
        base_avg = sum(all_base)/len(all_base) if all_base else 0
        base_wr = sum(1 for r in all_base if r>0)/len(all_base)*100 if all_base else 0
        
        f_l = sum(1 for f in total_filtered if f[4] < 0)
        f_w = sum(1 for f in total_filtered if f[4] > 0)
        
        print(f"\n{desc:20s}: 总{total_base:3d} 成交{len(total_trades_rets):3d} 过滤{len(total_filtered):2d} 均收益{b_avg:+7.2f}% 胜率{b_wr:5.1f}% 过滤输家{f_l:2d} 过滤赢家{f_w:2d} 收益Δ{b_avg-base_avg:+7.2f}% 胜率Δ{b_wr-base_wr:+6.1f}%")
        
        if f_w > 0:
            for ff in sorted(total_filtered, key=lambda x: x[4], reverse=True)[:3]:
                if ff[4] > 0:
                    print(f"  ⚠ 误杀 {ff[0]} {ff[1]} T+1回撤{ff[2]:.1f}% 量比{ff[3]:.2f}x 基准+{ff[4]:.1f}%")
        if f_l > 0:
            for ff in sorted(total_filtered, key=lambda x: x[4])[:3]:
                if ff[4] < 0:
                    print(f"  ✓ 躲过 {ff[0]} {ff[1]} T+1回撤{ff[2]:.1f}% 量比{ff[3]:.2f}x 基准{ff[4]:.1f}%")

tc.close()
sc.close()

#!/usr/bin/env python3
"""市场牛熊综合判断 — 使用公认标准"""
import sqlite3, os
from datetime import date, timedelta

os.environ["HTTP_PROXY"] = ""
os.environ["HTTPS_PROXY"] = ""

DB = "/home/ubuntu/databases/Sequoia选股.db"

def get_index_data(symbol, lookback=500):
    conn = sqlite3.connect(DB)
    rows = conn.execute(
        "SELECT date, close FROM stock_daily WHERE symbol=? AND close>0 ORDER BY date DESC LIMIT ?",
        (symbol, lookback)
    ).fetchall()
    conn.close()
    rows.reverse()  # 从旧到新
    return [r[1] for r in rows]

def regime(price, ma5, ma10, ma20, ma60, ma250, year_high, year_low):
    """
    综合判断市场状态。
    标准来源：技术性牛熊定义(Graham/Dodd) + 葛兰碧均线排列 + A股MA60分界线
    """
    from_high = (price / year_high - 1) * 100
    from_low  = (price / year_low  - 1) * 100
    
    # 第一层：技术性牛熊（最公认的定义）
    if from_high <= -20:
        base = "技术性熊市"
    elif from_low >= 20:
        base = "技术性牛市"
    else:
        base = "常规区间"
    
    # 第二层：均线排列（葛兰碧法则 + A股MA60分界线）
    if price > ma5 > ma10 > ma20 > ma60:
        ma_state = "多头排列↑"
    elif price < ma5 < ma10 < ma20 < ma60:
        ma_state = "空头排列↓"
    elif price > ma60 and ma20 > ma60:
        ma_state = "牛市中回调" if price < ma20 else "多头延续"
    elif price < ma60 and ma20 < ma60:
        ma_state = "熊市中反弹" if price > ma20 else "空头延续"
    elif price > ma20 > ma60:
        ma_state = "短线转强"
    elif price < ma20 < ma60:
        ma_state = "短线转弱"
    else:
        ma_state = "均线缠绕"
    
    # 第三层：MA60牛熊分界线（A股特色）
    if price > ma60:
        line_state = "MA60之上(偏牛)"
    else:
        line_state = "MA60之下(偏熊)"
    
    # 年线（超长线）
    if ma250 and price > ma250:
        yr_state = "年线上方(长多)"
    elif ma250:
        yr_state = "年线下方(长空)"
    else:
        yr_state = "数据不足"
    
    return {
        "价格": round(price, 1),
        "MA5": round(ma5, 1),
        "MA10": round(ma10, 1),
        "MA20": round(ma20, 1),
        "MA60": round(ma60, 1),
        "MA250": round(ma250, 1) if ma250 else None,
        "距年高": f"{from_high:.0f}%",
        "距年低": f"{from_low:.0f}%",
        "技术性牛熊": base,
        "均线状态": ma_state,
        "MA60分界线": line_state,
        "年线": yr_state,
        "综合判定": f"{base}·{ma_state}·{line_state}"
    }

def get_market_breadth(conn):
    """全市场站上MA20的比例"""
    today = date.today().strftime("%Y-%m-%d")
    # 检查是否有今天的趋势票数据
    trend_count = conn.execute(
        "SELECT COUNT(*) FROM stock_daily WHERE date=? AND close_qfq>0 AND ma20 IS NOT NULL AND close_qfq > ma20",
        (today,)
    ).fetchone()[0]
    total = conn.execute(
        "SELECT COUNT(*) FROM stock_daily WHERE date=? AND close_qfq>0",
        (today,)
    ).fetchone()[0]
    return trend_count / total * 100 if total else 0

def analyze_all():
    indices = [
        ("000001.SH", "上证指数"),
        ("399006.SZ", "创业板指"),
        ("000688.SH", "科创50"),
    ]
    
    conn = sqlite3.connect(DB)
    
    results = []
    for sym, name in indices:
        prices = get_index_data(sym)
        if len(prices) < 250:
            print(f"{name}: 数据不足({len(prices)}天)")
            continue
        
        cur = prices[-1]
        ma5  = sum(prices[-5:]) / 5
        ma10 = sum(prices[-10:]) / 10
        ma20 = sum(prices[-20:]) / 20
        ma60 = sum(prices[-60:]) / 60
        ma250 = sum(prices[-250:]) / 250 if len(prices) >= 250 else None
        
        year_high = max(prices[-250:]) if len(prices) >= 250 else max(prices)
        year_low  = min(prices[-250:]) if len(prices) >= 250 else min(prices)
        
        r = regime(cur, ma5, ma10, ma20, ma60, ma250, year_high, year_low)
        r["名称"] = name
        results.append(r)
    
    # 市场宽度（全市场站上MA20的比例）—— 用stock_daily+趋势票来估算
    today = date.today().strftime("%Y-%m-%d")
    # 查询全部有数据的股票数
    total_stocks = conn.execute(
        "SELECT COUNT(DISTINCT symbol) FROM stock_daily WHERE date=?",
        (today,)
    ).fetchone()[0]
    # 查询站上MA20的（通过是否入选趋势票来近似）
    above_ma20 = conn.execute(
        "SELECT COUNT(*) FROM sig_today", ()
    ).fetchone()[0] if conn.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='sig_today'").fetchone() else None
    
    conn.close()
    
    return results, total_stocks, above_ma20

def print_report():
    results, total, above = analyze_all()
    
    print("=" * 60)
    print("  市场牛熊综合诊断")
    print("=" * 60)
    print()
    
    for r in results:
        print(f"📊 {r['名称']}")
        print(f"  当前: {r['价格']}")
        print(f"  均线: MA5={r['MA5']} MA10={r['MA10']} MA20={r['MA20']} MA60={r['MA60']}")
        if r['MA250']:
            print(f"  年线: MA250={r['MA250']}")
        print(f"  距年高: {r['距年高']}  距年低: {r['距年低']}")
        print(f"  技术性牛熊: {r['技术性牛熊']}")
        print(f"  均线状态: {r['均线状态']}")
        print(f"  MA60分界线: {r['MA60分界线']}")
        print(f"  年线: {r['年线']}")
        print(f"  综合: {r['综合判定']}")
        print()
    
    if total:
        print(f"📈 市场宽度: 全市场{total}只股票今日有数据")
    
    print("=" * 60)
    print(f"  数据日期: {date.today()}")
    print()
    
    # 最终结论
    bears = [r for r in results if "技术性熊市" in r['技术性牛熊']]
    bulls = [r for r in results if "技术性牛市" in r['技术性牛熊']]
    print("📋 结论:")
    if bears and not bulls:
        print(f"  {'/'.join(r['名称'] for r in bears)} 已进入技术性熊市")
    if bulls:
        print(f"  {'/'.join(r['名称'] for r in bulls)} 处于技术性牛市")
    if not bears and not bulls:
        print(f"  各指数处于常规区间，参考均线状态判断方向")

if __name__ == "__main__":
    print_report()

#!/usr/bin/env python3
"""
老高博弈框架选股器 — 全市场扫描
基于「股市觉醒者老高」股票博弈分析框架：
  长底吸筹(缩量) → 放量启动 → 缩量回调确认 → 趋势运行

评分维度(满分100):
  ① 跌幅适中   20分  高点回撤20%~65% (洗盘充分)
  ② 底部时长   20分  长底(120天+)满分, 短底(<30天)低分
  ③ 底部缩量   20分  底部量能萎缩程度 (散户出逃主力吸筹)
  ④ 启动信号   20分  近20日放量阳线 (量比>=1.5, 阳线覆盖阴线)
  ⑤ MA生命线   10分  站上MA20
  ⑥ 反弹幅度   10分  距低点+5%~+40% (已启动未涨飞)
"""
import sqlite3, sys, time
from datetime import date

DB = "/home/ubuntu/Sequoia-X-a/data/sequoia_v2.db"
MIN_DAYS = 250  # 至少250个交易日数据
TOP_N = 15

def load_all_data(conn):
    """一次性拉取所有股票的前复权K线"""
    print("加载全市场K线数据...")
    rows = conn.execute(
        "SELECT symbol, date, open, high, low, close, close_qfq, volume "
        "FROM stock_daily WHERE close_qfq>0 AND date>='2024-06-01' "
        "ORDER BY symbol, date"
    ).fetchall()
    print(f"  共 {len(rows)} 行")
    data = {}
    for sym, d, o, h, l, c, cq, v in rows:
        if c and c > 0:
            ratio = cq / c
        else:
            ratio = 1.0
        data.setdefault(sym, []).append({
            "date": d, "o": o*ratio, "h": h*ratio, "l": l*ratio,
            "c": cq, "v": v
        })
    return data

def load_names(conn):
    """最新名称"""
    names = {}
    for sym, name in conn.execute(
        "SELECT symbol, name FROM stock_basics WHERE date=(SELECT MAX(date) FROM stock_basics)"
    ).fetchall():
        names[sym] = name
    return names

def analyze(sym, bars, name, min_streak=4, min_score=60):
    """底部确认框架单股分析, 返回 (分数, 明细dict)
    min_streak: 底部确认期数要求(连续N期评分≥min_score)
    min_score:  确认分数阈值(网格搜索最优=60)"""
    n = len(bars)
    if n < MIN_DAYS:
        return None
    last_date = bars[-1]["date"]
    cur = bars[-1]["c"]
    if cur < 1.0:  # 仙股排除
        return None
    if "ST" in name.upper():
        return None  # 排除ST(信披风险, 底部确认框架不做)
    
    closes = [b["c"] for b in bars]
    vols = [b["v"] for b in bars]
    
    # ── 250日高点(排除最近10日, 需已从高位回落) ──
    look = closes[-250:]
    high_250 = max(look)
    high_idx = look.index(high_250)
    # 高点必须至少在20个交易日前
    if n - 250 + high_idx >= n - 20:
        return None
    drop_pct = (cur / high_250 - 1) * 100  # 距高点跌幅(负)
    
    # ── 底部低点(高点之后) ──
    after_high = closes[n - 250 + high_idx:]
    low = min(after_high)
    low_idx = after_high.index(low)
    # 低点距今交易日数 = 底部时长
    bottom_days = len(after_high) - 1 - low_idx
    bounce_pct = (cur / low - 1) * 100  # 距低点反弹幅度
    
    # ── 均线 ──
    if n < 60: return None
    ma5 = sum(closes[-5:]) / 5
    ma10 = sum(closes[-10:]) / 10
    ma20 = sum(closes[-20:]) / 20
    ma60 = sum(closes[-60:]) / 60
    
    # ── 量能对比: 底部20日均量 vs 下跌段20日均量 ──
    bottom_vol = sum(vols[-20:]) / 20
    # 下跌段: 高点前20日
    decline_start = n - 250 + high_idx
    if decline_start >= 20:
        decline_vol = sum(vols[decline_start-20:decline_start]) / 20
    else:
        decline_vol = bottom_vol
    vol_shrink = bottom_vol / decline_vol if decline_vol > 0 else 1.0
    
    # ── 启动信号: 近20日放量阳线 ──
    launch = False
    launch_vol_ratio = 0
    for i in range(-20, 0):
        b = bars[i]
        prev = bars[i-1]["c"]
        chg = (b["c"] / prev - 1) * 100 if prev else 0
        # 阳线: 收盘>开盘
        if b["c"] > b["o"] and chg >= 3:
            vr = b["v"] / (sum(vols[i-5:i])/5) if i >= -5 and sum(vols[i-5:i]) > 0 else 1
            if vr >= 1.5:
                launch = True
                launch_vol_ratio = max(launch_vol_ratio, vr)
    
    # ── 评分 ──
    score = 0
    detail = {}
    
    # ① 跌幅适中 (20分)
    d = abs(drop_pct)
    if 20 <= d <= 65: score += 20
    elif 15 <= d < 20: score += 14
    elif 65 < d <= 80: score += 10
    elif 10 <= d < 15: score += 8
    else: score += 3
    detail["跌幅"] = f"{drop_pct:.0f}%"
    
    # ② 底部时长 (20分) — 短底重罚
    if bottom_days >= 120: score += 20
    elif bottom_days >= 60: score += 15
    elif bottom_days >= 30: score += 8
    elif bottom_days >= 15: score += 2
    else: score += 0  # 底部<15天: 视为下跌中继, 不给分
    detail["底部天数"] = bottom_days
    
    # ③ 底部缩量 (20分)
    if vol_shrink < 0.5: score += 20
    elif vol_shrink < 0.7: score += 14
    elif vol_shrink < 1.0: score += 7
    else: score += 2
    detail["量能萎缩"] = f"{vol_shrink:.2f}x"
    
    # ④ 启动信号 (20分)
    if launch: score += 20
    elif cur > ma20: score += 8
    detail["启动"] = "✅放量阳线" if launch else "❌待启动"
    
    # ⑤ MA生命线 (10分)
    if cur > ma20: score += 10
    elif cur > ma10: score += 5
    detail["MA20"] = f"{ma20:.2f}{'↑' if cur>ma20 else '↓'}"
    detail["ma20_val"] = round(ma20, 2)
    
    # ⑥ 反弹幅度 (10分)
    if 5 <= bounce_pct <= 40: score += 10
    elif 0 <= bounce_pct < 5: score += 5
    elif 40 < bounce_pct <= 60: score += 5
    elif bounce_pct > 60: score += 2
    elif bounce_pct < 0: score += 0  # 还在创新低
    detail["反弹"] = f"{bounce_pct:+.0f}%"
    
    # 阶段判定
    if bounce_pct < 0:
        stage = "A洗盘"
    elif launch and cur > ma20:
        stage = "B启动"
    elif cur > ma20 and cur < ma60:
        stage = "C回调确认"
    elif cur > ma60:
        stage = "D趋势运行"
    else:
        stage = "A洗盘"
    detail["阶段"] = stage
    detail["现价"] = round(cur, 2)
    detail["MA60"] = f"{ma60:.2f}"
    
    # ── 底部确认计数: 近6个历史评分点(每5日)中 score>=70 的次数 ──
    def quick_score_at(t):
        """完整版评分(与回测score_at一致: 含启动信号+MA20过滤), 返回分数或None"""
        if t < 250:
            return None
        seg = bars[t-249:t+1]
        wc = [b["c"] for b in seg]
        wo = [b["o"] for b in seg]
        wh = [b["h"] for b in seg]
        wl = [b["l"] for b in seg]
        wv = [b["v"] for b in seg]
        c = wc[-1]
        if c < 1.0:
            return None
        h250 = max(wc)
        hi = wc.index(h250)
        if hi >= len(wc) - 20:
            return None
        dp = (c / h250 - 1) * 100
        after = wc[hi:]
        low = min(after)
        li = after.index(low)
        bd = len(after) - 1 - li
        bp = (c / low - 1) * 100
        m20 = sum(wc[-20:]) / 20
        m5 = sum(wc[-5:]) / 5
        m10 = sum(wc[-10:]) / 10
        bv = sum(wv[-20:]) / 20
        ds = max(0, hi - 20)
        dv = sum(wv[ds:ds+20]) / 20 if ds + 20 <= len(wv) else bv
        vs = bv / dv if dv > 0 else 1.0
        # 启动信号(近20日放量阳线)
        launch = False
        for i in range(1, 21):
            prev_c = wc[-i-1]
            chg = (wc[-i] / prev_c - 1) * 100 if prev_c else 0
            if wc[-i] > wo[-i] and chg >= 3:
                v5 = sum(wv[-i-5:-i]) / 5 if i >= 5 else sum(wv[-i:]) / max(1, len(wv[-i:]))
                if v5 > 0 and wv[-i] / v5 >= 1.5:
                    launch = True
                    break
        s = 0
        d = abs(dp)
        if 20 <= d <= 65: s += 20
        elif 15 <= d < 20: s += 14
        elif 65 < d <= 80: s += 10
        elif 10 <= d < 15: s += 8
        else: s += 3
        if bd >= 120: s += 20
        elif bd >= 60: s += 15
        elif bd >= 30: s += 8
        elif bd >= 15: s += 2
        if vs < 0.5: s += 20
        elif vs < 0.7: s += 14
        elif vs < 1.0: s += 7
        else: s += 2
        if launch: s += 20
        elif c > m20: s += 8
        if c > m20: s += 10
        elif c > m10: s += 5
        if 5 <= bp <= 40: s += 10
        elif 0 <= bp < 5: s += 5
        elif 40 < bp <= 60: s += 5
        elif bp > 60: s += 2
        # MA20生命线过滤(与回测一致)
        if c <= m20:
            return None
        return s
    
    n = len(closes)
    streak = 0
    if n >= 250:
        for k in range(0, 31, 5):  # 0,5,10,...,30 (当前+前6个评分点)
            t = n - 1 - k
            s = quick_score_at(t)
            if s is not None and s >= min_score:
                streak += 1
            else:
                break  # 连续中断则停止计数
    detail["确认次数"] = streak
    
    if streak < min_streak:
        return None
    return score, detail

def main():
    conn = sqlite3.connect(DB)
    all_data = load_all_data(conn)
    names = load_names(conn)
    conn.close()
    
    print(f"扫描 {len(all_data)} 只股票...")
    results = []
    t0 = time.time()
    for i, (sym, bars) in enumerate(all_data.items()):
        name = names.get(sym, sym)
        r = analyze(sym, bars, name)
        if r:
            results.append((sym, name, r[0], r[1]))
        if (i+1) % 1000 == 0:
            print(f"  进度 {i+1}/{len(all_data)} 用时{time.time()-t0:.0f}s")
    
    results.sort(key=lambda x: -x[2])
    
    # 分组: 值得看(站上MA20) vs 观察(A洗盘/未站上MA20)
    worth = [r for r in results if r[3]["现价"] > r[3]["ma20_val"]]
    watch = [r for r in results if r[3]["现价"] <= r[3]["ma20_val"]]
    
    print(f"\n{'='*78}")
    print(f"🔥 值得看 Top {TOP_N} (站上MA20生命线 + 底部连续确认≥4期)")
    print(f"{'='*78}")
    print(f"{'代码':<8}{'名称':<10}{'现价':>6}{'阶段':<8}{'跌幅':>6}{'底部':>5}{'量缩':>6}{'确认':>4}{'分':>4}")
    print(f"{'-'*78}")
    for sym, name, score, d in worth[:TOP_N]:
        print(f"{sym:<8}{name:<10}{d['现价']:>6.2f}{d['阶段']:<8}{d['跌幅']:>6}{d['底部天数']:>4}天{d['量能萎缩']:>6}{d['确认次数']:>4}{score:>4}")
    
    print(f"\n👀 观察名单 Top 10 (A洗盘/未站上MA20/确认不足, 等启动信号)")
    print(f"{'代码':<8}{'名称':<10}{'现价':>6}{'阶段':<8}{'跌幅':>6}{'底部':>5}{'量缩':>6}{'确认':>4}{'分':>4}")
    print(f"{'-'*78}")
    for sym, name, score, d in watch[:10]:
        print(f"{sym:<8}{name:<10}{d['现价']:>6.2f}{d['阶段']:<8}{d['跌幅']:>6}{d['底部天数']:>4}天{d['量能萎缩']:>6}{d['确认次数']:>4}{score:>4}")
    
    # 按阶段分组展示
    print(f"\n{'='*70}")
    print("阶段分布:")
    stages = {}
    for sym, name, score, d in results:
        stages.setdefault(d['阶段'], []).append((sym, name, score, d))
    for st in ['B启动', 'C回调确认', 'D趋势运行', 'A洗盘']:
        if st in stages:
            print(f"  {st}: {len(stages[st])}只")
    
    print(f"\n输出文件: /tmp/bottom_confirm_picks.txt")
    with open('/tmp/bottom_confirm_picks.txt', 'w') as f:
        f.write(f"底部确认框架选股 {date.today()}\n")
        f.write(f"{'代码':<8}{'名称':<10}{'现价':>6}{'阶段':<8}{'跌幅':>6}{'底部':>5}{'量缩':>6}{'反弹':>7}{'分':>4}\n")
        for sym, name, score, d in results[:50]:
            f.write(f"{sym:<8}{name:<10}{d['现价']:>6.2f}{d['阶段']:<8}{d['跌幅']:>6}{d['底部天数']:>4}天{d['量能萎缩']:>6}{d['反弹']:>7}{score:>4}\n")

if __name__ == "__main__":
    main()

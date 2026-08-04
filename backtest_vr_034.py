#!/usr/bin/env python3
"""
Backtest: change VR threshold from 0.3 to 0.34 for three strategies.
- 原版 (original):    dist_ma20 10-20%, vr < 0.34, pct_20d 5-25%, no MA60
- 极品A (premium_a):  dist_ma20 12-25%, vr 0.1-0.34, pct_20d 3-15%, MA60 required
- 极品B (premium_b):  dist_ma20 12-25%, vr < 0.34, pct_20d 3-15%, MA60 required

Date range: 2024-01-01 to 2026-07-01 (leave margin for T+20)
"""
import sqlite3
import time
from collections import defaultdict
import statistics

START = '2024-01-01'
END = '2026-07-01'  # backtest end (signals up to this date, needs T+20 data after)

DB = '/home/ubuntu/databases/Sequoia选股.db'

STRATEGIES = {
    'original': {
        'name': '原版',
        'dl': 10, 'dh': 20,
        'vl': 0, 'vh': 0.34,
        'pl': 5, 'ph': 25,
        'ma60': False,
    },
    'premium_a': {
        'name': '极品A',
        'dl': 12, 'dh': 25,
        'vl': 0.1, 'vh': 0.34,
        'pl': 3, 'ph': 15,
        'ma60': True,
    },
    'premium_b': {
        'name': '极品B',
        'dl': 12, 'dh': 25,
        'vl': 0.0, 'vh': 0.34,
        'pl': 3, 'ph': 15,
        'ma60': True,
    },
}

# Baseline (for comparison) — also compute with vr < 0.3
STRATEGIES_BASELINE = {
    'original': {
        'name': '原版(base)',
        'dl': 10, 'dh': 20,
        'vl': 0, 'vh': 0.3,
        'pl': 5, 'ph': 25,
        'ma60': False,
    },
    'premium_b': {
        'name': '极品B(base)',
        'dl': 12, 'dh': 25,
        'vl': 0.0, 'vh': 0.3,
        'pl': 3, 'ph': 15,
        'ma60': True,
    },
}


def is_main_board(symbol):
    """Check if stock is on main board (Shanghai/Shenzhen main board)"""
    code3 = symbol[:3]
    if code3 in ('600', '601', '603', '605'):
        return True
    if code3 in ('000', '001', '002', '003'):
        return True
    return False


def match_strategy(dist, vr, p20, has_ma60, strat):
    """Check if a stock on a given day matches a strategy"""
    if not (strat['dl'] <= dist < strat['dh']):
        return False
    if not (strat['vl'] <= vr < strat['vh']):
        return False
    if p20 is None:
        return False
    if not (strat['pl'] <= p20 < strat['ph']):
        return False
    if strat['ma60'] and not has_ma60:
        return False
    return True


def backtest():
    conn = sqlite3.connect(DB)
    conn.row_factory = sqlite3.Row
    c = conn.cursor()

    # Get all main board symbols
    symbols = [r[0] for r in c.execute(
        "SELECT DISTINCT symbol FROM stock_daily WHERE close_qfq > 0 ORDER BY symbol"
    ).fetchall()]
    symbols = [s for s in symbols if is_main_board(s)]
    print(f"Main board stocks: {len(symbols)}")

    # Signal buckets
    signals = {k: [] for k in STRATEGIES}
    signals_base = {k: [] for k in STRATEGIES_BASELINE}

    t0 = time.time()

    for idx, sym in enumerate(symbols):
        if (idx + 1) % 200 == 0:
            elapsed = time.time() - t0
            print(f"  [{idx+1}/{len(symbols)}] {elapsed:.0f}s elapsed")

        rows = c.execute(
            "SELECT date, close_qfq, volume "
            "FROM stock_daily WHERE symbol=? AND close_qfq>0 AND date>=? ORDER BY date",
            (sym, '2020-01-01')  # pull from 2020 so we have enough data for MA60/vol avg
        ).fetchall()
        if len(rows) < 80:
            continue

        # Pre-extract arrays for fast iteration
        dates = [r[0] for r in rows]
        prices = [r[1] for r in rows]
        volumes = [r[2] for r in rows]
        n = len(rows)

        # Compute MA20, MA60, avg_vol_20 (20-day avg volume), and 20-day return
        ma20_list = [None] * n
        ma60_list = [None] * n
        avgv20_list = [None] * n
        pct20_list = [None] * n

        for i in range(n):
            if i >= 19:
                ma20_list[i] = sum(prices[i-19:i+1]) / 20
                avgv20_list[i] = sum(volumes[i-19:i+1]) / 20
            if i >= 59:
                ma60_list[i] = sum(prices[i-59:i+1]) / 60
            if i >= 20:
                ref = prices[i-20]
                if ref > 0:
                    pct20_list[i] = (prices[i] / ref - 1) * 100

        # Iterate through each day
        for i in range(60, n):
            dt = dates[i]
            if dt > END:
                continue
            if dt < START:
                continue

            price = prices[i]
            ma20 = ma20_list[i]
            ma60 = ma60_list[i]
            p20 = pct20_list[i]
            avgv20 = avgv20_list[i]
            if avgv20 is None or avgv20 <= 0:
                continue
            vr = volumes[i] / avgv20

            if ma20 is None or ma20 <= 0 or price <= 0:
                continue
            dist = (price / ma20 - 1) * 100
            has_ma60 = ma60 is not None and price > ma20 > ma60

            # Compute forward returns
            offsets = {'t1': 1, 't2': 2, 't3': 3, 't5': 5, 't10': 10, 't15': 15, 't20': 20}
            rets = {}
            for tag, off in offsets.items():
                j = i + off
                if j < n and prices[j] > 0:
                    rets[tag] = (prices[j] / price - 1) * 100
                else:
                    rets[tag] = None

            # Check all strategies
            for sk, sv in STRATEGIES.items():
                if match_strategy(dist, vr, p20, has_ma60, sv):
                    signals[sk].append({
                        'date': dt, 'symbol': sym, 'price': price,
                        'dist': dist, 'vr': vr, 'p20': p20,
                        **rets
                    })

            for sk, sv in STRATEGIES_BASELINE.items():
                if match_strategy(dist, vr, p20, has_ma60, sv):
                    signals_base[sk].append({
                        'date': dt, 'symbol': sym, 'price': price,
                        'dist': dist, 'vr': vr, 'p20': p20,
                        **rets
                    })

    conn.close()

    # Print results
    print("\n" + "=" * 80)
    print(f"量比阈值 0.3 → 0.34 回测对比 (回测区间: {START} ~ {END})")
    print("=" * 80)

    period_label = "T+20"
    period_offsets = ['t1', 't2', 't3', 't5', 't10', 't15', 't20']

    def print_strategy(name, sigs):
        sigs = sigs
        valid = [s for s in sigs if s['t20'] is not None]
        total = len(sigs)
        n_valid = len(valid)
        if n_valid == 0:
            print(f"\n  {name:<20s}: 总信号 {total:>4d}, 有T20数据 {n_valid:>4d}")
            return

        rets_t20 = [s['t20'] for s in valid]
        avg = statistics.mean(rets_t20)
        med = statistics.median(rets_t20)
        wr = sum(1 for r in rets_t20 if r > 0) / n_valid * 100

        print(f"\n  {name:<20s}: 总信号 {total:>4d}, 有T20数据 {n_valid:>4d}")
        print(f"  {'':20s} T20 均值: {avg:>+7.2f}%  中位数: {med:>+7.2f}%  胜率: {wr:>5.1f}%")

        # Period breakdown
        print(f"  {'':20s} 持有期收益:", end="")
        for tag in period_offsets:
            vals = [s[tag] for s in valid if s[tag] is not None]
            if vals:
                print(f"  {tag}={statistics.mean(vals):>+6.2f}%", end="")
        print()

        # Win/loss details
        top5 = sorted(valid, key=lambda x: x['t20'], reverse=True)[:5]
        bot5 = sorted(valid, key=lambda x: x['t20'])[:5]
        top5_str = ' '.join(f'{s["symbol"]}({s["t20"]:+.1f}%)' for s in top5)
        bot5_str = ' '.join(f'{s["symbol"]}({s["t20"]:+.1f}%)' for s in bot5)
        print(f"  {'':20s} Top5: {top5_str}")
        print(f"  {'':20s} Bot5: {bot5_str}")

    # Strategy name lookup
    all_names = {}
    for sk, sv in STRATEGIES.items():
        all_names[sk] = sv['name']
    for sk, sv in STRATEGIES_BASELINE.items():
        all_names[sk] = sv['name']

    for group_name, group in [("VR<0.34 (新参数)", signals), ("VR<0.3 (原始参数)", signals_base)]:
        print(f"\n{'─' * 80}")
        print(f"  {group_name}")
        print(f"{'─' * 80}")
        for sk in sorted(group.keys()):
            print_strategy(all_names.get(sk, sk), group[sk])

    # Compare signal overlap
    print(f"\n{'=' * 80}")
    print("  信号数对比")
    print(f"{'=' * 80}")
    print(f"  {'策略':<20s} {'VR<0.3(基准)':>12s} {'VR<0.34':>12s} {'变化':>12s} {'T20均值变化':>12s}")
    print(f"  {'─' * 68}")
    for label_new, label_base in [('original', 'original'), ('premium_b', 'premium_b')]:
        new = [s for s in signals[label_new] if s['t20'] is not None]
        base = [s for s in signals_base[label_base] if s['t20'] is not None]
        avg_new = statistics.mean([s['t20'] for s in new]) if new else 0
        avg_base = statistics.mean([s['t20'] for s in base]) if base else 0
        wr_new = sum(1 for s in new if s['t20'] > 0) / len(new) * 100 if new else 0
        wr_base = sum(1 for s in base if s['t20'] > 0) / len(base) * 100 if base else 0
        change = len(new) - len(base)
        val_change = avg_new - avg_base
        wr_change = wr_new - wr_base
        print(f"  {STRATEGIES[label_new]['name']:<20s} {len(base):>6d}({wr_base:>4.1f}%) {len(new):>6d}({wr_new:>4.1f}%) {change:>+6d}信号 {val_change:>+7.2f}pp {wr_change:>+5.1f}pp胜率")


if __name__ == '__main__':
    backtest()

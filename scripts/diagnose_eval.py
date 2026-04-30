"""
Diagnostic script — trace avg_days=0.0 and daily_breach mechanics.

Runs 10 short episodes without SB3 (random actions), printing per-episode
key accounting metrics so bugs in days_traded / daily_breach / max_dd_pct
are immediately visible.

Usage:
    python3 scripts/diagnose_eval.py
"""
import sys, os
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

import numpy as np
from data.features import FeaturePipeline
from env.ftmo_env   import FTMOEnv

N_EPS   = 10
MAX_STEPS = 200   # shorter window for fast diagnosis

def run():
    pipe = FeaturePipeline()
    df   = pipe.load()

    # Use val split (last 20% for simplicity here)
    n      = len(df)
    df_val = df.iloc[int(n * 0.80) : int(n * 0.90)].copy()
    print(f"Val split: {len(df_val):,} bars  "
          f"({df_val.index.min().date()} → {df_val.index.max().date()})")

    env = FTMOEnv(df_val, training=False, random_start=True,
                  max_episode_steps=MAX_STEPS, use_calendar=False, verbose=0)

    print(f"\n{'Ep':>3} {'Steps':>6} {'n_trades':>9} {'days':>5} "
          f"{'daily_br':>9} {'total_br':>9} {'pnl_pct':>9} {'max_dd_pct':>11}")
    print("-" * 75)

    results = []
    rng = np.random.default_rng(42)
    for ep in range(N_EPS):
        obs, info = env.reset(seed=ep)
        done = False
        steps = 0
        while not done:
            action = rng.uniform(-1, 1, size=(1,)).astype(np.float32)
            obs, r, terminated, truncated, info = env.step(action)
            done = terminated or truncated
            steps += 1

        r = results
        r.append(info)
        print(f"{ep:>3} {steps:>6} {info['n_trades']:>9} {info['trading_days']:>5} "
              f"{bool(info['daily_dd_breach']):>9} {bool(info['total_dd_breach']):>9} "
              f"{info['final_pnl_pct']:>+9.4f} {info['max_dd_pct']:>11.6f}")

    print("-" * 75)
    daily_breach_rate = sum(bool(r['daily_dd_breach']) for r in results) / N_EPS
    avg_days          = np.mean([r['trading_days']    for r in results])
    avg_trades        = np.mean([r['n_trades']         for r in results])
    avg_max_dd        = np.mean([r['max_dd_pct']       for r in results])
    avg_pnl           = np.mean([r['final_pnl_pct']    for r in results])
    print(f"  daily_breach_rate : {daily_breach_rate:.1%}")
    print(f"  avg_days          : {avg_days:.2f}")
    print(f"  avg_trades        : {avg_trades:.1f}")
    print(f"  avg_max_dd_pct    : {avg_max_dd:.6f}")
    print(f"  avg_pnl_pct       : {avg_pnl:+.4f}")

if __name__ == "__main__":
    run()

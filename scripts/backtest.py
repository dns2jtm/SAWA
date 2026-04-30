"""
Backtest a trained PPO model on out-of-sample EURGBP data.
Runs a full deterministic episode and prints FTMO metrics.
Also runs a Monte Carlo stress test (random episode permutations).

Usage:
    python scripts/backtest.py --start 2024-01-01 --end 2025-12-31
    python scripts/backtest.py --start 2024-01-01 --end 2025-12-31 --monte_carlo 500
"""

import argparse, os, sys
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from pathlib import Path
import numpy as np
import pandas as pd

from stable_baselines3 import PPO
from config.settings import DATA
from config.prop_firms import ACTIVE_FIRM
from data.features import FeaturePipeline
from env.ftmo_env import FTMOEnv

try:
    import wandb
    WANDB = True
except ImportError:
    WANDB = False


MODEL_PATH = Path(__file__).parent.parent / "models" / "best" / "best_model.zip"


def load_model():
    return PPO.load(MODEL_PATH, device="cpu")


def _utc_ts(value):
    ts = pd.Timestamp(value)
    return ts.tz_localize("UTC") if ts.tzinfo is None else ts.tz_convert("UTC")


def load_data(start: str, end: str):
    pipe = FeaturePipeline()
    df = pipe.load("XAUUSD_H1_features").sort_index()
    if df.index.tzinfo is None:
        df.index = df.index.tz_localize("UTC")
    return df.loc[_utc_ts(start):_utc_ts(end)].copy()


def run_episode(model, df, deterministic=True, seed=None) -> dict:
    env    = FTMOEnv(df, firm=ACTIVE_FIRM, training=False,
                     random_start=seed is not None,
                     max_episode_steps=max(1, min(720, len(df) - 1)),
                     use_calendar=False)
    if seed is not None:
        obs, _ = env.reset(seed=seed)
    else:
        obs, _ = env.reset()

    done     = False
    total_r  = 0.0
    max_ddd  = 0.0
    max_tdd  = 0.0
    info     = {}
    trade_pnls = []

    while not done:
        action, _ = model.predict(obs.astype(np.float32), deterministic=deterministic)
        obs, r, term, trunc, info = env.step(action)
        done     = term or trunc
        total_r += r
        max_ddd  = max(max_ddd, max(0.0, -info.get("daily_pnl", 0.0)) / (env.initial_balance + 1e-9))
        max_tdd  = max(max_tdd, info.get("max_dd_pct", 0.0))
        if info.get("trade_closed"):
            trade_pnls.append(float(info.get("trade_pnl_usd", 0.0)))

    return {
        "total_reward"  : round(total_r, 4),
        "final_pnl"     : round(info.get("total_pnl", 0), 2),
        "max_daily_dd"  : round(max_ddd, 6),
        "max_total_dd"  : round(max_tdd, 6),
        "trades"        : info.get("n_trades", 0),
        "win_rate"      : round(float(np.mean([p > 0 for p in trade_pnls])) if trade_pnls else 0.0, 4),
        "days_traded"   : info.get("trading_days", 0),
        "ftmo_pass"     : bool(info.get("challenge_passed", False)
                               and not info.get("daily_dd_breach", False)
                               and not info.get("total_dd_breach", False)),
    }


def print_result(label: str, r: dict):
    print(f"\n{'='*55}")
    print(f"  {label}")
    print(f"{'='*55}")
    print(f"  Final PnL        : £{r['final_pnl']:>+10,.2f}")
    print(f"  Total Reward     : {r['total_reward']:>+10.2f}")
    print(f"  Max Daily DD     : {r['max_daily_dd']:>10.2%}")
    print(f"  Max Total DD     : {r['max_total_dd']:>10.2%}")
    print(f"  Trades           : {r['trades']:>10}")
    print(f"  Win Rate         : {r['win_rate']:>10.2%}")
    print(f"  Days Traded      : {r['days_traded']:>10}")
    print(f"  FTMO Status      : {'  ✅ PASS' if r['ftmo_pass'] else '  ❌ FAIL'}")
    print(f"{'='*55}")


def monte_carlo(model, df, n: int = 500):
    print(f"\n[MC] Running {n} Monte Carlo episodes...")
    results = []
    for i in range(n):
        r = run_episode(model, df, deterministic=False, seed=i)
        results.append(r)
        if (i + 1) % 100 == 0:
            pass_rate = sum(x["ftmo_pass"] for x in results) / len(results)
            print(f"[MC] {i+1}/{n} | Pass rate so far: {pass_rate:.1%}")

    df_mc = pd.DataFrame(results)
    print(f"\n[MC] ── Monte Carlo Summary ({n} episodes) ──────────────────")
    print(f"  FTMO Pass Rate   : {df_mc['ftmo_pass'].mean():.1%}")
    print(f"  Median PnL       : £{df_mc['final_pnl'].median():>+,.0f}")
    print(f"  Mean PnL         : £{df_mc['final_pnl'].mean():>+,.0f}")
    print(f"  PnL 5th pct      : £{df_mc['final_pnl'].quantile(0.05):>+,.0f}")
    print(f"  Max Daily DD 95p : {df_mc['max_daily_dd'].quantile(0.95):.2%}")
    print(f"  Max Total DD 95p : {df_mc['max_total_dd'].quantile(0.95):.2%}")
    print(f"  Mean Win Rate    : {df_mc['win_rate'].mean():.2%}")
    print(f"  Mean Trades/ep   : {df_mc['trades'].mean():.0f}")

    os.makedirs("models", exist_ok=True)
    df_mc.to_csv("models/monte_carlo_results.csv", index=False)
    print("  Saved → models/monte_carlo_results.csv")
    return df_mc


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--start",        default=DATA["test_start"])
    parser.add_argument("--end",          default=DATA["test_end"])
    parser.add_argument("--monte_carlo",  type=int, default=0,
                        help="Number of MC episodes (0 = skip)")
    args = parser.parse_args()

    print(f"[BACKTEST] Loading model from {MODEL_PATH}")
    model = load_model()

    print(f"[BACKTEST] Loading data {args.start} → {args.end}")
    df = load_data(args.start, args.end)
    print(f"[BACKTEST] {len(df)} bars | {len(FeaturePipeline.OBS_COLUMNS)} features")

    result = run_episode(model, df, deterministic=True)
    print_result(f"Deterministic backtest  {args.start} → {args.end}", result)

    if args.monte_carlo > 0:
        monte_carlo(model, df, n=args.monte_carlo)

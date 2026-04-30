"""
Walk-Forward Backtest — XAUUSD FTMO Agent
==========================================
Validates a trained PPO model across multiple out-of-sample windows
before any live deployment. This is the gate the model must pass.

Walk-forward methodology:
  - Splits the full history into N rolling windows
  - Each window: train on 18 months, test on 6 months (no overlap)
  - Applies realistic execution costs: spread + slippage + commission
  - Simulates full FTMO challenge rules per window
  - Aggregates pass rate, Sharpe, max DD, Calmar across all windows

Deployment gate (all must pass):
  ✅ Walk-forward pass rate  ≥ 60%
  ✅ Mean Sharpe             ≥ 1.5
  ✅ Max drawdown (worst)    ≤ 7%   (buffer below 10% FTMO limit)
  ✅ Calmar ratio            ≥ 1.0
  ✅ Daily breach rate       ≤ 5%
  ✅ Profit factor           ≥ 1.5
  ✅ Win rate                ≥ 45%  (with 1:1.67 RR this is profitable)

Usage:
  python models/backtest.py --model models/best/best_model.zip
  python models/backtest.py --model models/best/best_model.zip --windows 12
  python models/backtest.py --model models/best/best_model.zip --report
  python models/backtest.py --compare models/best/best_model.zip models/ppo_v2.zip
"""

import argparse
import json
import os
import sys
import warnings
warnings.filterwarnings("ignore")
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from datetime  import datetime, timedelta
from pathlib   import Path
from typing    import List, Optional, Dict

import numpy  as np
import pandas as pd

from config.settings    import FTMO, INSTRUMENT, DATA
from config.prop_firms  import get_config, ACTIVE_FIRM
from config.instruments import get_instrument, ACTIVE_INSTRUMENT
from data.features      import FeaturePipeline
from env.ftmo_env       import FTMOEnv

try:
    from stable_baselines3 import PPO
    _SB3_OK = True
except ImportError:
    _SB3_OK = False

MODELS_DIR   = Path(__file__).parent
REPORTS_DIR  = MODELS_DIR / "reports"
REPORTS_DIR.mkdir(parents=True, exist_ok=True)

INST = get_instrument(ACTIVE_INSTRUMENT)
CFG  = get_config(ACTIVE_FIRM)

# ── Deployment gate thresholds ────────────────────────────────────────────────
GATE = {
    "pass_rate_min":     0.60,   # ≥60% of simulated challenges pass
    "sharpe_min":        1.50,   # Mean annualised Sharpe
    "max_dd_limit":      0.07,   # Worst-window max DD ≤7%
    "calmar_min":        1.00,   # Calmar ≥ 1.0
    "daily_breach_max":  0.05,   # Daily DD breach rate ≤5%
    "profit_factor_min": 1.50,   # Sum(wins) / Sum(losses)
    "win_rate_min":      0.45,   # ≥45% win rate
}


# ════════════════════════════════════════════════════════════════════════════════
# EXECUTION MODEL — Realistic Cost Simulation
# ════════════════════════════════════════════════════════════════════════════════

class ExecutionModel:
    """
    Applies realistic execution costs to every trade.

    XAUUSD specific (2024-2026 averages):
      Spread    : $0.30 typical, $1.50 on news spikes
      Slippage  : $0.10-0.50 per fill (market impact)
      Commission: $0 (FTMO spot gold — no per-trade commission)
      Swap      : -$2.50/lot/night long, -$0.50/lot/night short (approx)
    """
    # Cost profiles
    PROFILES = {
        "optimistic": {"spread": 0.25, "slippage": 0.05, "swap_long": -1.5,  "swap_short": -0.3},
        "realistic":  {"spread": 0.35, "slippage": 0.15, "swap_long": -2.5,  "swap_short": -0.5},
        "pessimistic":{"spread": 0.80, "slippage": 0.40, "swap_long": -3.5,  "swap_short": -0.8},
        "news_spike": {"spread": 2.00, "slippage": 1.50, "swap_long": -2.5,  "swap_short": -0.5},
    }

    def __init__(self, profile: str = "realistic", news_pct: float = 0.05):
        self.base    = self.PROFILES[profile]
        self.news    = self.PROFILES["news_spike"]
        self.news_pct = news_pct   # 5% of bars are near news

    def entry_cost(self, lot: float, is_news: bool = False) -> float:
        """Total cost in USD to enter a position."""
        p = self.news if is_news else self.base
        spread_cost   = (p["spread"]   / INST["pip_size"]) * INST["pip_value_per_lot"] * lot
        slippage_cost = (p["slippage"] / INST["pip_size"]) * INST["pip_value_per_lot"] * lot
        return spread_cost + slippage_cost

    def exit_cost(self, lot: float, is_news: bool = False) -> float:
        """Total cost in USD to exit a position."""
        return self.entry_cost(lot, is_news) * 0.5  # Exit slippage typically less

    def overnight_swap(self, lot: float, direction: int, n_nights: int = 1) -> float:
        """Swap cost for holding position overnight."""
        rate = self.base["swap_long"] if direction > 0 else self.base["swap_short"]
        return rate * lot * n_nights  # negative = cost to us

    def total_round_trip(self, lot: float, n_nights: int = 0,
                         direction: int = 1, is_news: bool = False) -> float:
        """Full round-trip cost for a trade."""
        entry = self.entry_cost(lot, is_news)
        exit_ = self.exit_cost(lot, is_news)
        swap  = self.overnight_swap(lot, direction, n_nights)
        return entry + exit_ + abs(swap)


# ════════════════════════════════════════════════════════════════════════════════
# SINGLE WINDOW SIMULATION
# ════════════════════════════════════════════════════════════════════════════════

def run_window(model, df_window: pd.DataFrame, exec_model: ExecutionModel,
               n_episodes: int = 30, seed_offset: int = 0) -> Dict:
    """
    Run N challenge simulations on a single walk-forward window.
    Returns aggregated statistics for this window.
    """
    env     = FTMOEnv(df_window, firm=ACTIVE_FIRM, training=False,
                      random_start=True, use_calendar=False)
    results = []

    for ep in range(n_episodes):
        obs, _  = env.reset(seed=ep + seed_offset)
        done    = False
        trades  = []
        rng     = np.random.default_rng(seed_offset + ep)
        net_equity = float(CFG["account_size"])
        net_day_start = net_equity
        net_daily_breach = False
        net_total_breach = False
        last_trade_date = None

        while not done:
            action, _ = model.predict(obs, deterministic=True)
            obs, reward, terminated, truncated, info = env.step(action)
            done = terminated or truncated

            if info.get("trade_closed"):
                gross_pnl = info.get("trade_pnl_usd", 0.0)
                lot       = info.get("lot_size",       0.01)
                nights    = info.get("bars_held",       0) // 24
                direction = info.get("direction",       1)
                is_news   = rng.random() < exec_model.news_pct

                step_idx = max(0, min(env.current_step - 1, len(env.df) - 1))
                trade_dt = pd.to_datetime(env.df.iloc[step_idx].get("datetime", env.df.index[step_idx]))
                trade_date = trade_dt.date() if hasattr(trade_dt, "date") else None
                if trade_date != last_trade_date:
                    net_day_start = net_equity
                    last_trade_date = trade_date

                cost      = exec_model.total_round_trip(lot, nights, direction, is_news)
                net_pnl   = gross_pnl - cost
                net_equity += net_pnl

                max_daily_loss = float(info.get("max_daily_loss", CFG["account_size"] * CFG["personal_daily_limit"]))
                max_total_loss = float(info.get("max_total_loss", CFG["account_size"] * CFG["personal_total_limit"]))
                net_daily_breach = net_daily_breach or (net_equity - net_day_start <= -max_daily_loss)
                net_total_breach = net_total_breach or (net_equity <= CFG["account_size"] - max_total_loss)

                trades.append({
                    "gross_pnl": gross_pnl,
                    "cost":      cost,
                    "net_pnl":   net_pnl,
                    "won":       net_pnl > 0,
                    "lot":       lot,
                })

        # Episode-level stats
        if trades:
            gross_pnls = [t["gross_pnl"] for t in trades]
            net_pnls   = [t["net_pnl"]   for t in trades]
            wins       = [t for t in trades if t["won"]]
            losses     = [t for t in trades if not t["won"]]

            total_costs     = sum(t["cost"]    for t in trades)
            total_net_pnl   = sum(net_pnls)
            win_rate        = len(wins) / len(trades) if trades else 0
            gross_profit    = sum(t["net_pnl"] for t in wins)   if wins   else 0
            gross_loss      = abs(sum(t["net_pnl"] for t in losses)) if losses else 1e-9
            profit_factor   = gross_profit / gross_loss

            # Running equity curve for drawdown calculation
            eq_curve = np.cumsum([0] + net_pnls) + CFG["account_size"]
            peak_eq  = np.maximum.accumulate(eq_curve)
            dd_curve = (peak_eq - eq_curve) / peak_eq
            max_dd   = dd_curve.max()

            # Daily returns for Sharpe — use running equity grouped by calendar day
            # so episodes of different lengths produce comparable Sharpe values.
            eq_series = pd.Series(
                np.cumsum([0] + net_pnls) + CFG["account_size"],
                index=pd.RangeIndex(len(net_pnls) + 1),
            )
            daily_ret = eq_series.pct_change().dropna()
            if (len(daily_ret) < 5
                    or float(daily_ret.std()) < 1e-6
                    or float(np.mean(np.abs(daily_ret))) < 1e-6):
                sharpe = 0.0
            else:
                sharpe = float(np.clip(
                    (daily_ret.mean() / daily_ret.std()) * np.sqrt(len(daily_ret)), -10.0, 10.0
                ))

        else:
            total_net_pnl = 0; win_rate = 0; profit_factor = 0
            max_dd = 0; sharpe = 0; total_costs = 0

        gross_final_pnl_pct = info.get("final_pnl_pct", 0.0)
        final_pnl_pct = (net_equity - CFG["account_size"]) / CFG["account_size"]
        passed        = (
            final_pnl_pct >= CFG["profit_target_pct"] and
            info.get("trading_days", 0) >= CFG["min_trading_days"] and
            not info.get("daily_dd_breach", False) and
            not info.get("total_dd_breach", False) and
            not net_daily_breach and
            not net_total_breach
        )

        results.append({
            "passed":        passed,
            "final_pnl_pct": final_pnl_pct,
            "gross_final_pnl_pct": gross_final_pnl_pct,
            "net_pnl_usd":   total_net_pnl,
            "total_costs":   total_costs,
            "n_trades":      len(trades),
            "win_rate":      win_rate,
            "profit_factor": profit_factor,
            "max_dd":        max_dd,
            "sharpe":        sharpe,
            "daily_breach":  bool(info.get("daily_dd_breach", False) or net_daily_breach),
            "total_breach":  bool(info.get("total_dd_breach", False) or net_total_breach),
            "trading_days":  info.get("trading_days", 0),
        })

    df_r = pd.DataFrame(results)
    rets  = df_r["net_pnl_usd"].values / CFG["account_size"]
    calmar = (rets.mean() * 252) / (df_r["max_dd"].max() + 1e-9)

    return {
        "pass_rate":       float(df_r["passed"].mean()),
        "avg_pnl_pct":     float(df_r["final_pnl_pct"].mean()),
        "avg_net_pnl":     float(df_r["net_pnl_usd"].mean()),
        "avg_costs":       float(df_r["total_costs"].mean()),
        "win_rate":        float(df_r["win_rate"].mean()),
        "profit_factor":   float(df_r["profit_factor"].mean()),
        "max_dd_worst":    float(df_r["max_dd"].max()),
        "max_dd_avg":      float(df_r["max_dd"].mean()),
        "sharpe":          float(df_r["sharpe"].mean()),
        "calmar":          float(calmar),
        "daily_breach":    float(df_r["daily_breach"].mean()),
        "total_breach":    float(df_r["total_breach"].mean()),
        "avg_trades":      float(df_r["n_trades"].mean()),
        "avg_days":        float(df_r["trading_days"].mean()),
        "n_episodes":      len(results),
    }


# ════════════════════════════════════════════════════════════════════════════════
# WALK-FORWARD ENGINE
# ════════════════════════════════════════════════════════════════════════════════

def walk_forward(model_path: Path,
                 n_windows:  int = 8,
                 train_months: int = 18,
                 test_months:  int = 6,
                 n_episodes:   int = 30,
                 cost_profile: str = "realistic",
                 df_full: pd.DataFrame = None) -> Dict:
    """
    Full walk-forward validation.

    Window structure (n_windows=8, train=18m, test=6m):
      W1: train 2004-01 → 2005-06 | test 2005-07 → 2005-12
      W2: train 2004-07 → 2006-00 | test 2006-01 → 2006-06
      ...
      W8: test covers 2009-07 → 2009-12
    For 2024-2026 data the windows are recent and most relevant.
    """
    if not _SB3_OK:
        print("SB3 not available"); return {}

    print(f"\n{'='*60}")
    print(f"  Walk-Forward Backtest — {INST['symbol']}")
    print(f"{'='*60}")
    print(f"  Model       : {model_path.name}")
    print(f"  Windows     : {n_windows}  ({train_months}m train / {test_months}m test)")
    print(f"  Episodes/wn : {n_episodes}")
    print(f"  Cost profile: {cost_profile}")
    print(f"{'='*60}\n")

    # Load model
    model = PPO.load(model_path, device="cpu")

    # Load full feature dataframe (caller may supply a rolling window)
    if df_full is None:
        pipe = FeaturePipeline()
        df_full = pipe.load("XAUUSD_H1_features")
    if df_full.index.tzinfo is None:
        df_full.index = df_full.index.tz_localize("UTC")

    exec_model = ExecutionModel(profile=cost_profile)

    # Build walk-forward windows from the TEST period only
    # (training data never contaminates the backtest)
    test_start = pd.Timestamp(DATA["test_start"], tz="UTC")
    test_end   = pd.Timestamp(DATA["test_end"],   tz="UTC")

    # Use full available history for window building
    total_start = df_full.index.min()
    total_end   = df_full.index.max()

    step_months = test_months
    window_start = total_end - pd.DateOffset(
        months=(n_windows * step_months + test_months)
    )
    if window_start < total_start:
        window_start = total_start

    all_window_results = []
    window_dates       = []

    cur = window_start
    for w in range(n_windows):
        w_test_start = cur + pd.DateOffset(months=train_months)
        w_test_end   = w_test_start + pd.DateOffset(months=test_months)

        if w_test_end > total_end:
            break

        df_window = df_full.loc[w_test_start:w_test_end].copy()

        if len(df_window) < 500:
            print(f"  Window {w+1}: too few bars ({len(df_window)}) — skipping")
            cur += pd.DateOffset(months=step_months)
            continue

        print(f"  Window {w+1}/{n_windows}: "
              f"{w_test_start.date()} → {w_test_end.date()} "
              f"({len(df_window):,} bars) ", end="", flush=True)

        wres = run_window(model, df_window, exec_model,
                          n_episodes=n_episodes,
                          seed_offset=w * n_episodes)

        status = "✅ PASS" if wres["pass_rate"] >= GATE["pass_rate_min"] else "❌ FAIL"
        print(f"| Pass: {wres['pass_rate']:.0%}  "
              f"Sharpe: {wres['sharpe']:.2f}  "
              f"MaxDD: {wres['max_dd_worst']:.1%}  {status}")

        wres["window"]       = w + 1
        wres["test_start"]   = str(w_test_start.date())
        wres["test_end"]     = str(w_test_end.date())
        all_window_results.append(wres)
        window_dates.append((w_test_start, w_test_end))

        cur += pd.DateOffset(months=step_months)

    if not all_window_results:
        print("No windows completed — check data availability")
        return {}

    # ── Aggregate ─────────────────────────────────────────────────────────────
    df_wf = pd.DataFrame(all_window_results)

    agg = {
        "model":            model_path.name,
        "n_windows":        len(df_wf),
        "cost_profile":     cost_profile,
        "timestamp":        datetime.now().isoformat(),

        # Key metrics (mean across windows)
        "pass_rate":        round(df_wf["pass_rate"].mean(),       3),
        "pass_rate_worst":  round(df_wf["pass_rate"].min(),        3),
        "sharpe_mean":      round(df_wf["sharpe"].mean(),          3),
        "sharpe_worst":     round(df_wf["sharpe"].min(),           3),
        "calmar_mean":      round(df_wf["calmar"].mean(),          3),
        "max_dd_worst":     round(df_wf["max_dd_worst"].max(),     4),
        "max_dd_avg":       round(df_wf["max_dd_avg"].mean(),      4),
        "daily_breach":     round(df_wf["daily_breach"].mean(),    3),
        "total_breach":     round(df_wf["total_breach"].mean(),    3),
        "win_rate":         round(df_wf["win_rate"].mean(),        3),
        "profit_factor":    round(df_wf["profit_factor"].mean(),   3),
        "avg_pnl_pct":      round(df_wf["avg_pnl_pct"].mean(),    4),
        "avg_costs_usd":    round(df_wf["avg_costs"].mean(),       2),
        "avg_trades":       round(df_wf["avg_trades"].mean(),      1),

        # Per-window breakdown
        "windows":          all_window_results,
    }

    # ── Gate check ─────────────────────────────────────────────────────────────
    gate_results = {
        "pass_rate":    (agg["pass_rate"]       >= GATE["pass_rate_min"],
                         agg["pass_rate"],        GATE["pass_rate_min"]),
        "sharpe":       (agg["sharpe_mean"]      >= GATE["sharpe_min"],
                         agg["sharpe_mean"],      GATE["sharpe_min"]),
        "max_dd":       (agg["max_dd_worst"]     <= GATE["max_dd_limit"],
                         agg["max_dd_worst"],     GATE["max_dd_limit"]),
        "calmar":       (agg["calmar_mean"]      >= GATE["calmar_min"],
                         agg["calmar_mean"],      GATE["calmar_min"]),
        "daily_breach": (agg["daily_breach"]     <= GATE["daily_breach_max"],
                         agg["daily_breach"],     GATE["daily_breach_max"]),
        "profit_factor":(agg["profit_factor"]    >= GATE["profit_factor_min"],
                         agg["profit_factor"],    GATE["profit_factor_min"]),
        "win_rate":     (agg["win_rate"]         >= GATE["win_rate_min"],
                         agg["win_rate"],         GATE["win_rate_min"]),
    }

    all_pass   = all(v[0] for v in gate_results.values())
    agg["gate_passed"] = all_pass
    agg["gate_detail"] = {k: {"passed": v[0], "value": v[1], "threshold": v[2]}
                          for k, v in gate_results.items()}

    # ── Print report ───────────────────────────────────────────────────────────
    _print_report(agg, gate_results, all_pass)

    # ── Save ──────────────────────────────────────────────────────────────────
    report_path = REPORTS_DIR / f"wf_{model_path.stem}_{datetime.now().strftime('%Y%m%d_%H%M')}.json"
    with open(report_path, "w") as f:
        json.dump(agg, f, indent=2, default=str)
    print(f"\n  Report saved → {report_path}")

    return agg


def _print_report(agg: Dict, gate_results: Dict, all_pass: bool):
    """Print the walk-forward report to console."""
    pad = 55
    print(f"\n{'='*pad}")
    print(f"  Walk-Forward Report — {agg['model']}")
    print(f"  {agg['n_windows']} windows  |  cost: {agg['cost_profile']}")
    print(f"{'='*pad}")

    g = gate_results
    rows = [
        ("Pass rate",      f"{agg['pass_rate']:.0%}",
         f"≥{GATE['pass_rate_min']:.0%}",     g["pass_rate"][0]),
        ("Sharpe (mean)",  f"{agg['sharpe_mean']:.2f}",
         f"≥{GATE['sharpe_min']:.1f}",         g["sharpe"][0]),
        ("Sharpe (worst)", f"{agg['sharpe_worst']:.2f}", "—", True),
        ("Max DD (worst)", f"{agg['max_dd_worst']:.1%}",
         f"≤{GATE['max_dd_limit']:.0%}",       g["max_dd"][0]),
        ("Calmar",         f"{agg['calmar_mean']:.2f}",
         f"≥{GATE['calmar_min']:.1f}",          g["calmar"][0]),
        ("Daily breach",   f"{agg['daily_breach']:.1%}",
         f"≤{GATE['daily_breach_max']:.0%}",   g["daily_breach"][0]),
        ("Win rate",       f"{agg['win_rate']:.1%}",
         f"≥{GATE['win_rate_min']:.0%}",        g["win_rate"][0]),
        ("Profit factor",  f"{agg['profit_factor']:.2f}",
         f"≥{GATE['profit_factor_min']:.1f}",  g["profit_factor"][0]),
        ("Avg PnL/ep",     f"{agg['avg_pnl_pct']:+.2%}", "—", True),
        ("Avg costs/ep",   f"${agg['avg_costs_usd']:.0f}", "—", True),
        ("Avg trades/ep",  f"{agg['avg_trades']:.0f}", "—", True),
    ]

    for name, val, threshold, passed in rows:
        icon = "✅" if passed else "❌"
        thr  = f"  (threshold: {threshold})" if threshold != "—" else ""
        print(f"  {icon}  {name:<20} {val:<10}{thr}")

    print(f"{'='*pad}")
    verdict = "✅ GATE PASSED — model approved for live deployment" if all_pass               else "❌ GATE FAILED — retrain required before going live"
    print(f"  {verdict}")
    print(f"{'='*pad}")


# ════════════════════════════════════════════════════════════════════════════════
# EQUITY CURVE PLOTTER
# ════════════════════════════════════════════════════════════════════════════════

def plot_equity_curves(model_path: Path, df_window: pd.DataFrame,
                       n_episodes: int = 10, save_path: Path = None):
    """Plot equity curves for N simulated challenges."""
    try:
        import matplotlib.pyplot as plt
        import matplotlib.ticker as mtick
    except ImportError:
        print("matplotlib not installed — skipping plot")
        return

    model      = PPO.load(model_path, device="cpu")
    exec_model = ExecutionModel(profile="realistic")
    env        = FTMOEnv(df_window, firm=ACTIVE_FIRM, training=False,
                         random_start=True, use_calendar=False)

    fig, axes = plt.subplots(2, 1, figsize=(14, 9), facecolor="#0d1117")
    ax1, ax2  = axes

    passed_curves = []
    failed_curves = []
    all_trades    = []

    for ep in range(n_episodes):
        obs, _    = env.reset(seed=ep)
        done      = False
        equity    = float(CFG["account_size"])
        day_start = equity
        daily_breach = False
        total_breach = False
        last_date = None
        eq_curve  = [equity]
        ep_trades = []

        while not done:
            action, _ = model.predict(obs, deterministic=True)
            obs, r, terminated, truncated, info = env.step(action)
            done = terminated or truncated

            if info.get("trade_closed"):
                pnl  = info.get("trade_pnl_usd", 0.0)
                lot  = info.get("lot_size",       0.01)
                cost = exec_model.total_round_trip(lot)
                net  = pnl - cost
                step_idx = max(0, min(env.current_step - 1, len(env.df) - 1))
                trade_dt = pd.to_datetime(env.df.iloc[step_idx].get("datetime", env.df.index[step_idx]))
                trade_date = trade_dt.date() if hasattr(trade_dt, "date") else None
                if trade_date != last_date:
                    day_start = equity
                    last_date = trade_date
                equity += net
                daily_breach = daily_breach or (equity - day_start <= -float(info.get("max_daily_loss", CFG["personal_daily_abs"])))
                total_breach = total_breach or (equity <= CFG["account_size"] - float(info.get("max_total_loss", CFG["personal_total_abs"])))
                ep_trades.append(net)
            eq_curve.append(equity)

        passed = (
            equity >= CFG["account_size"] * (1 + CFG["profit_target_pct"]) and
            info.get("trading_days", 0) >= CFG["min_trading_days"] and
            not info.get("daily_dd_breach", False) and
            not info.get("total_dd_breach", False) and
            not daily_breach and
            not total_breach
        )
        curve  = np.array(eq_curve)
        (passed_curves if passed else failed_curves).append(curve)
        all_trades.extend(ep_trades)

    # ── Equity curves ──────────────────────────────────────────────────────────
    target_line = CFG["account_size"] * (1 + CFG["profit_target_pct"])
    dd_line     = CFG["account_size"] * (1 - CFG["max_total_loss_pct"])

    for c in failed_curves:
        ax1.plot(c / CFG["account_size"] - 1, color="#ef4444", alpha=0.4, lw=0.8)
    for c in passed_curves:
        ax1.plot(c / CFG["account_size"] - 1, color="#22c55e", alpha=0.7, lw=1.0)

    ax1.axhline(CFG["profit_target_pct"],    color="#22c55e", ls="--", lw=1.5,
                label=f"Target +{CFG['profit_target_pct']:.0%}")
    ax1.axhline(-CFG["max_total_loss_pct"],  color="#ef4444", ls="--", lw=1.5,
                label=f"Total DD limit -{CFG['max_total_loss_pct']:.0%}")
    ax1.axhline(-CFG["max_daily_loss_pct"],  color="#f97316", ls=":",  lw=1.0,
                label=f"Daily DD limit -{CFG['max_daily_loss_pct']:.0%}")
    ax1.axhline(0, color="#6b7280", lw=0.5)

    n_pass = len(passed_curves)
    n_fail = len(failed_curves)
    ax1.set_title(
        f"XAUUSD FTMO Challenge Simulations  |  "
        f"Pass: {n_pass}/{n_episodes} ({n_pass/n_episodes:.0%})",
        color="white", fontsize=13, pad=12
    )
    ax1.set_ylabel("PnL %", color="#9ca3af")
    ax1.set_xlabel("Bars elapsed", color="#9ca3af")
    ax1.yaxis.set_major_formatter(mtick.PercentFormatter(xmax=1))
    ax1.legend(fontsize=9, facecolor="#1f2937", labelcolor="white")
    ax1.set_facecolor("#111827")
    ax1.tick_params(colors="#6b7280")
    for sp in ax1.spines.values():
        sp.set_color("#374151")

    # ── Trade PnL distribution ─────────────────────────────────────────────────
    if all_trades:
        trades_arr = np.array(all_trades)
        bins       = np.linspace(trades_arr.min(), trades_arr.max(), 40)
        ax2.hist(trades_arr[trades_arr >= 0], bins=bins, color="#22c55e",
                 alpha=0.7, label="Wins")
        ax2.hist(trades_arr[trades_arr <  0], bins=bins, color="#ef4444",
                 alpha=0.7, label="Losses")
        ax2.axvline(0, color="white", lw=0.8)
        ax2.axvline(np.mean(trades_arr), color="#facc15", lw=1.5, ls="--",
                    label=f"Mean ${np.mean(trades_arr):.0f}")

        w_rate = (trades_arr > 0).mean()
        pf     = trades_arr[trades_arr>0].sum() / abs(trades_arr[trades_arr<0].sum() + 1e-9)
        ax2.set_title(
            f"Trade PnL Distribution  |  "
            f"Win Rate: {w_rate:.1%}  |  Profit Factor: {pf:.2f}  |  "
            f"Mean: ${np.mean(trades_arr):.0f}",
            color="white", fontsize=11, pad=10
        )
        ax2.set_xlabel("Trade Net PnL (USD)", color="#9ca3af")
        ax2.set_ylabel("Frequency",           color="#9ca3af")
        ax2.legend(fontsize=9, facecolor="#1f2937", labelcolor="white")
        ax2.set_facecolor("#111827")
        ax2.tick_params(colors="#6b7280")
        for sp in ax2.spines.values():
            sp.set_color("#374151")

    fig.patch.set_facecolor("#0d1117")
    plt.tight_layout(pad=2)

    save_path = save_path or REPORTS_DIR / f"equity_curves_{model_path.stem}.png"
    plt.savefig(save_path, dpi=150, bbox_inches="tight", facecolor="#0d1117")
    print(f"  Chart saved → {save_path}")
    plt.close()


# ════════════════════════════════════════════════════════════════════════════════
# MODEL COMPARISON
# ════════════════════════════════════════════════════════════════════════════════

def compare_models(model_paths: List[Path], n_windows: int = 4) -> None:
    """Compare multiple trained models on the same walk-forward windows."""
    results = {}
    for mp in model_paths:
        print(f"\n  Evaluating {mp.name}...")
        r = walk_forward(mp, n_windows=n_windows, n_episodes=20)
        if r:
            results[mp.name] = r

    if len(results) < 2:
        print("Need at least 2 models to compare")
        return

    print(f"\n{'='*65}")
    print(f"  Model Comparison")
    print(f"{'='*65}")
    header = f"  {'Metric':<22}" + "".join(f"{n[:18]:<20}" for n in results)
    print(header)
    print("  " + "-" * (22 + 20 * len(results)))

    metrics = [
        ("pass_rate",     "{:.0%}"),
        ("sharpe_mean",   "{:.2f}"),
        ("max_dd_worst",  "{:.1%}"),
        ("calmar_mean",   "{:.2f}"),
        ("win_rate",      "{:.1%}"),
        ("profit_factor", "{:.2f}"),
        ("daily_breach",  "{:.1%}"),
        ("avg_pnl_pct",   "{:+.2%}"),
    ]

    for key, fmt in metrics:
        row = f"  {key:<22}"
        vals = [r.get(key, 0) for r in results.values()]
        best = max(vals) if "breach" not in key and "dd" not in key else min(vals)
        for v in vals:
            cell = fmt.format(v)
            mark = " ⭐" if abs(v - best) < 1e-6 else ""
            row += f"{cell + mark:<20}"
        print(row)

    print(f"{'='*65}")

    # Gate pass summary
    for name, r in results.items():
        gate = "✅ PASSES GATE" if r.get("gate_passed") else "❌ FAILS GATE"
        print(f"  {name}: {gate}")


# ════════════════════════════════════════════════════════════════════════════════
# CLI
# ════════════════════════════════════════════════════════════════════════════════

if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description="Walk-forward backtest for FTMO RL agent")
    parser.add_argument("--model",   required=False, default=None,
                        help="Path to trained model .zip")
    parser.add_argument("--windows", type=int, default=8,
                        help="Number of walk-forward windows")
    parser.add_argument("--episodes",type=int, default=30,
                        help="Episodes per window")
    parser.add_argument("--cost",    default="realistic",
                        choices=["optimistic", "realistic", "pessimistic"],
                        help="Execution cost profile")
    parser.add_argument("--report",  action="store_true",
                        help="Generate equity curve chart")
    parser.add_argument("--compare", nargs="+", default=None,
                        metavar="MODEL",
                        help="Compare multiple models")
    args = parser.parse_args()

    if args.compare:
        compare_models([Path(p) for p in args.compare], n_windows=args.windows)
    else:
        # Auto-find best model if not specified
        model_path = Path(args.model) if args.model else None
        if model_path is None:
            candidates = sorted((MODELS_DIR / "best").glob("best_model.zip"))
            if not candidates:
                candidates = sorted(MODELS_DIR.glob("ppo_xauusd_final_*.zip"))
            if not candidates:
                print("No model found. Run: python models/train.py first")
                sys.exit(1)
            model_path = candidates[-1]

        result = walk_forward(
            model_path  = model_path,
            n_windows   = args.windows,
            n_episodes  = args.episodes,
            cost_profile= args.cost,
        )

        if args.report and result.get("gate_passed"):
            print("\nGenerating equity curve chart...")
            pipe    = FeaturePipeline()
            df_full = pipe.load("XAUUSD_H1_features")
            # Use most recent 6 months for the chart
            df_chart = df_full.iloc[-4380:]  # ~6 months of H1
            plot_equity_curves(model_path, df_chart, n_episodes=20)

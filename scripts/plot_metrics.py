#!/usr/bin/env python3
"""
Performance Visualization Script
Reads FTMO metrics JSONL logs and generates a 4-panel dashboard.
Usage: python3 scripts/plot_metrics.py [--log path/to/ftmo_metrics.jsonl]
"""

import os
import sys
import json
import argparse
from pathlib import Path
import pandas as pd
import matplotlib.pyplot as plt
import seaborn as sns

ROOT_DIR = Path(__file__).resolve().parent.parent
LOGS_DIR = ROOT_DIR / "models" / "logs"

def find_latest_log() -> Path:
    """Finds the most recently modified ftmo_metrics_*.jsonl file."""
    logs = list(LOGS_DIR.glob("ftmo_metrics_*.jsonl"))
    if not logs:
        return None
    return max(logs, key=os.path.getmtime)

def plot_metrics(log_path: Path, save_path: Path):
    print(f"Reading log: {log_path.name}")
    
    records = []
    with open(log_path, "r") as f:
        for line in f:
            if not line.strip():
                continue
            try:
                records.append(json.loads(line))
            except json.JSONDecodeError:
                pass

    if not records:
        print("Log file is empty or invalid.")
        return

    df = pd.DataFrame(records)
    if "step" not in df.columns:
        print("Missing 'step' column in logs.")
        return

    df = df.sort_values("step")
    
    # Setup aesthetic
    sns.set_theme(style="darkgrid", context="talk")
    fig, axs = plt.subplots(2, 2, figsize=(16, 10), facecolor="#1e1e1e")
    fig.patch.set_facecolor('#1e1e1e')
    
    # Common text color
    text_color = "#e0e0e0"
    for ax in axs.flat:
        ax.set_facecolor("#2b2b2b")
        ax.tick_params(colors=text_color)
        ax.xaxis.label.set_color(text_color)
        ax.yaxis.label.set_color(text_color)
        ax.title.set_color(text_color)
        for spine in ax.spines.values():
            spine.set_color("#444444")

    # ── 1. Pass Rate ────────────────────────────────────────────────────────
    ax = axs[0, 0]
    if "pass_rate" in df.columns:
        ax.plot(df["step"], df["pass_rate"] * 100, color="#2ecc71", linewidth=2)
        # Add rolling average
        if len(df) > 10:
            ax.plot(df["step"], df["pass_rate"].rolling(10).mean() * 100, 
                    color="#27ae60", linestyle="--", linewidth=1.5, alpha=0.7)
    ax.set_title("Challenge Pass Rate (%)")
    ax.set_ylim(-5, 105)

    # ── 2. Drawdown Breaches ───────────────────────────────────────────────
    ax = axs[0, 1]
    if "daily_breach" in df.columns:
        ax.plot(df["step"], df["daily_breach"] * 100, color="#e74c3c", label="Daily DD", linewidth=2)
    if "total_breach" in df.columns:
        ax.plot(df["step"], df["total_breach"] * 100, color="#e67e22", label="Total DD", linewidth=2)
    ax.set_title("Drawdown Breach Rate (%)")
    ax.set_ylim(-5, 105)
    ax.legend(facecolor="#2b2b2b", labelcolor=text_color, edgecolor="#444444")

    # ── 3. Average PnL ─────────────────────────────────────────────────────
    ax = axs[1, 0]
    if "avg_pnl_pct" in df.columns:
        ax.plot(df["step"], df["avg_pnl_pct"] * 100, color="#3498db", linewidth=2)
        ax.axhline(10.0, color="#f1c40f", linestyle="--", alpha=0.5, label="Target (10%)")
        ax.axhline(0.0, color="#e0e0e0", linestyle="-", alpha=0.3)
        ax.legend(facecolor="#2b2b2b", labelcolor=text_color, edgecolor="#444444")
    ax.set_title("Average Episode PnL (%)")

    # ── 4. Sharpe Ratio ────────────────────────────────────────────────────
    ax = axs[1, 1]
    if "sharpe" in df.columns:
        ax.plot(df["step"], df["sharpe"], color="#9b59b6", linewidth=2)
        if len(df) > 10:
            ax.plot(df["step"], df["sharpe"].rolling(10).mean(), 
                    color="#8e44ad", linestyle="--", linewidth=1.5, alpha=0.7)
    ax.set_title("Sharpe Ratio")

    # Format x-axis for millions (M) or thousands (k)
    def step_formatter(x, pos):
        if x >= 1e6:
            return f"{x*1e-6:.1f}M"
        elif x >= 1e3:
            return f"{x*1e-3:.0f}k"
        return f"{int(x)}"

    from matplotlib.ticker import FuncFormatter
    for ax in axs.flat:
        ax.xaxis.set_major_formatter(FuncFormatter(step_formatter))
        ax.set_xlabel("Environment Steps")

    plt.tight_layout()
    plt.savefig(save_path, dpi=150, facecolor=fig.get_facecolor(), edgecolor='none')
    print(f"✅ Dashboard saved to: {save_path.resolve()}")
    
    # Fallback to display if running locally
    if os.environ.get("DISPLAY") or sys.platform == "darwin":
        try:
            plt.show()
        except:
            pass

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Plot FTMO RL training metrics.")
    parser.add_argument("--log", type=str, default=None,
                        help="Path to specific ftmo_metrics_*.jsonl file")
    args = parser.parse_args()

    if args.log:
        log_path = Path(args.log)
    else:
        log_path = find_latest_log()

    if not log_path or not log_path.exists():
        print("❌ No ftmo_metrics.jsonl log found.")
        sys.exit(1)

    save_path = log_path.parent / f"dashboard_{log_path.stem.replace('ftmo_metrics_', '')}.png"
    plot_metrics(log_path, save_path)

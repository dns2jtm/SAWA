"""
Challenge Monitor — Real-time FTMO account dashboard
=====================================================
Connects to MetaApi, pulls live account state for all configured accounts,
and displays a live terminal dashboard showing:
  - Current equity vs balance
  - Daily drawdown used / remaining
  - Total drawdown used / remaining
  - Progress toward profit target
  - Colour-coded danger zones
  - Alert when approaching personal limits

Usage:
    python scripts/challenge_monitor.py                    # monitor all accounts
    python scripts/challenge_monitor.py --account 531260945
    python scripts/challenge_monitor.py --interval 30      # refresh every 30s

Requires:
    META_API_TOKEN and account IDs in .env
    pip install metaapi-cloud-sdk rich python-dotenv
"""

import argparse
import asyncio
import os
import sys
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from datetime import datetime, timezone
from dotenv import load_dotenv
load_dotenv()

from rich.console import Console
from rich.table import Table
from rich.panel import Panel
from rich.layout import Layout
from rich.live import Live
from rich.text import Text
from rich import box

from config.prop_firms import get_config, ACTIVE_FIRM

console = Console()

# ── Account registry — add your accounts here ─────────────────────────────────
# Format: { "account_id": { "label": "...", "firm": "ftmo_swing", "starting_balance": 70000 } }
ACCOUNTS = {
    "531260945": {
        "label":            "Account 1 (531260945)",
        "firm":             "ftmo_swing",
        "starting_balance": 70_000,
    },
    "531260835": {
        "label":            "Account 2 (531260835)",
        "firm":             "ftmo_swing",
        "starting_balance": 70_000,
    },
}


# ── MetaApi live data fetcher ─────────────────────────────────────────────────

async def fetch_account_state(meta_api_token: str, account_id: str) -> dict:
    """Fetch live account state from MetaApi."""
    try:
        from metaapi_cloud_sdk import MetaApi
        api      = MetaApi(meta_api_token)
        account  = await api.metatrader_account_api.get_account(account_id)
        conn     = account.get_rpc_connection()
        await conn.connect()
        await conn.wait_synchronized()

        info     = await conn.get_account_information()
        equity   = info.get("equity",  0)
        balance  = info.get("balance", 0)
        margin   = info.get("margin",  0)

        positions = await conn.get_positions()
        open_pnl  = sum(p.get("unrealizedProfit", 0) for p in positions)

        await conn.close()
        await api.close()

        return {
            "equity":       equity,
            "balance":      balance,
            "margin":       margin,
            "open_pnl":     open_pnl,
            "n_positions":  len(positions),
            "error":        None,
        }
    except Exception as e:
        return {
            "equity":      0, "balance":     0,
            "margin":      0, "open_pnl":    0,
            "n_positions": 0, "error":       str(e),
        }


# ── Dashboard rendering ───────────────────────────────────────────────────────

def _pct_bar(used: float, limit: float, width: int = 20) -> Text:
    """Render a colour-coded progress bar."""
    ratio = min(used / limit, 1.0) if limit > 0 else 0
    filled = int(ratio * width)
    bar    = "█" * filled + "░" * (width - filled)

    if ratio < 0.50:  colour = "green"
    elif ratio < 0.75: colour = "yellow"
    elif ratio < 0.90: colour = "orange1"
    else:              colour = "red"

    pct_text = f"{ratio:.0%}"
    t = Text()
    t.append(f"[{bar}] ", style=colour)
    t.append(pct_text, style=f"bold {colour}")
    return t


def build_table(account_states: list) -> Table:
    table = Table(
        title=f"🔴 FTMO Challenge Monitor — {datetime.now(timezone.utc).strftime('%H:%M:%S UTC')}",
        box=box.ROUNDED,
        show_header=True,
        header_style="bold cyan",
        border_style="cyan",
        expand=True,
    )

    table.add_column("Account",         style="bold white",  min_width=22)
    table.add_column("Balance",         style="white",       min_width=12, justify="right")
    table.add_column("Equity",          style="white",       min_width=12, justify="right")
    table.add_column("Open PnL",        style="white",       min_width=12, justify="right")
    table.add_column("Daily DD Used",   min_width=30)
    table.add_column("Total DD Used",   min_width=30)
    table.add_column("Profit Progress", min_width=30)
    table.add_column("Status",          min_width=12, justify="center")

    for row in account_states:
        cfg     = get_config(row["firm"])
        state   = row["state"]
        label   = row["label"]
        start   = row["starting_balance"]

        if state["error"]:
            table.add_row(
                label, "—", "—", "—", "—", "—", "—",
                Text("⚠ API ERR", style="red"),
            )
            continue

        equity   = state["equity"]
        balance  = state["balance"]
        open_pnl = state["open_pnl"]

        # Drawdown calculations (FTMO uses balance-based daily DD)
        daily_dd_used    = max(0, start - equity)          # worst intraday
        total_dd_used    = max(0, start - min(balance, equity))
        profit_progress  = max(0, equity - start)

        daily_limit_abs  = cfg["personal_daily_abs"]
        total_limit_abs  = cfg["personal_total_abs"]
        profit_target    = cfg["profit_target_abs"]

        daily_ratio  = daily_dd_used  / daily_limit_abs  if daily_limit_abs  > 0 else 0
        total_ratio  = total_dd_used  / total_limit_abs  if total_limit_abs  > 0 else 0
        profit_ratio = profit_progress / profit_target   if profit_target    > 0 else 0

        # Status
        if daily_ratio > 0.90 or total_ratio > 0.90:
            status = Text("🚨 DANGER",  style="bold red blink")
        elif daily_ratio > 0.75 or total_ratio > 0.75:
            status = Text("⚠ WARNING", style="bold yellow")
        elif profit_ratio >= 1.0:
            status = Text("✅ PASSED",  style="bold green")
        else:
            status = Text("✔ OK",      style="bold green")

        # Colour open PnL
        pnl_colour  = "green" if open_pnl >= 0 else "red"
        pnl_text    = Text(f"£{open_pnl:+,.2f}", style=pnl_colour)

        table.add_row(
            f"{label}
[dim]{row['firm']}[/dim]",
            f"£{balance:,.2f}",
            f"£{equity:,.2f}",
            pnl_text,
            _pct_bar(daily_dd_used,   daily_limit_abs),
            _pct_bar(total_dd_used,   total_limit_abs),
            _pct_bar(profit_progress, profit_target),
            status,
        )

    return table


def _print_alerts(account_states: list):
    """Print urgent alerts below the table."""
    for row in account_states:
        if row["state"]["error"]:
            continue
        cfg   = get_config(row["firm"])
        state = row["state"]
        start = row["starting_balance"]

        daily_dd_used = max(0, start - state["equity"])
        total_dd_used = max(0, start - min(state["balance"], state["equity"]))

        daily_limit_abs = cfg["personal_daily_abs"]
        total_limit_abs = cfg["personal_total_abs"]
        firm_daily_abs  = cfg["max_daily_loss_abs"]
        firm_total_abs  = cfg["max_total_loss_abs"]

        remaining_daily = daily_limit_abs - daily_dd_used
        remaining_total = total_limit_abs - total_dd_used
        firm_remaining  = firm_daily_abs  - daily_dd_used

        if daily_dd_used / daily_limit_abs > 0.85:
            console.print(
                f"[bold red blink]🚨 ALERT {row['label']}: "
                f"Daily DD at {daily_dd_used/firm_daily_abs:.0%} of FTMO limit! "
                f"Only £{remaining_daily:,.0f} personal buffer remaining. "
                f"STOP TRADING.[/bold red blink]"
            )
        if total_dd_used / total_limit_abs > 0.85:
            console.print(
                f"[bold red blink]🚨 ALERT {row['label']}: "
                f"Total DD at {total_dd_used/firm_total_abs:.0%} of FTMO limit! "
                f"Only £{remaining_total:,.0f} personal buffer remaining.[/bold red blink]"
            )


# ── Main loop ─────────────────────────────────────────────────────────────────

async def run_monitor(account_ids: list, interval: int = 60):
    meta_api_token = os.getenv("META_API_TOKEN", "")

    if not meta_api_token:
        console.print("[red]META_API_TOKEN not set in .env — using demo mode[/red]")
        # Demo mode — simulated state for testing without MetaApi
        demo_states = [
            {"equity": 68_756.06, "balance": 67_688.88, "open_pnl": 1_067.18, "n_positions": 1, "margin": 200, "error": None},
            {"equity": 71_509.84, "balance": 70_624.76, "open_pnl": 885.08,   "n_positions": 1, "margin": 180, "error": None},
        ]
        account_data = [
            {**ACCOUNTS[aid], "account_id": aid, "state": state}
            for aid, state in zip(list(ACCOUNTS.keys())[:len(demo_states)], demo_states)
        ]
        table = build_table(account_data)
        console.print(table)
        _print_alerts(account_data)
        console.print(f"
[dim]Demo mode — add META_API_TOKEN to .env for live data[/dim]")
        return

    console.print(f"[cyan]Starting monitor for {len(account_ids)} account(s)... refresh every {interval}s[/cyan]")
    console.print(f"[dim]Press Ctrl+C to stop[/dim]
")

    while True:
        tasks = [
            fetch_account_state(meta_api_token, aid)
            for aid in account_ids
        ]
        states = await asyncio.gather(*tasks)

        account_data = []
        for aid, state in zip(account_ids, states):
            info = ACCOUNTS.get(aid, {
                "label": aid, "firm": ACTIVE_FIRM,
                "starting_balance": state.get("balance", 70_000)
            })
            account_data.append({**info, "account_id": aid, "state": state})

        console.clear()
        table = build_table(account_data)
        console.print(table)
        _print_alerts(account_data)
        console.print(f"
[dim]Next refresh in {interval}s — Ctrl+C to stop[/dim]")
        await asyncio.sleep(interval)


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--account",  nargs="+", default=list(ACCOUNTS.keys()),
                        help="Account IDs to monitor (default: all in ACCOUNTS dict)")
    parser.add_argument("--interval", type=int,  default=60,
                        help="Refresh interval in seconds (default: 60)")
    parser.add_argument("--demo",     action="store_true",
                        help="Run in demo mode without MetaApi connection")
    args = parser.parse_args()

    if args.demo:
        os.environ["META_API_TOKEN"] = ""

    asyncio.run(run_monitor(args.account, args.interval))

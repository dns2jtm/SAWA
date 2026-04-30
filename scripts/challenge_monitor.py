"""
Challenge Monitor — Real-time FTMO account dashboard
=====================================================
Connects to cTrader, pulls live account state for all configured accounts,
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
    CTRADER credentials in .env
    pip install ctrader-open-api rich python-dotenv
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
from config.settings import CTRADER

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


# ── cTrader live data fetcher ─────────────────────────────────────────────────

class CTraderMonitorClient:
    _reactor_started = False

    def __init__(self):
        self.client = None
        self._connected = False
        self._app_auth = False
        self.account_auths = set()

        from twisted.internet import reactor
        import threading
        if not CTraderMonitorClient._reactor_started:
            CTraderMonitorClient._reactor_started = True
            threading.Thread(target=lambda: reactor.run(installSignalHandlers=False), daemon=True).start()

        self._init_ctrader()

    def _init_ctrader(self):
        try:
            from ctrader_open_api import Client, EndPoints, TcpProtocol
            from ctrader_open_api.messages.OpenApiCommonMessages_pb2 import ProtoOAApplicationAuthReq
        except ImportError:
            return

        host = EndPoints.PROTOBUF_LIVE_HOST if CTRADER.get("host") == "live" else EndPoints.PROTOBUF_DEMO_HOST
        self.client = Client(host, CTRADER.get("port", 5035), TcpProtocol)

        def on_connected(client):
            req = ProtoOAApplicationAuthReq()
            req.clientId = CTRADER["client_id"]
            req.clientSecret = CTRADER["client_secret"]
            deferred = client.send(req)
            deferred.addCallbacks(self._on_app_auth, self._on_error)

        def on_disconnected(client, reason):
            self._connected = False
            self._app_auth = False
            self.account_auths.clear()

        def on_message(client, message):
            pass

        self.client.setConnectedCallback(on_connected)
        self.client.setDisconnectedCallback(on_disconnected)
        self.client.setMessageReceivedCallback(on_message)
        self.client.startService()

    def _on_app_auth(self, response):
        self._connected = True
        self._app_auth = True

    def _on_error(self, failure):
        pass

    async def _send_async(self, request):
        if not self._connected:
            raise Exception("cTrader not connected")
        import asyncio
        deferred = self.client.send(request)
        loop = asyncio.get_event_loop()
        return await deferred.asFuture(loop)

    async def fetch_state(self, account_id: str) -> dict:
        if not self._app_auth:
            return {"error": "Connecting to cTrader...", "equity": 0, "balance": 0, "margin": 0, "open_pnl": 0, "n_positions": 0}

        acc_id = int(account_id)
        if acc_id not in self.account_auths:
            from ctrader_open_api.messages.OpenApiMessages_pb2 import ProtoOAAccountAuthReq
            req = ProtoOAAccountAuthReq()
            req.ctidTraderAccountId = acc_id
            req.accessToken = CTRADER["access_token"]
            try:
                await self._send_async(req)
                self.account_auths.add(acc_id)
            except Exception as e:
                return {"error": f"Auth failed: {e}", "equity": 0, "balance": 0, "margin": 0, "open_pnl": 0, "n_positions": 0}

        try:
            from ctrader_open_api.messages.OpenApiMessages_pb2 import ProtoOATraderReq, ProtoOAReconcileReq
            req_trader = ProtoOATraderReq()
            req_trader.ctidTraderAccountId = acc_id
            res_trader = await self._send_async(req_trader)

            req_rec = ProtoOAReconcileReq()
            req_rec.ctidTraderAccountId = acc_id
            res_rec = await self._send_async(req_rec)

            trader = res_trader.payload.trader
            equity = trader.equity / 100.0
            balance = trader.balance / 100.0
            margin = getattr(trader, "usedMargin", 0) / 100.0

            n_positions = 0
            if res_rec.payload and hasattr(res_rec.payload, "position"):
                n_positions = len(res_rec.payload.position)

            open_pnl = equity - balance

            return {
                "equity": equity,
                "balance": balance,
                "margin": margin,
                "open_pnl": open_pnl,
                "n_positions": n_positions,
                "error": None
            }
        except Exception as e:
            return {"error": str(e), "equity": 0, "balance": 0, "margin": 0, "open_pnl": 0, "n_positions": 0}


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
    client_id = CTRADER.get("client_id", "")

    if not client_id:
        console.print("[red]CTRADER credentials not set in .env — using demo mode[/red]")
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
        CTRADER["client_id"] = ""

    asyncio.run(run_monitor(args.account, args.interval))

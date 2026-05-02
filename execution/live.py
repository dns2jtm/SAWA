"""
Live Execution Engine — XAUUSD FTMO
=====================================
Connects a trained, gate-approved PPO model to a broker execution feed for
live and demo trading.

Broker backend: cTrader Open API (replaces MetaApi/MT5)
  - Transition is in progress. The OrderManager is currently a mock stub
    that simulates all broker calls locally.
  - To activate live cTrader execution: implement _init_ctrader() and
    replace the mock methods with ctrader-open-api SDK calls.
    Install: pip install ctrader-open-api

Architecture:
  ┌──────────────────────────────────────────────────────┐
  │  LiveTrader                                         │
  │                                                     │
  │  BarFeeder ──► FeaturePipeline ──► PPO.predict()   │
  │       │                                 │           │
  │       │                         ActionExecutor      │
  │       │                                 │           │
  │  FTMOGuard ◄────────────────── OrderManager        │
  │       │                                 │           │
  │  EmergencyStop                    cTraderClient¹     │
  └──────────────────────────────────────────────────────┘
  ¹ Currently a mock stub. Live cTrader calls pending.

Safety layers (innermost → outermost):
  1. PositionSizer   — ATR-based lot sizing, hard lot cap
  2. FTMOGuard       — real-time DD monitor, kills trading if limits near
  3. CalendarFilter  — blocks entries near high-impact news
  4. SessionFilter   — only trades London/NY sessions
  5. EmergencyStop   — closes ALL positions if daily DD approaches limit

Usage:
  python execution/live.py --demo              # paper trading (mock mode)
  python execution/live.py --live              # LIVE — requires confirmed flag
  python execution/live.py --live --confirmed  # actual live trading
  python execution/live.py --status            # check current account state
  python execution/live.py --close-all         # emergency close all positions
"""

import argparse
import asyncio
import json
import logging
import os
import sys
import time
import urllib.request
import warnings
warnings.filterwarnings("ignore")
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from datetime  import datetime, timezone, timedelta
from pathlib   import Path
from typing    import Dict, List, Optional, Tuple

import numpy  as np
import pandas as pd

from config.settings    import CTRADER, EXECUTION, DATA
from config.prop_firms  import get_config, ACTIVE_FIRM
from config.instruments import get_instrument, ACTIVE_INSTRUMENT
from data.features      import FeaturePipeline
from data.news_calendar import CalendarFilter
from env.position_sizer import AdaptiveSizer

try:
    from stable_baselines3 import PPO
    _SB3_OK = True
except ImportError:
    _SB3_OK = False

MODELS_DIR = Path(__file__).parent.parent / "models"
EXEC_DIR   = Path(__file__).parent
LOG_DIR    = EXEC_DIR / "logs"
LOG_DIR.mkdir(parents=True, exist_ok=True)

DASHBOARD_PUSH_URL = os.getenv("DASHBOARD_URL", "http://localhost:8001") + "/api/organism/push"


def _push_to_dashboard(equity: float, drawdown: float,
                       volatility: float, action: str,
                       timestamp: str = None) -> None:
    """Fire-and-forget POST to /api/organism/push. Silently fails if backend is down."""
    body = json.dumps({
        "equity":      round(float(equity),              2),
        "drawdown":    round(float(max(drawdown, 0.0)),   4),
        "volatility":  round(float(np.clip(volatility, 0.1, 8.0)), 4),
        "last_action": action,
        "timestamp":   timestamp,
    }).encode()
    req = urllib.request.Request(
        DASHBOARD_PUSH_URL, data=body,
        headers={"Content-Type": "application/json"}, method="POST",
    )
    try:
        urllib.request.urlopen(req, timeout=1)
    except Exception:
        pass

INST = get_instrument(ACTIVE_INSTRUMENT)
CFG  = get_config(ACTIVE_FIRM)

# ── Logging ───────────────────────────────────────────────────────────────────
log_path = LOG_DIR / f"live_{datetime.now().strftime('%Y%m%d')}.log"
logging.basicConfig(
    level   = logging.INFO,
    format  = "%(asctime)s  %(levelname)-8s  %(message)s",
    datefmt = "%Y-%m-%d %H:%M:%S UTC",
    handlers=[
        logging.FileHandler(log_path),
        logging.StreamHandler(sys.stdout),
    ]
)
log = logging.getLogger("live_trader")


# ════════════════════════════════════════════════════════════════════════════════
# FTMO GUARD — Real-time drawdown monitor
# ════════════════════════════════════════════════════════════════════════════════

class FTMOGuard:
    """
    Monitors FTMO constraints in real time.
    Blocks new trades and triggers emergency stop when limits are near.

    Soft limits (warn + reduce size):
      Daily DD used ≥ 60% of limit  → reduce lot size 50%
      Total DD used ≥ 60% of limit  → reduce lot size 50%

    Hard limits (block all new entries):
      Daily DD used ≥ 85% of limit  → NO new trades today
      Total DD used ≥ 85% of limit  → NO new trades at all

    Emergency (close everything):
      Daily DD used ≥ 95% of limit  → close all + stop bot today
      Total DD used ≥ 95% of limit  → close all + stop bot permanently
    """

    SOFT_THRESHOLD      = 0.60
    HARD_THRESHOLD      = 0.85
    EMERGENCY_THRESHOLD = 0.95

    def __init__(self, account_size: float):
        self.account_size    = account_size
        self.initial_equity  = account_size
        self.daily_open_eq   = account_size
        self.peak_equity     = account_size
        self.last_reset_date = datetime.now(timezone.utc).date()

        self.daily_limit  = account_size * CFG["max_daily_loss_pct"]
        self.total_limit  = account_size * CFG["max_total_loss_pct"]

        # Personal conservative limits (tighter than FTMO rules)
        self.personal_daily  = account_size * CFG["personal_daily_limit"]
        self.personal_total  = account_size * CFG["personal_total_limit"]

        self._blocked_today  = False
        self._blocked_total  = False
        self._emergency      = False

    def update(self, current_equity: float) -> Dict:
        """Update guard state with current equity. Returns status dict."""
        now = datetime.now(timezone.utc)

        # Daily reset at UTC midnight
        if now.date() != self.last_reset_date:
            self.daily_open_eq   = current_equity
            self.last_reset_date = now.date()
            self._blocked_today  = False
            log.info(f"GUARD  Daily reset | equity={current_equity:,.2f}")

        # Update peak
        if current_equity > self.peak_equity:
            self.peak_equity = current_equity

        daily_loss  = self.daily_open_eq  - current_equity
        total_loss  = self.initial_equity - current_equity
        daily_ratio = daily_loss / (self.personal_daily  + 1e-9)
        total_ratio = total_loss / (self.personal_total  + 1e-9)

        # Determine state
        state = "OK"
        if daily_ratio >= self.EMERGENCY_THRESHOLD or total_ratio >= self.EMERGENCY_THRESHOLD:
            state           = "EMERGENCY"
            self._emergency = True
        elif daily_ratio >= self.HARD_THRESHOLD or total_ratio >= self.HARD_THRESHOLD:
            state = "BLOCKED"
            if daily_ratio >= self.HARD_THRESHOLD:
                self._blocked_today = True
            if total_ratio >= self.HARD_THRESHOLD:
                self._blocked_total = True
        elif daily_ratio >= self.SOFT_THRESHOLD or total_ratio >= self.SOFT_THRESHOLD:
            state = "CAUTION"

        return {
            "state":          state,
            "equity":         current_equity,
            "daily_open_eq":  self.daily_open_eq,
            "daily_loss":     daily_loss,
            "daily_ratio":    daily_ratio,
            "total_loss":     total_loss,
            "total_ratio":    total_ratio,
            "blocked_today":  self._blocked_today,
            "blocked_total":  self._blocked_total,
            "emergency":      self._emergency,
            "daily_remaining":max(0, self.personal_daily  - daily_loss),
            "total_remaining":max(0, self.personal_total  - total_loss),
        }

    def can_trade(self, current_equity: float) -> Tuple[bool, str]:
        """Returns (can_trade, reason)."""
        status = self.update(current_equity)
        if status["emergency"]:
            return False, f"EMERGENCY: equity near limit ({status['total_ratio']:.0%} of total DD used)"
        if status["blocked_total"]:
            return False, f"BLOCKED: total DD at {status['total_ratio']:.0%} of personal limit"
        if status["blocked_today"]:
            return False, f"BLOCKED today: daily DD at {status['daily_ratio']:.0%} of personal limit"
        return True, "OK"

    def lot_scale(self, current_equity: float) -> float:
        """Return lot scale factor based on current DD usage."""
        status = self.update(current_equity)
        daily_r = status["daily_ratio"]
        total_r = status["total_ratio"]
        worst   = max(daily_r, total_r)

        if worst >= self.SOFT_THRESHOLD:
            scale = max(0.25, 1.0 - worst)
            log.warning(f"GUARD  Lot scale reduced to {scale:.0%} "
                        f"(DD usage: {worst:.0%})")
            return scale
        return 1.0


# ════════════════════════════════════════════════════════════════════════════════
# BAR FEEDER — Fetches latest H1 bar from broker
# ════════════════════════════════════════════════════════════════════════════════

class BarFeeder:
    """
    Maintains a rolling window of the last N H1 bars.
    Maintains a rolling window of the last N H1 bars from the MT5 tick stream.
    Prepends historical Dukascopy data for indicator warmup.
    """

    WARMUP_BARS = 300   # Enough for EMA-200 + all indicators

    def __init__(self):
        self.pipe        = FeaturePipeline()
        self._df_warmup: Optional[pd.DataFrame] = None   # history cache (OHLCV+features)
        self._df_live:   Optional[pd.DataFrame] = None   # injected live bars (OHLCV)
        self._last_bar:  Optional[pd.Timestamp] = None

    def _load_warmup(self) -> pd.DataFrame:
        """Load last 300 H1 bars from stored feature cache for indicator warmup."""
        features_dir = DATA["features_dir"]
        candidates = sorted(features_dir.glob("XAUUSD_H1_features.parquet"), reverse=True)
        if not candidates:
            raise RuntimeError(
                "No feature cache found. Run: python data/features.py --auto"
            )
        df = pd.read_parquet(candidates[0])
        if df.index.tzinfo is None:
            df.index = df.index.tz_localize("UTC")
        log.info(f"Warmup loaded: {candidates[0].name} ({len(df):,} bars)")
        return df.iloc[-self.WARMUP_BARS:].copy()

    def inject_bar(self, bar: pd.DataFrame) -> None:
        """
        Called by LiveTrader when a new H1 bar closes.
        `bar` is a single-row DataFrame with columns [open, high, low, close, volume]
        and a UTC DatetimeIndex.
        """
        if bar is None or bar.empty:
            return
        if bar.index.tzinfo is None:
            bar.index = bar.index.tz_localize("UTC")
        if self._df_live is None:
            self._df_live = bar.copy()
        else:
            self._df_live = pd.concat([self._df_live, bar])
            self._df_live = (
                self._df_live[~self._df_live.index.duplicated(keep="last")]
                .sort_index()
            )

    def refresh(self) -> Optional[np.ndarray]:
        """
        Rebuild features over the warmup+live window and return the latest
        observation vector.  Returns None if no new bar has been injected.
        """
        if self._df_live is None or self._df_live.empty:
            log.debug("BarFeeder: no live bars injected yet")
            return None

        latest_ts = self._df_live.index.max()
        if self._last_bar is not None and latest_ts <= self._last_bar:
            return None   # No new closed bar since last call

        self._last_bar = latest_ts

        # Lazy warmup load — only on first real bar
        if self._df_warmup is None:
            self._df_warmup = self._load_warmup()

        # Merge warmup + live bars, keep last WARMUP_BARS
        combined = pd.concat([self._df_warmup, self._df_live])
        combined = combined[~combined.index.duplicated(keep="last")].sort_index()
        combined = combined.iloc[-self.WARMUP_BARS:]

        # Rebuild features and update warmup cache
        df_feat         = self.pipe.build(combined)
        self._df_warmup = df_feat

        X   = self.pipe.to_obs_array(df_feat)
        obs = X[-1].astype(np.float32)

        log.info(f"BarFeeder  New H1 bar: {latest_ts}  "
                 f"close={combined['close'].iloc[-1]:.2f}")
        return obs

    @property
    def latest_close(self) -> float:
        src = self._df_warmup if self._df_warmup is not None else self._df_live
        if src is not None and "close" in src.columns:
            return float(src["close"].iloc[-1])
        return 0.0

    @property
    def latest_atr(self) -> float:
        """Latest H1 ATR in USD (for position sizing)."""
        if self._df_warmup is not None and "atr_14" in self._df_warmup.columns:
            close     = self.latest_close
            atr_ratio = float(self._df_warmup["atr_14"].iloc[-1])
            return atr_ratio * close
        return INST["avg_atr_h1"]  # fallback to instrument average


# ════════════════════════════════════════════════════════════════════════════════
# ORDER MANAGER — MetaApi connector
# ════════════════════════════════════════════════════════════════════════════════

class OrderManager:
    """
    Sends orders to the broker.

    Broker: cTrader Open API (replaces MetaApi / MT5).
    """

    def __init__(self, dry_run: bool = True):
        self.dry_run = dry_run
        self._connected = False
        self.open_position: Optional[Dict] = None

        if not dry_run:
            from twisted.internet import reactor
            import threading
            
            # Auto-start twisted reactor in background thread
            if not getattr(OrderManager, "_reactor_started", False):
                OrderManager._reactor_started = True
                threading.Thread(target=lambda: reactor.run(installSignalHandlers=False), daemon=True).start()
            
            self._init_ctrader()

    def _init_ctrader(self):
        try:
            from ctrader_open_api import Client, EndPoints, TcpProtocol
            from ctrader_open_api.messages.OpenApiCommonMessages_pb2 import ProtoOAApplicationAuthReq
        except ImportError:
            log.error("ctrader-open-api not installed. Run: pip install ctrader-open-api")
            return

        host = EndPoints.PROTOBUF_LIVE_HOST if CTRADER["host"] == "live" else EndPoints.PROTOBUF_DEMO_HOST
        self.client = Client(host, CTRADER["port"], TcpProtocol)
        
        def on_connected(client):
            log.info("cTrader connected - authenticating app...")
            req = ProtoOAApplicationAuthReq()
            req.clientId = CTRADER["client_id"]
            req.clientSecret = CTRADER["client_secret"]
            deferred = client.send(req)
            deferred.addCallbacks(self._on_app_auth, self._on_error)
            
        def on_disconnected(client, reason):
            log.warning(f"cTrader disconnected: {reason}")
            self._connected = False
            
        def on_message(client, message):
            pass # Handle specific message updates

        self.client.setConnectedCallback(on_connected)
        self.client.setDisconnectedCallback(on_disconnected)
        self.client.setMessageReceivedCallback(on_message)
        self.client.startService()

    def _on_app_auth(self, response):
        from ctrader_open_api.messages.OpenApiMessages_pb2 import ProtoOAAccountAuthReq
        log.info("App authenticated - authenticating account...")
        req = ProtoOAAccountAuthReq()
        req.ctidTraderAccountId = int(CTRADER["account_id"])
        req.accessToken = CTRADER["access_token"]
        deferred = self.client.send(req)
        deferred.addCallbacks(self._on_account_auth, self._on_error)

    def _on_account_auth(self, response):
        from ctrader_open_api.messages.OpenApiMessages_pb2 import ProtoOASymbolsListReq
        log.info("Account authenticated - fetching symbols...")
        req = ProtoOASymbolsListReq()
        req.ctidTraderAccountId = int(CTRADER["account_id"])
        req.includeBaseSymbols = False
        deferred = self.client.send(req)
        deferred.addCallbacks(self._on_symbols_list, self._on_error)

    def _on_symbols_list(self, response):
        target_sym = INST.get("symbol", "XAUUSD")
        self.symbol_id = 1  # Fallback
        if hasattr(response.payload, "symbol"):
            for sym in response.payload.symbol:
                if sym.symbolName == target_sym:
                    self.symbol_id = sym.symbolId
                    break
        log.info(f"cTrader fully operational. Symbol ID for {target_sym}: {self.symbol_id}")
        self._connected = True

    def _on_error(self, failure):
        log.error(f"cTrader API Error: {failure}")

    async def _send_async(self, request):
        if self.dry_run or not self._connected:
            return None
        import asyncio
        deferred = self.client.send(request)
        loop = asyncio.get_event_loop()
        return await deferred.asFuture(loop)

    async def get_account_info(self) -> Dict:
        """Return account info using ProtoOATraderReq."""
        if self.dry_run or not self._connected:
            eq = CFG["account_size"]
            if self.open_position:
                eq += self.open_position.get("unrealized_pnl", 0.0)
            return {
                "equity": round(eq, 2), "balance": CFG["account_size"], "margin": 0.0, "free_margin": round(eq, 2)
            }
        
        try:
            from ctrader_open_api.messages.OpenApiMessages_pb2 import ProtoOATraderReq
            req = ProtoOATraderReq()
            req.ctidTraderAccountId = int(CTRADER["account_id"])
            res = await self._send_async(req)
            if res and res.payload:
                trader = res.payload.trader
                return {
                    "equity": trader.equity / 100.0,
                    "balance": trader.balance / 100.0,
                    "margin": getattr(trader, "usedMargin", 0) / 100.0, # some fields may be named differently
                    "free_margin": trader.equity / 100.0, 
                }
        except Exception as e:
            log.error(f"Failed to get account info: {e}")
        return {"equity": CFG["account_size"], "balance": CFG["account_size"]}

    async def get_positions(self) -> List[Dict]:
        """Return open positions using ProtoOAReconcileReq."""
        if self.dry_run:
            return [self.open_position] if self.open_position else []
        try:
            from ctrader_open_api.messages.OpenApiMessages_pb2 import ProtoOAReconcileReq
            req = ProtoOAReconcileReq()
            req.ctidTraderAccountId = int(CTRADER["account_id"])
            res = await self._send_async(req)
            if res and res.payload and hasattr(res.payload, 'position'):
                positions = []
                for p in res.payload.position:
                    dir_int = 1 if getattr(p.tradeData, 'tradeSide', 1) == 1 else -1
                    vol = getattr(p.tradeData, 'volume', 0) / 100.0
                    positions.append({
                        "ticket": str(p.positionId),
                        "direction": dir_int,
                        "lot": vol,
                        "entry": getattr(p, 'price', 0.0),
                        "sl": getattr(p, 'stopLoss', 0.0),
                        "tp": getattr(p, 'takeProfit', 0.0),
                        "unrealized_pnl": 0.0
                    })
                return positions
        except Exception as e:
            log.error(f"Failed to reconcile positions: {e}")
        return [self.open_position] if self.open_position else []

    async def open_trade(self, direction: int, lot: float,
                          sl_price: float, tp_price: float,
                          comment: str = "FTMO-RL") -> Optional[str]:
        """Place an order using ProtoOANewOrderReq."""
        symbol = INST["symbol"]
        side = "BUY" if direction > 0 else "SELL"
        if self.dry_run:
            ticket = f"MOCK_{int(time.time())}"
            self.open_position = {
                "ticket": ticket, "direction": direction, "lot": lot, "entry": 3300.0,
                "sl": sl_price, "tp": tp_price, "opened_at": datetime.now(timezone.utc).isoformat(), "unrealized_pnl": 0.0,
            }
            log.info(f"[MOCK cTrader] {side} {lot} {symbol} ticket={ticket}")
            return ticket

        if not self._connected:
            return None

        try:
            from ctrader_open_api.messages.OpenApiMessages_pb2 import ProtoOANewOrderReq, BUY, SELL, MARKET
            
            req = ProtoOANewOrderReq()
            req.ctidTraderAccountId = int(CTRADER["account_id"])
            req.symbolId = getattr(self, "symbol_id", 1)
            req.orderType = MARKET
            req.tradeSide = BUY if direction > 0 else SELL
            req.volume = int(lot * 100000) # Volume representation specifics
            req.stopLoss = float(sl_price)
            req.takeProfit = float(tp_price)
            req.comment = comment

            res = await self._send_async(req)
            ticket = f"CTR_{int(time.time())}"
            entry_price = 0.0
            
            if res and res.payload:
                if hasattr(res.payload, "order") and hasattr(res.payload.order, "orderId"):
                    ticket = str(res.payload.order.orderId)
                if hasattr(res.payload, "position") and hasattr(res.payload.position, "price"):
                    entry_price = res.payload.position.price / 100000.0

            self.open_position = {
                "ticket": ticket, "direction": direction, "lot": lot,
                "entry": entry_price,
                "sl": sl_price, "tp": tp_price, "opened_at": datetime.now(timezone.utc).isoformat(), "unrealized_pnl": 0.0,
            }
            log.info(f"[cTrader] {side} {lot} {symbol} ticket={ticket} entry={entry_price}")
            return ticket
        except Exception as e:
            log.error(f"Failed to open trade: {e}")
            return None

    async def close_position(self, ticket: str = None,
                              comment: str = "FTMO-RL-close") -> bool:
        """Close order using ProtoOAClosePositionReq."""
        ticket = ticket or (self.open_position or {}).get("ticket")
        if not ticket:
            return True
        if self.dry_run:
            log.info(f"[MOCK cTrader] CLOSE ticket={ticket}")
            self.open_position = None
            return True

        if not self._connected:
            return False

        try:
            from ctrader_open_api.messages.OpenApiMessages_pb2 import ProtoOAClosePositionReq
            req = ProtoOAClosePositionReq()
            req.ctidTraderAccountId = int(CTRADER["account_id"])
            req.positionId = int(ticket)
            req.volume = int(self.open_position["lot"] * 100000) if self.open_position else 0
            
            await self._send_async(req)
            log.info(f"[cTrader] CLOSE ticket={ticket}")
            self.open_position = None
            return True
        except Exception as e:
            log.error(f"Failed to close position: {e}")
            return False

    async def close_all(self, comment: str = "FTMO-RL-emergency") -> bool:
        log.warning("[cTrader] CLOSE ALL positions")
        if self.open_position:
            await self.close_position(self.open_position["ticket"], comment)
        return True

    async def modify_sl(self, ticket: str, new_sl: float) -> bool:
        """Modify SL using ProtoOAAmendPositionSLTPReq."""
        if self.open_position:
            self.open_position["sl"] = new_sl
        if self.dry_run:
            log.info(f"[MOCK cTrader] MODIFY SL ticket={ticket} new_sl={new_sl:.2f}")
            return True
        
        if not self._connected:
            return False

        try:
            from ctrader_open_api.messages.OpenApiMessages_pb2 import ProtoOAAmendPositionSLTPReq
            req = ProtoOAAmendPositionSLTPReq()
            req.ctidTraderAccountId = int(CTRADER["account_id"])
            req.positionId = int(ticket)
            req.stopLoss = float(new_sl)
            await self._send_async(req)
            log.info(f"[cTrader] MODIFY SL ticket={ticket} new_sl={new_sl:.2f}")
            return True
        except Exception as e:
            log.error(f"Failed to modify SL: {e}")
            return False

    async def get_latest_h1_bar(self) -> Optional[pd.DataFrame]:
        if self.dry_run or not self._connected or not getattr(self, "symbol_id", None):
            return None
            
        try:
            from ctrader_open_api.messages.OpenApiMessages_pb2 import ProtoOAGetTrendbarsReq, H1
            import time

            now_ms = int(time.time() * 1000)
            req = ProtoOAGetTrendbarsReq()
            req.ctidTraderAccountId = int(CTRADER["account_id"])
            req.period = H1
            req.fromTimestamp = now_ms - (86400 * 1000 * 3) # last 3 days
            req.toTimestamp = now_ms
            req.symbolId = self.symbol_id

            res = await self._send_async(req)
            if res and res.payload and hasattr(res.payload, 'trendbar'):
                bars = res.payload.trendbar
                if not bars:
                    return None

                records = []
                divisor = 100000.0  # standard price divisor
                for b in bars:
                    low = b.low / divisor
                    open_p = low + (getattr(b, "deltaOpen", 0) / divisor)
                    high_p = low + (getattr(b, "deltaHigh", 0) / divisor)
                    close_p = low + (getattr(b, "deltaClose", 0) / divisor)
                    vol = getattr(b, "volume", 0)

                    dt = pd.to_datetime(b.utcTimestampInMinutes, unit='m', utc=True)
                    records.append({
                        "datetime": dt, "open": open_p, "high": high_p,
                        "low": low, "close": close_p, "volume": vol
                    })
                
                if not records:
                    return None
                    
                df = pd.DataFrame(records).set_index("datetime").sort_index()
                return df.iloc[[-1]]
        except Exception as e:
            log.error(f"Failed to fetch latest H1 bar: {e}")
        return None


# ════════════════════════════════════════════════════════════════════════════════
# ACTION EXECUTOR — translates RL action → broker order
# ════════════════════════════════════════════════════════════════════════════════

class ActionExecutor:
    """
    Translates the PPO model's continuous action into broker orders.

    Action space (matches FTMOEnv):
      < -threshold = SELL/SHORT
      -threshold..+threshold = FLAT/CLOSE
      > +threshold = BUY/LONG
    Threshold is set by EXECUTION["action_threshold"] (default 0.33).

    Applies:
      - FTMOGuard check before every new entry
      - CalendarFilter check before every new entry
      - SessionFilter check before every new entry
      - ATR-based lot sizing via AdaptiveSizer
      - Trailing stop management after entry
    """

    # Session hours (UTC) when trading is allowed
    ALLOWED_HOURS = set(range(7, 21))   # 07:00 – 20:59 UTC

    def __init__(self, order_manager: OrderManager,
                 guard: FTMOGuard,
                 sizer: AdaptiveSizer,
                 calendar: CalendarFilter):
        self.om       = order_manager
        self.guard    = guard
        self.sizer    = sizer
        self.calendar = calendar
        self._current_position = 0   # -1, 0, +1

    async def execute(self, action: float, obs: np.ndarray,
                       equity: float, atr_h1: float,
                       close_price: float) -> Dict:
        """
        Execute the model's action. Returns execution log entry.
        """
        now      = datetime.now(timezone.utc)
        action_value = float(np.asarray(action).reshape(-1)[0])
        _thresh = float(EXECUTION.get("action_threshold", 0.33))
        if action_value > _thresh:
            target_position = 1
        elif action_value < -_thresh:
            target_position = -1
        else:
            target_position = 0
        result   = {"action": action_value, "executed": False, "reason": "", "timestamp": now.isoformat()}

        # ── FLAT / CLOSE ─────────────────────────────────────────────────────
        if target_position == 0 and self._current_position != 0:
            ticket = (self.om.open_position or {}).get("ticket")
            if ticket:
                await self.om.close_position(ticket)
            self._current_position = 0
            result["reason"]   = "CLOSE"
            result["executed"] = True
            return result

        if target_position == 0:
            result["reason"] = "HOLD"
            result["executed"] = True
            await self._manage_trailing_stop(close_price, atr_h1)
            return result

        # ── BUY / SELL — run all safety checks first ──────────────────────────
        direction = target_position

        # 1. Close opposite position first
        if self._current_position != 0 and self._current_position != direction:
            ticket = (self.om.open_position or {}).get("ticket")
            if ticket:
                await self.om.close_position(ticket)
            self._current_position = 0
            log.info("Closed opposite position before new entry")

        # Already in the same direction — hold
        if self._current_position == direction:
            result["reason"] = "ALREADY_IN_POSITION"
            return result

        # 2. FTMO guard check
        can_trade, reason = self.guard.can_trade(equity)
        if not can_trade:
            log.warning(f"GUARD BLOCK: {reason}")
            result["reason"] = f"GUARD:{reason}"
            return result

        # 3. Session filter
        if now.hour not in self.ALLOWED_HOURS:
            result["reason"] = f"SESSION_BLOCKED ({now.hour:02d}:00 UTC)"
            return result

        # 4. Calendar filter
        try:
            cal_status = self.calendar.get_status(INST["symbol"])
            if cal_status.block_new_trades:
                log.info(f"CALENDAR BLOCK: {cal_status.reason}")
                result["reason"] = f"CALENDAR:{cal_status.reason}"
                return result
        except Exception:
            pass   # Calendar failure → allow trade (fail open)

        # 5. Position sizing
        lot_scale = self.guard.lot_scale(equity)
        base_lot  = self.sizer.calculate(atr_h1, equity,
                                          daily_dd_used=self.guard.update(equity)["daily_loss"])
        lot       = round(base_lot * lot_scale, 2)
        lot       = max(INST["min_lot"], min(lot, INST["max_lot"]))

        # 6. Calculate SL / TP
        sl_price  = self.sizer.sl_price(close_price, direction, atr_h1)
        tp_price  = self.sizer.tp_price(close_price, direction, atr_h1)

        # Sanity check — SL must be valid
        if direction > 0 and sl_price >= close_price:
            result["reason"] = "INVALID_SL_LONG"
            return result
        if direction < 0 and sl_price <= close_price:
            result["reason"] = "INVALID_SL_SHORT"
            return result

        # 7. Send order
        ticket = await self.om.open_trade(
            direction = direction,
            lot       = lot,
            sl_price  = sl_price,
            tp_price  = tp_price,
            comment   = f"FTMO-RL-{'L' if direction>0 else 'S'}",
        )

        if ticket:
            self._current_position = direction
            risk_usd = abs(close_price - sl_price) / INST["pip_size"] * INST["pip_value_per_lot"] * lot
            log.info(
                f"ENTRY  {'LONG' if direction>0 else 'SHORT'}  "
                f"lot={lot}  entry={close_price:.2f}  "
                f"sl={sl_price:.2f}  tp={tp_price:.2f}  "
                f"risk=${risk_usd:.0f}  ticket={ticket}"
            )
            result["executed"] = True
            result["reason"]   = "ENTERED"
            result["ticket"]   = ticket
            result["lot"]      = lot
            result["sl"]       = sl_price
            result["tp"]       = tp_price
        else:
            result["reason"] = "ORDER_FAILED"

        return result

    async def _manage_trailing_stop(self, close_price: float, atr_h1: float):
        """Move SL to breakeven when trade is 1× ATR in profit."""
        pos = self.om.open_position
        if not pos:
            return

        direction = pos["direction"]
        entry     = pos["entry"]
        current_sl= pos["sl"]
        atr_move  = atr_h1 * INST["atr_stop_multiplier"]

        # Breakeven trigger: price moved 1× ATR in our favour
        if direction > 0:
            if close_price >= entry + atr_move:
                new_sl = max(entry + INST["pip_size"] * 5, current_sl)
                if new_sl > current_sl:
                    await self.om.modify_sl(pos["ticket"], new_sl)
        else:
            if close_price <= entry - atr_move:
                new_sl = min(entry - INST["pip_size"] * 5, current_sl)
                if new_sl < current_sl:
                    await self.om.modify_sl(pos["ticket"], new_sl)


# ════════════════════════════════════════════════════════════════════════════════
# LIVE TRADER — Main loop
# ════════════════════════════════════════════════════════════════════════════════

class LiveTrader:
    """
    Main trading loop. Wakes up every minute, checks for new H1 bar,
    runs model inference, and executes actions.
    """

    CHECK_INTERVAL = 60   # seconds between bar-close checks

    def __init__(self, model_path: Path, dry_run: bool = True):
        self.dry_run    = dry_run
        self.model_path = model_path
        self._running   = False
        self._trade_log: List[Dict] = []

        # Dry-run replay state — walks through the test split one bar per tick
        self._replay_df:  Optional[pd.DataFrame] = None
        self._replay_idx: int = 0

        # Account state tracking (mirrors FTMOEnv._get_obs dynamic features)
        self._initial_balance: float = float(CFG["account_size"])
        self._days_traded:     int   = 0
        self._trades_today:    int   = 0
        self._last_day:        Optional[str] = None
        self._traded_today:    bool  = False

        log.info(f"LiveTrader init | model={model_path.name} | dry_run={dry_run}")

        # Load model
        if not _SB3_OK:
            raise RuntimeError("stable-baselines3 not installed")
        self.model = PPO.load(model_path, device="cpu")
        log.info("Model loaded")

        # Load regime specialists (saved by train.py) for ensemble prediction
        self.specialists = []
        for i in range(3):
            sp_path = MODELS_DIR / "best" / f"specialist_{i}.zip"
            if sp_path.exists():
                self.specialists.append(PPO.load(sp_path, device="cpu"))
                log.info(f"  Loaded specialist {i} ({sp_path.name})")
            else:
                log.warning(f"Specialist {i} not found at {sp_path}; falling back to single model")
                self.specialists = None
                break
        if self.specialists and len(self.specialists) == 3:
            log.info(f"✅ Loaded {len(self.specialists)} regime specialists for live routing")

        # Initialise components
        self.bar_feeder = BarFeeder()
        self.guard      = FTMOGuard(account_size=CFG["account_size"])
        self.sizer      = AdaptiveSizer()
        self.calendar   = CalendarFilter()
        self.om         = OrderManager(dry_run=dry_run)
        self.executor   = ActionExecutor(self.om, self.guard, self.sizer, self.calendar)

        log.info(f"Components ready | firm={CFG['name']} | "
                 f"instrument={INST['symbol']} | "
                 f"account=£{CFG['account_size']:,}")

        if dry_run:
            self._init_dry_run_replay()

        # Sentiment pipeline — refreshes RSS headlines every 15 min
        try:
            from data.sentiment import get_sentiment_pipeline
            self._sentiment = get_sentiment_pipeline()
        except Exception:
            self._sentiment = None

    def _init_dry_run_replay(self) -> None:
        """Load the test split for dry-run bar-by-bar replay."""
        try:
            pipe = FeaturePipeline()
            df   = pipe.load("XAUUSD_H1_features")
            # Use the last 20% as replay data (post-training window)
            n         = len(df)
            start_idx = int(n * 0.80)
            self._replay_df  = df.iloc[start_idx:].copy()
            self._replay_idx = 0
            log.info(f"Dry-run replay: {len(self._replay_df):,} bars from "
                     f"{self._replay_df.index[0].date()} "
                     f"→ {self._replay_df.index[-1].date()}")
        except Exception as exc:
            log.warning(f"Dry-run replay data not available: {exc}")
            self._replay_df = None

    def _get_next_bar(self) -> Optional[pd.DataFrame]:
        """
        Return the next single-row OHLCV bar from the dry-run replay sequence.
        Returns None when the replay is exhausted or unavailable.
        """
        if self._replay_df is None or self._replay_idx >= len(self._replay_df):
            if self._replay_df is not None:
                log.info("Dry-run replay complete")
                self._running = False
            return None
        ohlcv_cols = [c for c in ["open", "high", "low", "close", "volume"]
                      if c in self._replay_df.columns]
        row = self._replay_df.iloc[[self._replay_idx]][ohlcv_cols].copy()
        
        # Add synthetic price movement for demonstration so equity changes on dashboard
        # Gentle upward drift with small random walk
        base_close = float(row["close"].iloc[0])
        drift = 0.08 * (self._replay_idx % 100 - 50) / 100.0
        noise = np.random.normal(0, 1.5)
        synthetic_close = base_close + drift + noise
        row["close"] = synthetic_close
        row["open"] = synthetic_close - 1.2
        row["high"] = synthetic_close + 2.5
        row["low"] = synthetic_close - 2.5
        
        self._replay_idx += 1
        return row

    def _build_live_obs(self, static_obs: np.ndarray, equity: float,
                         balance: float, guard_status: dict,
                         cal_blocked: bool = False) -> np.ndarray:
        """
        Construct the full 77-dim obs vector the model was trained on:
          obs = [12 account state features] + [65 static market features]

        The 65-dim `static_obs` comes from BarFeeder (FeaturePipeline output).
        The 12 account-state features mirror FTMOEnv._get_obs() exactly.
        """
        initial_balance = self._initial_balance
        profit_target   = initial_balance * CFG["profit_target_pct"]
        max_daily_loss  = initial_balance * CFG["personal_daily_limit"]
        max_total_loss  = initial_balance * CFG["personal_total_limit"]
        min_days        = int(CFG.get("min_trading_days", 10))
        max_trades_day  = int(CFG.get("max_trades_per_day", 3))

        daily_pnl = equity - guard_status.get("daily_open_eq", equity)
        total_pnl = equity - initial_balance
        open_pnl  = equity - balance   # floating P&L = equity - balance
        position  = self.executor._current_position

        dyn = np.array([
            equity     / initial_balance - 1.0,
            daily_pnl  / initial_balance,
            total_pnl  / initial_balance,
            total_pnl  / (profit_target + 1e-9),
            -min(daily_pnl, 0.0) / (max_daily_loss + 1e-9),
            -min(total_pnl, 0.0) / (max_total_loss + 1e-9),
            self._days_traded  / max(min_days,       1),
            self._trades_today / max(max_trades_day, 1),
            float(position > 0),
            float(position < 0),
            float(abs(position)),
            open_pnl / (initial_balance + 1e-9),
        ], dtype=np.float32)

        # Patch live sentiment into static obs indices 55-59
        # (sentiment_score, novelty, momentum, volume, event_flag)
        static = static_obs.copy()
        if self._sentiment is not None:
            try:
                sent_feats = self._sentiment.get_features(calendar_blocked=cal_blocked)
                static[55:60] = sent_feats
            except Exception:
                pass

        obs = np.concatenate([dyn, static]).astype(np.float32)
        return np.nan_to_num(obs, nan=0.0, posinf=1.0, neginf=-1.0)

    async def _get_equity(self) -> float:
        """Fetch current account equity from broker."""
        info = await self.om.get_account_info()
        return info.get("equity", CFG["account_size"])

    async def _tick(self):
        """Single bar-close processing cycle."""
        # 1. Get live account state from broker
        account_info = await self.om.get_account_info()
        equity  = account_info.get("equity",  self._initial_balance)
        balance = account_info.get("balance", self._initial_balance)

        # 2. Check FTMO guard state
        guard_status = self.guard.update(equity)
        if guard_status["emergency"]:
            log.critical(f"EMERGENCY STOP | equity={equity:.2f} | "
                         f"total_dd={guard_status['total_ratio']:.0%} of limit")
            await self.om.close_all("EMERGENCY")
            self._running = False
            return

        # 3. Feed the latest H1 bar into BarFeeder
        #    Live mode: poll MetaApi for the most recently closed H1 candle
        #    Dry-run:   replay next bar from the test split
        if self.dry_run:
            bar = self._get_next_bar()
        else:
            bar = await self.om.get_latest_h1_bar()

        if bar is not None:
            self.bar_feeder.inject_bar(bar)

        static_obs = self.bar_feeder.refresh()   # 65-dim static features
        if static_obs is None:
            return   # No new bar yet

        # 4. Calendar check (needed for both blocking AND obs feature)
        cal_blocked = False
        try:
            cal_status  = self.calendar.get_status(INST["symbol"])
            cal_blocked = cal_status.block_new_trades
        except Exception:
            pass

        # 5. Build full 77-dim obs = [12 account state] + [65 static]
        obs = self._build_live_obs(static_obs, equity, balance,
                                    guard_status, cal_blocked)

        # ── Regime Routing (mirrors FTMOEnv for consistency with specialists) ─────
        # Regime probs are at indices 61:64 in the 77-dim obs (after 12 dyn feats)
        regime_start = 61
        regime_probs = obs[regime_start:regime_start+3]
        current_regime = int(np.argmax(regime_probs))
        log.debug(f"Current regime: {current_regime} (probs={regime_probs.round(3)})")

        # Override with specialist if loaded (ensemble improves regime-specific performance)
        if getattr(self, 'specialists', None) and len(self.specialists) == 3:
            specialist = self.specialists[current_regime]
            action, _ = specialist.predict(obs, deterministic=True)
            log.debug(f"  → Using specialist {current_regime} for prediction")
        else:
            action, _ = self.model.predict(obs, deterministic=True)

        # 6. Model inference complete

        # 7. Execute
        result = await self.executor.execute(
            action      = action,
            obs         = obs,
            equity      = equity,
            atr_h1      = self.bar_feeder.latest_atr,
            close_price = self.bar_feeder.latest_close,
        )

        # 8. Track days_traded / trades_today
        today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        if today != self._last_day:
            if self._traded_today:
                self._days_traded += 1
            self._trades_today = 0
            self._traded_today = False
            self._last_day     = today
        if result.get("executed") and result.get("reason") == "ENTERED":
            self._trades_today += 1
            self._traded_today  = True

        # 9. Log
        log_entry = {
            **result,
            "equity":    round(equity, 2),
            "atr_h1":    round(self.bar_feeder.latest_atr, 2),
            "close":     round(self.bar_feeder.latest_close, 2),
            "daily_dd":  round(guard_status["daily_ratio"], 4),
            "total_dd":  round(guard_status["total_ratio"], 4),
        }
        self._trade_log.append(log_entry)

        # Save rolling log
        log_file = LOG_DIR / f"trades_{datetime.now().strftime('%Y%m%d')}.jsonl"
        with open(log_file, "a") as f:
            f.write(json.dumps(log_entry) + "\n")

        # 7. Status line
        pos_str = {1: "LONG▲", -1: "SHORT▼", 0: "FLAT ─"}
        action_scalar = float(np.asarray(action).reshape(-1)[0])
        log.info(
            f"TICK  close={self.bar_feeder.latest_close:.2f}  "
            f"action={action_scalar:+.3f}({result['reason']})  "
            f"pos={pos_str.get(self.executor._current_position, '?')}  "
            f"equity={equity:,.0f}  "
            f"daily_dd={guard_status['daily_ratio']:.1%}  "
            f"total_dd={guard_status['total_ratio']:.1%}"
        )

        # 10. Push live state to organism dashboard (non-blocking, best-effort)
        _dd_pct   = max((self.guard.peak_equity - equity) / max(self.guard.peak_equity, 1.0) * 100.0, 0.0)
        _avg_atr  = INST.get("avg_atr_h1", 10.0)
        _vol      = float(np.clip(self.bar_feeder.latest_atr / max(_avg_atr, 1e-9), 0.5, 3.0))
        _pos      = self.executor._current_position
        _action   = "LONG" if _pos > 0 else ("SHORT" if _pos < 0 else "FLAT")
        _ts_str   = str(self.bar_feeder._last_bar) if hasattr(self.bar_feeder, '_last_bar') and self.bar_feeder._last_bar else datetime.now(timezone.utc).isoformat()
        _push_to_dashboard(equity, _dd_pct, _vol, _action, _ts_str)

    async def run(self):
        """Main async loop."""
        mode = "DRY-RUN (paper)" if self.dry_run else "LIVE"
        log.info(f"{'='*55}")
        log.info(f"  STARTING {mode} TRADING")
        log.info(f"  Instrument : {INST['symbol']}")
        log.info(f"  Firm       : {CFG['name']}")
        log.info(f"  Account    : £{CFG['account_size']:,}")
        log.info(f"  Target     : {CFG['profit_target_pct']:.0%}  "
                 f"= £{CFG['account_size'] * CFG['profit_target_pct']:,.0f}")
        log.info(f"  Daily limit: {CFG['personal_daily_limit']:.1%}")
        log.info(f"{'='*55}")

        self._running = True

        while self._running:
            try:
                await self._tick()
            except KeyboardInterrupt:
                log.info("Keyboard interrupt — shutting down cleanly")
                self._running = False
            except Exception as e:
                log.error(f"Tick error: {e}", exc_info=True)
                await asyncio.sleep(10)   # Brief pause before retry

            if self._running:
                # Dry-run replays as fast as possible; live waits for next bar
                # Set to 0.5s in dry-run to prevent websocket from overloading the dashboard UI
                await asyncio.sleep(0.5 if self.dry_run else self.CHECK_INTERVAL)

        log.info("LiveTrader stopped")

    async def status(self):
        """Print current account status without trading."""
        equity  = await self._get_equity()
        guard_s = self.guard.update(equity)
        positions = await self.om.get_positions()

        print(f"\n{'='*50}")
        print(f"  Account Status — {INST['symbol']}  {CFG['name']}")
        print(f"{'='*50}")
        print(f"  Equity         : £{equity:>10,.2f}")
        print(f"  Daily DD used  :  {guard_s['daily_ratio']:>9.1%}")
        print(f"  Total DD used  :  {guard_s['total_ratio']:>9.1%}")
        print(f"  Daily remaining: £{guard_s['daily_remaining']:>9,.0f}")
        print(f"  Total remaining: £{guard_s['total_remaining']:>9,.0f}")
        print(f"  Guard state    :  {guard_s['state']}")
        print(f"  Open positions :  {len(positions)}")
        for p in positions:
            print(f"    {p}")
        print(f"{'='*50}")


# ════════════════════════════════════════════════════════════════════════════════
# CLI
# ════════════════════════════════════════════════════════════════════════════════

def find_best_model() -> Path:
    best = MODELS_DIR / "best" / "best_model.zip"
    if best.exists():
        return best
    finals = sorted(MODELS_DIR.glob("ppo_xauusd_final_*.zip"))
    if finals:
        return finals[-1]
    raise FileNotFoundError(
        "No trained model found.\n"
        "Run: python models/train.py\n"
        "Then: python models/backtest.py  (must pass gate before live)"
    )


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="XAUUSD FTMO Live Trader")
    parser.add_argument("--demo",      action="store_true",
                        help="Run on demo/paper account (safe)")
    parser.add_argument("--live",      action="store_true",
                        help="Run on live account (requires --confirmed)")
    parser.add_argument("--confirmed", action="store_true",
                        help="Confirm live trading (safety flag)")
    parser.add_argument("--model",     default=None,
                        help="Path to model .zip (auto-finds best if omitted)")
    parser.add_argument("--status",    action="store_true",
                        help="Print account status and exit")
    parser.add_argument("--close-all", action="store_true",
                        help="Emergency close all positions and exit")
    args = parser.parse_args()

    # Safety: live requires explicit --confirmed flag
    if args.live and not args.confirmed:
        print("\n⚠  LIVE trading requires --confirmed flag.")
        print("   Run the backtest gate first:")
        print("   python models/backtest.py --model models/best/best_model.zip")
        print("\n   If gate passed, re-run with:")
        print("   python execution/live.py --live --confirmed")
        sys.exit(1)

    dry_run = not (args.live and args.confirmed)

    model_path = Path(args.model) if args.model else find_best_model()
    trader     = LiveTrader(model_path=model_path, dry_run=dry_run)

    async def main():
        if args.status:
            await trader.status()
        elif args.close_all:
            log.warning("Manual close-all triggered")
            await trader.om.close_all("MANUAL")
        else:
            await trader.run()

    asyncio.run(main())

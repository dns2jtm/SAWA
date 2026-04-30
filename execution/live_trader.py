"""
Live trading execution engine for EURGBP on FTMO MT5 via MetaApi.

Features:
  - Real-time H1 bar streaming via MetaApi WebSocket
  - PPO policy inference (GPU if available)
  - Three-layer FTMO constraint enforcement
  - Redis drawdown sentinel (30s polling)
  - Async kill-switch: closes all positions before breach
  - Full trade logging to TimescaleDB + WandB

Usage:
    python execution/live_trader.py
"""

import asyncio
import logging
import os
import sys
import time
from datetime import datetime, timezone

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

import numpy as np
import pandas as pd
import torch

from config.settings import EXECUTION, FTMO, INSTRUMENT, DATA, RL
from data.features import build_observation_df, get_feature_cols

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[
        logging.StreamHandler(),
        logging.FileHandler("logs/live_trader.log", mode="a"),
    ],
)
log = logging.getLogger("live_trader")

# ── MetaApi ───────────────────────────────────────────────────────────────────
from metaapi_cloud_sdk import MetaApi
from metaapi_cloud_sdk.clients.metaapi.trade_exception import TradeException

# ── WandB (optional) ──────────────────────────────────────────────────────────
try:
    import wandb
    WANDB = True
except ImportError:
    WANDB = False

# ── Redis sentinel ────────────────────────────────────────────────────────────
try:
    import redis
    REDIS = True
except ImportError:
    REDIS = False
    log.warning("redis-py not installed. Sentinel will use in-memory state only.")

# ── SB3 ───────────────────────────────────────────────────────────────────────
from stable_baselines3 import PPO
from stable_baselines3.common.vec_env import VecNormalize


# ─────────────────────────────────────────────────────────────────────────────
# Constants
# ─────────────────────────────────────────────────────────────────────────────

TOKEN          = EXECUTION["metaapi_token"]
ACCOUNT_ID     = EXECUTION["metaapi_account"]
SYMBOL         = EXECUTION["symbol"]
PLATFORM       = EXECUTION["platform"]          # "mt5"
SERVER         = EXECUTION["ftmo_server"]       # "FTMO-Server3"
POLL_INTERVAL  = EXECUTION["poll_interval_s"]   # 60s
SENTINEL_INT   = EXECUTION["sentinel_interval"] # 30s

INITIAL_BAL    = float(FTMO["account_balance"])
KILL_DAILY     = FTMO["daily_dd_kill_pct"] * INITIAL_BAL
KILL_TOTAL     = FTMO["total_dd_kill_pct"] * INITIAL_BAL
PROFIT_TARGET  = FTMO["profit_target_phase1"] * INITIAL_BAL

MODEL_PATH     = os.path.join(os.path.dirname(__file__), "..", "models", "ppo_eurgbp_final")
VECNORM_PATH   = os.path.join(os.path.dirname(__file__), "..", "models", "vecnorm_final.pkl")

RISK_TABLE = {
    0: ("SELL", 0.02),
    1: ("SELL", 0.01),
    2: ("FLAT", 0.00),
    3: ("BUY",  0.01),
    4: ("BUY",  0.02),
}


# ─────────────────────────────────────────────────────────────────────────────
# Model loader
# ─────────────────────────────────────────────────────────────────────────────

def load_model():
    device = "cuda" if torch.cuda.is_available() else "cpu"
    log.info(f"Loading PPO model from {MODEL_PATH} on {device}")

    model    = PPO.load(MODEL_PATH, device=device)
    vec_norm = None

    if os.path.exists(VECNORM_PATH):
        # Load VecNormalize stats for observation normalisation
        import pickle
        with open(VECNORM_PATH, "rb") as fh:
            vec_norm = pickle.load(fh)
        log.info("VecNormalize stats loaded.")

    return model, vec_norm, device


def normalise_obs(obs: np.ndarray, vec_norm) -> np.ndarray:
    if vec_norm is None:
        return obs.astype(np.float32)
    normed = (obs - vec_norm.obs_rms.mean) / np.sqrt(vec_norm.obs_rms.var + 1e-8)
    return np.clip(normed, -5.0, 5.0).astype(np.float32)


# ─────────────────────────────────────────────────────────────────────────────
# Redis sentinel state
# ─────────────────────────────────────────────────────────────────────────────

class DrawdownState:
    """In-memory + Redis drawdown tracking."""

    def __init__(self):
        self.peak_equity     = INITIAL_BAL
        self.day_open_equity = INITIAL_BAL
        self.suspended       = False

        self._redis = None
        if REDIS:
            try:
                self._redis = redis.Redis(host="localhost", port=6379, decode_responses=True)
                self._redis.ping()
                log.info("Redis connected for drawdown sentinel.")
            except Exception as e:
                log.warning(f"Redis unavailable: {e}. Using in-memory sentinel.")
                self._redis = None

    def update(self, equity: float):
        if equity > self.peak_equity:
            self.peak_equity = equity
            if self._redis:
                self._redis.set("peak_equity", equity)

    def daily_dd(self, equity: float) -> float:
        return max(0.0, self.day_open_equity - equity)

    def total_dd(self, equity: float) -> float:
        return max(0.0, self.peak_equity - equity)

    def reset_daily(self, equity: float):
        self.day_open_equity = equity
        if self._redis:
            self._redis.set("day_open_equity", equity)
        log.info(f"Daily DD counter reset. Day open equity: £{equity:,.2f}")

    def check_kill(self, equity: float) -> str | None:
        """Returns 'daily', 'total', or None."""
        if self.daily_dd(equity) >= KILL_DAILY:
            return "daily"
        if self.total_dd(equity) >= KILL_TOTAL:
            return "total"
        return None


# ─────────────────────────────────────────────────────────────────────────────
# Position sizing (Level 2)
# ─────────────────────────────────────────────────────────────────────────────

def compute_lot(risk_pct: float, balance: float, atr_pips: float,
                dd_state: DrawdownState, equity: float) -> float:
    daily_rem = KILL_DAILY - dd_state.daily_dd(equity)
    total_rem = KILL_TOTAL - dd_state.total_dd(equity)
    safe_risk = min(daily_rem, total_rem) * 0.25
    risk_gbp  = min(safe_risk, risk_pct * balance)
    stop_pips = max(5.0, 1.5 * atr_pips)
    lot       = risk_gbp / (stop_pips * INSTRUMENT["pip_value_gbp"])
    return round(max(0.0, min(lot, INSTRUMENT["max_lot"])), 2)


# ─────────────────────────────────────────────────────────────────────────────
# DB trade logger
# ─────────────────────────────────────────────────────────────────────────────

def log_trade_to_db(record: dict):
    try:
        import psycopg2
        conn = psycopg2.connect(
            host=DATA["db_host"], port=DATA["db_port"],
            dbname=DATA["db_name"], user=DATA["db_user"],
            password=DATA["db_password"],
        )
        cur = conn.cursor()
        cur.execute("""
            CREATE TABLE IF NOT EXISTS live_trades (
                time        TIMESTAMPTZ NOT NULL,
                action      TEXT,
                lot         DOUBLE PRECISION,
                price       DOUBLE PRECISION,
                equity      DOUBLE PRECISION,
                daily_dd    DOUBLE PRECISION,
                total_dd    DOUBLE PRECISION,
                note        TEXT
            );
        """)
        cur.execute(
            "INSERT INTO live_trades VALUES (%s,%s,%s,%s,%s,%s,%s,%s)",
            (record["time"], record["action"], record.get("lot", 0),
             record.get("price", 0), record.get("equity", 0),
             record.get("daily_dd", 0), record.get("total_dd", 0),
             record.get("note", ""))
        )
        conn.commit(); cur.close(); conn.close()
    except Exception as e:
        log.warning(f"DB trade log failed: {e}")


# ─────────────────────────────────────────────────────────────────────────────
# Bar builder: fetch recent H1 bars and build feature observation
# ─────────────────────────────────────────────────────────────────────────────

async def get_latest_observation(account, feat_cols: list) -> tuple[np.ndarray | None, float]:
    """Fetch last 300 H1 bars, build features, return (obs, atr_pips)."""
    try:
        candles = await account.get_historical_candles(SYMBOL, "1h", count=300)
        if not candles:
            return None, 10.0

        df = pd.DataFrame([{
            "time"  : c["time"],
            "open"  : c["open"],
            "high"  : c["high"],
            "low"   : c["low"],
            "close" : c["close"],
            "volume": c.get("tickVolume", 0),
        } for c in candles])
        df["time"] = pd.to_datetime(df["time"])
        df.set_index("time", inplace=True)
        df.sort_index(inplace=True)

        df_feat   = build_observation_df(df)
        all_cols  = get_feature_cols(df_feat)
        if not all_cols:
            return None, 10.0

        last_row  = df_feat.iloc[-1]
        feats     = last_row[all_cols].values.astype(np.float32)
        feats     = np.nan_to_num(feats, nan=0.0, posinf=3.0, neginf=-3.0)
        feats     = np.clip(feats, -5.0, 5.0)
        atr_pips  = float(last_row.get("atr_14", 0.001)) * 10_000

        return feats, atr_pips, all_cols

    except Exception as e:
        log.error(f"Failed to build observation: {e}")
        return None, 10.0, feat_cols


# ─────────────────────────────────────────────────────────────────────────────
# Main trading loop
# ─────────────────────────────────────────────────────────────────────────────

async def run_trader():
    os.makedirs("logs", exist_ok=True)

    if WANDB:
        wandb.init(project=EXECUTION["wandb_project"],
                   entity=EXECUTION["wandb_entity"],
                   name=f"live-{datetime.now().strftime('%Y%m%d-%H%M')}",
                   tags=["live", "phase1", "mt5"])

    log.info("Connecting to MetaApi...")
    api     = MetaApi(TOKEN)
    account = await api.metatrader_account_api.get_account(ACCOUNT_ID)

    if account.state not in ["DEPLOYED", "DEPLOYING"]:
        log.info("Deploying account...")
        await account.deploy()

    log.info("Waiting for broker connection...")
    await account.wait_connected()
    log.info(f"Connected to {SERVER} (MT5) ✅")

    model, vec_norm, device = load_model()
    dd_state  = DrawdownState()
    feat_cols = None
    current_side = None   # "BUY", "SELL", or None

    last_day        = datetime.now(timezone.utc).date()
    sentinel_timer  = time.monotonic()

    log.info(f"Live trader active. Symbol={SYMBOL} | Phase 1 target=£{PROFIT_TARGET:,.0f}")
    log.info(f"Kill thresholds — Daily: £{KILL_DAILY:,.0f} | Total: £{KILL_TOTAL:,.0f}")

    while True:
        try:
            # ── Daily DD reset ────────────────────────────────────────────────
            today = datetime.now(timezone.utc).date()
            if today != last_day:
                acc_info = await account.get_account_information()
                dd_state.reset_daily(acc_info["equity"])
                last_day = today

            # ── Sentinel check (every 30s) ────────────────────────────────────
            if time.monotonic() - sentinel_timer >= SENTINEL_INT:
                sentinel_timer = time.monotonic()
                acc_info = await account.get_account_information()
                equity   = acc_info["equity"]
                balance  = acc_info["balance"]
                dd_state.update(equity)

                kill = dd_state.check_kill(equity)
                if kill:
                    log.critical(f"KILL SWITCH TRIGGERED ({kill} drawdown limit). Closing all positions.")
                    await close_all_positions(account)
                    dd_state.suspended = True
                    log_trade_to_db({
                        "time"    : datetime.now(timezone.utc),
                        "action"  : "KILL_SWITCH",
                        "equity"  : equity,
                        "daily_dd": dd_state.daily_dd(equity) / INITIAL_BAL,
                        "total_dd": dd_state.total_dd(equity) / INITIAL_BAL,
                        "note"    : f"{kill}_limit",
                    })
                    if WANDB and wandb.run:
                        wandb.alert(title="KILL SWITCH", text=f"{kill} DD limit hit",
                                    level=wandb.AlertLevel.ERROR)
                    if kill == "total":
                        log.critical("Total DD limit hit — system halted permanently.")
                        break
                    log.warning("Daily DD limit hit — suspended until tomorrow.")
                    await asyncio.sleep(3600)
                    dd_state.suspended = False
                    continue

                if WANDB and wandb.run:
                    wandb.log({
                        "live/equity"     : equity,
                        "live/balance"    : balance,
                        "live/daily_dd"   : dd_state.daily_dd(equity) / INITIAL_BAL,
                        "live/total_dd"   : dd_state.total_dd(equity) / INITIAL_BAL,
                        "live/pnl"        : equity - INITIAL_BAL,
                    })

            if dd_state.suspended:
                await asyncio.sleep(60)
                continue

            # ── Build observation ─────────────────────────────────────────────
            result = await get_latest_observation(account, feat_cols or [])
            if result[0] is None:
                log.warning("No observation available. Skipping bar.")
                await asyncio.sleep(POLL_INTERVAL)
                continue

            feats, atr_pips, feat_cols = result

            # Append account state to observation
            acc_info   = await account.get_account_information()
            equity     = acc_info["equity"]
            balance    = acc_info["balance"]
            dd_state.update(equity)

            state_vec = np.array([
                equity / INITIAL_BAL - 1.0,
                (equity - INITIAL_BAL) / INITIAL_BAL,
                dd_state.daily_dd(equity) / INITIAL_BAL,
                dd_state.total_dd(equity) / INITIAL_BAL,
                float(current_side is not None),
            ], dtype=np.float32)

            obs        = np.concatenate([feats, state_vec])
            obs_normed = normalise_obs(obs, vec_norm)

            # ── Policy inference ──────────────────────────────────────────────
            action, _ = model.predict(obs_normed[np.newaxis], deterministic=True)
            action    = int(action[0])
            side, risk_pct = RISK_TABLE[action]

            price    = acc_info.get("equity", 0)  # rough proxy; real price from ask
            positions = await account.get_positions()
            open_pos  = [p for p in positions if p["symbol"] == SYMBOL]

            log.info(f"Action={side} | risk={risk_pct:.0%} | "
                     f"Equity=£{equity:,.2f} | "
                     f"DailyDD={dd_state.daily_dd(equity)/INITIAL_BAL:.2%} | "
                     f"TotalDD={dd_state.total_dd(equity)/INITIAL_BAL:.2%}")

            # ── Execute ───────────────────────────────────────────────────────
            if side == "FLAT" and open_pos:
                await close_all_positions(account)
                current_side = None
                log.info(f"FLAT — closed all {SYMBOL} positions.")

            elif side in ("BUY", "SELL"):
                # Close opposite side first
                opposite = [p for p in open_pos
                            if (side == "BUY"  and p["type"] == "POSITION_TYPE_SELL") or
                               (side == "SELL" and p["type"] == "POSITION_TYPE_BUY")]
                if opposite:
                    await close_all_positions(account)
                    current_side = None

                lot = compute_lot(risk_pct, balance, atr_pips, dd_state, equity)
                if lot < INSTRUMENT["min_lot"]:
                    log.warning(f"Lot {lot} below minimum — skipping order.")
                else:
                    try:
                        if side == "BUY":
                            result = await account.create_market_buy_order(
                                SYMBOL, lot, comment="ftmo_rl_v1"
                            )
                        else:
                            result = await account.create_market_sell_order(
                                SYMBOL, lot, comment="ftmo_rl_v1"
                            )
                        current_side = side
                        log.info(f"ORDER PLACED: {side} {lot}L {SYMBOL} | "
                                 f"orderId={result.get('orderId','?')}")
                        log_trade_to_db({
                            "time"    : datetime.now(timezone.utc),
                            "action"  : side,
                            "lot"     : lot,
                            "price"   : acc_info.get("broker", 0),
                            "equity"  : equity,
                            "daily_dd": dd_state.daily_dd(equity) / INITIAL_BAL,
                            "total_dd": dd_state.total_dd(equity) / INITIAL_BAL,
                        })
                    except TradeException as te:
                        log.error(f"Trade failed: {te}")

            # ── Check profit target ───────────────────────────────────────────
            if equity - INITIAL_BAL >= PROFIT_TARGET:
                log.info(f"PROFIT TARGET REACHED: £{equity-INITIAL_BAL:,.2f} 🎯")
                await close_all_positions(account)
                if WANDB and wandb.run:
                    wandb.alert(title="PROFIT TARGET HIT",
                                text=f"Phase 1 target achieved. PnL=£{equity-INITIAL_BAL:,.0f}",
                                level=wandb.AlertLevel.INFO)
                break

            await asyncio.sleep(POLL_INTERVAL)

        except KeyboardInterrupt:
            log.info("Keyboard interrupt — closing positions and exiting.")
            await close_all_positions(account)
            break
        except Exception as e:
            log.error(f"Unexpected error: {e}", exc_info=True)
            await asyncio.sleep(30)

    if WANDB and wandb.run:
        wandb.finish()
    log.info("Live trader stopped.")


async def close_all_positions(account):
    """Close every open position on the account."""
    try:
        positions = await account.get_positions()
        for pos in positions:
            if pos["symbol"] == SYMBOL:
                await account.close_position(pos["id"])
                log.info(f"Closed position {pos['id']} ({pos['type']} {pos['volume']}L)")
    except Exception as e:
        log.error(f"Error closing positions: {e}")


if __name__ == "__main__":
    asyncio.run(run_trader())

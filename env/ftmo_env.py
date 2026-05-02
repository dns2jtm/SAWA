"""
FTMO Gym Environment — Prop-Firm-Aware RL Trading Environment
==============================================================
Extends a standard continuous action space with:
  1. FTMO constraint enforcement (daily DD, total DD, profit target)
  2. Economic calendar integration — blocks trades before high-impact events
  3. Session-aware reward shaping (London/NY bonus, Asian penalty)
  4. Universal prop firm config (change ACTIVE_FIRM in config/prop_firms.py)
  5. Position sizing driven by prop firm risk_per_trade_pct

Observation space (77 features):
  - OHLCV + technical indicators (RSI, MACD, ATR, Bollinger, EMA stack)
  - Market microstructure (spread, volume ratio, session flags)
  - Account state (equity_pct, daily_pnl_pct, total_pnl_pct, days_traded)
  - Sentiment signal (FinancialBERT + DeBERTa ensemble score, novelty)
  - Calendar state (minutes_to_next_event, block_flag)
  - Regime state (HMM regime 0/1/2, VIX proxy)

Action space: Box([-1], [1], float32)
  -1.0 → -0.33  : SHORT  (size proportional to |action|)
  -0.33 → +0.33 : FLAT   (close any open position)
  +0.33 → +1.0  : LONG   (size proportional to action)
"""

import os
import sys
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

import numpy as np
import pandas as pd
import gymnasium as gym
from gymnasium import spaces
from typing import Tuple, List, Optional

from config.prop_firms import get_config, ACTIVE_FIRM
from config.instruments import INSTRUMENTS, ACTIVE_INSTRUMENT
from data.features import FeaturePipeline
from data.news_calendar import CalendarFilter, CalendarStatus


# ── Execution ───────────────────────────────────────────────────────────────
FLAT_ZONE  = 0.33   # |action| < this = flat
SESSION_UTC = {
    "london":   (7, 16),
    "new_york": (12, 21),
    "overlap":  (12, 16),
}


class ExecutionModel:
    """
    Applies realistic execution costs to every trade.
    """
    PROFILES = {
        "optimistic": {"spread": 0.25, "slippage": 0.05, "swap_long": -1.5,  "swap_short": -0.3},
        "realistic":  {"spread": 0.35, "slippage": 0.15, "swap_long": -2.5,  "swap_short": -0.5},
        "pessimistic":{"spread": 0.80, "slippage": 0.40, "swap_long": -3.5,  "swap_short": -0.8},
        "news_spike": {"spread": 2.00, "slippage": 1.50, "swap_long": -2.5,  "swap_short": -0.5},
    }

    def __init__(self, profile: str = "realistic", symbol: str = "XAUUSD", news_pct: float = 0.05):
        self.base = self.PROFILES.get(profile, self.PROFILES["realistic"])
        self.news_pct = news_pct
        from config.instruments import get_instrument
        inst = get_instrument(symbol)
        self.pip_size = inst["pip_size"]
        self.pip_value_per_lot = inst["pip_value_per_lot"]

    def entry_cost(self, lot: float, is_news: bool = False) -> float:
        p = self.base if not is_news else self.PROFILES["news_spike"]
        # spread + slippage in pips
        total_pips = (p["spread"] + p["slippage"]) / self.pip_size
        return total_pips * self.pip_value_per_lot * lot

    def exit_cost(self, lot: float, is_news: bool = False) -> float:
        # Exit slippage is typically half of entry
        p = self.base if not is_news else self.PROFILES["news_spike"]
        total_pips = (p["spread"] * 0.5 + p["slippage"] * 0.5) / self.pip_size
        return total_pips * self.pip_value_per_lot * lot

    def overnight_swap(self, lot: float, direction: int, n_nights: int = 1) -> float:
        rate = self.base["swap_long"] if direction > 0 else self.base["swap_short"]
        return rate * lot * n_nights

    def total_round_trip(self, lot: float, n_nights: int = 0,
                         direction: int = 1, is_news: bool = False) -> float:
        """Full round-trip cost for a trade."""
        entry = self.entry_cost(lot, is_news)
        exit_ = self.exit_cost(lot, is_news)
        swap  = self.overnight_swap(lot, direction, n_nights)
        return entry + exit_ + abs(swap)


class FTMOEnv(gym.Env):
    """
    Prop-firm-aware trading environment.

    Parameters
    ----------
    df : pd.DataFrame
        OHLCV + feature dataframe indexed by UTC datetime.
        Required columns: open, high, low, close, volume
        Optional: rsi, macd, macd_signal, atr, bb_upper, bb_lower,
                  ema_20, ema_50, ema_200, sentiment_score, sentiment_novelty,
                  hmm_regime, spread_pips
    firm : str
        Prop firm key from config/prop_firms.py. Default: ACTIVE_FIRM.
    initial_balance : float
        Starting account balance. Overridden by firm config if set.
    pip_value : float
        $ value per pip per 0.01 lot (default: 1.0 for XAUUSD — $1/pip/0.01lot).
    use_calendar : bool
        Whether to enforce economic calendar blocking (default: True).
    training : bool
        If True, skips live calendar fetch (uses synthetic calendar).
        Set False for live trading.
    verbose : int
        0 = silent, 1 = episode summary, 2 = step-level logging.
    """

    metadata = {"render_modes": ["human", "ansi"]}

    def __init__(
        self,
        df:                  pd.DataFrame,
        firm:                str   = None,
        initial_balance:     float = None,
        pip_value:           float = None,   # None -> use instrument default
        use_calendar:        bool  = True,
        training:            bool  = True,
        verbose:             int   = 0,
        max_episode_steps:   int   = 720,   # 30 days × 24 H1 bars = FTMO window
        random_start:        bool  = None,  # None → True if training, False if not
        execution_profile:   str   = "realistic",
    ):
        super().__init__()

        # ── Prop firm config ──────────────────────────────────────────────────
        self.firm_key  = firm or ACTIVE_FIRM
        self.cfg       = get_config(self.firm_key)
        
        # ── Instrument config ─────────────────────────────────────────────────
        # Default to XAUUSD if not specified in firm config
        instr_key = self.cfg.get("instruments", [ACTIVE_INSTRUMENT])[0]
        self.instr_cfg = INSTRUMENTS.get(instr_key, INSTRUMENTS[ACTIVE_INSTRUMENT])
        
        self.pip_value = pip_value or self.instr_cfg.get("pip_value_per_lot", 1.0)
        self.pip_size  = self.instr_cfg.get("pip_size", 0.01)
        self.spread    = self.instr_cfg.get("spread_typical", 0.30) / self.pip_size # convert to pips
        
        # ── Execution Model ───────────────────────────────────────────────────
        self.exec_model = ExecutionModel(profile=execution_profile, symbol=instr_key)
        
        self.verbose   = verbose
        self.training  = training
        self.specialists = None  # List of 3 PPO models, one per regime (set via set_specialists())
        self.regime_probs = None
        self.current_regime = 1  # default RANGING

        # Account sizing
        self.initial_balance = initial_balance or float(self.cfg["account_size"])
        self.balance         = self.initial_balance

        # Constraint thresholds (personal limits — conservative vs FTMO hard limits)
        self.ftmo_max_daily_loss = self.initial_balance * self.cfg["max_daily_loss_pct"]
        self.ftmo_max_total_loss = self.initial_balance * self.cfg["max_total_loss_pct"]
        self.personal_daily_loss = self.initial_balance * self.cfg["personal_daily_limit"]
        self.personal_total_loss = self.initial_balance * self.cfg["personal_total_limit"]
        self.profit_target   = self.initial_balance * self.cfg["profit_target_pct"]
        self.risk_per_trade  = self.initial_balance * self.cfg["risk_per_trade_pct"]
        self.min_days        = self.cfg["min_trading_days"]

        # Reward shaping weights — all in fractional-return space (~1% = 0.01)
        # These are Phase-1 defaults; the curriculum callback overrides them.
        self.lambda_daily_dd = 0.020   # soft daily DD penalty coefficient (raised from 0.005)
        self.lambda_total_dd = 0.030   # soft total DD penalty coefficient (raised from 0.010)
        self.lambda_target   = 0.50    # challenge completion bonus

        # Hard daily cutout: if daily_pnl < -cutout_frac * max_daily_loss,
        # force-close open position and block new trades for the rest of the day.
        self.daily_cutout_frac = 0.70  # cut out at 70% of daily limit

        # ── Data ─────────────────────────────────────────────────────────────
        self.df               = df.reset_index(drop=False)   # keep datetime as column
        self.n_steps          = len(self.df)
        self.max_episode_steps = max(1, max_episode_steps)
        # random_start defaults to True during training, False during eval
        self.random_start     = training if random_start is None else random_start
        self.episode_start    = 0   # updated in reset()

        # ── Calendar filter ───────────────────────────────────────────────────
        self.use_calendar = use_calendar and not training
        if self.use_calendar:
            self.calendar = CalendarFilter(firm=self.firm_key)
        else:
            self.calendar = None

        # ── Spaces ────────────────────────────────────────────────────────────
        self.obs_dim = 77  # 65 static from FeaturePipeline + 12 dynamic account state
        self.observation_space = spaces.Box(
            low=-np.inf, high=np.inf,
            shape=(self.obs_dim,), dtype=np.float32
        )
        self.action_space = spaces.Box(
            low=np.array([-1.0], dtype=np.float32),
            high=np.array([1.0],  dtype=np.float32),
        )

        # ── Cache observation column names (avoid per-step import) ────────────
        self._obs_columns = FeaturePipeline.OBS_COLUMNS

        # ── Episode state (reset in reset()) ─────────────────────────────────
        self._reset_state()

    # ── Reset ─────────────────────────────────────────────────────────────────

    def _reset_state(self):
        self.current_step       = self.episode_start if hasattr(self, "episode_start") else 0
        self.balance            = self.initial_balance
        self.equity             = self.initial_balance
        self.position           = 0.0       # lot size, negative = short
        self.entry_price        = 0.0
        self.open_pnl           = 0.0
        self.daily_pnl          = 0.0
        self.total_pnl          = 0.0
        self.peak_equity        = self.initial_balance
        self.daily_start_equity = self.initial_balance
        self.max_dd_pct         = 0.0       # peak-to-trough drawdown fraction
        self.days_traded        = 0
        self.trades_today       = 0
        
        # Initialize last_date from the first bar of the episode to prevent
        # an immediate day-boundary reset on the first step.
        row = self.df.iloc[self.current_step]
        dt = pd.to_datetime(row.get("datetime", row.name))
        self.last_date = dt.date() if hasattr(dt, "date") else None
        
        self.episode_trades     = []
        self.calendar_blocked   = False
        self.prev_equity        = self.initial_balance  # for per-step MTM reward
        self.trade_count        = 0
        self.direction          = 0    # current position direction: -1 short / 0 flat / +1 long
        self.stop_loss_price    = 0.0  # enforced hard stop based on 1.5x ATR
        self._target_bonus_awarded = False

        # ── Trade tracking (for backtest cost simulation) ──────────────────────
        self._trade_closed    = False   # True for one step after a position closes
        self._trade_pnl       = 0.0    # Realised PnL of the last closed trade
        self._trade_cost      = 0.0    # Total cost of the last closed trade
        self._trade_lots      = 0.0    # Lot size of the last closed trade
        self._trade_direction = 0      # Direction of the last closed trade
        self._bars_held       = 0      # Bars the last trade was held
        self._entry_step      = 0      # Step at which current position was opened
        self._accrued_swap    = 0.0    # Overnight swap accrued on current position

        # ── Intra-bar breach tracking ──────────────────────────────────────────
        self._breach_daily    = False   # True if a daily DD breach terminated episode
        self._breach_total    = False   # True if a total DD breach terminated episode

    def reset(self, seed: int = None, options: dict = None) -> Tuple[np.ndarray, dict]:
        super().reset(seed=seed)
        # Pick a random start bar so each episode sees different market conditions.
        # Ensure there are enough bars remaining for at least one episode window.
        max_start = max(0, self.n_steps - self.max_episode_steps - 1)
        if self.random_start and max_start > 0:
            self.episode_start = int(self.np_random.integers(0, max_start))
        else:
            self.episode_start = 0
        self._reset_state()
        obs  = self._get_obs()
        info = self._get_info()
        return obs, info

    def set_specialists(self, specialists: List):
        """Set the 3 specialist PPO models (one per regime: 0=TREND, 1=RANGE, 2=VOL)."""
        if len(specialists) != 3:
            raise ValueError("Must provide exactly 3 specialist models")
        self.specialists = specialists
        print(f"  📊 Loaded {len(specialists)} regime specialists")

    # ── Step ──────────────────────────────────────────────────────────────────

    def step(self, action: np.ndarray) -> Tuple[np.ndarray, float, bool, bool, dict]:
        assert self.action_space.contains(action), f"Invalid action: {action}"

        self._trade_closed    = False
        self._trade_pnl       = 0.0
        self._trade_lots      = 0.0
        self._trade_direction = 0
        self._bars_held       = 0

        row     = self.df.iloc[self.current_step]
        price   = float(row["close"])
        dt      = pd.to_datetime(row.get("datetime", row.name))
        hour    = dt.hour if hasattr(dt, "hour") else 0

        # ── Regime Routing ─────────────────────────────────────────────────────
        # Extract regime probabilities from observation (indices 61-64)
        obs = self._get_obs()
        regime_start = 61
        regime_probs = obs[regime_start:regime_start+3]
        self.regime_probs = regime_probs
        self.current_regime = int(np.argmax(regime_probs))

        # If we have specialists, override the action with the appropriate specialist
        if self.specialists is not None and len(self.specialists) == 3:
            specialist = self.specialists[self.current_regime]
            action, _ = specialist.predict(obs, deterministic=True)

        # ── Day boundary reset ─────────────────────────────────────────────
        current_date = dt.date() if hasattr(dt, "date") else None
        if current_date and current_date != self.last_date:
            if self.last_date is not None and self.trades_today > 0:
                self.days_traded += 1
            self.daily_pnl          = 0.0
            self.daily_start_equity = self.equity
            self.trades_today       = 0
            self.last_date          = current_date

        # ── Calendar check (live mode only) ───────────────────────────────
        block_trades = False
        close_now    = False
        if self.use_calendar and self.calendar:
            symbol = self.cfg.get("instruments", [ACTIVE_INSTRUMENT])[0]
            status: CalendarStatus = self.calendar.get_status(symbol)
            block_trades    = status.block_new_trades
            close_now       = status.close_positions
            self.calendar_blocked = block_trades

        # ── Weekend check ──────────────────────────────────────────────────
        if not self.cfg.get("weekend_holding", True):
            if hasattr(dt, "weekday") and dt.weekday() >= 4 and hour >= 20:
                close_now    = True
                block_trades = True

        # ── Hard daily DD cutout ───────────────────────────────────────────
        # If today's floating loss has reached the cutout threshold, force
        # close any open position and block further trades for the day.
        # This is the primary mechanism preventing daily breach spiralling.
        _current_daily_dd = max(0.0, -self.daily_pnl)
        if _current_daily_dd >= self.personal_daily_loss * self.daily_cutout_frac:
            block_trades = True
            if self.position != 0:
                close_now = True

        # ── Daily Target Cutout ────────────────────────────────────────────
        # If today's profit reaches the prop firm daily target pacing, block
        # further trades. Prevents overtrading once daily goal is hit.
        daily_target = self.initial_balance * self.cfg.get("daily_target_pct", 1.0)
        if self.daily_pnl >= daily_target:
            block_trades = True
            if self.position != 0:
                close_now = True

        # ── Max trades per day ─────────────────────────────────────────────
        max_trades = self.cfg.get("max_trades_per_day", 3)
        if self.trades_today >= max_trades:
            block_trades = True

        # ── Interpret action ───────────────────────────────────────────────
        act_val       = float(action[0])
        desired_pos   = self._action_to_position(act_val, block_trades, self.direction)

        # ── Execute trade ──────────────────────────────────────────────────
        # desired_pos: direction signal (-1, 0, +1)
        # self.direction: current open direction (-1, 0, +1)
        # self.position: actual lot size (e.g. ±0.35) — NEVER compare to desired_pos
        reward        = 0.0
        trade_cost    = 0.0

        # ── Enforce Stop Loss ──────────────────────────────────────────────
        stop_hit = False
        bar_open = float(row.get("open", price))
        bar_low  = float(row.get("low", price))
        bar_high = float(row.get("high", price))
        sl_price = getattr(self, "stop_loss_price", -np.inf if self.position > 0 else np.inf)

        if self.position > 0:
            if bar_open <= sl_price:
                self._close_position(bar_open)
                self.direction = 0
                stop_hit = True
            elif bar_low <= sl_price:
                self._close_position(sl_price)
                self.direction = 0
                stop_hit = True
        elif self.position < 0:
            if bar_open >= sl_price:
                self._close_position(bar_open)
                self.direction = 0
                stop_hit = True
            elif bar_high >= sl_price:
                self._close_position(sl_price)
                self.direction = 0
                stop_hit = True

        if close_now and self.position != 0:
            self._close_position(price)
            self.direction = 0

        elif not stop_hit and desired_pos != self.direction:   # direction changed (or flat→open)
            # Close existing position first
            if self.position != 0:
                self._close_position(price)
                self.direction = 0

            # Open new position in the desired direction
            if desired_pos != 0 and not block_trades:
                lot_size          = self._compute_lot_size(price)
                self.position     = desired_pos * lot_size
                self.entry_price  = price
                self.direction    = int(desired_pos)
                self.trades_today += 1
                self.trade_count  += 1
                self._entry_step  = self.current_step

                # Set hard Stop-Loss (1.5x ATR, capped between $10 and $150)
                atr_norm = float(row.get("atr_14", 0.01))
                atr_usd  = max(atr_norm * price, 1.0)
                stop_usd = max(10.0, min(atr_usd * 1.5, 150.0))
                self.stop_loss_price = price - (desired_pos * stop_usd)

        # ── Mark-to-market ─────────────────────────────────────────────────
        is_news = row.get("event_flag", 0.0) > 0.5
        if self.position != 0 and self.entry_price > 0:
            pip_move      = (price - self.entry_price) / self.pip_size
            # Use ExecutionModel for a more realistic net PnL
            entry_cost    = self.exec_model.entry_cost(abs(self.position), is_news)
            exit_cost     = self.exec_model.exit_cost(abs(self.position), is_news)
            
            # Accrue swap overnight but do NOT deduct from balance here.
            # The accrued amount is subtracted from PnL when the position closes,
            # preventing the double-count that previously reduced balance AND open_pnl.
            if hour == 22 and getattr(self, "_last_hour", -1) != 22:
                self._accrued_swap += abs(
                    self.exec_model.overnight_swap(abs(self.position), self.direction)
                )
            self._last_hour = hour

            self.open_pnl = (self.position * pip_move * self.pip_value) - (entry_cost + exit_cost + self._accrued_swap)
        else:
            self.open_pnl = 0.0

        self.equity          = self.balance + self.open_pnl
        self.daily_pnl       = self.equity - self.daily_start_equity
        self.total_pnl       = self.equity - self.initial_balance
        self.peak_equity     = max(self.peak_equity, self.equity)
        # Track max drawdown from peak (fraction of peak equity)
        _dd_from_peak        = (self.peak_equity - self.equity) / (self.peak_equity + 1e-9)
        self.max_dd_pct      = max(self.max_dd_pct, _dd_from_peak)

        # ── Per-step MTM reward ────────────────────────────────────────────
        reward += (self.equity - self.prev_equity) / self.initial_balance
        self.prev_equity = self.equity

        # ── Intra-bar Drawdown Check ───────────────────────────────────────
        # Real FTMO tracks equity tick-by-tick. We must check the worst intra-bar
        # excursion (high or low) to prevent survivorship bias where the agent 
        # survives a massive intra-hour crash because the close price recovered.
        if self.position > 0:
            worst_price = float(row.get("low", price))
        elif self.position < 0:
            worst_price = float(row.get("high", price))
        else:
            worst_price = price

        if self.position != 0 and self.entry_price > 0:
            worst_pip_move = (worst_price - self.entry_price) / self.pip_size
            entry_cost     = self.exec_model.entry_cost(abs(self.position), is_news)
            exit_cost      = self.exec_model.exit_cost(abs(self.position), is_news)
            worst_open_pnl = (self.position * worst_pip_move * self.pip_value) - (entry_cost + exit_cost)
        else:
            worst_open_pnl = 0.0
            
        worst_equity    = self.balance + worst_open_pnl
        worst_daily_pnl = worst_equity - self.daily_start_equity
        # Track max drawdown using intra-bar worst equity (not just close-price)
        _worst_dd_from_peak = (self.peak_equity - worst_equity) / (self.peak_equity + 1e-9)
        self.max_dd_pct     = max(self.max_dd_pct, _worst_dd_from_peak)

        # ── FTMO constraint penalties (Non-linear) ──────────────────────────
        daily_dd  = max(0.0, -worst_daily_pnl)
        total_dd  = max(0.0, self.initial_balance - worst_equity)

        # DD usage metrics (terminal penalty uses these, but we removed the continuous
        # exponential penalty because it caused agents to blow up accounts intentionally
        # to escape the per-step penalty bleed).
        daily_dd_ratio = daily_dd / (self.personal_daily_loss + 1e-9)
        total_dd_ratio = total_dd / (self.personal_total_loss + 1e-9)

        # ── Profit target bonus ────────────────────────────────────────────
        if self.total_pnl >= self.profit_target and not self._target_bonus_awarded:
            reward += self.lambda_target   # fractional bonus for hitting challenge target
            self._target_bonus_awarded = True
            if self.verbose >= 1:
                print(f"  🏆 Profit target hit! PnL: £{self.total_pnl:,.2f}")

        # ── Session reward shaping ─────────────────────────────────────────
        if self.position != 0:
            if SESSION_UTC["overlap"][0] <= hour < SESSION_UTC["overlap"][1]:
                reward = reward * 1.20 if reward > 0 else reward
            elif SESSION_UTC["london"][0] <= hour < SESSION_UTC["london"][1]:
                reward = reward * 1.10 if reward > 0 else reward
            elif SESSION_UTC["new_york"][0] <= hour < SESSION_UTC["new_york"][1]:
                reward = reward * 1.05 if reward > 0 else reward
            else:
                # Asian session — penalise holding
                reward = reward * 0.80 if reward > 0 else reward * 1.20

        # ── Termination conditions ─────────────────────────────────────────
        terminated  = False
        truncated   = False

        if daily_dd >= self.ftmo_max_daily_loss:
            terminated          = True
            self._breach_daily  = True
            reward    -= self.lambda_daily_dd * 10
            if self.verbose >= 1:
                print(f"  💀 Daily DD breach: £{daily_dd:,.2f} > £{self.ftmo_max_daily_loss:,.2f}")

        if total_dd >= self.ftmo_max_total_loss:
            terminated          = True
            self._breach_total  = True
            reward    -= self.lambda_total_dd * 10
            if self.verbose >= 1:
                print(f"  💀 Total DD breach: £{total_dd:,.2f} > £{self.ftmo_max_total_loss:,.2f}")

        if self.total_pnl >= self.profit_target and self.days_traded >= self.min_days:
            terminated = True
            if self.verbose >= 1:
                print(f"  ✅ Challenge passed! Days: {self.days_traded}, PnL: £{self.total_pnl:,.2f}")

        # ── Advance step and check truncation ─────────────────────────────────
        self.current_step += 1
        steps_this_episode = self.current_step - getattr(self, "episode_start", 0)
        if self.current_step >= self.n_steps - 1 or steps_this_episode >= self.max_episode_steps:
            truncated = True

        # ── Count the final active day at episode end ──────────────────────
        # The day-boundary block only increments days_traded when the NEXT
        # day's first bar arrives.  If the episode terminates before that
        # crossing (e.g. on a DD breach on day 1), the current day is never
        # counted.  Fix: credit the current day on termination/truncation.
        if (terminated or truncated) and self.trades_today > 0:
            self.days_traded += 1

        if (terminated or truncated) and self.position != 0:
            self._close_position(price)
            self.direction  = 0
            self.equity     = self.balance
            self.daily_pnl  = self.equity - self.daily_start_equity
            self.total_pnl  = self.equity - self.initial_balance

        obs  = self._get_obs()
        info = self._get_info()
        
        # Scale entire reward surface by 100 to shift from fractional percentage space
        # (where 1% gain = 0.01 reward) into integer-scale space (1% gain = 1.0 reward).
        # This prevents the PPO Value Function from struggling with microscopic gradients.
        scaled_reward = reward * 100.0
        
        return obs, scaled_reward, terminated, truncated, info

    # ── Helpers ───────────────────────────────────────────────────────────────

    def _action_to_position(self, action: float, blocked: bool, current_dir: int) -> float:
        if blocked:
            return 0.0
        
        # Hysteresis to prevent noise-induced closing/whipsawing
        # If flat, require strong signal (> 0.5) to enter
        # If open, require signal to drop near 0 (< 0.1) to close
        entry_thresh = 0.50
        exit_thresh  = 0.10

        if current_dir == 1:
            if action < -entry_thresh: return -1.0
            if action < exit_thresh:   return 0.0
            return 1.0
        elif current_dir == -1:
            if action > entry_thresh:  return 1.0
            if action > -exit_thresh:  return 0.0
            return -1.0
        else:
            if action > entry_thresh:  return 1.0
            if action < -entry_thresh: return -1.0
            return 0.0

    def _compute_lot_size(self, price: float) -> float:
        """ATR-based position sizing with volatility-regime scaling.

        Base sizing: risk £X per trade with 1.5×ATR stop.
        Regime scalar: if current ATR is elevated vs its rolling historical
        average, scale the lot size down proportionally. This prevents the
        agent from taking full-size positions in high-volatility regimes
        (e.g. test period Jan–Apr 2026, which is 2.5× more volatile than
        the training period) and is the primary fix for the 62% daily breach
        rate observed out-of-sample.

        Formula:
            vol_scalar = clip(atr_hist_mean / atr_current, 0.25, 1.0)
            lot = base_lot × vol_scalar

        At 1× vol (normal regime):   vol_scalar ≈ 1.0  → full size
        At 2× vol (elevated regime): vol_scalar ≈ 0.5  → half size
        At 3× vol (crisis regime):   vol_scalar = 0.25 → quarter size
        """
        row      = self.df.iloc[min(self.current_step, self.n_steps - 1)]
        atr_norm = float(row.get("atr_14", 0.01))          # ATR / close (normalized)
        atr_usd  = max(atr_norm * price, 1.0)               # raw ATR in price units

        # ── Volatility regime scalar ──────────────────────────────────────────
        # Compare current ATR to rolling 200-bar mean ATR from the feature df.
        # If unavailable, fall back to scalar = 1.0 (no adjustment).
        step     = self.current_step
        lookback = min(200, step)
        if lookback > 10 and "atr_14" in self.df.columns:
            hist_atr = self.df["atr_14"].iloc[max(0, step - lookback):step]
            atr_hist_mean = float(hist_atr.mean()) * price   # convert to USD
            # scalar < 1 when we're in a high-vol regime vs history
            vol_scalar = np.clip(atr_hist_mean / (atr_usd + 1e-9), 0.25, 1.0)
        else:
            vol_scalar = 1.0   # not enough history yet — use full size

        # ── Base lot from risk / stop ─────────────────────────────────────────
        # Use 1.0x ATR for risk calculation to match tightened stop-loss
        stop_usd  = max(5.0, min(atr_usd * 1.0, 100.0))   
        stop_pips = stop_usd / self.pip_size                  # = stop_usd / 0.01
        base_lot  = self.risk_per_trade / (stop_pips * self.pip_value)

        lot = base_lot * vol_scalar
        return round(max(0.01, min(lot, 5.0)), 2)            # cap at 5.0 lots


    def _close_position(self, price: float) -> float:
        if self.position == 0:
            return 0.0
            
        row = self.df.iloc[min(self.current_step, self.n_steps - 1)]
        is_news = row.get("event_flag", 0.0) > 0.5
        
        pip_move    = (price - self.entry_price) / self.pip_size
        pnl         = self.position * pip_move * self.pip_value
        
        # Total round-trip cost: spread/slippage + accrued overnight swap
        entry_cost  = self.exec_model.entry_cost(abs(self.position), is_news)
        exit_cost   = self.exec_model.exit_cost(abs(self.position), is_news)
        trade_cost  = entry_cost + exit_cost + getattr(self, "_accrued_swap", 0.0)

        realised_pnl = pnl - trade_cost
        self.balance += realised_pnl

        # ── Record trade info for backtest cost simulation ────────────────────
        self._trade_closed    = True
        self._trade_pnl       = realised_pnl
        self._trade_cost      = trade_cost
        self._trade_lots      = abs(self.position)
        self._trade_direction = int(np.sign(self.position))
        self._bars_held       = max(0, self.current_step - self._entry_step)

        self.position      = 0.0
        self.entry_price   = 0.0
        self.open_pnl      = 0.0
        self._accrued_swap = 0.0   # reset for next position
        self.episode_trades.append(realised_pnl)
        return 0.0   # P&L captured by per-step MTM reward; balance already updated

    def _get_obs(self) -> np.ndarray:
        row = self.df.iloc[min(self.current_step, self.n_steps - 1)]

        # ── 1. Dynamic Account State (12 features) ────────────────────────────
        dyn_feats = [
            # Account state (8)
            self.equity / self.initial_balance - 1,
            self.daily_pnl / self.initial_balance,
            self.total_pnl / self.initial_balance,
            self.total_pnl / (self.profit_target + 1e-9),
            -min(self.daily_pnl, 0) / (self.personal_daily_loss + 1e-9),
            -min(self.total_pnl, 0) / (self.personal_total_loss + 1e-9),
            self.days_traded / max(self.min_days, 1),
            self.trades_today / max(self.cfg.get("max_trades_per_day", 3), 1),

            # Position state (4)
            float(self.position > 0),
            float(self.position < 0),
            abs(self.position),
            self.open_pnl / (self.initial_balance + 1e-9),
        ]

        # ── 2. Static Market Features (65 features from FeaturePipeline) ──────
        static_feats = [float(0.0 if pd.isna(row.get(col, 0.0)) else row.get(col, 0.0)) for col in self._obs_columns]

        # Total = 77 features
        obs = np.array(dyn_feats + static_feats, dtype=np.float32)
        obs = np.nan_to_num(obs, nan=0.0, posinf=1.0, neginf=-1.0)
        return obs

    def _get_info(self) -> dict:
        passed = self.total_pnl >= self.profit_target and self.days_traded >= self.min_days

        return {
            "balance":           self.balance,
            "equity":            self.equity,
            "daily_pnl":         self.daily_pnl,
            "total_pnl":         self.total_pnl,
            "position":          self.position,
            "days_traded":       self.days_traded,
            "trades_today":      self.trades_today,
            "n_trades":          self.trade_count,
            "trading_days":      self.days_traded,
            "final_pnl_pct":     self.total_pnl / (self.initial_balance + 1e-9),
            "challenge_passed":  passed,
            "daily_dd_breach":   self._breach_daily,
            "total_dd_breach":   self._breach_total,
            "max_dd_pct":        self.max_dd_pct,
            "profit_target":     self.profit_target,
            "max_daily_loss":    self.ftmo_max_daily_loss,
            "max_total_loss":    self.ftmo_max_total_loss,
            "personal_daily_loss": self.personal_daily_loss,
            "personal_total_loss": self.personal_total_loss,
            "calendar_blocked":  self.calendar_blocked,
            "firm":              self.firm_key,
            "trade_closed":      self._trade_closed,
            "trade_pnl_usd":     self._trade_pnl,
            "trade_cost":        self._trade_cost,
            "lot_size":          self._trade_lots,
            "direction":         self._trade_direction,
            "bars_held":         self._bars_held,
            "current_regime":    self.current_regime,
        }

    def render(self, mode: str = "human"):
        info = self._get_info()
        print(
            f"Step {self.current_step:5d} | "
            f"Eq £{info['equity']:>10,.2f} | "
            f"Day PnL £{info['daily_pnl']:>+8,.2f} | "
            f"Total PnL £{info['total_pnl']:>+9,.2f} | "
            f"Pos: {info['position']:>+5.2f} | "
            f"Days: {info['days_traded']:2d} | "
            f"Regime: {info['current_regime']} | "
            f"Firm: {info['firm']}"
        )


"""
Feature Engineering Pipeline — XAUUSD
======================================
Transforms raw OHLCV into the 65-feature observation vector
consumed by FTMOEnv.

Features built:
  Group A — Price & Returns (8)
    log_return, log_return_h4, log_return_d, body_pct, upper_wick, lower_wick,
    gap_open, overnight_gap

  Group B — Momentum Indicators (10)
    rsi_14, rsi_7, macd, macd_signal, macd_hist, adx_14, cci_20,
    roc_10, willr_14, stoch_k

  Group C — Volatility (8)
    atr_14, atr_7, bb_upper, bb_lower, bb_width, bb_pct,
    hist_vol_20, hist_vol_5

  Group D — Trend / Structure (8)
    ema_20, ema_50, ema_200, ema_cross_20_50, ema_cross_50_200,
    price_vs_ema200, higher_high, lower_low

  Group E — Volume (4)
    volume_ratio, volume_ma20, obv_norm, vwap_dist

  Group F — Session & Calendar (6)
    hour_sin, hour_cos, day_sin, day_cos, is_london, is_ny,
    (6 features)

  Group G — Multi-timeframe (6)
    h4_rsi, h4_macd, h4_trend, d_rsi, d_trend, h4_atr

  Group H — Gold-Specific Macro Proxies (5)
    dxy_proxy, real_yield_proxy, vix_proxy, gold_seasonality, roll_day

  Group I — Sentiment (6)   [filled with zeros until NLP pipeline runs]
    sentiment_score, sentiment_novelty, sentiment_momentum,
    news_volume, event_flag, minutes_to_news

  Group J — Regime (4)
    hmm_regime_0, hmm_regime_1, hmm_regime_2, trend_strength

Usage:
    from data.features import FeaturePipeline
    pipe = FeaturePipeline()
    df   = pipe.build(df_h1, df_h4=df_h4, df_d=df_d)   # full pipeline
    X    = pipe.to_obs_array(df)                          # (n, 65) float32
"""

import os
import sys
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

import warnings
warnings.filterwarnings("ignore")

from pathlib import Path
from typing  import Optional

import pickle

import numpy  as np
import pandas as pd

# All technical indicators are implemented natively in pure numpy/pandas
# (see _rsi, _macd, _atr, _adx, _bollinger, etc. below).
# No external TA library required.

RAW_DIR      = Path(__file__).parent / "raw"
FEATURES_DIR = Path(__file__).parent / "features"
FEATURES_DIR.mkdir(parents=True, exist_ok=True)

OBS_DIM = 65


# ── Low-level indicator helpers (pure pandas — no external deps) ──────────────

def _ema(series: pd.Series, span: int) -> pd.Series:
    return series.ewm(span=span, adjust=False).mean()

def _rsi(close: pd.Series, period: int = 14) -> pd.Series:
    delta  = close.diff()
    gain   = delta.clip(lower=0)
    loss   = -delta.clip(upper=0)
    avg_g  = gain.ewm(com=period - 1, adjust=False).mean()
    avg_l  = loss.ewm(com=period - 1, adjust=False).mean()
    rs     = avg_g / (avg_l + 1e-9)
    return 100 - (100 / (1 + rs))

def _macd(close: pd.Series, fast=12, slow=26, signal=9):
    ema_fast = _ema(close, fast)
    ema_slow = _ema(close, slow)
    macd_line   = ema_fast - ema_slow
    signal_line = _ema(macd_line, signal)
    hist        = macd_line - signal_line
    return macd_line, signal_line, hist

def _atr(high: pd.Series, low: pd.Series, close: pd.Series, period: int = 14) -> pd.Series:
    tr = pd.concat([
        high - low,
        (high - close.shift(1)).abs(),
        (low  - close.shift(1)).abs(),
    ], axis=1).max(axis=1)
    return tr.ewm(com=period - 1, adjust=False).mean()

def _bollinger(close: pd.Series, period: int = 20, std: float = 2.0):
    ma     = close.rolling(period).mean()
    sd     = close.rolling(period).std()
    upper  = ma + std * sd
    lower  = ma - std * sd
    width  = (upper - lower) / (ma + 1e-9)
    pct    = (close - lower) / (upper - lower + 1e-9)
    return upper, lower, width, pct

def _adx(high: pd.Series, low: pd.Series, close: pd.Series, period: int = 14) -> pd.Series:
    up_move   = high.diff().fillna(0.0)
    down_move = (-low.diff()).fillna(0.0)
    plus_dm   = np.where((up_move > down_move) & (up_move > 0), up_move, 0.0)
    minus_dm  = np.where((down_move > up_move) & (down_move > 0), down_move, 0.0)

    atr_vals  = _atr(high, low, close, period)
    plus_di   = 100 * pd.Series(plus_dm,  index=close.index).ewm(com=period-1, adjust=False).mean() / (atr_vals + 1e-9)
    minus_di  = 100 * pd.Series(minus_dm, index=close.index).ewm(com=period-1, adjust=False).mean() / (atr_vals + 1e-9)
    dx        = 100 * (plus_di - minus_di).abs() / (plus_di + minus_di + 1e-9)
    adx       = dx.ewm(com=period-1, adjust=False).mean()
    return adx

def _obv(close: pd.Series, volume: pd.Series) -> pd.Series:
    direction = np.sign(close.diff().fillna(0))
    return (direction * volume).cumsum()

def _stoch(high: pd.Series, low: pd.Series, close: pd.Series,
           k_period: int = 14, d_period: int = 3):
    lowest_low   = low.rolling(k_period).min()
    highest_high = high.rolling(k_period).max()
    k = 100 * (close - lowest_low) / (highest_high - lowest_low + 1e-9)
    d = k.rolling(d_period).mean()
    return k, d

def _cci(high: pd.Series, low: pd.Series, close: pd.Series, period: int = 20) -> pd.Series:
    tp   = (high + low + close) / 3
    ma   = tp.rolling(period).mean()
    md   = tp.rolling(period).apply(lambda x: np.mean(np.abs(x - x.mean())))
    return (tp - ma) / (0.015 * md + 1e-9)

def _willr(high: pd.Series, low: pd.Series, close: pd.Series, period: int = 14) -> pd.Series:
    hh = high.rolling(period).max()
    ll = low.rolling(period).min()
    return -100 * (hh - close) / (hh - ll + 1e-9)


# ── Gold seasonality (month-of-year effect) ───────────────────────────────────
# Gold historically strong in Jan, Feb, Aug, Sep, Nov (safe-haven / jewellery demand)
GOLD_SEASONAL = {
    1: 0.6, 2: 0.7, 3: 0.1, 4: 0.2,  5: -0.1, 6: -0.2,
    7: 0.0, 8: 0.5, 9: 0.6, 10: 0.0, 11: 0.4,  12: 0.3,
}


# ════════════════════════════════════════════════════════════════════════════════
# LSEG Overlay Helpers
# ════════════════════════════════════════════════════════════════════════════════

def _overlay_lseg_macro(df: pd.DataFrame) -> pd.DataFrame:
    """
    Replace proxy Group-H columns with real LSEG macro data when a cache file
    exists.  Silently no-ops if the cache is absent — pipeline continues with
    the existing proxy values.

    Replaces
    --------
    dxy_proxy        ← LSEG DXY z-score   (was: -log_return.rolling(24).sum())
    real_yield_proxy ← LSEG TIPS z-score  (was: hist_vol rolling-mean delta)
    vix_proxy        ← LSEG VIX z-score   (was: hist_vol_20 z-score)
    """
    try:
        from data.lseg_client import load_macro_cache
        macro = load_macro_cache()
        if macro.empty:
            return df

        H1_WINDOW = 252 * 24  # 1 calendar year of H1 bars ≈ 6 048 bars

        def _zscore_h1(daily_series: pd.Series, h1_idx) -> pd.Series:
            """Forward-fill daily series to H1 index, then z-score."""
            s = daily_series.reindex(h1_idx, method="ffill").ffill().bfill()
            mu = s.rolling(H1_WINDOW, min_periods=50).mean()
            sd = s.rolling(H1_WINDOW, min_periods=50).std() + 1e-9
            return ((s - mu) / sd).clip(-3, 3) / 3

        idx = df.index

        if "dxy" in macro.columns:
            df["dxy_proxy"] = _zscore_h1(macro["dxy"], idx)
            print("  [LSEG] dxy_proxy  ← real DXY (.DXY)")

        if "real_yield" in macro.columns:
            df["real_yield_proxy"] = _zscore_h1(macro["real_yield"], idx)
            print("  [LSEG] real_yield_proxy  ← US 10Y TIPS (US10YTIP=RR)")

        if "gold_vol" in macro.columns:
            df["vix_proxy"] = _zscore_h1(macro["gold_vol"], idx)
            print("  [LSEG] vix_proxy  ← real Gold Implied Volatility (XAU1MO=R)")

    except Exception as exc:
        print(f"  [LSEG] macro overlay skipped: {exc}")

    return df


def _overlay_lseg_sentiment(df: pd.DataFrame) -> pd.DataFrame:
    """
    Replace zero Group-I sentiment columns with Reuters-scored hourly values
    when a LSEG sentiment cache file exists.  Silently no-ops otherwise.

    Replaces
    --------
    sentiment_score     ← LSEG hourly mean compound score  [-1, +1]
    sentiment_novelty   ← hourly score std dev              [0, 1]
    sentiment_momentum  ← 6-hour EMA of sentiment_score
    news_volume         ← log-normalised headline count     [0, ~1]
    event_flag          ← 1 on unusual headline volume burst
    calendar_block      ← NOT replaced (live-only, set by CalendarFilter)
    """
    try:
        from data.lseg_client import load_sentiment_cache
        sent = load_sentiment_cache()
        if sent.empty:
            return df

        SENT_COLS = [
            "sentiment_score", "sentiment_novelty", "sentiment_momentum",
            "news_volume", "event_flag",
        ]
        available = [c for c in SENT_COLS if c in sent.columns]
        if not available:
            return df

        for col in available:
            aligned = sent[col].reindex(df.index, method="ffill").fillna(0)
            df[col] = aligned.values
        print(f"  [LSEG] sentiment overlay  ← {len(available)} cols, "
              f"{sent.index.min().date()} → {sent.index.max().date()}")

    except Exception as exc:
        print(f"  [LSEG] sentiment overlay skipped: {exc}")

    return df


def _add_minutes_to_news(df: pd.DataFrame) -> pd.DataFrame:
    """
    Calculate minutes until the next high-impact economic event.
    Normalized to [0, 1] where 1.0 = event right now, 0.0 = > 24 hours away.
    """
    df["minutes_to_news"] = 0.0
    try:
        from data.lseg_client import load_calendar_cache
        events_df = load_calendar_cache()
        if events_df.empty:
            return df

        event_times = pd.to_datetime(events_df["datetime_utc"], utc=True).sort_values().values
        bar_times   = df.index.values

        # For each bar, find the next event
        # np.searchsorted finds the insertion point for each bar_time in event_times
        idx = np.searchsorted(event_times, bar_times)

        # Filter out indices that are out of bounds (no future events for this bar)
        valid_mask = idx < len(event_times)
        next_event_times = np.full(len(bar_times), np.nan, dtype='datetime64[ns]')
        next_event_times[valid_mask] = event_times[idx[valid_mask]]

        # Calculate minutes
        # Note: both are in UTC nanoseconds (numpy datetime64[ns])
        diff_ns = (next_event_times - bar_times).astype(float)
        diff_min = diff_ns / (1e9 * 60.0)

        # Normalize: 1.0 at 0 min, 0.0 at 1440 min (24 hours) or more
        df["minutes_to_news"] = np.clip(1.0 - (diff_min / 1440.0), 0.0, 1.0)
        df["minutes_to_news"] = df["minutes_to_news"].fillna(0.0)

        print(f"  [FeaturePipeline] minutes_to_news added from {len(events_df)} events")

    except Exception as e:
        # Silently fail if calendar data is missing
        pass

    return df


# ════════════════════════════════════════════════════════════════════════════════
# Main Feature Pipeline
# ════════════════════════════════════════════════════════════════════════════════

class FeaturePipeline:
    """
    Builds the full 65-feature dataframe for FTMOEnv.

    Usage:
        pipe   = FeaturePipeline()
        df_out = pipe.build(df_h1, df_h4=df_h4, df_d=df_d)
        X      = pipe.to_obs_array(df_out)   # shape (n, 65)
    """

    OBS_COLUMNS = [
        # Group A — Price (8)
        "log_return", "log_return_4", "log_return_d",
        "body_pct", "upper_wick", "lower_wick", "gap_open", "overnight_gap",
        # Group B — Momentum (10)
        "rsi_14", "rsi_7", "macd", "macd_signal", "macd_hist",
        "adx_14", "cci_20", "roc_10", "willr_14", "stoch_k",
        # Group C — Volatility (8)
        "atr_14", "atr_7", "bb_upper", "bb_lower", "bb_width", "bb_pct",
        "hist_vol_20", "hist_vol_5",
        # Group D — Trend (8)
        "ema_20", "ema_50", "ema_200", "ema_cross_20_50", "ema_cross_50_200",
        "price_vs_ema200", "higher_high", "lower_low",
        # Group E — Volume (4)
        "volume_ratio", "volume_ma20", "obv_norm", "vwap_dist",
        # Group F — Session (6)
        "hour_sin", "hour_cos", "day_sin", "day_cos", "is_london", "is_ny",
        # Group G — MTF (6)
        "h4_rsi", "h4_macd", "h4_trend", "d_rsi", "d_trend", "h4_atr",
        # Group H — Gold Macro (5)
        "dxy_proxy", "real_yield_proxy", "vix_proxy",
        "gold_seasonality", "roll_day",
        # Group I — Sentiment (6)
        "sentiment_score", "sentiment_novelty", "sentiment_momentum",
        "news_volume", "event_flag", "minutes_to_news",
        # Group J — Regime (4)
        "hmm_regime_0", "hmm_regime_1", "hmm_regime_2", "trend_strength",
    ]   # total = 8+10+8+8+4+6+6+5+6+4 = 65 ✅

    def __init__(self):
        assert len(self.OBS_COLUMNS) == OBS_DIM, f"Column count mismatch: {len(self.OBS_COLUMNS)} != {OBS_DIM}"

    def build(self, df_h1: pd.DataFrame,
              df_h4: Optional[pd.DataFrame] = None,
              df_d:  Optional[pd.DataFrame] = None,
              refit_gmm: bool = False) -> pd.DataFrame:
        """
        Full feature pipeline.
        Returns dataframe with all 65 features + original OHLCV.
        """
        df = df_h1.copy()
        df = df.sort_index()

        # Ensure UTC index
        if df.index.tzinfo is None:
            df.index = df.index.tz_localize("UTC")

        # ── Price-scale guard ─────────────────────────────────────────────────
        # Dukascopy XAUUSD was historically downloaded with divisor=10 instead
        # of 1000, leaving prices ~100× too large (e.g. 206517 vs 2065.17).
        # Auto-correct: if median close looks like centidollars, divide by 100.
        # XAUUSD should always be in [1000, 5000] USD range.
        median_close = float(df["close"].median())
        if median_close > 10_000:
            scale_factor = round(median_close / 3000)  # nearest power-of-10 factor
            if scale_factor > 1:
                warnings.warn(
                    f"[FeaturePipeline] Detected price scale error: "
                    f"median close={median_close:.0f}, dividing OHLC by {scale_factor}. "
                    f"Fix the download divisor to avoid this.",
                    UserWarning, stacklevel=2,
                )
                for col in ("open", "high", "low", "close"):
                    if col in df.columns:
                        df[col] = df[col] / scale_factor

        close  = df["close"]
        high   = df["high"]
        low    = df["low"]
        open_  = df["open"]
        volume = df["volume"].replace(0, np.nan).ffill()

        # ── Group A: Price & Returns ──────────────────────────────────────────
        df["log_return"]    = np.log(close / close.shift(1))
        df["log_return_4"]  = np.log(close / close.shift(4))
        df["log_return_d"]  = np.log(close / close.shift(24))
        df["body_pct"]      = (close - open_) / (high - low + 1e-9)
        df["upper_wick"]    = (high - close.clip(lower=open_)) / (high - low + 1e-9)
        df["lower_wick"]    = (open_.clip(upper=close) - low) / (high - low + 1e-9)
        df["gap_open"]      = (open_ - close.shift(1)) / (close.shift(1) + 1e-9)
        df["overnight_gap"] = df["gap_open"] * (df.index.hour == 0).astype(float)

        # ── Group B: Momentum ─────────────────────────────────────────────────
        df["rsi_14"]        = _rsi(close, 14) / 100
        df["rsi_7"]         = _rsi(close,  7) / 100
        macd_l, macd_s, macd_h = _macd(close)
        df["macd"]          = macd_l / (close + 1e-9)
        df["macd_signal"]   = macd_s / (close + 1e-9)
        df["macd_hist"]     = macd_h / (close + 1e-9)
        df["adx_14"]        = _adx(high, low, close, 14) / 100
        df["cci_20"]        = _cci(high, low, close, 20).clip(-3, 3) / 3
        df["roc_10"]        = close.pct_change(10)
        df["willr_14"]      = _willr(high, low, close, 14) / 100
        stoch_k, _          = _stoch(high, low, close)
        df["stoch_k"]       = stoch_k / 100

        # ── Group C: Volatility ───────────────────────────────────────────────
        df["atr_14"]        = _atr(high, low, close, 14) / close
        df["atr_7"]         = _atr(high, low, close,  7) / close
        bb_u, bb_l, bb_w, bb_p = _bollinger(close)
        df["bb_upper"]      = (bb_u - close) / (close + 1e-9)
        df["bb_lower"]      = (close - bb_l) / (close + 1e-9)
        df["bb_width"]      = bb_w
        df["bb_pct"]        = bb_p.clip(0, 1)
        df["hist_vol_20"]   = df["log_return"].rolling(20).std() * np.sqrt(252 * 24)
        df["hist_vol_5"]    = df["log_return"].rolling(5).std()  * np.sqrt(252 * 24)

        # ── Group D: Trend ────────────────────────────────────────────────────
        e20  = _ema(close, 20)
        e50  = _ema(close, 50)
        e200 = _ema(close, 200)
        df["ema_20"]            = (close - e20)  / (close + 1e-9)
        df["ema_50"]            = (close - e50)  / (close + 1e-9)
        df["ema_200"]           = (close - e200) / (close + 1e-9)
        df["ema_cross_20_50"]   = np.sign(e20 - e50).astype(float)
        df["ema_cross_50_200"]  = np.sign(e50 - e200).astype(float)
        df["price_vs_ema200"]   = np.sign(close - e200).astype(float)
        df["higher_high"]       = (high > high.shift(1)).astype(float)
        df["lower_low"]         = (low  < low.shift(1)).astype(float)

        # ── Group E: Volume ───────────────────────────────────────────────────
        vol_ma20              = volume.rolling(20).mean()
        df["volume_ratio"]    = (volume / (vol_ma20 + 1e-9)).clip(0, 5) / 5
        df["volume_ma20"]     = np.log1p(vol_ma20 / 1e4)
        obv                   = _obv(close, volume)
        df["obv_norm"]        = (obv - obv.rolling(20).mean()) / (obv.rolling(20).std() + 1e-9)
        df["obv_norm"]        = df["obv_norm"].clip(-3, 3) / 3
        # VWAP (rolling 24-bar proxy)
        typical_price         = (high + low + close) / 3
        vwap                  = (typical_price * volume).rolling(24).sum() / (volume.rolling(24).sum() + 1e-9)
        df["vwap_dist"]       = (close - vwap) / (close + 1e-9)

        # ── Group F: Session ──────────────────────────────────────────────────
        hour                  = df.index.hour
        dow                   = df.index.dayofweek
        df["hour_sin"]        = np.sin(2 * np.pi * hour / 24)
        df["hour_cos"]        = np.cos(2 * np.pi * hour / 24)
        df["day_sin"]         = np.sin(2 * np.pi * dow  / 7)
        df["day_cos"]         = np.cos(2 * np.pi * dow  / 7)
        df["is_london"]       = ((hour >= 7)  & (hour < 16)).astype(float)
        df["is_ny"]           = ((hour >= 13) & (hour < 21)).astype(float)

        # ── Group G: Multi-timeframe ──────────────────────────────────────────
        if df_h4 is not None:
            h4 = df_h4.copy().sort_index()
            if h4.index.tzinfo is None:
                h4.index = h4.index.tz_localize("UTC")
            h4["rsi"]   = _rsi(h4["close"], 14) / 100
            macd_h4, _, _ = _macd(h4["close"])
            h4["macd"]  = macd_h4 / (h4["close"] + 1e-9)
            h4["trend"] = np.sign(h4["close"] - _ema(h4["close"], 20)).astype(float)
            h4["atr"]   = _atr(h4["high"], h4["low"], h4["close"], 14) / h4["close"]
            
            # PREVENT LOOKAHEAD BIAS: Shift H4 data forward by 1 period (4 hours).
            # Resampled H4 bars are stamped at the START of the period (e.g. 00:00).
            # The data inside it finishes forming at 04:00. It must only be visible at 04:00.
            h4 = h4.shift(1)
            
            # Forward-fill H4 values onto H1 index
            df["h4_rsi"]   = h4["rsi"].reindex(df.index, method="ffill")
            df["h4_macd"]  = h4["macd"].reindex(df.index, method="ffill")
            df["h4_trend"] = h4["trend"].reindex(df.index, method="ffill")
            df["h4_atr"]   = h4["atr"].reindex(df.index, method="ffill")
        else:
            df["h4_rsi"]   = df["rsi_14"]
            df["h4_macd"]  = df["macd"]
            df["h4_trend"] = df["ema_cross_20_50"]
            df["h4_atr"]   = df["atr_14"]

        if df_d is not None:
            d = df_d.copy().sort_index()
            if d.index.tzinfo is None:
                d.index = d.index.tz_localize("UTC")
            d["rsi"]   = _rsi(d["close"], 14) / 100
            d["trend"] = np.sign(d["close"] - _ema(d["close"], 50)).astype(float)
            
            # PREVENT LOOKAHEAD BIAS: Shift Daily data forward by 1 period (24 hours).
            d = d.shift(1)
            
            df["d_rsi"]   = d["rsi"].reindex(df.index, method="ffill")
            df["d_trend"] = d["trend"].reindex(df.index, method="ffill")
        else:
            df["d_rsi"]   = df["rsi_14"]
            df["d_trend"] = df["ema_cross_50_200"]

        # ── Group H: Gold Macro Proxies ───────────────────────────────────────
        # Baseline proxies (used when LSEG cache is absent)
        df["dxy_proxy"]        = -df["log_return"].rolling(24).sum()
        df["real_yield_proxy"] = df["hist_vol_20"].rolling(5).mean() - df["hist_vol_20"].rolling(20).mean()
        vol_zscore             = (df["hist_vol_20"] - df["hist_vol_20"].rolling(252).mean()) \
                                 / (df["hist_vol_20"].rolling(252).std() + 1e-9)
        df["vix_proxy"]        = vol_zscore.clip(-3, 3) / 3
        df["gold_seasonality"] = df.index.month.map(GOLD_SEASONAL).astype(float)
        df["roll_day"]         = pd.Series(25 - df.index.day, index=df.index).clip(-5, 25) / 25

        # LSEG overlay — replace proxy values with real macro data when cached
        df = _overlay_lseg_macro(df)

        # ── Group I: Sentiment (zeros until NLP pipeline runs) ────────────────
        for col in ["sentiment_score", "sentiment_novelty", "sentiment_momentum",
                    "news_volume", "event_flag", "minutes_to_news"]:
            if col not in df.columns:
                df[col] = 0.0

        # LSEG overlay — replace zero sentiment with Reuters scored values when cached
        df = _overlay_lseg_sentiment(df)

        # Add Time to News feature (normalized)
        df = _add_minutes_to_news(df)

        # ── Group J: Regime (Unsupervised GMM) ──────────────────────────────────────
        # Fit a Gaussian Mixture Model to identify 3 distinct market regimes
        # based on historical volatility and trend strength.
        # The fitted model is cached to disk so regime labels are stable across
        # retraining runs (GMM label permutation is otherwise non-deterministic).
        from sklearn.mixture import GaussianMixture

        GMM_CACHE = FEATURES_DIR / "gmm_regime_v2.pkl"

        # Prepare features for GMM (forward-fill any NaNs in inputs first)
        regime_feats = df[["hist_vol_20", "adx_14"]].ffill().bfill().values

        try:
            if not refit_gmm and GMM_CACHE.exists():
                with open(GMM_CACHE, "rb") as _f:
                    gmm = pickle.load(_f)
            else:
                # LOOKAHEAD FIX: fit on the training split only (first 80% of data),
                # mirroring the exact chronological split in models/train.py.
                # Prevents val/test regime distributions from leaking into features.
                train_end_idx = int(len(regime_feats) * 0.80)
                train_feats   = regime_feats[:train_end_idx]
                print(f"  GMM fitted on first {train_end_idx:,} bars (80% training split) → {GMM_CACHE}")

                gmm = GaussianMixture(n_components=3, random_state=42, n_init=3)
                gmm.fit(train_feats)
                with open(GMM_CACHE, "wb") as _f:
                    pickle.dump(gmm, _f)

            regime_probs = gmm.predict_proba(regime_feats)

            # Ensure stable regime labels by sorting components by their mean volatility
            # hist_vol_20 is feature index 0. This guarantees:
            # Regime 0 = Low Vol, Regime 1 = Med Vol, Regime 2 = High Vol
            order = np.argsort(gmm.means_[:, 0])
            df["hmm_regime_0"] = regime_probs[:, order[0]]
            df["hmm_regime_1"] = regime_probs[:, order[1]]
            df["hmm_regime_2"] = regime_probs[:, order[2]]
        except Exception as e:
            print(f"  ⚠ GMM regime fitting failed ({e}) — falling back to 1/3")
            df["hmm_regime_0"] = 1/3
            df["hmm_regime_1"] = 1/3
            df["hmm_regime_2"] = 1/3

        # Trend strength: ADX-based (0=ranging, 1=strong trend)
        df["trend_strength"]   = df["adx_14"].clip(0, 1)

        # ── Final cleanup ─────────────────────────────────────────────────────
        df = df.replace([np.inf, -np.inf], np.nan)
        df = df.ffill().bfill()
        df = df.dropna(subset=self.OBS_COLUMNS[:20])  # Drop only if core features missing

        return df

    def to_obs_array(self, df: pd.DataFrame) -> np.ndarray:
        """Extract the 65-feature obs matrix. Shape: (n_bars, 65)."""
        missing = [c for c in self.OBS_COLUMNS if c not in df.columns]
        if missing:
            raise ValueError(f"Missing feature columns: {missing}")
        X = df[self.OBS_COLUMNS].astype('float64').values.astype(np.float32)
        X = np.nan_to_num(X, nan=0.0, posinf=1.0, neginf=-1.0)
        return X

    def save(self, df: pd.DataFrame, name: str = "XAUUSD_H1_features"):
        out = FEATURES_DIR / f"{name}.parquet"
        df.to_parquet(out)
        print(f"  ✅ Features saved → {out}  ({len(df):,} bars × {len(self.OBS_COLUMNS)} features)")
        return out

    def load(self, name: str = "XAUUSD_H1_features") -> pd.DataFrame:
        path = FEATURES_DIR / f"{name}.parquet"
        if not path.exists():
            raise FileNotFoundError(f"Features not found: {path}  Run: python data/features.py")
        return pd.read_parquet(path)


# ── CLI ───────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument("--h1",   default=None, help="Path to H1 parquet file")
    parser.add_argument("--h4",   default=None, help="Path to H4 parquet file (optional)")
    parser.add_argument("--d",    default=None, help="Path to Daily parquet file (optional)")
    parser.add_argument("--out",  default="XAUUSD_H1_features", help="Output name")
    parser.add_argument("--auto", action="store_true",
                        help="Auto-find latest parquet files in data/raw/")
    parser.add_argument("--refit-gmm", action="store_true",
                        help="Force refit the GMM regime model (discard cached gmm_regime_v2.pkl)")
    args = parser.parse_args()

    # Auto-discover parquet files (prefer stitched hybrid data, then fallback to others)
    if args.auto or not args.h1:
        def get_best_file(tf):
            # 1. Prefer stitched hybrid data
            stitched = list(RAW_DIR.glob(f"stitched_*_{tf}_hybrid.parquet"))
            if stitched:
                return str(stitched[0])
            # 2. Fall back to largest available parquet (LSEG or Dukascopy)
            files = list(RAW_DIR.glob(f"*XAUUSD_{tf}_*.parquet"))
            if not files:
                return None
            return str(max(files, key=lambda f: (f.stat().st_size, f.name)))

        args.h1 = get_best_file("H1")
        args.h4 = get_best_file("H4")
        args.d  = get_best_file("D")
        
        if not args.h1:
            print("No H1 data found. Run: python data/download.py first")
            raise SystemExit(1)

    print(f"Loading H1 : {args.h1}")
    df_h1 = pd.read_parquet(args.h1)

    df_h4, df_d = None, None
    if args.h4:
        print(f"Loading H4 : {args.h4}")
        df_h4 = pd.read_parquet(args.h4)
    if args.d:
        print(f"Loading D  : {args.d}")
        df_d  = pd.read_parquet(args.d)

    print(f"\nBuilding features for {len(df_h1):,} H1 bars...")
    pipe   = FeaturePipeline()
    df_out = pipe.build(df_h1, df_h4=df_h4, df_d=df_d, refit_gmm=args.refit_gmm)
    pipe.save(df_out, name=args.out)

    # Quick stats
    X = pipe.to_obs_array(df_out)
    print(f"  Obs array shape : {X.shape}")
    print(f"  NaN count       : {np.isnan(X).sum()}")
    print("  Feature ranges:")
    for i, col in enumerate(pipe.OBS_COLUMNS[:10]):
        print(f"    {col:<25} min={X[:,i].min():>8.4f}  max={X[:,i].max():>8.4f}  mean={X[:,i].mean():>8.4f}")
    print(f"    ... ({OBS_DIM - 10} more features)")

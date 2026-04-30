"""
HMM Regime Detector — XAUUSD Market State Classification
===========================================================
Fits a 3-state Hidden Markov Model on price features to classify
the current market regime. Replaces placeholder features 62-64.

States:
  0 = TRENDING   — directional move, momentum building, ride with trend
  1 = RANGING    — oscillating, mean-revert, fade extremes
  2 = VOLATILE   — high uncertainty, reduce size or sit flat

Feature inputs to HMM:
  - Rolling 20-bar return (signed)
  - Rolling 20-bar return variance (unsigned)
  - ATR ratio (current ATR / 50-bar median ATR)
  - Return autocorrelation at lag-1 (positive = trending, negative = mean-reverting)
  - Bollinger Band %B (position within bands)

Usage:
  from data.regime import RegimeDetector
  detector = RegimeDetector()
  detector.fit(df_features)           # call once on training data
  state, probs = detector.predict(df_features.iloc[-1])
  # state: 0=trending, 1=ranging, 2=volatile
  # probs: shape (3,) probability of each state
"""

import logging
import os
import pickle
import sys
import warnings
warnings.filterwarnings("ignore")
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from pathlib import Path
from typing  import Optional, Tuple

import numpy  as np
import pandas as pd

log = logging.getLogger("regime")

MODELS_DIR   = Path(__file__).parent.parent / "models"
REGIME_PATH  = MODELS_DIR / "regime_hmm.pkl"

# ── Optional hmmlearn import ──────────────────────────────────────────────────
try:
    from hmmlearn.hmm import GaussianHMM
    _HMM_OK = True
except ImportError:
    _HMM_OK = False
    log.warning("hmmlearn not installed — install: pip install hmmlearn")


# ════════════════════════════════════════════════════════════════════════════════
# REGIME FEATURES — 5 inputs to HMM
# ════════════════════════════════════════════════════════════════════════════════

def build_regime_inputs(df: pd.DataFrame) -> np.ndarray:
    """
    Build 5-feature matrix for HMM from a features dataframe.
    Requires columns: close, atr_14  (as in FeaturePipeline output)

    Returns np.ndarray shape (n_bars, 5)
    """
    close = df["close"].values.astype(float)
    n     = len(close)
    W     = 20   # rolling window

    # 1. Rolling 20-bar log return
    log_ret = np.zeros(n)
    for i in range(W, n):
        log_ret[i] = np.log(close[i] / close[i - W] + 1e-10)

    # 2. Rolling 20-bar return variance (volatility)
    ret_1  = np.diff(np.log(close + 1e-10), prepend=np.log(close[0]))
    vol    = pd.Series(ret_1).rolling(W, min_periods=1).std().fillna(0).values

    # 3. ATR ratio: current ATR / 50-bar median ATR
    if "atr_14" in df.columns:
        atr_raw = df["atr_14"].values.astype(float) * close   # un-normalise
    else:
        atr_raw = vol * close   # fallback

    atr_median = pd.Series(atr_raw).rolling(50, min_periods=5).median().fillna(atr_raw.mean()).values
    atr_ratio  = np.where(atr_median > 0, atr_raw / (atr_median + 1e-10), 1.0)

    # 4. Return autocorrelation lag-1 (positive = trending, negative = mean-reverting)
    autocorr = np.zeros(n)
    for i in range(W + 1, n):
        window = ret_1[i - W:i]
        if len(window) > 4:
            cov = np.cov(window[:-1], window[1:])
            var = np.var(window[:-1])
            autocorr[i] = float(cov[0, 1] / (var + 1e-10)) if var > 1e-12 else 0.0

    # 5. Bollinger Band %B — position within 20-bar bands
    mid  = pd.Series(close).rolling(W, min_periods=1).mean().values
    std  = pd.Series(close).rolling(W, min_periods=1).std().fillna(1).values
    bb_b = np.where(std > 0, (close - (mid - 2 * std)) / (4 * std + 1e-10), 0.5)
    bb_b = np.clip(bb_b, 0.0, 1.0)

    X = np.column_stack([log_ret, vol, atr_ratio, autocorr, bb_b])
    return np.nan_to_num(X, nan=0.0, posinf=1.0, neginf=-1.0)


# ════════════════════════════════════════════════════════════════════════════════
# REGIME DETECTOR
# ════════════════════════════════════════════════════════════════════════════════

class RegimeDetector:
    """
    3-state Gaussian HMM for market regime detection.

    After fitting, state labels are assigned semantically:
      - TRENDING (0):  high autocorrelation, moderate volatility
      - RANGING  (1):  low autocorrelation, low-moderate ATR ratio
      - VOLATILE (2):  high ATR ratio, high variance, low autocorrelation

    The detector produces 3 features for the obs vector (indices 62-64):
      hmm_regime_0 — probability of TRENDING state
      hmm_regime_1 — probability of RANGING state
      hmm_regime_2 — probability of VOLATILE state

    Using probabilities (not one-hot) lets the agent respond to ambiguous
    regime transitions rather than hard state switches.
    """

    N_STATES = 3

    def __init__(self):
        self.model: Optional[object] = None
        self._state_map: dict = {0: 0, 1: 1, 2: 2}   # hmm_state → semantic_state
        self._is_fitted = False

        # Try loading pre-fitted model
        if REGIME_PATH.exists():
            self._load()

    def _label_states(self, X: np.ndarray):
        """
        After fitting, map HMM states 0/1/2 to TRENDING/RANGING/VOLATILE
        by examining the learned means.

        autocorr is feature[:,3], atr_ratio is feature[:,2], vol is feature[:,1]
        """
        means = self.model.means_   # shape (n_states, 5)
        # [log_ret, vol, atr_ratio, autocorr, bb_b]
        autocorr_means = means[:, 3]
        atr_means      = means[:, 2]
        vol_means      = means[:, 1]

        # VOLATILE  = highest ATR ratio
        volatile_state = int(np.argmax(atr_means))
        # TRENDING  = highest autocorrelation (excluding volatile)
        remaining = [i for i in range(self.N_STATES) if i != volatile_state]
        trending_state = remaining[int(np.argmax(autocorr_means[remaining]))]
        # RANGING   = the last one
        ranging_state  = [i for i in range(self.N_STATES)
                          if i != volatile_state and i != trending_state][0]

        self._state_map = {
            trending_state: 0,   # → TRENDING
            ranging_state:  1,   # → RANGING
            volatile_state: 2,   # → VOLATILE
        }
        log.info(f"Regime states mapped: "
                 f"TRENDING={trending_state}  "
                 f"RANGING={ranging_state}  "
                 f"VOLATILE={volatile_state}")

    def fit(self, df: pd.DataFrame) -> "RegimeDetector":
        """Fit HMM on historical features dataframe."""
        if not _HMM_OK:
            log.error("hmmlearn required — pip install hmmlearn")
            return self

        log.info(f"Fitting 3-state HMM on {len(df):,} bars...")
        X = build_regime_inputs(df)

        model = GaussianHMM(
            n_components   = self.N_STATES,
            covariance_type= "full",
            n_iter         = 200,
            tol            = 1e-4,
            random_state    = 42,
        )
        model.fit(X)
        self.model      = model
        self._is_fitted = True

        self._label_states(X)
        self._save()
        log.info("HMM fitted and saved")
        return self

    def predict_bar(self, df: pd.DataFrame,
                     lookback: int = 100) -> Tuple[int, np.ndarray]:
        """
        Predict regime for the latest bar.
        Uses the last `lookback` bars to warm up the HMM state.

        Returns:
          state: int (0=TRENDING, 1=RANGING, 2=VOLATILE)
          probs: np.ndarray shape (3,) — probability of each semantic state
        """
        if not self._is_fitted:
            return 1, np.array([0.0, 1.0, 0.0], dtype=np.float32)  # default RANGING

        window = df.iloc[-lookback:] if len(df) >= lookback else df
        X      = build_regime_inputs(window)

        # Posterior state probabilities
        raw_probs = self.model.predict_proba(X)   # shape (n_bars, n_states)
        last_probs_raw = raw_probs[-1]             # (n_states,)

        # Remap to semantic states
        semantic_probs = np.zeros(self.N_STATES, dtype=np.float32)
        for raw_s, sem_s in self._state_map.items():
            semantic_probs[sem_s] = last_probs_raw[raw_s]

        state = int(np.argmax(semantic_probs))
        return state, semantic_probs

    def predict_series(self, df: pd.DataFrame) -> pd.DataFrame:
        """
        Predict regime for every bar in df.
        Returns dataframe with columns: hmm_regime_0, hmm_regime_1, hmm_regime_2
        """
        if not self._is_fitted:
            n = len(df)
            return pd.DataFrame({
                "hmm_regime_0": np.zeros(n),
                "hmm_regime_1": np.ones(n),
                "hmm_regime_2": np.zeros(n),
            }, index=df.index)

        X         = build_regime_inputs(df)
        raw_probs = self.model.predict_proba(X)   # (n, 3)

        # Remap columns
        sem_probs = np.zeros_like(raw_probs)
        for raw_s, sem_s in self._state_map.items():
            sem_probs[:, sem_s] = raw_probs[:, raw_s]

        return pd.DataFrame({
            "hmm_regime_0": sem_probs[:, 0].astype(np.float32),
            "hmm_regime_1": sem_probs[:, 1].astype(np.float32),
            "hmm_regime_2": sem_probs[:, 2].astype(np.float32),
        }, index=df.index)

    def _save(self):
        MODELS_DIR.mkdir(parents=True, exist_ok=True)
        with open(REGIME_PATH, "wb") as f:
            pickle.dump({"model": self.model, "state_map": self._state_map}, f)
        log.info(f"HMM saved → {REGIME_PATH}")

    def _load(self):
        try:
            with open(REGIME_PATH, "rb") as f:
                data = pickle.load(f)
            self.model      = data["model"]
            self._state_map = data["state_map"]
            self._is_fitted = True
            log.info(f"HMM loaded from {REGIME_PATH}")
        except Exception as e:
            log.warning(f"HMM load failed: {e}")

    def describe(self, df: pd.DataFrame) -> str:
        """Human-readable regime summary for the latest bar."""
        state, probs = self.predict_bar(df)
        names = ["TRENDING", "RANGING", "VOLATILE"]
        icons = ["📈", "↔️ ", "⚡"]
        lines = [f"Current regime: {icons[state]} {names[state]}"]
        for i, (name, p) in enumerate(zip(names, probs)):
            bar   = "█" * int(p * 20)
            lines.append(f"  {icons[i]} {name:<10} {p:.3f}  {bar}")
        return "\n".join(lines)


# ════════════════════════════════════════════════════════════════════════════════
# Convenience: fit + save from the command line
# ════════════════════════════════════════════════════════════════════════════════

if __name__ == "__main__":
    import argparse
    from data.features import FeaturePipeline

    parser = argparse.ArgumentParser(description="Fit HMM regime detector")
    parser.add_argument("--fit",     action="store_true")
    parser.add_argument("--status",  action="store_true")
    args = parser.parse_args()

    if args.fit or args.status:
        logging.basicConfig(level=logging.INFO,
                            format="%(asctime)s  %(levelname)-8s  %(message)s")
        pipe = FeaturePipeline()
        try:
            df = pipe.load("XAUUSD_H1_features")
            print(f"Loaded {len(df):,} bars for HMM fitting")
        except FileNotFoundError:
            print("Feature cache not found — run: python data/features.py --auto")
            sys.exit(1)

        detector = RegimeDetector()
        if args.fit:
            detector.fit(df)
            print("\nFitted on full history. Current state:")
        print("\n" + detector.describe(df))
    else:
        import argparse
        print("Usage: python data/regime.py --fit     (fit HMM on historical data)")
        print("       python data/regime.py --status  (show current regime)")

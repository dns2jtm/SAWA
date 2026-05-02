"""
config/settings.py — Unified settings
"""

import os
from pathlib import Path
from dotenv  import load_dotenv

load_dotenv()

# ── Paths ─────────────────────────────────────────────────────────────────────
BASE_DIR = Path(__file__).parent.parent

# ── cTrader Open API settings (replaces MetaAPI / MT5) ────────────────────────
CTRADER = {
    "client_id":       os.getenv("CTRADER_CLIENT_ID",       ""),
    "client_secret":   os.getenv("CTRADER_CLIENT_SECRET",   ""),
    "account_id":      os.getenv("CTRADER_ACCOUNT_ID",      ""),
    "host":            os.getenv("CTRADER_HOST",            "demo.ctraderapi.com"),
    "port":            int(os.getenv("CTRADER_PORT",        "5035")),
    "access_token":    os.getenv("CTRADER_ACCESS_TOKEN",    ""),
}

# ── Live execution settings ────────────────────────────────────────────────
EXECUTION = {
    "friday_close_utc":     21,   # Flatten all positions at 21:00 UTC on Friday
    "action_threshold":     0.33, # |action| must exceed this to open/close a trade
    # cTrader credentials forwarded from CTRADER block for convenience
    "ctrader_account":      os.getenv("CTRADER_ACCOUNT_ID", ""),
}

# ── FTMO Challenge settings ────────────────────────────────────────────────────
FTMO = {
    "account_size":        100_000,
    "profit_target_pct":   0.10,
    "max_daily_loss_pct":  0.05,
    "max_total_loss_pct":  0.10,
    "personal_daily_limit":0.03,   # Conservative — 60% of FTMO limit
    "personal_total_limit":0.07,
}

# ── Active instrument / firm ───────────────────────────────────────────────────
INSTRUMENT = {
    "symbol":     "XAUUSD",
    "mt5_symbol": "XAUUSD",
    "timeframe":  "H1",
    "min_lot":    0.01,
    "pip_size":   0.01,           # XAUUSD: 1 pip = $0.01
}

# ── Data paths ────────────────────────────────────────────────────────────────
DATA = {
    "raw_dir":      BASE_DIR / "data" / "raw",
    "features_dir": BASE_DIR / "data" / "features",
    "models_dir":   BASE_DIR / "models" / "saved",
    # NOTE: actual train/val/test splits are computed dynamically in
    # models/train.py load_data() as 95/2.5/2.5 by bar count, not by date.
    # These date strings are reference-only and are not used by the pipeline.
    "train_start":  "2004-01-01",
    "train_end":    "2023-12-31",
    "val_start":    "2024-01-01",
    "val_end":      "2024-12-31",
    "test_start":   "2025-01-01",
    "test_end":     "2026-12-31",
}

# ── RL training ───────────────────────────────────────────────────────────────
import torch as _torch

# Auto-scale for GPU vs CPU:
#   A100 80GB : n_envs=32, batch=4096 → ~200k fps
#   RTX 4090  : n_envs=16, batch=2048 → ~100k fps
#   Mac CPU   : n_envs=4,  batch=512  → ~8k fps
_cuda = _torch.cuda.is_available()
_gpu_name = _torch.cuda.get_device_name(0).lower() if _cuda else ""
_is_a100  = "a100" in _gpu_name or "h100" in _gpu_name
_is_4090  = "4090" in _gpu_name or "3090" in _gpu_name or "a40" in _gpu_name

if _is_a100:
    _n_envs, _batch = 32, 4096
elif _is_4090:
    _n_envs, _batch = 16, 2048
elif _cuda:
    _n_envs, _batch = 8, 1024
else:
    _n_envs, _batch = 4, 512   # CPU (local Mac)

RL = {
    "net_arch": [256, 256],
    "n_epochs": 10,
    "device": "auto",

    "algorithm":       "PPO",
    "total_timesteps": 15_000_000,
    "n_envs":          _n_envs,
    "obs_dim":         77,
    "learning_rate":   3e-4,
    "n_steps":         2048,
    "batch_size":      _batch,
    "gamma":           0.99,
    "gae_lambda":      0.95,
    "clip_range":      0.2,
    "ent_coef":        0.01,
    "vf_coef":         0.5,
    "max_grad_norm":   0.5,
    "seed":            42,
}


# ── Sentiment pipeline settings ────────────────────────────────────────────────
# DeepSeek removed — sentiment uses lexicon + GDELT + RSS only (no API key required)
SENTIMENT = {
    "refresh_interval_sec": 900,      # 15 minutes
    "obs_indices":          (55, 61), # Feature positions in static obs (after Groups A-H = 55 cols)
    "lexicon_fallback":     True,
    "gdelt_enabled":        True,
    "rss_enabled":          True,
    "window_hours":         24,
    "decay_half_life_min":  30,
}

# ── HMM Regime detector settings ──────────────────────────────────────────────
REGIME = {
    "n_states":       3,
    "obs_indices":    (61, 65),
    "lookback_bars":  100,
    "refit_interval": "monthly",
}

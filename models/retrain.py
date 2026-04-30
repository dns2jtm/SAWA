"""
Automated Monthly Retraining — FTMO XAUUSD
============================================
Runs on a schedule (cron or manual) to keep the model current.
Gold's regime shifts over months — a model trained on 2024 data
will degrade by Q2 2025 without periodic retraining.

Schedule:
  - Retrain on a rolling 18-month window of H1 data
  - Run walk-forward backtest gate after every retrain
  - Only replace production model if gate passes
  - Archive old models with timestamp

Cron setup (run monthly on the 1st at 02:00 UTC):
  0 2 1 * * cd /path/to/ftmo-eurgbp && python models/retrain.py >> logs/retrain.log 2>&1

Usage:
  python models/retrain.py                 # Full retrain + gate
  python models/retrain.py --dry-run       # Simulate without replacing model
  python models/retrain.py --months 12     # Use 12-month window instead of 18
  python models/retrain.py --skip-gate     # Skip gate (testing only)
"""

import argparse
import logging
import shutil
import sys
import warnings
warnings.filterwarnings("ignore")

from datetime import datetime, timezone, timedelta
from pathlib  import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).parent.parent))

from models.train     import build_env, MODELS_DIR, DATA_DIR
from models.backtest  import run_gate
from data.features    import FeaturePipeline
from data.regime      import RegimeDetector
from config.settings  import RL

log = logging.getLogger("retrain")
logging.basicConfig(level=logging.INFO,
                    format="%(asctime)s  %(levelname)-8s  %(message)s")

ARCHIVE_DIR = MODELS_DIR / "archive"
ARCHIVE_DIR.mkdir(parents=True, exist_ok=True)


def retrain(months: int = 18, dry_run: bool = False,
            skip_gate: bool = False) -> bool:
    """
    Full retrain pipeline.
    Returns True if new model was deployed, False otherwise.
    """
    stamp = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M")
    log.info(f"{'='*55}")
    log.info(f"  MONTHLY RETRAIN  |  window={months}mo  |  {stamp}")
    log.info(f"{'='*55}")

    # ── 1. Load features, slice to rolling window ─────────────────────────────
    pipe = FeaturePipeline()
    try:
        df = pipe.load("XAUUSD_H1_features")
    except FileNotFoundError:
        log.error("Feature cache not found — run: python data/features.py --auto")
        return False

    cutoff = pd.Timestamp.now(tz="UTC") - pd.DateOffset(months=months)
    df_window = df[df.index >= cutoff]
    log.info(f"Training window: {df_window.index[0].date()} → "
             f"{df_window.index[-1].date()}  ({len(df_window):,} bars)")

    if len(df_window) < 5000:
        log.error(f"Too few bars ({len(df_window)}) — need ≥5000")
        return False

    # ── 2. Refit HMM regime detector on new window ───────────────────────────
    log.info("Refitting HMM regime detector...")
    detector = RegimeDetector()
    detector.fit(df_window)

    # ── 3. Retrain PPO ────────────────────────────────────────────────────────
    new_model_path = MODELS_DIR / f"ppo_xauusd_retrain_{stamp}.zip"

    try:
        from stable_baselines3 import PPO
        from stable_baselines3.common.vec_env import VecNormalize, SubprocVecEnv

        log.info("Building training environment...")
        env = build_env(df_window, n_envs=RL["n_envs"])

        log.info(f"Training PPO for {RL['total_timesteps']:,} steps...")
        model = PPO(
            "MlpPolicy",
            env,
            learning_rate = RL["learning_rate"],
            n_steps       = RL["n_steps"],
            batch_size    = RL["batch_size"],
            gamma         = RL["gamma"],
            gae_lambda    = RL["gae_lambda"],
            clip_range    = RL["clip_range"],
            ent_coef      = RL["ent_coef"],
            verbose       = 1,
            seed          = RL["seed"],
            device        = "auto",
        )
        model.learn(total_timesteps=RL["total_timesteps"],
                    progress_bar=True)
        model.save(new_model_path)
        log.info(f"Retrained model saved: {new_model_path}")

    except Exception as e:
        log.error(f"Training failed: {e}")
        return False

    # ── 4. Walk-forward gate ──────────────────────────────────────────────────
    if not skip_gate:
        log.info("Running deployment gate...")
        gate_result = run_gate(new_model_path, df_window)

        if not gate_result["passed"]:
            log.warning(f"Gate FAILED — new model NOT deployed")
            log.warning(f"Failed metrics: {gate_result.get('failed_metrics', [])}")
            # Archive the failed model for debugging
            shutil.move(str(new_model_path),
                        str(ARCHIVE_DIR / f"FAILED_{new_model_path.name}"))
            return False

        log.info("Gate PASSED — deploying new model")
    else:
        log.warning("Gate check SKIPPED — deploying anyway (testing only)")

    # ── 5. Deploy ─────────────────────────────────────────────────────────────
    if dry_run:
        log.info("DRY RUN — not replacing production model")
        shutil.move(str(new_model_path),
                    str(ARCHIVE_DIR / f"DRYRUN_{new_model_path.name}"))
        return True

    # Archive current production model
    best_path = MODELS_DIR / "best" / "best_model.zip"
    if best_path.exists():
        archived = ARCHIVE_DIR / f"best_model_{stamp}_retired.zip"
        shutil.copy(str(best_path), str(archived))
        log.info(f"Previous model archived: {archived.name}")

    # Deploy new model
    best_path.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy(str(new_model_path), str(best_path))
    log.info(f"✅ New model deployed to {best_path}")

    # Also archive the new model by timestamp
    shutil.move(str(new_model_path),
                str(ARCHIVE_DIR / new_model_path.name))

    log.info(f"Retrain complete | stamp={stamp}")
    return True


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Monthly model retraining")
    parser.add_argument("--months",    type=int, default=18,
                        help="Rolling window length in months (default 18)")
    parser.add_argument("--dry-run",   action="store_true",
                        help="Simulate without replacing production model")
    parser.add_argument("--skip-gate", action="store_true",
                        help="Skip deployment gate (testing only)")
    args = parser.parse_args()

    success = retrain(months=args.months,
                      dry_run=args.dry_run,
                      skip_gate=args.skip_gate)
    sys.exit(0 if success else 1)

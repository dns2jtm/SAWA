"""
PPO Training Script — XAUUSD FTMO RL Agent
===========================================
Trains a Proximal Policy Optimisation agent on 20 years of XAUUSD H1 data
using Stable-Baselines3. The agent learns to:
  1. Maximise profit within FTMO drawdown constraints
  2. Hit the 10% profit target within the 30-day window
  3. Avoid the daily and total drawdown limits
  4. Trade only during high-probability sessions
  5. Respect the economic calendar

Training regime:
  Phase 1 — Warm-up         (0-2M steps):   Low penalty, learn basic trading mechanics
  Phase 2 — Constraint drill (2-6M steps):  Ramp up DD penalties, teach survival
  Phase 3 — Target drill     (6-10M steps): Target reward scaled up, push for profit
  Curriculum advances automatically when mean_reward improves 3 epochs in a row

Usage:
  python models/train.py                        # full train from scratch
  python models/train.py --resume               # resume from latest checkpoint
  python models/train.py --phase 2              # start at specific curriculum phase
  python models/train.py --timesteps 5000000    # custom timestep count
  python models/train.py --eval                 # eval mode — no training
  python models/train.py --fast                 # quick smoke-test (100k steps)
"""

import argparse
import json
import os
import sys
import warnings
warnings.filterwarnings("ignore")
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from datetime import datetime
from pathlib  import Path
from typing   import Optional

import numpy  as np
import pandas as pd

# ── SB3 + Gym ─────────────────────────────────────────────────────────────────
try:
    from stable_baselines3          import PPO
    from stable_baselines3.common.callbacks  import (
        BaseCallback, EvalCallback, CheckpointCallback, CallbackList
    )
    from stable_baselines3.common.env_util   import make_vec_env
    from stable_baselines3.common.vec_env    import SubprocVecEnv, VecNormalize
    from stable_baselines3.common.monitor    import Monitor
    from stable_baselines3.common.utils      import set_random_seed
    _SB3_OK = True
except ImportError:
    _SB3_OK = False
    print("⚠ stable-baselines3 not installed. Run: pip install stable-baselines3[extra]")

import gymnasium as gym

from config.settings    import RL, FTMO, DATA, INSTRUMENT
from config.prop_firms  import get_config, ACTIVE_FIRM
from config.instruments import get_instrument, ACTIVE_INSTRUMENT
from data.features      import FeaturePipeline
from env.ftmo_env       import FTMOEnv

# ── Paths ─────────────────────────────────────────────────────────────────────
MODELS_DIR = Path(__file__).parent
LOGS_DIR   = MODELS_DIR / "logs"
CKPT_DIR   = MODELS_DIR / "checkpoints"
BEST_DIR   = MODELS_DIR / "best"
EVAL_DIR   = MODELS_DIR / "eval"

for d in (LOGS_DIR, CKPT_DIR, BEST_DIR, EVAL_DIR):
    d.mkdir(parents=True, exist_ok=True)

RUN_ID = datetime.now().strftime("%Y%m%d_%H%M%S")

INST = get_instrument(ACTIVE_INSTRUMENT)
CFG  = get_config(ACTIVE_FIRM)


# ════════════════════════════════════════════════════════════════════════════════
# CURRICULUM SCHEDULE
# ════════════════════════════════════════════════════════════════════════════════

CURRICULUM = {
    1: {
        "name":             "warm_up",
        "description":      "Learn buy/sell/hold mechanics with mild DD cost signal",
        "step_end":         3_000_000,   # Phase 1 runs steps 0 – 3M
        "lambda_daily_dd":  0.020,       # Raised: 0.001→0.020 so penalty is meaningful
        "lambda_total_dd":  0.030,
        "lambda_target":    0.50,
        "learning_rate":    3e-4,
        "ent_coef":         0.02,        # High entropy — encourage exploration
        "clip_range":       0.2,
    },
    2: {
        "name":             "constraint_drill",
        "description":      "Enforce FTMO drawdown rules with strong penalty",
        "step_end":         7_000_000,   # Phase 2 runs steps 3M – 7M
        "lambda_daily_dd":  0.080,       # 4× Phase-1 — daily breach is seriously costly
        "lambda_total_dd":  0.100,
        "lambda_target":    0.50,
        "learning_rate":    1e-4,
        "ent_coef":         0.01,
        "clip_range":       0.15,
    },
    3: {
        "name":             "target_drill",
        "description":      "Drive toward profit target; maintain discipline",
        "step_end":         10_000_000,  # Phase 3 runs steps 7M – 10M
        "lambda_daily_dd":  0.150,       # Hold the discipline learned in Phase 2
        "lambda_total_dd":  0.150,
        "lambda_target":    1.00,        # Strong pull toward 10% target
        "learning_rate":    5e-5,
        "ent_coef":         0.005,       # Lower entropy — exploit learned policy
        "clip_range":       0.1,
    },
}


# ════════════════════════════════════════════════════════════════════════════════
# DATA LOADING
# ════════════════════════════════════════════════════════════════════════════════

def load_data(split: str = "train") -> pd.DataFrame:
    """Load pre-built feature dataframe for given split.

    Splits are chronological (no leakage):
      train — oldest 80% of available bars
      val   — next 10% (used for EvalCallback during training)
      test  — most recent 10% (held out; never seen during training)

    Previously all three splits mapped to the identical full date range,
    meaning validation and test were identical to train — true out-of-sample
    performance was unmeasurable.
    """
    pipe = FeaturePipeline()
    feature_name = "XAUUSD_H1_features"
    try:
        df_full = pipe.load(feature_name)
    except FileNotFoundError:
        print("Feature file not found. Run: python data/features.py --auto")
        sys.exit(1)

    # Ensure timezone-aware index
    if df_full.index.tzinfo is None:
        df_full.index = df_full.index.tz_localize("UTC")
    df_full = df_full.sort_index()

    # Chronological 80/10/10 split by bar count
    n        = len(df_full)
    i_val    = int(n * 0.80)
    i_test   = int(n * 0.90)

    splits = {
        "train": df_full.iloc[:i_val],
        "val":   df_full.iloc[i_val:i_test],
        "test":  df_full.iloc[i_test:],
    }

    df = splits[split].copy()

    if df.empty:
        raise ValueError(
            f"No data for split={split}. "
            f"Full range: {df_full.index.min().date()} → {df_full.index.max().date()} "
            f"({n:,} bars)"
        )

    print(f"  {split:<5} split: {len(df):>8,} bars  "
          f"({df.index.min().date()} → {df.index.max().date()})")
    return df


# ════════════════════════════════════════════════════════════════════════════════
# ENVIRONMENT FACTORY
# ════════════════════════════════════════════════════════════════════════════════

def make_env(df: pd.DataFrame, phase: int = 1,
             training: bool = True, seed: int = 0):
    """
    Factory function for creating a monitored FTMOEnv.
    Used by make_vec_env for parallel environments.
    """
    def _init():
        set_random_seed(seed)
        phase_cfg = CURRICULUM[phase]
        env = FTMOEnv(
            df              = df,
            firm            = ACTIVE_FIRM,
            training        = training,
            random_start    = True,  # ALWAYS random start, even for eval, to sample full val set
            use_calendar    = False,  # Historical backtesting: calendar uses datetime.now(), not bar time
        )
        env.lambda_daily_dd = phase_cfg["lambda_daily_dd"]
        env.lambda_total_dd = phase_cfg["lambda_total_dd"]
        env.lambda_target   = phase_cfg["lambda_target"]
        env = Monitor(env, filename=str(LOGS_DIR / f"monitor_{seed}_{RUN_ID}"))
        return env
    return _init


# ════════════════════════════════════════════════════════════════════════════════
# CALLBACKS
# ════════════════════════════════════════════════════════════════════════════════

class CurriculumCallback(BaseCallback):
    """
    Advances curriculum based on fixed step thresholds (not fragile monotone reward).

    Previously used patience-based advance: required 3 consecutive improvements
    in mean_reward. In practice, noisy episode rewards prevented this from ever
    firing — the agent trained exclusively on Phase-1 hyperparams for 10M steps.

    Now: curriculum advances at the step_end boundaries defined in CURRICULUM.
    Hyperparams are updated the moment the threshold is crossed.
    """
    def __init__(self, phase_start: int = 1, verbose: int = 1):
        super().__init__(verbose)
        self.phase          = phase_start
        self._ema_reward    = None          # EMA of last-100-ep mean reward
        self._ema_alpha     = 0.3           # EMA smoothing factor
        self._episode_rewards = []
        self._log_path      = LOGS_DIR / f"curriculum_{RUN_ID}.jsonl"

    def _apply_phase(self, phase: int) -> None:
        """Push new hyperparams into the env and model.

        SB3 stores learning_rate, ent_coef, and clip_range as callables
        (constant schedule functions). Assigning a raw float to clip_range
        causes TypeError: 'float' object is not callable on the next train()
        call. Wrap every scalar in a constant lambda before assigning.
        """
        phase_cfg = CURRICULUM[phase]
        try:
            self.training_env.set_attr("lambda_daily_dd", phase_cfg["lambda_daily_dd"])
            self.training_env.set_attr("lambda_total_dd", phase_cfg["lambda_total_dd"])
            self.training_env.set_attr("lambda_target",   phase_cfg["lambda_target"])
        except Exception:
            pass
        # SB3 hyperparams must be callables — wrap raw floats
        try:
            lr  = phase_cfg["learning_rate"]
            ec  = phase_cfg["ent_coef"]
            cr  = phase_cfg["clip_range"]
            self.model.learning_rate = lr if callable(lr) else (lambda v: lambda _: v)(lr)
            self.model.ent_coef      = ec
            self.model.clip_range    = cr if callable(cr) else (lambda v: lambda _: v)(cr)
        except Exception:
            pass

    def _on_step(self) -> bool:
        # Collect episode rewards from Monitor wrapper
        for info in self.locals.get("infos", []):
            if "episode" in info:
                self._episode_rewards.append(float(info["episode"]["r"]))

        # ── Check step-threshold advance ───────────────────────────────────
        if self.phase < 3:
            next_phase    = self.phase + 1
            step_boundary = CURRICULUM[self.phase]["step_end"]
            if self.num_timesteps >= step_boundary:
                self.phase = next_phase
                self._apply_phase(self.phase)
                phase_cfg = CURRICULUM[self.phase]
                print(f"\n  🎓 CURRICULUM ADVANCE → Phase {self.phase}: "
                      f"{phase_cfg['name']} — {phase_cfg['description']}\n")
                print(f"     lambda_daily_dd={phase_cfg['lambda_daily_dd']}  "
                      f"lambda_total_dd={phase_cfg['lambda_total_dd']}  "
                      f"lr={phase_cfg['learning_rate']}\n")

        # ── Log every 50k steps ───────────────────────────────────────────────
        if self.n_calls % 50_000 == 0 and self._episode_rewards:
            mean_r = float(np.mean(self._episode_rewards[-100:]))
            # EMA-smooth for stable monitoring
            if self._ema_reward is None:
                self._ema_reward = mean_r
            else:
                self._ema_reward = self._ema_alpha * mean_r + (1 - self._ema_alpha) * self._ema_reward

            log_entry = {
                "step":        self.num_timesteps,
                "phase":       self.phase,
                "mean_reward": round(mean_r, 4),
                "ema_reward":  round(self._ema_reward, 4),
                "n_episodes":  len(self._episode_rewards),
                "timestamp":   datetime.now().isoformat(),
            }
            with open(self._log_path, "a") as f:
                f.write(json.dumps(log_entry) + "\n")

            if self.verbose >= 1:
                print(f"  [Step {self.num_timesteps:>10,}] Phase {self.phase} | "
                      f"Mean reward: {mean_r:>8.2f} | EMA: {self._ema_reward:>8.2f} | "
                      f"Episodes: {len(self._episode_rewards):>6,}")

        return True


class FTMOMetricsCallback(BaseCallback):
    """
    Tracks FTMO-specific metrics beyond generic reward:
      - Challenge pass rate (hit 10% target without DD breach)
      - Daily DD violation rate
      - Total DD violation rate
      - Avg days to target
      - Active episode fraction
      - Sharpe ratio of episode returns
    """
    def __init__(self, eval_freq: int = 100_000, verbose: int = 1):
        super().__init__(verbose)
        self.eval_freq = eval_freq
        self._episodes = []
        self._log_path = LOGS_DIR / f"ftmo_metrics_{RUN_ID}.jsonl"

    def _metric(self, info, key, default=0.0):
        val = info.get(key, default)
        try:
            return float(val)
        except Exception:
            return default

    def _on_step(self) -> bool:
        for info in self.locals.get("infos", []):
            if "episode" in info:
                ep = {
                    "reward": self._metric(info["episode"], "r", 0.0),
                    "length": self._metric(info["episode"], "l", 0.0),
                    "passed": bool(info.get("challenge_passed", False)),
                    "daily_breach": bool(info.get("daily_dd_breach", False)),
                    "total_breach": bool(info.get("total_dd_breach", False)),
                    "final_pnl_pct": self._metric(info, "final_pnl_pct", 0.0),
                    "n_trades": self._metric(info, "n_trades", 0.0),
                    "trading_days": self._metric(info, "trading_days", 0.0),
                }
                self._episodes.append(ep)

        if self.n_calls % self.eval_freq == 0 and len(self._episodes) >= 10:
            recent = self._episodes[-200:]
            n = len(recent)

            pass_rate = sum(bool(e["passed"]) for e in recent) / n
            daily_breach = sum(bool(e["daily_breach"]) for e in recent) / n
            total_breach = sum(bool(e["total_breach"]) for e in recent) / n

            pnl_values = np.array(
                [float(e.get("final_pnl_pct", 0.0) or 0.0) for e in recent],
                dtype=float,
            )
            trade_values = np.array(
                [float(e.get("n_trades", 0.0) or 0.0) for e in recent],
                dtype=float,
            )
            days_values = np.array(
                [float(e.get("trading_days", 0.0) or 0.0) for e in recent],
                dtype=float,
            )

            avg_pnl = float(np.mean(pnl_values)) if len(pnl_values) else 0.0
            avg_trades = float(np.mean(trade_values)) if len(trade_values) else 0.0
            avg_days = float(np.mean(days_values)) if len(days_values) else 0.0
            active_episode_fraction = float(np.mean(trade_values > 0)) if len(trade_values) else 0.0

            sharpe_base = pnl_values if np.any(np.abs(pnl_values) > 1e-12) else np.array([], dtype=float)
            if len(sharpe_base) < 5 or float(np.std(sharpe_base)) < 1e-6 or avg_trades < 0.5:
                sharpe = 0.0
            else:
                sharpe = float(np.clip(
                    (np.mean(sharpe_base) / np.std(sharpe_base)) * np.sqrt(252), -10.0, 10.0
                ))

            metrics = {
                "step": self.num_timesteps,
                "pass_rate": round(pass_rate, 3),
                "daily_breach": round(daily_breach, 3),
                "total_breach": round(total_breach, 3),
                "avg_pnl_pct": round(avg_pnl, 4),
                "avg_trades": round(avg_trades, 1),
                "avg_days": round(avg_days, 1),
                "active_episode_fraction": round(active_episode_fraction, 3),
                "sharpe": round(float(sharpe), 3),
                "n_episodes": n,
            }

            with open(self._log_path, "a") as f:
                f.write(json.dumps(metrics) + "\n")

            if self.verbose >= 1:
                target_pct = FTMO["profit_target_pct"] * 100
                print(f"  ┌─ FTMO Metrics ──────────────────────────────")
                print(f"  │  Pass rate    : {pass_rate:.1%}  (target: {target_pct:.0f}% profit without DD breach)")
                print(f"  │  Daily breach : {daily_breach:.1%}")
                print(f"  │  Total breach : {total_breach:.1%}")
                print(f"  │  Avg PnL      : {avg_pnl:+.2%}")
                print(f"  │  Avg trades   : {avg_trades:.0f}")
                print(f"  │  Avg days     : {avg_days:.1f}")
                print(f"  │  Active ep.   : {active_episode_fraction:.1%}")
                print(f"  │  Sharpe       : {sharpe:.2f}")
                print(f"  └─────────────────────────────────────────────")

        return True

# ════════════════════════════════════════════════════════════════════════════════
# MODEL BUILDER
# ════════════════════════════════════════════════════════════════════════════════

def build_model(env, phase: int = 1,
                resume_path: Optional[Path] = None) -> "PPO":
    """Build or resume a PPO model."""
    phase_cfg = CURRICULUM[phase]

    if resume_path and resume_path.exists():
        print(f"  Resuming from {resume_path}")
        model = PPO.load(resume_path, env=env, device=RL["device"])
        # PPO.load() restores clip_range / lr as raw floats from the zip.
        # SB3 expects callables — wrap them before the first train() call.
        lr = phase_cfg["learning_rate"]
        cr = phase_cfg["clip_range"]
        model.learning_rate = lr if callable(lr) else (lambda v: lambda _: v)(lr)
        model.ent_coef      = phase_cfg["ent_coef"]
        model.clip_range    = cr if callable(cr) else (lambda v: lambda _: v)(cr)
        return model

    policy_kwargs = dict(
        net_arch        = dict(pi=RL["net_arch"], vf=RL["net_arch"]),
        activation_fn   = __import__("torch.nn", fromlist=["Tanh"]).Tanh,
        ortho_init      = True,
    )

    model = PPO(
        policy          = "MlpPolicy",
        env             = env,
        learning_rate   = phase_cfg["learning_rate"],
        n_steps         = RL["n_steps"],
        batch_size      = RL["batch_size"],
        n_epochs        = RL["n_epochs"],
        gamma           = RL["gamma"],
        gae_lambda      = RL["gae_lambda"],
        clip_range      = phase_cfg["clip_range"],
        ent_coef        = phase_cfg["ent_coef"],
        vf_coef         = RL["vf_coef"],
        max_grad_norm   = RL["max_grad_norm"],
        policy_kwargs   = policy_kwargs,
        tensorboard_log = str(LOGS_DIR / "tb"),
        device          = RL["device"],
        verbose         = 1,
    )

    print(f"  PPO model built — Phase {phase}: {phase_cfg['name']}")
    print(f"  Network: {RL['net_arch']}×2  |  LR: {phase_cfg['learning_rate']}  "
          f"|  Entropy: {phase_cfg['ent_coef']}  |  Device: {RL['device']}")
    return model


# ════════════════════════════════════════════════════════════════════════════════
# EVALUATION
# ════════════════════════════════════════════════════════════════════════════════

def evaluate_model(model_path: Path, n_episodes: int = 50,
                   split: str = "test") -> dict:
    """
    Run deterministic evaluation on test set.
    Returns full metrics dict with pass rate, Sharpe, max DD etc.
    """
    if not _SB3_OK:
        print("SB3 not available for evaluation")
        return {}

    df_test = load_data(split)
    # random_start=True: each episode starts at a different bar (seeded by ep
    # number for reproducibility). Prevents degenerate Sharpe=0 from all 50
    # episodes running the identical bar-0 trajectory.
    env     = FTMOEnv(df_test, firm=ACTIVE_FIRM, training=False,
                      random_start=True, max_episode_steps=720,
                      use_calendar=False)
    model   = PPO.load(model_path, device="cpu")

    results = []
    for ep in range(n_episodes):
        obs, _  = env.reset(seed=ep)
        done    = False
        ep_r    = 0.0

        while not done:
            action, _ = model.predict(obs, deterministic=True)
            obs, r, terminated, truncated, info = env.step(action)
            done   = terminated or truncated
            ep_r  += r

        results.append({
            "episode":       ep,
            "reward":        ep_r,
            "passed":        info.get("challenge_passed",   False),
            "final_pnl_pct": info.get("final_pnl_pct",      0.0),
            "n_trades":      info.get("n_trades",            0),
            "trading_days":  info.get("trading_days",        0),
            "daily_breach":  info.get("daily_dd_breach",     False),
            "total_breach":  info.get("total_dd_breach",     False),
            "max_dd_pct":    info.get("max_dd_pct",          0.0),
        })

    df_r      = pd.DataFrame(results)
    pass_rate = df_r["passed"].mean()

    # Sharpe on pnl_pct values (matches FTMOMetricsCallback).
    # Raw step rewards are shaped/penalised and produce absurd Sharpe
    # when all episodes hit a breach (std → 0, mean/std → ±∞).
    pnl_vals = df_r["final_pnl_pct"].values.astype(float)
    if (len(pnl_vals) < 5
            or float(np.std(pnl_vals)) < 1e-6
            or float(np.mean(np.abs(pnl_vals))) < 1e-6):
        sharpe = 0.0
    else:
        sharpe = float(np.clip(
            (np.mean(pnl_vals) / np.std(pnl_vals)) * np.sqrt(252), -10.0, 10.0
        ))

    metrics = {
        "model":         str(model_path.name),
        "split":         split,
        "n_episodes":    n_episodes,
        "pass_rate":     round(float(pass_rate),                       3),
        "daily_breach":  round(float(df_r["daily_breach"].mean()),      3),
        "total_breach":  round(float(df_r["total_breach"].mean()),      3),
        "avg_pnl_pct":   round(float(df_r["final_pnl_pct"].mean()),     4),
        "avg_trades":    round(float(df_r["n_trades"].mean()),          1),
        "avg_days":      round(float(df_r["trading_days"].mean()),      1),
        "mean_reward":   round(float(df_r["reward"].mean()),            3),
        "sharpe":        round(float(sharpe),                           3),
        "max_dd_avg":    round(float(df_r["max_dd_pct"].mean()),        4),
    }

    # Save
    eval_path = EVAL_DIR / f"eval_{model_path.stem}_{split}.json"
    with open(eval_path, "w") as f:
        json.dump(metrics, f, indent=2)

    print(f"\n{'='*55}")
    print(f"  Evaluation — {metrics['model']}  ({split})")
    print(f"{'='*55}")
    print(f"  Pass rate     : {pass_rate:.1%}")
    print(f"  Avg PnL       : {metrics['avg_pnl_pct']:+.2%}")
    print(f"  Sharpe        : {metrics['sharpe']:.2f}")
    print(f"  Daily breach  : {metrics['daily_breach']:.1%}")
    print(f"  Total breach  : {metrics['total_breach']:.1%}")
    print(f"  Avg trades    : {metrics['avg_trades']:.0f}")
    print(f"  Avg days      : {metrics['avg_days']:.1f}")
    print(f"  Saved → {eval_path}")
    print(f"{'='*55}")
    return metrics


# ════════════════════════════════════════════════════════════════════════════════
# MAIN TRAINING LOOP
# ════════════════════════════════════════════════════════════════════════════════

def train(phase_start: int   = 1,
          total_timesteps: int = None,
          resume: bool         = False,
          resume_model: Optional[Path] = None,
          n_envs: int          = 4,
          fast: bool           = False):
    """Full training loop with curriculum."""

    if not _SB3_OK:
        print("Install SB3 first: pip install stable-baselines3[extra]")
        return

    total_timesteps = total_timesteps or RL["total_timesteps"]
    if fast:
        total_timesteps = 100_000
        n_envs          = 1
        print("  🏃 Fast mode: 100k steps, 1 env")

    print(f"\n{'='*55}")
    print(f"  FTMO RL Training — {INST['symbol']}  [{RUN_ID}]")
    print(f"{'='*55}")
    print(f"  Firm          : {CFG['name']}")
    print(f"  Account       : £{CFG['account_size']:,}")
    print(f"  Target        : {CFG['profit_target_pct']:.0%}  "
          f"= £{CFG['account_size'] * CFG['profit_target_pct']:,.0f}")
    print(f"  Max daily DD  : {CFG['max_daily_loss_pct']:.0%}")
    print(f"  Max total DD  : {CFG['max_total_loss_pct']:.0%}")
    print(f"  Total steps   : {total_timesteps:,}")
    print(f"  Parallel envs : {n_envs}")
    print(f"  Curriculum    : Phase {phase_start} → 3")
    print(f"{'='*55}\n")

    # ── Load data ──────────────────────────────────────────────────────────────
    print("Loading data...")
    df_train = load_data("train")
    df_val   = load_data("val")

    # ── Build vectorised training env ─────────────────────────────────────────
    train_env = make_vec_env(
        make_env(df_train, phase=phase_start, training=True),
        n_envs    = n_envs,
        seed      = 42,
        vec_env_cls = SubprocVecEnv if n_envs > 1 else None,
    )
    train_env = VecNormalize(train_env, norm_obs=False, norm_reward=False,
                              clip_obs=10.0, gamma=RL["gamma"])

    # ── Resume? ───────────────────────────────────────────────────────────────
    resume_path = None
    if resume_model and resume_model.exists():
        # Explicit model path takes priority
        resume_path = resume_model
        print(f"  Resuming from explicit path: {resume_path.name}")
    elif resume:
        # Fall back to latest checkpoint
        ckpts = sorted(CKPT_DIR.glob("ppo_xauusd_*.zip"))
        if ckpts:
            resume_path = ckpts[-1]
            print(f"  Resuming from latest checkpoint: {resume_path.name}")

    # ── Build model ───────────────────────────────────────────────────────────
    model = build_model(train_env, phase=phase_start, resume_path=resume_path)

    # ── Callbacks ─────────────────────────────────────────────────────────────
    checkpoint_cb = CheckpointCallback(
        save_freq      = 100_000,
        save_path      = str(CKPT_DIR),
        name_prefix    = "ppo_xauusd",
        save_replay_buffer  = False,
        save_vecnormalize    = True,
    )

    eval_env = make_vec_env(
        make_env(df_val, phase=phase_start, training=False),
        n_envs=1,
        seed=43,
    )
    eval_env = VecNormalize(eval_env, norm_obs=False, norm_reward=False,
                            clip_obs=10.0, gamma=RL["gamma"], training=False)

    eval_cb = EvalCallback(
        eval_env,
        best_model_save_path = str(BEST_DIR),
        log_path             = str(EVAL_DIR),
        eval_freq            = 50_000,
        n_eval_episodes      = 20,
        deterministic        = True,
        render               = False,
    )

    curriculum_cb  = CurriculumCallback(phase_start=phase_start)
    ftmo_metrics_cb = FTMOMetricsCallback(eval_freq=100_000)

    callbacks = CallbackList([
        checkpoint_cb,
        eval_cb,
        curriculum_cb,
        ftmo_metrics_cb,
    ])

    # ── Train ─────────────────────────────────────────────────────────────────
    print(f"  Starting training...\n")
    try:
        model.learn(
            total_timesteps  = total_timesteps,
            callback         = callbacks,
            tb_log_name      = f"ppo_xauusd_phase{phase_start}_{RUN_ID}",
            reset_num_timesteps = not resume,
            progress_bar     = True,
        )
    except KeyboardInterrupt:
        print("\n  Training interrupted — saving checkpoint...")

    # ── Save final model ──────────────────────────────────────────────────────
    final_path = MODELS_DIR / f"ppo_xauusd_final_{RUN_ID}.zip"
    model.save(final_path)
    train_env.save(MODELS_DIR / f"vecnorm_{RUN_ID}.pkl")

    print(f"\n  ✅ Training complete")
    print(f"  Final model → {final_path}")
    print(f"  Best model  → {BEST_DIR / 'best_model.zip'}")

    # ── Evaluate on val set ───────────────────────────────────────────────────
    best = BEST_DIR / "best_model.zip"
    if best.exists():
        print("\n  Running final evaluation on validation set...")
        evaluate_model(best, n_episodes=50, split="val")

    return model


# ════════════════════════════════════════════════════════════════════════════════
# CLI
# ════════════════════════════════════════════════════════════════════════════════

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Train FTMO PPO agent on XAUUSD")
    parser.add_argument("--phase",      type=int, default=1,
                        choices=[1, 2, 3], help="Curriculum phase to start at")
    parser.add_argument("--timesteps",  type=int, default=None,
                        help="Override total timesteps")
    parser.add_argument("--resume",     action="store_true",
                        help="Resume from latest checkpoint (by name sort)")
    parser.add_argument("--model",      type=str, default=None,
                        metavar="MODEL_PATH",
                        help="Explicit model zip to resume from (overrides --resume)")
    parser.add_argument("--n-envs",     type=int, default=4,
                        help="Parallel envs for training")
    parser.add_argument("--fast",       action="store_true",
                        help="100k step smoke test")
    parser.add_argument("--eval",       type=str, default=None,
                        metavar="MODEL_PATH",
                        help="Evaluate a saved model (skip training)")
    parser.add_argument("--split",      default="test",
                        choices=["train", "val", "test"],
                        help="Data split for --eval")
    args = parser.parse_args()

    if args.eval:
        evaluate_model(Path(args.eval), n_episodes=100, split=args.split)
    else:
        train(
            phase_start     = args.phase,
            total_timesteps = args.timesteps,
            resume          = args.resume,
            resume_model    = Path(args.model) if args.model else None,
            n_envs          = args.n_envs,
            fast            = args.fast,
        )

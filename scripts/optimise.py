"""
Optuna hyperparameter optimisation for FTMOSwingEnv PPO agent.

Searches over:
  - Learning rate, entropy coefficient, clip range
  - Network architecture
  - FTMO reward shaping weights (lambda_daily_dd, lambda_total_dd)
  - Position sizing risk percentages

Usage:
    python scripts/optimise.py --n_trials 100 --device auto
    python scripts/optimise.py --n_trials 200 --device cuda
"""

import argparse
import os
import sys
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

import numpy as np
import optuna
from optuna.samplers import TPESampler
from optuna.pruners import MedianPruner

from stable_baselines3 import PPO
from stable_baselines3.common.env_util import make_vec_env
from stable_baselines3.common.vec_env import VecNormalize
from stable_baselines3.common.callbacks import BaseCallback

from config.settings import DATA, RL
from config.prop_firms import ACTIVE_FIRM
from data.features import FeaturePipeline
from env.ftmo_env import FTMOEnv


# ── Data (loaded once, shared across trials) ──────────────────────────────────

def _load_data():
    print("[OPT] Loading training data for HPO...")
    pipe = FeaturePipeline()
    df = pipe.load("XAUUSD_H1_features").sort_index()
    import pandas as _pd
    if df.index.tzinfo is None:
        df.index = df.index.tz_localize("UTC")
    # 85/15 train/val split
    split = int(len(df) * 0.85)
    return df.iloc[:split].copy(), df.iloc[split:].copy()


# ── Pruning callback ──────────────────────────────────────────────────────────

class OptunaPruningCallback(BaseCallback):
    def __init__(self, trial, eval_env, eval_freq=10_000):
        super().__init__()
        self.trial     = trial
        self.eval_env  = eval_env
        self.eval_freq = eval_freq
        self.n_calls   = 0

    def _on_step(self) -> bool:
        self.n_calls += 1
        if self.n_calls % self.eval_freq != 0:
            return True

        # Quick single-episode eval
        obs, _ = self.eval_env.reset()
        done   = False
        total_r = 0.0
        while not done:
            action, _ = self.model.predict(obs, deterministic=True)
            obs, r, term, trunc, _ = self.eval_env.step(action)
            done    = term or trunc
            total_r += r

        self.trial.report(total_r, self.n_calls)
        if self.trial.should_prune():
            return False  # stops training
        return True


# ── Objective function ────────────────────────────────────────────────────────

_DATA_CACHE = None

def objective(trial: optuna.Trial, device: str = "auto") -> float:
    global _DATA_CACHE
    if _DATA_CACHE is None:
        _DATA_CACHE = _load_data()
    df_train, df_val = _DATA_CACHE

    # ── Hyperparameter search space ───────────────────────────────────────────
    lr            = trial.suggest_float("learning_rate",    1e-5, 1e-3, log=True)
    ent_coef      = trial.suggest_float("ent_coef",         1e-4, 0.05, log=True)
    clip_range    = trial.suggest_float("clip_range",        0.1,  0.4)
    n_steps       = trial.suggest_categorical("n_steps",    [1024, 2048, 4096])
    batch_size    = trial.suggest_categorical("batch_size",  [32, 64, 128])
    n_epochs      = trial.suggest_int("n_epochs",            5, 15)
    gamma         = trial.suggest_float("gamma",             0.95, 0.999)
    gae_lambda    = trial.suggest_float("gae_lambda",        0.9, 0.99)
    n_layers      = trial.suggest_int("n_layers",            2, 3)
    layer_size    = trial.suggest_categorical("layer_size",  [128, 256, 512])
    lambda_daily  = trial.suggest_float("lambda_daily_dd",   0.005, 0.20, log=True)
    lambda_total  = trial.suggest_float("lambda_total_dd",   0.005, 0.25, log=True)

    net_arch = [layer_size] * n_layers

    try:
        def _make_train_env():
            e = FTMOEnv(df_train, firm=ACTIVE_FIRM, training=True, random_start=True)
            e.lambda_daily_dd = lambda_daily
            e.lambda_total_dd = lambda_total
            return e

        env = VecNormalize(
            make_vec_env(_make_train_env, n_envs=2),
            norm_obs=False, norm_reward=False, clip_obs=10.0
        )
        eval_env = FTMOEnv(df_val, firm=ACTIVE_FIRM, training=False,
                           random_start=False, use_calendar=False)
        eval_env.lambda_daily_dd = lambda_daily
        eval_env.lambda_total_dd = lambda_total

        model = PPO(
            policy        = "MlpPolicy",
            env           = env,
            learning_rate = lr,
            n_steps       = n_steps,
            batch_size    = batch_size,
            n_epochs      = n_epochs,
            gamma         = gamma,
            gae_lambda    = gae_lambda,
            clip_range    = clip_range,
            ent_coef      = ent_coef,
            vf_coef       = RL["vf_coef"],
            max_grad_norm = RL["max_grad_norm"],
            policy_kwargs = dict(net_arch=net_arch),
            device        = device,
            verbose       = 0,
        )

        pruning_cb = OptunaPruningCallback(trial, eval_env, eval_freq=5_000)

        # Short training run per trial — 500k steps
        model.learn(
            total_timesteps = 500_000,
            callback        = pruning_cb,
            progress_bar    = False,
        )

        # Final evaluation — full episode, deterministic
        obs, _ = eval_env.reset()
        done   = False
        total_r = 0.0
        max_ddd = 0.0
        max_tdd = 0.0
        info    = {}
        while not done:
            action, _ = model.predict(obs, deterministic=True)
            obs, r, term, trunc, info = eval_env.step(action)
            done    = term or trunc
            total_r += r
            max_ddd  = max(max_ddd, max(0.0, -info.get("daily_pnl", 0.0)) / (eval_env.initial_balance + 1e-9))
            max_tdd  = max(max_tdd, info.get("max_dd_pct", 0.0))

        # Heavy penalty if FTMO limits are breached
        ftmo_pass = bool(info.get("challenge_passed", False)
                         and not info.get("daily_dd_breach", False)
                         and not info.get("total_dd_breach", False))
        if not ftmo_pass:
            total_r -= 5_000

        trial.set_user_attr("final_pnl",     info.get("total_pnl", 0))
        trial.set_user_attr("max_daily_dd",  max_ddd)
        trial.set_user_attr("max_total_dd",  max_tdd)
        trial.set_user_attr("ftmo_pass",     ftmo_pass)
        trial.set_user_attr("n_trades",      info.get("n_trades", 0))

        env.close()
        return total_r

    except Exception as e:
        print(f"[OPT] Trial {trial.number} failed: {e}")
        raise optuna.exceptions.TrialPruned()


# ── Entry point ───────────────────────────────────────────────────────────────

if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--n_trials", type=int,  default=100)
    parser.add_argument("--device",   default="auto")
    parser.add_argument("--study",    default="ftmo_xauusd_ppo")
    args = parser.parse_args()

    os.makedirs("models", exist_ok=True)
    storage = f"sqlite:///models/optuna_{args.study}.db"

    study = optuna.create_study(
        study_name    = args.study,
        storage       = storage,
        direction     = "maximize",
        sampler       = TPESampler(n_startup_trials=20, multivariate=True),
        pruner        = MedianPruner(n_startup_trials=10, n_warmup_steps=5),
        load_if_exists= True,
    )

    print(f"[OPT] Starting Optuna HPO | {args.n_trials} trials | device={args.device}")
    print(f"[OPT] Study: {args.study} | Storage: {storage}")

    study.optimize(
        lambda trial: objective(trial, args.device),
        n_trials        = args.n_trials,
        show_progress_bar= True,
        n_jobs          = 1,
    )

    print("\n[OPT] ══ Best Trial ═══════════════════════════════════════")
    best = study.best_trial
    print(f"  Value        : {best.value:.4f}")
    print(f"  Final PnL    : £{best.user_attrs.get('final_pnl', 0):+,.0f}")
    print(f"  Max Daily DD : {best.user_attrs.get('max_daily_dd', 0):.2%}")
    print(f"  Max Total DD : {best.user_attrs.get('max_total_dd', 0):.2%}")
    print(f"  FTMO Pass    : {best.user_attrs.get('ftmo_pass', False)}")
    print(f"  Win Rate     : {best.user_attrs.get('win_rate', 0):.2%}")
    print(f"\n  Parameters:")
    for k, v in best.params.items():
        print(f"    {k}: {v}")

    # Save best params to config
    import json
    best_path = "models/best_hyperparams.json"
    with open(best_path, "w") as fh:
        json.dump({"params": best.params, "value": best.value,
                   "user_attrs": best.user_attrs}, fh, indent=2)
    print(f"\n[OPT] Best params saved → {best_path}")
    print(f"[OPT] Full study DB      → {storage}")
    print(f"[OPT] Visualise: optuna-dashboard sqlite:///models/optuna_{args.study}.db")

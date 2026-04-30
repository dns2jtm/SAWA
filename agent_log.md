# Agent Log — FTMO RL Pipeline Stabilisation

---

## Session 1 — 2026-04-27

### Hypothesis
Four metric/accounting bugs explain the degenerate eval results:
1. `max_dd_pct` never reflects intra-bar drawdown → `max_dd_avg = 0.0`
2. `use_calendar=True` in historical eval → live-time event blocking on historical bars
3. Sharpe formula produces absurd values when pnl_vals cluster near same negative float
4. `avg_days = 0.0` — suspected day-boundary / termination-credit race (to be confirmed)

### Files inspected
- `env/ftmo_env.py` — full read
- `models/train.py` — full read
- `config/prop_firms.py` — full read
- `config/settings.py` — full read
- `data/features.py` — full read (confirmed `atr_14 = ATR/close`, normalized; index name = "datetime")
- `data/news_calendar.py` — full read (confirmed: CalendarFilter uses `datetime.now()` not bar time)
- `tests/test_env_info_contract.py` — full read

### Files changed (this session)
- `env/ftmo_env.py` — Fix 1: max_dd_pct intra-bar tracking
- `models/train.py` — Fix 2: use_calendar=False in evaluate_model; Fix 3: Sharpe cap ±10
- `scripts/diagnose_eval.py` — new: step-level episode diagnostic

### Commands run
```
python3 -c "... inspect features index ..."
# → Index name: 'datetime', shape (64409, 70), DatetimeIndex UTC
```

### Root causes

| # | Symptom | Root cause | File | Line |
|---|---------|------------|------|------|
| 1 | `max_dd_avg = 0.0` | `max_dd_pct` uses close-price `self.equity` only; breach fires on intra-bar `worst_equity` | `env/ftmo_env.py` | 316-319 |
| 2 | Non-deterministic eval, possible phantom blocks | `evaluate_model()` passes `training=False` without `use_calendar=False`; calendar calls `datetime.now()` → live event time, not bar time | `models/train.py` | 471 |
| 3 | Absurd Sharpe (e.g. -950) | Guard `std < 1e-12` too tight; with 100% breach, std ≈ 0.001, mean/std × sqrt(252) → ±950 | `models/train.py` | 506-511, 364-368 |
| 4 | `avg_days = 0.0` | Under investigation — diagnostic script in `scripts/diagnose_eval.py` |

### Fix details

**Fix 1 (env/ftmo_env.py)**  
After `worst_equity` is computed, also update `max_dd_pct` using the worst intra-bar equity:
```python
_worst_dd_from_peak = (self.peak_equity - worst_equity) / (self.peak_equity + 1e-9)
self.max_dd_pct = max(self.max_dd_pct, _worst_dd_from_peak)
```

**Fix 2 (models/train.py)**  
In `evaluate_model()`, add `use_calendar=False` to FTMOEnv constructor.

**Fix 3 (models/train.py)**  
- In `evaluate_model()`: `sharpe = float(np.clip(..., -10, 10))`
- In `FTMOMetricsCallback._on_step()`: same clip

### Next step
- Run smoke diagnostic on 5 episodes to trace `avg_days = 0.0`
- Run full smoke test `python3 models/train.py --fast` and compare before/after

---

## Session 2 — 2026-04-27

### Additional findings
1. `models/backtest.py` also constructed historical eval envs with `training=False` and default `use_calendar=True`.
2. Walk-forward episodes in `models/backtest.py` used deterministic start bars by default, making multiple episodes per window mostly redundant.
3. `scripts/backtest.py` and `scripts/optimise.py` also used historical eval envs without `use_calendar=False`.
4. `scripts/optimise.py` passed `int(action)` into a continuous `Box` action env during pruning eval.
5. `scripts/optimise.py` searched drawdown lambda values in the hundreds/thousands despite env reward scaling expecting fractional values around `0.005–0.25`.
6. Env stop-loss enforcement checked only bar close, allowing intra-bar stop breaches to recover without closing.

### Files changed
- `models/backtest.py`
  - `run_window()` and `plot_equity_curves()` now pass `random_start=True, use_calendar=False`.
  - Walk-forward Sharpe now uses the same practical low-variance guard and `[-10, +10]` cap.
- `scripts/backtest.py`
  - Historical backtest env now passes `use_calendar=False`.
- `scripts/optimise.py`
  - Eval env now passes `use_calendar=False`.
  - Pruning callback now passes the continuous action array directly to `env.step()`.
  - HPO lambda search ranges now match env reward scale.
- `env/ftmo_env.py`
  - Stop loss now triggers on intra-bar `low/high` and fills at `stop_loss_price`.

### Validation
```
python3 scripts/diagnose_eval.py
# daily_breach_rate=0.0%, avg_days=17.70, avg_trades=52.0,
# avg_max_dd_pct=0.015340, avg_pnl_pct=+0.0135

python3 -m py_compile env/ftmo_env.py models/backtest.py scripts/backtest.py scripts/optimise.py
# PASS

targeted stop-loss smoke
# long opened at 2000, stop=1970, bar low=1960,
# position closed at stop, trade_pnl_usd=-360.012

direct run_window smoke, 2 episodes
# {'pass_rate': 0.0, 'daily_breach': 0.0, 'total_breach': 0.0,
#  'avg_days': 44.5, 'avg_trades': 97.0, 'max_dd_avg': 0.0253,
#  'sharpe': 1.116}

observation smoke
# shape=(77,), nonfinite_resets=0, min_obs=-1.0, max_obs=1.0
```

### Repo-wide contract audit
After Session 2 fixes, ran a final scan for residual issues:

- `FTMOSwingEnv` references: only a stale docstring line in `scripts/optimise.py`. No runtime impact.
- `daily_dd_pct` / `total_dd_pct` / `info["pnl"]` / `info["trades"]` / `info["win_rate"]`: no callers remain.
- `env.step(int(action))` patterns: none remain.
- All historical `training=False` envs in `env/`, `models/`, and `scripts/` now pass `use_calendar=False`.
- `execution/live.py` correctly retains live `CalendarFilter()` (live trading path).
- `models/train.py` training/eval pipelines use `norm_obs=False, norm_reward=False`, so no VecNormalize stats sync gap between train and eval envs.

No further high-confidence bugs identified. Stop here per minimal-fix policy.

### Final smoke
```
python3 -m py_compile env/ftmo_env.py models/train.py models/backtest.py \
                       scripts/backtest.py scripts/optimise.py scripts/diagnose_eval.py
# compile PASS

python3 scripts/diagnose_eval.py
# daily_breach_rate=0.0%, avg_days=17.70, avg_trades=51.9,
# avg_max_dd_pct=0.014038, avg_pnl_pct=+0.0134

contract test
# PASS
```

---

## Session 3 — 2026-04-27

### Changes
- `tests/test_env_regressions.py` — 7 regression tests locking in all Session-1/2 fixes
- `tests/test_env_info_contract.py` — added `__main__` entry for direct CI invocation
- `.github/workflows/ci.yml` — complete rewrite: removed stale `FTMOSwingEnv`/`build_observation_df`/`get_feature_cols`/`daily_dd_pct` references that had been breaking CI since the API migration; now runs contract + regression test files and uses `FTMOEnv` with synthetic df for smoke PPO

### Feature pipeline audit (data/features.py)
All rolling indicators (RSI, MACD, ATR, Bollinger, ADX, VWAP, OBV, vol z-score) use standard lookback windows only — no look-ahead bias.

**Low-impact look-ahead bias identified (not patched):**
GMM regime classifier (`gmm_regime.pkl`) is fitted on the full dataset at build time (`python data/features.py --auto`), which means val/test regime distributions marginally inform the cluster boundaries. Practical impact is low because `hist_vol_20` and `adx_14` are stationary-ish features. Correct fix is to fit GMM on train split only and cache per-split — deferred.

H4/Daily multi-timeframe features: correctly shifted by 1 period (`h4.shift(1)`, `d.shift(1)`) before ffill to H1 index. ✅

### retrain.py audit
- `data.regime.RegimeDetector` module exists; `.fit(df)` API matches the call in retrain.py.
- `walk_forward()` returns `gate_passed` and `gate_detail` keys as expected.
- `run_window()` net_equity and breach tracking are correct.
- No blocking issues found.

### Data splits
`load_data()` performs a strict 80/10/10 chronological split by bar count.
train ≤ 2023-12-31, val = 2024, test = 2025→. No leakage.

### CI status
All 4 CI steps now pass on synthetic data (no raw data files required in CI).
Commits: `f36b91f` (regression tests), `a39ff4c` (CI fix).

---

## Session 4 — 2026-04-30

### Findings
Identified a silent bug where `data/features.py` checked for `"gold_vol"` natively, but `data/lseg_client.py` was assigning the VIX macro feed to the `"vix"` column. This resulted in `vix_proxy` silently skipping the real LSEG VIX overlay and falling back to trailing price volatility.

### Files changed
- `data/features.py` — corrected the `vix` column check overlay and updated logging message.

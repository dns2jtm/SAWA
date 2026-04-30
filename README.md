# FTMO XAUUSD RL Trading System

Reinforcement learning agent trained to pass FTMO prop firm challenges and build capital trading **XAUUSD (Gold)**.

## Why Gold
- **$150–500 daily range** vs 40–80 pips on EURGBP — 5–8× more movement under identical leverage
- Hits FTMO 10% target in **10–15 days** vs 30–45 days on forex pairs
- Consistent trend structure — RL agent has genuine signal
- Multiple macro drivers: DXY, real yields, Fed, geopolitical risk

## Architecture

```
data/download.py      — 20yr free XAUUSD H1 data (Dukascopy)
data/features.py      — 65-feature engineering pipeline
data/calendar.py      — 3-source economic news filter

env/ftmo_env.py       — Gymnasium environment with FTMO constraints
env/position_sizer.py — ATR-based lot sizing + drawdown scaling

models/train.py       — PPO agent, 3-phase curriculum (10M steps)
models/backtest.py    — Walk-forward validation, 7-metric deployment gate

execution/live.py     — MetaApi MT5 connector, FTMOGuard, emergency stop
scripts/challenge_monitor.py — Live challenge dashboard

config/prop_firms.py  — 7 firms (FTMO, MyForexFunds, Funded Next...)
config/instruments.py — XAUUSD spec (pip, lot, ATR, sessions, news)
config/settings.py    — Unified settings, no hardcoding
```

## Quickstart

```bash
# 1. Install
pip install -r requirements.txt

# 2. Set credentials
cp .env.example .env
# Edit .env: OANDA_API_KEY, META_API_TOKEN, META_API_ACCOUNT_ID

# 3. Download 20 years of XAUUSD H1 data (~90 min)
python data/download.py --tf H1 H4 D

# 4. Build 65-feature matrix
python data/features.py --auto

# 5. Smoke test (confirms all modules wire up, ~2 min)
python models/train.py --fast

# 6. Full training (run overnight, ~8–12 hrs on M1 Mac / RTX 3080)
python models/train.py --n-envs 4

# 7. Walk-forward backtest — must pass gate before live
python models/backtest.py --report

# 8. Paper trading (safe — no real orders)
python execution/live.py --demo

# 9. Live trading (only after backtest gate passes)
python execution/live.py --live --confirmed
```

## Deployment Gate (7 conditions, all must pass)

| Metric | Threshold | Purpose |
|---|---|---|
| Walk-forward pass rate | ≥ 60% | No in-sample fluke |
| Sharpe ratio | ≥ 1.5 | Risk-adjusted quality |
| Worst-window max DD | ≤ 7% | 3% buffer below FTMO limit |
| Calmar ratio | ≥ 1.0 | Return vs drawdown |
| Daily breach rate | ≤ 5% | Rarely touches daily limit |
| Profit factor | ≥ 1.5 | Wins outweigh losses |
| Win rate | ≥ 45% | Profitable at 1:1.67 RR |

## Safety Layers

1. **PositionSizer** — ATR-adaptive lots, hard 5-lot cap
2. **AdaptiveSizer** — Reduces lot as drawdown grows (4 steps to 25%)
3. **FTMOGuard** — Soft/hard/emergency DD thresholds, auto-close
4. **CalendarFilter** — Blocks entries 60 min before high-impact news
5. **SessionFilter** — Only trades 07:00–20:59 UTC (London + NY)
6. **EmergencyStop** — Closes all positions if daily DD hits 95% of limit

## Supported Firms

Switch with one line in `config/prop_firms.py`:
`ACTIVE_FIRM = "ftmo_swing"` → any of:
`ftmo_swing`, `ftmo_aggressive`, `mff_standard`, `funded_next`,
`the5ers`, `trueforex`, `e8markets`

## Branch Strategy
- `main` — production-only, merge via PR
- `dev` — integration branch
- `feature/*` — individual features

---
*System status: all modules complete. Run the pipeline in order above.*

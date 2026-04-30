# AGENTS.md

## Role
You are the lead quant architect for this repository.

## Mission
Improve the FTMO RL training pipeline safely, reproducibly, and with small auditable changes.

## Working style
- Always work from the repo root.
- Always use `python3` or `uv run python`.
- Prefer the smallest change that fixes the issue.
- Reproduce bugs before changing code.
- After every code change, run the shortest meaningful verification.
- Summarize what changed, what passed, and what still needs work.

## Git rules
- Never work directly on `main`.
- Default working branch is `dev` unless told otherwise.
- Prefer small commits with explicit messages.
- Never force-push.
- Never commit large generated artifacts, caches, logs, checkpoints, or raw data unless explicitly asked.

## Files and folders not to commit
- `models/best/`
- `models/eval/`
- `models/checkpoints/`
- `models/logs/`
- `data/raw/`
- `data/cache/`
- `__pycache__/`
- `.venv/`

## Environment rules
- Always run commands from `~/ftmo-eurgbp`.
- Always prefer repo-local scripts over ad hoc commands when available.
- Do not delete or overwrite raw data without explicit approval.
- Do not change secrets, credentials, remotes, or branch protections without approval.

## FTMO metrics contract
The environment must emit these keys at episode end:
- `n_trades`
- `trading_days`
- `final_pnl_pct`
- `challenge_passed`
- `daily_dd_breach`
- `total_dd_breach`

The training callback must log and print:
- `pass_rate`
- `daily_breach`
- `total_breach`
- `avg_pnl_pct`
- `avg_trades`
- `avg_days`
- `active_episode_fraction`
- `sharpe`

## Verification loop
After every source change:
1. Run a smoke test or shortest valid training/eval command.
2. Check that the process starts cleanly.
3. Check that FTMO metrics fields exist.
4. Check whether metrics are plausible, not just non-crashing.
5. Only then commit.

## Success criteria
A fix is not complete unless:
- The training run starts successfully.
- The FTMO metrics block prints without crashing.
- Expected FTMO keys exist in env info and callback metrics.
- The change does not introduce new path/import/runtime errors.

## Preferred commands
- `python3 data/features.py --auto`
- `python3 models/train.py`
- `python3 models/train.py --fast`
- `git status`
- `git diff -- <file>`
- `git add <file> && git commit -m "<message>" && git push origin dev`

#!/bin/bash
# ─────────────────────────────────────────────────────────────────────────────
# scripts/runpod_train.sh
# Runs INSIDE the RunPod pod (as the startup script or via SSH).
#
# What it does:
#   1. Pulls latest code from GitHub
#   2. Downloads historical data (if not already present on network volume)
#   3. Rebuilds feature file
#   4. Runs full PPO training with GPU-optimised settings
#   5. Copies final model to /workspace/output/ for easy download
#
# Environment variables (set in RunPod template or pod env):
#   GITHUB_REPO   — e.g. https://github.com/dns2jtm/ftmo-eurgbp.git
#   GITHUB_BRANCH — default: dev
#   N_ENVS        — parallel envs (A100: 32, 4090: 16)
#   TIMESTEPS     — default: 20000000
#   PHASE         — start phase (1, 2, or 3)
#   MODEL_PATH    — optional: path to zip to resume from
#   HF_TOKEN      — optional: HuggingFace token for model hub upload
# ─────────────────────────────────────────────────────────────────────────────

set -e

REPO="${GITHUB_REPO:-https://github.com/dns2jtm/ftmo-eurgbp.git}"
BRANCH="${GITHUB_BRANCH:-dev}"
WORKDIR="/workspace/ftmo-eurgbp"
N_ENVS="${N_ENVS:-32}"
TIMESTEPS="${TIMESTEPS:-20000000}"
PHASE="${PHASE:-1}"
OUTPUT_DIR="/workspace/output"

# ── Inject token into HTTPS URL (never echoed to stdout) ──────────────────────
# Set GITHUB_TOKEN in RunPod pod environment variables (Secrets section).
# Fine-grained PAT with Contents: Read-only on this repo is sufficient.
if [ -n "$GITHUB_TOKEN" ]; then
    # Embed token: https://<token>@github.com/owner/repo.git
    AUTH_REPO=$(echo "$REPO" | sed "s|https://|https://${GITHUB_TOKEN}@|")
else
    AUTH_REPO="$REPO"
    echo "⚠  GITHUB_TOKEN not set — assuming public repo or pre-cloned volume"
fi

echo "══════════════════════════════════════════════════════════"
echo "  RunPod FTMO Training  |  $(date -u '+%Y-%m-%d %H:%M UTC')"
echo "══════════════════════════════════════════════════════════"

# ── GPU check ─────────────────────────────────────────────────────────────────
python3 -c "
import torch
print(f'PyTorch   : {torch.__version__}')
print(f'CUDA      : {torch.version.cuda}')
print(f'GPU count : {torch.cuda.device_count()}')
for i in range(torch.cuda.device_count()):
    p = torch.cuda.get_device_properties(i)
    print(f'  GPU {i}  : {p.name}  ({p.total_memory/1e9:.1f} GB)')
"
echo ""

# ── Clone / update repo ───────────────────────────────────────────────────────
if [ -d "$WORKDIR/.git" ]; then
    echo "[1/5] Updating existing repo (branch: $BRANCH)..."
    git -C "$WORKDIR" remote set-url origin "$AUTH_REPO"
    git -C "$WORKDIR" fetch origin
    git -C "$WORKDIR" checkout "$BRANCH"
    git -C "$WORKDIR" pull origin "$BRANCH"
else
    echo "[1/5] Cloning repo (branch: $BRANCH)..."
    git clone --branch "$BRANCH" "$AUTH_REPO" "$WORKDIR"
fi

# Scrub the token from git remote URL so it's not stored in .git/config
if [ -n "$GITHUB_TOKEN" ]; then
    git -C "$WORKDIR" remote set-url origin "$REPO"
fi

cd "$WORKDIR"

# ── Install / update Python deps ──────────────────────────────────────────────
echo "[2/5] Installing Python dependencies..."
pip install --no-cache-dir --upgrade pip -q
pip install --no-cache-dir -r requirements.txt -q
echo "     Done."

# ── Data: download if raw H1 parquet not present ──────────────────────────────
H1_FILE=$(ls data/raw/XAUUSD_H1_*.parquet 2>/dev/null | sort | tail -1)
if [ -z "$H1_FILE" ]; then
    echo "[3/5] Downloading full XAUUSD H1 history from Dukascopy (2004 → today)..."
    python3 data/download.py \
        --symbol XAUUSD \
        --start  2004-01-01 \
        --end    "$(date +%Y-%m-%d)" \
        --tf     H1 \
        --workers 16
else
    echo "[3/5] Raw data found: $H1_FILE — skipping download"
fi

# ── Feature file ──────────────────────────────────────────────────────────────
FEAT_FILE="data/features/XAUUSD_H1_features.parquet"
if [ ! -f "$FEAT_FILE" ]; then
    echo "[4/5] Building feature file..."
    python3 data/features.py --auto
else
    echo "[4/5] Feature file found — skipping rebuild"
    python3 -c "
import pandas as pd
df = pd.read_parquet('$FEAT_FILE')
print(f'     {len(df):,} bars  ({df.index.min().date()} → {df.index.max().date()})')
"
fi

# ── Training ──────────────────────────────────────────────────────────────────
mkdir -p "$OUTPUT_DIR"
echo ""
echo "[5/5] Starting training..."
echo "      Phase=${PHASE}  Steps=${TIMESTEPS}  Envs=${N_ENVS}"
echo ""

if [ -n "$MODEL_PATH" ] && [ -f "$MODEL_PATH" ]; then
    echo "      Resuming from: $MODEL_PATH"
    python3 models/train.py \
        --model     "$MODEL_PATH" \
        --phase     "$PHASE" \
        --timesteps "$TIMESTEPS" \
        --n-envs    "$N_ENVS"
else
    python3 models/train.py \
        --phase     "$PHASE" \
        --timesteps "$TIMESTEPS" \
        --n-envs    "$N_ENVS"
fi

# ── Copy outputs to /workspace/output for easy retrieval ──────────────────────
echo ""
echo "Copying outputs to $OUTPUT_DIR ..."
cp -r models/best/          "$OUTPUT_DIR/best/"          2>/dev/null || true
cp -r models/eval/          "$OUTPUT_DIR/eval/"          2>/dev/null || true
cp    models/logs/ftmo_metrics_*.jsonl "$OUTPUT_DIR/"   2>/dev/null || true
cp    models/ppo_xauusd_final_*.zip    "$OUTPUT_DIR/"   2>/dev/null || true

echo ""
echo "══════════════════════════════════════════════════════════"
echo "  COMPLETE — outputs in $OUTPUT_DIR"
echo "══════════════════════════════════════════════════════════"
ls -lh "$OUTPUT_DIR/"

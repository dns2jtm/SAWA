#!/bin/bash
# ─────────────────────────────────────────────────────────────────────────────
# docker/entrypoint.sh — RunPod + local Docker entrypoint
#
# Commands:
#   train      — full PPO training from scratch
#   resume     — resume from latest checkpoint (pass MODEL_PATH env var for explicit)
#   download   — download historical OHLCV data only
#   features   — rebuild feature file from raw data
#   eval       — evaluate a saved model (pass MODEL_PATH env var)
#   bash       — interactive shell (debug)
# ─────────────────────────────────────────────────────────────────────────────

set -e

echo "═══════════════════════════════════════════════════════"
echo "  FTMO-EURGBP  |  $(date -u '+%Y-%m-%d %H:%M:%S UTC')"
echo "═══════════════════════════════════════════════════════"

# ── GPU detection ─────────────────────────────────────────────────────────────
if python3 -c "import torch; exit(0 if torch.cuda.is_available() else 1)" 2>/dev/null; then
    GPU=$(python3 -c "import torch; print(torch.cuda.get_device_name(0))")
    N_GPUS=$(python3 -c "import torch; print(torch.cuda.device_count())")
    echo "[GPU] $GPU detected (${N_GPUS}x) — training on CUDA"
    DEVICE="cuda"
else
    echo "[GPU] No GPU — falling back to CPU"
    DEVICE="cpu"
fi
export DEVICE

# ── Default env vars ──────────────────────────────────────────────────────────
# Override any of these via: docker run -e N_ENVS=16 ...
PHASE="${PHASE:-1}"
TIMESTEPS="${TIMESTEPS:-10000000}"
N_ENVS="${N_ENVS:-16}"         # A100: 16-32 envs; 4090: 8-16; CPU: 4
MODEL_PATH="${MODEL_PATH:-}"   # Explicit model to resume from
DATA_START="${DATA_START:-2004-01-01}"
DATA_END="${DATA_END:-$(date +%Y-%m-%d)}"

echo "[CFG] Phase=${PHASE}  Steps=${TIMESTEPS}  Envs=${N_ENVS}  Device=${DEVICE}"
echo ""

case "$1" in
    train)
        echo "[TASK] Full PPO training from scratch"
        # Rebuild features if raw data exists but feature file doesn't
        if [ ! -f data/features/XAUUSD_H1_features.parquet ]; then
            echo "[INFO] Feature file missing — building from raw data..."
            python3 data/features.py --auto
        fi
        python3 models/train.py \
            --phase    "$PHASE" \
            --timesteps "$TIMESTEPS" \
            --n-envs   "$N_ENVS"
        ;;

    resume)
        echo "[TASK] Resuming training"
        if [ ! -f data/features/XAUUSD_H1_features.parquet ]; then
            echo "[INFO] Feature file missing — building from raw data..."
            python3 data/features.py --auto
        fi
        if [ -n "$MODEL_PATH" ]; then
            python3 models/train.py \
                --model    "$MODEL_PATH" \
                --phase    "$PHASE" \
                --timesteps "$TIMESTEPS" \
                --n-envs   "$N_ENVS"
        else
            python3 models/train.py \
                --resume \
                --phase    "$PHASE" \
                --timesteps "$TIMESTEPS" \
                --n-envs   "$N_ENVS"
        fi
        ;;

    download)
        echo "[TASK] Downloading XAUUSD historical data from Dukascopy"
        python3 data/download.py \
            --symbol XAUUSD \
            --start  "$DATA_START" \
            --end    "$DATA_END" \
            --tf     H1
        ;;

    features)
        echo "[TASK] Rebuilding feature file from raw data"
        python3 data/features.py --auto
        ;;

    eval)
        echo "[TASK] Evaluating model"
        MODEL_PATH="${MODEL_PATH:-models/best/best_model.zip}"
        python3 models/train.py \
            --eval  "$MODEL_PATH" \
            --split "${EVAL_SPLIT:-test}"
        ;;

    bash)
        echo "[TASK] Interactive shell"
        exec /bin/bash
        ;;

    *)
        echo "Unknown command: $1"
        echo "Usage: $0 {train|resume|download|features|eval|bash}"
        exit 1
        ;;
esac

echo ""
echo "═══════════════════════════════════════════════════════"
echo "  DONE  |  $(date -u '+%Y-%m-%d %H:%M:%S UTC')"
echo "═══════════════════════════════════════════════════════"

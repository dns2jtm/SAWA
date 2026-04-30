#!/bin/bash
# ─────────────────────────────────────────────────────────────────────────────
# scripts/sync_from_runpod.sh
# Pull trained model outputs from a RunPod pod back to your local Mac.
#
# Usage:
#   ./scripts/sync_from_runpod.sh <pod-id>
#   ./scripts/sync_from_runpod.sh <pod-id> --all    # also sync logs + checkpoints
#
# Prerequisites:
#   1. Install runpodctl:  brew install runpod/runpodctl/runpodctl
#   2. Login:             runpodctl config --apiKey <your-api-key>
#   3. Pod must be RUNNING and have SSH enabled
#
# What gets synced:
#   models/best/best_model.zip        — best checkpoint (EvalCallback)
#   models/eval/                      — evaluation JSON results
#   models/logs/ftmo_metrics_*.jsonl  — FTMO training metrics
#   models/ppo_xauusd_final_*.zip     — final model (optional --all)
# ─────────────────────────────────────────────────────────────────────────────

set -e

POD_ID="${1}"
MODE="${2:-}"

if [ -z "$POD_ID" ]; then
    echo "Usage: $0 <pod-id> [--all]"
    echo ""
    echo "Get pod ID from: runpodctl get pod"
    exit 1
fi

LOCAL_ROOT="$(cd "$(dirname "$0")/.." && pwd)"
REMOTE_DIR="/workspace/ftmo-eurgbp"
OUTPUT_DIR="/workspace/output"

# Get SSH connection details from runpodctl
echo "Fetching pod connection info for: $POD_ID"
SSH_INFO=$(runpodctl get pod "$POD_ID" 2>/dev/null | grep -E "sshCommand|SSH" | head -1)
if [ -z "$SSH_INFO" ]; then
    echo "Could not get SSH info. Trying manual connection..."
    echo "Run: runpodctl get pod $POD_ID"
    exit 1
fi

# Parse SSH host/port from runpodctl output
# Format: ssh root@<host> -p <port> -i ~/.runpod/ssh/id_ed25519
SSH_HOST=$(echo "$SSH_INFO" | grep -oP '(?<=@)[^ ]+' | head -1)
SSH_PORT=$(echo "$SSH_INFO" | grep -oP '(?<=-p )\d+' | head -1)
SSH_KEY="${HOME}/.runpod/ssh/id_ed25519"

if [ -z "$SSH_HOST" ] || [ -z "$SSH_PORT" ]; then
    echo "⚠ Could not auto-parse SSH details. Manual rsync:"
    echo ""
    echo "  # Get SSH command from RunPod dashboard, then:"
    echo "  rsync -avz --progress \\"
    echo "    -e 'ssh -p <PORT> -i ~/.runpod/ssh/id_ed25519 -o StrictHostKeyChecking=no' \\"
    echo "    root@<HOST>:${OUTPUT_DIR}/ \\"
    echo "    ${LOCAL_ROOT}/models/"
    exit 1
fi

SSH_OPTS="-p $SSH_PORT -i $SSH_KEY -o StrictHostKeyChecking=no -o ConnectTimeout=10"
RSYNC_OPTS="-avz --progress"

echo ""
echo "Syncing from pod $POD_ID ($SSH_HOST:$SSH_PORT) → $LOCAL_ROOT"
echo ""

# Always sync: best model + eval results + FTMO metrics
echo "── Syncing best model and eval results..."
rsync $RSYNC_OPTS \
    -e "ssh $SSH_OPTS" \
    "root@${SSH_HOST}:${OUTPUT_DIR}/" \
    "${LOCAL_ROOT}/models/runpod_output/"

# Additional syncs when --all is passed
if [ "$MODE" = "--all" ]; then
    echo "── Syncing full logs directory..."
    rsync $RSYNC_OPTS \
        -e "ssh $SSH_OPTS" \
        --exclude="tb/" \
        "root@${SSH_HOST}:${REMOTE_DIR}/models/logs/" \
        "${LOCAL_ROOT}/models/logs/"

    echo "── Syncing checkpoints (latest 3 only)..."
    ssh root@${SSH_HOST} $SSH_OPTS \
        "ls ${REMOTE_DIR}/models/checkpoints/*.zip | sort | tail -3" | \
    while read -r ckpt; do
        rsync $RSYNC_OPTS \
            -e "ssh $SSH_OPTS" \
            "root@${SSH_HOST}:${ckpt}" \
            "${LOCAL_ROOT}/models/checkpoints/"
    done
fi

echo ""
echo "✅ Sync complete → ${LOCAL_ROOT}/models/runpod_output/"
ls -lh "${LOCAL_ROOT}/models/runpod_output/" 2>/dev/null || true

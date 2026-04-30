#!/bin/bash
# ─────────────────────────────────────────────────────────────────────────────
# scripts/train_pipeline.sh
# Master pipeline to rebuild features, push to pod, and train on RunPod.
# ─────────────────────────────────────────────────────────────────────────────

set -e

# RunPod config
POD_USER="root"
POD_HOST="213.173.105.9"
POD_PORT="34513"
SSH_KEY="~/.ssh/id_ed25519"

echo "=== 1. Building features locally ==="
cd ~/ftmo-eurgbp
python3 data/features.py --auto
FEAT_FILE=$(ls data/features/XAUUSD_H1_features.parquet | tail -n 1)

echo ""
echo "=== 2. Uploading features to RunPod ==="
rsync -avz --progress \
    -e "ssh -p $POD_PORT -i $SSH_KEY" \
    "$FEAT_FILE" \
    $POD_USER@$POD_HOST:/workspace/ftmo-eurgbp/data/features/

echo ""
echo "=== 3. Starting remote training on A100 ==="
ssh -p $POD_PORT -i $SSH_KEY $POD_USER@$POD_HOST << 'EOF'
    cd /workspace/ftmo-eurgbp
    
    # Start training in background (runpod_train.sh handles the git pull)
    nohup bash scripts/runpod_train.sh > /workspace/train_full.log 2>&1 &
    
    echo "Training started in background on pod."
    echo "To view logs on pod: tail -f /workspace/train_full.log"
EOF

echo ""
echo "=== Pipeline Triggered Successfully ==="

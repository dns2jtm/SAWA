#!/bin/bash
# ─────────────────────────────────────────────────────────────────────────────
# RunPod setup script for SAWA
# Tested on: RunPod PyTorch 2.x image | NVIDIA RTX 2000 Ada
#
# Usage (run once after pod starts):
#   bash scripts/runpod_setup.sh
# ─────────────────────────────────────────────────────────────────────────────

set -e
echo "================================================"
echo " FTMO SAWA — RunPod Environment Setup"
echo "================================================"

# ── 1. System packages ────────────────────────────────────────────────────────
echo "[1/7] Installing system packages..."
apt-get update -qq
apt-get install -y -qq wget curl git build-essential libpq-dev redis-server

# ── 2. TimescaleDB (PostgreSQL 15) ────────────────────────────────────────────
echo "[2/7] Installing PostgreSQL + TimescaleDB..."
apt-get install -y -qq gnupg
echo "deb https://apt.postgresql.org/pub/repos/apt $(lsb_release -cs)-pgdg main"     > /etc/apt/sources.list.d/pgdg.list
wget -qO- https://www.postgresql.org/media/keys/ACCC4CF8.asc | apt-key add -

# TimescaleDB repo
echo "deb https://packagecloud.io/timescale/timescaledb/ubuntu/ $(lsb_release -cs) main"     > /etc/apt/sources.list.d/timescaledb.list
wget -qO- https://packagecloud.io/timescale/timescaledb/gpgkey | apt-key add -

apt-get update -qq
apt-get install -y -qq timescaledb-2-postgresql-15

# Configure TimescaleDB
timescaledb-tune --quiet --yes
service postgresql start || pg_ctlcluster 15 main start || true

# Create DB user and database
sudo -u postgres psql -c "CREATE USER ftmo_user WITH PASSWORD 'ftmo_secure_pass';" 2>/dev/null || true
sudo -u postgres psql -c "CREATE DATABASE ftmo OWNER ftmo_user;" 2>/dev/null || true
sudo -u postgres psql -d ftmo -c "CREATE EXTENSION IF NOT EXISTS timescaledb CASCADE;" 2>/dev/null || true
echo "[2/7] TimescaleDB ready."

# ── 3. Redis ─────────────────────────────────────────────────────────────────
echo "[3/7] Starting Redis..."
service redis-server start || redis-server --daemonize yes
echo "[3/7] Redis ready."

# ── 4. Python dependencies ────────────────────────────────────────────────────
echo "[4/7] Installing Python packages..."
pip install --quiet --upgrade pip
pip install --quiet -r /workspace/SAWA/requirements.txt
echo "[4/7] Python packages installed."

# ── 5. TA-Lib (C library + Python wrapper) ───────────────────────────────────
echo "[5/7] Installing TA-Lib..."
cd /tmp
wget -q https://sourceforge.net/projects/ta-lib/files/ta-lib/0.4.0/ta-lib-0.4.0-src.tar.gz
tar -xzf ta-lib-0.4.0-src.tar.gz
cd ta-lib
./configure --prefix=/usr --build=x86_64-linux-gnu > /dev/null 2>&1
make -j$(nproc) > /dev/null 2>&1
make install > /dev/null 2>&1
cd /workspace
pip install --quiet TA-Lib
echo "[5/7] TA-Lib installed."

# ── 6. WandB login ────────────────────────────────────────────────────────────
echo "[6/7] WandB login (enter your API key when prompted)..."
wandb login

# ── 7. Verify GPU ─────────────────────────────────────────────────────────────
echo "[7/7] Verifying GPU..."
python3 -c "
import torch
print(f'PyTorch {torch.__version__}')
print(f'CUDA available: {torch.cuda.is_available()}')
if torch.cuda.is_available():
    print(f'GPU: {torch.cuda.get_device_name(0)}')
    print(f'VRAM: {torch.cuda.get_device_properties(0).total_memory / 1e9:.1f} GB')
"

# ── 8. Sanity-check imports ───────────────────────────────────────────────────
echo "[8] Checking project imports..."
cd /workspace/SAWA
python3 -c "
from config.settings import FTMO, EXECUTION
from data.features import FeaturePipeline
from env.ftmo_env import FTMOEnv
print('✅ All imports OK')
print(f'   Account    : £{FTMO[\"account_balance\"]:,}')
print(f'   Kill daily : {FTMO[\"daily_dd_kill_pct\"]:.1%}')
print(f'   Kill total : {FTMO[\"total_dd_kill_pct\"]:.1%}')
print(f'   Platform   : {EXECUTION[\"platform\"]}')
print(f'   Server     : {EXECUTION[\"ftmo_server\"]}')
print(f'   Features   : {len(FeaturePipeline.OBS_COLUMNS)}')
"

echo ""
echo "================================================"
echo " Setup complete! Next steps:"
echo ""
echo "  1. Edit config/settings.py — paste your MetaApi token"
echo "  2. python data/download.py          # fetch data"
echo "  3. python scripts/optimise.py       # HPO (optional)"
echo "  4. python models/train.py           # train agent"
echo "  5. python models/backtest.py --report # validation"
echo "  6. python execution/live.py --demo  # paper trading"
echo "================================================"

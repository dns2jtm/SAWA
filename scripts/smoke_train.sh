#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")/.."

echo "== Smoke train start =="
python3 models/train.py --fast
echo "== Smoke train done =="

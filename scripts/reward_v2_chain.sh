#!/bin/bash
# reward v2 chain (2026-10-08): run_512x2r_1m -> recalibrate -> boss_v2r_1m
set -u
cd "$(dirname "$0")/.."

echo "[1/3] run_512x2r_1m (512,256, 1M steps, reward v2) $(date)"
OMP_NUM_THREADS=4 uv run python -u scripts/train_run.py \
  --steps 1000000 --eval-every 100000 --log-every 20000 \
  --net 512,256 --out run_512x2r_1m > models/logs/run_512x2r_1m.log 2>&1
echo "run_512x2r_1m done $(date)"

echo "[2/3] recalibrate boss entry with run_512x2r_1m $(date)"
uv run python scripts/estimate_boss_entry.py --model models/run_512x2r_1m.zip --runs 40 || {
  echo "calibration failed, keep fallback"
}

echo "[3/3] boss_v2r_1m (512,256, 1M steps, reward v2 aligned) $(date)"
OMP_NUM_THREADS=4 uv run python -u scripts/train_boss.py \
  --steps 1000000 --eval-every 100000 --log-every 20000 \
  --net 512,256 --out boss_v2r_1m > models/logs/boss_v2r_1m.log 2>&1
echo "boss_v2r_1m done $(date)"
echo "==== reward_v2_chain complete $(date) ===="

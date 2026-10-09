#!/bin/bash
# 退火续链（2026-10-08）：160 从 anneal_400 承接，80 从 160 承接
set -u
cd "$(dirname "$0")/.."
PREV="models/sampled_boss_anneal_400.zip"
for hp in 160 80; do
  echo "anneal hp=${hp} from ${PREV} $(date)"
  OMP_NUM_THREADS=4 uv run python -u scripts/train_sampled.py \
    --steps 300000 --difficulties boss --anneal-from "${PREV}" --anneal-hp ${hp} \
    --out sampled_boss_anneal_${hp} > models/logs/sampled_boss_anneal_${hp}.log 2>&1
  PREV="models/sampled_boss_anneal_${hp}.zip"
done
echo "==== anneal complete $(date) ===="

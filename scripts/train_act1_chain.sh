#!/bin/bash
# Act 1 分档训练链（2026-10-08）：弱/强/精英正常训 + Boss 退火
set -u
cd "$(dirname "$0")/.."

echo "[1/4] weak (damage target <=5) $(date)"
OMP_NUM_THREADS=4 uv run python -u scripts/train_sampled.py \
  --steps 1000000 --difficulties weak --out sampled_a1_weak_v1 > models/logs/sampled_a1_weak_v1.log 2>&1
echo "weak done $(date)"

echo "[2/4] strong (damage target <=12) $(date)"
OMP_NUM_THREADS=4 uv run python -u scripts/train_sampled.py \
  --steps 1000000 --difficulties strong --out sampled_a1_strong_v1 > models/logs/sampled_a1_strong_v1.log 2>&1
echo "strong done $(date)"

echo "[3/4] elite (damage target <=25) $(date)"
OMP_NUM_THREADS=4 uv run python -u scripts/train_sampled.py \
  --steps 1000000 --difficulties elite --out sampled_a1_elite_v1 > models/logs/sampled_a1_elite_v1.log 2>&1
echo "elite done $(date)"

echo "[4/4] boss anneal 1000->400->160->80 (chained) $(date)"
# 退火：逐级承接（1000→400 已完成；160 从 400 的产物续，80 从 160 续）
PREV="models/sampled_boss_anneal_400.zip"
for hp in 160 80; do
  echo "  anneal step: hp=${hp} from ${PREV} $(date)"
  OMP_NUM_THREADS=4 uv run python -u scripts/train_sampled.py \
    --steps 300000 --difficulties boss --anneal-from "${PREV}" --anneal-hp ${hp} \
    --out sampled_boss_anneal_${hp} > models/logs/sampled_boss_anneal_${hp}.log 2>&1
  PREV="models/sampled_boss_anneal_${hp}.zip"
done
echo "boss anneal done $(date)"
echo "==== act1 chain complete $(date) ===="

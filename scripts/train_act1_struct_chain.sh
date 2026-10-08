#!/bin/bash
# Act 1 分档训练链 v2（2026-10-08）：structured 架构 + ACTION_LIMIT 保险丝。
# 前置：sampled_a1_strong_struct_v2 对照存活（塌缩根因为 CARD_SELECT
# toggle 吸收态，已由 ACTION_LIMIT 封死——见 EXPERIMENTS.md EXP-08/09）。
set -u
cd "$(dirname "$0")/.."
ARCH=structured

echo "[1/4] weak (damage target <=5) $(date)"
OMP_NUM_THREADS=4 uv run python -u scripts/train_sampled.py \
  --steps 1000000 --difficulties weak --arch $ARCH --net 512,256 \
  --out sampled_a1_weak_struct_v2 > models/logs/sampled_a1_weak_struct_v2.log 2>&1
echo "weak done $(date)"

echo "[2/4] strong (damage target <=12) $(date)"
OMP_NUM_THREADS=4 uv run python -u scripts/train_sampled.py \
  --steps 1000000 --difficulties strong --arch $ARCH --net 512,256 \
  --out sampled_a1_strong_struct_v2 > models/logs/sampled_a1_strong_struct_v2.log 2>&1
echo "strong done $(date)"

echo "[3/4] elite (damage target <=25) $(date)"
OMP_NUM_THREADS=4 uv run python -u scripts/train_sampled.py \
  --steps 1000000 --difficulties elite --arch $ARCH --net 512,256 \
  --out sampled_a1_elite_struct_v2 > models/logs/sampled_a1_elite_struct_v2.log 2>&1
echo "elite done $(date)"

echo "[4/4] boss anneal 1000->400->160->80 (chained) $(date)"
# 退火：逐级承接（每级 300k 步、LR 减半）
OMP_NUM_THREADS=4 uv run python -u scripts/train_sampled.py \
  --steps 300000 --difficulties boss --arch $ARCH --net 512,256 --anneal-hp 1000 \
  --out sampled_boss_struct_1000 > models/logs/sampled_boss_struct_1000.log 2>&1
PREV="models/sampled_boss_struct_1000.zip"
for hp in 400 160 80; do
  echo "  anneal step: hp=${hp} from ${PREV} $(date)"
  OMP_NUM_THREADS=4 uv run python -u scripts/train_sampled.py \
    --steps 300000 --difficulties boss --arch $ARCH --net 512,256 \
    --anneal-from "${PREV}" --anneal-hp ${hp} \
    --out sampled_boss_struct_${hp} > models/logs/sampled_boss_struct_${hp}.log 2>&1
  PREV="models/sampled_boss_struct_${hp}.zip"
done
echo "boss anneal done $(date)"
echo "==== act1 struct chain complete $(date) ===="

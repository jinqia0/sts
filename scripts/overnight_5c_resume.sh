#!/bin/bash
# overnight_5c 接续版（2026-10-08 01:20）：首跑链在阶段 2 崩溃
# （pgrep 等待窗口 race：run_v1 首跑被杀时链即放行，模型尚未存在；
# 之后 boss_v1 在旧 heuristic 标定上误训已作废删除）。本脚本从阶段 2
# 重启，用刚出炉的 models/run_v1.zip 重新标定，然后走完全部剩余阶段。
set -u
cd "$(dirname "$0")/.."

echo "==== overnight_5c 接续链启动 $(date) ===="

# ---- 2. Boss 入场分布标定（外层策略 = run_v1 真模型）----
echo "[2/5] Boss 入场 HP 条件分布标定（run_v1 实测 40 run）$(date)"
uv run python scripts/estimate_boss_entry.py --model models/run_v1.zip --runs 40 || {
  echo "标定失败，沿用兜底分布继续（boss_env 自带 fallback）"
}

# ---- 3. Boss 专家训练 ----
echo "[3/5] Boss 专家训练 boss_v1（1M 步）$(date)"
OMP_NUM_THREADS=4 uv run python -u scripts/train_boss.py \
  --steps 1000000 --eval-every 100000 --log-every 20000 \
  --net 1024,512 --out boss_v1 > models/logs/boss_v1.log 2>&1
echo "boss_v1 完成 $(date)"
tail -20 models/logs/boss_v1.log

# ---- 4. run 场景网络扫描（各 1M 步）----
for entry in "256,128|run_256x2_1m" "512,256|run_512x2_1m" "1024,512|run_1024x2_1m" "1024,512,256|run_1024x3_1m"; do
  net="${entry%%|*}"
  name="${entry##*|}"
  echo "[4/5] 扫描 $name（$net，1M 步）$(date)"
  OMP_NUM_THREADS=4 uv run python -u scripts/train_run.py \
    --steps 1000000 --eval-every 100000 --log-every 20000 \
    --net "$net" --out "$name" > "models/logs/$name.log" 2>&1
  echo "$name 完成 $(date)"
done

# ---- 5. Boss 小网络对照 ----
echo "[5/5] Boss 小网络对照 boss_512x2_1m（512,256，1M 步）$(date)"
OMP_NUM_THREADS=4 uv run python -u scripts/train_boss.py \
  --steps 1000000 --eval-every 100000 --log-every 20000 \
  --net 512,256 --out boss_512x2_1m > models/logs/boss_512x2_1m.log 2>&1
echo "boss_512x2_1m 完成 $(date)"

echo "==== overnight_5c 接续链全部完成 $(date) ===="

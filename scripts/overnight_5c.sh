#!/bin/bash
# 批次 5c 夜间链（2026-10-08，用户指令：独立完成）
#
#   1. 等待 run_v1（2M 步迷你局训练）完成
#   2. 用 run_v1 模型重标定 Boss 入场 HP 条件分布（40 run 实测）
#   3. Boss 专家训练 boss_v1（1M 步，[1024,512]）
#   4. 网络大小/深度/步数扫描（run 场景，各 1M 步）：
#      256,128 / 512,256 / 1024,512（与 run_v1@2M 构成步数对照）/ 1024,512,256
#   5. Boss 场景小网络对照 boss_512x2_1m（512,256）
#
# 用法：nohup bash scripts/overnight_5c.sh > models/logs/overnight_5c.log 2>&1 &
set -u
cd "$(dirname "$0")/.."

echo "==== overnight_5c 链启动 $(date) ===="

# ---- 1. 等 run_v1 进程退出（其最终评估在进程内完成后才退出）----
echo "[1/5] 等待 run_v1 完成…"
while pgrep -f "train_run.py.*--out run_v1" > /dev/null; do
  sleep 60
done
echo "run_v1 已结束 $(date)"
tail -20 models/logs/run_v1.log

# ---- 2. Boss 入场分布重标定（外层策略 = run_v1）----
echo "[2/5] Boss 入场 HP 条件分布标定（run_v1 实测 40 run）$(date)"
uv run python scripts/estimate_boss_entry.py --model models/run_v1.zip --runs 40 || {
  echo "标定失败，沿用兜底分布继续（boss_env 自带 fallback）"
}

# ---- 3. Boss 专家训练 ----
echo "[3/5] Boss 专家训练 boss_v1（1M 步）$(date)"
uv run python -u scripts/train_boss.py \
  --steps 1000000 --eval-every 100000 --log-every 20000 \
  --net 1024,512 --out boss_v1 > models/logs/boss_v1.log 2>&1
echo "boss_v1 完成 $(date)"
tail -20 models/logs/boss_v1.log

# ---- 4. run 场景网络扫描（各 1M 步）----
for entry in "256,128|run_256x2_1m" "512,256|run_512x2_1m" "1024,512|run_1024x2_1m" "1024,512,256|run_1024x3_1m"; do
  net="${entry%%|*}"
  name="${entry##*|}"
  echo "[4/5] 扫描 $name（$net，1M 步）$(date)"
  uv run python -u scripts/train_run.py \
    --steps 1000000 --eval-every 100000 --log-every 20000 \
    --net "$net" --out "$name" > "models/logs/$name.log" 2>&1
  echo "$name 完成 $(date)"
done


# ---- 5. Boss 小网络对照 ----
echo "[5/5] Boss 小网络对照 boss_512x2_1m（512,256，1M 步）$(date)"
uv run python -u scripts/train_boss.py \
  --steps 1000000 --eval-every 100000 --log-every 20000 \
  --net 512,256 --out boss_512x2_1m > models/logs/boss_512x2_1m.log 2>&1
echo "boss_512x2_1m 完成 $(date)"

echo "==== overnight_5c 链全部完成 $(date) ===="

#!/bin/bash
# overnight_5c 阶段 4-5 接续（2026-10-08 01:55）：resume 链在阶段 4 的
# echo 行上报 name unbound（疑似进程启动时读到写入中间态）。本脚本只含
# 扫描段，纯 ASCII 变量名 + ASCII echo，规避任何非字节安全写法。
set -u
cd "$(dirname "$0")/.."

for entry in "256,128|run_256x2_1m" "512,256|run_512x2_1m" "1024,512|run_1024x2_1m" "1024,512,256|run_1024x3_1m"; do
  net="${entry%%|*}"
  name="${entry##*|}"
  echo "[4/5] scan ${name} (${net}, 1M steps) $(date)"
  OMP_NUM_THREADS=4 uv run python -u scripts/train_run.py \
    --steps 1000000 --eval-every 100000 --log-every 20000 \
    --net "${net}" --out "${name}" > "models/logs/${name}.log" 2>&1
  echo "${name} done $(date)"
done

echo "[5/5] boss small net boss_512x2_1m (512,256, 1M steps) $(date)"
OMP_NUM_THREADS=4 uv run python -u scripts/train_boss.py \
  --steps 1000000 --eval-every 100000 --log-every 20000 \
  --net 512,256 --out boss_512x2_1m > models/logs/boss_512x2_1m.log 2>&1
echo "boss_512x2_1m done $(date)"
echo "==== scan_5c complete $(date) ===="

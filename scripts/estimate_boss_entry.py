"""Boss 入场 HP 损耗分布估计（批次 5c，2026-10-08，v2：run 级条件分布）。

Boss 专家训练的入场状态采样（StsBossEnv）需要「打完前 7 场还剩多少
HP」的分布。牌组/遗物/药水的分布在 run 层是纯 RNG（选牌/掉落与策略
无关），唯一策略依赖的是 HP——本脚本用**外层策略**（已训练的
MaskablePPO 模型）在 StsRunEnv 上实打若干 run，只取**到达 Boss 的
轨迹**（条件分布本身），逐场记录 (难度, 净损耗)，写入
sts/boss_entry_costs.json。

净损耗口径 = 该场开始时 HP（火堆回血已计入）- 结算后 HP（燃烧之血
+6 已含）——与 StsBossEnv 快进路径的「先火堆、再扣损耗」一一对应。

v1 教训（已废弃）：用 heuristic 单场损耗标定会把入场 HP 几乎全钳到
1（heuristic 精英死亡率 41%）——外层策略实际是 PPO，条件分布必须
用 PPO 实测。

用法：uv run python scripts/estimate_boss_entry.py --model models/run_v1.zip [--runs 40]
"""

from __future__ import annotations

import argparse
import json
import sys
from collections import defaultdict
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from sts.run_env import RUN_STRUCTURE, StsRunEnv

OUT = Path(__file__).resolve().parent.parent / "sts" / "boss_entry_costs.json"


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--model", required=True, help="外层策略模型路径（.zip）")
    parser.add_argument("--runs", type=int, default=40)
    args = parser.parse_args()

    from sb3_contrib import MaskablePPO

    m = MaskablePPO.load(args.model)
    env = StsRunEnv()

    def ppo(env_) -> int:
        a, _ = m.predict(env_._get_obs(), deterministic=True, action_masks=env_.action_masks())
        return int(a)

    costs: dict[str, list[int]] = defaultdict(list)
    reached = 0
    for s in range(args.runs):
        env.reset(seed=50_000 + s)
        hp_trace = []  # (battle_no, kind, hp_at_start)
        reached_boss = False
        steps = 0
        while True:
            # 战斗开始时的 HP（火堆已在 _start_battle 内结算）
            hp_trace.append((env.battle_no, env._current_kind, env.hp))
            prev_no = env.battle_no
            while env.battle_no == prev_no and not env.run_over:
                mask = env.action_masks()
                if not mask.any():
                    break
                obs, r, term, trunc, info = env.step(ppo(env))
                steps += 1
                if term or trunc or steps > 4000:
                    break
            if env.run_over:
                break
            if env.battle_no >= 7:
                reached_boss = True
                break
            if steps > 4000:
                break
        if reached_boss:
            reached += 1
            # 逐场净损耗 = 开始 HP - 结算后 HP。结算后 HP 不可直接观测
            # （下一场开始值已含其前火堆回血），故对火堆后继场补回回血量：
            # cost_i = start_i - start_{i+1} + heal（battle i+1 ∈ 火堆位时）
            from sts.run_env import CAMPFIRE_BEFORE, CAMPFIRE_HEAL_FRACTION

            for i, (no, kind, hp_start) in enumerate(hp_trace):
                if i + 1 < len(hp_trace):
                    hp_end = hp_trace[i + 1][2]
                else:
                    hp_end = env.hp
                if (i + 1) in CAMPFIRE_BEFORE:
                    hp_end -= env.max_hp * CAMPFIRE_HEAL_FRACTION // 100
                costs[kind].append(max(0, hp_start - hp_end))
    print(f"{args.runs} run 中 {reached} 个到达 Boss（{reached / args.runs:.0%}）")
    out = {}
    for kind in ("weak", "strong", "elite"):
        arr = np.array(costs.get(kind, [0]))
        out[kind] = [int(c) for c in costs.get(kind, [])]
        print(
            f"{kind:6s} n={len(arr)}  净损耗 mean={arr.mean():.1f}  "
            f"p25={np.percentile(arr, 25):.0f}  p50={np.percentile(arr, 50):.0f}  "
            f"p75={np.percentile(arr, 75):.0f}"
        )
    OUT.write_text(json.dumps(out), encoding="utf-8")
    print(f"已写入 {OUT}")


if __name__ == "__main__":
    main()

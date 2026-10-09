#!/usr/bin/env python3
"""微场景战术规则评测 CLI（EXP-15）：4 个脚本局面上的规则符合率。

用法：
    uv run python scripts/eval_tactics.py                      # 仅双 baseline
    uv run python scripts/eval_tactics.py --model models/xxx.zip
    uv run python scripts/eval_tactics.py --model xxx --seeds 50

策略采样默认 stochastic（deterministic=False）：观测对种子不变
（§4.3 审计），通过率估计的是策略概率质量落在预期行为上的比例；
--deterministic 切换贪心动作（结果逐种子恒同，看单一答案）。
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from sts.baselines import heuristic_policy, random_policy
from sts.tactics import TACTICS_SCENARIOS, evaluate_policy, format_report

MODEL_DIR = Path(__file__).resolve().parent.parent / "models"


def main() -> None:
    parser = argparse.ArgumentParser(description="微场景战术规则评测（sts/tactics.py）")
    parser.add_argument("--model", type=str, default=None, help="模型路径或 models/ 下文件名")
    parser.add_argument("--seeds", type=int, default=30, help="每个场景的 rollout 次数（默认 30）")
    parser.add_argument(
        "--deterministic",
        action="store_true",
        help="模型贪心动作（默认随机采样——测概率质量而非单点）",
    )
    args = parser.parse_args()
    seeds = range(args.seeds)

    for name, policy in [("random", random_policy), ("heuristic", heuristic_policy)]:
        reports = [evaluate_policy(policy, spec, seeds) for spec in TACTICS_SCENARIOS.values()]
        print(format_report(reports, name))
        print()

    if args.model:
        path = Path(args.model)
        if not path.exists() and (MODEL_DIR / f"{args.model}.zip").exists():
            path = MODEL_DIR / f"{args.model}.zip"
        if not path.exists():
            path = MODEL_DIR / args.model  # 报错信息走加载异常
        from sts.tactics import make_model_policy

        mode = "贪心" if args.deterministic else "随机采样"
        policy = make_model_policy(str(path), deterministic=args.deterministic)
        reports = [evaluate_policy(policy, spec, seeds) for spec in TACTICS_SCENARIOS.values()]
        print(format_report(reports, f"MaskablePPO [{path.name}]（{mode}）"))


if __name__ == "__main__":
    main()

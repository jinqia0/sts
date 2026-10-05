#!/usr/bin/env python3
"""MaskablePPO 训练：基础牌组 vs 弱怪池随机单场遭遇（ROADMAP 第 2 步）。

场景（2026-10-05 用户简化）：每局从弱怪池（cultist/jaw_worm/louses/
slimes_s/fungi_beast）均匀抽一种遭遇、打一场。各怪被采样次数相同，
样本分布比连打序列干净；无跨场状态，学习难度显著低于连打。

用法：
    uv run python scripts/train.py                          # 默认 300k 步
    uv run python scripts/train.py --steps 100000
    uv run python scripts/train.py --eval-only models/weak_v1.zip

训练协议（DESIGN.md §4.3 / §5）：
- 训练种子 ≥ 10_000（与评估种子带 0..99 不相交）
- 周期评估固定种子 70..99（含各怪遭遇），打印回报/胜率/剩余HP
- 结束后与 random、heuristic 两个 baseline 同种子对比
- 总体 + 分遭遇（per-encounter）双口径统计

奖励（2026-10-05 用户决策：战损为唯一目标）：
    终局 = 剩余 HP / max_hp（胜），败 0，进行中 0
    胜率退化为前提——保不住血自然输。主指标即平均剩余 HP。
"""

from __future__ import annotations

import argparse
import sys
from collections import defaultdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import numpy as np

from sts.baselines import heuristic_policy, random_policy
from sts.env import WEAK_POOL, StsBattleEnv

TRAIN_SEED = 10_000  # 训练种子基点（与评估 0..99 不相交）
EVAL_SEEDS = list(range(70, 100))  # 周期/最终评估固定种子
MODEL_DIR = Path(__file__).resolve().parent.parent / "models"


def run_eval_episode(env: StsBattleEnv, policy, seed: int) -> dict:
    obs, info = env.reset(seed=seed)
    total = 0.0
    while True:
        action = policy(env)
        obs, r, term, trunc, info = env.step(action)
        total += r
        if term or trunc:
            break
    return {"reward": total, "won": bool(info["won"]), "hp": info["hp_remaining"], "encounter": info["encounter"]}


def evaluate(policy, seeds=EVAL_SEEDS, verbose_name: str | None = None, scenario="weak") -> dict:
    """固定种子集上评估，返回总体 + 分遭遇统计。"""
    env = StsBattleEnv(scenario=scenario)
    eps = [run_eval_episode(env, policy, s) for s in seeds]
    per_enc: dict[str, list[dict]] = defaultdict(list)
    for e in eps:
        per_enc[e["encounter"]].append(e)
    out = {
        "reward": float(np.mean([e["reward"] for e in eps])),
        "win_rate": float(np.mean([e["won"] for e in eps])),
        "hp": float(np.mean([e["hp"] for e in eps])),
        "per_encounter": {
            enc: {
                "n": len(lst),
                "win_rate": float(np.mean([e["won"] for e in lst])),
                "avg_hp": float(np.mean([e["hp"] for e in lst])),
            }
            for enc, lst in sorted(per_enc.items())
        },
    }
    if verbose_name:
        print(
            f"  [{verbose_name:12s}] 平均剩余HP {out['hp']:.1f}/80  回报 {out['reward']:.3f}  胜率 {out['win_rate']:.2f}"
        )
        for enc, st in out["per_encounter"].items():
            print(f"      {enc:12s} n={st['n']:3d}  均余HP {st['avg_hp']:.1f}  胜率 {st['win_rate']:.2f}")
    return out


class _PeriodicEvalCallback:
    """训练中的周期评估（用 gymnasium Env 的独立实例，不打断采样流）。"""

    def __init__(self, every: int, eval_env: StsBattleEnv):
        from stable_baselines3.common.callbacks import BaseCallback

        outer = self
        self.every = every
        self.eval_env = eval_env
        self.history: list[tuple[int, dict]] = []

        class _Cb(BaseCallback):
            def _on_step(self) -> bool:
                if self.num_timesteps % outer.every == 0 and self.n_calls > 1:
                    rec = {
                        "t": self.num_timesteps,
                        "reward": 0.0,
                        "win_rate": 0.0,
                        "hp": 0.0,
                    }
                    wins = 0.0
                    for s in EVAL_SEEDS:
                        obs, info = outer.eval_env.reset(seed=s)
                        done = False
                        while not done:
                            mask = outer.eval_env.action_masks()
                            action, _ = self.model.predict(obs, deterministic=True, action_masks=mask)
                            obs, rew, term, trunc, info = outer.eval_env.step(int(action))
                            rec["reward"] += rew
                            if term or trunc:
                                done = True
                        wins += info["won"]
                        rec["hp"] += info["hp_remaining"]
                    n = len(EVAL_SEEDS)
                    rec["win_rate"] = wins / n
                    rec["hp"] /= n
                    rec["reward"] /= n
                    outer.history.append((self.num_timesteps, rec))
                    print(
                        f"    {rec['t']:>8d} 步  剩余HP {rec['hp']:.1f}  "
                        f"回报 {rec['reward']:.3f}  胜率 {rec['win_rate']:.2f}",
                        flush=True,
                    )
                return True

        self.cb = _Cb()


def make_model(scenario: str):
    from sb3_contrib import MaskablePPO

    env = StsBattleEnv(scenario=scenario)
    return MaskablePPO(
        "MlpPolicy",
        env,
        # 单场战斗短视野（~30-60 步），标准超参起步
        learning_rate=3e-4,
        n_steps=512,
        batch_size=256,
        gamma=0.99,
        gae_lambda=0.95,
        ent_coef=0.01,  # 动作空间大，早期保探索
        verbose=0,
        seed=TRAIN_SEED,
    )


def train(total_steps: int, eval_every: int, scenario: str, out: str) -> None:
    from sts.scenarios import get_scenario

    spec = get_scenario(scenario)
    MODEL_DIR.mkdir(exist_ok=True)
    model = make_model(scenario)
    print(f"开始训练：场景 [{spec.name}] {spec.description}")
    print(f"{total_steps} 步（训练种子 {TRAIN_SEED}，评估种子 70..99，奖励 {spec.reward}）")
    periodic = _PeriodicEvalCallback(eval_every, StsBattleEnv(scenario=scenario))
    model.learn(total_timesteps=total_steps, callback=periodic.cb)
    model_path = MODEL_DIR / f"{out}.zip"
    model.save(model_path)
    print(f"\n模型已保存：{model_path}")

    if periodic.history:
        print("\n训练曲线（主指标：剩余 HP）：")
        for t, rec in periodic.history:
            print(f"    {t:>8d}  hp={rec['hp']:.1f}  reward={rec['reward']:.3f}  win={rec['win_rate']:.2f}")

    print("\n==== 最终对比（评估种子 70..99，分遭遇）====")
    evaluate(random_policy, verbose_name="random", scenario=scenario)
    evaluate(heuristic_policy, verbose_name="heuristic", scenario=scenario)

    from sb3_contrib import MaskablePPO

    m = MaskablePPO.load(model_path)

    def ppo_policy(env: StsBattleEnv) -> int:
        a, _ = m.predict(env._get_obs(), deterministic=True, action_masks=env.action_masks())
        return int(a)

    evaluate(ppo_policy, verbose_name="MaskablePPO", scenario=scenario)


def main() -> None:
    parser = argparse.ArgumentParser(description="多场景 MaskablePPO 训练（场景见 sts/scenarios.py）")
    parser.add_argument("--scenario", default="weak", help="场景名（sts/scenarios.py 注册表，默认 weak）")
    parser.add_argument("--steps", type=int, default=300_000)
    parser.add_argument("--eval-every", type=int, default=50_000)
    parser.add_argument("--out", default=None, help="模型文件名（不含 .zip；默认 <scenario>_v1）")
    parser.add_argument("--eval-only", type=str, default=None, help="只评估已保存的模型路径")
    args = parser.parse_args()
    out = args.out or f"{args.scenario}_v1"

    if args.eval_only:
        print(f"==== 评估 {args.eval_only}（场景 {args.scenario}，种子 70..99）====")
        evaluate(random_policy, verbose_name="random", scenario=args.scenario)
        evaluate(heuristic_policy, verbose_name="heuristic", scenario=args.scenario)

        from sb3_contrib import MaskablePPO

        m = MaskablePPO.load(args.eval_only)

        def ppo_policy(env: StsBattleEnv) -> int:
            a, _ = m.predict(env._get_obs(), deterministic=True, action_masks=env.action_masks())
            return int(a)

        evaluate(ppo_policy, verbose_name="MaskablePPO", scenario=args.scenario)
        return

    train(args.steps, args.eval_every, args.scenario, out)


if __name__ == "__main__":
    main()

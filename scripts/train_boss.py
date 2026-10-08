"""Boss 专家 MaskablePPO 训练（批次 5c，2026-10-08，用户指令）。

用法：uv run python scripts/train_boss.py --steps 1000000 --out boss_v1

动机（见 sts/boss_env.py 模块头）：run 训练中 Boss 样本稀缺（只有活到
第 8 场的轨迹含 Boss 战斗），单独训练 Boss 应对策略——入场状态按
概率模拟（牌组/遗物/药水走 run 层精确 RNG，HP 用外层策略实测条件
分布 sts/boss_entry_costs.json）。

超参：单场战斗（episode ~30-100 步），γ=0.99；网络默认 [1024, 512]
（与 run 策略同规模）。奖励 = 胜时实际 HP / 80（与 run 层口径一致）。
"""

from __future__ import annotations

import argparse
import sys
from collections import defaultdict
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from sts.baselines import heuristic_policy, random_policy
from sts.boss_env import StsBossEnv

TRAIN_SEED = 10_000
EVAL_SEEDS_PERIODIC = list(range(70, 80))
EVAL_SEEDS_FINAL = list(range(70, 100))
MODEL_DIR = Path(__file__).resolve().parent.parent / "models"

DEFAULT_NET = [1024, 512]


def run_episode(env: StsBossEnv, policy, seed: int, max_steps: int = 1000) -> dict:
    obs, info = env.reset(seed=seed)
    total = 0.0
    steps = 0
    while True:
        action = policy(env)
        obs, r, term, trunc, info = env.step(action)
        total += r
        steps += 1
        if term or trunc or steps >= max_steps:
            break
    return {
        "reward": total,
        "won": bool(info["won"]),
        "entry_hp": info["entry_hp"],
        "encounter": info["encounter"],
    }


def evaluate(policy, seeds, verbose_name: str | None = None) -> dict:
    env = StsBossEnv()
    eps = [run_episode(env, policy, s) for s in seeds]
    per_enc: dict[str, list[dict]] = defaultdict(list)
    for e in eps:
        per_enc[e["encounter"]].append(e)
    out = {
        "reward": float(np.mean([e["reward"] for e in eps])),
        "win_rate": float(np.mean([e["won"] for e in eps])),
        "per_boss": {
            enc: {"n": len(lst), "win_rate": float(np.mean([e["won"] for e in lst]))}
            for enc, lst in sorted(per_enc.items())
        },
    }
    if verbose_name:
        print(f"  [{verbose_name:12s}] 平均奖励 {out['reward']:.2f}  胜率 {out['win_rate']:.2f}")
        for enc, st in out["per_boss"].items():
            print(f"      {enc:12s} n={st['n']:3d}  胜率 {st['win_rate']:.2f}")
    return out


class _TrainLogCallback:
    """训练过程日志（20k 步一次，口径同 scripts/train_run.py）。"""

    def __init__(self, every: int):
        from stable_baselines3.common.callbacks import BaseCallback

        outer = self
        self.every = every
        self.history: list[dict] = []

        class _Cb(BaseCallback):
            def __init__(self):
                super().__init__()
                self._next = every

            def _on_step(self) -> bool:
                if self.num_timesteps >= self._next:
                    v = self.model.logger.name_to_value
                    buf = getattr(self.model, "ep_info_buffer", None) or []
                    rec = {
                        "t": self.num_timesteps,
                        "ep_rew": float(np.mean([e["r"] for e in buf])) if buf else float("nan"),
                        "ep_len": float(np.mean([e["l"] for e in buf])) if buf else float("nan"),
                        "loss": v.get("train/loss", float("nan")),
                        "entropy": v.get("train/entropy_loss", float("nan")),
                        "kl": v.get("train/approx_kl", float("nan")),
                        "ev": v.get("train/explained_variance", float("nan")),
                    }
                    outer.history.append(dict(rec))
                    print(
                        f"    [训练] {rec['t']:>9d} 步  ep_rew={rec['ep_rew']:.2f}  "
                        f"ep_len={rec['ep_len']:.0f}  loss={rec['loss']:.4f}  "
                        f"H={rec['entropy']:.3f}  kl={rec['kl']:.4f}  ev={rec['ev']:.2f}",
                        flush=True,
                    )
                    self._next += every
                return True

        self.cb = _Cb()


class _PeriodicEvalCallback:
    def __init__(self, every: int):
        from stable_baselines3.common.callbacks import BaseCallback

        outer = self
        self.every = every
        self.eval_env = StsBossEnv()
        self.history: list[tuple[int, dict]] = []

        class _Cb(BaseCallback):
            def _on_step(self) -> bool:
                if self.num_timesteps % outer.every == 0 and self.n_calls > 1:
                    rec = {"t": self.num_timesteps, "reward": 0.0, "win_rate": 0.0}
                    for s in EVAL_SEEDS_PERIODIC:
                        obs, info = outer.eval_env.reset(seed=s)
                        done, steps = False, 0
                        while not done:
                            mask = outer.eval_env.action_masks()
                            action, _ = self.model.predict(obs, deterministic=True, action_masks=mask)
                            obs, rew, term, trunc, info = outer.eval_env.step(int(action))
                            rec["reward"] += rew
                            steps += 1
                            if term or trunc or steps >= 1000:
                                done = True
                        rec["win_rate"] += bool(info["won"])
                    n = len(EVAL_SEEDS_PERIODIC)
                    rec["reward"] /= n
                    rec["win_rate"] /= n
                    outer.history.append((self.num_timesteps, dict(rec)))
                    print(
                        f"    {rec['t']:>9d} 步  奖励 {rec['reward']:.2f}  胜率 {rec['win_rate']:.2f}",
                        flush=True,
                    )
                return True

        self.cb = _Cb()


def make_model(net_arch: list[int]):
    from sb3_contrib import MaskablePPO
    from stable_baselines3.common.monitor import Monitor

    env = Monitor(StsBossEnv())
    return MaskablePPO(
        "MlpPolicy",
        env,
        policy_kwargs={"net_arch": dict(pi=list(net_arch), vf=list(net_arch))},
        learning_rate=3e-4,
        n_steps=1024,
        batch_size=512,
        gamma=0.99,  # 单场战斗
        gae_lambda=0.95,
        ent_coef=0.01,
        n_epochs=10,
        verbose=0,
        seed=TRAIN_SEED,
    )


def parse_net(s: str) -> list[int]:
    return [int(x) for x in s.split(",")]


def main() -> None:
    parser = argparse.ArgumentParser(description="Boss 专家 MaskablePPO 训练（StsBossEnv）")
    parser.add_argument("--steps", type=int, default=1_000_000)
    parser.add_argument("--eval-every", type=int, default=100_000)
    parser.add_argument("--log-every", type=int, default=20_000)
    parser.add_argument("--net", type=parse_net, default=DEFAULT_NET, help='如 "1024,512"')
    parser.add_argument("--out", default="boss_v1")
    parser.add_argument("--eval-only", type=str, default=None)
    args = parser.parse_args()

    if args.eval_only:
        print(f"==== 评估 {args.eval_only}（种子 70..99）====")
        evaluate(random_policy, EVAL_SEEDS_FINAL, "random")
        evaluate(heuristic_policy, EVAL_SEEDS_FINAL, "heuristic")
        from sb3_contrib import MaskablePPO

        m = MaskablePPO.load(args.eval_only)

        def ppo_policy(env: StsBossEnv) -> int:
            a, _ = m.predict(env._battle_obs(), deterministic=True, action_masks=env.action_masks())
            return int(a)

        evaluate(ppo_policy, EVAL_SEEDS_FINAL, "MaskablePPO")
        return

    MODEL_DIR.mkdir(exist_ok=True)
    model = make_model(args.net)
    n_params = sum(p.numel() for p in model.policy.parameters())
    print(f"开始 Boss 专家训练：网络 {args.net}（{n_params / 1e6:.1f}M 参数）")
    print(f"{args.steps} 步（训练种子 {TRAIN_SEED}，γ=0.99）")
    from stable_baselines3.common.callbacks import CallbackList

    train_log = _TrainLogCallback(args.log_every)
    periodic = _PeriodicEvalCallback(args.eval_every)
    model.learn(
        total_timesteps=args.steps, callback=CallbackList([train_log.cb, periodic.cb])
    )
    model_path = MODEL_DIR / f"{args.out}.zip"
    model.save(model_path)
    print(f"\n模型已保存：{model_path}")

    if train_log.history:
        print("\n训练过程曲线（每 {:d} 步）:".format(args.log_every))
        for rec in train_log.history:
            print(
                f"    {rec['t']:>9d}  ep_rew={rec['ep_rew']:.2f}  ep_len={rec['ep_len']:.0f}  "
                f"loss={rec['loss']:.4f}  H={rec['entropy']:.3f}  kl={rec['kl']:.4f}  ev={rec['ev']:.2f}"
            )
    if periodic.history:
        print("\n周期评估：")
        for t, rec in periodic.history:
            print(f"    {t:>9d}  reward={rec['reward']:.2f}  win={rec['win_rate']:.2f}")

    print("\n==== 最终对比（评估种子 70..99）====")
    evaluate(random_policy, EVAL_SEEDS_FINAL, "random")
    evaluate(heuristic_policy, EVAL_SEEDS_FINAL, "heuristic")

    from sb3_contrib import MaskablePPO

    m = MaskablePPO.load(model_path)

    def ppo_policy(env: StsBossEnv) -> int:
        a, _ = m.predict(env._battle_obs(), deterministic=True, action_masks=env.action_masks())
        return int(a)

    evaluate(ppo_policy, EVAL_SEEDS_FINAL, "MaskablePPO")


if __name__ == "__main__":
    main()

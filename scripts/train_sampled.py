"""采样式环境 MaskablePPO 训练（批次 5c v3，2026-10-08 用户重设计）。

用法：uv run python scripts/train_sampled.py --difficulties all --steps 1000000

StsSampledEnv：每场独立（入场状态按难度参数表采样），单场 episode
短（~30-150 步），γ=0.99 短视野即够——v1/v2 连续 run 结构的跨场
credit 问题不复存在。混合难度（默认）每局随机抽一档。
"""

from __future__ import annotations

import argparse
import sys
from collections import defaultdict
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from sts.baselines import heuristic_policy, random_policy
from sts.sampled_env import StsSampledEnv

TRAIN_SEED = 10_000
EVAL_SEEDS_PERIODIC = list(range(70, 80))
EVAL_SEEDS_FINAL = list(range(70, 100))
MODEL_DIR = Path(__file__).resolve().parent.parent / "models"
DEFAULT_NET = [512, 256]


def run_episode(env: StsSampledEnv, policy, seed: int, max_steps: int = 800) -> dict:
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
    return {"reward": total, "won": bool(info["won"]), "difficulty": info["difficulty"]}


def evaluate(policy, seeds, verbose_name: str | None = None) -> dict:
    env = StsSampledEnv()
    eps = [run_episode(env, policy, s) for s in seeds]
    per_diff: dict[str, list[dict]] = defaultdict(list)
    for e in eps:
        per_diff[e["difficulty"]].append(e)
    out = {
        "reward": float(np.mean([e["reward"] for e in eps])),
        "win_rate": float(np.mean([e["won"] for e in eps])),
        "per_difficulty": {
            d: {
                "n": len(lst),
                "reward": float(np.mean([e["reward"] for e in lst])),
                "win_rate": float(np.mean([e["won"] for e in lst])),
            }
            for d, lst in sorted(per_diff.items())
        },
    }
    if verbose_name:
        print(f"  [{verbose_name:12s}] 平均奖励 {out['reward']:.2f}  胜率 {out['win_rate']:.2f}")
        for d, st in out["per_difficulty"].items():
            print(
                f"      {d:6s} n={st['n']:3d}  奖励 {st['reward']:.2f}  胜率 {st['win_rate']:.2f}"
            )
    return out


class _TrainLogCallback:
    """训练过程日志（20k 步一次，口径同 train_run.py，含看门狗喂狗）。"""

    def __init__(self, every: int, watchdog):
        from stable_baselines3.common.callbacks import BaseCallback

        outer = self
        self.every = every
        self.watchdog = watchdog
        self.history: list[dict] = []

        class _Cb(BaseCallback):
            def __init__(self):
                super().__init__()
                self._next = every

            def _on_step(self) -> bool:
                outer.watchdog.feed()
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
                    import time

                    print(
                        f"    [训练] {rec['t']:>9d} 步 {time.strftime('%H:%M:%S')}  ep_rew={rec['ep_rew']:.2f}  "
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
        self.eval_env = StsSampledEnv()
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
                            if term or trunc or steps >= 800:
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


def parse_net(s: str) -> list[int]:
    return [int(x) for x in s.split(",")]


def parse_difficulties(s: str):
    if s == "all":
        return ("weak", "strong", "elite", "boss")
    diffs = tuple(s.split(","))
    for d in diffs:
        if d not in ("weak", "strong", "elite", "boss"):
            raise ValueError(f"未知难度 {d}")
    return diffs


def make_model(net_arch: list[int], difficulties):
    from sb3_contrib import MaskablePPO
    from stable_baselines3.common.monitor import Monitor

    env = Monitor(StsSampledEnv(difficulties))
    return MaskablePPO(
        "MlpPolicy",
        env,
        policy_kwargs={"net_arch": dict(pi=list(net_arch), vf=list(net_arch))},
        learning_rate=1e-4,  # 大负尾巴奖励（Boss ×5 → ±3.5 级）下 3e-4 塌缩
        n_steps=1024,
        batch_size=512,
        gamma=0.99,  # 单场 episode
        gae_lambda=0.95,
        ent_coef=0.01,  # 等权对照验证 0.01 健康（塌缩源是尺度悬殊非熵不足）
        normalize_advantage=True,  # 批内 advantage 标准化：对冲难度间残余尺度差
        n_epochs=10,
        verbose=0,
        seed=TRAIN_SEED,
    )


def main() -> None:
    parser = argparse.ArgumentParser(description="采样式环境 MaskablePPO 训练")
    parser.add_argument("--steps", type=int, default=1_000_000)
    parser.add_argument("--eval-every", type=int, default=100_000)
    parser.add_argument("--log-every", type=int, default=20_000)
    parser.add_argument("--net", type=parse_net, default=DEFAULT_NET)
    parser.add_argument("--difficulties", type=parse_difficulties, default="all")
    parser.add_argument("--out", default=None)
    parser.add_argument("--eval-only", type=str, default=None)
    args = parser.parse_args()
    out = args.out or f"sampled_{'_'.join(args.difficulties)}_v1"

    if args.eval_only:
        print(f"==== 评估 {args.eval_only}（种子 70..99）====")
        evaluate(random_policy, EVAL_SEEDS_FINAL, "random")
        evaluate(heuristic_policy, EVAL_SEEDS_FINAL, "heuristic")
        from sb3_contrib import MaskablePPO

        m = MaskablePPO.load(args.eval_only)

        def ppo_policy(env: StsSampledEnv) -> int:
            a, _ = m.predict(env._get_obs(), deterministic=True, action_masks=env.action_masks())
            return int(a)

        evaluate(ppo_policy, EVAL_SEEDS_FINAL, "MaskablePPO")
        return

    MODEL_DIR.mkdir(exist_ok=True)
    from scripts.train_run import _ProgressWatchdog as _Wd

    watchdog = _Wd()
    model = make_model(args.net, args.difficulties)
    n_params = sum(p.numel() for p in model.policy.parameters())
    print(f"开始采样式训练：网络 {args.net}（{n_params / 1e6:.1f}M 参数），难度 {args.difficulties}")
    print(f"{args.steps} 步（训练种子 {TRAIN_SEED}，γ=0.99）")
    from stable_baselines3.common.callbacks import CallbackList

    train_log = _TrainLogCallback(args.log_every, watchdog)
    periodic = _PeriodicEvalCallback(args.eval_every)
    model.learn(
        total_timesteps=args.steps, callback=CallbackList([train_log.cb, periodic.cb])
    )
    model_path = MODEL_DIR / f"{out}.zip"
    model.save(model_path)
    print(f"\n模型已保存：{model_path}")

    if periodic.history:
        print("\n周期评估：")
        for t, rec in periodic.history:
            print(f"    {t:>9d}  reward={rec['reward']:.2f}  win={rec['win_rate']:.2f}")

    print("\n==== 最终对比（评估种子 70..99）====")
    evaluate(random_policy, EVAL_SEEDS_FINAL, "random")
    evaluate(heuristic_policy, EVAL_SEEDS_FINAL, "heuristic")

    from sb3_contrib import MaskablePPO

    m = MaskablePPO.load(model_path)

    def ppo_policy(env: StsSampledEnv) -> int:
        a, _ = m.predict(env._get_obs(), deterministic=True, action_masks=env.action_masks())
        return int(a)

    evaluate(ppo_policy, EVAL_SEEDS_FINAL, "MaskablePPO")


if __name__ == "__main__":
    main()

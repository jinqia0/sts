"""迷你局 MaskablePPO 训练（批次 5c，2026-10-08）。

用法：uv run python scripts/train_run.py --steps 2000000 --out run_v1

与 scripts/train.py（单场）的差异：
- 环境 StsRunEnv（8 场迷你局：3 弱→精英→2 强→精英→Boss + 局外掉落，
  奖励 = 逐场剩血求和，基数固定 80——2026-10-08 用户纠错口径）
- 网络大幅扩容：观测 12444 维（单场版 691 维的 18 倍），默认
  [64,64] MLP 是瓶颈层——[1024, 512]（~1350 万参数），铁甲全内容
  的卡牌/遗物/药水词表信息才装得下
- episode 变长（~200-500 步 vs 单场 30-60）：γ 0.99→0.995（跨场
  credit），n_steps 512→2048（一个 rollout 覆盖多条完整 run）
- 周期评估走 run 级指标（平均奖励/最远场次/通关率），种子 70..79
  （10 条 run，评估开销可控）；最终对照 70..99 全集 vs 双 baseline
"""

from __future__ import annotations

import argparse
import faulthandler
import os
import signal
import sys
import threading
import time
from collections import defaultdict
from pathlib import Path

import numpy as np

# 可按需发 SIGUSR1 转储全部线程 Python 栈到 stderr（诊断卡死）
faulthandler.register(signal.SIGUSR1, all_threads=True)

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from sts.baselines import heuristic_policy, random_policy
from sts.run_env import StsRunEnv

TRAIN_SEED = 10_000
EVAL_SEEDS_PERIODIC = list(range(70, 80))  # 训练中（10 条 run，控评估开销）
EVAL_SEEDS_FINAL = list(range(70, 100))
MODEL_DIR = Path(__file__).resolve().parent.parent / "models"
LOG_DIR = MODEL_DIR / "logs"

# 网络结构（大幅扩容，模块头说明）
NET_ARCH = dict(pi=[1024, 512], vf=[1024, 512])


def parse_net(s: str) -> dict:
    """CLI "--net 1024,512" → SB3 net_arch dict（pi/vf 同构）。"""
    layers = [int(x) for x in s.split(",")]
    return dict(pi=layers, vf=list(layers))


def run_episode(env: StsRunEnv, policy, seed: int, max_steps: int = 4000) -> dict:
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
        "battle_no": info["battle_no"],
        "run_won": bool(info["run_won"]),
    }


def evaluate(policy, seeds, verbose_name: str | None = None) -> dict:
    env = StsRunEnv()
    eps = [run_episode(env, policy, s) for s in seeds]
    # 按死亡场次分桶（短板分析用）
    buckets = defaultdict(int)
    for e in eps:
        buckets[e["battle_no"] if not e["run_won"] else "通关"] += 1
    out = {
        "reward": float(np.mean([e["reward"] for e in eps])),
        "win_rate": float(np.mean([e["run_won"] for e in eps])),
        "furthest": int(max(e["battle_no"] for e in eps)),
        "death_by_battle": dict(buckets),
    }
    if verbose_name:
        print(
            f"  [{verbose_name:12s}] 平均奖励 {out['reward']:.2f}  "
            f"通关率 {out['win_rate']:.2f}  最远场次 {out['furthest'] + 1}"
        )
        print(f"      终局分布（按场次，0 起）: {dict(sorted(buckets.items(), key=str))}")
    return out


class _ProgressWatchdog:
    """心跳看门狗（2026-10-08）：run_v1 曾在 ~340k 步卡死 48 分钟
    （CPU 满载、零日志——sample 显示 libomp barrier 特征，疑似
    torch/OpenMP 线程活锁）。机制：每步回调喂狗；独立线程每 10s 检查，
    超过 grace 秒无心跳 → faulthandler 转储全线程栈到 stderr 并
    os._exit(1)（fail fast：链式脚本继续跑后续实验，日志留现场）。
    """

    def __init__(self, grace: float = 120.0):
        self._last = time.monotonic()
        self._grace = grace
        self._stop = threading.Event()

        def _watch() -> None:
            while not self._stop.wait(10.0):
                if time.monotonic() - self._last > self._grace:
                    print(
                        f"\n[看门狗] {self._grace:.0f}s 无心跳，转储线程栈后退出",
                        file=sys.stderr,
                        flush=True,
                    )
                    faulthandler.dump_traceback(file=sys.stderr, all_threads=True)
                    os._exit(1)

        threading.Thread(target=_watch, daemon=True, name="watchdog").start()

    def feed(self) -> None:
        self._last = time.monotonic()


class _TrainLogCallback:
    """训练过程日志：每 log_every 步打一行 SB3 logger 的训练指标
    （ep_rew_mean / ep_len / loss / entropy / approx_kl / explained_variance）。
    2026-10-08 用户要求：20k 步一次，看得到训练进程而非只有周期评估。"""

    def __init__(self, every: int, watchdog: "_ProgressWatchdog"):
        from stable_baselines3.common.callbacks import BaseCallback

        outer = self
        self.every = every
        self.watchdog = watchdog
        self.history: list[tuple[int, dict]] = []

        class _Cb(BaseCallback):
            def __init__(self):
                super().__init__()
                self._next = every

            def _on_step(self) -> bool:
                outer.watchdog.feed()
                if self.num_timesteps >= self._next:
                    v = self.model.logger.name_to_value
                    # rollout 指标直接读 Monitor 的回合缓冲（verbose=0 时
                    # SB3 不 record/dump rollout/*，logger 里没有）
                    buf = getattr(self.model, "ep_info_buffer", None) or []
                    # MaskablePPO 的 buffer 条目是扁平 dict {'r','l','t'}（Monitor
                    # 的 'episode' 已在 _update_info_buffer 拆包）
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
                        f"    [训练] {rec['t']:>9d} 步 {time.strftime('%H:%M:%S')}  ep_rew={rec['ep_rew']:.2f}  "
                        f"ep_len={rec['ep_len']:.0f}  loss={rec['loss']:.4f}  "
                        f"H={rec['entropy']:.3f}  kl={rec['kl']:.4f}  ev={rec['ev']:.2f}",
                        flush=True,
                    )
                    self._next += every
                return True

        self.cb = _Cb()


class _PeriodicEvalCallback:
    """训练中的周期评估（独立 env 实例，不打断采样流）。"""

    def __init__(self, every: int):
        from stable_baselines3.common.callbacks import BaseCallback

        outer = self
        self.every = every
        self.eval_env = StsRunEnv()
        self.history: list[tuple[int, dict]] = []

        class _Cb(BaseCallback):
            def _on_step(self) -> bool:
                if self.num_timesteps % outer.every == 0 and self.n_calls > 1:
                    rec = {"t": self.num_timesteps, "reward": 0.0, "win_rate": 0.0, "furthest": 0}
                    for s in EVAL_SEEDS_PERIODIC:
                        obs, info = outer.eval_env.reset(seed=s)
                        done, steps = False, 0
                        while not done:
                            mask = outer.eval_env.action_masks()
                            action, _ = self.model.predict(obs, deterministic=True, action_masks=mask)
                            obs, rew, term, trunc, info = outer.eval_env.step(int(action))
                            rec["reward"] += rew
                            rec["furthest"] = max(rec["furthest"], info["battle_no"])
                            steps += 1
                            if term or trunc or steps >= 4000:
                                done = True
                        rec["win_rate"] += bool(info["run_won"])
                    n = len(EVAL_SEEDS_PERIODIC)
                    for k in ("reward", "win_rate"):
                        rec[k] /= n
                    outer.history.append((self.num_timesteps, dict(rec)))
                    print(
                        f"    {rec['t']:>9d} 步  奖励 {rec['reward']:.2f}  "
                        f"通关 {rec['win_rate']:.2f}  最远第 {rec['furthest'] + 1} 场",
                        flush=True,
                    )
                return True

        self.cb = _Cb()


def make_model(net_arch: dict | None = None) -> "MaskablePPO":
    from sb3_contrib import MaskablePPO
    from stable_baselines3.common.monitor import Monitor

    # Monitor 包装：启用 ep_rew_mean / ep_len_mean 的回合统计（SB3
    # logger 的 rollout 指标依赖 Monitor 的 episode info）
    env = Monitor(StsRunEnv())
    return MaskablePPO(
        "MlpPolicy",
        env,
        policy_kwargs={"net_arch": net_arch or NET_ARCH},
        learning_rate=1e-4,  # v2 奖励大负尾巴下 3e-4 诱发早期策略塌缩（H→0）
        n_steps=2048,
        batch_size=512,
        gamma=0.995,  # 迷你局 episode 数百步，跨场 credit
        gae_lambda=0.95,
        ent_coef=0.02,  # v2 死亡惩罚尺度下的熵支撑（0.01 曾塌缩到 H≈0）
        n_epochs=10,
        verbose=0,
        seed=TRAIN_SEED,
    )


def main() -> None:
    parser = argparse.ArgumentParser(description="迷你局 MaskablePPO 训练（StsRunEnv）")
    parser.add_argument("--steps", type=int, default=2_000_000)
    parser.add_argument("--eval-every", type=int, default=100_000)
    parser.add_argument("--log-every", type=int, default=20_000, help="训练日志间隔（步）")
    parser.add_argument("--net", type=parse_net, default=None, help='网络隐藏层，如 "1024,512"（默认 [1024,512]）')
    parser.add_argument("--out", default="run_v1")
    parser.add_argument("--eval-only", type=str, default=None)
    args = parser.parse_args()

    if args.eval_only:
        print(f"==== 评估 {args.eval_only}（种子 70..99，run 级口径）====")
        evaluate(lambda e: random_policy(e._battle), EVAL_SEEDS_FINAL, "random")
        evaluate(lambda e: heuristic_policy(e._battle), EVAL_SEEDS_FINAL, "heuristic")
        from sb3_contrib import MaskablePPO

        m = MaskablePPO.load(args.eval_only)

        def ppo_policy(env: StsRunEnv) -> int:
            a, _ = m.predict(env._get_obs(), deterministic=True, action_masks=env.action_masks())
            return int(a)

        evaluate(ppo_policy, EVAL_SEEDS_FINAL, "MaskablePPO")
        return

    MODEL_DIR.mkdir(exist_ok=True)
    LOG_DIR.mkdir(exist_ok=True)
    model = make_model(args.net)
    n_params = sum(p.numel() for p in model.policy.parameters())
    net = args.net or NET_ARCH
    print(f"开始迷你局训练：网络 {net}（{n_params / 1e6:.1f}M 参数）")
    print(f"{args.steps} 步（训练种子 {TRAIN_SEED}，周期评估种子 70..79，γ=0.995）")
    watchdog = _ProgressWatchdog()
    periodic = _PeriodicEvalCallback(args.eval_every)
    train_log = _TrainLogCallback(args.log_every, watchdog)
    from stable_baselines3.common.callbacks import CallbackList

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
        print("\n训练曲线（主指标：平均奖励，上界 8）：")
        for t, rec in periodic.history:
            print(
                f"    {t:>9d}  reward={rec['reward']:.2f}  win={rec['win_rate']:.2f}  "
                f"furthest={rec['furthest'] + 1}"
            )

    print("\n==== 最终对比（评估种子 70..99）====")
    evaluate(lambda e: random_policy(e._battle), EVAL_SEEDS_FINAL, "random")
    evaluate(lambda e: heuristic_policy(e._battle), EVAL_SEEDS_FINAL, "heuristic")

    from sb3_contrib import MaskablePPO

    m = MaskablePPO.load(model_path)

    def ppo_policy(env: StsRunEnv) -> int:
        a, _ = m.predict(env._get_obs(), deterministic=True, action_masks=env.action_masks())
        return int(a)

    evaluate(ppo_policy, EVAL_SEEDS_FINAL, "MaskablePPO")


if __name__ == "__main__":
    main()

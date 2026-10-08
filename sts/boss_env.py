"""Boss 专家训练环境（批次 5c，2026-10-08，用户指令）。

动机：run 训练中只有活到第 8 场的轨迹才含 Boss 样本（早期不足 5%
的梯度信号流向 Boss 战斗），且无局外学习可复用——Boss 应对策略
数据稀缺。方案：**按概率模拟 Boss 入场状态，单独训练 Boss 专家**。

入场状态构成（两条来源，见模块头设计说明）：
- 牌组/遗物/药水/保底计数器：run 层精确 RNG 逻辑重放（选牌/掉落与
  策略无关，分布天然正确——StsRunEnv 的 _drop_relic/_roll_potion_drop/
  _card_reward 逐场快进）
- HP：按 sts/boss_entry_costs.json 的实测条件分布采样（外层 PPO 策略
  到达 Boss 的轨迹上逐场净损耗；scripts/estimate_boss_entry.py 生成）。
  火堆（30% max_hp ×3）按 run 结构如实结算

Boss 池 = guardian / hexaghost / slime_boss 均匀抽一。

奖励口径：与 run 层一致——胜 = 结束时实际 HP / 80（REWARD_HP_BASE，
与实时 max_hp 解耦），败/截断 0。动作/观测/信息边界完全透传
StsBattleEnv（12428 维观测 / 120 动作，5a/5b 的边界保证直接继承）。
"""

from __future__ import annotations

import json
import pathlib

import gymnasium as gym
import numpy as np
from gymnasium import spaces

from sts.combat.types import Outcome
from sts.env import (
    N_ACTIONS,
    OBSERVATION_MAXIMUMS,
    OBSERVATION_MINIMUMS,
    OBS_DIM,
    TURN_LIMIT,
    StsBattleEnv,
)
from sts.run_env import (
    CAMPFIRE_BEFORE,
    CAMPFIRE_HEAL_FRACTION,
    PROGRESS_CREDIT,
    REWARD_HP_BASE,
    RUN_STRUCTURE,
    StsRunEnv,
    WIN_BONUS,
)

_COSTS_PATH = pathlib.Path(__file__).parent / "boss_entry_costs.json"

# 兜底分布（JSON 缺失/为空时）：宽区间均匀——宁可覆盖过宽不可漏尾
_FALLBACK_COSTS = {"weak": (0, 10), "strong": (10, 45), "elite": (20, 70)}


def _load_costs() -> dict[str, list[int]]:
    if _COSTS_PATH.exists():
        data = json.loads(_COSTS_PATH.read_text())
        if all(data.get(k) for k in ("weak", "strong", "elite")):
            return data
    return {}


class StsBossEnv(gym.Env):
    """单场 Boss 战斗，入场状态按概率模拟（见模块头）。

    对策略而言就是一场普通战斗（12428 维观测 / 120 动作 / mask 同
    StsBattleEnv）；bc 属性暴露引擎上下文（heuristic baseline 兼容）。
    """

    metadata = {"render_modes": []}

    def __init__(self) -> None:
        self.action_space = spaces.Discrete(N_ACTIONS)
        self.observation_space = spaces.Box(
            low=np.array(OBSERVATION_MINIMUMS, dtype=np.int32),
            high=np.array(OBSERVATION_MAXIMUMS, dtype=np.int32),
            shape=(OBS_DIM,),
            dtype=np.int32,
        )
        self._run = StsRunEnv()
        self._costs = _load_costs()
        self.entry_hp = 80
        self.entry_deck_size = 10

    # ---- Gymnasium API ----

    def reset(self, *, seed: int | None = None, options: dict | None = None):
        super().reset(seed=seed)
        run_seed = int(self.np_random.integers(0, 2**31 - 1))
        run = self._run
        run.reset(seed=run_seed)  # 种下 np_random 与掉落流（battle 0 弃用）
        # ---- 快进前 7 场：火堆如实结算，HP 按实测条件分布扣损，掉落走精确 RNG ----
        for k in range(len(RUN_STRUCTURE) - 1):
            if k in CAMPFIRE_BEFORE:  # (3, 6)：精英 1/2 前的火堆
                heal = run.max_hp * CAMPFIRE_HEAL_FRACTION // 100
                run.hp = min(run.max_hp, run.hp + heal)
            kind = RUN_STRUCTURE[k]
            run.hp = max(1, run.hp - self._sample_cost(kind))
            if kind == "elite":
                run._drop_relic()
            run._roll_potion_drop()
            run._card_reward()  # battle_no == k：前 3 场必选语义正确
            run.battle_no = k + 1
        # ---- 第 8 场：Boss（_start_battle 内含 Boss 前火堆）----
        run._start_battle()
        self.entry_hp = run.hp
        self.entry_deck_size = len(run.deck)
        return self._battle_obs(), self._get_info()

    def step(self, action):
        obs, _r, terminated, truncated, _info = self._battle.step(action)
        bc = self._run._battle.bc
        assert bc is not None
        # 奖励口径 v2（与 run 层 Boss 场边际价值对齐，2026-10-08）：
        # 胜 = (结算HP-入场HP)/80 + 存活信用 + 通关奖金；死亡 =
        # -入场HP/80；截断 = 实际战损。入场 HP 记 entry_hp（火堆后）。
        if not (terminated or truncated):
            reward = 0.0
        elif bc.won:
            reward = (bc.player.hp - self.entry_hp) / REWARD_HP_BASE + PROGRESS_CREDIT + WIN_BONUS
        elif bc.outcome == Outcome.PLAYER_LOSS:
            reward = -self.entry_hp / REWARD_HP_BASE
        else:  # 截断（保险丝）：负信用（对齐 run 层 v2 终版）
            reward = (bc.player.hp - self.entry_hp) / REWARD_HP_BASE - PROGRESS_CREDIT
        return obs, reward, terminated, truncated, self._get_info()

    def action_masks(self) -> np.ndarray:
        return self._battle.action_masks()

    # ---- 辅助 ----

    @property
    def _battle(self) -> StsBattleEnv:
        return self._run._battle

    @property
    def bc(self):
        """引擎上下文（heuristic/random baseline 的入口约定）。"""
        return self._run._battle.bc

    def _battle_obs(self) -> np.ndarray:
        return self._run._battle._get_obs()

    def _sample_cost(self, kind: str) -> int:
        pool = self._costs.get(kind)
        if pool:
            return int(pool[self.np_random.integers(0, len(pool))])
        lo, hi = _FALLBACK_COSTS[kind]
        return int(self.np_random.integers(lo, hi + 1))

    def _get_info(self) -> dict:
        bc = self._run._battle.bc
        assert bc is not None
        return {
            "encounter": self._run._current_encounter,
            "hp_remaining": bc.player.hp,
            "entry_hp": self.entry_hp,
            "entry_deck_size": self.entry_deck_size,
            "relics": [r.name for r in self._run.relics],
            "potions": [pd.pid if pd else None for pd in self._run.potions],
            "won": bc.won,
            "outcome": bc.outcome.name,
        }

"""采样式战斗环境（批次 5c v3，2026-10-08 用户重设计）。

放弃「8 场连续 run」的整体性（v1/v2 的连续结构使跨场 credit 与拖延
问题纠缠），改为**每场独立采样**：入场状态（牌组/药水/HP/遗物）按
难度参数化的分布随机生成，保留「按场结算」但以难度权重体现递进——
一场一个 episode，难度从环境配置读出，策略在独立同分布上学习
「给定状态怎么打好这一场」。

难度参数表（用户设定，2026-10-08）：

    参数              弱怪      强怪      精英      Boss
    遭遇池            WEAK      STRONG    ELITES    BOSSES
    回报权重          0.3       0.5       1         5
    入场 HP           60-80     40-80     30-70     25-70
    药水/栏概率       10%       20%       50%       70%
    新增卡（非基础）  0-2       2-5       3-7       3-8
    卡升级概率        30%       30%       30%       30%
    移除基础打/防     0         0-1       0-2       0-2
    遗物数            0         0-1       0-2       0-3

- 移除只作用于初始 10 张（5 打击 / 4 防御 / 1 痛击）中的打击/防御
  （模拟删牌服务——本体也优先删基础牌；痛击不动）
- 遗物沿用源码 tier 池（50% common / 32% uncommon / 17% rare，去重）
- 新增卡从铁甲奖励池（20 common / 36 uncommon / 17 rare）按 3/37/60
  + 保底计数器 roll——run_env 的 _card_reward 同款口径

奖励（按场结算，用户决策）：胜 = 实际HP/80 × 难度权重；败 = −入场
HP/80 × 权重；截断 = 负信用同败（拖延防护沿用 v2 终版结论）。单场
episode 无跨场项，γ=0.99 短视野即够。
"""

from __future__ import annotations

import gymnasium as gym
import numpy as np
from gymnasium import spaces

from sts.combat.relics import RelicId
from sts.combat.types import Outcome
from sts.env import (
    N_ACTIONS,
    OBSERVATION_MAXIMUMS,
    OBSERVATION_MINIMUMS,
    OBS_DIM,
    StsBattleEnv,
)
from sts.rng import RngStreams
from sts.run_env import (
    BOSSES,
    CARD_POOLS,
    CARD_PITY_FLOOR,
    CARD_PITY_GROWTH,
    CARD_PITY_START,
    CARD_RARE,
    ELITES,
    RELIC_POOLS,
    RELIC_TIER_COMMON,
    RELIC_TIER_RARE,
    STRONG_POOL,
    WEAK_POOL,
)

# ---- 难度参数表（用户设定，模块头）----
DIFFICULTY_SPECS: dict[str, dict] = {
    # weight：用户设定 0.3/0.5/1/5 → 2026-10-08 实测塌缩后与用户确认改为
    # 0.3/0.5/1/2。Boss×5 的 12 倍回报尺度悬殊是策略塌缩元凶（受控实验：
    # 等权对照 100k 步全程健康 vs 原权重 60k 步 H→0）；×2 保住「Boss 最
    # 重要」语义（极差 6.7 倍）+ normalize_advantage 对冲残余尺度差
    "weak": {
        "pool": WEAK_POOL, "weight": 0.3, "hp": (60, 80), "potion_p": 10,
        "extra_cards": (0, 2), "removes": (0, 0), "relics": (0, 0),
    },
    "strong": {
        "pool": STRONG_POOL, "weight": 0.5, "hp": (40, 80), "potion_p": 20,
        "extra_cards": (2, 5), "removes": (0, 1), "relics": (0, 1),
    },
    "elite": {
        "pool": ELITES, "weight": 1.0, "hp": (30, 70), "potion_p": 50,
        "extra_cards": (3, 7), "removes": (0, 2), "relics": (0, 2),
    },
    "boss": {
        "pool": BOSSES, "weight": 2.0, "hp": (25, 70), "potion_p": 70,
        "extra_cards": (3, 8), "removes": (0, 2), "relics": (0, 3),
    },
}

UPGRADE_CHANCE = 30  # 每张新增卡 30% 升级版（用户设定，四难度同）

# 卡牌稀有度 roll 常量（run_env 同款源码口径）
_RARE = CARD_RARE
_UNCOMMON_TOTAL = CARD_RARE + 37
_COMMON_TOTAL = 100


class StsSampledEnv(gym.Env):
    """采样式单场战斗：入场状态按难度分布生成，按场结算加权回报。

    一个 episode = 一场战斗。对策略而言与 StsBattleEnv 同构
    （12428 维观测 / 120 动作 / mask 全透传），差异只在 reset 的
    入场状态构造与 step 的奖励结算。bc 属性暴露引擎上下文。
    """

    metadata = {"render_modes": []}

    def __init__(self, difficulty: str | tuple[str, ...] = ("weak", "strong", "elite", "boss")) -> None:
        """difficulty：单难度名（专训，如 "boss"）或难度元组（每局
        随机抽一档——混合训练）。"""
        if isinstance(difficulty, str):
            self.difficulties = (difficulty,)
        else:
            self.difficulties = tuple(difficulty)
        for d in self.difficulties:
            if d not in DIFFICULTY_SPECS:
                raise ValueError(f"未知难度：{d}（可选：{sorted(DIFFICULTY_SPECS)}）")
        self.action_space = spaces.Discrete(N_ACTIONS)
        self.observation_space = spaces.Box(
            low=np.array(OBSERVATION_MINIMUMS, dtype=np.int32),
            high=np.array(OBSERVATION_MAXIMUMS, dtype=np.int32),
            shape=(OBS_DIM,),
            dtype=np.int32,
        )
        self._battle = StsBattleEnv()
        self.rngs: RngStreams | None = None
        self.difficulty = self.difficulties[0]
        self.entry_hp = 80
        self._current_encounter = ""

    # ---- Gymnasium API ----

    def reset(self, *, seed: int | None = None, options: dict | None = None):
        super().reset(seed=seed)
        run_seed = int(self.np_random.integers(0, 2**31 - 1))
        self.rngs = RngStreams(run_seed)
        self.difficulty = self.difficulties[int(self.np_random.integers(0, len(self.difficulties)))]
        spec = DIFFICULTY_SPECS[self.difficulty]
        # ---- 入场状态采样 ----
        hp_lo, hp_hi = spec["hp"]
        self.entry_hp = int(self.rngs.misc.int_inclusive(hp_lo, hp_hi))
        deck = self._sample_deck(spec)
        relics = self._sample_relics(spec)
        potions = self._sample_potions(spec)
        encounter = spec["pool"][self.rngs.misc.int_inclusive(0, len(spec["pool"]) - 1)]
        battle_seed = int(self.np_random.integers(0, 2**31 - 1))
        self._battle.__init__(
            encounter=encounter,
            relics=relics or None,
            potions=potions or None,
            deck=deck,
        )
        self._battle.reset(seed=battle_seed)
        bc = self._battle.bc
        bc.player.hp = self.entry_hp
        self._current_encounter = encounter
        return self._get_obs(), self._get_info()

    def step(self, action):
        obs, _r, terminated, truncated, _info = self._battle.step(action)
        bc = self._battle.bc
        assert bc is not None
        weight = DIFFICULTY_SPECS[self.difficulty]["weight"]
        if not (terminated or truncated):
            reward = 0.0
        elif bc.won:
            reward = bc.player.hp / 80 * weight
        elif bc.outcome == Outcome.PLAYER_LOSS:
            reward = -self.entry_hp / 80 * weight
        else:  # 截断：负信用同败（拖延防护，v2 终版结论沿用）
            reward = -self.entry_hp / 80 * weight
        return obs, reward, terminated, truncated, self._get_info()

    def action_masks(self) -> np.ndarray:
        return self._battle.action_masks()

    # ---- 采样器 ----

    def _sample_deck(self, spec: dict) -> list:
        """初始 10 张 − 随机删（打/防）+ 随机增（奖励池 + 30% 升级）。
        痛击不动（唯一非基础起始牌）。"""
        from sts.content.cards.ironclad import BASH, DEFEND, STRIKE

        rng = self.rngs.misc
        deck: list = [STRIKE] * 5 + [DEFEND] * 4 + [BASH]
        lo, hi = spec["removes"]
        n_rm = rng.int_inclusive(lo, hi)
        basics = [c for c in deck if c is STRIKE or c is DEFEND]
        for _ in range(min(n_rm, len(basics))):
            victim = basics[rng.int_inclusive(0, len(basics) - 1)]
            deck.remove(victim)
            basics.remove(victim)
        lo, hi = spec["extra_cards"]
        n_add = rng.int_inclusive(lo, hi)
        pity = CARD_PITY_START
        for _ in range(n_add):
            roll = rng.int_inclusive(0, 99) + pity
            if roll < _RARE:
                rar, pity = "rare", CARD_PITY_START
            elif roll < _UNCOMMON_TOTAL:
                rar = "uncommon"
            else:
                rar = "common"
                pity = max(CARD_PITY_FLOOR, pity - CARD_PITY_GROWTH)
            pool = CARD_POOLS[rar]
            deck.append(pool[rng.int_inclusive(0, len(pool) - 1)])
        return deck

    def _sample_relics(self, spec: dict) -> list[RelicId]:
        rng = self.rngs.misc
        lo, hi = spec["relics"]
        n = rng.int_inclusive(lo, hi)
        out: list[RelicId] = []
        for _ in range(n):
            roll = rng.int_inclusive(0, 99)
            tier = "COMMON" if roll < RELIC_TIER_COMMON else ("RARE" if roll > RELIC_TIER_RARE else "UNCOMMON")
            pool = [r for r in RELIC_POOLS[tier] if r not in out]
            if not pool:
                for alt in ("COMMON", "UNCOMMON", "RARE"):
                    pool = [r for r in RELIC_POOLS[alt] if r not in out]
                    if pool:
                        break
            if pool:
                out.append(pool[rng.int_inclusive(0, len(pool) - 1)])
        return out

    def _sample_potions(self, spec: dict) -> list:
        """每栏独立 p 概率给一瓶（稀有度 65/25/10，铁甲池 33）。"""
        from sts.content.potions import IRONCLAD_POTION_POOL

        rng = self.rngs.misc
        out = []
        for _slot in range(3):
            if rng.int_inclusive(0, 99) < spec["potion_p"]:
                roll = rng.int_inclusive(0, 99)
                rar = "common" if roll < 65 else ("uncommon" if roll < 90 else "rare")
                pool = [p for p in IRONCLAD_POTION_POOL if p.rarity == rar]
                out.append(pool[rng.int_inclusive(0, len(pool) - 1)])
        return out

    # ---- 观测/info ----

    @property
    def bc(self):
        return self._battle.bc

    def _get_obs(self) -> np.ndarray:
        return self._battle._get_obs()

    def _get_info(self) -> dict:
        bc = self._battle.bc
        assert bc is not None
        return {
            "encounter": self._current_encounter,
            "difficulty": self.difficulty,
            "entry_hp": self.entry_hp,
            "hp_remaining": bc.player.hp,
            "won": bc.won,
            "outcome": bc.outcome.name,
        }

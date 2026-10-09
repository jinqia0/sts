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

奖励（2026-10-09 用户决策，事件计价塑形）：终局 = 胜 −战损 × 权重 /
败截断 −(入场HP + 怪物剩余总血量) × 权重；每步事件分叠加——奖励：
造成伤害(+0.1/点) / 格挡吸收(+1/点) / 击杀(+5) / 状态资产增量
(Power 牌按未来收益贴现入账)；惩罚：受到伤害(−1/点) / 溢出格挡
(−0.5/点)。事件分改变最优策略（理论风险由对照实验检验）。设计
动机：势函数塑形实测阴性（EXP-11）——Φ 只覆盖 HP 差，格挡校准
（实测 44% 溢出 + 51% 漏防）无就地信号；Power 牌收益延迟且复合，
逐事件口径当步净负，故状态资产单独入账。已知近似：怪物分裂使
mhp 出现负差已由 max 钳制；溢出检测用「turn 推进 + block 归零」。
单场 episode 无跨场项，γ=0.99 短视野即够。
"""

from __future__ import annotations

import gymnasium as gym
import numpy as np
from gymnasium import spaces

from sts.combat.relics import RelicId
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

# Boss 专训冷启动变体（2026-10-08 用户决策）：难度名 "boss1000"——
# 参数同 boss 但 HP 恒 1000。破「全输局 value 无方差」死锁：高血量
# Boss 战可赢 → value 有信号 → 策略先学会打 Boss 的输出/格挡节奏，
# 后续退火回正常血量区间。
DIFFICULTY_SPECS["boss1000"] = dict(DIFFICULTY_SPECS["boss"], hp=(1000, 1000))

# ---- 随机预训练档（2026-10-09 用户决策）----
# 「认牌」预训练：实测旧卡组构成（基础 10 张打底 + 新增 ≤8 张）下
# 非基础卡曝光密度过低，模型不认识绝大多数卡。random 档把变量收拢
# 到「卡牌 × 怪物」本身：全池均匀 20~30 张卡组（30% 升级位）、遭遇
# 从全部 21 场（含 Boss）均匀抽、移除药水/遗物/随机 HP（固定 80 满
# 血入场）。收敛后接回真实分布卡组的分档微调。
RANDOM_DECK_SIZE = (20, 30)
UNIFORM_DECK_EXCLUDE = {"Burn", "Dazed", "Wound"}  # 状态牌是战斗内动态牌，不进初始卡组（与本体一致）
_UNIFORM_DECK_POOL: list | None = None  # 懒构建：全池均匀牌池（75 张可玩铁甲牌）

DIFFICULTY_SPECS["random"] = {
    "pool": WEAK_POOL + STRONG_POOL + ELITES + BOSSES,
    "weight": 1.0, "hp": (80, 80), "potion_p": 0,
    "extra_cards": (0, 0), "removes": (0, 0), "relics": (0, 0),
    "uniform_deck": True,
}

UPGRADE_CHANCE = 30  # 每张新增卡 30% 升级版（用户设定，四难度同）

# ---- 事件计价常量（2026-10-09 用户决策）----
# 逐事件：造成伤害/格挡吸收/击杀 +，受到伤害/溢出格挡 −；状态资产
# （方案 A，用户确认「能力牌类的奖励」问法后的设计）：Power 牌的
# 收益延迟且复合（Demon Form 之后每回合 +2 力量），逐事件口径下
# 打出 Power 当步净负——会系统性压制 Power。状态资产入 Φ 解决：
# 打出 Power 时按「未来收益贴现」立刻入账，后续逐回合变现走事件分。
# 系数标定：事件分 1 点 HP = 1 分；力量 ≈ 每回合 1 次攻击 ×1 伤
# ×~5 回合贴现 ≈ 3 分/层；DEMON_FORM（+层/回合）≈ 力量的 ~1/2
# 现值折半入账；METALLICIZE = 稳定格挡 1×层/回合 ≈ 1 分/层。
EVENT_SCORE = {
    "dealt": 0.1,     # 造成 1 点伤害 +0.1（终局战损口径 1:1 主导，事件分牵引节奏）
    "blocked": 1.0,   # 格挡吸收 1 点 +1（最大缺口：格挡校准就地信号）
    "kill": 5.0,      # 造成击杀 +5（节奏推进奖励）
    "taken": 1.0,     # 受到 1 点伤害 −1
    "wasted": 0.5,    # 溢出格挡 1 点 −0.5（过量防御惩罚）
}
# 状态资产系数（Φ 的玩家侧资产项）：δΦ = Σ k_s × Δ层数
STATUS_ASSET = {
    "STRENGTH": 3.0,
    "DEXTERITY": 3.0,      # 敏捷同力量对称（格挡 +1/层/防牌）
    "DEMON_FORM": 1.5,
    "METALLICIZE": 1.0,
    "BARRICADE": 2.0,      # 格挡不清零 = 资产性质（保守低配）
    "BRUTALITY": 0.5,
    "JUGGERNAUT": 1.0,
    "RUPTURE": 1.0,
    "RAGE": 0.3,
    "ARTIFACT": 2.0,
    "CORRUPTION": 0.0,     # 双刃（技能 0 费 vs 消耗）——中性，事件分自然定价
    "VIGOR": 1.0,
    "ENERGIZED": 1.0,
}

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
        if self.entry_hp > 80:  # 冷启动变体（boss1000）：上限同步抬升
            bc.player.max_hp = self.entry_hp
        bc.player.hp = self.entry_hp
        self._current_encounter = encounter
        return self._get_obs(), self._get_info()

    def step(self, action):
        bc = self._battle.bc
        assert bc is not None
        # 事件快照（动作结算前：玩家 HP/格挡/回合数/状态资产、各怪 HP/存活）
        hp0, blk0, turn0 = bc.player.hp, bc.player.block, bc.turn
        asset0 = self._status_asset(bc)
        mhp0 = [m.hp for m in bc.monsters.monsters]
        alive0 = [not m.is_dead_or_escaped() for m in bc.monsters.monsters]
        obs, _r, terminated, truncated, _info = self._battle.step(action)
        weight = DIFFICULTY_SPECS[self.difficulty]["weight"]
        # 事件计价塑形（2026-10-09 用户决策）：势函数塑形实测阴性
        # （EXP-11——Φ 只覆盖 HP 差，「格挡挡住的伤害」这一最大缺口
        # 无就地信号）。事件计价按当步事件直接给分：
        #   奖励：造成伤害 / 格挡吸收 / 造成击杀 / 状态资产增量（Power 牌）
        #   惩罚：受到伤害 / 溢出格挡（回合末清零的 block）
        # 事件分叠加在终局分之上（改变最优策略——有过度防御/刷小伤
        # 的理论风险，正是本轮要实验检验的）。
        dealt = sum(max(h0 - m.hp, 0) for h0, m in zip(mhp0, bc.monsters.monsters))
        taken = max(hp0 - bc.player.hp, 0)
        blocked = max(blk0 - bc.player.block - taken, 0)
        kills = sum(1 for a0, m in zip(alive0, bc.monsters.monsters) if a0 and m.is_dead_or_escaped())
        reward = (
            EVENT_SCORE["dealt"] * dealt
            + EVENT_SCORE["blocked"] * blocked
            + EVENT_SCORE["kill"] * kills
            - EVENT_SCORE["taken"] * taken
            + (self._status_asset(bc) - asset0)
        ) * weight
        # 溢出格挡：END_TURN 触发敌方结算，结算尾旧 block 清零、
        # 新回合 block=0——「turn 推进 + 归零」联合检测，惩罚量 =
        # 结算前存量（敌方攻击吸收已在上面 blocked 计量，这里只罚
        # 纯浪费）。怪物中途分裂等使 mhp 出现负差的情形已由 max 钳制。
        if bc.turn > turn0 and bc.player.block == 0 and blk0 > 0 and not (terminated or truncated):
            wasted = max(blk0 - blocked - taken, 0)
            reward -= EVENT_SCORE["wasted"] * wasted * weight
        if terminated or truncated:
            reward += self._terminal_reward(bc, weight)
        return obs, reward, terminated, truncated, self._get_info()

    def _status_asset(self, bc) -> float:
        """状态资产现值（Power 牌的延迟收益贴现入账）：Σ k_s × 层数。
        负向状态（VULNERABLE/WEAK/FRAIL 等）不在此计——它们通过
        事件分（多受伤害/少造成伤害）自然受罚，避免双重计价。"""
        from sts.combat.types import PlayerStatus

        s = bc.player.statuses
        return sum(k * s.get(getattr(PlayerStatus, name)) for name, k in STATUS_ASSET.items())

    def _terminal_reward(self, bc, weight: float) -> float:
        """纯战损奖励（2026-10-09 用户决策，模块头）。抽出成方法供
        测试直接构造终局态验证公式。"""
        if bc.won:
            return (bc.player.hp - self.entry_hp) * weight
        # 败/截断：入场 HP + 存活怪物剩余总血量（截断同败级定价，
        # 拖延防护沿用 v2 终版结论；剩余血量让拖延的代价只增不减）
        remaining = sum(m.hp for m in bc.monsters.monsters if m.hp > 0)
        return -(self.entry_hp + remaining) * weight

    def action_masks(self) -> np.ndarray:
        return self._battle.action_masks()

    # ---- 采样器 ----

    def _sample_deck(self, spec: dict) -> list:
        """random 档走全池均匀采样；其余档 = 初始 10 张 − 随机删
        （打/防）+ 随机增（奖励池 + 30% 升级位）。痛击不动（唯一
        非基础起始牌）。"""
        if spec.get("uniform_deck"):
            return self._sample_uniform_deck()
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
            card = pool[rng.int_inclusive(0, len(pool) - 1)]
            deck.append(self._maybe_upgrade(card))
        return deck

    def _sample_uniform_deck(self) -> list:
        """随机预训练档卡组：全池均匀 20~30 张，含基础打/防/痛击，
        排除 Burn/Dazed/Wound 状态牌，30% 升级位（(CardDef, True)
        元组——create_deck_card_in_draw_pile 的升级形式）。"""
        global _UNIFORM_DECK_POOL
        if _UNIFORM_DECK_POOL is None:
            from sts.content.cards._base import CardDef
            import sts.content.cards.ironclad as _ic

            _UNIFORM_DECK_POOL = [
                c for c in vars(_ic).values()
                if isinstance(c, CardDef) and c.name not in UNIFORM_DECK_EXCLUDE
            ]
        rng = self.rngs.misc
        lo, hi = RANDOM_DECK_SIZE
        deck = []
        for _ in range(rng.int_inclusive(lo, hi)):
            card = _UNIFORM_DECK_POOL[rng.int_inclusive(0, len(_UNIFORM_DECK_POOL) - 1)]
            deck.append(self._maybe_upgrade(card))
        return deck

    def _maybe_upgrade(self, card):
        """30% 升级位（UPGRADE_CHANCE）。bug 修复（2026-10-09）：常量
        自 5c 起声明了「30% 升级版」但从未接入采样——旧档训练的卡组里
        升级版词表维度长期为 0。升级走 (CardDef, True) 元组形式。"""
        upgraded = self.rngs.misc.int_inclusive(0, 99) < UPGRADE_CHANCE
        return (card, True) if upgraded else card

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

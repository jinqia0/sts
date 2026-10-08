"""迷你局环境（批次 5c，2026-10-07）：8 场战斗 + 局外掉落的 Gymnasium 封装。

结构（用户设定，DESIGN.md §5.3）：

    弱怪 ×3 → 精英 1 → 强怪 ×2 → 精英 2 → Boss

    · 每场胜利后：卡牌奖励（3 张按稀有度 roll，随机选 1）+ 药水掉落
      （40% + blizzard 补偿 ±10/场，槽满即弃）
    · 两次精英与 Boss 战斗前各一次火堆：回复 30% 最大生命
    · 精英战后掉落随机遗物（tier roll 50% common / 32% uncommon /
      17% rare，与已持有去重）

全部掉落预设取自本体反编译源码（sts_game_data/decompiled/，V2.3.4）：

    CampfireSleepEffect.java      火堆回血 = 30% max_hp（Regal Pillow +15
                                  本项目未迁移，略）
    AbstractRoom.addPotionToRewards   药水掉率 40% + blizzardPotionMod
                                  （掉落 -10 / 未掉 +10；奖励 ≥4 条置 0；
                                  White Beast Statue 置 100——未迁移，略）
    PotionHelper                  药水稀有度 65/25/10；铁甲池 = 3 专属
                                  + 30 通用（content/potions.py 按源码修正）
    AbstractRoom.getCardRarity    卡牌稀有度 3% rare / 37% uncommon /
                                  60% common + 保底计数器（初始 +5，出
                                  common -1 至 -40 封顶，出 rare 归 5）
    getRewardCards                奖励 3 张、奖励内同 cardID 去重、
                                  Act 1 升级概率 0%（Exordium）
    MonsterRoomBoss.getCardRarity Boss 卡牌奖励恒为 rare（本迷你局 Boss
                                  是最后一场，卡牌奖励无后续意义——仍
                                  结算，保持口径一致）
    MonsterRoomElite              精英遗物 tier roll：<50 common / >82
                                  rare / 其余 uncommon；Black Star 未迁移

随机选牌规则（用户决策）：前期（战斗 1-3）必选 1 张；后期（4-8）50%
跳过（模仿真实玩家「前期拿牌后期开始挑」）。

奖励口径（用户决策）：逐场剩血求和——每场战斗胜利时立即结算
该场剩余 HP，8 场累加；死亡或截断的场次记 0，已结算的不追回。
**归一化基数 = run 起始最大生命（80），非实时 max_hp**（2026-10-08
用户纠错）：max_hp 可变（Feed/果汁药水 +上限），与实时上限挂钩会把
「上限增长」变成奖励稀释——上限增长是正面效果，奖励只与实际 HP
相关（实际 HP 随上限同步 +，奖励自然更高）。总奖励上界 8（无增长），
上限增长可略微超过——正向偏差，保留。

信息边界：动作/观测透传 StsBattleEnv（战斗内边界由 5a/5b 保证）；
局外掉落发生在战斗间隙（无决策点），run 特征段（战斗序号/下一场
类型）是玩家在真实游戏里可见的地图信息。
"""

from __future__ import annotations

import gymnasium as gym
import numpy as np
from gymnasium import spaces

from sts.combat.battle import BattleContext
from sts.combat.relics import RelicId
from sts.combat.types import Outcome
from sts.content.cards import CardDef
from sts.content.cards import ironclad as cards_ironclad
from sts.content.cards.ironclad import DEFEND, STRIKE
from sts.content.cards.ironclad import BASH as _BASH
from sts.env import N_ACTIONS, OBSERVATION_MAXIMUMS, OBSERVATION_MINIMUMS, StsBattleEnv
from sts.rng import RngStreams

# ---- 掉落预设常量（源码口径，见模块头）----
POTION_DROP_BASE = 40       # AbstractRoom.addPotionToRewards：普通/精英 40%
POTION_BLIZZARD_STEP = 10   # 掉落 -10 / 未掉 +10（动态补偿）
CARD_RARE = 3               # AbstractRoom baseRareCardChance
CARD_UNCOMMON = 37          # baseUncommonCardChance（其余 common）
CARD_PITY_START = 5         # cardBlizzStartOffset
CARD_PITY_GROWTH = 1        # cardBlizzGrowth（出 common 递减）
CARD_PITY_FLOOR = -40       # cardBlizzMaxOffset
POTION_RARITY_COMMON = 65   # POTION_COMMON_CHANCE
POTION_RARITY_UNCOMMON = 25  # POTION_UNCOMMON_CHANCE（其余 rare）
RELIC_TIER_COMMON = 50      # MonsterRoomElite.returnRandomRelicTier：<50
RELIC_TIER_RARE = 82        # >82 rare，其间 uncommon
CAMPFIRE_HEAL_FRACTION = 30  # CampfireSleepEffect：30% max_hp（实时上限，与本体一致）

# 奖励归一化基数：run 起始最大生命（常量，不随 Feed/果汁的增长变动——
# 奖励只与实际 HP 相关，见模块头「奖励口径」）
REWARD_HP_BASE = 80

# ---- 迷你局结构（8 场：3 弱 → 精英 → 2 强 → 精英 → Boss）----
RUN_STRUCTURE = ("weak", "weak", "weak", "elite", "strong", "strong", "elite", "boss")

# ---- 奖励口径 v2（2026-10-08 用户决策：等权战损 + 进度信用）----
# 逐场结算：胜场 = 净HP变化/80 + 每场存活信用；死亡场 = -入场HP/80；
# 火堆转换 = +heal/80（收到即入账——否则「火堆后死」重复计损、死亡时序
# 倒挂）；通关 +1。每点战损全程等价（v1 逐场剩血求和的复利计权使后期
# 战斗占比萎缩——用户纠错）。恒等式：通关总回报 = 终局HP/80 + 1 ∈
# [1.01, 2]；死于第 k 场（0 起）= -1 + (k+1)*信用... 见 tests。
PROGRESS_CREDIT = 1.0 / len(RUN_STRUCTURE)  # 每场存活信用（1/8）
WIN_BONUS = 1.0  # 通关（Boss 胜）终端奖励

# Act 1 池（encounters.py 文档标注分类；强怪 = Act 1 普通房高难度组合）
WEAK_POOL = ("cultist", "jaw_worm", "louses", "slimes_s", "fungi_beast",
             "two_fungi_beasts", "three_louse", "small_slimes", "looter")
STRONG_POOL = ("exordium_wildlife", "gremlin_gang", "slavers", "three_sentries",
               "exordium_thugs", "large_slime", "lots_of_slimes")
ELITE_POOL = ("gremlin_nob", "lagavulin", "guardian")  # 池内第 3 位是 Boss 名——精英池取前 2
BOSSES = ("guardian", "hexaghost", "slime_boss")
ELITES = ("gremlin_nob", "lagavulin")

# 火堆位置（用户决策：3 次）：精英 1（第 4 场前）、精英 2（第 7 场前）、Boss（第 8 场前）
CAMPFIRE_BEFORE = (3, 6, 7)  # 索引 = 场次号，火堆发生在该场战斗开始前

# 前期必选 / 后期可跳（用户决策）：战斗序号 < PICK_MANDATORY_BEFORE 的奖励必选 1 张
PICK_MANDATORY_BEFORE = 4

# ---- 铁甲初始牌组（5 Strike / 4 Defend / 1 Bash）----
INITIAL_DECK: list[CardDef] = [STRIKE] * 5 + [DEFEND] * 4 + [_BASH]

# ---- 铁甲卡牌奖励池（本体 CardLibrary 红色卡按稀有度；数据=源码+wiki 双源）----
# common 20 / uncommon 35+Rage / rare 17+Hand of Greed（后者定义在
# colorless 模块但本体分类 Ironclad Rare，wiki cards.json 同）
def _build_card_pools() -> dict[str, list[CardDef]]:
    import json
    import pathlib

    wiki = {c["name"]: c for c in json.load(open(pathlib.Path(__file__).parent.parent / "wiki_data" / "cards.json"))["cards"]}
    pools: dict[str, list[CardDef]] = {"common": [], "uncommon": [], "rare": []}
    seen: set[int] = set()
    for k, d in vars(cards_ironclad).items():
        if k.startswith("_") or not isinstance(d, CardDef) or id(d) in seen:
            continue
        seen.add(id(d))
        w = wiki.get(d.name)
        if w is None:
            continue
        rar = w["rarity"].lower()
        if rar in pools:
            pools[rar].append(d)
    # wiki 缺页的两张（源码补齐批次，本体分类）：
    from sts.content.cards.ironclad import RAGE
    from sts.content.cards.colorless import HAND_OF_GREED

    pools["uncommon"].append(RAGE)          # Rage.java：red uncommon
    pools["rare"].append(HAND_OF_GREED)     # wiki：Ironclad Rare
    return pools


CARD_POOLS = _build_card_pools()

# ---- 遗物 tier 表（wiki relics.json 113 + 源码 16；排除非随机池 tier）----


def _build_relic_pools() -> dict[str, list[RelicId]]:
    import json
    import pathlib
    import re

    tiers: dict[str, str] = {}
    rw = json.load(open(pathlib.Path(__file__).parent.parent / "wiki_data" / "relics.json"))["relics"]
    for r in rw:
        if r.get("relic_id"):
            tiers[r["relic_id"]] = (r.get("tier") or "").upper()
    # 源码补 16（wiki 归档缺条目；tier 从反编译 ctor 提取，此处按本体知识登记）
    for name, tier in {
        "BRIMSTONE": "BOSS", "CHEMICAL_X": "SHOP", "FROZEN_CORE": "BOSS",
        "GOLDEN_EYE": "UNCOMMON", "MARK_OF_THE_BLOOM": "SPECIAL",
        "BLACK_BLOOD": "BOSS", "BLUE_CANDLE": "UNCOMMON", "MEDICAL_KIT": "UNCOMMON",
        "BOTTLED_FLAME": "UNCOMMON", "BOTTLED_LIGHTNING": "UNCOMMON",
        "BOTTLED_TORNADO": "UNCOMMON", "ANCIENT_TEA_SET": "COMMON",
        "GAMBLING_CHIP": "UNCOMMON", "SACRED_BARK": "BOSS",
        "TOY_ORNITHOPTER": "COMMON", "POTION_BELT": "COMMON",
    }.items():
        tiers.setdefault(name, tier)
    pools: dict[str, list[RelicId]] = {"COMMON": [], "UNCOMMON": [], "RARE": []}
    for rid in RelicId:
        t = tiers.get(rid.name)
        if t in pools:
            pools[t].append(rid)
    return pools


RELIC_POOLS = _build_relic_pools()

# ---- 观测扩展段（战斗观测 + run 特征）----
RUN_FEATURE_DIM = 16
# 布局：战斗序号 one-hot×8 / 下一场类型(weak,strong,elite,boss)×4 /
# 本场类型×4 → 其余保留
N_RUN_FEATURES = 8
_RUN_NEXT = N_RUN_FEATURES          # 下一场（索引+1）类型 one-hot 段
_RUN_CUR = _RUN_NEXT + 4            # 本场类型 one-hot 段
RUN_OBS_DIM = len(OBSERVATION_MAXIMUMS) + RUN_FEATURE_DIM
RUN_OBSERVATION_MAXIMUMS = list(OBSERVATION_MAXIMUMS) + [1] * RUN_FEATURE_DIM
RUN_OBSERVATION_MINIMUMS = list(OBSERVATION_MINIMUMS) + [0] * RUN_FEATURE_DIM

_KINDS = ("weak", "strong", "elite", "boss")


class StsRunEnv(gym.Env):
    """迷你局环境：组合 StsBattleEnv（动作/观测透传）+ 局外掉落逻辑。

    对策略而言这是一个「加长版单场战斗」：动作空间 120 原样透传，
    观测 = 战斗观测 + run 特征段（16 维）。战斗结束的瞬间 env 内部
    结算掉落/选牌/火堆并直接构造下一场战斗——对 step 循环而言下一
    步就是下一场战斗的首个决策点（无中间等待步）。

    奖励（用户决策）：逐场剩血求和。terminated = 8 场打完（Boss 胜/
    负）或任意一场死亡；truncated = 当前场超 TURN_LIMIT。
    """

    metadata = {"render_modes": []}

    def __init__(self, character: str = "ironclad") -> None:
        assert character == "ironclad", "迷你局首版仅铁甲（5c 范围）"
        self.character = character
        self.action_space = spaces.Discrete(N_ACTIONS)
        self.observation_space = spaces.Box(
            low=np.array(RUN_OBSERVATION_MINIMUMS, dtype=np.int32),
            high=np.array(RUN_OBSERVATION_MAXIMUMS, dtype=np.int32),
            shape=(RUN_OBS_DIM,),
            dtype=np.int32,
        )
        # 内嵌战斗 env（透传层）
        self._battle = StsBattleEnv(character=character)
        # run 状态（reset 重建）
        self.rngs: RngStreams | None = None
        self.battle_no = 0            # 0..7（结构索引）
        self.deck: list[CardDef] = []
        self.relics: list[RelicId] = []
        self.potions: list = []       # PotionDef | None × 槽位数
        self.potion_slots = 3
        self.hp = 80
        self.max_hp = 80
        self.potion_blizzard = 0      # 药水掉率补偿
        self.card_pity = CARD_PITY_START  # 卡牌稀有度保底计数器
        self.run_over = False
        self.run_won = False
        self._run_log: list[str] = []
        self._current_kind = "weak"
        self._current_encounter = ""
        self._battle_settled = False  # 当前场是否已结算（防重复结算）

    # ---- Gymnasium API ----

    def reset(self, *, seed: int | None = None, options: dict | None = None):
        super().reset(seed=seed)
        run_seed = int(self.np_random.integers(0, 2**31 - 1))
        # 局外掉落走独立 RNG 流（与战斗内部流隔离：改掉落逻辑不破坏
        # 战斗轨迹的固定种子回归）
        self.rngs = RngStreams(run_seed)
        self.battle_no = 0
        self.deck = list(INITIAL_DECK)
        self.relics = [RelicId.BURNING_BLOOD]  # 铁甲开局遗物（战后回 6）
        self.potions = [None] * self.potion_slots
        self.hp, self.max_hp = 80, 80
        self.potion_blizzard = 0
        self.card_pity = CARD_PITY_START
        self.run_over = False
        self.run_won = False
        self._run_log = []
        self._hp_at_battle_start = 80
        self._start_battle()
        return self._get_obs(), self._get_info()

    def step(self, action):
        """单步 = 战斗内单步。terminated 只在 run 结束（死亡或 8 场通关）
        时为 True——中间场的胜利不是 episode 终止（run 层立即结算掉落并
        构造下一场，对策略而言下一步就是下一场的首个决策点）。"""
        if self._battle.bc is None:
            raise RuntimeError("必须先 reset 才能 step")
        obs, _r, _battle_term, _battle_trunc, _info = self._battle.step(action)
        reward = 0.0
        if self._battle.bc.over or _battle_trunc:
            reward = self._settle_battle()
            if self.run_over:
                # run 终止：观测冻结在结算时刻（无新战斗）
                return self._append_run_features(obs), reward, True, False, self._get_info()
        obs = self._append_run_features(obs)
        return obs, reward, False, _battle_trunc and not self.run_over, self._get_info()

    def action_masks(self) -> np.ndarray:
        """战斗 env 的 mask 透传；若战斗已被外部置终（over 且未结算，
        仅测试路径可达），先补结算再返回空 mask（下一步 step 由调用方
        以任意动作终止——正常路径不存在：怪死亡发生在 step 的结算内）。"""
        bc = self._battle.bc
        if (
            bc is not None
            and bc.over
            and not self.run_over
            and self._battle.current_encounter == self._current_encounter
            and not self._battle_settled
        ):
            self._settle_battle()
        return self._battle.action_masks()

    # ---- 局外推进 ----

    def _sample_encounter(self, kind: str) -> str:
        rng = self.rngs.misc
        pool = {
            "weak": WEAK_POOL,
            "strong": STRONG_POOL,
            "elite": ELITES,
            "boss": BOSSES,
        }[kind]
        return pool[rng.int_inclusive(0, len(pool) - 1)]

    def _start_battle(self) -> float:
        """按 run 结构构造当前场战斗（含火堆回血）。返回火堆信用
        （heal/80，奖励口径 v2：收到即入账，防死亡路径重复计损）——
        由 _settle_battle 并入上一场的结算步回报。"""
        kind = RUN_STRUCTURE[self.battle_no]
        campfire_credit = 0.0
        if self.battle_no in CAMPFIRE_BEFORE:
            heal = self.max_hp * CAMPFIRE_HEAL_FRACTION // 100
            hp_before = self.hp
            self.hp = min(self.max_hp, self.hp + heal)
            # 信用按实际回复量（满血时被上限钳制为 0——名义 24 不记，
            # 否则通关恒等式 final/80+1 被虚增）
            campfire_credit = (self.hp - hp_before) / REWARD_HP_BASE
            self._run_log.append(
                f"火堆：回复 {self.hp - hp_before} HP（{self.hp}/{self.max_hp}）"
            )
        encounter = self._sample_encounter(kind)
        # 战斗种子独立于局外流（np_random 派生 → 同 reset seed 可复现）
        battle_seed = int(self.np_random.integers(0, 2**31 - 1))
        self._battle.__init__(
            encounter=encounter,
            character=self.character,
            relics=list(self.relics),
            potions=[p for p in self.potions if p is not None] or None,
            deck=list(self.deck),
        )
        self._battle.reset(seed=battle_seed)
        # 跨场 HP/上限继承：以 run 状态覆盖战斗初始（上限增长跨场保留）
        bc = self._battle.bc
        bc.player.max_hp = self.max_hp
        bc.player.hp = min(self.hp, self.max_hp)
        self._battle_settled = False  # 新一场：结算位复位
        self._hp_at_battle_start = self.hp  # 战损基数（v2：净HP变化相对此值）
        self._current_kind = kind
        self._current_encounter = encounter
        return campfire_credit

    def _settle_battle(self) -> float:
        """战斗结束结算：奖励 + 掉落 + 选牌 + 推进或终止 run。

        奖励口径 v2（等权战损 + 进度信用，2026-10-08 用户决策）：
        - 胜场 = (结算HP - 入场HP)/80 + PROGRESS_CREDIT（每点战损全程
          等价；存活信用保证「死亡越晚回报越高」）
        - 死亡场 = -入场HP/80（输掉全部剩余，无信用）
        - 截断（TURN_LIMIT 保险丝）= 实际战损 − 1/8（负信用）——拖延
          对任何真打胜利严格劣 1/4，僵局生态位（弱伤遭遇无损拖满）
          无利可图
        - Boss 胜 = 上式 + WIN_BONUS
        - 火堆转换的 +heal/80 信用并入本场结算步（_start_battle 返回）
        恒等式：通关总回报 = 终局HP/80 + 1；死于第 k 场（0 起）=
        -1 + k/8 单调递增；胜败区间分离（胜 ≥1.01 > 败 ≤-0.125）。
        """
        bc = self._battle.bc
        assert bc is not None
        if self._battle_settled:
            return 0.0  # 已结算（action_masks 补结算路径 + step 双入口）
        self._battle_settled = True
        # 上限增长同步回 run（Feed/果汁；下一场带增长后的上限进战）
        self.max_hp = bc.player.max_hp
        hp_start = self._hp_at_battle_start
        if bc.won:
            reward = (bc.player.hp - hp_start) / REWARD_HP_BASE + PROGRESS_CREDIT
            if self.battle_no == len(RUN_STRUCTURE) - 1:
                reward += WIN_BONUS
        elif bc.outcome == Outcome.PLAYER_LOSS:
            reward = -hp_start / REWARD_HP_BASE
        else:  # 截断（TURN_LIMIT 保险丝）：负信用（2026-10-08 终版）。
            # 拖延的完整病理（实测三轮）：①100 回合窗口下挂机拿满信用套利
            # ②25 回合窗口下 slimes 类弱伤遭遇仍可无损拖满。死亡级定价
            # （-1）过钝——把「拖过弱怪」和「死于精英」同价。负信用版：
            # 实际战损 - 1/8，对任何真打胜利（战损 + 1/8）严格劣 1/4，
            # 排序恒正且保留战损梯度（拖得越久磨的血越多越亏）
            reward = (bc.player.hp - hp_start) / REWARD_HP_BASE - PROGRESS_CREDIT
        # 跨场 HP 更新（败局无意义但保持口径）
        self.hp = max(0, bc.player.hp)
        self._run_log.append(
            f"战斗 {self.battle_no + 1}（{self._current_kind}/{self._current_encounter}）："
            f"{'胜' if bc.won else '负'} 剩血 {self.hp}"
        )
        if not bc.won or self.battle_no == len(RUN_STRUCTURE) - 1:
            self.run_over = True
            self.run_won = bool(bc.won)
            return reward
        # ---- 掉落结算（仅胜场；Boss 场无后续，跳过）----
        if self._current_kind == "elite":
            self._drop_relic()
        self._roll_potion_drop()
        self._card_reward()
        self.battle_no += 1
        # 火堆信用（若下一场前有火堆）并入本场结算步的回报流
        reward += self._start_battle()
        return reward

    def _drop_relic(self) -> None:
        """精英遗物：tier roll（<50 common / >82 rare / 其余 uncommon），
        与已持有去重，重复再 roll（本体 returnRandomRelic 同 tier 补抽）。"""
        rng = self.rngs.misc
        roll = rng.int_inclusive(0, 99)
        tier = "COMMON" if roll < RELIC_TIER_COMMON else ("RARE" if roll > RELIC_TIER_RARE else "UNCOMMON")
        pool = [r for r in RELIC_POOLS[tier] if r not in self.relics]
        if not pool:
            # 该 tier 已集齐：降级到其他随机池 tier（本体 fallback 略，
            # 此处换 tier 重 roll 一次）
            for alt in ("COMMON", "UNCOMMON", "RARE"):
                pool = [r for r in RELIC_POOLS[alt] if r not in self.relics]
                if pool:
                    break
        if pool:
            got = pool[rng.int_inclusive(0, len(pool) - 1)]
            self.relics.append(got)
            self._run_log.append(f"精英遗物：{got.name}（{tier}）")

    def _roll_potion_drop(self) -> None:
        """药水掉落：40% + blizzard 补偿；稀有度 65/25/10；槽满即弃。"""
        rng = self.rngs.misc
        chance = POTION_DROP_BASE + self.potion_blizzard
        if rng.int_inclusive(0, 99) < chance:
            self.potion_blizzard -= POTION_BLIZZARD_STEP
            roll = rng.int_inclusive(0, 99)
            if roll < POTION_RARITY_COMMON:
                rar = "common"
            elif roll < POTION_RARITY_COMMON + POTION_RARITY_UNCOMMON:
                rar = "uncommon"
            else:
                rar = "rare"
            from sts.content.potions import IRONCLAD_POTION_POOL

            pool = [p for p in IRONCLAD_POTION_POOL if p.rarity == rar]
            pd = pool[rng.int_inclusive(0, len(pool) - 1)]
            for i, cur in enumerate(self.potions):
                if cur is None:
                    self.potions[i] = pd
                    self._run_log.append(f"药水掉落：{pd.zh}（{rar}）")
                    return
            self._run_log.append(f"药水掉落：{pd.zh}（{rar}）——槽满丢弃")
        else:
            self.potion_blizzard += POTION_BLIZZARD_STEP

    def _card_reward(self) -> None:
        """卡牌奖励：3 张按稀有度 roll（3/37/60 + 保底计数器），奖励内
        cardID 去重；随机选牌（前期必选 / 后期 50% 跳过，用户决策）。"""
        rng = self.rngs.misc
        offered: list[CardDef] = []
        seen_names: set[str] = set()
        for _ in range(3):
            roll = rng.int_inclusive(0, 99) + self.card_pity
            if roll < CARD_RARE:
                rar, self.card_pity = "rare", CARD_PITY_START
            elif roll < CARD_RARE + CARD_UNCOMMON:
                rar = "uncommon"  # 保底计数器不动（源码 uncommon 分支无操作）
            else:
                # 源码：common 时计数器递减（封底 -40）
                rar = "common"
                self.card_pity = max(CARD_PITY_FLOOR, self.card_pity - CARD_PITY_GROWTH)
            pool = CARD_POOLS[rar]
            for _attempt in range(len(pool)):
                c = pool[rng.int_inclusive(0, len(pool) - 1)]
                if c.name not in seen_names:
                    seen_names.add(c.name)
                    offered.append(c)
                    break
        pick_mandatory = self.battle_no < PICK_MANDATORY_BEFORE
        if pick_mandatory or rng.int_inclusive(0, 1) == 0:
            chosen = offered[rng.int_inclusive(0, len(offered) - 1)]
            self.deck.append(chosen)
            self._run_log.append(f"选牌：{chosen.zh}（{chosen.name}，3 选 1）")
        else:
            self._run_log.append("选牌：跳过")

    # ---- 观测 ----

    def _append_run_features(self, obs: np.ndarray) -> np.ndarray:
        out = np.zeros(RUN_OBS_DIM, dtype=np.int32)
        out[: len(obs)] = obs
        b = len(obs)
        out[b + min(self.battle_no, N_RUN_FEATURES - 1)] = 1  # 战斗序号
        kind_next = (
            RUN_STRUCTURE[self.battle_no + 1] if self.battle_no + 1 < len(RUN_STRUCTURE) else None
        )
        if kind_next is not None:
            out[b + _RUN_NEXT + _KINDS.index(kind_next)] = 1
        out[b + _RUN_CUR + _KINDS.index(self._current_kind)] = 1
        return out

    def _get_obs(self) -> np.ndarray:
        obs = self._battle._get_obs()
        return self._append_run_features(obs)

    def _get_info(self) -> dict:
        bc = self._battle.bc
        return {
            "battle_no": self.battle_no,
            "battle_kind": self._current_kind,
            "encounter": self._current_encounter,
            "hp_remaining": self.hp,
            "run_over": self.run_over,
            "run_won": self.run_won,
            "won": bc.won if bc else None,
            "outcome": bc.outcome.name if bc else None,
            "deck_size": len(self.deck),
            "relics": [r.name for r in self.relics],
            "run_log": list(self._run_log),
        }

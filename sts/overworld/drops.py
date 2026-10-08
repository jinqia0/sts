"""战斗后掉落与宝箱（Phase 3a，2026-10-08）。

对齐本体：
- 金币：普通 10-20 / 精英 25-35（treasureRng，AbstractRoom.java:302-316）；
  Boss 100 + miscRng(-5,5)（:276-287，A13 ×0.75 不实现）
- 药水掉落：40% + blizzard 补偿（掉 −10 / 未掉 +10，AbstractRoom.java:582-610，
  幕间清零；WhiteBeast 置 100；奖励 ≥4 条置 0）；稀有度 65/25/10 拒绝采样
  （AbstractDungeon.returnRandomPotion :805-829，池永不清空不去重）
- 精英遗物：必掉，tier roll 50/33/17 头取（MonsterRoomElite.java:76-93）；
  BlackStar 追加第二件（排除营地三件套）
- 宝箱（AbstractChest.java:46-94）：箱型 roll 50/33/17（Small/Medium/Large）；
  同一 roll 定金币与遗物档（本体怪癖照抄）——roll < GOLD_CHANCE 给金币、
  roll < COMMON_CHANCE 为 common 遗物、否则按 uncommon/rare 分档；
  金币量 = round(random(GOLD_AMT×0.9, ×1.1))。Matryoshka 双遗物（75% common）

药水稀有度拒绝采样照抄：身份均匀抽、rarity 不匹配则重抽（同流多耗）。
"""

from __future__ import annotations

from dataclasses import dataclass

from sts.combat.relics import RelicId
from sts.content.potions import IRONCLAD_POTION_POOL, PotionDef
from sts.overworld.relic_effects import (
    elite_drops_second_relic,
    potion_drop_chance,
)
from sts.overworld.relic_pools import RelicPools, roll_tier
from sts.overworld.rng import OverworldRngStreams
from sts.overworld.state import RunState

POTION_DROP_BASE = 40
POTION_BLIZZARD_STEP = 10
POTION_RARITY_COMMON = 65
POTION_RARITY_UNCOMMON = 25

RELIC_TIER_COMMON = 50  # roll < 50 common
RELIC_TIER_RARE = 82  # roll > 82 rare，其间 uncommon

# 宝箱参数（SmallChest/MediumChest/LargeChest.java）
_CHEST_PARAMS = {
    "small": {"common": 75, "uncommon": 25, "rare": 0, "gold_chance": 50, "gold_amt": 25},
    "medium": {"common": 35, "uncommon": 50, "rare": 15, "gold_chance": 35, "gold_amt": 50},
    "large": {"common": 0, "uncommon": 75, "rare": 25, "gold_chance": 50, "gold_amt": 75},
}
_SMALL_CHEST_CHANCE = 50  # Exordium.java:97-98
_MEDIUM_CHEST_CHANCE = 33

MATRYOSHKA_COMMON_CHANCE = 75  # Matryoshka.java:31


def gold_reward(rngs: OverworldRngStreams, room: str) -> int:
    """战斗胜利金币。room ∈ monster/elite/boss。"""
    if room == "boss":
        return 100 + rngs.misc.int_inclusive(-5, 5)
    if room == "elite":
        return rngs.treasure.int_inclusive(25, 35)
    return rngs.treasure.int_inclusive(10, 20)


def roll_potion_drop(
    state: RunState, rngs: OverworldRngStreams, reward_count: int
) -> PotionDef | None:
    """战斗后药水掉落 roll（含 blizzard 补偿与 WhiteBeast 修正）。"""
    if reward_count >= 4:
        return None
    chance = potion_drop_chance(state, POTION_DROP_BASE + state.potion_blizzard)
    if rngs.potion.int_inclusive(0, 99) < chance:
        state.potion_blizzard -= POTION_BLIZZARD_STEP
        return random_potion_by_rarity(rngs)
    state.potion_blizzard += POTION_BLIZZARD_STEP
    return None


def random_potion_by_rarity(rngs: OverworldRngStreams) -> PotionDef:
    """稀有度 65/25/10 + 身份拒绝采样（同流消耗，照抄本体）。"""
    roll = rngs.potion.int_inclusive(0, 99)
    if roll < POTION_RARITY_COMMON:
        rarity = "common"
    elif roll < POTION_RARITY_COMMON + POTION_RARITY_UNCOMMON:
        rarity = "uncommon"
    else:
        rarity = "rare"
    while True:
        pd = IRONCLAD_POTION_POOL[rngs.potion.int_inclusive(0, len(IRONCLAD_POTION_POOL) - 1)]
        if pd.rarity == rarity:
            return pd


def elite_relic_drops(state: RunState, rngs: OverworldRngStreams, pools: RelicPools) -> list[RelicId]:
    """精英掉落：1 件 tier roll 头取；BlackStar 追加非营地第二件。"""
    out = [pools.take_drop(roll_tier(rngs.relic), state)]
    if elite_drops_second_relic(state):
        out.append(pools.take_non_campfire(state))
    return out


@dataclass(frozen=True)
class ChestLoot:
    gold: int
    relics: list[RelicId]
    size: str = ""  # small / medium / large（观测/测试用）


def open_chest(state: RunState, rngs: OverworldRngStreams, pools: RelicPools) -> ChestLoot:
    """开宝箱（row 8 固定宝箱与 ？房 TREASURE 旁路共用）。"""
    size_roll = rngs.treasure.int_inclusive(0, 99)
    if size_roll < _SMALL_CHEST_CHANCE:
        size = "small"
    elif size_roll < _SMALL_CHEST_CHANCE + _MEDIUM_CHEST_CHANCE:
        size = "medium"
    else:
        size = "large"
    params = _CHEST_PARAMS[size]

    roll = rngs.treasure.int_inclusive(0, 99)  # 本体：金币与遗物档共用同一次 roll
    gold = 0
    if roll < params["gold_chance"]:
        amt = params["gold_amt"]
        gold = int(round(amt * rngs.treasure.int_inclusive(0, 99) / 99.0 * 0.2 + amt * 0.9))
    if roll < params["common"]:
        tier = "common"
    elif roll < params["common"] + params["uncommon"]:
        tier = "uncommon"
    else:
        tier = "rare"
    relics = [pools.take_drop(tier, state)]
    # Matryoshka：接下来 2 个宝箱双遗物（75% common，非 Boss 宝箱）
    if state.has(RelicId.MATRYOSHKA) and state.counter(RelicId.MATRYOSHKA) > 0:
        state.set_counter(RelicId.MATRYOSHKA, state.counter(RelicId.MATRYOSHKA) - 1)
        extra_tier = "common" if rngs.relic.int_inclusive(0, 99) < MATRYOSHKA_COMMON_CHANCE else "uncommon"
        relics.append(pools.take_drop(extra_tier, state))
    return ChestLoot(gold=gold, relics=relics, size=size)

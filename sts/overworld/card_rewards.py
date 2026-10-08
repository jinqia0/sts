"""卡牌奖励生成（Phase 3a，2026-10-08）。

对齐本体 AbstractDungeon.getRewardCards（java:1403-1459）+ rollRarity
（:1577-1599）+ 房间稀有度阈值（rooms/AbstractRoom.java:98-101 与各覆盖）：

    房间        rare 阈值   uncommon 阈值    说明
    普通           3            37           roll < 3 rare / < 40 uncommon
    精英          10            40           MonsterRoomElite.java:29-30
    Boss        恒 rare                       MonsterRoomBoss.java:35-37
    商店           9            37           ShopRoom.java:31（不套遗物修正）

pity（cardBlizzRandomizer）：初始 +5，出 common −1（下限 −40），出 rare
归 5；roll = random(99) + pity 与低端阈值比较——开局 +5 意味着首个奖励
无稀有牌（本体行为照抄）。槽内同 cardID 去重重 roll。升级 roll：
Act 1 为 0（Exordium.cardUpgradedChance，java:104），故本模块奖励恒
非升级（升级牌只经蛋类/事件产生）。
"""

from __future__ import annotations

from sts.content.cards import CardDef
from sts.overworld.card_pools import ANY_COLOR_POOLS, OWN_POOLS
from sts.overworld.relic_effects import card_reward_count, card_pool_any_color
from sts.overworld.rng import OverworldRngStreams
from sts.overworld.state import RunState

CARD_PITY_START = 5  # cardBlizzStartOffset（java:2753）
CARD_PITY_GROWTH = 1  # cardBlizzGrowth
CARD_PITY_FLOOR = -40  # cardBlizzMaxOffset

_BASE_NUM_CARDS = 3

# 房间 → (rare 阈值, uncommon 阈值)
_RARITY_THRESHOLDS: dict[str, tuple[int, int]] = {
    "monster": (3, 37),
    "elite": (10, 40),
    "shop": (9, 37),
}


def roll_rarity(rngs: OverworldRngStreams, pity: int, room: str) -> tuple[str, int]:
    """一次稀有度 roll，返回 (rarity, 新 pity)。room ∈ monster/elite/shop；boss 恒 rare。"""
    if room == "boss":
        return "rare", CARD_PITY_START
    rare_t, unc_t = _RARITY_THRESHOLDS[room]
    roll = rngs.card.int_inclusive(0, 99) + pity
    if roll < rare_t:
        return "rare", CARD_PITY_START
    if roll < rare_t + unc_t:
        return "uncommon", pity
    return "common", max(pity - CARD_PITY_GROWTH, CARD_PITY_FLOOR)


def _pick_card(rngs: OverworldRngStreams, state: RunState, rarity: str, ctype: str | None = None) -> CardDef | None:
    """从池均匀抽 1 张（可按类型过滤）；POWER 空池沿 common→uncommon→rare 降级（java:1518-1557）。"""
    pools = ANY_COLOR_POOLS if card_pool_any_color(state) else OWN_POOLS
    if ctype is not None:
        for rar in ("common", "uncommon", "rare") if rarity == "common" else (rarity,):
            pool = [c for c in pools[rar] if getattr(c, "ctype", "") == ctype]
            if pool:
                return pool[rngs.card.int_inclusive(0, len(pool) - 1)]
        return None
    pool = pools[rarity]
    return pool[rngs.card.int_inclusive(0, len(pool) - 1)]


def get_reward_cards(state: RunState, rngs: OverworldRngStreams, room: str) -> list[CardDef]:
    """一组卡牌奖励（数量经 QuestionCard/BustedCrown 修正）。"""
    num = card_reward_count(state, _BASE_NUM_CARDS)
    out: list[CardDef] = []
    for _ in range(num):
        rarity, state.card_pity = roll_rarity(rngs, state.card_pity, room)
        card = _pick_card(rngs, state, rarity)
        # 槽内去重：同 cardID 重 roll（本体 while containsDupe）
        while card is not None and any(c.name == card.name for c in out):
            card = _pick_card(rngs, state, rarity)
        if card is not None:
            out.append(card)
    return out


def roll_shop_card(rngs: OverworldRngStreams, state: RunState, ctype: str, exclude: set[str] | None = None) -> CardDef | None:
    """商店彩色槽：稀有度 roll（shop 阈值，读当前 pity 不更新）+ 类型过滤选卡。

    exclude：同槽去重（第 2 张攻击/技能与第 1 张不同 cardID，Merchant.java:59-67）。
    """
    rarity, _ = roll_rarity(rngs, state.card_pity, "shop")
    card = _pick_card(rngs, state, rarity, ctype=ctype)
    while card is not None and exclude and card.name in exclude:
        card = _pick_card(rngs, state, rarity, ctype=ctype)
    return card


def roll_colorless_card(rngs: OverworldRngStreams, rarity: str):
    """商店无色槽（getColorlessCardFromPool：uncommon / rare 二选）。"""
    from sts.overworld.card_pools import COLORLESS_POOLS

    pool = COLORLESS_POOLS[rarity]
    return pool[rngs.card.int_inclusive(0, len(pool) - 1)]

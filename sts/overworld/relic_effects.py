"""局外遗物效果（Phase 3a，2026-10-08）。

局外遗物效果不进战斗钩子链（sts/combat/relics.py 只管战斗面）——
全部效果集中在本模块，由 state/run/shop/drops/event_roll 在操作位调用。
数值逐条对照本体反编译源码（sts_game_data/decompiled/，V2.3.4）。

拾取效果分两类：
- 自动生效（金币/maxHP/随机药水/随机升级）：``apply_pickup`` 直接结算
- 需要玩家选择（删 2 牌/复制/变化 3 张/加牌）：返回 PendingRelicChoice
  描述符，由 run 循环交给策略决策后结算
"""

from __future__ import annotations

from dataclasses import dataclass

from sts.combat.relics import RelicId
from sts.content.cards import CardDef
from sts.overworld.rng import OverworldRngStreams
from sts.overworld.state import RunState

# 营地类遗物（Shovel.canSpawn：campfireRelicCount < 2 才能刷出）
CAMPFIRE_RELICS = (RelicId.GIRYA, RelicId.SHOVEL, RelicId.PEACE_PIPE)

GIRYA_STR_LIMIT = 3  # Girya.java:21
REGAL_PILLOW_HEAL = 15  # RegalPillow.java:13
MEAL_TICKET_HEAL = 15  # MealTicket.java:16
MAW_BANK_GOLD = 12  # MawBank.java:15
CERAMIC_FISH_GOLD = 9  # CeramicFish.onObtainCard
ETERNAL_FEATHER_PER_5 = 3  # EternalFeather.java:32-34：deck/5×3
STRAWBERRY_HP = 7  # Strawberry.java:26
PEAR_HP = 10  # Pear.java:26
MANGO_HP = 14  # Mango.java:26
OLD_COIN_GOLD = 300  # OldCoin.java:29
PURGE_BASE_COST = 75  # ShopScreen.purgeCost
PURGE_COST_STEP = 25  # 每次使用 +25
SMILING_MASK_COST = 50  # SmilingMask.java:15
CAULDRON_POTIONS = 5  # Cauldron：5 瓶随机药水
TINY_HOUSE_MAX_HP = 5  # TinyHouse.java:21
TINY_HOUSE_GOLD = 50  # TinyHouse.java:20
WINGED_GREAVES_CHARGES = 3  # WingBoots counter
MATRYOSHKA_CHESTS = 2  # Matryoshka counter
TINY_CHEST_INTERVAL = 4  # TinyChest：每 4 个 ？房


@dataclass(frozen=True)
class PendingRelicChoice:
    """拾取时需要策略介入的选择型效果（run 循环经 policy 结算）。"""

    kind: str  # "remove2" | "duplicate" | "transform3_upgrade" | "card_reward" | "card_reward_x5"
    relic: RelicId


# ---- 加牌钩子 ----


def egg_upgraded(state: RunState, card: CardDef) -> bool:
    """蛋类：获得对应类型牌时自动升级（非诅咒，Egg2.java 系列）。"""
    ctype = getattr(card, "ctype", "")
    if ctype == "Curse":
        return False
    if ctype == "Attack" and state.has(RelicId.MOLTEN_EGG):
        return True
    if ctype == "Skill" and state.has(RelicId.FROZEN_EGG):
        return True
    if ctype == "Power" and state.has(RelicId.TOXIC_EGG):
        return True
    return False


def on_add_card(state: RunState, card: CardDef, upgraded: bool) -> None:
    if state.has(RelicId.CERAMIC_FISH):
        state.add_gold(CERAMIC_FISH_GOLD)


# ---- 休息处 ----


def on_enter_rest(state: RunState) -> int:
    """进火堆房即结算的效果，返回回复量（EternalFeather）。"""
    healed = 0
    if state.has(RelicId.ETERNAL_FEATHER):
        healed += state.heal(len(state.deck) // 5 * ETERNAL_FEATHER_PER_5)
    return healed


def rest_heal_bonus(state: RunState) -> int:
    return REGAL_PILLOW_HEAL if state.has(RelicId.REGAL_PILLOW) else 0


def campfire_options(state: RunState) -> list[str]:
    """火堆可用选项（run 循环展开）：rest / smith / 遗物解锁项。

    Girya counter 达上限则不可举重（Girya.java:57 liftOption(counter<3)）。
    """
    opts = ["rest", "smith"]
    if state.has(RelicId.GIRYA) and state.counter(RelicId.GIRYA) < GIRYA_STR_LIMIT:
        opts.append("lift")
    if state.has(RelicId.SHOVEL):
        opts.append("dig")
    if state.has(RelicId.PEACE_PIPE):
        opts.append("smoke")
    return opts


# ---- 商店 ----


def on_enter_shop(state: RunState) -> int:
    """进商店即结算：餐券回血，返回回复量。"""
    if state.has(RelicId.MEAL_TICKET):
        return state.heal(MEAL_TICKET_HEAL)
    return 0


def shop_price_multiplier(state: RunState) -> float:
    """商店折扣（乘法叠加：会员卡 5 折 × 鉴识单片眼镜 8 折 × 送货员 8 折）。"""
    m = 1.0
    if state.has(RelicId.MEMBERSHIP_CARD):
        m *= 0.5
    if state.has(RelicId.DISCERNING_MONOCLE):
        m *= 0.8
    if state.has(RelicId.THE_COURIER):
        m *= 0.8
    return m


def purge_price(state: RunState) -> int:
    if state.has(RelicId.SMILING_MASK):
        return SMILING_MASK_COST
    return PURGE_BASE_COST + PURGE_COST_STEP * state.purge_uses


def shop_restocks(state: RunState) -> bool:
    """送货员：卡/遗物/药水卖出后补新货。"""
    return state.has(RelicId.THE_COURIER)


# ---- 楼层推进 ----


def on_floor_advance(state: RunState) -> None:
    """爬一层：巨口储蓄罐 +12 金（未失效时）。"""
    if state.has(RelicId.MAW_BANK) and state.counter(RelicId.MAW_BANK) != -2:
        state.add_gold(MAW_BANK_GOLD)


# ---- 掉落/奖励修正 ----


def potion_drop_chance(state: RunState, base: int) -> int:
    if state.has(RelicId.WHITE_BEAST_STATUE):
        return 100
    return base


def card_reward_count(state: RunState, n: int) -> int:
    """奖励卡张数修正（QuestionCard +1 / BustedCrown −2，Java changeNumberOfCardsInReward）。"""
    if state.has(RelicId.QUESTION_CARD):
        n += 1
    if state.has(RelicId.BUSTED_CROWN):
        n -= 2
    return max(0, n)


def extra_card_reward_after_combat(state: RunState, room_kind: str) -> bool:
    """转经轮：普通战斗房多一组卡牌奖励。"""
    return room_kind == "monster" and state.has(RelicId.PRAYER_WHEEL)


def elite_drops_second_relic(state: RunState) -> bool:
    return state.has(RelicId.BLACK_STAR)


def card_pool_any_color(state: RunState) -> bool:
    """棱镜碎片：卡牌奖励从全职业池抽取。"""
    return state.has(RelicId.PRISMATIC_SHARD)


# ---- ？房干预 ----


def tiny_chest_forces_treasure(state: RunState) -> bool:
    counter = state.counter(RelicId.TINY_CHEST) + 1
    if counter % TINY_CHEST_INTERVAL == 0:
        return True
    return False


def juzu_blocks_monster(state: RunState) -> bool:
    return state.has(RelicId.JUZU_BRACELET)


# ---- 路线 ----


def winged_greaves_charges_left(state: RunState) -> int:
    if not state.has(RelicId.WINGED_GREAVES):
        return 0
    return WINGED_GREAVES_CHARGES - state.counter(RelicId.WINGED_GREAVES)


def consume_winged_greaves(state: RunState) -> None:
    state.set_counter(RelicId.WINGED_GREAVES, state.counter(RelicId.WINGED_GREAVES) + 1)


# ---- 拾取效果 ----


def apply_pickup(state: RunState, relic: RelicId, rngs: OverworldRngStreams) -> list[PendingRelicChoice]:
    """遗物入手：先入列表 + 即时效果；返回需要策略决策的挂起选择。

    随机药水/随机升级的随机源用 misc 流（对齐本体 miscRng 语义）。
    """
    state.relics.append(relic)
    pending: list[PendingRelicChoice] = []
    if relic == RelicId.STRAWBERRY:
        state.gain_max_hp(STRAWBERRY_HP)
    elif relic == RelicId.PEAR:
        state.gain_max_hp(PEAR_HP)
    elif relic == RelicId.MANGO:
        state.gain_max_hp(MANGO_HP)
    elif relic == RelicId.OLD_COIN:
        state.add_gold(OLD_COIN_GOLD)
    elif relic == RelicId.POTION_BELT:
        state.potions += [None, None]  # 药水槽 +2（onEquip 时加槽）
    elif relic == RelicId.MAW_BANK:
        state.set_counter(RelicId.MAW_BANK, 0)
    elif relic == RelicId.WINGED_GREAVES:
        state.set_counter(RelicId.WINGED_GREAVES, 0)
    elif relic == RelicId.MATRYOSHKA:
        state.set_counter(RelicId.MATRYOSHKA, MATRYOSHKA_CHESTS)
    elif relic == RelicId.TINY_CHEST:
        state.set_counter(RelicId.TINY_CHEST, 0)
    elif relic == RelicId.WAR_PAINT:
        _upgrade_random(state, rngs, ctype="Skill", n=2)
    elif relic == RelicId.WHETSTONE:
        _upgrade_random(state, rngs, ctype="Attack", n=2)
    elif relic == RelicId.EMPTY_CAGE:
        pending.append(PendingRelicChoice("remove2", relic))
    elif relic == RelicId.DOLLYS_MIRROR:
        pending.append(PendingRelicChoice("duplicate", relic))
    elif relic == RelicId.ASTROLABE:
        pending.append(PendingRelicChoice("transform3_upgrade", relic))
    elif relic == RelicId.ORRERY:
        pending.append(PendingRelicChoice("card_reward_x5", relic))
    elif relic == RelicId.TINY_HOUSE:
        state.gain_max_hp(TINY_HOUSE_MAX_HP)
        state.add_gold(TINY_HOUSE_GOLD)
        _upgrade_random(state, rngs, ctype=None, n=1)
        pending.append(PendingRelicChoice("card_reward", relic))
        # 1 瓶随机药水（满槽由 run 循环走弃瓶决策）
        from sts.content.potions import random_run_potion

        state.obtain_potion(random_run_potion(rngs.potion))
    elif relic == RelicId.PANDORAS_BOX:
        _transform_strikes_defends(state, rngs)
    elif relic == RelicId.CAULDRON:
        from sts.content.potions import random_run_potion

        for _ in range(CAULDRON_POTIONS):
            state.obtain_potion(random_run_potion(rngs.potion))
    elif relic == RelicId.CALLING_BELL:
        # 召唤铃铛：1 诅咒 + 3 件遗物（CallingBell.java——1 common + 1 uncommon + 1 rare）
        pending.append(PendingRelicChoice("calling_bell", relic))
    return pending


def _upgrade_random(state: RunState, rngs: OverworldRngStreams, ctype: str | None, n: int) -> None:
    """随机升级 n 张可升级（可按类型过滤）牌（WarPaint/Whetstone/TinyHouse 路径）。"""
    for _ in range(n):
        idxs = [i for i, dc in enumerate(state.deck) if not dc.upgraded and (ctype is None or getattr(dc.card, "ctype", "") == ctype)]
        if not idxs:
            return
        state.upgrade_card(idxs[rngs.misc.int_inclusive(0, len(idxs) - 1)])


def _transform_strikes_defends(state: RunState, rngs: OverworldRngStreams) -> None:
    """潘多拉魔盒：变化全部打击/防御（同稀有度替换 = 基础牌 → 随机普通牌）。"""
    from sts.overworld.card_pools import POOLS

    for i, dc in enumerate(state.deck):
        if dc.card.name in ("Strike", "Defend"):
            pool = POOLS["common"]
            card = pool[rngs.misc.int_inclusive(0, len(pool) - 1)]
            state.deck[i] = state.deck[i].__class__(card, False)

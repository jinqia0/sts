"""RunState / 遗物池 / 局外遗物效果测试（Phase 3a）。"""

from __future__ import annotations

from sts.combat.relics import RelicId
from sts.content.cards import colorless as cards_colorless
from sts.content.cards.ironclad import DEFEND, STRIKE
from sts.overworld.relic_effects import (
    CAMPFIRE_RELICS,
    apply_pickup,
    campfire_options,
    egg_upgraded,
    purge_price,
    rest_heal_bonus,
    shop_price_multiplier,
)
from sts.overworld.relic_pools import (
    BOSS_POOL,
    COMMON_POOL,
    RARE_POOL,
    RelicPools,
    SHOP_POOL,
    UNCOMMON_POOL,
    can_spawn,
    roll_tier,
)
from sts.overworld.rng import OverworldRngStreams
from sts.overworld.state import STARTING_GOLD, DeckCard, RunState
from sts.rng import Rng

# 其他职业桶遗物（不应出现在铁甲池：RelicLibrary 绿/蓝/紫注册表）
_OTHER_CLASS_RELICS = {
    RelicId.NINJA_SCROLL, RelicId.PAPER_KRANE, RelicId.THE_SPECIMEN,  # 绿
    RelicId.DATA_DISK, RelicId.EMOTION_CHIP, RelicId.FROZEN_CORE,  # 蓝
    RelicId.DAMARU, RelicId.HOLY_WATER, RelicId.MELANGE, RelicId.VIOLET_LOTUS,  # 紫
    RelicId.DUALITY, RelicId.TEARDROP_LOCKET,
}


def test_pool_composition_lock():
    """池构成锁（shared+红，tier 自构造器）：33/31/28/15/22。"""
    assert len(COMMON_POOL) == 33
    assert len(UNCOMMON_POOL) == 31
    assert len(RARE_POOL) == 28
    assert len(SHOP_POOL) == 15
    assert len(BOSS_POOL) == 22
    all_pool = COMMON_POOL + UNCOMMON_POOL + RARE_POOL + SHOP_POOL + BOSS_POOL
    assert len(set(all_pool)) == len(all_pool), "池间重复"
    assert not (_OTHER_CLASS_RELICS & set(all_pool)), "他职业遗物混入铁甲池"
    # 红桶遗物在池中（RelicId.RED_SKULL/PAPER_FROG/CHAMPION_BELT 等红皮）
    for rid in (RelicId.RED_SKULL, RelicId.PAPER_FROG, RelicId.CHAMPION_BELT, RelicId.MAGIC_FLOWER):
        assert rid in COMMON_POOL + UNCOMMON_POOL + RARE_POOL
    # 事件专属遗物不在池中
    for rid in (RelicId.GOLDEN_IDOL, RelicId.SPIRIT_POOP, RelicId.BLOODY_IDOL):
        assert rid not in all_pool


def test_take_drop_head_and_removal():
    pools = RelicPools(Rng(11))
    s = RunState()
    first = COMMON_POOL[0] if COMMON_POOL[0] in pools.pools["common"] else None
    # 头取：取走池首（洗牌后池首即 pools.pools['common'][0]）
    head = pools.pools["common"][0]
    got = pools.take_drop("common", s)
    assert got == head
    assert head not in pools.pools["common"]


def test_take_shop_tail():
    pools = RelicPools(Rng(11))
    s = RunState()
    tail = pools.pools["shop"][-1]
    got = pools.take_shop("shop", s)
    assert got == tail
    assert tail not in pools.pools["shop"]


def test_degrade_chain_to_circlet():
    pools = RelicPools(Rng(11))
    s = RunState()
    # 排空 common/uncommon/rare
    for _name in ("common", "uncommon", "rare"):
        pools.pools[_name].clear()
    assert pools.take_drop("common", s) == RelicId.CIRCLET
    pools.pools["boss"].clear()
    assert pools.take_drop("boss", s) == RelicId.RED_CIRCLET


def test_shop_can_spawn_excludes_relics():
    s = RunState()
    for rid in (RelicId.THE_COURIER, RelicId.MAW_BANK, RelicId.OLD_COIN, RelicId.SMILING_MASK):
        assert can_spawn(rid, s, in_shop=True) is False
        assert can_spawn(rid, s, in_shop=False) is True  # 掉落路径不受限


def test_roll_tier_statistics():
    from collections import Counter

    c = Counter(roll_tier(Rng(seed)) for seed in range(600))
    total = sum(c.values())
    assert abs(c["common"] / total - 0.50) < 0.06
    assert abs(c["uncommon"] / total - 0.33) < 0.05
    assert abs(c["rare"] / total - 0.17) < 0.05


# ---- RunState ----


def test_state_initial_values():
    s = RunState()
    assert (s.hp, s.max_hp, s.gold) == (80, 80, STARTING_GOLD)
    assert len(s.deck) == 10 and s.potions == [None, None, None]
    assert s.relics == [RelicId.BURNING_BLOOD]


def test_clone_independence():
    s = RunState()
    s.gold = 123
    s.deck.append(DeckCard(STRIKE, True))
    s.event_pool = ["A", "B"]
    s.event_scratch["x"] = {"a": 1}
    c = s.clone()
    c.gold = 1
    c.deck.append(DeckCard(DEFEND))
    c.event_pool.remove("A")
    c.event_scratch["x"]["a"] = 2
    assert s.gold == 123 and len(s.deck) == 11 and s.event_pool == ["A", "B"]
    assert s.event_scratch["x"]["a"] == 1


def test_heal_and_lose_hp():
    s = RunState()
    assert s.heal(100) == 0
    s.lose_hp(30)
    assert s.hp == 50 and s.heal(20) == 20 and s.hp == 70
    s.lose_hp(999)
    assert s.hp == 0


def test_add_card_egg_upgrade():
    s = RunState()
    rngs = OverworldRngStreams(1)
    apply_pickup(s, RelicId.MOLTEN_EGG, rngs)
    s.add_card(STRIKE)  # 攻击牌 → 自动升级
    assert s.deck[-1].upgraded is True
    s.add_card(DEFEND)  # 技能牌 → 不升级
    assert s.deck[-1].upgraded is False
    assert egg_upgraded(s, STRIKE) and not egg_upgraded(s, DEFEND)


def test_ceramic_fish_gold_on_add():
    s = RunState()
    rngs = OverworldRngStreams(1)
    apply_pickup(s, RelicId.CERAMIC_FISH, rngs)
    before = s.gold
    s.add_card(STRIKE)
    assert s.gold == before + 9


def test_pickup_max_hp_and_gold_relics():
    s = RunState()
    rngs = OverworldRngStreams(1)
    apply_pickup(s, RelicId.STRAWBERRY, rngs)
    assert s.max_hp == 87 and s.hp == 87
    apply_pickup(s, RelicId.PEAR, rngs)
    assert s.max_hp == 97
    apply_pickup(s, RelicId.OLD_COIN, rngs)
    assert s.gold == STARTING_GOLD + 300
    apply_pickup(s, RelicId.POTION_BELT, rngs)
    assert len(s.potions) == 5


def test_maw_bank_breaks_on_shop_spend():
    s = RunState()
    rngs = OverworldRngStreams(1)
    apply_pickup(s, RelicId.MAW_BANK, rngs)
    s.spend_gold(10, in_shop=True)
    assert s.counter(RelicId.MAW_BANK) == -2  # 失效
    before = s.gold
    from sts.overworld.relic_effects import on_floor_advance

    on_floor_advance(s)
    assert s.gold == before  # 失效后不再产金


def test_campfire_options_and_rest_bonuses():
    s = RunState()
    assert campfire_options(s) == ["rest", "smith"]
    rngs = OverworldRngStreams(1)
    for rid in (RelicId.GIRYA, RelicId.SHOVEL, RelicId.PEACE_PIPE):
        apply_pickup(s, rid, rngs)
    assert set(campfire_options(s)) == {"rest", "smith", "lift", "dig", "smoke"}
    s.set_counter(RelicId.GIRYA, 3)
    assert "lift" not in campfire_options(s)  # 上限 3 次
    apply_pickup(s, RelicId.REGAL_PILLOW, rngs)
    assert rest_heal_bonus(s) == 15


def test_shop_discount_stacking():
    s = RunState()
    assert shop_price_multiplier(s) == 1.0
    s.relics.append(RelicId.MEMBERSHIP_CARD)
    assert shop_price_multiplier(s) == 0.5
    s.relics.append(RelicId.DISCERNING_MONOCLE)
    assert abs(shop_price_multiplier(s) - 0.4) < 1e-9


def test_purge_price():
    s = RunState()
    assert purge_price(s) == 75
    s.purge_uses = 2
    assert purge_price(s) == 125
    s.relics.append(RelicId.SMILING_MASK)
    assert purge_price(s) == 50


def test_shovel_spawn_needs_few_campfire_relics():
    s = RunState()
    s.relics.extend([RelicId.GIRYA, RelicId.PEACE_PIPE])
    assert can_spawn(RelicId.SHOVEL, s) is False  # 营地遗物已 2 件
    s2 = RunState()
    s2.relics.append(RelicId.GIRYA)
    assert can_spawn(RelicId.SHOVEL, s2) is True


def test_campfire_relics_constant():
    assert set(CAMPFIRE_RELICS) == {RelicId.GIRYA, RelicId.SHOVEL, RelicId.PEACE_PIPE}

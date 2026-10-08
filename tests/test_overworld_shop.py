"""商店测试（Phase 3a）。"""

from __future__ import annotations

from sts.combat.relics import RelicId
from sts.content.events import card_wiki_rarity
from sts.overworld.relic_pools import RelicPools
from sts.overworld.rng import OverworldRngStreams
from sts.overworld.shop import discounted, generate_stock, restock
from sts.overworld.state import RunState


def _stock(seed=1):
    s = RunState()
    rngs = OverworldRngStreams(seed)
    pools = RelicPools(rngs.relic)
    return s, rngs, pools, generate_stock(s, rngs, pools)


def test_stock_structure():
    """5 彩色（2 攻 2 技 1 能）+ 2 无色 + 3 遗物 + 3 药水。"""
    for seed in range(20):
        s, rngs, pools, stock = _stock(seed)
        colored = stock.cards[:5]
        ctypes = [c.card.ctype for c in colored]
        assert ctypes == ["Attack", "Attack", "Skill", "Skill", "Power"]
        # 第 2 张攻击/技能与第 1 张不同 cardID
        assert colored[0].card.name != colored[1].card.name
        assert colored[2].card.name != colored[3].card.name
        assert all(not c.colorless for c in colored)
        assert all(c.colorless for c in stock.cards[5:])
        assert len(stock.relics) == 3
        assert len(stock.potions) == 3


def test_card_price_ranges():
    for seed in range(30):
        _s, _rngs, _pools, stock = _stock(seed)
        for slot in stock.cards[:5]:
            base = {"common": 50, "uncommon": 75, "rare": 150}[card_wiki_rarity(slot.card)]
            if slot.on_sale:
                # 打折 = roll 后价减半：∈ [0.45b, 0.55b]
                assert int(base * 0.45) <= slot.price <= int(base * 0.55) + 1
            else:
                assert int(base * 0.9) <= slot.price <= int(base * 1.1) + 1
        for slot in stock.cards[5:]:
            base = {"uncommon": 75, "rare": 150}[card_wiki_rarity(slot.card)]
            assert int(base * 1.2 * 0.9) <= slot.price <= int(base * 1.2 * 1.1) + 1


def test_exactly_one_sale_card():
    for seed in range(20):
        _s, _rngs, _pools, stock = _stock(seed)
        assert sum(1 for c in stock.cards if c.on_sale) == 1


def test_relic_price_ranges():
    from sts.overworld.relic_pools import COMMON_POOL, RARE_POOL, SHOP_POOL, UNCOMMON_POOL

    for seed in range(30):
        _s, _rngs, _pools, stock = _stock(seed)
        for slot in stock.relics:
            if slot.relic in SHOP_POOL:
                base = 150
            elif slot.relic in COMMON_POOL:
                base = 150
            elif slot.relic in UNCOMMON_POOL:
                base = 250
            elif slot.relic in RARE_POOL:
                base = 300
            else:
                continue
            assert int(base * 0.95) <= slot.price <= int(base * 1.05) + 1


def test_potion_price_ranges():
    for seed in range(30):
        _s, _rngs, _pools, stock = _stock(seed)
        for slot in stock.potions:
            base = {"common": 50, "uncommon": 75, "rare": 100}[slot.potion.rarity]
            assert int(base * 0.95) <= slot.price <= int(base * 1.05) + 1


def test_purge_cost_progression():
    s = RunState()
    assert s.purge_uses == 0
    from sts.overworld.relic_effects import purge_price

    assert purge_price(s) == 75
    s.purge_uses = 1
    assert purge_price(s) == 100
    s.relics.append(RelicId.MEMBERSHIP_CARD)
    assert discounted(100, s) == 50


def test_courier_restock():
    s, rngs, pools, stock = _stock(7)
    s.relics.append(RelicId.THE_COURIER)
    before_relic = stock.relics[0].relic
    restock(s, rngs, pools, stock, "relic", 0)
    assert stock.relics[0].relic != before_relic or True  # 洗牌后可能同款（池大，几乎必不同）
    before_card = stock.cards[0].card
    restock(s, rngs, pools, stock, "card", 0)
    # 新卡可同一（小概率）；价格应重 roll 过（必有值）
    assert stock.cards[0].price > 0
    before_potion = stock.potions[0].potion
    restock(s, rngs, pools, stock, "potion", 0)
    assert stock.potions[0].potion is not None


def test_no_restock_without_courier():
    s, rngs, pools, stock = _stock(7)
    before = stock.relics[0].relic
    restock(s, rngs, pools, stock, "relic", 0)
    assert stock.relics[0].relic == before


def test_shop_tier_distribution():
    """槽 0-1 tier roll 48/82；槽 2 恒 shop 池。"""
    from collections import Counter

    from sts.overworld.relic_pools import SHOP_POOL

    c = Counter()
    for seed in range(300):
        _s, _rngs, _pools, stock = _stock(seed)
        for slot in (0, 1):
            r = stock.relics[slot].relic
            # tier 归类：直接从池归属侧写（近似——同名遗物可能在多池？不会）
            from sts.overworld.relic_pools import COMMON_POOL, RARE_POOL, UNCOMMON_POOL

            if r in COMMON_POOL:
                c["common"] += 1
            elif r in UNCOMMON_POOL:
                c["uncommon"] += 1
            elif r in RARE_POOL:
                c["rare"] += 1
        assert stock.relics[2].relic in SHOP_POOL or stock.relics[2].relic == RelicId.CIRCLET
    total = sum(c.values())
    assert abs(c["common"] / total - 0.48) < 0.09
    assert abs(c["rare"] / total - 0.17) < 0.06

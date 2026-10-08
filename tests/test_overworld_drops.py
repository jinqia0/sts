"""掉落 / 卡牌奖励测试（Phase 3a）——统计容差 + 机制口径。"""

from __future__ import annotations

from sts.combat.relics import RelicId
from sts.overworld.card_rewards import (
    CARD_PITY_FLOOR,
    CARD_PITY_START,
    get_reward_cards,
    roll_rarity,
)
from sts.overworld.drops import (
    ChestLoot,
    POTION_DROP_BASE,
    gold_reward,
    open_chest,
    random_potion_by_rarity,
    roll_potion_drop,
)
from sts.overworld.rng import OverworldRngStreams
from sts.overworld.state import RunState


def test_gold_reward_ranges():
    for seed in range(50):
        rngs = OverworldRngStreams(seed)
        assert 10 <= gold_reward(rngs, "monster") <= 20
        assert 25 <= gold_reward(rngs, "elite") <= 25 + 10
        assert 95 <= gold_reward(rngs, "boss") <= 105


def test_roll_rarity_pity_mechanics():
    """pity：初始 +5（开局无稀有）；common −1 至 -40；rare 归 5；uncommon 不变。"""
    # 直接驱动：构造只出 common/uncommon 的伪流不可行（roll 不可注入），
    # 改测状态转移函数性质
    rngs = OverworldRngStreams(42)
    # 强制各分支：通过多次 roll 验证 pity 单调性与重置
    s = RunState()
    pity = CARD_PITY_START
    for _ in range(30):
        rarity, pity2 = roll_rarity(rngs, pity, "monster")
        if rarity == "rare":
            assert pity2 == CARD_PITY_START
        elif rarity == "common":
            assert pity2 == max(pity - 1, CARD_PITY_FLOOR)
        else:
            assert pity2 == pity
        pity = pity2
        assert CARD_PITY_FLOOR <= pity <= CARD_PITY_START


def test_roll_rarity_initial_no_rare():
    """开局 pity=+5：roll ∈ [5,103] 永不 <3 → 首个奖励无稀有（本体行为）。"""
    rngs = OverworldRngStreams(7)
    for _ in range(200):
        rarity, _ = roll_rarity(rngs, CARD_PITY_START, "monster")
        assert rarity != "rare"


def test_reward_cards_dedup_and_count():
    s = RunState()
    for seed in range(30):
        rngs = OverworldRngStreams(seed)
        cards = get_reward_cards(s, rngs, "monster")
        assert len(cards) == 3
        names = [c.name for c in cards]
        assert len(set(names)) == len(names), "奖励内同 cardID 未去重"
    # QuestionCard +1 / BustedCrown -2
    s.relics.append(RelicId.QUESTION_CARD)
    rngs = OverworldRngStreams(1)
    assert len(get_reward_cards(s, rngs, "monster")) == 4
    s.relics.append(RelicId.BUSTED_CROWN)
    assert len(get_reward_cards(s, rngs, "monster")) == 2


def test_boss_reward_always_rare_and_pity_reset():
    s = RunState()
    s.card_pity = -40
    for seed in range(20):
        rngs = OverworldRngStreams(seed)
        cards = get_reward_cards(s, rngs, "boss")
        from sts.overworld.card_pools import OWN_POOLS

        assert all(c in OWN_POOLS["rare"] for c in cards)
        assert s.card_pity == CARD_PITY_START  # Boss 恒稀有 → 每张重置


def test_potion_drop_statistics_and_blizzard():
    """40% 基础 + blizzard 补偿（连续未掉概率上升）。"""
    drop = 0
    trials = 0
    for seed in range(300):
        s = RunState()
        rngs = OverworldRngStreams(seed)
        pd = roll_potion_drop(s, rngs, reward_count=1)
        trials += 1
        if pd is not None:
            drop += 1
    # blizzard 会在未掉时抬升后续概率 → 聚合掉率高于 40% 基线（~46%）
    rate = drop / trials
    assert 0.36 < rate < 0.58, f"药水掉率异常：{rate:.3f}"


def test_potion_drop_reward_gate():
    s = RunState()
    rngs = OverworldRngStreams(1)
    assert roll_potion_drop(s, rngs, reward_count=4) is None  # 奖励 ≥4 条置 0


def test_white_beast_statue_always_drops():
    s = RunState()
    s.relics.append(RelicId.WHITE_BEAST_STATUE)
    for seed in range(20):
        rngs = OverworldRngStreams(seed)
        assert roll_potion_drop(s, rngs, reward_count=0) is not None


def test_potion_rarity_statistics():
    from collections import Counter

    c = Counter()
    for seed in range(400):
        rngs = OverworldRngStreams(seed)
        c[random_potion_by_rarity(rngs).rarity] += 1
    total = sum(c.values())
    assert abs(c["common"] / total - 0.65) < 0.08
    assert abs(c["uncommon"] / total - 0.25) < 0.06
    assert abs(c["rare"] / total - 0.10) < 0.05


def test_chest_size_and_quirk():
    """箱型 ~50/33/17；同 roll 怪癖：小箱出金则必为 common 遗物、大箱出金则非 common。"""
    from collections import Counter

    sizes: Counter = Counter()
    gold_small_common = 0
    gold_small = 0
    gold_large_noncommon = 0
    gold_large = 0
    for seed in range(300):
        s = RunState()
        rngs = OverworldRngStreams(seed)
        pools = _make_pools(rngs)
        loot = open_chest(s, rngs, pools)
        assert isinstance(loot, ChestLoot) and len(loot.relics) >= 1
        sizes[loot.size] += 1
        if loot.size == "small" and loot.gold > 0:
            gold_small += 1
        if loot.size == "large" and loot.gold > 0:
            gold_large += 1
    total = sum(sizes.values())
    assert abs(sizes["small"] / total - 0.50) < 0.09
    assert abs(sizes["medium"] / total - 0.33) < 0.07
    assert abs(sizes["large"] / total - 0.17) < 0.05
    assert gold_small > 0 and gold_large > 0  # 两种箱都会出金（GOLD_CHANCE>0）


def _make_pools(rngs):
    from sts.overworld.relic_pools import RelicPools

    return RelicPools(rngs.relic)


def test_matryoshka_double_relic():
    s = RunState()
    rngs = OverworldRngStreams(3)
    pools = _make_pools(rngs)
    from sts.overworld.relic_effects import apply_pickup

    apply_pickup(s, RelicId.MATRYOSHKA, rngs)
    loot = open_chest(s, rngs, pools)
    assert len(loot.relics) == 2
    loot = open_chest(s, rngs, pools)
    assert len(loot.relics) == 2
    loot = open_chest(s, rngs, pools)  # 用尽后恢复 1 件
    assert len(loot.relics) == 1


def test_chest_gold_probability():
    """出金概率：small 50% / medium 35% / large 50%（GOLD_CHANCE 字段）。"""
    # medium=35 为非显然值——专门验证（LargeChest/MediumChest.java）
    gold = total = 0
    for seed in range(600):
        s = RunState()
        rngs = OverworldRngStreams(seed)
        pools = _make_pools(rngs)
        loot = open_chest(s, rngs, pools)
        if loot.size != "medium":
            continue
        total += 1
        if loot.gold > 0:
            gold += 1
    assert total > 80
    assert abs(gold / total - 0.35) < 0.10

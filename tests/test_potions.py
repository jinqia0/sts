"""药水批次断言（42 种，对照本体反编译源码 potions/*.java）。

构造模式对齐 test_relics.py：BattleContext(seed=N, potions=[...]) +
setup_hand。选卡/弃牌类药水经 CARD_SELECT 挂起后 choose_cards 驱动。
"""

from __future__ import annotations

import pytest

from sts.combat import BattleContext
from sts.combat.relics import RelicId
from sts.combat.types import (
    InputState,
    MonsterStatus,
    Outcome,
    PlayerStatus,
    Stance,
)
from sts.content.cards import DEFEND, STRIKE, CardDef
from sts.content.monsters import Cultist
from sts.content.potions import (
    ALL_POTIONS,
    AMBROSIA,
    ANCIENT_POTION,
    ATTACK_POTION,
    BLOCK_POTION,
    BLESSING_OF_THE_FORGE,
    BLOOD_POTION,
    BOTTLED_MIRACLE,
    CULTIST_POTION,
    CUNNING_POTION,
    COLORLESS_POTION,
    DEXTERITY_POTION,
    DISTILLED_CHAOS,
    DUPLICATION_POTION,
    ELIXIR_POTION,
    ENERGY_POTION,
    ENTROPIC_BREW,
    ESSENCE_OF_DARKNESS,
    ESSENCE_OF_STEEL,
    EXPLOSIVE_POTION,
    FAIRY_POTION,
    FEAR_POTION,
    FIRE_POTION,
    FOCUS_POTION,
    FRUIT_JUICE,
    GAMBLERS_BREW,
    GHOST_IN_A_JAR,
    HEART_OF_IRON,
    IRONCLAD_POTION_POOL,
    LIQUID_BRONZE,
    LIQUID_MEMORIES,
    POTION_OF_CAPACITY,
    POISON_POTION,
    POWER_POTION,
    REGEN_POTION,
    SKILL_POTION,
    SMOKE_BOMB,
    SNECKO_OIL,
    SPEED_POTION,
    STANCE_POTION,
    STEROID_POTION,
    STRENGTH_POTION,
    SWIFT_POTION,
    WEAK_POTION,
)


def add_cultist(bc: BattleContext, idx: int = 1, hp: int = 50) -> Cultist:
    m = Cultist(idx=idx, hp=hp, max_hp=hp)
    m.set_move(Cultist.INCANTATION)
    bc.monsters.add(m)
    return m


# ---- 覆盖计数与池结构 ----


def test_potion_count_and_unique_ids():
    assert len(ALL_POTIONS) == 42
    assert len({p.pid for p in ALL_POTIONS}) == 42


def test_ironclad_pool_33():
    assert len(IRONCLAD_POTION_POOL) == 33


# ---- 通用 API ----


def test_use_potion_consumes_slot():
    bc = BattleContext(seed=1, potions=[BLOCK_POTION])
    assert bc.player.potions == [BLOCK_POTION, None, None]
    bc.use_potion(0)
    assert bc.player.potions[0] is None


def test_use_potion_rejects_outside_player_normal():
    # 挂起在 CARD_SELECT（选卡界面）期间不可用药水
    from sts.content.cards import APOTHEOSIS

    bc = BattleContext(seed=1, potions=[SWIFT_POTION])
    from sts.combat.actions import Actions

    bc.add_to_bot(Actions.discard_chosen(1))
    bc.set_state(InputState.EXECUTING_ACTIONS)
    bc.execute_actions()
    if bc.input_state == InputState.CARD_SELECT:
        with pytest.raises(ValueError):
            bc.use_potion(0)
    else:
        bc.cards.discard_pile.append(bc.cards.instantiate(APOTHEOSIS))
        bc.add_to_bot(Actions.discard_chosen(2))
        bc.set_state(InputState.EXECUTING_ACTIONS)
        bc.execute_actions()
        assert bc.input_state == InputState.CARD_SELECT
        with pytest.raises(ValueError):
            bc.use_potion(0)


def test_targeting_potion_requires_target():
    bc = BattleContext(seed=1, potions=[WEAK_POTION])
    add_cultist(bc)
    with pytest.raises(ValueError, match="目标"):
        bc.use_potion(0, target=None) if bc.monsters.monster_count != 1 else None
    # 双怪时显式传目标可用
    bc2 = BattleContext(seed=2, potions=[WEAK_POTION])
    add_cultist(bc2)
    bc2.use_potion(0, target=1)
    assert bc2.monsters.monsters[1].statuses.get(MonsterStatus.WEAK) == 3


def test_fairy_potion_not_manually_usable():
    bc = BattleContext(seed=1, potions=[FAIRY_POTION])
    with pytest.raises(ValueError):
        bc.use_potion(0)


# ---- 简单效果 ----


def test_block_potion():
    bc = BattleContext(seed=1, potions=[BLOCK_POTION])
    bc.use_potion(0)
    assert bc.player.block == 12


def test_dexterity_potion():
    bc = BattleContext(seed=1, potions=[DEXTERITY_POTION])
    bc.use_potion(0)
    assert bc.player.statuses.get(PlayerStatus.DEXTERITY) == 2


def test_energy_potion():
    bc = BattleContext(seed=1, potions=[ENERGY_POTION])
    bc.use_potion(0)
    assert bc.player.energy == 5  # 3 + 2


def test_strength_potion():
    bc = BattleContext(seed=1, potions=[STRENGTH_POTION])
    bc.use_potion(0)
    assert bc.player.statuses.get(PlayerStatus.STRENGTH) == 2


def test_regen_potion_heals_at_end_of_round():
    bc = BattleContext(seed=1, potions=[REGEN_POTION])
    bc.player.hp = 50
    bc.use_potion(0)
    assert bc.player.statuses.get(PlayerStatus.REGEN_P) == 5
    bc.end_turn()
    assert bc.player.hp == 55  # 回合末回 5
    assert bc.player.statuses.get(PlayerStatus.REGEN_P) == 4


def test_ancient_potion_artifact():
    bc = BattleContext(seed=1, potions=[ANCIENT_POTION])
    bc.use_potion(0)
    assert bc.player.statuses.get(PlayerStatus.ARTIFACT) == 1


def test_liquid_bronze_thorns():
    bc = BattleContext(seed=1, potions=[LIQUID_BRONZE])
    bc.use_potion(0)
    assert bc.player.statuses.get(PlayerStatus.THORNS) == 3


def test_essence_of_steel_plated_armor():
    bc = BattleContext(seed=1, potions=[ESSENCE_OF_STEEL])
    bc.use_potion(0)
    assert bc.player.statuses.get(PlayerStatus.PLATED_ARMOR) == 4


def test_heart_of_iron_metallicize():
    bc = BattleContext(seed=1, potions=[HEART_OF_IRON])
    bc.use_potion(0)
    assert bc.player.statuses.get(PlayerStatus.METALLICIZE) == 6


def test_ghost_in_a_jar_intangible():
    bc = BattleContext(seed=1, potions=[GHOST_IN_A_JAR])
    bc.use_potion(0)
    assert bc.player.statuses.get(PlayerStatus.INTANGIBLE) == 1


def test_focus_potion():
    bc = BattleContext(seed=1, potions=[FOCUS_POTION])
    bc.use_potion(0)
    assert bc.player.statuses.get(PlayerStatus.FOCUS) == 2


def test_cultist_potion_end_of_turn_strength():
    bc = BattleContext(seed=1, potions=[CULTIST_POTION])
    bc.use_potion(0)
    assert bc.player.statuses.get(PlayerStatus.RITUAL_P) == 1
    bc.end_turn()
    assert bc.player.statuses.get(PlayerStatus.STRENGTH) == 1  # 玩家回合末 +1


def test_steroid_potion_temp_strength():
    bc = BattleContext(seed=1, potions=[STEROID_POTION])
    bc.use_potion(0)
    assert bc.player.statuses.get(PlayerStatus.STRENGTH) == 5
    assert bc.player.statuses.get(PlayerStatus.LOSE_STRENGTH) == 5
    bc.end_turn()
    assert bc.player.statuses.get(PlayerStatus.STRENGTH) == 0  # 回合末 -5


def test_speed_potion_temp_dexterity():
    bc = BattleContext(seed=1, potions=[SPEED_POTION])
    bc.use_potion(0)
    assert bc.player.statuses.get(PlayerStatus.DEXTERITY) == 5
    bc.end_turn()
    assert bc.player.statuses.get(PlayerStatus.DEXTERITY) == 0


# ---- 伤害类 ----


def test_explosive_potion_all_enemies():
    bc = BattleContext(seed=1, potions=[EXPLOSIVE_POTION])
    m1, m2 = bc.monsters.monsters[0], add_cultist(bc)
    bc.use_potion(0)
    assert m1.hp == m1.max_hp - 10
    assert m2.hp == m2.max_hp - 10


def test_fire_potion_single_target_pure_damage():
    bc = BattleContext(seed=1, potions=[FIRE_POTION])
    add_cultist(bc)
    m = bc.monsters.monsters[1]
    # 目标带易伤也不放大（THORNS 类型不过乘区）
    m.statuses.add(MonsterStatus.VULNERABLE, 1)
    hp0 = m.hp
    bc.use_potion(0, target=1)
    assert hp0 - m.hp == 20


def test_weak_fear_poison_targeting():
    bc = BattleContext(seed=1, potions=[WEAK_POTION, FEAR_POTION, POISON_POTION])
    add_cultist(bc)
    m = bc.monsters.monsters[1]
    bc.use_potion(0, target=1)
    bc.use_potion(1, target=1)
    bc.use_potion(2, target=1)
    assert m.statuses.get(MonsterStatus.WEAK) == 3
    assert m.statuses.get(MonsterStatus.VULNERABLE) == 3
    assert m.statuses.get(MonsterStatus.POISON) == 6


# ---- 抽牌 / 手牌类 ----


def test_swift_potion_draws_3():
    bc = BattleContext(seed=1, potions=[SWIFT_POTION])
    n0 = len(bc.cards.hand)
    bc.use_potion(0)
    assert len(bc.cards.hand) == n0 + 3


def test_snecko_oil_draw_and_randomize():
    bc = BattleContext(seed=1, potions=[SNECKO_OIL])
    n0 = len(bc.cards.hand)
    bc.use_potion(0)
    assert len(bc.cards.hand) == n0 + 5
    assert all(0 <= c.cost_for_turn <= 3 for c in bc.cards.hand)


def test_bottled_miracle_two_miracles():
    bc = BattleContext(seed=1, potions=[BOTTLED_MIRACLE])
    bc.use_potion(0)
    miracles = [c for c in bc.cards.hand if c.card.name == "Miracle"]
    assert len(miracles) == 2


def test_cunning_potion_three_upgraded_shivs():
    bc = BattleContext(seed=1, potions=[CUNNING_POTION])
    bc.use_potion(0)
    shivs = [c for c in bc.cards.hand if c.card.name == "Shiv"]
    assert len(shivs) == 3
    assert all(c.upgraded for c in shivs)


def test_liquid_memories_from_discard_zero_cost():
    bc = BattleContext(seed=1, potions=[LIQUID_MEMORIES])
    bc.cards.discard_pile.append(bc.cards.instantiate(STRIKE))
    bc.cards.discard_pile.append(bc.cards.instantiate(DEFEND))
    bc.use_potion(0)
    assert bc.input_state == InputState.CARD_SELECT  # 双候选挂起
    n_hand = len(bc.cards.hand)
    bc.choose_cards([0])  # 堆顶 STRIKE（后进先出索引 0）
    inst = bc.cards.hand[-1]
    assert inst.cost_for_turn == 0
    assert len(bc.cards.hand) == n_hand + 1
    # 单候选路径：弃牌堆仅 1 张时直执不挂起（引擎单候选直执语义）
    bc2 = BattleContext(seed=2, potions=[LIQUID_MEMORIES])
    bc2.cards.discard_pile.append(bc2.cards.instantiate(STRIKE))
    bc2.use_potion(0)
    assert bc2.input_state == InputState.PLAYER_NORMAL
    assert bc2.cards.hand[-1].card is STRIKE


# ---- 选择 / 多段类 ----


def test_attack_potion_discovery_into_hand_free():
    bc = BattleContext(seed=1, potions=[ATTACK_POTION])
    bc.use_potion(0)
    assert bc.input_state == InputState.CARD_SELECT
    info = bc.card_select_info
    assert info is not None and len(info.candidates) == 3
    assert all(c.card.ctype == "Attack" for c in info.candidates)
    bc.choose_cards([0])
    inst = bc.cards.hand[-1]
    assert inst.card.ctype == "Attack"
    assert inst.cost_for_turn == 0


def test_colorless_potion_pool_is_colorless():
    # 当前随机无色池仅 Hand of Greed（_COLORLESS_CARDS）→ 单候选直执入手
    bc = BattleContext(seed=1, potions=[COLORLESS_POTION])
    n_hand = len(bc.cards.hand)
    bc.use_potion(0)
    assert bc.input_state == InputState.PLAYER_NORMAL
    assert len(bc.cards.hand) == n_hand + 1
    assert bc.cards.hand[-1].card.colorless
    assert bc.cards.hand[-1].cost_for_turn == 0


def test_power_potion_pool_is_power():
    bc = BattleContext(seed=1, potions=[POWER_POTION])
    bc.use_potion(0)
    info = bc.card_select_info
    assert all(c.card.ctype == "Power" for c in info.candidates)


def test_gamblers_brew_discard_draw():
    bc = BattleContext(seed=1, potions=[GAMBLERS_BREW])
    n0 = len(bc.cards.hand)
    bc.use_potion(0)
    assert bc.input_state == InputState.CARD_SELECT
    bc.choose_cards([0, 1])
    assert len(bc.cards.hand) == n0
    assert bc.player.cards_discarded_this_turn == 2


def test_elixir_exhausts_chosen():
    bc = BattleContext(seed=1, potions=[ELIXIR_POTION])
    bc.cards.hand.append(bc.cards.instantiate(DEFEND))
    bc.use_potion(0)
    assert bc.input_state == InputState.CARD_SELECT
    bc.choose_cards([0, 1])
    assert len(bc.cards.exhaust_pile) == 2


def test_duplication_potion_next_card_twice():
    bc = BattleContext(seed=1, potions=[DUPLICATION_POTION])
    m = bc.monsters.monsters[0]
    bc.cards.hand.clear()
    bc.cards.hand.append(bc.cards.instantiate(STRIKE))
    bc.use_potion(0)
    bc.play_card(0)
    assert m.hp == m.max_hp - 12  # 打击 6×2


def test_distilled_chaos_plays_top_3():
    bc = BattleContext(seed=1, potions=[DISTILLED_CHAOS])
    # 抽牌堆顶 3 张（默认铁甲初始牌组 >= 3）
    top3 = list(bc.cards.draw_pile[-3:])
    m = bc.monsters.monsters[0]
    hp0 = m.hp
    bc.use_potion(0)
    # 至少 3 张离堆（打出），且怪受了一定伤害（打击类）
    assert all(c not in bc.cards.draw_pile for c in top3)
    assert m.hp < hp0


def test_blessing_of_the_forge_upgrades_hand():
    bc = BattleContext(seed=1, potions=[BLESSING_OF_THE_FORGE])
    assert not all(c.upgraded for c in bc.cards.hand)
    bc.use_potion(0)
    assert all(c.upgraded for c in bc.cards.hand)


def test_fruit_juice_max_hp():
    bc = BattleContext(seed=1, potions=[FRUIT_JUICE])
    hp0, max0 = bc.player.hp, bc.player.max_hp
    bc.use_potion(0)
    assert bc.player.max_hp == max0 + 5
    assert bc.player.hp == hp0 + 5


# ---- 特殊机制 ----


def test_fairy_potion_saves_from_death():
    bc = BattleContext(seed=1, potions=[FAIRY_POTION])
    bc.player.hp = 1
    m = bc.monsters.monsters[0]
    m.set_move(Cultist.DARK_STRIKE)
    bc.end_turn()  # 黑暗打击 6 伤致死 → 精灵免死
    assert bc.outcome == Outcome.UNDECIDED
    assert bc.player.hp == 80 * 30 // 100
    assert bc.player.potions[0] is None  # 已消耗


def test_smoke_bomb_escapes_combat():
    bc = BattleContext(seed=1, potions=[SMOKE_BOMB])
    bc.use_potion(0)
    assert bc.outcome == Outcome.ESCAPED
    assert bc.is_battle_over


def test_smoke_bomb_rejected_in_boss_encounter():
    from sts.combat.relics import BOSS_ENCOUNTERS

    BOSS_ENCOUNTERS.add("guardian")
    try:
        bc = BattleContext(seed=1, encounter="guardian", potions=[SMOKE_BOMB])
        with pytest.raises(ValueError):
            bc.use_potion(0)
    finally:
        BOSS_ENCOUNTERS.discard("guardian")


def test_stance_potion_choice():
    bc = BattleContext(seed=1, potions=[STANCE_POTION])
    bc.use_potion(0, choice="wrath")
    assert bc.player.stance == Stance.WRATH
    assert bc.player.potions[0] is None


def test_stance_potion_rejects_no_choice():
    bc = BattleContext(seed=1, potions=[STANCE_POTION])
    with pytest.raises(ValueError, match="选择"):
        bc.use_potion(0)


def test_ambrosia_divinity():
    bc = BattleContext(seed=1, potions=[AMBROSIA])
    bc.use_potion(0)
    assert bc.player.stance == Stance.DIVINITY


def test_blood_potion_heals_percent():
    bc = BattleContext(seed=1, potions=[BLOOD_POTION])
    bc.player.hp = 10
    bc.use_potion(0)
    assert bc.player.hp == 10 + 16  # 80 × 20% = 16


def test_potion_of_capacity():
    bc = BattleContext(seed=1, potions=[POTION_OF_CAPACITY])
    assert bc.player.orb_slots == 3
    bc.use_potion(0)
    assert bc.player.orb_slots == 5


def test_essence_of_darkness_per_channeled_orb():
    from sts.combat.types import Orb

    bc = BattleContext(seed=1, potions=[ESSENCE_OF_DARKNESS])
    bc.use_potion(0)
    assert bc.player.orbs == []  # 0 球引导：无效果（源码怪癖）
    bc2 = BattleContext(seed=2, potions=[ESSENCE_OF_DARKNESS])
    bc2.player.channel_orb(bc2, Orb.FROST)
    bc2.use_potion(0)
    # 已引导 1 球：循环引导暗球至满槽，满后再引导唤起最老球（冰球）——
    # 净效果 = 3 暗球（对齐源码循环 + channelOrb 满槽唤起语义）
    assert len(bc2.player.orbs) == 3
    assert all(o == Orb.DARK for o in bc2.player.orbs)


def test_entropic_brew_fills_empty_slots():
    from sts.content.potions import ENTROPIC_BREW

    # 3 空槽持 brew：使用后自身槽位腾出，全 3 槽被随机药水填满
    # （本体：for potionSlots → ObtainPotionAction，含自身腾出的槽）
    bc = BattleContext(seed=1, potions=[ENTROPIC_BREW])
    assert all(p is None for p in bc.player.potions[1:])
    bc.use_potion(0)
    assert all(p is not None for p in bc.player.potions)
    assert not any(p is ENTROPIC_BREW for p in bc.player.potions)


# ---- 遗物联动 ----


def test_sacred_bark_doubles_potency():
    bc = BattleContext(seed=1, relics=[RelicId.SACRED_BARK], potions=[BLOCK_POTION])
    bc.use_potion(0)
    assert bc.player.block == 24  # 12 × 2


def test_toy_ornithopter_heals_on_use():
    bc = BattleContext(seed=1, relics=[RelicId.TOY_ORNITHOPTER], potions=[BLOCK_POTION])
    bc.player.hp = 40
    bc.use_potion(0)
    assert bc.player.hp == 45


def test_potion_belt_five_slots():
    bc = BattleContext(seed=1, relics=[RelicId.POTION_BELT], potions=[])
    assert bc.player.potion_slots == 5
    assert len(bc.player.potions) == 5


def test_sozu_blocks_obtain_not_use():
    bc = BattleContext(seed=1, relics=[RelicId.SOZU], potions=[BLOCK_POTION])
    bc.use_potion(0)  # 使用不受阻
    assert bc.player.block == 12
    assert not bc.obtain_potion(BLOOD_POTION)  # 获得被拦


def test_venomology_obtains_potion():
    from sts.content.cards import VENOLOGY

    bc = BattleContext(seed=7)
    bc.cards.hand.clear()
    bc.cards.hand.append(bc.cards.instantiate(VENOLOGY))
    bc.player.energy = 1
    bc.play_card(0)
    assert any(p is not None for p in bc.player.potions)

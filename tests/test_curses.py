"""诅咒卡逐卡断言（cards/curses.py；对齐 lightspeed useNoTriggerCard L933-961）。

构造手牌沿用 test_cards.py 的 setup_hand 模式（清空手牌直接放入指定卡，
初始 5 张直接消失）。默认遭遇 cultist 首动 INCANTATION（无伤害），
回合末 HP 断言不受怪物阶段干扰。C++ 口径：callEndTurnActions 按手牌
顺序入队 no-trigger 卡，regretCardCount = 入队时完整手牌数（含自身）。
"""

import pytest

from sts.combat import BattleContext
from sts.combat.types import PlayerStatus
from sts.content.cards import BURN, BURNING_PACT, DEFEND, STRIKE
from sts.content.cards.curses import (
    ASCENDERS_BANE,
    CLUMSY,
    CURSE_OF_THE_BELL,
    DECAY,
    DOUBT,
    INJURY,
    NECRONOMICURSE,
    NORMALITY,
    PAIN,
    PARASITE,
    PRIDE,
    REGRET,
    SHAME,
    WRITHE,
)


def setup_hand(bc: BattleContext, *cards) -> None:
    """清空手牌并按序放入指定卡（同 test_cards.py 约定）。"""
    bc.cards.hand.clear()
    for c in cards:
        bc.cards.hand.append(bc.cards.instantiate(c))


# ---- Regret：回合末按结算前完整手牌数失去 HP（含自身）----


def test_regret_loses_1_hp_per_hand_card_including_self():
    bc = BattleContext(seed=201)
    setup_hand(bc, STRIKE, REGRET, DEFEND)
    regret = bc.cards.hand[1]
    bc.end_turn()
    # 手牌 3 张（含 Regret 自身，对齐 Regret.java magicNumber=hand.size()）
    assert bc.player.hp == 80 - 3
    assert regret in bc.cards.discard_pile


def test_regret_alone_counts_itself():
    bc = BattleContext(seed=202)
    setup_hand(bc, REGRET)
    bc.end_turn()
    assert bc.player.hp == 80 - 1


def test_regret_ignores_block():
    # PlayerLoseHp 路径不吃格挡（对齐 C++ PlayerLoseHp / 本体 LoseHPAction）
    bc = BattleContext(seed=203)
    setup_hand(bc, REGRET)
    bc.player.block = 10
    bc.end_turn()
    assert bc.player.hp == 80 - 1


def test_regret_counts_cards_settled_before_it():
    # Burn 先于 Regret 结算：C++ 快照口径手牌数 = 2（Burn+Regret），
    # 引擎逐张离手，靠 no_trigger 结算标记重建（cards.py::_burn_effect 协同）
    bc = BattleContext(seed=204)
    setup_hand(bc, BURN, REGRET)
    bc.end_turn()
    # Burn 2 伤（damage 管线）+ Regret 2 点 HP（lose_hp 管线）
    assert bc.player.hp == 80 - 2 - 2


def test_regret_after_previous_turn_burn_not_overcounted():
    # 跨回合隔离：上一回合末结算过的 Burn（在弃牌堆尾部）不计入本回合
    # Regret 的手牌数——no_trigger 结算标记带回合号，只认本回合。
    bc = BattleContext(seed=205)
    setup_hand(bc, BURN)
    bc.end_turn()  # Burn 结算 2 伤，独占弃牌堆尾
    setup_hand(bc, REGRET)
    bc.end_turn()
    # 基线：同种子同流程但第 2 回合手牌换成 STRIKE（不产生 no-trigger 结算，
    # 也不给格挡）；cultist 第 2 回合的攻击伤害在两次中一致（同种子同 RNG 消耗）
    base = BattleContext(seed=205)
    setup_hand(base, BURN)
    base.end_turn()
    setup_hand(base, STRIKE)
    base.end_turn()
    assert bc.player.hp == base.player.hp - 1  # 仅 Regret 自身 1 点


# ---- Decay / Shame / Doubt：回合末状态与伤害路径 ----


def test_decay_2_damage_eats_block():
    # DamagePlayer 路径吃格挡（对齐 C++ DamagePlayer(2, true)）
    bc = BattleContext(seed=207)
    setup_hand(bc, DECAY)
    decay = bc.cards.hand[0]
    bc.player.block = 1
    bc.end_turn()
    assert bc.player.hp == 80 - 1  # 1 点格挡吸收后仍失去 1 HP
    assert decay in bc.cards.discard_pile


def test_decay_full_damage_without_block():
    bc = BattleContext(seed=208)
    setup_hand(bc, DECAY)
    bc.end_turn()
    assert bc.player.hp == 80 - 2


def test_shame_frail_at_end_of_turn():
    bc = BattleContext(seed=209)
    setup_hand(bc, SHAME)
    bc.end_turn()
    assert bc.player.statuses.get(PlayerStatus.FRAIL) == 1


def test_doubt_weak_at_end_of_turn():
    bc = BattleContext(seed=210)
    setup_hand(bc, DOUBT)
    bc.end_turn()
    assert bc.player.statuses.get(PlayerStatus.WEAK) == 1


def test_doubt_weak_does_not_expire_same_round():
    # justApplied 语义（C++ debuff<WEAK>(1, true)）：本回合末施加，
    # 同回合末衰减跳过，虚弱存活到下个玩家回合（此时才是其生效窗口）
    bc = BattleContext(seed=211)
    setup_hand(bc, DOUBT)
    bc.end_turn()
    assert bc.player.statuses.get(PlayerStatus.WEAK) == 1


# ---- Pain：打出其他牌掉血 ----


def test_pain_loses_hp_when_playing_other_cards():
    bc = BattleContext(seed=212)
    setup_hand(bc, STRIKE, PAIN)
    bc.player.hp = 80
    bc.play_card(0)
    assert bc.player.hp == 80 - 1


def test_pain_stacks_in_hand():
    bc = BattleContext(seed=213)
    setup_hand(bc, STRIKE, PAIN, PAIN)
    bc.player.hp = 80
    bc.play_card(0)
    assert bc.player.hp == 80 - 2


def test_pain_does_not_trigger_when_pain_card_is_not_in_hand():
    # Pain 本身不可打出：被消耗掉之后不再掉血
    bc = BattleContext(seed=214)
    setup_hand(bc, STRIKE, PAIN)
    bc.cards.hand.pop(1)  # 模拟 Pain 已离手（如被消耗）
    bc.player.hp = 80
    bc.play_card(0)
    assert bc.player.hp == 80


def test_pain_hp_loss_resolves_before_played_card_effect():
    """顺序回归（2026-10-07 审计）：Pain 的掉血 addToTop 插队头、先于
    打出牌的效果动作执行（本体 Pain.triggerOnOtherCardPlayed →
    addToTop(LoseHPAction)；lightspeed triggerOnOtherCardPlayed 同）。
    场景：玩家 1 HP + Pain 在手 + 打出足以击杀怪物的攻击牌——掉血先
    结算 → 玩家先死（PLAYER_LOSS），攻击不再执行。"""
    from sts.combat.types import Outcome

    bc = BattleContext(seed=215)
    setup_hand(bc, STRIKE, PAIN)
    bc.player.hp = 1
    m = bc.monsters.monsters[0]
    m.hp = 1  # 攻击足以击杀
    bc.play_card(0)
    assert bc.outcome == Outcome.PLAYER_LOSS
    assert m.hp == 1  # 攻击未结算


# ---- 打出拦截：unplayable ----


@pytest.mark.parametrize("curse", [
    REGRET, INJURY, SHAME, PARASITE, NORMALITY, DOUBT, WRITHE,
    PAIN, DECAY, CLUMSY, ASCENDERS_BANE, CURSE_OF_THE_BELL, NECRONOMICURSE,
])
def test_curse_cards_unplayable(curse):
    bc = BattleContext(seed=215)
    setup_hand(bc, curse)
    with pytest.raises(ValueError, match="不可打出"):
        bc.play_card(0)


# ---- Writhe 固有 / Clumsy、Ascender's Bane 虚无 ----


def test_writhe_innate_in_opening_hand():
    bc = BattleContext(seed=216, deck=[WRITHE, STRIKE, STRIKE, STRIKE, STRIKE, STRIKE])
    assert any(c.card is WRITHE for c in bc.cards.hand)


def test_clumsy_ethereal_exhausts_at_end_of_turn():
    bc = BattleContext(seed=217)
    setup_hand(bc, CLUMSY, STRIKE)
    clumsy = bc.cards.hand[0]
    strike = bc.cards.hand[1]
    bc.end_turn()
    assert clumsy in bc.cards.exhaust_pile
    assert clumsy not in bc.cards.discard_pile
    assert strike in bc.cards.discard_pile  # 普通手牌正常弃置


def test_ascenders_bane_ethereal_exhausts_at_end_of_turn():
    bc = BattleContext(seed=218)
    setup_hand(bc, ASCENDERS_BANE)
    bane = bc.cards.hand[0]
    bc.end_turn()
    assert bane in bc.cards.exhaust_pile


# ---- Curse of the Bell / Necronomicurse ----


def test_curse_of_the_bell_no_copy_on_exhaust():
    # wiki 口径（2026-10-06 复核）："Unplayable. Cannot be removed from your
    # deck."——被消耗时**无**复制效果；lightspeed 的 triggerOnExhaust 复制
    # 系其笔误，此前被误继承，已移除。
    bc = BattleContext(seed=219)
    setup_hand(bc, BURNING_PACT, CURSE_OF_THE_BELL)
    bell = bc.cards.hand[1]
    bc.play_card(0)  # 唯一手牌候选 → 选卡直执消耗
    assert bell in bc.cards.exhaust_pile
    assert not any(c.card is CURSE_OF_THE_BELL for c in bc.cards.hand)


def test_necronomicurse_copies_on_exhaust():
    bc = BattleContext(seed=220)
    setup_hand(bc, BURNING_PACT, NECRONOMICURSE)
    curse = bc.cards.hand[1]
    bc.play_card(0)
    assert curse in bc.cards.exhaust_pile
    copies = [c for c in bc.cards.hand if c.card is NECRONOMICURSE]
    assert len(copies) == 1


def test_necronomicurse_no_copy_when_discarded_normally():
    # 仅消耗触发复制；回合末正常弃置不复制
    bc = BattleContext(seed=221)
    setup_hand(bc, NECRONOMICURSE, STRIKE)
    curse = bc.cards.hand[0]
    bc.end_turn()
    assert curse in bc.cards.discard_pile
    assert not any(c.card is NECRONOMICURSE for c in bc.cards.hand)
    assert not any(c.card is NECRONOMICURSE for c in bc.cards.exhaust_pile)


# ---- Pride：可打出的诅咒（cost 1 / 固有 / 打出即消耗）----


def test_pride_playable_and_exhausts_on_play():
    bc = BattleContext(seed=222)
    setup_hand(bc, PRIDE, STRIKE)
    assert bc.player.energy == 3
    bc.play_card(0)  # 1 费可打出，不抛异常
    assert bc.player.energy == 2
    assert not any(c.card is PRIDE for c in bc.cards.hand)
    assert not any(c.card is PRIDE for c in bc.cards.discard_pile)
    assert sum(1 for c in bc.cards.exhaust_pile if c.card is PRIDE) == 1
    # 打出仅消耗，不复制（复制只发生在回合末留在手中时）
    assert not any(c.card is PRIDE for c in bc.cards.draw_pile)


def test_pride_innate_and_copies_to_draw_top_at_end_of_turn():
    # 牌组仅 2 张：Pride（固有开局在手）+ Strike。回合末结算：
    # 副本置抽牌堆顶 + 原牌正常弃置（不消耗，对齐 Pride.java）。
    bc = BattleContext(seed=223, deck=[PRIDE, STRIKE])
    assert [c.card for c in bc.cards.hand] == [PRIDE, STRIKE]
    original = bc.cards.hand[0]
    bc.end_turn()
    # 原牌经回合末弃牌阶段弃置，随后洗回 → 手中 2 张 Pride（原 + 副本）
    assert bc.cards.exhaust_pile == []  # 未消耗
    prides = [c for c in bc.cards.hand if c.card is PRIDE]
    assert len(prides) == 2
    assert original in bc.cards.hand  # 原实例经洗牌回到手中


# ---- 多诅咒回合末：结算顺序 = 手牌顺序（对齐 C++ 入队）----


def test_multiple_curses_settle_in_hand_order():
    bc = BattleContext(seed=224)
    decay, regret, doubt = (bc.cards.instantiate(c) for c in (DECAY, REGRET, DOUBT))
    bc.cards.hand.clear()
    bc.cards.hand.extend([decay, regret, doubt])
    bc.end_turn()
    # Decay 2 伤（damage）+ Regret 3 HP（手牌 3 张）→ 75；Doubt 施加 1 虚弱
    assert bc.player.hp == 80 - 2 - 3
    assert bc.player.statuses.get(PlayerStatus.WEAK) == 1
    # 三张均结算离手，弃牌堆顺序 = 手牌顺序（对齐 C++ 逐张入队出队）
    assert [c.card.name for c in bc.cards.discard_pile[:3]] == ["Decay", "Regret", "Doubt"]


def test_two_regrets_both_count_full_hand():
    bc = BattleContext(seed=225)
    setup_hand(bc, REGRET, REGRET)
    bc.end_turn()
    # C++：两张 Regret 的 regretCardCount 均为入队时手牌数 2
    assert bc.player.hp == 80 - 2 - 2


def test_burn_triggers_rupture():
    """Burn 的回合末结算在 C++ 传 selfDamage=true（DamagePlayer 第二参）
    → 触发 RUPTURE（引擎 damage_player 已补 self_inflicted 位）。"""
    from sts.combat import BattleContext
    from sts.combat.types import PlayerStatus
    from sts.content.cards import BURN

    bc = BattleContext(seed=900)
    bc.cards.hand.clear()
    burn = bc.cards.instantiate(BURN)
    bc.cards.hand.append(burn)
    bc.player.statuses.add(PlayerStatus.RUPTURE, 1)
    bc.end_turn()
    assert bc.player.statuses.get(PlayerStatus.STRENGTH) == 1
    # 格挡全额吸收的 Burn 不触发（无 HP 损失）
    bc2 = BattleContext(seed=901)
    bc2.cards.hand.clear()
    bc2.cards.hand.append(bc2.cards.instantiate(BURN))
    bc2.player.statuses.add(PlayerStatus.RUPTURE, 1)
    bc2.player.block = 10  # BARRICADE 语义：手动保留格挡观察
    bc2.player.statuses.add(PlayerStatus.BARRICADE, 1)
    bc2.end_turn()
    assert bc2.player.statuses.get(PlayerStatus.STRENGTH) == 0  # 无 HP 损失不触发

"""Silent 全卡移植断言（数值/结算以 slaythespire.wiki.gg 为权威源，
Cards.h 交叉校验费用/消耗/固定位；状态语义对齐 lightspeed C++ 已实现部分）。

逐卡至少 1 用例 + 升级分支。沿用 test_colorless_cards.py 的构造模式
（setup_hand / add_cultist / 手动填抽牌堆），保证出牌序列确定、不依赖
初始洗牌；抽牌堆默认保留遭遇牌组的 5 张残余——引擎主循环有"三堆皆空
即判负"的守卫（battle.py execute_actions），测试中清空抽牌堆的用例必须
在断言前保留至少一张牌在手/堆中。

引擎接线状态（见 cards/silent.py 模块注释）：
- 已接（f0d724f / 批次 A）：POISON/ENVENOM/CORPSE_EXPLOSION/弃牌管线/
  Retain/next_turn_cards/special["wlp"]/NO_DRAW/NOXIOUS_FUMES 落点等——
  全流程断言；
- 未接（special 槽位）：next_turn_energy / next_turn_draw / blur_next_turn /
  tott_draw / wraith_form_dex / CHOKED 触发 / Endless Agony 抽到复制 /
  Eviscerate 动态费用——只断言槽位落地或近似行为；
- 7 个预留状态（AFTER_IMAGE/BURST/A_THOUSAND_CUTS/ACCURACY/
  INFINITE_BLADES/NOXIOUS_FUMES/PHANTASMAL_KILLER）：本文件按任务口径只
  测"状态落地"（层数/费用/固有位），结算行为由主会话补测。
"""

import subprocess
import sys

import pytest

from sts.combat import BattleContext
from sts.combat.types import InputState, MonsterStatus, Outcome, PlayerStatus
from sts.content.cards import CardDef
from sts.content.monsters import Cultist

from sts.content.cards import STRIKE
from sts.content.cards.silent import (
    ENDLESS_AGONY,
    EVISCERATE,
    ACCURACY,
    ACROBATICS,
    ADRENALINE,
    A_THOUSAND_CUTS,
    ALL_OUT_ATTACK,
    AFTER_IMAGE,
    BACKFLIP,
    BACKSTAB,
    BANE,
    BLADE_DANCE,
    BLUR,
    BOUNCING_FLASK,
    BULLET_TIME,
    BURST,
    CALCULATED_GAMBLE,
    CALTROPS,
    CATALYST,
    CHOKE,
    CLOAK_AND_DAGGER,
    CONCENTRATE,
    CORPSE_EXPLOSION,
    CRIPPLING_CLOUD,
    DAGGER_SPRAY,
    DAGGER_THROW,
    DASH,
    DEADLY_POISON,
    DEFEND_S,
    DEFLECT,
    DIE_DIE_DIE,
    DISTRACTION,
    DODGE_AND_ROLL,
    DOPPELGANGER,
    ENDLESS_AGONY,
    ENVENOM,
    ESCAPE_PLAN,
    EVISCERATE,
    EXPERTISE,
    FINISHER,
    FLECHETTES,
    FLYING_KNEE,
    FOOTWORK,
    GLASS_KNIFE,
    GRAND_FINALE,
    HEEL_HOOK,
    INFINITE_BLADES,
    LEG_SWEEP,
    MALAISE,
    MASTERFUL_STAB,
    NEUTRALIZE,
    NIGHTMARE,
    NOXIOUS_FUMES,
    OUTMANEUVER,
    PHANTASMAL_KILLER,
    PIERCING_WAIL,
    POISONED_STAB,
    PREPARED,
    PREDATOR,
    QUICK_SLASH,
    REFLEX,
    RIDDLE_WITH_HOLES,
    SETUP,
    SHIV,
    SKEWER,
    SLICE,
    SNEAKY_STRIKE,
    STORM_OF_STEEL,
    STRIKE_S,
    SUCKER_PUNCH,
    SURVIVOR,
    TACTICIAN,
    TERROR,
    TOOLS_OF_THE_TRADE,
    UNLOAD,
    WELL_LAID_PLANS,
    WRAITH_FORM,
)

from tests.test_engine_batch0 import run_queue


def setup_hand(bc: BattleContext, *cards) -> None:
    bc.cards.hand.clear()
    for c in cards:
        bc.cards.hand.append(bc.cards.instantiate(c))


def setup_hand_upgraded(bc: BattleContext, *cards) -> None:
    bc.cards.hand.clear()
    for c in cards:
        inst = bc.cards.instantiate(c)
        inst.upgraded = True
        bc.cards.hand.append(inst)


def fill_draw(bc: BattleContext, n: int, card: CardDef = DEFLECT) -> None:
    bc.cards.draw_pile.clear()
    for _ in range(n):
        bc.cards.draw_pile.append(bc.cards.instantiate(card))


def add_cultist(bc: BattleContext, idx: int = 1, hp: int = 99) -> Cultist:
    m = Cultist(idx=idx, hp=hp, max_hp=hp)
    m.set_move(Cultist.INCANTATION)
    bc.monsters.add(m)
    return m


def pile_names(bc, pile) -> list[str]:
    return [c.card.name for c in pile]


# ---- re-export 与导入顺序 ----


def test_silent_reexport_via_cards_module():
    import sts.content.cards.silent as sc
    import sts.content.cards as cards_mod

    assert cards_mod.SHIV is sc.SHIV
    assert cards_mod.SURVIVOR is sc.SURVIVOR
    assert cards_mod.NIGHTMARE is sc.NIGHTMARE
    # 与铁甲的 STRIKE/DEFEND 不同对象，卡名刻意同名（CARD_INDEX 按名去重）
    assert cards_mod.STRIKE_S is sc.STRIKE_S
    assert cards_mod.STRIKE_S.name == "Strike"
    assert cards_mod.STRIKE_S is not cards_mod.STRIKE


def test_silent_first_import_order_keeps_reexport():
    """cards.silent 被先行导入时，包根 eager re-export 仍可用。"""
    code = (
        "import sts.content.cards.silent as sc; "
        "from sts.content import cards; "
        "assert cards.SHIV is sc.SHIV; "
        "from sts.content.cards import REGRET; "  # 诅咒 re-export 不受影响
        "from sts.content.cards import TRANSMUTATION"  # 无色 re-export 不受影响
    )
    subprocess.run([sys.executable, "-c", code], check=True, timeout=60)


def test_silent_card_count_and_types():
    """wiki 口径：75 张（4 基础 + 19 普通 + 33 非普通 + 19 稀有，含跳过的
    Alchemize）；本模块正式定义 74 张 + SHIV = 75 个 CardDef。"""
    import sts.content.cards.silent as sc

    cards = [g for g in vars(sc).values() if isinstance(g, CardDef)]
    assert len(cards) == 75
    assert SHIV.cost == 0 and SHIV.exhausts and SHIV.ctype == "Attack"


# ---- 基础 4 张 + SHIV ----


def test_strike_s_deals_6():
    bc = BattleContext(seed=600)
    m = bc.monsters.monsters[0]
    hp0 = m.hp
    setup_hand(bc, STRIKE_S)
    bc.play_card(0)
    assert m.hp == hp0 - 6


def test_strike_s_upgraded_deals_9():
    bc = BattleContext(seed=601)
    m = bc.monsters.monsters[0]
    hp0 = m.hp
    setup_hand_upgraded(bc, STRIKE_S)
    bc.play_card(0)
    assert m.hp == hp0 - 9


def test_defend_s_gains_5_block():
    bc = BattleContext(seed=602)
    setup_hand(bc, DEFEND_S)
    bc.play_card(0)
    assert bc.player.block == 5


def test_defend_s_upgraded_gains_8_block():
    bc = BattleContext(seed=603)
    setup_hand_upgraded(bc, DEFEND_S)
    bc.play_card(0)
    assert bc.player.block == 8


def test_neutralize_damage_and_weak():
    bc = BattleContext(seed=604)
    m = bc.monsters.monsters[0]
    hp0 = m.hp
    setup_hand(bc, NEUTRALIZE)
    bc.play_card(0)
    assert m.hp == hp0 - 3
    assert m.statuses.get(MonsterStatus.WEAK) == 1


def test_neutralize_upgraded():
    bc = BattleContext(seed=605)
    m = bc.monsters.monsters[0]
    hp0 = m.hp
    setup_hand_upgraded(bc, NEUTRALIZE)
    bc.play_card(0)
    assert m.hp == hp0 - 4
    assert m.statuses.get(MonsterStatus.WEAK) == 2


def test_survivor_block_and_discard():
    bc = BattleContext(seed=606)
    setup_hand(bc, SURVIVOR, DEFLECT)
    bc.play_card(0)
    assert bc.player.block == 8
    # 唯一弃牌候选 → 单候选直执（open_card_select 内建），不进选卡状态
    assert bc.cards.hand == []
    assert bc.player.cards_discarded_this_turn == 1
    assert pile_names(bc, bc.cards.discard_pile).count("Deflect") == 1


def test_survivor_upgraded_block_11():
    bc = BattleContext(seed=607)
    setup_hand_upgraded(bc, SURVIVOR)
    bc.play_card(0)
    assert bc.player.block == 11
    # 空手弃 1：无候选直接跳过（对齐 discard_chosen 空手分支）
    assert bc.input_state == InputState.PLAYER_NORMAL


def test_shiv_deals_4_and_exhausts():
    bc = BattleContext(seed=608)
    m = bc.monsters.monsters[0]
    hp0 = m.hp
    setup_hand(bc, SHIV)
    bc.play_card(0)
    assert m.hp == hp0 - 4
    assert pile_names(bc, bc.cards.exhaust_pile) == ["Shiv"]
    assert bc.cards.discard_pile == []


def test_shiv_upgraded_deals_6():
    bc = BattleContext(seed=609)
    m = bc.monsters.monsters[0]
    hp0 = m.hp
    setup_hand_upgraded(bc, SHIV)
    bc.play_card(0)
    assert m.hp == hp0 - 6


# ---- 普通 19 张 ----


def test_acrobatics_draws_3_discards_1():
    bc = BattleContext(seed=610)
    fill_draw(bc, 3)
    setup_hand(bc, ACROBATICS)
    bc.play_card(0)
    assert len(bc.cards.hand) == 3
    bc.choose_cards([0])
    assert len(bc.cards.hand) == 2
    assert bc.player.cards_discarded_this_turn == 1


def test_acrobatics_upgraded_draws_4():
    bc = BattleContext(seed=611)
    fill_draw(bc, 4)
    setup_hand_upgraded(bc, ACROBATICS)
    bc.play_card(0)
    assert len(bc.cards.hand) == 4
    bc.choose_cards([0])
    assert len(bc.cards.hand) == 3


def test_backflip_block_and_draw():
    bc = BattleContext(seed=612)
    fill_draw(bc, 2)
    setup_hand(bc, BACKFLIP)
    bc.play_card(0)
    assert bc.player.block == 5
    assert len(bc.cards.hand) == 2


def test_backflip_upgraded_block_8():
    bc = BattleContext(seed=613)
    fill_draw(bc, 2)
    setup_hand_upgraded(bc, BACKFLIP)
    bc.play_card(0)
    assert bc.player.block == 8
    assert len(bc.cards.hand) == 2


def test_bane_single_hit_without_poison():
    bc = BattleContext(seed=614)
    m = bc.monsters.monsters[0]
    hp0 = m.hp
    setup_hand(bc, BANE)
    bc.play_card(0)
    assert m.hp == hp0 - 7


def test_bane_double_hit_with_poison():
    bc = BattleContext(seed=615)
    m = bc.monsters.monsters[0]
    m.statuses.add(MonsterStatus.POISON, 1)
    hp0 = m.hp
    setup_hand(bc, BANE)
    bc.play_card(0)
    assert m.hp == hp0 - 14


def test_bane_upgraded_deals_10_twice():
    bc = BattleContext(seed=616)
    m = bc.monsters.monsters[0]
    m.statuses.add(MonsterStatus.POISON, 1)
    hp0 = m.hp
    setup_hand_upgraded(bc, BANE)
    bc.play_card(0)
    assert m.hp == hp0 - 20


def test_blade_dance_adds_3_shivs():
    bc = BattleContext(seed=617)
    setup_hand(bc, BLADE_DANCE)
    bc.play_card(0)
    assert len(bc.cards.hand) == 3
    assert all(c.card is SHIV and c.cost == 0 for c in bc.cards.hand)


def test_blade_dance_upgraded_adds_4_shivs():
    bc = BattleContext(seed=618)
    setup_hand_upgraded(bc, BLADE_DANCE)
    bc.play_card(0)
    assert len(bc.cards.hand) == 4
    assert all(c.card is SHIV for c in bc.cards.hand)


def test_cloak_and_dagger_block_and_shiv():
    bc = BattleContext(seed=619)
    setup_hand(bc, CLOAK_AND_DAGGER)
    bc.play_card(0)
    assert bc.player.block == 6
    assert pile_names(bc, bc.cards.hand) == ["Shiv"]


def test_cloak_and_dagger_upgraded_2_shivs():
    bc = BattleContext(seed=620)
    setup_hand_upgraded(bc, CLOAK_AND_DAGGER)
    bc.play_card(0)
    assert bc.player.block == 6
    assert len(bc.cards.hand) == 2
    assert all(c.card is SHIV for c in bc.cards.hand)


def test_dagger_spray_hits_all_twice():
    bc = BattleContext(seed=621)
    m2 = add_cultist(bc)
    m1 = bc.monsters.monsters[0]
    hp1, hp2 = m1.hp, m2.hp
    setup_hand(bc, DAGGER_SPRAY)
    bc.play_card(0)
    assert m1.hp == hp1 - 8
    assert m2.hp == hp2 - 8


def test_dagger_spray_upgraded_6_twice():
    bc = BattleContext(seed=622)
    m2 = add_cultist(bc)
    m1 = bc.monsters.monsters[0]
    hp1, hp2 = m1.hp, m2.hp
    setup_hand_upgraded(bc, DAGGER_SPRAY)
    bc.play_card(0)
    assert m1.hp == hp1 - 12
    assert m2.hp == hp2 - 12


def test_dagger_throw_draw_and_discard():
    bc = BattleContext(seed=623)
    m = bc.monsters.monsters[0]
    hp0 = m.hp
    fill_draw(bc, 1)
    setup_hand(bc, DAGGER_THROW, DEFLECT)
    bc.play_card(0)
    assert m.hp == hp0 - 9
    assert len(bc.cards.hand) == 2  # DEFLECT + 新抽 1 张
    bc.choose_cards([0])
    assert len(bc.cards.hand) == 1
    assert bc.player.cards_discarded_this_turn == 1


def test_dagger_throw_upgraded_deals_12():
    bc = BattleContext(seed=624)
    m = bc.monsters.monsters[0]
    hp0 = m.hp
    fill_draw(bc, 1)
    setup_hand_upgraded(bc, DAGGER_THROW, DEFLECT)
    bc.play_card(0)
    assert m.hp == hp0 - 12
    bc.choose_cards([0])


def test_deadly_poison_applies_5():
    bc = BattleContext(seed=625)
    m = bc.monsters.monsters[0]
    setup_hand(bc, DEADLY_POISON)
    bc.play_card(0)
    assert m.statuses.get(MonsterStatus.POISON) == 5


def test_deadly_poison_upgraded_applies_7():
    bc = BattleContext(seed=626)
    m = bc.monsters.monsters[0]
    setup_hand_upgraded(bc, DEADLY_POISON)
    bc.play_card(0)
    assert m.statuses.get(MonsterStatus.POISON) == 7


def test_poison_ticks_at_turn_start():
    """毒的引擎结算：回合开始掉层数血、层数-1（批次 A 已接）。"""
    bc = BattleContext(seed=627)
    m = bc.monsters.monsters[0]
    m.hp = 50
    setup_hand(bc, DEADLY_POISON)
    bc.play_card(0)
    bc.end_turn()
    assert m.hp == 50 - 5
    assert m.statuses.get(MonsterStatus.POISON) == 4


def test_deflect_gains_4_block():
    bc = BattleContext(seed=628)
    setup_hand(bc, DEFLECT)
    bc.play_card(0)
    assert bc.player.block == 4


def test_deflect_upgraded_gains_7_block():
    bc = BattleContext(seed=629)
    setup_hand_upgraded(bc, DEFLECT)
    bc.play_card(0)
    assert bc.player.block == 7


def test_dodge_and_roll_next_turn_block():
    bc = BattleContext(seed=630)
    setup_hand(bc, DODGE_AND_ROLL)
    bc.play_card(0)
    assert bc.player.block == 4
    bc.end_turn()
    # NEXT_TURN_BLOCK：回合开始获得 4 格挡后移除（引擎已接）
    assert bc.player.block == 4
    assert not bc.player.statuses.has(PlayerStatus.NEXT_TURN_BLOCK)


def test_dodge_and_roll_upgraded_6_and_6():
    bc = BattleContext(seed=631)
    setup_hand_upgraded(bc, DODGE_AND_ROLL)
    bc.play_card(0)
    assert bc.player.block == 6
    bc.end_turn()
    assert bc.player.block == 6


def test_flying_knee_damage_and_next_turn_energy_slot():
    bc = BattleContext(seed=632)
    m = bc.monsters.monsters[0]
    hp0 = m.hp
    setup_hand(bc, FLYING_KNEE)
    bc.play_card(0)
    assert m.hp == hp0 - 8
    # 引擎 _recharge_energy 尚未读此槽（接线见迁移报告），先断言槽位
    assert bc.player.special.get("next_turn_energy") == 1


def test_flying_knee_upgraded_deals_11():
    bc = BattleContext(seed=633)
    m = bc.monsters.monsters[0]
    hp0 = m.hp
    setup_hand_upgraded(bc, FLYING_KNEE)
    bc.play_card(0)
    assert m.hp == hp0 - 11
    assert bc.player.special.get("next_turn_energy") == 1


def test_outmaneuver_next_turn_energy_2():
    bc = BattleContext(seed=634)
    setup_hand(bc, OUTMANEUVER)
    bc.play_card(0)
    assert bc.player.special.get("next_turn_energy") == 2


def test_outmaneuver_upgraded_next_turn_energy_3():
    bc = BattleContext(seed=635)
    setup_hand_upgraded(bc, OUTMANEUVER)
    bc.play_card(0)
    assert bc.player.special.get("next_turn_energy") == 3


def test_piercing_wail_strength_loss_and_restore():
    bc = BattleContext(seed=636)
    m2 = add_cultist(bc)
    m1 = bc.monsters.monsters[0]
    setup_hand(bc, PIERCING_WAIL)
    bc.play_card(0)
    assert m1.statuses.get(MonsterStatus.STRENGTH) == -6
    assert m1.statuses.get(MonsterStatus.SHACKLED) == 6
    assert m2.statuses.get(MonsterStatus.STRENGTH) == -6
    assert pile_names(bc, bc.cards.exhaust_pile) == ["Piercing Wail"]
    bc.end_turn()  # 怪回合末回补（SHACKLED 已接）
    assert m1.statuses.get(MonsterStatus.STRENGTH) == 0
    assert not m1.statuses.has(MonsterStatus.SHACKLED)


def test_piercing_wail_upgraded_loses_8():
    bc = BattleContext(seed=637)
    m = bc.monsters.monsters[0]
    setup_hand_upgraded(bc, PIERCING_WAIL)
    bc.play_card(0)
    assert m.statuses.get(MonsterStatus.STRENGTH) == -8


def test_poisoned_stab_damage_and_poison():
    bc = BattleContext(seed=638)
    m = bc.monsters.monsters[0]
    hp0 = m.hp
    setup_hand(bc, POISONED_STAB)
    bc.play_card(0)
    assert m.hp == hp0 - 6
    assert m.statuses.get(MonsterStatus.POISON) == 3


def test_poisoned_stab_upgraded():
    bc = BattleContext(seed=639)
    m = bc.monsters.monsters[0]
    hp0 = m.hp
    setup_hand_upgraded(bc, POISONED_STAB)
    bc.play_card(0)
    assert m.hp == hp0 - 8
    assert m.statuses.get(MonsterStatus.POISON) == 4


def test_prepared_draws_and_discards():
    bc = BattleContext(seed=640)
    fill_draw(bc, 1)
    setup_hand(bc, PREPARED, DEFLECT)
    bc.play_card(0)
    assert len(bc.cards.hand) == 2  # DEFLECT + 新抽
    bc.choose_cards([0])
    assert len(bc.cards.hand) == 1
    assert bc.player.cards_discarded_this_turn == 1


def test_prepared_upgraded_2_and_2():
    bc = BattleContext(seed=641)
    fill_draw(bc, 2)
    setup_hand_upgraded(bc, PREPARED)
    bc.play_card(0)
    assert len(bc.cards.hand) == 2
    bc.choose_cards([0, 1])
    assert bc.cards.hand == []
    assert bc.player.cards_discarded_this_turn == 2


def test_quick_slash_damage_and_draw():
    bc = BattleContext(seed=642)
    m = bc.monsters.monsters[0]
    hp0 = m.hp
    fill_draw(bc, 1)
    setup_hand(bc, QUICK_SLASH)
    bc.play_card(0)
    assert m.hp == hp0 - 8
    assert len(bc.cards.hand) == 1


def test_quick_slash_upgraded_deals_12():
    bc = BattleContext(seed=643)
    m = bc.monsters.monsters[0]
    hp0 = m.hp
    fill_draw(bc, 1)
    setup_hand_upgraded(bc, QUICK_SLASH)
    bc.play_card(0)
    assert m.hp == hp0 - 12


def test_slice_deals_6():
    bc = BattleContext(seed=644)
    m = bc.monsters.monsters[0]
    hp0 = m.hp
    setup_hand(bc, SLICE)
    bc.play_card(0)
    assert m.hp == hp0 - 6


def test_slice_upgraded_deals_9():
    bc = BattleContext(seed=645)
    m = bc.monsters.monsters[0]
    hp0 = m.hp
    setup_hand_upgraded(bc, SLICE)
    bc.play_card(0)
    assert m.hp == hp0 - 9


def test_sneaky_strike_no_energy_without_discard():
    bc = BattleContext(seed=646)
    m = bc.monsters.monsters[0]
    hp0 = m.hp
    setup_hand(bc, SNEAKY_STRIKE)
    bc.play_card(0)
    assert m.hp == hp0 - 12
    assert bc.player.energy == 1  # 3 - 2 费，无弃牌不加能量


def test_sneaky_strike_gains_2_after_discard():
    bc = BattleContext(seed=647)
    setup_hand(bc, SNEAKY_STRIKE, DEFLECT)
    bc.manual_discard(bc.cards.hand[1])
    bc.play_card(0)
    assert bc.player.energy == 3  # 3 - 2 + 2


def test_sneaky_strike_upgraded_deals_16():
    bc = BattleContext(seed=648)
    m = bc.monsters.monsters[0]
    hp0 = m.hp
    setup_hand_upgraded(bc, SNEAKY_STRIKE, DEFLECT)
    bc.manual_discard(bc.cards.hand[1])
    bc.play_card(0)
    assert m.hp == hp0 - 16
    assert bc.player.energy == 3


def test_sucker_punch_damage_and_weak():
    bc = BattleContext(seed=649)
    m = bc.monsters.monsters[0]
    hp0 = m.hp
    setup_hand(bc, SUCKER_PUNCH)
    bc.play_card(0)
    assert m.hp == hp0 - 7
    assert m.statuses.get(MonsterStatus.WEAK) == 1


def test_sucker_punch_upgraded():
    bc = BattleContext(seed=650)
    m = bc.monsters.monsters[0]
    hp0 = m.hp
    setup_hand_upgraded(bc, SUCKER_PUNCH)
    bc.play_card(0)
    assert m.hp == hp0 - 9
    assert m.statuses.get(MonsterStatus.WEAK) == 2


# ---- 非普通 33 张 ----


def test_accuracy_status_landing():
    bc = BattleContext(seed=651)
    setup_hand(bc, ACCURACY)
    bc.play_card(0)
    # wiki：袖剑 +4 伤害（状态层=附加伤害）；Shiv 加伤结算段在引擎
    # calculate_card_damage（f0d724f 已接，主会话补测全行为）
    assert bc.player.statuses.get(PlayerStatus.ACCURACY) == 4


def test_accuracy_upgraded_lands_6():
    bc = BattleContext(seed=652)
    setup_hand_upgraded(bc, ACCURACY)
    bc.play_card(0)
    assert bc.player.statuses.get(PlayerStatus.ACCURACY) == 6


def test_all_out_attack_all_and_random_discard():
    bc = BattleContext(seed=653)
    m2 = add_cultist(bc)
    m1 = bc.monsters.monsters[0]
    hp1, hp2 = m1.hp, m2.hp
    setup_hand(bc, ALL_OUT_ATTACK, DEFLECT, DEFLECT)
    bc.play_card(0)
    assert m1.hp == hp1 - 10
    assert m2.hp == hp2 - 10
    assert len(bc.cards.hand) == 1  # 随机弃 1
    assert bc.player.cards_discarded_this_turn == 1


def test_all_out_attack_upgraded_14():
    bc = BattleContext(seed=654)
    m = bc.monsters.monsters[0]
    hp0 = m.hp
    setup_hand_upgraded(bc, ALL_OUT_ATTACK)
    bc.play_card(0)
    assert m.hp == hp0 - 14


def test_backstab_innate_damage_and_exhaust():
    assert BACKSTAB.innate
    assert BACKSTAB.exhausts
    bc = BattleContext(seed=655)
    m = bc.monsters.monsters[0]
    hp0 = m.hp
    setup_hand(bc, BACKSTAB)
    bc.play_card(0)
    assert m.hp == hp0 - 11
    assert pile_names(bc, bc.cards.exhaust_pile) == ["Backstab"]


def test_backstab_upgraded_deals_15():
    bc = BattleContext(seed=656)
    m = bc.monsters.monsters[0]
    hp0 = m.hp
    setup_hand_upgraded(bc, BACKSTAB)
    bc.play_card(0)
    assert m.hp == hp0 - 15
    assert pile_names(bc, bc.cards.exhaust_pile) == ["Backstab"]


def test_blur_block_and_next_turn_flag():
    bc = BattleContext(seed=657)
    setup_hand(bc, BLUR)
    bc.play_card(0)
    assert bc.player.block == 5
    # 格挡衰减豁免需引擎 after_monster_turns 读此槽（接线见迁移报告）
    assert bc.player.special.get("blur_next_turn") == 1


def test_blur_upgraded_block_8():
    bc = BattleContext(seed=658)
    setup_hand_upgraded(bc, BLUR)
    bc.play_card(0)
    assert bc.player.block == 8
    assert bc.player.special.get("blur_next_turn") == 1


def test_bouncing_flask_single_enemy_9_poison():
    bc = BattleContext(seed=659)
    m = bc.monsters.monsters[0]
    setup_hand(bc, BOUNCING_FLASK)
    bc.play_card(0)
    assert m.statuses.get(MonsterStatus.POISON) == 9  # 3 跳 × 3 层


def test_bouncing_flask_two_enemies_total_9():
    bc = BattleContext(seed=660)
    m2 = add_cultist(bc)
    m1 = bc.monsters.monsters[0]
    setup_hand(bc, BOUNCING_FLASK)
    bc.play_card(0)
    total = m1.statuses.get(MonsterStatus.POISON) + m2.statuses.get(MonsterStatus.POISON)
    assert total == 9


def test_bouncing_flask_upgraded_4_bounces():
    bc = BattleContext(seed=661)
    m = bc.monsters.monsters[0]
    setup_hand_upgraded(bc, BOUNCING_FLASK)
    bc.play_card(0)
    assert m.statuses.get(MonsterStatus.POISON) == 12


def test_calculated_gamble_discards_and_draws_same():
    bc = BattleContext(seed=662)
    fill_draw(bc, 3)
    setup_hand(bc, CALCULATED_GAMBLE, DEFLECT, DEFLECT)
    bc.play_card(0)
    assert len(bc.cards.hand) == 2  # 弃 2 抽 2
    assert bc.player.cards_discarded_this_turn == 2
    assert pile_names(bc, bc.cards.exhaust_pile) == ["Calculated Gamble"]  # 基础版消耗


def test_calculated_gamble_upgraded_does_not_exhaust():
    bc = BattleContext(seed=663)
    fill_draw(bc, 3)
    setup_hand(bc, CALCULATED_GAMBLE, DEFLECT, DEFLECT)
    inst = bc.cards.hand[0]
    inst.upgrade()
    bc.play_card(0)
    assert len(bc.cards.hand) == 2
    assert any(c is inst for c in bc.cards.discard_pile)
    assert bc.cards.exhaust_pile == []


def test_caltrops_thorns_reflect():
    bc = BattleContext(seed=664)
    m = bc.monsters.monsters[0]
    hp0 = m.hp
    setup_hand(bc, CALTROPS)
    bc.play_card(0)
    assert bc.player.statuses.get(PlayerStatus.THORNS) == 3
    bc.player.attacked(bc, 0, 5)
    run_queue(bc)
    assert m.hp == hp0 - 3  # 受击反弹（引擎 Player.attacked 已接）


def test_caltrops_upgraded_thorns_5():
    bc = BattleContext(seed=665)
    m = bc.monsters.monsters[0]
    hp0 = m.hp
    setup_hand_upgraded(bc, CALTROPS)
    bc.play_card(0)
    assert bc.player.statuses.get(PlayerStatus.THORNS) == 5
    bc.player.attacked(bc, 0, 5)
    run_queue(bc)
    assert m.hp == hp0 - 5


def test_catalyst_doubles_poison():
    bc = BattleContext(seed=666)
    m = bc.monsters.monsters[0]
    m.statuses.add(MonsterStatus.POISON, 5)
    setup_hand(bc, CATALYST)
    bc.play_card(0)
    assert m.statuses.get(MonsterStatus.POISON) == 10
    assert pile_names(bc, bc.cards.exhaust_pile) == ["Catalyst"]


def test_catalyst_no_poison_no_effect():
    bc = BattleContext(seed=667)
    m = bc.monsters.monsters[0]
    setup_hand(bc, CATALYST)
    bc.play_card(0)
    assert m.statuses.get(MonsterStatus.POISON) == 0


def test_catalyst_upgraded_triples():
    bc = BattleContext(seed=668)
    m = bc.monsters.monsters[0]
    m.statuses.add(MonsterStatus.POISON, 5)
    setup_hand_upgraded(bc, CATALYST)
    bc.play_card(0)
    assert m.statuses.get(MonsterStatus.POISON) == 15


def test_choke_damage_and_choked_status():
    bc = BattleContext(seed=669)
    m = bc.monsters.monsters[0]
    hp0 = m.hp
    setup_hand(bc, CHOKE)
    bc.play_card(0)
    assert m.hp == hp0 - 12
    # "每打出一张牌掉 3 HP" 的触发段在引擎 use_card（接线见迁移报告），
    # 此处断言状态落地
    assert m.statuses.get(MonsterStatus.CHOKED) == 3


def test_choke_upgraded_5_choked():
    bc = BattleContext(seed=670)
    m = bc.monsters.monsters[0]
    setup_hand_upgraded(bc, CHOKE)
    bc.play_card(0)
    assert m.hp == m.max_hp - 12  # 升级不加伤
    assert m.statuses.get(MonsterStatus.CHOKED) == 5


def test_concentrate_discard_3_gain_2_energy():
    bc = BattleContext(seed=671)
    setup_hand(bc, CONCENTRATE, DEFLECT, DEFLECT, DEFLECT)
    bc.play_card(0)
    assert bc.input_state == InputState.CARD_SELECT
    bc.choose_cards([0, 1, 2])
    assert bc.cards.hand == []
    assert bc.player.cards_discarded_this_turn == 3
    assert bc.player.energy == 5  # 3 + 2（0 费）


def test_concentrate_upgraded_discards_2():
    bc = BattleContext(seed=672)
    setup_hand_upgraded(bc, CONCENTRATE, DEFLECT, DEFLECT)
    bc.play_card(0)
    assert bc.input_state == InputState.CARD_SELECT
    bc.choose_cards([0, 1])
    assert bc.cards.hand == []
    assert bc.player.energy == 5


def test_crippling_cloud_all_enemies():
    bc = BattleContext(seed=673)
    m2 = add_cultist(bc)
    m1 = bc.monsters.monsters[0]
    setup_hand(bc, CRIPPLING_CLOUD)
    bc.play_card(0)
    assert m1.statuses.get(MonsterStatus.POISON) == 4
    assert m1.statuses.get(MonsterStatus.WEAK) == 2
    assert m2.statuses.get(MonsterStatus.POISON) == 4
    assert m2.statuses.get(MonsterStatus.WEAK) == 2
    assert pile_names(bc, bc.cards.exhaust_pile) == ["Crippling Cloud"]


def test_crippling_cloud_upgraded_7_poison():
    bc = BattleContext(seed=674)
    m = bc.monsters.monsters[0]
    setup_hand_upgraded(bc, CRIPPLING_CLOUD)
    bc.play_card(0)
    assert m.statuses.get(MonsterStatus.POISON) == 7
    assert m.statuses.get(MonsterStatus.WEAK) == 2


def test_dash_block_and_damage():
    bc = BattleContext(seed=675)
    m = bc.monsters.monsters[0]
    hp0 = m.hp
    setup_hand(bc, DASH)
    bc.play_card(0)
    assert bc.player.block == 10
    assert m.hp == hp0 - 10


def test_dash_upgraded_13_and_13():
    bc = BattleContext(seed=676)
    m = bc.monsters.monsters[0]
    hp0 = m.hp
    setup_hand_upgraded(bc, DASH)
    bc.play_card(0)
    assert bc.player.block == 13
    assert m.hp == hp0 - 13


def test_distraction_random_skill_zero_cost():
    bc = BattleContext(seed=677)
    setup_hand(bc, DISTRACTION)
    bc.play_card(0)
    assert len(bc.cards.hand) == 1
    c = bc.cards.hand[0]
    assert c.card.ctype == "Skill"  # 随机技能（池=Silent 技能+无色技能）
    assert c.cost == 0  # 本回合 0 费
    assert pile_names(bc, bc.cards.exhaust_pile) == ["Distraction"]


def test_distraction_upgraded_cost_0():
    bc = BattleContext(seed=678)
    inst = bc.cards.instantiate(DISTRACTION)
    inst.upgrade()
    assert inst.cost == 0  # 升级 1→0


def test_endless_agony_damage_and_exhaust():
    bc = BattleContext(seed=679)
    m = bc.monsters.monsters[0]
    hp0 = m.hp
    setup_hand(bc, ENDLESS_AGONY)
    bc.play_card(0)
    assert m.hp == hp0 - 4
    assert pile_names(bc, bc.cards.exhaust_pile) == ["Endless Agony"]
    # "抽到时复制入手"需引擎 on_card_drawn 钩子（接线见迁移报告）


def test_endless_agony_upgraded_deals_6():
    bc = BattleContext(seed=680)
    m = bc.monsters.monsters[0]
    hp0 = m.hp
    setup_hand_upgraded(bc, ENDLESS_AGONY)
    bc.play_card(0)
    assert m.hp == hp0 - 6


def test_escape_plan_block_on_skill_draw():
    bc = BattleContext(seed=681)
    fill_draw(bc, 1, DEFLECT)  # 抽到技能牌
    setup_hand(bc, ESCAPE_PLAN)
    bc.play_card(0)
    assert bc.player.block == 3
    assert len(bc.cards.hand) == 1


def test_escape_plan_no_block_on_attack_draw():
    bc = BattleContext(seed=682)
    fill_draw(bc, 1, SLICE)  # 抽到攻击牌
    setup_hand(bc, ESCAPE_PLAN)
    bc.play_card(0)
    assert bc.player.block == 0
    assert len(bc.cards.hand) == 1


def test_escape_plan_upgraded_5_block():
    bc = BattleContext(seed=683)
    fill_draw(bc, 1, DEFLECT)
    setup_hand_upgraded(bc, ESCAPE_PLAN)
    bc.play_card(0)
    assert bc.player.block == 5


def test_eviscerate_three_hits():
    bc = BattleContext(seed=684)
    m = bc.monsters.monsters[0]
    hp0 = m.hp
    setup_hand(bc, EVISCERATE)
    bc.play_card(0)
    assert m.hp == hp0 - 21  # 7 × 3


def test_eviscerate_energy_refund_per_discard():
    """动态费用（3 - 本回合弃牌数）的近似实现：名义 3 费支付后按弃牌数退还。"""
    bc = BattleContext(seed=685)
    setup_hand(bc, EVISCERATE, DEFLECT)
    bc.manual_discard(bc.cards.hand[1])
    bc.play_card(0)
    assert bc.player.energy == 1  # 3 - 3 + 1（弃 1 退 1）
    bc2 = BattleContext(seed=686)
    setup_hand(bc2, EVISCERATE)
    bc2.play_card(0)
    assert bc2.player.energy == 0  # 无弃牌全额支付


def test_eviscerate_upgraded_9_damage():
    bc = BattleContext(seed=687)
    m = bc.monsters.monsters[0]
    hp0 = m.hp
    setup_hand_upgraded(bc, EVISCERATE)
    bc.play_card(0)
    assert m.hp == hp0 - 27  # 9 × 3


def test_expertise_draws_up_to_6():
    bc = BattleContext(seed=688)
    fill_draw(bc, 8)
    setup_hand(bc, EXPERTISE, DEFLECT)
    bc.play_card(0)
    assert len(bc.cards.hand) == 6


def test_expertise_upgraded_up_to_7():
    bc = BattleContext(seed=689)
    fill_draw(bc, 8)
    setup_hand_upgraded(bc, EXPERTISE, DEFLECT)
    bc.play_card(0)
    assert len(bc.cards.hand) == 7


def test_expertise_no_draw_when_full():
    bc = BattleContext(seed=690)
    setup_hand(bc, EXPERTISE, DEFLECT, DEFLECT, DEFLECT, DEFLECT, DEFLECT, DEFLECT)
    bc.play_card(0)
    assert len(bc.cards.hand) == 6  # 已有 6 张，不再抽


def test_finisher_counts_itself():
    bc = BattleContext(seed=691)
    m = bc.monsters.monsters[0]
    hp0 = m.hp
    setup_hand(bc, FINISHER)
    bc.play_card(0)
    assert m.hp == hp0 - 6  # 本回合攻击数含自身 = 1


def test_finisher_scales_with_attacks():
    bc = BattleContext(seed=692)
    m = bc.monsters.monsters[0]
    hp0 = m.hp
    setup_hand(bc, SLICE, FINISHER)
    bc.play_card(0)
    assert m.hp == hp0 - 6
    hp0 = m.hp
    bc.play_card(0)
    assert m.hp == hp0 - 12  # 2 次攻击 × 6


def test_finisher_upgraded_8_per_attack():
    bc = BattleContext(seed=693)
    m = bc.monsters.monsters[0]
    hp0 = m.hp
    setup_hand_upgraded(bc, FINISHER)
    bc.play_card(0)
    assert m.hp == hp0 - 8


def test_flechettes_per_skill_in_hand():
    bc = BattleContext(seed=694)
    m = bc.monsters.monsters[0]
    hp0 = m.hp
    setup_hand(bc, FLECHETTES, DEFLECT, DEFLECT)
    bc.play_card(0)
    assert m.hp == hp0 - 8  # 2 张技能 × 4


def test_flechettes_upgraded_6_per_skill():
    bc = BattleContext(seed=695)
    m = bc.monsters.monsters[0]
    hp0 = m.hp
    setup_hand_upgraded(bc, FLECHETTES, DEFLECT)
    bc.play_card(0)
    assert m.hp == hp0 - 6


def test_footwork_2_dexterity():
    bc = BattleContext(seed=696)
    setup_hand(bc, FOOTWORK)
    bc.play_card(0)
    assert bc.player.statuses.get(PlayerStatus.DEXTERITY) == 2


def test_footwork_upgraded_3_dexterity():
    bc = BattleContext(seed=697)
    setup_hand_upgraded(bc, FOOTWORK)
    bc.play_card(0)
    assert bc.player.statuses.get(PlayerStatus.DEXTERITY) == 3


def test_heel_hook_no_weak_no_bonus():
    bc = BattleContext(seed=698)
    m = bc.monsters.monsters[0]
    hp0 = m.hp
    fill_draw(bc, 1)
    setup_hand(bc, HEEL_HOOK)
    bc.play_card(0)
    assert m.hp == hp0 - 5
    assert bc.player.energy == 2  # 3 - 1，无奖励
    assert bc.cards.hand == []


def test_heel_hook_weak_gives_energy_and_draw():
    bc = BattleContext(seed=699)
    m = bc.monsters.monsters[0]
    m.statuses.add(MonsterStatus.WEAK, 1)
    fill_draw(bc, 1)
    setup_hand(bc, HEEL_HOOK)
    bc.play_card(0)
    assert bc.player.energy == 3  # 3 - 1 + 1
    assert len(bc.cards.hand) == 1


def test_heel_hook_upgraded_deals_8():
    bc = BattleContext(seed=700)
    m = bc.monsters.monsters[0]
    hp0 = m.hp
    fill_draw(bc, 1)
    setup_hand_upgraded(bc, HEEL_HOOK)
    bc.play_card(0)
    assert m.hp == hp0 - 8


def test_infinite_blades_status_landing():
    bc = BattleContext(seed=701)
    setup_hand(bc, INFINITE_BLADES)
    bc.play_card(0)
    # wiki/C++：回合开始无条件生成袖剑（引擎 f0d724f 接线带
    # "上回合出过攻击牌"条件，出入见迁移报告）——此处只断言状态落地
    assert bc.player.statuses.get(PlayerStatus.INFINITE_BLADES) == 1


def test_infinite_blades_innate_when_upgraded():
    assert INFINITE_BLADES.innate_when_upgraded
    bc = BattleContext(seed=702)
    setup_hand_upgraded(bc, INFINITE_BLADES)
    bc.play_card(0)
    assert bc.player.statuses.get(PlayerStatus.INFINITE_BLADES) == 1


def test_leg_sweep_weak_and_block():
    bc = BattleContext(seed=703)
    m = bc.monsters.monsters[0]
    setup_hand(bc, LEG_SWEEP)
    bc.play_card(0)
    assert m.statuses.get(MonsterStatus.WEAK) == 2
    assert bc.player.block == 11


def test_leg_sweep_upgraded_3_weak_14_block():
    bc = BattleContext(seed=704)
    m = bc.monsters.monsters[0]
    setup_hand_upgraded(bc, LEG_SWEEP)
    bc.play_card(0)
    assert m.statuses.get(MonsterStatus.WEAK) == 3
    assert bc.player.block == 14


def test_masterful_stab_damage():
    bc = BattleContext(seed=705)
    m = bc.monsters.monsters[0]
    hp0 = m.hp
    setup_hand(bc, MASTERFUL_STAB)
    bc.play_card(0)
    assert m.hp == hp0 - 12


def test_masterful_stab_cost_increases_per_hp_loss():
    """wiki：本场战斗你每次失去 HP，此牌费用 +1（引擎 cost_delta_on_damage）。"""
    bc = BattleContext(seed=706)
    inst = bc.cards.instantiate(MASTERFUL_STAB)
    bc.cards.draw_pile.append(inst)
    assert inst.cost == 0
    bc.player.lose_hp(bc, 2)
    assert inst.cost == 1
    bc.player.attacked(bc, 0, 2)
    bc.execute_actions()
    assert inst.cost == 2


def test_masterful_stab_upgraded_deals_16():
    bc = BattleContext(seed=707)
    m = bc.monsters.monsters[0]
    hp0 = m.hp
    setup_hand_upgraded(bc, MASTERFUL_STAB)
    bc.play_card(0)
    assert m.hp == hp0 - 16


def test_noxious_fumes_status_landing():
    bc = BattleContext(seed=708)
    setup_hand(bc, NOXIOUS_FUMES)
    bc.play_card(0)
    # wiki：回合开始对全体施 2 层毒（结算在引擎 after_monster_turns，
    # f0d724f 已接）——此处断言状态落地
    assert bc.player.statuses.get(PlayerStatus.NOXIOUS_FUMES) == 2


def test_noxious_fumes_upgraded_lands_3():
    bc = BattleContext(seed=709)
    setup_hand_upgraded(bc, NOXIOUS_FUMES)
    bc.play_card(0)
    assert bc.player.statuses.get(PlayerStatus.NOXIOUS_FUMES) == 3


def test_predator_damage_and_draw_slot():
    bc = BattleContext(seed=710)
    m = bc.monsters.monsters[0]
    hp0 = m.hp
    setup_hand(bc, PREDATOR)
    bc.play_card(0)
    assert m.hp == hp0 - 15
    # 下回合多抽 2 走 next_turn_draw 槽（接线见迁移报告）
    assert bc.player.special.get("next_turn_draw") == 2


def test_predator_upgraded_deals_20():
    bc = BattleContext(seed=711)
    m = bc.monsters.monsters[0]
    hp0 = m.hp
    setup_hand_upgraded(bc, PREDATOR)
    bc.play_card(0)
    assert m.hp == hp0 - 20
    assert bc.player.special.get("next_turn_draw") == 2


def test_reflex_unplayable_and_discard_draws_2():
    bc = BattleContext(seed=712)
    fill_draw(bc, 2)
    setup_hand(bc, REFLEX)
    with pytest.raises(ValueError):
        bc.play_card(0)
    bc.manual_discard(bc.cards.hand[0])
    run_queue(bc)
    assert len(bc.cards.hand) == 2  # 被弃触发抽 2


def test_reflex_upgraded_draws_3():
    bc = BattleContext(seed=713)
    fill_draw(bc, 3)
    setup_hand_upgraded(bc, REFLEX)
    bc.manual_discard(bc.cards.hand[0])
    run_queue(bc)
    assert len(bc.cards.hand) == 3


def test_riddle_with_holes_5_hits():
    bc = BattleContext(seed=714)
    m = bc.monsters.monsters[0]
    hp0 = m.hp
    setup_hand(bc, RIDDLE_WITH_HOLES)
    bc.play_card(0)
    assert m.hp == hp0 - 15


def test_riddle_with_holes_upgraded_5x4():
    bc = BattleContext(seed=715)
    m = bc.monsters.monsters[0]
    hp0 = m.hp
    setup_hand_upgraded(bc, RIDDLE_WITH_HOLES)
    bc.play_card(0)
    assert m.hp == hp0 - 20


def test_setup_puts_card_on_top_zero_cost():
    from sts.content.cards import BLUDGEON

    bc = BattleContext(seed=716)
    bc.cards.draw_pile.clear()
    setup_hand(bc, SETUP, BLUDGEON)
    bc.play_card(0)
    # 单候选直执：Bludgeon 置抽牌堆顶，0 费直到被打出（cost_override 近似）
    top = bc.cards.draw_pile[-1]
    assert top.card is BLUDGEON
    assert top.cost == 0
    assert bc.cards.hand == []
    assert bc.cards.exhaust_pile == []  # 不消耗


def test_setup_upgraded_cost_0():
    bc = BattleContext(seed=717)
    inst = bc.cards.instantiate(SETUP)
    inst.upgrade()
    assert inst.cost == 0


def test_skewer_x_times():
    bc = BattleContext(seed=718)
    m = bc.monsters.monsters[0]
    hp0 = m.hp
    setup_hand(bc, SKEWER)
    bc.play_card(0)  # 3 能量 → X=3
    assert m.hp == hp0 - 21
    assert bc.player.energy == 0


def test_skewer_upgraded_10_per_energy():
    bc = BattleContext(seed=719)
    m = bc.monsters.monsters[0]
    hp0 = m.hp
    setup_hand_upgraded(bc, SKEWER)
    bc.play_card(0)
    assert m.hp == hp0 - 30


def test_tactician_unplayable_and_discard_gains_1_energy():
    bc = BattleContext(seed=720)
    setup_hand(bc, TACTICIAN)
    with pytest.raises(ValueError):
        bc.play_card(0)
    e0 = bc.player.energy
    bc.manual_discard(bc.cards.hand[0])
    run_queue(bc)
    assert bc.player.energy == e0 + 1  # wiki 口径：基础 +1


def test_tactician_upgraded_discard_gains_2_energy():
    bc = BattleContext(seed=721)
    setup_hand_upgraded(bc, TACTICIAN)
    e0 = bc.player.energy
    bc.manual_discard(bc.cards.hand[0])
    run_queue(bc)
    assert bc.player.energy == e0 + 2


def test_terror_99_vulnerable_and_exhaust():
    bc = BattleContext(seed=722)
    m = bc.monsters.monsters[0]
    setup_hand(bc, TERROR)
    bc.play_card(0)
    assert m.statuses.get(MonsterStatus.VULNERABLE) == 99
    assert pile_names(bc, bc.cards.exhaust_pile) == ["Terror"]


def test_terror_upgraded_costs_0():
    bc = BattleContext(seed=723)
    m = bc.monsters.monsters[0]
    setup_hand_upgraded(bc, TERROR)
    bc.play_card(0)
    assert m.statuses.get(MonsterStatus.VULNERABLE) == 99
    assert bc.player.energy == 3  # 0 费
    assert pile_names(bc, bc.cards.exhaust_pile) == ["Terror"]


def test_well_laid_plans_retains_chosen_card():
    from sts.content.cards import DEFEND

    bc = BattleContext(seed=724)
    fill_draw(bc, 8)  # 抽牌堆富余：回合末弃牌不会被洗回，断言不受干扰
    setup_hand(bc, WELL_LAID_PLANS, DEFEND, SLICE)
    defend_id = bc.cards.hand[1].unique_id
    bc.play_card(0)
    assert bc.player.special.get("wlp") == 1
    bc.end_turn()
    # 引擎 call_end_turn_actions 的 wlp 分支（f0d724f 已接）：回合末选 1 张保留
    if bc.input_state == InputState.CARD_SELECT:
        defend = next(c for c in bc.card_select_info.candidates if c.card is DEFEND)
        bc.choose_cards([bc.card_select_info.candidates.index(defend)])
    hand_ids = [c.unique_id for c in bc.cards.hand]
    assert defend_id in hand_ids  # 保留的牌下回合回手
    # SLICE 未被选中 → 走弃牌堆（8 张富余抽牌堆保证不洗回）
    assert any(c.card is SLICE for c in bc.cards.discard_pile)


def test_well_laid_plans_upgraded_slot_2():
    bc = BattleContext(seed=725)
    setup_hand_upgraded(bc, WELL_LAID_PLANS)
    bc.play_card(0)
    assert bc.player.special.get("wlp") == 2
    # 升级版选 2 张的 pick_count 引擎差异见迁移报告


# ---- 稀有 18 张（Alchemize 跳过）----


def test_thousand_cuts_status_landing():
    bc = BattleContext(seed=726)
    setup_hand(bc, A_THOUSAND_CUTS)
    bc.play_card(0)
    # wiki：每打出一张牌全体 1×层 伤（结算在引擎 use_card，f0d724f 已接，
    # 主会话补测全行为）——此处断言状态落地
    assert bc.player.statuses.get(PlayerStatus.A_THOUSAND_CUTS) == 1


def test_thousand_cuts_upgraded_lands_2():
    bc = BattleContext(seed=727)
    setup_hand_upgraded(bc, A_THOUSAND_CUTS)
    bc.play_card(0)
    assert bc.player.statuses.get(PlayerStatus.A_THOUSAND_CUTS) == 2


def test_adrenaline_energy_draw_and_exhaust():
    bc = BattleContext(seed=728)
    fill_draw(bc, 2)
    setup_hand(bc, ADRENALINE)
    bc.play_card(0)
    assert bc.player.energy == 4  # 3 + 1
    assert len(bc.cards.hand) == 2
    assert pile_names(bc, bc.cards.exhaust_pile) == ["Adrenaline"]


def test_adrenaline_upgraded_2_energy():
    bc = BattleContext(seed=729)
    fill_draw(bc, 2)
    setup_hand_upgraded(bc, ADRENALINE)
    bc.play_card(0)
    assert bc.player.energy == 5
    assert len(bc.cards.hand) == 2


def test_after_image_status_landing():
    bc = BattleContext(seed=730)
    setup_hand(bc, AFTER_IMAGE)
    bc.play_card(0)
    # wiki/C++ 语义：每打出一张牌得 1 格挡（引擎 f0d724f 按"出技能生成袖剑"
    # 接线，出入见迁移报告）——按任务口径只断言状态落地
    assert bc.player.statuses.get(PlayerStatus.AFTER_IMAGE) == 1
    assert AFTER_IMAGE.innate_when_upgraded


def test_bullet_time_no_draw_and_costs_zero():
    from sts.content.cards import BLUDGEON

    bc = BattleContext(seed=731)
    setup_hand(bc, BULLET_TIME, BLUDGEON)
    bc.player.energy = 4
    bc.play_card(0)
    assert bc.player.statuses.has(PlayerStatus.NO_DRAW)
    assert bc.cards.hand[0].cost == 0  # 手牌本轮 0 费


def test_bullet_time_cost_reset_next_turn():
    from sts.content.cards import BLUDGEON

    bc = BattleContext(seed=732)
    fill_draw(bc, 3)
    setup_hand(bc, BULLET_TIME, BLUDGEON)
    bludgeon = bc.cards.hand[1]
    bc.player.energy = 4
    bc.play_card(0)
    assert bludgeon.cost == 0
    bc.end_turn()
    # cost_for_turn 回合末复原（reset_attributes_at_end_of_turn）
    assert bludgeon.cost == 3
    assert not bc.player.statuses.has(PlayerStatus.NO_DRAW)


def test_bullet_time_upgraded_costs_2():
    bc = BattleContext(seed=733)
    inst = bc.cards.instantiate(BULLET_TIME)
    inst.upgrade()
    assert inst.cost == 2


def test_burst_status_landing():
    bc = BattleContext(seed=734)
    setup_hand(bc, BURST)
    bc.play_card(0)
    # wiki：下一张技能牌结算两次（结算在引擎 on_use_skill_card，f0d724f 已接，
    # 主会话补测全行为）——此处断言状态落地
    assert bc.player.statuses.get(PlayerStatus.BURST) == 1


def test_burst_upgraded_lands_2():
    bc = BattleContext(seed=735)
    setup_hand_upgraded(bc, BURST)
    bc.play_card(0)
    assert bc.player.statuses.get(PlayerStatus.BURST) == 2


def test_corpse_explosion_poison_and_status():
    bc = BattleContext(seed=736)
    m = bc.monsters.monsters[0]
    setup_hand(bc, CORPSE_EXPLOSION)
    bc.play_card(0)
    assert m.statuses.get(MonsterStatus.POISON) == 6
    assert m.statuses.get(MonsterStatus.CORPSE_EXPLOSION) == 1
    assert bc.cards.exhaust_pile == []  # 不消耗（wiki desc 无 Exhaust）


def test_corpse_explosion_death_damages_all():
    """尸爆引擎结算（批次 A 已接）：带层怪死亡 → 全体受 maxHp×层。"""
    bc = BattleContext(seed=737)
    m1 = bc.monsters.monsters[0]
    m1.max_hp = 60
    m1.hp = 60
    m2 = add_cultist(bc, hp=99)
    setup_hand(bc, CORPSE_EXPLOSION)
    bc.cards.draw_pile.clear()  # 后续清抽牌堆前先保证手牌来源
    bc.play_card(0, target=0)
    assert m1.statuses.get(MonsterStatus.CORPSE_EXPLOSION) == 1
    m1.hp = 6  # 毒 6 恰好致死
    bc.cards.hand.append(bc.cards.instantiate(DEFLECT))  # 防无牌判负
    bc.end_turn()
    assert not m1.alive
    assert m2.hp == 99 - 60


def test_corpse_explosion_upgraded_9_poison():
    bc = BattleContext(seed=738)
    m = bc.monsters.monsters[0]
    setup_hand_upgraded(bc, CORPSE_EXPLOSION)
    bc.play_card(0)
    assert m.statuses.get(MonsterStatus.POISON) == 9


def test_die_die_die_all_damage_and_exhaust():
    bc = BattleContext(seed=739)
    m2 = add_cultist(bc)
    m1 = bc.monsters.monsters[0]
    hp1, hp2 = m1.hp, m2.hp
    setup_hand(bc, DIE_DIE_DIE)
    bc.play_card(0)
    assert m1.hp == hp1 - 13
    assert m2.hp == hp2 - 13
    assert pile_names(bc, bc.cards.exhaust_pile) == ["Die Die Die"]


def test_die_die_die_upgraded_17():
    bc = BattleContext(seed=740)
    m = bc.monsters.monsters[0]
    hp0 = m.hp
    setup_hand_upgraded(bc, DIE_DIE_DIE)
    bc.play_card(0)
    assert m.hp == hp0 - 17


def test_doppelganger_slots():
    bc = BattleContext(seed=741)
    setup_hand(bc, DOPPELGANGER)
    bc.play_card(0)  # X=3
    assert bc.player.energy == 0
    assert bc.player.special.get("next_turn_draw") == 3
    assert bc.player.special.get("next_turn_energy") == 3
    assert pile_names(bc, bc.cards.exhaust_pile) == ["Doppelganger"]


def test_doppelganger_upgraded_x_plus_1():
    bc = BattleContext(seed=742)
    setup_hand_upgraded(bc, DOPPELGANGER)
    bc.play_card(0)
    assert bc.player.special.get("next_turn_draw") == 4
    assert bc.player.special.get("next_turn_energy") == 4


def test_envenom_status_and_integration():
    bc = BattleContext(seed=743)
    setup_hand(bc, ENVENOM)
    bc.play_card(0)
    assert bc.player.statuses.get(PlayerStatus.ENVENOM) == 1
    # 引擎已接（Monster._apply_damage）：未格挡攻击自动 +1 毒
    setup_hand(bc, SHIV)
    m = bc.monsters.monsters[0]
    hp0 = m.hp
    bc.play_card(0)
    assert m.hp == hp0 - 4
    assert m.statuses.get(MonsterStatus.POISON) == 1


def test_envenom_upgraded_cost_1():
    bc = BattleContext(seed=744)
    inst = bc.cards.instantiate(ENVENOM)
    inst.upgrade()
    assert inst.cost == 1


def test_glass_knife_two_hits_and_decay():
    bc = BattleContext(seed=745)
    m = bc.monsters.monsters[0]
    m.hp = 100
    setup_hand(bc, GLASS_KNIFE)
    gk = bc.cards.hand[0]
    hp0 = m.hp
    bc.play_card(0)
    assert m.hp == hp0 - 16  # 8 × 2
    assert gk.misc_data == 1
    # 同一实例从弃牌堆回手再打：8 - 2×1 = 6 × 2
    bc.cards.hand.append(gk)
    hp0 = m.hp
    bc.play_card(0)
    assert m.hp == hp0 - 12
    assert gk.misc_data == 2


def test_glass_knife_upgraded_12_twice():
    bc = BattleContext(seed=746)
    m = bc.monsters.monsters[0]
    hp0 = m.hp
    setup_hand_upgraded(bc, GLASS_KNIFE)
    bc.play_card(0)
    assert m.hp == hp0 - 24
    assert bc.cards.hand == []


def test_grand_finale_blocked_with_cards_in_draw():
    bc = BattleContext(seed=747)
    setup_hand(bc, GRAND_FINALE)
    with pytest.raises(ValueError):
        bc.play_card(0)


def test_grand_finale_50_damage_when_draw_empty():
    bc = BattleContext(seed=748)
    m2 = add_cultist(bc)
    m1 = bc.monsters.monsters[0]
    m1.hp = 200  # 防过击杀（默认 48-54 血不够 50 伤断言）
    m2.hp = 200
    hp1, hp2 = m1.hp, m2.hp
    setup_hand(bc, GRAND_FINALE, DEFLECT)  # 保留 1 张手牌防无牌判负
    bc.cards.draw_pile.clear()
    bc.play_card(0)
    assert m1.hp == hp1 - 50
    assert m2.hp == hp2 - 50


def test_grand_finale_upgraded_60():
    bc = BattleContext(seed=749)
    m = bc.monsters.monsters[0]
    m.hp = 200
    hp0 = m.hp
    setup_hand_upgraded(bc, GRAND_FINALE, DEFLECT)
    bc.cards.draw_pile.clear()
    bc.play_card(0)
    assert m.hp == hp0 - 60


def test_malaise_x_strength_and_weak():
    bc = BattleContext(seed=750)
    m = bc.monsters.monsters[0]
    bc.player.energy = 2
    setup_hand(bc, MALAISE)
    bc.play_card(0)  # X=2
    assert m.statuses.get(MonsterStatus.STRENGTH) == -2
    assert m.statuses.get(MonsterStatus.WEAK) == 2
    assert bc.player.energy == 0
    assert pile_names(bc, bc.cards.exhaust_pile) == ["Malaise"]


def test_malaise_upgraded_x_plus_1():
    bc = BattleContext(seed=751)
    m = bc.monsters.monsters[0]
    bc.player.energy = 2
    setup_hand_upgraded(bc, MALAISE)
    bc.play_card(0)
    assert m.statuses.get(MonsterStatus.STRENGTH) == -3
    assert m.statuses.get(MonsterStatus.WEAK) == 3


def test_malaise_zero_energy_no_debuff():
    bc = BattleContext(seed=752)
    m = bc.monsters.monsters[0]
    bc.player.energy = 0
    setup_hand(bc, MALAISE)
    bc.play_card(0)
    assert m.statuses.get(MonsterStatus.STRENGTH) == 0
    assert not m.statuses.has(MonsterStatus.WEAK)


def test_nightmare_copies_next_turn():
    bc = BattleContext(seed=753)
    fill_draw(bc, 8)  # 抽牌堆富余：回合末弃牌不会被洗回，断言不受干扰
    setup_hand(bc, NIGHTMARE, STRIKE_S)
    original_id = bc.cards.hand[1].unique_id
    bc.play_card(0)
    assert bc.player.special["next_turn_cards"] == [(STRIKE_S, False, 3)]
    bc.end_turn()
    # 引擎 after_monster_turns 的 next_turn_cards 槽（f0d724f 已接）：
    # 3 份保留副本入手（原实例经弃牌阶段离手，不计入）
    copies = [c for c in bc.cards.hand
              if c.card is STRIKE_S and c.unique_id != original_id]
    assert len(copies) == 3
    assert all(c.retain for c in copies)
    assert pile_names(bc, bc.cards.exhaust_pile).count("Nightmare") == 1


def test_nightmare_upgraded_cost_2_and_copies_upgraded():
    bc = BattleContext(seed=754)
    inst = bc.cards.instantiate(NIGHTMARE)
    inst.upgrade()
    assert inst.cost == 2
    setup_hand(bc, STRIKE_S)
    bc.cards.hand[0].upgrade()
    bc.cards.hand.append(inst)
    bc.play_card(1)  # 单候选直执：STRIKE_S+
    assert bc.player.special["next_turn_cards"] == [(STRIKE_S, True, 3)]


def test_phantasmal_killer_status_landing():
    bc = BattleContext(seed=755)
    setup_hand(bc, PHANTASMAL_KILLER)
    bc.play_card(0)
    # 引擎 f0d724f：回合开始落 DOUBLE_DAMAGE、首攻击翻倍；wiki/C++ 为下回合
    # 全部攻击翻倍（出入见迁移报告）——按任务口径只断言状态落地
    assert bc.player.statuses.get(PlayerStatus.PHANTASMAL_KILLER) == 1


def test_phantasmal_killer_upgraded_cost_0():
    bc = BattleContext(seed=756)
    inst = bc.cards.instantiate(PHANTASMAL_KILLER)
    inst.upgrade()
    assert inst.cost == 0


def test_storm_of_steel_discards_and_adds_shivs():
    bc = BattleContext(seed=757)
    setup_hand(bc, STORM_OF_STEEL, DEFLECT, DEFLECT, DEFLECT)
    bc.play_card(0)
    assert bc.player.cards_discarded_this_turn == 3
    assert len(bc.cards.hand) == 3
    assert all(c.card is SHIV for c in bc.cards.hand)


def test_storm_of_steel_upgraded_shivs_are_upgraded():
    bc = BattleContext(seed=758)
    m = bc.monsters.monsters[0]
    setup_hand_upgraded(bc, STORM_OF_STEEL, DEFLECT)
    bc.play_card(0)
    assert len(bc.cards.hand) == 1
    shiv = bc.cards.hand[0]
    assert shiv.card is SHIV and shiv.upgraded
    hp0 = m.hp
    bc.play_card(0)
    assert m.hp == hp0 - 6  # Shiv+ 6 伤


def test_tools_of_the_trade_slot():
    bc = BattleContext(seed=759)
    setup_hand(bc, TOOLS_OF_THE_TRADE)
    bc.play_card(0)
    # 回合开始抽 1 弃 1 走 special["tott_draw"] 槽（接线见迁移报告）
    assert bc.player.special.get("tott_draw") == 1


def test_tools_of_the_trade_upgraded_cost_0():
    bc = BattleContext(seed=760)
    inst = bc.cards.instantiate(TOOLS_OF_THE_TRADE)
    inst.upgrade()
    assert inst.cost == 0


def test_unload_damage_and_discards_non_attacks():
    bc = BattleContext(seed=761)
    m = bc.monsters.monsters[0]
    hp0 = m.hp
    setup_hand(bc, UNLOAD, DEFLECT, DEFLECT)
    bc.play_card(0)
    assert m.hp == hp0 - 14
    assert bc.cards.hand == []
    assert bc.player.cards_discarded_this_turn == 2


def test_unload_upgraded_18():
    bc = BattleContext(seed=762)
    m = bc.monsters.monsters[0]
    hp0 = m.hp
    setup_hand_upgraded(bc, UNLOAD)
    bc.play_card(0)
    assert m.hp == hp0 - 18


def test_wraith_form_intangible_and_dex_slot():
    bc = BattleContext(seed=763)
    setup_hand(bc, WRAITH_FORM)
    bc.play_card(0)
    assert bc.player.statuses.get(PlayerStatus.INTANGIBLE) == 2
    # wiki：回合结束失去 1 点敏捷（每回合，可叠）——走
    # special["wraith_form_dex"] 槽（接线见迁移报告）
    assert bc.player.special.get("wraith_form_dex") == 1


def test_wraith_form_upgraded_3_intangible():
    bc = BattleContext(seed=764)
    setup_hand_upgraded(bc, WRAITH_FORM)
    bc.play_card(0)
    assert bc.player.statuses.get(PlayerStatus.INTANGIBLE) == 3
    assert bc.player.special.get("wraith_form_dex") == 1


def test_wraith_form_intangible_reduces_incoming_damage():
    """无实体的引擎结算（回合末衰减，期间攻击伤害降为 1）。"""
    bc = BattleContext(seed=765)
    setup_hand(bc, WRAITH_FORM)
    bc.play_card(0)
    hp0 = bc.player.hp
    bc.player.attacked(bc, 0, 30)
    bc.execute_actions()
    assert bc.player.hp == hp0 - 1


# ---- 引擎接线回归（批次 C 报告的 special 槽位与状态修正，主会话接线后补测）----


def test_next_turn_energy_slot_flying_knee_semantics():
    from sts.combat import BattleContext
    from sts.combat.actions import Actions

    bc = BattleContext(seed=940, deck=[STRIKE] * 15)
    bc.player.special["next_turn_energy"] = 2
    bc.end_turn()
    assert bc.player.energy == 3 + 2
    assert "next_turn_energy" not in bc.player.special  # 一次性


def test_next_turn_draw_slot():
    from sts.combat import BattleContext

    bc = BattleContext(seed=941, deck=[STRIKE] * 15)
    bc.player.special["next_turn_draw"] = 2
    bc.end_turn()
    assert len(bc.cards.hand) == 7  # 5 + 2
    assert "next_turn_draw" not in bc.player.special


def test_blur_next_turn_keeps_block():
    from sts.combat import BattleContext

    bc = BattleContext(seed=942, deck=[STRIKE] * 15)
    bc.player.block = 9
    bc.player.special["blur_next_turn"] = True
    bc.end_turn()
    assert bc.player.block == 9  # Blur：豁免一轮衰减
    bc.end_turn()
    assert bc.player.block == 0  # 只豁免一轮


def test_wraith_form_dexterity_drain():
    from sts.combat import BattleContext
    from sts.combat.types import PlayerStatus

    bc = BattleContext(seed=943, deck=[STRIKE] * 15)
    bc.player.special["wraith_form_dex"] = 1
    bc.end_turn()
    assert bc.player.statuses.get(PlayerStatus.DEXTERITY) == -1
    bc.end_turn()
    assert bc.player.statuses.get(PlayerStatus.DEXTERITY) == -2  # 每回合持续


def test_choked_damages_on_card_play_and_clears():
    from sts.combat import BattleContext
    from sts.combat.actions import Actions
    from sts.combat.queue import Action
    from sts.combat.types import MonsterStatus

    bc = BattleContext(seed=944, deck=[STRIKE] * 15)
    m = bc.monsters.monsters[0]
    m.statuses.add(MonsterStatus.CHOKED, 3)
    hp0 = m.hp

    def run_queue(b):
        if b.input_state.name == "PLAYER_NORMAL":
            b.set_state(type(b.input_state)(0))
        from sts.combat.types import InputState
        if b.input_state != InputState.EXECUTING_ACTIONS:
            b.set_state(InputState.EXECUTING_ACTIONS)
        b.execute_actions()

    bc.cards.hand.clear()
    bc.cards.hand.append(bc.cards.instantiate(STRIKE))
    bc.play_card(0)
    assert m.hp == hp0 - 6 - 3  # 攻击 6 + Choke 3
    bc.end_turn()  # 怪回合开始清除
    assert not m.statuses.has(MonsterStatus.CHOKED)


def test_after_image_grants_block_per_card():
    from sts.combat import BattleContext
    from sts.combat.types import PlayerStatus

    bc = BattleContext(seed=945, deck=[STRIKE] * 15)
    bc.player.statuses.add(PlayerStatus.AFTER_IMAGE, 1)
    bc.cards.hand.clear()
    bc.cards.hand.append(bc.cards.instantiate(STRIKE))
    bc.cards.hand.append(bc.cards.instantiate(STRIKE))
    bc.play_card(0)
    bc.play_card(0)
    assert bc.player.block == 2  # 每张牌 1 格挡（修正后语义）


def test_infinite_blades_unconditional():
    from sts.combat import BattleContext
    from sts.combat.types import PlayerStatus

    bc = BattleContext(seed=946, deck=[STRIKE] * 15)
    bc.player.statuses.add(PlayerStatus.INFINITE_BLADES, 1)
    bc.end_turn()  # 上回合 0 攻击：仍生成（无条件，修正后）
    assert any(c.card.name == "Shiv" for c in bc.cards.hand)


def test_phantasmal_killer_full_turn_double():
    from sts.combat import BattleContext
    from sts.combat.types import PlayerStatus

    bc = BattleContext(seed=947, deck=[STRIKE] * 15)
    bc.player.statuses.add(PlayerStatus.PHANTASMAL_KILLER, 1)
    bc.end_turn()  # 落 DOUBLE_DAMAGE
    assert bc.player.statuses.has(PlayerStatus.DOUBLE_DAMAGE)
    m = bc.monsters.monsters[0]
    hp0 = m.hp
    bc.cards.hand.clear()
    bc.cards.hand.append(bc.cards.instantiate(STRIKE))
    bc.cards.hand.append(bc.cards.instantiate(STRIKE))
    bc.play_card(0)
    assert m.hp == hp0 - 12  # 第一张翻倍
    hp1 = m.hp
    bc.play_card(0)
    assert m.hp == hp1 - 12  # 第二张仍翻倍（全回合，修正后）
    bc.end_turn()
    assert not bc.player.statuses.has(PlayerStatus.DOUBLE_DAMAGE)  # 回合末衰减


def test_endless_agony_on_drawn_effect():
    from sts.combat import BattleContext
    from sts.combat.types import InputState

    bc = BattleContext(seed=948, deck=[STRIKE] * 15)
    bc.cards.hand.clear()
    inst = bc.cards.instantiate(ENDLESS_AGONY)
    bc.cards.draw_pile.append(inst)
    from sts.combat.actions import Actions
    from sts.combat.types import InputState as IS
    bc.add_to_bot(Actions.draw_cards(1))
    if bc.input_state == IS.PLAYER_NORMAL:
        bc.set_state(IS.EXECUTING_ACTIONS)
    bc.execute_actions()
    # 抽到 Endless Agony：复制 1 张入手（on_drawn_effect）
    assert sum(1 for c in bc.cards.hand if c.card is ENDLESS_AGONY) == 2


def test_eviscerate_dynamic_cost():
    from sts.combat import BattleContext

    bc = BattleContext(seed=949, deck=[STRIKE] * 15)
    bc.cards.hand.clear()
    e1 = bc.cards.instantiate(EVISCERATE)
    bc.cards.hand.append(e1)
    bc.player.energy = 1  # 已弃 2 张 → 实际费用 1
    bc.player.cards_discarded_this_turn = 2
    bc.play_card(0)  # 动态费用 3-2=1：可打出
    assert bc.player.energy == 0

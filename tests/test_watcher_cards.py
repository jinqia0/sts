"""Watcher 全卡移植断言（数值/结算以 slaythespire.wiki.gg 为权威源，
Cards.h 交叉校验费用/消耗/保留/固定位）。

逐卡至少 1 用例 + 升级分支；构造模式沿用 test_silent_cards.py
（setup_hand / fill_draw / add_cultist，出牌序列确定、不依赖初始洗牌）。

三类接线状态分层断言（详见 watcher_cards.py 模块注释）：
- 引擎已接（MANTRA/DEVOTION/RUSHDOWN/Scry/Retain/VIGOR/next_turn_draw 等）：
  全流程断言；
- 内容层仿真（Calm 退出 +2 能量 / Divinity 进入 +3 能量 / Flurry 回手 /
  真言计数）：对内容驱动路径全流程断言；
- 槽位落地 + 引擎接线需求（foresight/battle_hymn/study/deva_form/omega/
  collect_miracles/establishment/blasphemy_die/nirvana/wave_of_the_hand/
  swivel/weave_recall 等 special 槽 + BLOCK_RETURN/MARK 触发段）：只断言
  槽位/状态落地。

已知引擎常量偏差（wiki 口径 vs 引擎实现，迁移报告）：
- MENTAL_FORTRESS：wiki 每次切换 4/6 格挡，引擎 3×层 → 断言按引擎实际值 3；
- LIKE_WATER：wiki 回合末 5/7 格挡，引擎 3×层 → 只断言状态落地。
"""

import subprocess
import sys

import pytest

from sts.combat import BattleContext
from sts.combat.actions import Actions
from sts.combat.card_manager import MAX_HAND_SIZE
from sts.combat.types import InputState, MonsterStatus, Outcome, PlayerStatus, Stance
from sts.content.cards import CardDef, STRIKE, WOUND
from sts.content.monsters import Cultist

from sts.content.watcher_cards import (
    ALPHA,
    BATTLE_HYMN,
    BETA,
    BLASPHEMY,
    BOWLING_BASH,
    BRILLIANCE,
    CARVE_REALITY,
    COLLECT,
    CONCLUDE,
    CONJURE_BLADE,
    CONSECRATE,
    CRESCENDO,
    CRUSH_JOINTS,
    CUT_THROUGH_FATE,
    DECEIVE_REALITY,
    DEFEND_W,
    DEUS_EX_MACHINA,
    DEVA_FORM,
    DEVOTION,
    EMPTY_BODY,
    EMPTY_FIST,
    EMPTY_MIND,
    ERUPTION,
    ESTABLISHMENT,
    EVALUATE,
    EXPUNGER,
    FASTING,
    FEAR_NO_EVIL,
    FLURRY_OF_BLOWS,
    FLYING_SLEEVES,
    FOLLOW_UP,
    FOREIGN_INFLUENCE,
    FORESIGHT,
    HALT,
    INDIGNATION,
    INNER_PEACE,
    INSIGHT,
    JUDGMENT,
    JUST_LUCKY,
    LESSON_LEARNED,
    LIKE_WATER,
    MASTER_REALITY,
    MEDITATE,
    MENTAL_FORTRESS,
    MIRACLE,
    NIRVANA,
    OMEGA,
    OMNISCIENCE,
    PERSEVERANCE,
    PRAY,
    PRESSURE_POINTS,
    PROSTRATE,
    PROTECT,
    RAGNAROK,
    REACH_HEAVEN,
    RUSHDOWN,
    SAFETY,
    SANCTITY,
    SANDS_OF_TIME,
    SASH_WHIP,
    SCRAWL,
    SIGNATURE_MOVE,
    SIMMERING_FURY,
    SMITE,
    SPIRIT_SHIELD,
    STRIKE_W,
    STUDY,
    SWIVEL,
    TALK_TO_THE_HAND,
    TANTRUM,
    THIRD_EYE,
    THROUGH_VIOLENCE,
    TRANQUILITY,
    VAULT,
    VIGILANCE,
    WISH,
    WALLOP,
    WAVE_OF_THE_HAND,
    WEAVE,
    WHEEL_KICK,
    WINDMILL_STRIKE,
    WORSHIP,
    WREATH_OF_FLAME,
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


def fill_draw(bc: BattleContext, n: int, card: CardDef = STRIKE) -> None:
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


def test_watcher_reexport_via_cards_module():
    import sts.content.cards as cards_mod
    import sts.content.watcher_cards as w

    assert cards_mod.ERUPTION is w.ERUPTION
    assert cards_mod.WORSHIP is w.WORSHIP
    assert cards_mod.MIRACLE is w.MIRACLE
    # 与铁甲/静默的 Strike/Defend 不同对象，卡名刻意同名（CARD_INDEX 按名去重）
    assert cards_mod.STRIKE_W is w.STRIKE_W
    assert cards_mod.STRIKE_W.name == "Strike"
    assert cards_mod.STRIKE_W is not cards_mod.STRIKE


def test_watcher_first_import_order_keeps_reexport():
    """watcher_cards 被先行导入时，cards.py 的惰性 re-export 仍可用。"""
    code = (
        "import sts.content.watcher_cards as w; "
        "from sts.content import cards; "
        "assert cards.ERUPTION is w.ERUPTION; "
        "from sts.content.cards import REGRET; "
        "from sts.content.cards import SHIV; "
        "from sts.content.cards import TRANSMUTATION"
    )
    subprocess.run([sys.executable, "-c", code], check=True, timeout=60)


def test_watcher_card_count():
    """wiki 口径：池内 75（4 基础 + 19 普通 + 35 非普通 + 17 稀有）+ 8 生成卡
    = 83 个 CardDef。"""
    import sts.content.watcher_cards as w

    cards = [g for g in vars(w).values() if isinstance(g, CardDef)]
    assert len(cards) == 83


def test_watcher_flags_per_cards_h():
    """Cards.h 数据位交叉校验：保留 / 仅升级版保留 / 消耗 / 固有（升级版）/
    X 费 / 升级改费。"""

    def is_x(card):
        return card.x_cost

    for card in (CRESCENDO, FLYING_SLEEVES, PROTECT, TRANQUILITY, PERSEVERANCE,
                 SANDS_OF_TIME, WINDMILL_STRIKE, MIRACLE, INSIGHT, SAFETY,
                 SMITE, THROUGH_VIOLENCE):
        assert card.self_retain, card.name
    for card in (WORSHIP, BLASPHEMY):
        assert card.retain_when_upgraded, card.name
    exhaust_set = {
        CRESCENDO, TRANQUILITY, COLLECT, FOREIGN_INFLUENCE, TALK_TO_THE_HAND,
        ALPHA, BLASPHEMY, CONJURE_BLADE, DEUS_EX_MACHINA, LESSON_LEARNED,
        OMNISCIENCE, SCRAWL, VAULT, WISH, BETA, INSIGHT, MIRACLE, SAFETY,
        SMITE, THROUGH_VIOLENCE,
    }
    for card in exhaust_set:
        assert card.exhausts, card.name
    for card in (ERUPTION, OMNISCIENCE, VAULT, STUDY, TRANQUILITY, CRESCENDO,
                 RUSHDOWN, SCRAWL, MASTER_REALITY, BETA):
        assert card.upgraded_cost is not None, card.name
    assert ERUPTION.upgraded_cost == 1 and ERUPTION.cost == 2
    assert VIGILANCE.cost == 2 and VIGILANCE.upgraded_cost is None
    assert OMNISCIENCE.upgraded_cost == 3
    assert VAULT.upgraded_cost == 2
    assert STUDY.upgraded_cost == 1
    assert BETA.upgraded_cost == 1
    assert SANDS_OF_TIME.cost == 4
    assert DEVA_FORM.cost == 3 and DEVA_FORM.ethereal
    assert is_x(COLLECT) and is_x(CONJURE_BLADE)
    assert not is_x(ERUPTION)
    for card, flag in ((BATTLE_HYMN, True), (ALPHA, True), (ESTABLISHMENT, True)):
        assert card.innate_when_upgraded is flag and not card.innate


# ---- 基础 4 张 ----


def test_strike_w_deals_6():
    bc = BattleContext(seed=700)
    m = bc.monsters.monsters[0]
    hp0 = m.hp
    setup_hand(bc, STRIKE_W)
    bc.play_card(0)
    assert m.hp == hp0 - 6


def test_strike_w_upgraded_deals_9():
    bc = BattleContext(seed=701)
    m = bc.monsters.monsters[0]
    hp0 = m.hp
    setup_hand_upgraded(bc, STRIKE_W)
    bc.play_card(0)
    assert m.hp == hp0 - 9


def test_defend_w_gains_5_block():
    bc = BattleContext(seed=702)
    setup_hand(bc, DEFEND_W)
    bc.play_card(0)
    assert bc.player.block == 5


def test_defend_w_upgraded_gains_8():
    bc = BattleContext(seed=703)
    setup_hand_upgraded(bc, DEFEND_W)
    bc.play_card(0)
    assert bc.player.block == 8


def test_eruption_damage_then_wrath():
    """wiki Order 节：先结算伤害再进愤怒——自身伤害不吃尚未进入的 ×2。"""
    bc = BattleContext(seed=704)
    m = bc.monsters.monsters[0]
    hp0 = m.hp
    setup_hand(bc, ERUPTION)
    bc.play_card(0)
    assert m.hp == hp0 - 9
    assert bc.player.stance == Stance.WRATH
    # 愤怒下后续攻击 ×2（引擎乘区）
    setup_hand(bc, STRIKE_W)
    bc.play_card(0)
    assert m.hp == hp0 - 9 - 12


def test_eruption_upgraded_costs_1():
    bc = BattleContext(seed=705)
    m = bc.monsters.monsters[0]
    hp0 = m.hp
    setup_hand_upgraded(bc, ERUPTION)
    bc.player.energy = 1
    bc.play_card(0)
    assert m.hp == hp0 - 9  # 升级只改费（2→1），伤害仍 9（wiki 口径）
    assert bc.player.stance == Stance.WRATH


def test_vigilance_block_and_calm():
    bc = BattleContext(seed=706)
    setup_hand(bc, VIGILANCE)
    bc.play_card(0)
    assert bc.player.block == 8
    assert bc.player.stance == Stance.CALM


def test_vigilance_upgraded_12_block():
    bc = BattleContext(seed=707)
    setup_hand_upgraded(bc, VIGILANCE)
    bc.play_card(0)
    assert bc.player.block == 12


def test_calm_exit_grants_2_energy():
    """Keywords#Stance：退出平静 +2 能量（内容层仿真，见 watcher_cards 注释）。"""
    bc = BattleContext(seed=708, deck=[STRIKE] * 10)
    setup_hand(bc, VIGILANCE, ERUPTION)
    bc.player.energy = 5
    bc.play_card(0)  # Vigilance：-2 能量 → 3，进平静
    assert bc.player.stance == Stance.CALM
    bc.play_card(0)  # Eruption：-2 → 1，退出平静 +2 → 3
    assert bc.player.energy == 3
    assert bc.player.stance == Stance.WRATH


# ---- 生成牌 8 张 ----


def test_miracle_gains_1_energy_exhausts_retains():
    bc = BattleContext(seed=710, deck=[STRIKE] * 10)
    setup_hand(bc, MIRACLE)
    bc.player.energy = 1
    bc.play_card(0)
    assert bc.player.energy == 2
    assert pile_names(bc, bc.cards.exhaust_pile) == ["Miracle"]
    # 保留：未打出的 Miracle 回合末留手
    setup_hand(bc, MIRACLE)
    bc.end_turn()
    assert "Miracle" in pile_names(bc, bc.cards.hand)


def test_miracle_upgraded_gains_2_energy():
    bc = BattleContext(seed=711)
    setup_hand_upgraded(bc, MIRACLE)
    bc.player.energy = 1
    bc.play_card(0)
    assert bc.player.energy == 3


def test_insight_draws_2_and_exhausts():
    bc = BattleContext(seed=712)
    fill_draw(bc, 4)
    setup_hand(bc, INSIGHT)
    bc.play_card(0)
    assert len(bc.cards.hand) == 2
    assert pile_names(bc, bc.cards.exhaust_pile) == ["Insight"]


def test_insight_upgraded_draws_3():
    bc = BattleContext(seed=713)
    fill_draw(bc, 4)
    setup_hand_upgraded(bc, INSIGHT)
    bc.play_card(0)
    assert len(bc.cards.hand) == 3


def test_safety_12_block_exhausts_retains():
    bc = BattleContext(seed=714, deck=[STRIKE] * 10)
    setup_hand(bc, SAFETY)
    bc.play_card(0)
    assert bc.player.block == 12
    assert pile_names(bc, bc.cards.exhaust_pile) == ["Safety"]
    setup_hand(bc, SAFETY)
    bc.end_turn()
    assert "Safety" in pile_names(bc, bc.cards.hand)


def test_safety_upgraded_16_block():
    bc = BattleContext(seed=715)
    setup_hand_upgraded(bc, SAFETY)
    bc.play_card(0)
    assert bc.player.block == 16


def test_smite_12_damage_exhausts_retains():
    bc = BattleContext(seed=716, deck=[STRIKE] * 10)
    m = bc.monsters.monsters[0]
    hp0 = m.hp
    setup_hand(bc, SMITE)
    bc.play_card(0)
    assert m.hp == hp0 - 12
    assert pile_names(bc, bc.cards.exhaust_pile) == ["Smite"]
    setup_hand(bc, SMITE)
    bc.end_turn()
    assert "Smite" in pile_names(bc, bc.cards.hand)


def test_smite_upgraded_16_damage():
    bc = BattleContext(seed=717)
    m = bc.monsters.monsters[0]
    hp0 = m.hp
    setup_hand_upgraded(bc, SMITE)
    bc.play_card(0)
    assert m.hp == hp0 - 16


def test_through_violence_20_damage():
    bc = BattleContext(seed=718)
    m = bc.monsters.monsters[0]
    hp0 = m.hp
    setup_hand(bc, THROUGH_VIOLENCE)
    bc.play_card(0)
    assert m.hp == hp0 - 20
    assert pile_names(bc, bc.cards.exhaust_pile) == ["Through Violence"]


def test_through_violence_upgraded_30():
    bc = BattleContext(seed=719)
    m = bc.monsters.monsters[0]
    hp0 = m.hp
    setup_hand_upgraded(bc, THROUGH_VIOLENCE)
    bc.play_card(0)
    assert m.hp == hp0 - 30


def test_beta_shuffles_omega():
    bc = BattleContext(seed=720)
    fill_draw(bc, 3)
    setup_hand(bc, BETA)
    bc.play_card(0)
    assert "Omega" in pile_names(bc, bc.cards.draw_pile)
    assert pile_names(bc, bc.cards.exhaust_pile) == ["Beta"]


def test_beta_upgraded_costs_1():
    bc = BattleContext(seed=721)
    fill_draw(bc, 3)
    setup_hand_upgraded(bc, BETA)
    bc.player.energy = 1
    bc.play_card(0)
    assert "Omega" in pile_names(bc, bc.cards.draw_pile)


def test_omega_slots_end_of_turn_damage():
    """回合末全体 50/60 伤害无引擎钩子——special["omega"] 槽位落地。"""
    bc = BattleContext(seed=722)
    setup_hand(bc, OMEGA)
    bc.play_card(0)
    assert bc.player.special.get("omega") == 50
    assert not bc.cards.hand  # 能力牌打出即离场
    bc2 = BattleContext(seed=723)
    setup_hand_upgraded(bc2, OMEGA)
    bc2.play_card(0)
    assert bc2.player.special.get("omega") == 60


def test_expunger_deals_damage_x_times():
    """misc_data = 段数（由 Conjure Blade 写入）；独立打出时按段数结算。"""
    bc = BattleContext(seed=724)
    m = bc.monsters.monsters[0]
    hp0 = m.hp
    setup_hand(bc, EXPUNGER)
    bc.cards.hand[0].misc_data = 3
    bc.play_card(0)
    assert m.hp == hp0 - 27  # 9 × 3


def test_expunger_upgraded_15_damage():
    bc = BattleContext(seed=725)
    m = bc.monsters.monsters[0]
    hp0 = m.hp
    setup_hand_upgraded(bc, EXPUNGER)
    bc.cards.hand[0].misc_data = 2
    bc.play_card(0)
    assert m.hp == hp0 - 30  # 15 × 2


# ---- 普通 19 张 ----


def test_bowling_bash_hits_per_living_enemy():
    bc = BattleContext(seed=726)
    add_cultist(bc, idx=1, hp=99)
    m0 = bc.monsters.monsters[0]
    m1 = bc.monsters.monsters[1]
    hp0 = m0.hp
    setup_hand(bc, BOWLING_BASH)
    bc.play_card(0, target=0)
    assert m0.hp == hp0 - 14  # 7 × 2 只存活敌人
    assert m1.hp == 99  # 单目标
    # 存活敌人死亡后不计数（wiki：dead Darklings do not count）
    m1.hp = 0
    m1.is_dying = True
    bc.monsters.alive_count -= 1
    hp0 = m0.hp
    setup_hand(bc, BOWLING_BASH)
    bc.play_card(0, target=0)
    assert m0.hp == hp0 - 7


def test_bowling_bash_upgraded_10_per_hit():
    bc = BattleContext(seed=727)
    add_cultist(bc, idx=1, hp=99)
    m0 = bc.monsters.monsters[0]
    hp0 = m0.hp
    setup_hand_upgraded(bc, BOWLING_BASH)
    bc.play_card(0, target=0)
    assert m0.hp == hp0 - 20


def test_consecrate_hits_all():
    bc = BattleContext(seed=728)
    m0 = bc.monsters.monsters[0]
    m1 = add_cultist(bc, idx=1, hp=99)
    hp0 = m0.hp
    setup_hand(bc, CONSECRATE)
    bc.play_card(0)
    assert m0.hp == hp0 - 5
    assert m1.hp == 99 - 5


def test_crescendo_enters_wrath_retains_exhausts():
    bc = BattleContext(seed=729, deck=[STRIKE] * 10)
    setup_hand(bc, CRESCENDO)
    bc.play_card(0)
    assert bc.player.stance == Stance.WRATH
    assert pile_names(bc, bc.cards.exhaust_pile) == ["Crescendo"]
    # 保留：回合末在手不弃（打出路径不涉及；未打出时验证）
    setup_hand(bc, CRESCENDO)
    bc.end_turn()
    assert "Crescendo" in pile_names(bc, bc.cards.hand)
    assert bc.player.stance == Stance.WRATH  # 保留未打出，不切姿态


def test_crescendo_upgraded_costs_0():
    bc = BattleContext(seed=730)
    setup_hand_upgraded(bc, CRESCENDO)
    bc.player.energy = 0
    bc.play_card(0)
    assert bc.player.stance == Stance.WRATH


def test_crush_joints_after_skill_applies_vulnerable():
    bc = BattleContext(seed=731)
    setup_hand(bc, DEFEND_W, CRUSH_JOINTS)
    bc.play_card(0)  # 技能牌在前
    m = bc.monsters.monsters[0]
    assert m.statuses.get(MonsterStatus.VULNERABLE) == 0
    bc.player.energy = 3
    bc.play_card(0)
    assert m.statuses.get(MonsterStatus.VULNERABLE) == 1


def test_crush_joints_after_attack_no_vulnerable():
    bc = BattleContext(seed=732)
    m = bc.monsters.monsters[0]
    setup_hand(bc, STRIKE_W, CRUSH_JOINTS)
    bc.player.energy = 3
    bc.play_card(0)
    bc.play_card(0)
    assert m.statuses.get(MonsterStatus.VULNERABLE) == 0


def test_crush_joints_upgraded_10_damage_2_vulnerable():
    bc = BattleContext(seed=733)
    m = bc.monsters.monsters[0]
    hp0 = m.hp
    setup_hand(bc, DEFEND_W)
    bc.play_card(0)
    setup_hand_upgraded(bc, CRUSH_JOINTS)
    bc.player.energy = 3
    bc.play_card(0)
    assert m.hp == hp0 - 10
    assert m.statuses.get(MonsterStatus.VULNERABLE) == 2


def test_cut_through_fate_damage_scry_draw():
    bc = BattleContext(seed=734)
    m = bc.monsters.monsters[0]
    hp0 = m.hp
    fill_draw(bc, 4, WOUND)
    setup_hand(bc, CUT_THROUGH_FATE)
    bc.play_card(0)
    assert m.hp == hp0 - 7
    assert bc.input_state == InputState.SCRY
    assert len(bc.scry_cards) == 2
    bc.choose_scry(0)  # 全弃
    assert len(bc.cards.discard_pile) == 3  # 2 张伤口 + CTF 本体落堆
    assert len(bc.cards.hand) == 1  # 检视后抽 1


def test_cut_through_fate_upgraded_scry_3():
    bc = BattleContext(seed=735)
    m = bc.monsters.monsters[0]
    hp0 = m.hp
    fill_draw(bc, 5, WOUND)
    setup_hand_upgraded(bc, CUT_THROUGH_FATE)
    bc.play_card(0)
    assert m.hp == hp0 - 9
    assert len(bc.scry_cards) == 3
    bc.choose_scry(3)  # 全保留
    assert len(bc.cards.discard_pile) == 1  # 仅 CTF+ 本体落堆
    assert len(bc.cards.hand) == 1


def test_empty_body_block_and_exit_stance():
    bc = BattleContext(seed=736)
    bc.player.change_stance(bc, Stance.WRATH)
    setup_hand(bc, EMPTY_BODY)
    bc.play_card(0)
    assert bc.player.block == 7
    assert bc.player.stance == Stance.NEUTRAL


def test_empty_body_upgraded_10_block():
    bc = BattleContext(seed=737)
    setup_hand_upgraded(bc, EMPTY_BODY)
    bc.play_card(0)
    assert bc.player.block == 10


def test_empty_fist_damage_and_exit():
    bc = BattleContext(seed=738)
    m = bc.monsters.monsters[0]
    hp0 = m.hp
    bc.player.change_stance(bc, Stance.CALM)
    bc.player.energy = 1
    setup_hand(bc, EMPTY_FIST)
    bc.play_card(0)
    assert m.hp == hp0 - 9
    assert bc.player.stance == Stance.NEUTRAL
    assert bc.player.energy == 2  # 退出平静 +2（仿真）


def test_empty_fist_upgraded_14():
    bc = BattleContext(seed=739)
    m = bc.monsters.monsters[0]
    hp0 = m.hp
    setup_hand_upgraded(bc, EMPTY_FIST)
    bc.play_card(0)
    assert m.hp == hp0 - 14


def test_evaluate_block_and_insight():
    bc = BattleContext(seed=740)
    fill_draw(bc, 3)
    setup_hand(bc, EVALUATE)
    bc.play_card(0)
    assert bc.player.block == 6
    assert "Insight" in pile_names(bc, bc.cards.draw_pile)


def test_evaluate_upgraded_10_block():
    bc = BattleContext(seed=741)
    fill_draw(bc, 3)
    setup_hand_upgraded(bc, EVALUATE)
    bc.play_card(0)
    assert bc.player.block == 10


def test_flurry_of_blows_damage_and_recall_on_stance_change():
    """姿态实际切换时从弃牌堆回手（内容层仿真，_change_stance 内）。"""
    bc = BattleContext(seed=742, deck=[STRIKE] * 10)
    m = bc.monsters.monsters[0]
    hp0 = m.hp
    setup_hand(bc, FLURRY_OF_BLOWS, CRESCENDO)
    bc.play_card(0)
    assert m.hp == hp0 - 4
    assert pile_names(bc, bc.cards.discard_pile) == ["Flurry of Blows"]
    bc.play_card(0)  # Crescendo：进愤怒（真实切换）→ Flurry 回手
    assert bc.player.stance == Stance.WRATH
    assert "Flurry of Blows" in pile_names(bc, bc.cards.hand)


def test_flurry_of_blows_upgraded_6():
    bc = BattleContext(seed=743)
    m = bc.monsters.monsters[0]
    hp0 = m.hp
    setup_hand_upgraded(bc, FLURRY_OF_BLOWS)
    bc.play_card(0)
    assert m.hp == hp0 - 6


def test_flying_sleeves_twice_and_retains():
    bc = BattleContext(seed=744, deck=[STRIKE] * 10)
    m = bc.monsters.monsters[0]
    hp0 = m.hp
    setup_hand(bc, FLYING_SLEEVES)
    bc.play_card(0)
    assert m.hp == hp0 - 8  # 4 × 2
    setup_hand(bc, FLYING_SLEEVES)
    bc.end_turn()
    assert "Flying Sleeves" in pile_names(bc, bc.cards.hand)


def test_flying_sleeves_upgraded_12_total():
    bc = BattleContext(seed=745)
    m = bc.monsters.monsters[0]
    hp0 = m.hp
    setup_hand_upgraded(bc, FLYING_SLEEVES)
    bc.play_card(0)
    assert m.hp == hp0 - 12


def test_follow_up_after_attack_gains_energy():
    bc = BattleContext(seed=746, deck=[STRIKE] * 10)
    setup_hand(bc, STRIKE_W, FOLLOW_UP)
    bc.player.energy = 2
    bc.play_card(0)
    assert bc.player.energy == 1
    bc.play_card(0)
    assert bc.player.energy == 1  # -1 费 +1 能量：净 1（上一张是攻击）


def test_follow_up_first_card_no_energy():
    bc = BattleContext(seed=747)
    m = bc.monsters.monsters[0]
    setup_hand(bc, FOLLOW_UP)
    bc.player.energy = 1
    bc.play_card(0)
    assert bc.player.energy == 0  # 本场首张，无奖励


def test_follow_up_upgraded_11_damage():
    bc = BattleContext(seed=748)
    m = bc.monsters.monsters[0]
    hp0 = m.hp
    setup_hand_upgraded(bc, FOLLOW_UP)
    bc.play_card(0)
    assert m.hp == hp0 - 11


def test_halt_base_block():
    bc = BattleContext(seed=749)
    setup_hand(bc, HALT)
    bc.play_card(0)
    assert bc.player.block == 3


def test_halt_in_wrath_extra_block():
    bc = BattleContext(seed=750)
    bc.player.change_stance(bc, Stance.WRATH)
    setup_hand(bc, HALT)
    bc.play_card(0)
    assert bc.player.block == 12  # 3 + 9


def test_halt_upgraded_in_wrath_18():
    bc = BattleContext(seed=751)
    bc.player.change_stance(bc, Stance.WRATH)
    setup_hand_upgraded(bc, HALT)
    bc.play_card(0)
    assert bc.player.block == 18  # 4 + 14


def test_just_lucky_scry_block_damage():
    bc = BattleContext(seed=752)
    m = bc.monsters.monsters[0]
    hp0 = m.hp
    fill_draw(bc, 2, WOUND)
    setup_hand(bc, JUST_LUCKY)
    bc.play_card(0)
    assert bc.input_state == InputState.SCRY
    assert len(bc.scry_cards) == 1
    bc.choose_scry(0)
    assert bc.player.block == 2
    assert m.hp == hp0 - 3


def test_just_lucky_upgraded():
    bc = BattleContext(seed=753)
    m = bc.monsters.monsters[0]
    hp0 = m.hp
    fill_draw(bc, 2, WOUND)
    setup_hand_upgraded(bc, JUST_LUCKY)
    bc.play_card(0)
    assert len(bc.scry_cards) == 2
    bc.choose_scry(0)
    assert bc.player.block == 3
    assert m.hp == hp0 - 4


def test_pressure_points_mark_and_hp_loss():
    bc = BattleContext(seed=754)
    m0 = bc.monsters.monsters[0]
    m1 = add_cultist(bc, idx=1, hp=99)
    hp0 = m0.hp
    setup_hand(bc, PRESSURE_POINTS)
    bc.play_card(0)
    assert m0.statuses.get(MonsterStatus.MARK) == 8
    assert m1.statuses.get(MonsterStatus.MARK) == 8
    assert m0.hp == hp0 - 8
    assert m1.hp == 99 - 8
    # 标记可叠：第二张按 16 结算
    hp0 = m0.hp
    bc.player.energy = 1
    setup_hand(bc, PRESSURE_POINTS)
    bc.play_card(0)
    assert m0.statuses.get(MonsterStatus.MARK) == 16
    assert m0.hp == hp0 - 16


def test_pressure_points_hp_loss_ignores_block():
    """wiki：lose HP 不吃格挡。"""
    bc = BattleContext(seed=755)
    m = bc.monsters.monsters[0]
    m.block = 20
    hp0 = m.hp
    setup_hand(bc, PRESSURE_POINTS)
    bc.play_card(0)
    assert m.hp == hp0 - 8
    assert m.block == 20


def test_pressure_points_upgraded_11():
    bc = BattleContext(seed=756)
    m = bc.monsters.monsters[0]
    hp0 = m.hp
    setup_hand_upgraded(bc, PRESSURE_POINTS)
    bc.play_card(0)
    assert m.hp == hp0 - 11


def test_prostrate_mantra_and_block():
    bc = BattleContext(seed=757)
    setup_hand(bc, PROSTRATE)
    bc.play_card(0)
    assert bc.player.statuses.get(PlayerStatus.MANTRA) == 2
    assert bc.player.block == 4


def test_prostrate_upgraded_3_mantra():
    bc = BattleContext(seed=758)
    setup_hand_upgraded(bc, PROSTRATE)
    bc.play_card(0)
    assert bc.player.statuses.get(PlayerStatus.MANTRA) == 3


def test_mantra_at_ten_enters_divinity_with_energy():
    """5×Prostrate(2) 累计满 10：进 Divinity + 3 能量（内容层仿真）。"""
    bc = BattleContext(seed=759, deck=[STRIKE] * 10)
    for _ in range(5):
        setup_hand(bc, PROSTRATE)
        bc.player.energy = 1
        bc.play_card(0)
    assert bc.player.stance == Stance.DIVINITY
    assert not bc.player.statuses.has(PlayerStatus.MANTRA)  # 清零
    assert bc.player.energy == 4  # 末次打出后剩 1，进 Divinity +3 → 4
    # Divinity 攻击 ×3，且下回合开始回中性（引擎已接）
    setup_hand(bc, STRIKE_W)
    bc.play_card(0)
    bc.end_turn()
    assert bc.player.stance == Stance.NEUTRAL


def test_protect_block_and_retains():
    bc = BattleContext(seed=760, deck=[STRIKE] * 10)
    setup_hand(bc, PROTECT)
    bc.play_card(0)
    assert bc.player.block == 12
    setup_hand(bc, PROTECT)
    bc.end_turn()
    assert "Protect" in pile_names(bc, bc.cards.hand)


def test_protect_upgraded_16():
    bc = BattleContext(seed=761)
    setup_hand_upgraded(bc, PROTECT)
    bc.play_card(0)
    assert bc.player.block == 16


def test_sash_whip_after_attack_applies_weak():
    bc = BattleContext(seed=762)
    m = bc.monsters.monsters[0]
    setup_hand(bc, STRIKE_W, SASH_WHIP)
    bc.player.energy = 2
    bc.play_card(0)
    assert m.statuses.get(MonsterStatus.WEAK) == 0
    bc.play_card(0)
    assert m.statuses.get(MonsterStatus.WEAK) == 1


def test_sash_whip_after_skill_no_weak():
    bc = BattleContext(seed=763)
    m = bc.monsters.monsters[0]
    setup_hand(bc, DEFEND_W, SASH_WHIP)
    bc.player.energy = 2
    bc.play_card(0)
    bc.play_card(0)
    assert m.statuses.get(MonsterStatus.WEAK) == 0


def test_sash_whip_upgraded_10_damage_2_weak():
    bc = BattleContext(seed=764)
    m = bc.monsters.monsters[0]
    hp0 = m.hp
    setup_hand(bc, STRIKE_W)
    bc.play_card(0)
    setup_hand_upgraded(bc, SASH_WHIP)
    bc.player.energy = 1
    bc.play_card(0)
    assert m.hp == hp0 - 6 - 10
    assert m.statuses.get(MonsterStatus.WEAK) == 2


def test_third_eye_block_and_scry():
    bc = BattleContext(seed=765)
    fill_draw(bc, 5, WOUND)
    setup_hand(bc, THIRD_EYE)
    bc.play_card(0)
    assert bc.player.block == 7
    assert bc.input_state == InputState.SCRY
    assert len(bc.scry_cards) == 3
    bc.choose_scry(0)
    assert len(bc.cards.discard_pile) == 4  # 3 张伤口 + Third Eye 本体


def test_third_eye_upgraded_scry_5():
    bc = BattleContext(seed=766)
    fill_draw(bc, 6, WOUND)
    setup_hand_upgraded(bc, THIRD_EYE)
    bc.play_card(0)
    assert bc.player.block == 9
    assert len(bc.scry_cards) == 5
    bc.choose_scry(0)


def test_tranquility_enters_calm_retains_exhausts():
    bc = BattleContext(seed=767, deck=[STRIKE] * 10)
    setup_hand(bc, TRANQUILITY)
    bc.play_card(0)
    assert bc.player.stance == Stance.CALM
    assert pile_names(bc, bc.cards.exhaust_pile) == ["Tranquility"]
    setup_hand(bc, TRANQUILITY)
    bc.end_turn()
    assert "Tranquility" in pile_names(bc, bc.cards.hand)


def test_tranquility_upgraded_costs_0():
    bc = BattleContext(seed=768)
    setup_hand_upgraded(bc, TRANQUILITY)
    bc.player.energy = 0
    bc.play_card(0)
    assert bc.player.stance == Stance.CALM


# ---- 非普通 35 张 ----


def test_battle_hymn_slots_and_innate_when_upgraded():
    bc = BattleContext(seed=769)
    setup_hand(bc, BATTLE_HYMN)
    bc.play_card(0)
    assert bc.player.special.get("battle_hymn") == 1
    assert BATTLE_HYMN.innate_when_upgraded and not BATTLE_HYMN.innate


def test_carve_reality_damage_and_smite():
    bc = BattleContext(seed=770)
    m = bc.monsters.monsters[0]
    hp0 = m.hp
    setup_hand(bc, CARVE_REALITY)
    bc.play_card(0)
    assert m.hp == hp0 - 6
    assert "Smite" in pile_names(bc, bc.cards.hand)


def test_carve_reality_upgraded_10():
    bc = BattleContext(seed=771)
    m = bc.monsters.monsters[0]
    hp0 = m.hp
    setup_hand_upgraded(bc, CARVE_REALITY)
    bc.play_card(0)
    assert m.hp == hp0 - 10


def test_collect_slots_turns():
    bc = BattleContext(seed=772)
    fill_draw(bc, 3)
    setup_hand(bc, COLLECT)
    bc.player.energy = 3
    bc.play_card(0)
    assert bc.player.special.get("collect_miracles") == 3
    assert pile_names(bc, bc.cards.exhaust_pile) == ["Collect"]


def test_collect_upgraded_x_plus_1():
    bc = BattleContext(seed=773)
    setup_hand_upgraded(bc, COLLECT)
    bc.player.energy = 2
    bc.play_card(0)
    assert bc.player.special.get("collect_miracles") == 3


def test_conclude_ends_turn():
    bc = BattleContext(seed=774, deck=[STRIKE] * 10)
    m = bc.monsters.monsters[0]
    hp0 = m.hp
    setup_hand(bc, CONCLUDE)
    bc.play_card(0)
    assert m.hp == hp0 - 12
    assert bc.turn == 2  # 结束回合 → 敌方行动 → 新回合
    assert len(bc.cards.hand) == 5
    assert bc.player.energy == 3


def test_conclude_upgraded_16():
    bc = BattleContext(seed=775, deck=[STRIKE] * 10)
    m = bc.monsters.monsters[0]
    hp0 = m.hp
    setup_hand_upgraded(bc, CONCLUDE)
    bc.play_card(0)
    assert m.hp == hp0 - 16


def test_deceive_reality_block_and_safety():
    bc = BattleContext(seed=776)
    setup_hand(bc, DECEIVE_REALITY)
    bc.play_card(0)
    assert bc.player.block == 4
    assert "Safety" in pile_names(bc, bc.cards.hand)


def test_deceive_reality_upgraded_7_block():
    bc = BattleContext(seed=777)
    setup_hand_upgraded(bc, DECEIVE_REALITY)
    bc.play_card(0)
    assert bc.player.block == 7


def test_empty_mind_exit_and_draw():
    bc = BattleContext(seed=778)
    bc.player.change_stance(bc, Stance.WRATH)
    fill_draw(bc, 3)
    setup_hand(bc, EMPTY_MIND)
    bc.play_card(0)
    assert bc.player.stance == Stance.NEUTRAL
    assert len(bc.cards.hand) == 2


def test_empty_mind_upgraded_draw_3():
    bc = BattleContext(seed=779)
    fill_draw(bc, 3)
    setup_hand_upgraded(bc, EMPTY_MIND)
    bc.play_card(0)
    assert len(bc.cards.hand) == 3


def test_fasting_stats_and_energy_penalty():
    bc = BattleContext(seed=780, deck=[STRIKE] * 10)
    setup_hand(bc, FASTING)
    bc.player.energy = 2
    bc.play_card(0)
    assert bc.player.statuses.get(PlayerStatus.STRENGTH) == 3
    assert bc.player.statuses.get(PlayerStatus.DEXTERITY) == 3
    bc.end_turn()
    assert bc.player.energy == 2  # 3 - 1（energy_per_turn_bonus）


def test_fasting_upgraded_4_4():
    bc = BattleContext(seed=781, deck=[STRIKE] * 10)
    setup_hand_upgraded(bc, FASTING)
    bc.player.energy = 2
    bc.play_card(0)
    assert bc.player.statuses.get(PlayerStatus.STRENGTH) == 4
    assert bc.player.statuses.get(PlayerStatus.DEXTERITY) == 4
    bc.end_turn()
    assert bc.player.energy == 2


def test_fear_no_evil_enters_calm_on_attack_intent():
    bc = BattleContext(seed=782)
    m = bc.monsters.monsters[0]
    m.set_move(Cultist.DARK_STRIKE)
    setup_hand(bc, FEAR_NO_EVIL)
    bc.play_card(0)
    assert bc.player.stance == Stance.CALM


def test_fear_no_evil_no_calm_on_non_attack_intent():
    bc = BattleContext(seed=783)
    m = bc.monsters.monsters[0]
    m.set_move(Cultist.INCANTATION)
    setup_hand(bc, FEAR_NO_EVIL)
    bc.play_card(0)
    assert bc.player.stance == Stance.NEUTRAL


def test_fear_no_evil_upgraded_11():
    bc = BattleContext(seed=784)
    m = bc.monsters.monsters[0]
    hp0 = m.hp
    m.set_move(Cultist.DARK_STRIKE)
    setup_hand_upgraded(bc, FEAR_NO_EVIL)
    bc.play_card(0)
    assert m.hp == hp0 - 11
    assert bc.player.stance == Stance.CALM


def test_foreign_influence_choose_one():
    bc = BattleContext(seed=785)
    setup_hand(bc, FOREIGN_INFLUENCE)
    bc.play_card(0)
    assert bc.input_state == InputState.CARD_SELECT
    cands = bc.card_select_info.candidates
    assert len(cands) == 3
    assert all(c.ctype == "Attack" for c in cands)
    assert pile_names(bc, bc.cards.exhaust_pile) == ["Foreign Influence"]
    bc.choose_card(0)
    chosen = bc.cards.hand[-1]
    assert chosen.card.ctype == "Attack"
    assert chosen.cost_for_turn == -1  # 基础版不改费


def test_foreign_influence_upgraded_zero_cost():
    bc = BattleContext(seed=786)
    setup_hand_upgraded(bc, FOREIGN_INFLUENCE)
    bc.play_card(0)
    bc.choose_card(0)
    assert bc.cards.hand[-1].cost_for_turn == 0


def test_foreign_influence_pool_exclusions():
    from sts.content.watcher_cards import _foreign_influence_pool

    pool = _foreign_influence_pool()
    names = {c.name for c in pool}
    assert not (names & {"Feed", "Reaper", "Lesson Learned", "Bite", "Ritual Dagger",
                         "Shiv", "Smite", "Through Violence", "Expunger", "Strike",
                         "Defend"})
    assert {"Bash", "Neutralize", "Swift Strike", "Eruption"}.issubset(names)


def test_foresight_slots():
    bc = BattleContext(seed=787)
    setup_hand(bc, FORESIGHT)
    bc.play_card(0)
    assert bc.player.special.get("foresight") == 3
    bc2 = BattleContext(seed=788)
    setup_hand_upgraded(bc2, FORESIGHT)
    bc2.play_card(0)
    assert bc2.player.special.get("foresight") == 4


def test_indignation_enters_wrath_when_not_wrath():
    bc = BattleContext(seed=789)
    setup_hand(bc, INDIGNATION)
    bc.play_card(0)
    assert bc.player.stance == Stance.WRATH


def test_indignation_vulnerable_all_when_wrath():
    bc = BattleContext(seed=790)
    m0 = bc.monsters.monsters[0]
    m1 = add_cultist(bc, idx=1, hp=99)
    bc.player.change_stance(bc, Stance.WRATH)
    setup_hand(bc, INDIGNATION)
    bc.play_card(0)
    assert bc.player.stance == Stance.WRATH
    assert m0.statuses.get(MonsterStatus.VULNERABLE) == 3
    assert m1.statuses.get(MonsterStatus.VULNERABLE) == 3


def test_indignation_upgraded_5_vulnerable():
    bc = BattleContext(seed=791)
    m = bc.monsters.monsters[0]
    bc.player.change_stance(bc, Stance.WRATH)
    setup_hand_upgraded(bc, INDIGNATION)
    bc.play_card(0)
    assert m.statuses.get(MonsterStatus.VULNERABLE) == 5


def test_inner_peace_draws_when_calm():
    bc = BattleContext(seed=792)
    bc.player.change_stance(bc, Stance.CALM)
    fill_draw(bc, 3)
    setup_hand(bc, INNER_PEACE)
    bc.play_card(0)
    assert len(bc.cards.hand) == 3
    assert bc.player.stance == Stance.CALM


def test_inner_peace_enters_calm_otherwise():
    bc = BattleContext(seed=793)
    setup_hand(bc, INNER_PEACE)
    bc.play_card(0)
    assert bc.player.stance == Stance.CALM
    assert len(bc.cards.hand) == 0


def test_inner_peace_upgraded_draw_4():
    bc = BattleContext(seed=794)
    bc.player.change_stance(bc, Stance.CALM)
    fill_draw(bc, 4)
    setup_hand_upgraded(bc, INNER_PEACE)
    bc.play_card(0)
    assert len(bc.cards.hand) == 4


def test_like_water_status_lands():
    """wiki 回合末 5/7 格挡 vs 引擎 3×层——只断言状态落地（偏差见迁移报告）。"""
    bc = BattleContext(seed=795)
    setup_hand(bc, LIKE_WATER)
    bc.play_card(0)
    assert bc.player.statuses.get(PlayerStatus.LIKE_WATER) == 5


def test_meditate_retains_discard_card_and_ends_turn():
    bc = BattleContext(seed=796, deck=[STRIKE] * 10)
    bc.cards.discard_pile.clear()
    bc.cards.discard_pile.append(bc.cards.instantiate(STRIKE_W))
    setup_hand(bc, MEDITATE)
    bc.play_card(0)
    assert bc.input_state == InputState.CARD_SELECT
    bc.choose_card(0)
    assert "Strike" in pile_names(bc, bc.cards.hand)
    assert bc.player.stance == Stance.CALM
    assert bc.turn == 2  # 结束回合
    # 保留牌跨回合还在手（回合开始 limbo 还手）
    assert "Strike" in pile_names(bc, bc.cards.hand)


def test_meditate_upgraded_two_cards():
    bc = BattleContext(seed=797, deck=[STRIKE] * 10)
    bc.cards.discard_pile.clear()
    for _ in range(2):
        bc.cards.discard_pile.append(bc.cards.instantiate(STRIKE_W))
    fill_draw(bc, 0)  # 清空抽牌堆：回合开始只还手 2 张保留牌，计数确定
    setup_hand_upgraded(bc, MEDITATE)
    bc.play_card(0)
    bc.choose_cards([0, 1])
    assert sum(1 for n in pile_names(bc, bc.cards.hand) if n == "Strike") == 2


def test_mental_fortress_blocks_on_stance_change():
    """wiki 每次切换 4/6 格挡；引擎常量 3×层（偏差见迁移报告）→ 断言 3。"""
    bc = BattleContext(seed=798)
    setup_hand(bc, MENTAL_FORTRESS)
    bc.play_card(0)
    assert bc.player.statuses.get(PlayerStatus.MENTAL_FORTRESS) == 1
    bc.player.change_stance(bc, Stance.CALM)
    run_queue(bc)
    assert bc.player.block == 4  # wiki 常量 4


def test_nirvana_slots():
    bc = BattleContext(seed=799)
    setup_hand(bc, NIRVANA)
    bc.play_card(0)
    assert bc.player.special.get("nirvana") == 3
    bc2 = BattleContext(seed=800)
    setup_hand_upgraded(bc2, NIRVANA)
    bc2.play_card(0)
    assert bc2.player.special.get("nirvana") == 4


def test_perseverance_block_and_retain():
    bc = BattleContext(seed=801, deck=[STRIKE] * 10)
    setup_hand(bc, PERSEVERANCE)
    bc.play_card(0)
    assert bc.player.block == 5
    setup_hand(bc, PERSEVERANCE)
    bc.end_turn()
    assert "Perseverance" in pile_names(bc, bc.cards.hand)


def test_perseverance_misc_data_bonus_counts():
    """保留增量缺引擎钩子（迁移报告）；misc_data 手动推进时 play 应计入。"""
    bc = BattleContext(seed=802)
    setup_hand(bc, PERSEVERANCE)
    bc.cards.hand[0].misc_data = 4  # 两回合保留（+2/回合）的等效累计
    bc.play_card(0)
    assert bc.player.block == 9  # 5 + 4


def test_perseverance_upgraded_7_block():
    bc = BattleContext(seed=803)
    setup_hand_upgraded(bc, PERSEVERANCE)
    bc.play_card(0)
    assert bc.player.block == 7


def test_pray_mantra_and_insight():
    bc = BattleContext(seed=804)
    fill_draw(bc, 3)
    setup_hand(bc, PRAY)
    bc.play_card(0)
    assert bc.player.statuses.get(PlayerStatus.MANTRA) == 3
    assert "Insight" in pile_names(bc, bc.cards.draw_pile)


def test_pray_upgraded_4_mantra():
    bc = BattleContext(seed=805)
    fill_draw(bc, 3)
    setup_hand_upgraded(bc, PRAY)
    bc.play_card(0)
    assert bc.player.statuses.get(PlayerStatus.MANTRA) == 4


def test_reach_heaven_damage_and_through_violence():
    bc = BattleContext(seed=806)
    m = bc.monsters.monsters[0]
    hp0 = m.hp
    fill_draw(bc, 3)
    setup_hand(bc, REACH_HEAVEN)
    bc.play_card(0)
    assert m.hp == hp0 - 10
    assert "Through Violence" in pile_names(bc, bc.cards.draw_pile)


def test_reach_heaven_upgraded_15():
    bc = BattleContext(seed=807)
    m = bc.monsters.monsters[0]
    hp0 = m.hp
    setup_hand_upgraded(bc, REACH_HEAVEN)
    bc.play_card(0)
    assert m.hp == hp0 - 15


def test_rushdown_draws_on_wrath_entry():
    bc = BattleContext(seed=808, deck=[STRIKE] * 10)
    setup_hand(bc, RUSHDOWN, ERUPTION)
    fill_draw(bc, 5)
    bc.player.energy = 3
    bc.play_card(0)  # Power
    assert bc.player.statuses.get(PlayerStatus.RUSHDOWN) == 1
    bc.play_card(0)  # Eruption 进愤怒 → 抽 2
    assert bc.player.stance == Stance.WRATH
    assert len(bc.cards.hand) == 2


def test_rushdown_upgraded_costs_0():
    bc = BattleContext(seed=809)
    setup_hand_upgraded(bc, RUSHDOWN)
    bc.player.energy = 0
    bc.play_card(0)
    assert bc.player.statuses.get(PlayerStatus.RUSHDOWN) == 1


def test_sanctity_draws_after_skill():
    bc = BattleContext(seed=810)
    fill_draw(bc, 3)
    setup_hand(bc, DEFEND_W, SANCTITY)
    bc.player.energy = 2
    bc.play_card(0)  # Defend（技能）
    assert len(bc.cards.hand) == 1  # 剩 Sanctity
    bc.play_card(0)
    assert bc.player.block == 6 + 5  # Defend 5 + Sanctity 6
    assert len(bc.cards.hand) == 2  # 上一张是技能 → 抽 2


def test_sanctity_no_draw_after_attack():
    bc = BattleContext(seed=811)
    fill_draw(bc, 3)
    setup_hand(bc, STRIKE_W, SANCTITY)
    bc.player.energy = 2
    bc.play_card(0)
    bc.play_card(0)
    assert len(bc.cards.hand) == 0


def test_sanctity_upgraded_9_block():
    bc = BattleContext(seed=812)
    setup_hand_upgraded(bc, SANCTITY)
    bc.play_card(0)
    assert bc.player.block == 9


def test_sands_of_time_damage_and_retain():
    bc = BattleContext(seed=813, deck=[STRIKE] * 10)
    m = bc.monsters.monsters[0]
    hp0 = m.hp
    setup_hand(bc, SANDS_OF_TIME)
    bc.player.energy = 4
    bc.play_card(0)
    assert m.hp == hp0 - 20
    setup_hand(bc, SANDS_OF_TIME)
    bc.end_turn()
    assert "Sands of Time" in pile_names(bc, bc.cards.hand)


def test_sands_of_time_upgraded_26():
    bc = BattleContext(seed=814)
    m = bc.monsters.monsters[0]
    hp0 = m.hp
    setup_hand_upgraded(bc, SANDS_OF_TIME)
    bc.player.energy = 4
    bc.play_card(0)
    assert m.hp == hp0 - 26


def test_signature_move_playable_when_sole_attack():
    bc = BattleContext(seed=815)
    m = bc.monsters.monsters[0]
    hp0 = m.hp
    setup_hand(bc, SIGNATURE_MOVE, DEFEND_W)
    bc.player.energy = 2
    bc.play_card(0)
    assert m.hp == hp0 - 30


def test_signature_move_blocked_with_other_attack():
    bc = BattleContext(seed=816)
    setup_hand(bc, SIGNATURE_MOVE, STRIKE_W)
    with pytest.raises(ValueError, match="不满足打出条件"):
        bc.play_card(0)


def test_signature_move_upgraded_40():
    bc = BattleContext(seed=817)
    m = bc.monsters.monsters[0]
    hp0 = m.hp
    setup_hand_upgraded(bc, SIGNATURE_MOVE)
    bc.player.energy = 2
    bc.play_card(0)
    assert m.hp == hp0 - 40


def test_simmering_fury_next_turn_wrath_and_draw():
    bc = BattleContext(seed=818, deck=[STRIKE] * 10)
    setup_hand(bc, SIMMERING_FURY)
    bc.play_card(0)
    assert bc.player.statuses.get(PlayerStatus.WRATH_NEXT_TURN) == 1
    assert bc.player.special.get("next_turn_draw") == 2
    fill_draw(bc, 10)  # 抽牌堆充足：5 + 2 全额到手
    bc.end_turn()
    assert bc.player.stance == Stance.WRATH
    assert len(bc.cards.hand) == 7


def test_simmering_fury_upgraded_draw_3():
    bc = BattleContext(seed=819, deck=[STRIKE] * 10)
    setup_hand_upgraded(bc, SIMMERING_FURY)
    bc.play_card(0)
    fill_draw(bc, 10)
    bc.end_turn()
    assert bc.player.stance == Stance.WRATH
    assert len(bc.cards.hand) == 8


def test_study_slots_and_upgraded_cost():
    bc = BattleContext(seed=820)
    setup_hand(bc, STUDY)
    bc.play_card(0)
    assert bc.player.special.get("study") == 1
    assert STUDY.upgraded_cost == 1


def test_swivel_block_and_slot():
    bc = BattleContext(seed=821)
    setup_hand(bc, SWIVEL)
    bc.play_card(0)
    assert bc.player.block == 8
    assert bc.player.special.get("swivel") == 1


def test_swivel_upgraded_11_block():
    bc = BattleContext(seed=822)
    setup_hand_upgraded(bc, SWIVEL)
    bc.play_card(0)
    assert bc.player.block == 11


def test_talk_to_the_hand_damage_and_block_return():
    bc = BattleContext(seed=823)
    m = bc.monsters.monsters[0]
    hp0 = m.hp
    setup_hand(bc, TALK_TO_THE_HAND)
    bc.play_card(0)
    assert m.hp == hp0 - 5
    assert m.statuses.get(MonsterStatus.BLOCK_RETURN) == 2
    assert pile_names(bc, bc.cards.exhaust_pile) == ["Talk to the Hand"]


def test_talk_to_the_hand_upgraded_7_3():
    bc = BattleContext(seed=824)
    m = bc.monsters.monsters[0]
    hp0 = m.hp
    setup_hand_upgraded(bc, TALK_TO_THE_HAND)
    bc.play_card(0)
    assert m.hp == hp0 - 7
    assert m.statuses.get(MonsterStatus.BLOCK_RETURN) == 3


def test_tantrum_multi_hit_wrath_shuffle():
    bc = BattleContext(seed=825)
    m = bc.monsters.monsters[0]
    hp0 = m.hp
    fill_draw(bc, 3)
    setup_hand(bc, TANTRUM)
    bc.play_card(0)
    assert m.hp == hp0 - 9  # 3 × 3
    assert bc.player.stance == Stance.WRATH
    assert "Tantrum" in pile_names(bc, bc.cards.draw_pile)  # 本体洗回抽牌堆
    assert "Tantrum" not in pile_names(bc, bc.cards.discard_pile)


def test_tantrum_upgraded_4_hits():
    bc = BattleContext(seed=826)
    m = bc.monsters.monsters[0]
    hp0 = m.hp
    setup_hand_upgraded(bc, TANTRUM)
    bc.play_card(0)
    assert m.hp == hp0 - 12


def test_wallop_gains_unblocked_damage():
    bc = BattleContext(seed=827)
    m = bc.monsters.monsters[0]
    m.block = 5
    setup_hand(bc, WALLOP)
    bc.play_card(0)
    assert bc.player.block == 4  # 9 伤 - 5 格挡吸收 = 4 未格挡


def test_wallop_upgraded_12():
    bc = BattleContext(seed=828)
    m = bc.monsters.monsters[0]
    hp0 = m.hp
    setup_hand_upgraded(bc, WALLOP)
    bc.play_card(0)
    assert m.hp == hp0 - 12
    assert bc.player.block == 12


def test_wave_of_the_hand_slots():
    bc = BattleContext(seed=829)
    setup_hand(bc, WAVE_OF_THE_HAND)
    bc.play_card(0)
    assert bc.player.special.get("wave_of_the_hand") == 1
    bc2 = BattleContext(seed=830)
    setup_hand_upgraded(bc2, WAVE_OF_THE_HAND)
    bc2.play_card(0)
    assert bc2.player.special.get("wave_of_the_hand") == 2


def test_weave_damage_and_slot():
    bc = BattleContext(seed=831)
    m = bc.monsters.monsters[0]
    hp0 = m.hp
    setup_hand(bc, WEAVE)
    bc.play_card(0)
    assert m.hp == hp0 - 4
    assert bc.player.special.get("weave_recall") == 1


def test_weave_upgraded_6():
    bc = BattleContext(seed=832)
    m = bc.monsters.monsters[0]
    hp0 = m.hp
    setup_hand_upgraded(bc, WEAVE)
    bc.play_card(0)
    assert m.hp == hp0 - 6


def test_wheel_kick_damage_and_draw():
    bc = BattleContext(seed=833)
    m = bc.monsters.monsters[0]
    hp0 = m.hp
    fill_draw(bc, 3)
    setup_hand(bc, WHEEL_KICK)
    bc.play_card(0)
    assert m.hp == hp0 - 15
    assert len(bc.cards.hand) == 2


def test_wheel_kick_upgraded_20():
    bc = BattleContext(seed=834)
    m = bc.monsters.monsters[0]
    hp0 = m.hp
    setup_hand_upgraded(bc, WHEEL_KICK)
    bc.play_card(0)
    assert m.hp == hp0 - 20


def test_windmill_strike_damage_and_retain():
    bc = BattleContext(seed=835, deck=[STRIKE] * 10)
    m = bc.monsters.monsters[0]
    hp0 = m.hp
    setup_hand(bc, WINDMILL_STRIKE)
    bc.play_card(0)
    assert m.hp == hp0 - 7
    setup_hand(bc, WINDMILL_STRIKE)
    bc.end_turn()
    assert "Windmill Strike" in pile_names(bc, bc.cards.hand)


def test_windmill_strike_misc_data_bonus_counts():
    """保留增量缺引擎钩子（迁移报告）；misc_data 手动推进时 play 应计入。"""
    bc = BattleContext(seed=836)
    m = bc.monsters.monsters[0]
    hp0 = m.hp
    setup_hand(bc, WINDMILL_STRIKE)
    bc.cards.hand[0].misc_data = 8  # 两回合保留（+4/回合）
    bc.play_card(0)
    assert m.hp == hp0 - 15  # 7 + 8


def test_worship_five_mantra():
    bc = BattleContext(seed=837)
    setup_hand(bc, WORSHIP)
    bc.play_card(0)
    assert bc.player.statuses.get(PlayerStatus.MANTRA) == 5


def test_worship_upgraded_retains():
    bc = BattleContext(seed=838, deck=[STRIKE] * 10)
    setup_hand_upgraded(bc, WORSHIP)
    assert bc.cards.hand[0].is_retained  # retain_when_upgraded
    bc.end_turn()
    assert "Worship" in pile_names(bc, bc.cards.hand)


def test_worship_base_not_retained():
    bc = BattleContext(seed=839, deck=[STRIKE] * 10)
    setup_hand(bc, WORSHIP)
    assert not bc.cards.hand[0].is_retained
    bc.end_turn()
    assert "Worship" not in pile_names(bc, bc.cards.hand)


def test_wreath_of_flame_next_attack_bonus():
    bc = BattleContext(seed=840)
    m = bc.monsters.monsters[0]
    hp0 = m.hp
    setup_hand(bc, WREATH_OF_FLAME, STRIKE_W, STRIKE_W)
    bc.player.energy = 3
    bc.play_card(0)
    assert bc.player.statuses.get(PlayerStatus.VIGOR) == 5
    bc.play_card(0)
    assert m.hp == hp0 - 11  # 6 + 5
    assert not bc.player.statuses.has(PlayerStatus.VIGOR)  # 出伤后移除
    bc.play_card(0)
    assert m.hp == hp0 - 11 - 6  # 第二张攻击不再加成


def test_wreath_of_flame_upgraded_8():
    bc = BattleContext(seed=841)
    m = bc.monsters.monsters[0]
    hp0 = m.hp
    setup_hand(bc, WREATH_OF_FLAME, STRIKE_W)
    bc.cards.hand[0].upgraded = True  # 只升级焰环，打击保持基础版
    bc.player.energy = 2
    bc.play_card(0)
    bc.play_card(0)
    assert m.hp == hp0 - 14  # 6 + 8


# ---- 稀有 17 张 ----


def test_alpha_shuffles_beta():
    bc = BattleContext(seed=842)
    fill_draw(bc, 3)
    setup_hand(bc, ALPHA)
    bc.play_card(0)
    assert "Beta" in pile_names(bc, bc.cards.draw_pile)
    assert pile_names(bc, bc.cards.exhaust_pile) == ["Alpha"]
    assert ALPHA.innate_when_upgraded and not ALPHA.innate


def test_blasphemy_enters_divinity_gains_3_energy_and_dies_next_turn_slot():
    bc = BattleContext(seed=843)
    setup_hand(bc, BLASPHEMY)
    bc.player.energy = 1
    bc.play_card(0)
    assert bc.player.stance == Stance.DIVINITY
    assert bc.player.energy == 1 - 1 + 3  # Divinity 进入 +3（仿真）
    assert bc.player.special.get("blasphemy_die") == 1  # 下回合死亡槽位
    assert pile_names(bc, bc.cards.exhaust_pile) == ["Blasphemy"]


def test_blasphemy_upgraded_retains():
    bc = BattleContext(seed=844, deck=[STRIKE] * 10)
    setup_hand_upgraded(bc, BLASPHEMY)
    assert bc.cards.hand[0].is_retained
    bc.end_turn()
    assert "Blasphemy" in pile_names(bc, bc.cards.hand)


def test_brilliance_base_12():
    bc = BattleContext(seed=845)
    m = bc.monsters.monsters[0]
    hp0 = m.hp
    setup_hand(bc, BRILLIANCE)
    bc.play_card(0)
    assert m.hp == hp0 - 12


def test_brilliance_scales_with_mantra_gained():
    bc = BattleContext(seed=846)
    m = bc.monsters.monsters[0]
    hp0 = m.hp
    setup_hand(bc, PROSTRATE, BRILLIANCE)
    bc.player.energy = 2
    bc.play_card(0)  # +2 真言（内容层计数）
    bc.play_card(0)
    assert m.hp == hp0 - 14  # 12 + 2


def test_brilliance_upgraded_16():
    bc = BattleContext(seed=847)
    m = bc.monsters.monsters[0]
    hp0 = m.hp
    setup_hand_upgraded(bc, BRILLIANCE)
    bc.play_card(0)
    assert m.hp == hp0 - 16


def test_conjure_blade_shuffles_expunger():
    bc = BattleContext(seed=848)
    fill_draw(bc, 3)
    setup_hand(bc, CONJURE_BLADE)
    bc.player.energy = 2
    bc.play_card(0)
    expungers = [c for c in bc.cards.draw_pile if c.card is EXPUNGER]
    assert len(expungers) == 1
    assert expungers[0].misc_data == 2  # X = 2
    assert not expungers[0].upgraded
    assert pile_names(bc, bc.cards.exhaust_pile) == ["Conjure Blade"]
    # 打出该肃清者：9 × 2 = 18
    m = bc.monsters.monsters[0]
    hp0 = m.hp
    bc.cards.draw_pile.remove(expungers[0])
    bc.cards.hand.clear()
    bc.cards.hand.append(expungers[0])
    bc.player.energy = 1
    bc.play_card(0)
    assert m.hp == hp0 - 18


def test_conjure_blade_upgraded_x_plus_1():
    bc = BattleContext(seed=849)
    fill_draw(bc, 3)
    setup_hand_upgraded(bc, CONJURE_BLADE)
    bc.player.energy = 2
    bc.play_card(0)
    expungers = [c for c in bc.cards.draw_pile if c.card is EXPUNGER]
    assert expungers[0].misc_data == 3  # X + 1
    assert not expungers[0].upgraded  # 肃清者自身未升级（升级只改段数）


def test_deus_ex_machina_unplayable():
    bc = BattleContext(seed=850)
    setup_hand(bc, DEUS_EX_MACHINA)
    with pytest.raises(ValueError, match="不可打出"):
        bc.play_card(0)


def test_deus_ex_machina_on_draw_creates_miracles_and_exhausts():
    bc = BattleContext(seed=851)
    bc.cards.draw_pile.clear()
    d = bc.cards.instantiate(DEUS_EX_MACHINA)
    bc.cards.draw_pile.append(d)
    bc.cards.hand.clear()
    bc.add_to_bot(Actions.draw_cards(1))
    run_queue(bc)
    assert pile_names(bc, bc.cards.hand).count("Miracle") == 2
    assert pile_names(bc, bc.cards.exhaust_pile) == ["Deus Ex Machina"]


def test_deus_ex_machina_upgraded_3_miracles():
    bc = BattleContext(seed=852)
    bc.cards.draw_pile.clear()
    d = bc.cards.instantiate(DEUS_EX_MACHINA)
    d.upgraded = True
    bc.cards.draw_pile.append(d)
    bc.cards.hand.clear()
    bc.add_to_bot(Actions.draw_cards(1))
    run_queue(bc)
    assert pile_names(bc, bc.cards.hand).count("Miracle") == 3


def test_deva_form_ethereal_and_slot():
    bc = BattleContext(seed=853, deck=[STRIKE] * 10)
    setup_hand(bc, DEVA_FORM)
    bc.player.energy = 3
    bc.play_card(0)
    assert bc.player.special.get("deva_form") == 1
    # 虚无：在手过回合末 → 消散而非弃置
    setup_hand(bc, DEVA_FORM)
    bc.end_turn()
    assert "Deva Form" not in pile_names(bc, bc.cards.hand)
    assert "Deva Form" in pile_names(bc, bc.cards.exhaust_pile)


def test_devotion_mantra_per_turn():
    bc = BattleContext(seed=854, deck=[STRIKE] * 10)
    setup_hand(bc, DEVOTION)
    bc.play_card(0)
    assert bc.player.statuses.get(PlayerStatus.DEVOTION) == 2
    bc.end_turn()
    assert bc.player.statuses.get(PlayerStatus.MANTRA) == 2
    bc.end_turn()
    assert bc.player.statuses.get(PlayerStatus.MANTRA) == 4


def test_devotion_upgraded_3_mantra():
    bc = BattleContext(seed=855, deck=[STRIKE] * 10)
    setup_hand_upgraded(bc, DEVOTION)
    bc.play_card(0)
    assert bc.player.statuses.get(PlayerStatus.DEVOTION) == 3
    bc.end_turn()
    assert bc.player.statuses.get(PlayerStatus.MANTRA) == 3


def test_establishment_slot_and_innate_when_upgraded():
    bc = BattleContext(seed=856)
    setup_hand(bc, ESTABLISHMENT)
    bc.play_card(0)
    assert bc.player.special.get("establishment") == 1
    assert ESTABLISHMENT.innate_when_upgraded and not ESTABLISHMENT.innate


def test_judgment_kills_low_hp_enemy():
    bc = BattleContext(seed=857)
    m = bc.monsters.monsters[0]
    m.hp = 30
    setup_hand(bc, JUDGMENT)
    bc.play_card(0)
    assert bc.outcome == Outcome.PLAYER_VICTORY
    assert m.hp == 0


def test_judgment_no_effect_above_threshold():
    bc = BattleContext(seed=858)
    m = bc.monsters.monsters[0]
    m.hp = 31
    setup_hand(bc, JUDGMENT)
    bc.play_card(0)
    assert m.hp == 31
    assert bc.outcome == Outcome.UNDECIDED


def test_judgment_upgraded_40():
    bc = BattleContext(seed=859)
    m = bc.monsters.monsters[0]
    m.hp = 40
    setup_hand_upgraded(bc, JUDGMENT)
    bc.play_card(0)
    assert bc.outcome == Outcome.PLAYER_VICTORY


def test_lesson_learned_fatal_upgrades_random_card():
    bc = BattleContext(seed=860)
    m = bc.monsters.monsters[0]
    m.hp = 10
    fill_draw(bc, 6, STRIKE_W)
    setup_hand(bc, LESSON_LEARNED)
    bc.player.energy = 2
    bc.play_card(0)
    assert bc.outcome == Outcome.PLAYER_VICTORY
    upgraded = [c for c in bc.cards.draw_pile if c.upgraded]
    assert len(upgraded) == 1  # 战斗内近似：随机升级一张在堆牌
    assert pile_names(bc, bc.cards.exhaust_pile) == ["Lesson Learned"]


def test_lesson_learned_non_fatal_no_upgrade():
    bc = BattleContext(seed=861)
    m = bc.monsters.monsters[0]
    hp0 = m.hp
    fill_draw(bc, 6, STRIKE_W)
    setup_hand(bc, LESSON_LEARNED)
    bc.player.energy = 2
    bc.play_card(0)
    assert m.hp == hp0 - 10
    assert not any(c.upgraded for c in bc.cards.draw_pile)


def test_master_reality_upgrades_created_cards():
    bc = BattleContext(seed=862)
    setup_hand(bc, MASTER_REALITY, EVALUATE)
    bc.player.energy = 2
    bc.play_card(0)
    assert bc.player.special.get("master_reality") == 1
    fill_draw(bc, 3)
    bc.play_card(0)  # Evaluate 洗入的洞见应为升级版
    insights = [c for c in bc.cards.draw_pile if c.card is INSIGHT]
    assert len(insights) == 1
    assert insights[0].upgraded


def test_master_reality_upgraded_cost_0():
    bc = BattleContext(seed=863)
    setup_hand_upgraded(bc, MASTER_REALITY)
    bc.player.energy = 0
    bc.play_card(0)
    assert bc.player.special.get("master_reality") == 1


def test_omniscience_plays_chosen_twice_and_exhausts_it():
    bc = BattleContext(seed=864, deck=[STRIKE] * 10)
    m = bc.monsters.monsters[0]
    hp0 = m.hp
    bc.cards.draw_pile.clear()
    bc.cards.draw_pile.append(bc.cards.instantiate(WOUND))
    s = bc.cards.instantiate(STRIKE_W)
    bc.cards.draw_pile.append(s)  # 堆顶
    setup_hand(bc, OMNISCIENCE)
    bc.player.energy = 4
    bc.play_card(0)
    assert bc.input_state == InputState.CARD_SELECT
    bc.choose_card(1)  # 选打击
    assert m.hp == hp0 - 12  # 打出两次
    assert "Omniscience" in pile_names(bc, bc.cards.exhaust_pile)
    assert "Strike" in pile_names(bc, bc.cards.exhaust_pile)  # 该牌被消耗
    assert "Strike" not in pile_names(bc, bc.cards.discard_pile)


def test_omniscience_upgraded_costs_3():
    bc = BattleContext(seed=865, deck=[STRIKE] * 10)
    bc.cards.draw_pile.clear()
    bc.cards.draw_pile.append(bc.cards.instantiate(STRIKE_W))
    setup_hand_upgraded(bc, OMNISCIENCE)
    bc.player.energy = 3
    bc.play_card(0)
    # 单候选直执（open_card_select 内建）
    assert "Strike" in pile_names(bc, bc.cards.exhaust_pile)


def test_ragnarok_5_hits_5_damage_single_enemy():
    bc = BattleContext(seed=866)
    m = bc.monsters.monsters[0]
    hp0 = m.hp
    setup_hand(bc, RAGNAROK)
    bc.player.energy = 3
    bc.play_card(0)
    assert m.hp == hp0 - 25


def test_ragnarok_upgraded_6_hits_6_damage():
    bc = BattleContext(seed=867)
    m = bc.monsters.monsters[0]
    hp0 = m.hp
    setup_hand_upgraded(bc, RAGNAROK)
    bc.player.energy = 3
    bc.play_card(0)
    assert m.hp == hp0 - 36


def test_scrawl_draws_until_hand_full():
    bc = BattleContext(seed=868)
    fill_draw(bc, 10)
    setup_hand(bc, SCRAWL)
    bc.play_card(0)
    assert len(bc.cards.hand) == MAX_HAND_SIZE
    assert pile_names(bc, bc.cards.exhaust_pile) == ["Scrawl"]


def test_scrawl_upgraded_costs_0():
    bc = BattleContext(seed=869)
    fill_draw(bc, 10)
    setup_hand_upgraded(bc, SCRAWL)
    bc.player.energy = 0
    bc.play_card(0)
    assert len(bc.cards.hand) == MAX_HAND_SIZE


def test_spirit_shield_block_per_hand_card():
    bc = BattleContext(seed=870)
    setup_hand(bc, DEFEND_W, DEFEND_W, DEFEND_W, SPIRIT_SHIELD)
    bc.player.energy = 2
    bc.play_card(3)
    assert bc.player.block == 9  # 3 张手牌 × 3（自身已离手不计）


def test_spirit_shield_upgraded_4_each():
    bc = BattleContext(seed=871)
    setup_hand(bc, DEFEND_W, DEFEND_W, DEFEND_W, SPIRIT_SHIELD)
    bc.cards.hand[3].upgraded = True
    bc.player.energy = 2
    bc.play_card(3)
    assert bc.player.block == 12


def test_vault_takes_extra_turn_skipping_enemy_phase():
    """降级实现：结束本回合 + 跳过敌方阶段 = 额外回合（差异见迁移报告）。"""
    bc = BattleContext(seed=872, deck=[STRIKE] * 10)
    m = bc.monsters.monsters[0]
    setup_hand(bc, VAULT)
    bc.play_card(0)
    assert bc.turn == 2
    assert len(bc.cards.hand) == 5  # 额外回合重抽
    assert bc.player.energy == 3  # 额外回合回能
    assert m.turns_taken == 0  # 敌方未行动
    assert bc.outcome == Outcome.UNDECIDED
    assert pile_names(bc, bc.cards.exhaust_pile) == ["Vault"]


def test_vault_upgraded_costs_2():
    bc = BattleContext(seed=873, deck=[STRIKE] * 10)
    setup_hand_upgraded(bc, VAULT)
    bc.player.energy = 2
    bc.play_card(0)
    assert bc.turn == 2


def test_wish_plated_armor_option():
    bc = BattleContext(seed=874)
    setup_hand(bc, WISH)
    bc.play_card(0)
    assert bc.input_state == InputState.CARD_SELECT
    bc.choose_card(0)  # Live Forever
    assert bc.player.statuses.get(PlayerStatus.PLATED_ARMOR) == 6
    assert pile_names(bc, bc.cards.exhaust_pile) == ["Wish"]


def test_wish_strength_option():
    bc = BattleContext(seed=875)
    setup_hand(bc, WISH)
    bc.play_card(0)
    bc.choose_card(1)  # Become Almighty
    assert bc.player.statuses.get(PlayerStatus.STRENGTH) == 3


def test_wish_gold_option():
    bc = BattleContext(seed=876)
    setup_hand(bc, WISH)
    gold0 = bc.player.gold
    bc.play_card(0)
    bc.choose_card(2)  # Fame and Fortune
    assert bc.player.gold == gold0 + 25


def test_wish_upgraded_values():
    bc = BattleContext(seed=877)
    setup_hand_upgraded(bc, WISH)
    bc.play_card(0)
    bc.choose_card(0)
    assert bc.player.statuses.get(PlayerStatus.PLATED_ARMOR) == 8


# ---- 内容层仿真与已知缺口的边界 ----


def test_wrath_double_damage_taken():
    """WRATH 姿态承伤 ×2（引擎 attacked 乘区已接，wiki Keywords#Stance）。"""
    bc = BattleContext(seed=878, deck=[STRIKE] * 10)
    m = bc.monsters.monsters[0]
    m.set_move(Cultist.DARK_STRIKE)
    bc.player.change_stance(bc, Stance.WRATH)
    bc.end_turn()
    assert bc.player.hp == 80 - 12  # 6 × 2


def test_flurry_not_recalled_on_same_stance_change():
    bc = BattleContext(seed=879, deck=[STRIKE] * 10)
    setup_hand(bc, FLURRY_OF_BLOWS, TRANQUILITY, TRANQUILITY)
    bc.play_card(0)
    bc.player.change_stance(bc, Stance.CALM)
    bc.player.energy = 2
    bc.play_card(0)  # Calm → Calm：no-op
    assert "Flurry of Blows" not in pile_names(bc, bc.cards.hand)

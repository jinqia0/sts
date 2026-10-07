"""Defect 全卡移植断言（数值/结算以 slaythespire.wiki.gg 逐卡页为权威源，
Cards.h 交叉校验费用/消耗/固有/X 费位）。

逐卡至少 1 用例 + 升级分支；构造模式沿用 test_watcher_cards.py
（setup_hand / fill_draw / add_cultist，出牌序列确定、不依赖初始洗牌）。

三类接线状态分层断言（详见 cards/defect.py 模块注释）：
- 引擎已接（充能球全套/EQUILIBRIUM/next_turn_energy/DRAW_REDUCTION 负层/
  CARD_SELECT/X 费快照/静态消耗位）：全流程断言；
- 槽位落地 + 引擎接线需求（REBOUND 触发/LOCK_ON 乘区/bias_focus/
  hello_world/creative_ai/storm/heatsinks/amplify/echo_form/buffer/
  self_repair/本场引导计数的内容层入口）：只断言槽位/状态落地；
- 引擎已知偏差（STATIC_DISCHARGE 恒 1 个/LOOP 仅 FROST/ECHO_FORM 升级版
  误虚无）：按引擎实际行为断言或仅断言数据位，偏差记录在迁移报告。
"""

import subprocess
import sys

from sts.combat import BattleContext
from sts.combat.actions import Actions
from sts.combat.card_manager import MAX_HAND_SIZE
from sts.combat.types import InputState, MonsterStatus, Orb, Outcome, PlayerStatus
from sts.content.cards import BURN, CardDef, STRIKE, VOID
from sts.content.cards.defect import (
    AGGREGATE,
    ALL_FOR_ONE,
    AMPLIFY,
    AUTO_SHIELDS,
    BALL_LIGHTNING,
    BARRAGE,
    BEAM_CELL,
    BIASED_COGNITION,
    BLIZZARD,
    BOOT_SEQUENCE,
    BUFFER,
    BULLSEYE,
    CAPACITOR,
    CHAOS,
    CHARGE_BATTERY,
    CHILL,
    CLAW,
    COLD_SNAP,
    COMPILE_DRIVER,
    CONSUME,
    COOLHEADED,
    CORE_SURGE,
    CREATIVE_AI,
    DARKNESS,
    DEFEND_D,
    DEFRAGMENT,
    DOOM_AND_GLOOM,
    DOUBLE_ENERGY,
    DUALCAST,
    ECHO_FORM,
    ELECTRODYNAMICS,
    EQUILIBRIUM,
    FISSION,
    FORCE_FIELD,
    FTL,
    FUSION,
    GENETIC_ALGORITHM,
    GLACIER,
    GO_FOR_THE_EYES,
    HEATSINKS,
    HELLO_WORLD,
    HOLOGRAM,
    HYPERBEAM,
    LEAP,
    LOOP,
    MACHINE_LEARNING,
    MELTER,
    METEOR_STRIKE,
    MULTI_CAST,
    OVERCLOCK,
    RAINBOW,
    REBOOT,
    REBOUND,
    RECYCLE,
    RECURSION,
    REINFORCED_BODY,
    REPROGRAM,
    RIP_AND_TEAR,
    SCRAPE,
    SEEK,
    SELF_REPAIR,
    SKIM,
    STACK,
    STATIC_DISCHARGE,
    STEAM_BARRIER,
    STORM,
    STREAMLINE,
    STRIKE_D,
    SUNDER,
    SWEEPING_BEAM,
    TEMPEST,
    THUNDER_STRIKE,
    TURBO,
    WHITE_NOISE,
    ZAP,
)
from sts.content.monsters import Cultist

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


def add_upgraded(bc: BattleContext, *cards) -> None:
    """向现有手牌追加升级实例（不清空，用于基础/升级混排出牌序列）。"""
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


def to_discard(bc: BattleContext, *cards) -> None:
    for c in cards:
        bc.cards.discard_pile.append(bc.cards.instantiate(c))


# ---- re-export 与导入顺序 ----


def test_defect_reexport_via_cards_module():
    import sts.content.cards as cards_mod
    import sts.content.cards.defect as d

    assert cards_mod.ZAP is d.ZAP
    assert cards_mod.METEOR_STRIKE is d.METEOR_STRIKE
    # 与其他职业的 Strike/Defend 不同对象，卡名刻意同名（观测词表按 "模块:常量名" 身份区分）
    assert cards_mod.STRIKE_D is d.STRIKE_D
    assert cards_mod.STRIKE_D.name == "Strike"
    assert cards_mod.STRIKE_D is not cards_mod.STRIKE


def test_defect_first_import_order_keeps_reexport():
    """cards.defect 被先行导入时，包根 eager re-export 仍可用。"""
    code = (
        "import sts.content.cards.defect as d; "
        "from sts.content import cards; "
        "assert cards.ZAP is d.ZAP; "
        "from sts.content.cards import REGRET; "
        "from sts.content.cards import SHIV; "
        "from sts.content.cards import ERUPTION"
    )
    subprocess.run([sys.executable, "-c", code], check=True, timeout=60)


def test_defect_card_count():
    """wiki 口径：4 基础 + 18 普通 + 36 非普通 + 17 稀有 = 75 个 CardDef
    （本模块另自 cards.py 导入 BURN/VOID 两个状态卡模板，不计入）。"""
    import sts.content.cards.defect as d

    own = {n: g for n, g in vars(d).items()
           if isinstance(g, CardDef) and g not in (BURN, VOID)}
    assert len(own) == 75
    assert len(d.__all__) == 75
    assert set(d.__all__) == set(own)


def test_defect_flags_per_cards_h():
    """Cards.h 数据位交叉校验：消耗 / 固有（升级版）/ X 费 / 升级改费。"""
    exhaust_set = {
        BOOT_SEQUENCE, CHILL, DOUBLE_ENERGY, GENETIC_ALGORITHM, TEMPEST,
        WHITE_NOISE, CORE_SURGE, FISSION, REBOOT, SEEK,
    }
    for card in exhaust_set:
        assert card.exhausts, card.name
    for card in (TURBO, AGGREGATE, SKIM, CHAOS, RECYCLE, LOOP, REBOUND, STACK):
        assert not card.exhausts, card.name
    # 仅基础版消耗（play 内覆盖，Cards.h doesCardExhaust 的 !upgraded 分支）
    for card in (HOLOGRAM, RAINBOW):
        assert not card.exhausts, card.name
    assert BOOT_SEQUENCE.innate and not BOOT_SEQUENCE.innate_when_upgraded
    for card in (CHILL, HELLO_WORLD, STORM, MACHINE_LEARNING):
        assert card.innate_when_upgraded and not card.innate, card.name
    for card in (TEMPEST, MULTI_CAST, REINFORCED_BODY):
        assert card.x_cost and card.cost == -1, card.name
    for card in (ZAP, DUALCAST, RECURSION, DOUBLE_ENERGY, RECYCLE, WHITE_NOISE):
        assert card.upgraded_cost == 0, card.name
    assert FUSION.upgraded_cost == 1 and FUSION.cost == 2
    assert CREATIVE_AI.upgraded_cost == 2 and CREATIVE_AI.cost == 3
    assert METEOR_STRIKE.cost == 5 and METEOR_STRIKE.upgraded_cost is None
    assert FORCE_FIELD.cost == 4 and FORCE_FIELD.upgraded_cost is None
    assert ECHO_FORM.ethereal
    # 无保留位（Cards.h doesCardSelfRetain 无 Defect 卡）与虚无（仅 ECHO_FORM）
    for g in vars(sys.modules["sts.content.cards.defect"]).values():
        if isinstance(g, CardDef) and g not in (BURN, VOID):
            assert not g.self_retain, g.name
            assert g.ethereal is (g is ECHO_FORM), g.name


# ---- 基础 4 张 ----


def test_strike_d_deals_6():
    bc = BattleContext(seed=800)
    m = bc.monsters.monsters[0]
    hp0 = m.hp
    setup_hand(bc, STRIKE_D)
    bc.play_card(0)
    assert m.hp == hp0 - 6


def test_strike_d_upgraded_deals_9():
    bc = BattleContext(seed=801)
    m = bc.monsters.monsters[0]
    hp0 = m.hp
    setup_hand_upgraded(bc, STRIKE_D)
    bc.play_card(0)
    assert m.hp == hp0 - 9


def test_defend_d_gains_5_block():
    bc = BattleContext(seed=802)
    setup_hand(bc, DEFEND_D)
    bc.play_card(0)
    assert bc.player.block == 5


def test_defend_d_upgraded_gains_8():
    bc = BattleContext(seed=803)
    setup_hand_upgraded(bc, DEFEND_D)
    bc.play_card(0)
    assert bc.player.block == 8


def test_zap_channels_lightning():
    bc = BattleContext(seed=804)
    setup_hand(bc, ZAP)
    bc.play_card(0)
    assert bc.player.orbs == [Orb.LIGHTNING]
    assert bc.player.special.get("chan_lightning") == 1


def test_zap_upgraded_costs_0():
    bc = BattleContext(seed=805)
    setup_hand_upgraded(bc, ZAP)
    bc.player.energy = 1
    bc.play_card(0)
    assert bc.player.energy == 1
    assert bc.player.orbs == [Orb.LIGHTNING]


def test_dualcast_evoke_twice():
    """2 个球时双重施法：唤起 2 次（闪电 3 伤 + 冰球 2 格挡）。"""
    bc = BattleContext(seed=806)
    m = bc.monsters.monsters[0]
    hp0 = m.hp
    setup_hand(bc, ZAP, COOLHEADED, DUALCAST)
    bc.player.energy = 9
    bc.play_card(0)
    bc.play_card(0)
    bc.play_card(0)
    assert bc.player.orbs == []
    assert m.hp == hp0 - 3
    assert bc.player.block == 2


def test_dualcast_single_orb_second_evoke_noop():
    """仅 1 个球：首唤起生效，第二次无球空转。"""
    bc = BattleContext(seed=806)
    m = bc.monsters.monsters[0]
    hp0 = m.hp
    setup_hand(bc, ZAP, DUALCAST)
    bc.player.energy = 9
    bc.play_card(0)
    bc.play_card(0)
    assert bc.player.orbs == []
    assert m.hp == hp0 - 3
    assert bc.player.block == 0


def test_dualcast_upgraded_costs_0_and_empty_orbs_noop():
    bc = BattleContext(seed=807)
    setup_hand_upgraded(bc, DUALCAST)
    bc.player.energy = 1
    bc.play_card(0)
    assert bc.player.energy == 1  # 0 费且无球空转


# ---- 普通 18 张 ----


def test_ball_lightning_damage_and_channel():
    bc = BattleContext(seed=810)
    m = bc.monsters.monsters[0]
    hp0 = m.hp
    setup_hand(bc, BALL_LIGHTNING)
    bc.play_card(0)
    assert m.hp == hp0 - 7
    assert bc.player.orbs == [Orb.LIGHTNING]


def test_ball_lightning_upgraded_10():
    bc = BattleContext(seed=811)
    m = bc.monsters.monsters[0]
    hp0 = m.hp
    setup_hand_upgraded(bc, BALL_LIGHTNING)
    bc.play_card(0)
    assert m.hp == hp0 - 10


def test_barrage_damage_per_orb():
    """2 个球 = 单段 4×2 = 8 伤（力量计入一次）。"""
    bc = BattleContext(seed=812)
    m = bc.monsters.monsters[0]
    hp0 = m.hp
    setup_hand(bc, ZAP, COOLHEADED, BARRAGE)
    bc.player.energy = 9
    bc.play_card(0)
    bc.play_card(0)
    bc.play_card(0)
    assert len(bc.player.orbs) == 2
    assert m.hp == hp0 - 8
    # 升级版每球 6
    bc2 = BattleContext(seed=812)
    m2 = bc2.monsters.monsters[0]
    hp1 = m2.hp
    setup_hand(bc2, ZAP, COOLHEADED)
    add_upgraded(bc2, BARRAGE)
    bc2.player.energy = 9
    bc2.play_card(0)
    bc2.play_card(0)
    bc2.play_card(0)
    assert m2.hp == hp1 - 12


def test_beam_cell_damage_and_vulnerable():
    bc = BattleContext(seed=813)
    m = bc.monsters.monsters[0]
    hp0 = m.hp
    setup_hand(bc, BEAM_CELL)
    bc.play_card(0)
    assert m.hp == hp0 - 3
    assert m.statuses.get(MonsterStatus.VULNERABLE) == 1
    # 升级：4 伤 2 层
    bc2 = BattleContext(seed=813)
    m2 = bc2.monsters.monsters[0]
    hp1 = m2.hp
    setup_hand_upgraded(bc2, BEAM_CELL)
    bc2.play_card(0)
    assert m2.hp == hp1 - 4
    assert m2.statuses.get(MonsterStatus.VULNERABLE) == 2


def test_charge_battery_block_and_next_turn_energy():
    bc = BattleContext(seed=814, deck=[STRIKE] * 10)
    fill_draw(bc, 10)
    setup_hand(bc, CHARGE_BATTERY)
    bc.play_card(0)
    assert bc.player.block == 7
    assert bc.player.special.get("next_turn_energy") == 1
    bc.end_turn()  # 邪教徒首回合咒语不攻击
    assert bc.player.energy == 4  # 3 基础 + 1（引擎 next_turn_energy 已接）
    assert bc.player.block == 0  # 回合开始格挡衰减（无 BARRICADE）
    # 升级 10 格挡
    bc2 = BattleContext(seed=814)
    setup_hand_upgraded(bc2, CHARGE_BATTERY)
    bc2.play_card(0)
    assert bc2.player.block == 10


def test_claw_global_scaling():
    """两张爪击依次打出：3 伤 → 3+2=5 伤（ALL Claw cards 共享 +2）。"""
    bc = BattleContext(seed=815)
    m = bc.monsters.monsters[0]
    hp0 = m.hp
    setup_hand(bc, CLAW, CLAW)
    bc.play_card(0)
    assert m.hp == hp0 - 3
    assert bc.player.special.get("claw_bonus") == 2
    bc.play_card(0)
    assert m.hp == hp0 - 8


def test_cold_snap_damage_and_frost():
    bc = BattleContext(seed=816)
    m = bc.monsters.monsters[0]
    hp0 = m.hp
    setup_hand(bc, COLD_SNAP)
    bc.play_card(0)
    assert m.hp == hp0 - 6
    assert bc.player.orbs == [Orb.FROST]
    assert bc.player.special.get("chan_frost") == 1


def test_compile_driver_draw_per_unique_orb():
    bc = BattleContext(seed=817)
    m = bc.monsters.monsters[0]
    hp0 = m.hp
    fill_draw(bc, 10)
    setup_hand(bc, ZAP, COOLHEADED, COMPILE_DRIVER)
    bc.player.energy = 9
    bc.play_card(0)
    bc.play_card(0)
    assert len(set(bc.player.orbs)) == 2
    bc.play_card(0)
    assert m.hp == hp0 - 7
    assert len(bc.cards.hand) == 3  # 1（冷静）+ 2（两类型球）


def test_coolheaded_channel_and_draw():
    bc = BattleContext(seed=818)
    fill_draw(bc, 10)
    setup_hand(bc, COOLHEADED)
    bc.play_card(0)
    assert bc.player.orbs == [Orb.FROST]
    assert len(bc.cards.hand) == 1
    # 升级抽 2
    bc2 = BattleContext(seed=818)
    fill_draw(bc2, 10)
    setup_hand_upgraded(bc2, COOLHEADED)
    bc2.play_card(0)
    assert len(bc2.cards.hand) == 2


def test_go_for_the_eyes_weak_only_on_attack_intent():
    bc = BattleContext(seed=819)
    m = bc.monsters.monsters[0]
    hp0 = m.hp
    setup_hand(bc, GO_FOR_THE_EYES)
    bc.play_card(0)
    assert m.hp == hp0 - 3
    assert not m.statuses.has(MonsterStatus.WEAK)  # 首回合咒语（非攻击意图）
    bc2 = BattleContext(seed=819)
    m2 = bc2.monsters.monsters[0]
    hp1 = m2.hp
    m2.set_move(Cultist.DARK_STRIKE)
    setup_hand(bc2, GO_FOR_THE_EYES)
    bc2.play_card(0)
    assert m2.hp == hp1 - 3
    assert m2.statuses.get(MonsterStatus.WEAK) == 1


def test_go_for_the_eyes_upgraded_4_damage_2_weak():
    bc = BattleContext(seed=820)
    m = bc.monsters.monsters[0]
    hp0 = m.hp
    m.set_move(Cultist.DARK_STRIKE)
    setup_hand_upgraded(bc, GO_FOR_THE_EYES)
    bc.play_card(0)
    assert m.hp == hp0 - 4
    assert m.statuses.get(MonsterStatus.WEAK) == 2


def test_hologram_returns_discard_card():
    bc = BattleContext(seed=821)
    to_discard(bc, STRIKE_D, DEFEND_D)
    setup_hand(bc, HOLOGRAM)
    bc.play_card(0)
    assert bc.player.block == 3
    assert bc.input_state == InputState.CARD_SELECT
    assert len(bc.card_select_info.candidates) == 2
    bc.choose_card(1)  # 选防御
    assert pile_names(bc, bc.cards.hand) == ["Defend"]
    assert pile_names(bc, bc.cards.discard_pile) == ["Strike"]
    assert pile_names(bc, bc.cards.exhaust_pile) == ["Hologram"]  # 基础版消耗


def test_hologram_upgraded_no_exhaust_5_block():
    bc = BattleContext(seed=822)
    to_discard(bc, STRIKE_D)
    setup_hand_upgraded(bc, HOLOGRAM)
    bc.play_card(0)
    # 单候选直执（引擎 open_card_select 内建）
    assert pile_names(bc, bc.cards.hand) == ["Strike"]
    assert bc.player.block == 5
    assert pile_names(bc, bc.cards.exhaust_pile) == []
    assert pile_names(bc, bc.cards.discard_pile) == ["Hologram"]


def test_leap_block():
    bc = BattleContext(seed=823)
    setup_hand(bc, LEAP)
    bc.play_card(0)
    assert bc.player.block == 9
    setup_hand_upgraded(bc, LEAP)
    bc.player.block = 0
    bc.play_card(0)
    assert bc.player.block == 12


def test_rebound_damage_and_status():
    """REBOUND 状态落地（触发段引擎接线待接，见迁移报告）。"""
    bc = BattleContext(seed=824)
    m = bc.monsters.monsters[0]
    hp0 = m.hp
    setup_hand(bc, REBOUND)
    bc.play_card(0)
    assert m.hp == hp0 - 9
    assert bc.player.statuses.get(PlayerStatus.REBOUND) == 1
    setup_hand_upgraded(bc, REBOUND)
    bc.play_card(0)
    assert m.hp == hp0 - 9 - 12


def test_recursion_evoke_and_channel_copy():
    """暗球存层随副本保留（wiki Synergies：built up damage carried over）。"""
    bc = BattleContext(seed=825, deck=[STRIKE] * 10)
    fill_draw(bc, 10)
    setup_hand(bc, DARKNESS)
    bc.play_card(0)
    bc.end_turn()  # 回合结束暗球 passive：+6 存层
    assert bc.player.dark_stacks == 6
    m = bc.monsters.monsters[0]
    hp0 = m.hp
    setup_hand(bc, RECURSION)
    bc.play_card(0)
    assert bc.player.orbs == [Orb.DARK]
    assert bc.player.dark_stacks == 6  # 副本存层回填
    assert m.hp == hp0 - 36  # 唤起：6×6 存层


def test_recursion_empty_orbs_noop_and_upgraded_cost():
    bc = BattleContext(seed=826)
    setup_hand_upgraded(bc, RECURSION)
    bc.player.energy = 1
    bc.play_card(0)
    assert bc.player.energy == 1  # 0 费、无球空转


def test_stack_block_equals_discard_count():
    bc = BattleContext(seed=827)
    to_discard(bc, STRIKE_D, STRIKE_D, STRIKE_D, STRIKE_D)
    setup_hand(bc, STACK)
    bc.play_card(0)
    # Stack 打出时自身尚未落弃牌堆（wiki Order 节不计自身），4 张 = 4 格挡
    assert bc.player.block == 4
    assert len(bc.cards.discard_pile) == 5  # 结算后自身落堆


def test_stack_upgraded_plus_3():
    bc = BattleContext(seed=828)
    to_discard(bc, STRIKE_D)
    setup_hand_upgraded(bc, STACK)
    bc.play_card(0)
    assert bc.player.block == 4  # 1 + 3


def test_steam_barrier_decreasing_block():
    """每实例独立计数：同一张连打两次 6 → 6-1（本体"此牌"= 该张拷贝）。"""
    bc = BattleContext(seed=829)
    setup_hand(bc, STEAM_BARRIER)
    bc.play_card(0)
    assert bc.player.block == 6
    inst = bc.cards.discard_pile.pop()  # 同一实例回手再打
    bc.cards.hand.append(inst)
    bc.play_card(0)
    assert bc.player.block == 6 + 5
    # 两张不同拷贝各自从满额开始
    bc2 = BattleContext(seed=829)
    setup_hand(bc2, STEAM_BARRIER, STEAM_BARRIER)
    bc2.play_card(0)
    bc2.play_card(0)
    assert bc2.player.block == 12
    setup_hand_upgraded(bc2, STEAM_BARRIER)
    bc2.play_card(0)
    assert bc2.player.block == 12 + 8


def test_streamline_cost_reduction():
    bc = BattleContext(seed=830)
    m = bc.monsters.monsters[0]
    hp0 = m.hp
    setup_hand(bc, STREAMLINE)
    bc.player.energy = 9
    bc.play_card(0)
    assert m.hp == hp0 - 15
    inst = bc.cards.discard_pile[-1]
    assert inst.cost == 1  # 2-1：本场永久减费
    # 升级 20 伤
    bc2 = BattleContext(seed=830)
    m2 = bc2.monsters.monsters[0]
    hp1 = m2.hp
    setup_hand_upgraded(bc2, STREAMLINE)
    bc2.player.energy = 9
    bc2.play_card(0)
    assert m2.hp == hp1 - 20


def test_sweeping_beam_aoe_and_draw():
    bc = BattleContext(seed=831)
    add_cultist(bc, idx=1)
    m1, m2 = bc.monsters.monsters
    hp1, hp2 = m1.hp, m2.hp
    fill_draw(bc, 10)
    setup_hand(bc, SWEEPING_BEAM)
    bc.play_card(0)
    assert m1.hp == hp1 - 6 and m2.hp == hp2 - 6
    assert len(bc.cards.hand) == 1


def test_sweeping_beam_upgraded_9():
    bc = BattleContext(seed=832)
    m = bc.monsters.monsters[0]
    hp0 = m.hp
    setup_hand_upgraded(bc, SWEEPING_BEAM)
    bc.play_card(0)
    assert m.hp == hp0 - 9


def test_turbo_energy_and_void():
    bc = BattleContext(seed=833)
    setup_hand(bc, TURBO)
    bc.player.energy = 3
    bc.play_card(0)
    assert bc.player.energy == 5  # 3 - 0 + 2
    # 不消耗：效果动作（Void 落弃牌堆）先于出牌收尾，自身最后落堆
    #（对齐本体 UseCardAction 晚于 MakeTempCardInDiscardAction）
    assert pile_names(bc, bc.cards.discard_pile) == ["Void", "TURBO"]
    assert bc.cards.discard_pile[0].card is VOID
    assert pile_names(bc, bc.cards.exhaust_pile) == []


def test_turbo_upgraded_3_energy():
    bc = BattleContext(seed=834)
    setup_hand_upgraded(bc, TURBO)
    bc.play_card(0)
    assert bc.player.energy == 6  # 3 + 3
    assert pile_names(bc, bc.cards.discard_pile) == ["Void", "TURBO"]


# ---- 非普通 36 张 ----


def test_aggregate_energy_per_4_cards():
    bc = BattleContext(seed=840)
    fill_draw(bc, 12)
    setup_hand(bc, AGGREGATE)
    bc.player.energy = 3
    bc.play_card(0)
    assert bc.player.energy == 3 - 1 + 3
    # 升级每 3 张：12//3 = 4
    bc2 = BattleContext(seed=840)
    fill_draw(bc2, 12)
    setup_hand_upgraded(bc2, AGGREGATE)
    bc2.player.energy = 3
    bc2.play_card(0)
    assert bc2.player.energy == 3 - 1 + 4


def test_auto_shields_only_without_block():
    bc = BattleContext(seed=841)
    setup_hand(bc, AUTO_SHIELDS)
    bc.play_card(0)
    assert bc.player.block == 11
    bc2 = BattleContext(seed=841)
    bc2.player.block = 5
    setup_hand(bc2, AUTO_SHIELDS)
    bc2.play_card(0)
    assert bc2.player.block == 5  # 已有格挡无效果
    # 升级 15
    bc3 = BattleContext(seed=841)
    setup_hand_upgraded(bc3, AUTO_SHIELDS)
    bc3.play_card(0)
    assert bc3.player.block == 15


def test_blizzard_damage_per_frost_channeled():
    bc = BattleContext(seed=842)
    m = bc.monsters.monsters[0]
    hp0 = m.hp
    setup_hand(bc, GLACIER, COOLHEADED, BLIZZARD)
    bc.player.energy = 9
    bc.play_card(0)  # 2 冰
    bc.play_card(0)  # 1 冰
    assert bc.player.special.get("chan_frost") == 3
    bc.play_card(0)
    assert m.hp == hp0 - 6  # 2 × 3 冰，单段大攻击
    # 升级 3 倍
    bc2 = BattleContext(seed=842)
    m2 = bc2.monsters.monsters[0]
    hp1 = m2.hp
    setup_hand(bc2, GLACIER)
    add_upgraded(bc2, BLIZZARD)
    bc2.player.energy = 9
    bc2.play_card(0)
    bc2.play_card(0)
    assert m2.hp == hp1 - 6  # 3 × 2 冰


def test_boot_sequence_innate_block_exhaust():
    bc = BattleContext(seed=843, deck=[BOOT_SEQUENCE] + [STRIKE_D] * 9)
    assert "Boot Sequence" in pile_names(bc, bc.cards.hand)  # 固有：开局必在手
    idx = pile_names(bc, bc.cards.hand).index("Boot Sequence")
    bc.play_card(idx)
    assert bc.player.block == 10
    assert pile_names(bc, bc.cards.exhaust_pile) == ["Boot Sequence"]


def test_boot_sequence_upgraded_13():
    bc = BattleContext(seed=844, deck=[STRIKE_D] * 10)
    setup_hand_upgraded(bc, BOOT_SEQUENCE)
    bc.play_card(0)
    assert bc.player.block == 13


def test_bullseye_lock_on():
    bc = BattleContext(seed=845)
    m = bc.monsters.monsters[0]
    hp0 = m.hp
    setup_hand(bc, BULLSEYE)
    bc.play_card(0)
    assert m.hp == hp0 - 8
    assert m.statuses.get(MonsterStatus.LOCK_ON) == 2
    setup_hand_upgraded(bc, BULLSEYE)
    bc.play_card(0)
    assert m.hp == hp0 - 8 - 11
    assert m.statuses.get(MonsterStatus.LOCK_ON) == 5


def test_capacitor_orb_slots():
    bc = BattleContext(seed=846)
    setup_hand(bc, CAPACITOR)
    bc.play_card(0)
    assert bc.player.orb_slots == 5
    setup_hand_upgraded(bc, CAPACITOR)
    bc.play_card(0)
    assert bc.player.orb_slots == 8  # 可叠


def test_chaos_random_orb():
    bc = BattleContext(seed=847)
    setup_hand(bc, CHAOS)
    bc.play_card(0)
    assert len(bc.player.orbs) == 1
    assert sum(bc.player.special.get(f"chan_{o.name.lower()}", 0)
               for o in Orb) == 1  # 计数入口统一
    # 升级 2 个
    bc2 = BattleContext(seed=847)
    setup_hand_upgraded(bc2, CHAOS)
    bc2.play_card(0)
    assert len(bc2.player.orbs) == 2


def test_chill_frost_per_enemy_and_exhaust():
    bc = BattleContext(seed=848)
    add_cultist(bc, idx=1)
    setup_hand(bc, CHILL)
    bc.play_card(0)
    assert bc.player.orbs == [Orb.FROST, Orb.FROST]
    assert pile_names(bc, bc.cards.exhaust_pile) == ["Chill"]


def test_consume_focus_and_slot_removal():
    """满槽（3 球）时消耗：最老球随球位直接移除（不唤起，wiki Neutral 节）。"""
    bc = BattleContext(seed=849)
    setup_hand(bc, ZAP, COOLHEADED, DARKNESS, CONSUME)
    bc.player.energy = 9
    bc.play_card(0)
    bc.play_card(0)
    bc.play_card(0)
    assert bc.player.orbs == [Orb.LIGHTNING, Orb.FROST, Orb.DARK]
    bc.play_card(0)
    assert bc.player.orbs == [Orb.FROST, Orb.DARK]  # 最老（闪电）随槽移除
    assert bc.player.orb_slots == 2
    assert bc.player.statuses.get(PlayerStatus.FOCUS) == 2
    # 升级 3 专长
    bc2 = BattleContext(seed=849)
    setup_hand_upgraded(bc2, CONSUME)
    bc2.play_card(0)
    assert bc2.player.statuses.get(PlayerStatus.FOCUS) == 3


def test_darkness_channel_and_upgraded_passive():
    bc = BattleContext(seed=850)
    setup_hand(bc, DARKNESS)
    bc.play_card(0)
    assert bc.player.orbs == [Orb.DARK]
    assert bc.player.dark_stacks == 0
    # 升级：额外触发所有暗球被动（+6 存层）
    bc2 = BattleContext(seed=850)
    setup_hand_upgraded(bc2, DARKNESS)
    bc2.play_card(0)
    assert bc2.player.orbs == [Orb.DARK]
    assert bc2.player.dark_stacks == 6


def test_defragment_focus():
    bc = BattleContext(seed=851)
    setup_hand(bc, DEFRAGMENT)
    bc.play_card(0)
    assert bc.player.statuses.get(PlayerStatus.FOCUS) == 1
    setup_hand_upgraded(bc, DEFRAGMENT)
    bc.play_card(0)
    assert bc.player.statuses.get(PlayerStatus.FOCUS) == 3  # 可叠


def test_doom_and_gloom_aoe_and_dark():
    bc = BattleContext(seed=852)
    add_cultist(bc, idx=1)
    m1, m2 = bc.monsters.monsters
    hp1, hp2 = m1.hp, m2.hp
    setup_hand(bc, DOOM_AND_GLOOM)
    bc.player.energy = 9
    bc.play_card(0)
    assert m1.hp == hp1 - 10 and m2.hp == hp2 - 10
    assert bc.player.orbs == [Orb.DARK]
    # 升级 14 伤
    bc2 = BattleContext(seed=852)
    m = bc2.monsters.monsters[0]
    hp0 = m.hp
    setup_hand_upgraded(bc2, DOOM_AND_GLOOM)
    bc2.play_card(0)
    assert m.hp == hp0 - 14


def test_double_energy():
    """wiki Order 例：3 能量付 1 → 2 → 翻倍 4。"""
    bc = BattleContext(seed=853)
    setup_hand(bc, DOUBLE_ENERGY)
    bc.player.energy = 3
    bc.play_card(0)
    assert bc.player.energy == 4
    assert pile_names(bc, bc.cards.exhaust_pile) == ["Double Energy"]
    # 升级 0 费：3×2=6
    bc2 = BattleContext(seed=853)
    setup_hand_upgraded(bc2, DOUBLE_ENERGY)
    bc2.play_card(0)
    assert bc2.player.energy == 6


def test_equilibrium_retains_hand():
    bc = BattleContext(seed=854, deck=[STRIKE] * 10)
    fill_draw(bc, 10)
    setup_hand(bc, EQUILIBRIUM, STRIKE_D, STRIKE_D)
    bc.player.energy = 9
    bc.play_card(0)
    assert bc.player.block == 13
    assert bc.player.statuses.get(PlayerStatus.EQUILIBRIUM) == 1
    bc.end_turn()
    # 手牌整手保留（EQUILIBRIUM 引擎已接），下回合再抽 5
    assert len(bc.cards.hand) == 7  # 2 保留 + 5 新抽
    assert not bc.player.statuses.has(PlayerStatus.EQUILIBRIUM)  # 回合末衰减


def test_ftl_draws_when_early():
    bc = BattleContext(seed=855)
    fill_draw(bc, 10)
    setup_hand(bc, FTL)
    m = bc.monsters.monsters[0]
    hp0 = m.hp
    bc.play_card(0)
    assert m.hp == hp0 - 5
    assert len(bc.cards.hand) == 1  # 第 1 张牌 → 抽 1


def test_ftl_no_draw_when_4th_card():
    bc = BattleContext(seed=856)
    fill_draw(bc, 10)
    setup_hand(bc, STRIKE_D, STRIKE_D, STRIKE_D, FTL)
    bc.player.energy = 9
    for _ in range(3):
        bc.play_card(0)
    bc.play_card(0)  # FTL 是本回合第 4 张 → 不抽
    assert len(bc.cards.hand) == 0


def test_ftl_upgraded_threshold_4():
    bc = BattleContext(seed=857)
    fill_draw(bc, 10)
    setup_hand(bc, STRIKE_D, STRIKE_D, STRIKE_D)
    add_upgraded(bc, FTL)
    bc.player.energy = 9
    for _ in range(3):
        bc.play_card(0)
    bc.play_card(0)  # 第 4 张 < 4（升级）→ 抽 1
    assert len(bc.cards.hand) == 1


def test_force_field_dynamic_cost_and_block():
    bc = BattleContext(seed=858)
    fill_draw(bc, 10)
    setup_hand(bc, DEFRAGMENT, FORCE_FIELD)
    bc.player.energy = 9
    bc.play_card(0)  # 1 张能力牌 → 力场 4-1 = 3 费
    assert bc.player.statuses.get(PlayerStatus.FOCUS) == 1
    bc.play_card(0)
    assert bc.player.energy == 9 - 1 - 3
    assert bc.player.block == 12


def test_force_field_free_after_4_powers():
    bc = BattleContext(seed=859)
    fill_draw(bc, 10)
    setup_hand(bc, DEFRAGMENT, DEFRAGMENT, DEFRAGMENT, DEFRAGMENT, FORCE_FIELD)
    bc.player.energy = 9
    for _ in range(4):
        bc.play_card(0)
    assert _hand_cost(bc, "Force Field") == 0
    bc.play_card(0)
    assert bc.player.energy == 9 - 4  # 力场 0 费
    assert bc.player.block == 12
    # 升级 16 格挡
    bc2 = BattleContext(seed=859)
    setup_hand_upgraded(bc2, FORCE_FIELD)
    bc2.player.energy = 9
    bc2.play_card(0)
    assert bc2.player.block == 16


def _hand_cost(bc, name):
    for c in bc.cards.hand:
        if c.card.name == name:
            return c.card.dynamic_cost(bc, c)
    raise AssertionError(f"{name} 不在手牌")


def test_fusion_plasma():
    bc = BattleContext(seed=860)
    setup_hand(bc, FUSION)
    bc.player.energy = 9
    bc.play_card(0)
    assert bc.player.orbs == [Orb.PLASMA]
    assert bc.player.special.get("chan_plasma") == 1
    setup_hand_upgraded(bc, FUSION)
    bc.player.energy = 1
    bc.play_card(0)
    assert bc.player.energy == 0  # 升级 1 费
    assert bc.player.orbs == [Orb.PLASMA, Orb.PLASMA]


def test_genetic_algorithm_scaling():
    bc = BattleContext(seed=861)
    setup_hand(bc, GENETIC_ALGORITHM)
    bc.play_card(0)
    assert bc.player.block == 1
    assert bc.cards.exhaust_pile[0].misc_data == 2  # 永久 +2
    # 同一实例再打出（Exhume 类回手路径）：1+2 格挡
    inst = bc.cards.exhaust_pile.pop()
    bc.cards.hand.append(inst)
    bc.play_card(0)
    assert bc.player.block == 4
    # 升级每打 +3
    bc2 = BattleContext(seed=861)
    setup_hand_upgraded(bc2, GENETIC_ALGORITHM)
    bc2.play_card(0)
    assert bc2.player.block == 1
    assert bc2.cards.exhaust_pile[0].misc_data == 3


def test_glacier_block_and_2_frost():
    bc = BattleContext(seed=862)
    setup_hand(bc, GLACIER)
    bc.player.energy = 9
    bc.play_card(0)
    assert bc.player.block == 7
    assert bc.player.orbs == [Orb.FROST, Orb.FROST]
    setup_hand_upgraded(bc, GLACIER)
    bc.play_card(0)
    # 满 3 槽后第 4 个冰球唤起最老（+2 格挡）
    assert bc.player.block == 7 + 10 + 2
    assert bc.player.orbs == [Orb.FROST] * 3


def test_heatsinks_slot():
    """special["heatsinks"] 落槽（on_use_power_card 钩子接线见迁移报告）。"""
    bc = BattleContext(seed=863)
    setup_hand(bc, HEATSINKS)
    bc.play_card(0)
    assert bc.player.special.get("heatsinks") == 1
    setup_hand_upgraded(bc, HEATSINKS)
    bc.play_card(0)
    assert bc.player.special.get("heatsinks") == 3  # 可叠


def test_hello_world_slot():
    bc = BattleContext(seed=864)
    setup_hand(bc, HELLO_WORLD)
    bc.play_card(0)
    assert bc.player.special.get("hello_world") == 1


def test_loop_status_and_frost_full_flow():
    bc = BattleContext(seed=865, deck=[STRIKE] * 10)
    fill_draw(bc, 10)
    setup_hand(bc, LOOP, COOLHEADED)
    bc.player.energy = 9
    bc.play_card(0)
    assert bc.player.statuses.get(PlayerStatus.LOOP) == 1
    bc.play_card(0)
    bc.end_turn()  # 邪教徒咒语回合不攻击
    # 回合开始：冰球 passive 2 + LOOP 额外触发 2 = 4 格挡
    assert bc.player.block == 4
    # 升级 2 层：2 + 2×2 = 6
    bc2 = BattleContext(seed=865, deck=[STRIKE] * 10)
    fill_draw(bc2, 10)
    setup_hand_upgraded(bc2, LOOP)
    bc2.play_card(0)
    setup_hand(bc2, COOLHEADED)
    bc2.play_card(0)
    bc2.end_turn()
    assert bc2.player.block == 6


def test_melter_removes_block_first():
    bc = BattleContext(seed=866)
    m = bc.monsters.monsters[0]
    m.block = 8
    hp0 = m.hp
    setup_hand(bc, MELTER)
    bc.play_card(0)
    assert m.hp == hp0 - 10  # 先移除格挡再结算（wiki Order 节）
    assert m.block == 0
    setup_hand_upgraded(bc, MELTER)
    bc.play_card(0)
    assert m.hp == hp0 - 10 - 14


def test_overclock_draw_and_burn():
    bc = BattleContext(seed=867)
    fill_draw(bc, 10)
    setup_hand(bc, OVERCLOCK)
    bc.play_card(0)
    assert len(bc.cards.hand) == 2
    # Burn 为效果动作先落堆，Overclock 出牌收尾最后落（对齐本体）
    assert pile_names(bc, bc.cards.discard_pile) == ["Burn", "Overclock"]
    assert bc.cards.discard_pile[0].card is BURN


def test_overclock_upgraded_draw_3():
    bc = BattleContext(seed=868)
    fill_draw(bc, 10)
    setup_hand_upgraded(bc, OVERCLOCK)
    bc.play_card(0)
    assert len(bc.cards.hand) == 3
    assert pile_names(bc, bc.cards.discard_pile) == ["Burn", "Overclock"]


def test_recycle_exhaust_for_energy():
    bc = BattleContext(seed=869)
    setup_hand(bc, RECYCLE, STRIKE_D, CLAW)
    bc.player.energy = 3
    bc.play_card(0)
    assert bc.input_state == InputState.CARD_SELECT
    bc.choose_card(0)  # 消耗打击（1 费）→ +1 能量
    assert pile_names(bc, bc.cards.exhaust_pile) == ["Strike"]
    assert bc.player.energy == 3 - 1 + 1
    assert pile_names(bc, bc.cards.hand) == ["Claw"]


def test_recycle_upgraded_costs_0():
    """单候选直执（引擎 open_card_select 内建）：0 费打出 + 回收 1 费。"""
    bc = BattleContext(seed=870)
    setup_hand_upgraded(bc, RECYCLE, STRIKE_D)
    bc.player.energy = 1
    bc.play_card(0)
    assert pile_names(bc, bc.cards.exhaust_pile) == ["Strike"]
    assert bc.player.energy == 1 + 1
    assert pile_names(bc, bc.cards.hand) == []


def test_reinforced_body_x_block():
    bc = BattleContext(seed=871)
    setup_hand(bc, REINFORCED_BODY)
    bc.player.energy = 2
    bc.play_card(0)
    assert bc.player.energy == 0
    assert bc.player.block == 14  # 7 × 2
    # 0 能量打出：0 次
    setup_hand(bc, REINFORCED_BODY)
    bc.play_card(0)
    assert bc.player.block == 14
    # 升级 9×2
    bc2 = BattleContext(seed=871)
    setup_hand_upgraded(bc2, REINFORCED_BODY)
    bc2.player.energy = 2
    bc2.play_card(0)
    assert bc2.player.block == 18


def test_reinforced_body_dexterity_x_times():
    bc = BattleContext(seed=872)
    bc.player.statuses.add(PlayerStatus.DEXTERITY, 2)
    setup_hand(bc, REINFORCED_BODY)
    bc.player.energy = 3
    bc.play_card(0)
    assert bc.player.block == (7 + 2) * 3  # 敏捷受益 X 次


def test_reprogram_focus_for_stats():
    bc = BattleContext(seed=873)
    setup_hand(bc, REPROGRAM)
    bc.play_card(0)
    s = bc.player.statuses
    assert s.get(PlayerStatus.FOCUS) == -1
    assert s.get(PlayerStatus.STRENGTH) == 1
    assert s.get(PlayerStatus.DEXTERITY) == 1
    setup_hand_upgraded(bc, REPROGRAM)
    bc.play_card(0)
    assert s.get(PlayerStatus.FOCUS) == -3
    assert s.get(PlayerStatus.STRENGTH) == 3
    assert s.get(PlayerStatus.DEXTERITY) == 3


def test_rip_and_tear_random_enemy_twice():
    bc = BattleContext(seed=874)
    add_cultist(bc, idx=1)
    total0 = sum(m.hp for m in bc.monsters.monsters)
    setup_hand(bc, RIP_AND_TEAR)
    bc.play_card(0)
    assert sum(m.hp for m in bc.monsters.monsters) == total0 - 14  # 7×2


def test_rip_and_tear_upgraded_9():
    bc = BattleContext(seed=875)
    m = bc.monsters.monsters[0]
    hp0 = m.hp
    setup_hand_upgraded(bc, RIP_AND_TEAR)
    bc.play_card(0)
    assert m.hp == hp0 - 18


def test_scrape_draw_and_discard_nonzero():
    bc = BattleContext(seed=876)
    for card in (CLAW, CLAW, STRIKE_D, STRIKE_D):
        bc.cards.draw_pile.append(bc.cards.instantiate(card))
    m = bc.monsters.monsters[0]
    hp0 = m.hp
    setup_hand(bc, SCRAPE)
    bc.player.energy = 9
    bc.play_card(0)
    assert m.hp == hp0 - 7
    assert pile_names(bc, bc.cards.hand) == ["Claw", "Claw"]  # 0 费保留
    # 弃牌为效果动作先落堆，Scrape 出牌收尾最后落（对齐本体）
    assert pile_names(bc, bc.cards.discard_pile) == ["Strike", "Strike", "Scrape"]


def test_scrape_upgraded_10_damage_5_draw():
    bc = BattleContext(seed=877)
    for card in (CLAW, CLAW, CLAW, CLAW, STRIKE_D):
        bc.cards.draw_pile.append(bc.cards.instantiate(card))
    m = bc.monsters.monsters[0]
    hp0 = m.hp
    setup_hand_upgraded(bc, SCRAPE)
    bc.player.energy = 9
    bc.play_card(0)
    assert m.hp == hp0 - 10
    assert pile_names(bc, bc.cards.hand) == ["Claw"] * 4
    assert pile_names(bc, bc.cards.discard_pile) == ["Strike", "Scrape"]


def test_self_repair_slot():
    bc = BattleContext(seed=878)
    setup_hand(bc, SELF_REPAIR)
    bc.play_card(0)
    assert bc.player.special.get("self_repair") == 7
    setup_hand_upgraded(bc, SELF_REPAIR)
    bc.play_card(0)
    assert bc.player.special.get("self_repair") == 17  # 可叠


def test_skim_draw():
    bc = BattleContext(seed=879)
    fill_draw(bc, 10)
    setup_hand(bc, SKIM)
    bc.play_card(0)
    assert len(bc.cards.hand) == 3
    bc2 = BattleContext(seed=879)
    fill_draw(bc2, 10)
    setup_hand_upgraded(bc2, SKIM)
    bc2.play_card(0)
    assert len(bc2.cards.hand) == 4


def test_static_discharge_channels_on_hit():
    bc = BattleContext(seed=880)
    setup_hand(bc, STATIC_DISCHARGE)
    bc.play_card(0)
    assert bc.player.statuses.get(PlayerStatus.STATIC_DISCHARGE) == 1
    bc.add_to_bot(Actions.attack_player(0, 5))
    run_queue(bc)
    assert bc.player.orbs == [Orb.LIGHTNING]  # 受击引导（引擎已接）


def test_storm_slot():
    bc = BattleContext(seed=881)
    setup_hand(bc, STORM)
    bc.play_card(0)
    assert bc.player.special.get("storm") == 1


def test_sunder_kill_grants_energy():
    bc = BattleContext(seed=882)
    add_cultist(bc, idx=1)  # 第二只怪防止战斗提前结束
    m = bc.monsters.monsters[0]
    m.hp = 10
    setup_hand(bc, SUNDER)
    bc.player.energy = 9
    bc.play_card(0, 0)  # 双怪需显式目标
    assert not m.alive
    assert bc.player.energy == 9 - 3 + 3  # 击杀 +3
    assert bc.outcome == Outcome.UNDECIDED


def test_sunder_no_kill_no_energy():
    bc = BattleContext(seed=883)
    m = bc.monsters.monsters[0]
    hp0 = m.hp
    setup_hand_upgraded(bc, SUNDER)
    bc.player.energy = 9
    bc.play_card(0)
    assert m.hp == hp0 - 32
    assert bc.player.energy == 9 - 3


def test_tempest_x_lightning():
    bc = BattleContext(seed=884)
    setup_hand(bc, TEMPEST)
    bc.player.energy = 3
    bc.play_card(0)
    assert bc.player.energy == 0
    assert bc.player.orbs == [Orb.LIGHTNING] * 3
    assert bc.player.special.get("chan_lightning") == 3
    assert pile_names(bc, bc.cards.exhaust_pile) == ["Tempest"]


def test_tempest_upgraded_x_plus_1():
    bc = BattleContext(seed=885)
    setup_hand_upgraded(bc, TEMPEST)
    bc.player.energy = 2
    bc.play_card(0)
    assert bc.player.orbs == [Orb.LIGHTNING] * 3  # X+1


def test_white_noise_random_power():
    bc = BattleContext(seed=886)
    setup_hand(bc, WHITE_NOISE)
    bc.play_card(0)
    assert len(bc.cards.hand) == 1
    inst = bc.cards.hand[0]
    assert inst.card.ctype == "Power"
    assert inst.card.name != "Self Repair"  # 治疗卡不可生成（wiki Neutral）
    assert inst.cost == 0  # 本回合 0 费
    assert pile_names(bc, bc.cards.exhaust_pile) == ["White Noise"]


def test_white_noise_pool_excludes_self_repair():
    from sts.content.cards.defect import SELF_REPAIR, _defect_pool

    pool = _defect_pool("Power", exclude=(SELF_REPAIR,))
    assert SELF_REPAIR not in pool
    assert CAPACITOR in pool and LOOP in pool and ECHO_FORM in pool


def test_white_noise_upgraded_costs_0():
    bc = BattleContext(seed=887)
    setup_hand_upgraded(bc, WHITE_NOISE)
    bc.player.energy = 1
    bc.play_card(0)
    assert bc.player.energy == 1
    assert len(bc.cards.hand) == 1


# ---- 稀有 17 张 ----


def test_all_for_one_returns_zero_cost_cards():
    bc = BattleContext(seed=890)
    to_discard(bc, CLAW, TURBO, STRIKE_D)
    m = bc.monsters.monsters[0]
    hp0 = m.hp
    setup_hand(bc, ALL_FOR_ONE)
    bc.player.energy = 9
    bc.play_card(0)
    assert m.hp == hp0 - 10
    assert pile_names(bc, bc.cards.hand) == ["Claw", "TURBO"]  # 弃牌堆序
    assert pile_names(bc, bc.cards.discard_pile) == ["Strike", "All for One"]


def test_all_for_one_respects_hand_limit():
    bc = BattleContext(seed=891)
    for _ in range(MAX_HAND_SIZE):
        bc.cards.discard_pile.append(bc.cards.instantiate(CLAW))
    to_discard(bc, STRIKE_D)  # 排在 10 张爪击之后，手满留弃牌堆
    setup_hand(bc, ALL_FOR_ONE)
    bc.player.energy = 9
    bc.play_card(0)
    assert len(bc.cards.hand) == MAX_HAND_SIZE
    assert pile_names(bc, bc.cards.hand) == ["Claw"] * MAX_HAND_SIZE
    assert pile_names(bc, bc.cards.discard_pile) == ["Strike", "All for One"]


def test_all_for_one_upgraded_14():
    bc = BattleContext(seed=892)
    m = bc.monsters.monsters[0]
    hp0 = m.hp
    setup_hand_upgraded(bc, ALL_FOR_ONE)
    bc.player.energy = 9
    bc.play_card(0)
    assert m.hp == hp0 - 14


def test_all_for_one_never_returns_status_cards():
    """wiki Neutral：无具体费用的牌（状态/诅咒）永不回手——TURBO 洗入的
    Void（本引擎模板费 0）按类型排除。"""
    bc = BattleContext(seed=893)
    to_discard(bc, CLAW)
    bc.cards.discard_pile.append(bc.cards.instantiate(VOID))
    setup_hand(bc, ALL_FOR_ONE)
    bc.player.energy = 9
    bc.play_card(0)
    assert pile_names(bc, bc.cards.hand) == ["Claw"]
    assert "Void" in pile_names(bc, bc.cards.discard_pile)


def test_scrape_always_discards_status_cards():
    bc = BattleContext(seed=893)
    bc.cards.draw_pile.append(bc.cards.instantiate(VOID))
    bc.cards.draw_pile.append(bc.cards.instantiate(CLAW))
    setup_hand(bc, SCRAPE)
    bc.player.energy = 9
    bc.play_card(0)
    assert pile_names(bc, bc.cards.hand) == ["Claw"]
    assert "Void" in pile_names(bc, bc.cards.discard_pile)


def test_amplify_slot():
    bc = BattleContext(seed=893)
    setup_hand(bc, AMPLIFY)
    bc.play_card(0)
    assert bc.player.special.get("amplify") == 1
    setup_hand_upgraded(bc, AMPLIFY)
    bc.play_card(0)
    assert bc.player.special.get("amplify") == 3


def test_biased_cognition_focus_and_bias_slot():
    """special["bias_focus"] 落槽（BIAS 状态引擎接线见迁移报告）。"""
    bc = BattleContext(seed=894)
    setup_hand(bc, BIASED_COGNITION)
    bc.play_card(0)
    assert bc.player.statuses.get(PlayerStatus.FOCUS) == 4
    assert bc.player.special.get("bias_focus") == 1
    setup_hand_upgraded(bc, BIASED_COGNITION)
    bc.play_card(0)
    assert bc.player.statuses.get(PlayerStatus.FOCUS) == 9
    assert bc.player.special.get("bias_focus") == 2


def test_buffer_slot():
    bc = BattleContext(seed=895)
    setup_hand(bc, BUFFER)
    bc.player.energy = 9
    bc.play_card(0)
    assert bc.player.special.get("buffer") == 1
    setup_hand_upgraded(bc, BUFFER)
    bc.play_card(0)
    assert bc.player.special.get("buffer") == 3


def test_core_surge_artifact_and_exhaust():
    bc = BattleContext(seed=896)
    m = bc.monsters.monsters[0]
    hp0 = m.hp
    setup_hand(bc, CORE_SURGE)
    bc.play_card(0)
    assert m.hp == hp0 - 11
    assert bc.player.statuses.get(PlayerStatus.ARTIFACT) == 1
    assert pile_names(bc, bc.cards.exhaust_pile) == ["Core Surge"]
    setup_hand_upgraded(bc, CORE_SURGE)
    bc.play_card(0)
    assert m.hp == hp0 - 11 - 15


def test_creative_ai_slot_and_upgraded_cost():
    bc = BattleContext(seed=897)
    setup_hand(bc, CREATIVE_AI)
    bc.player.energy = 3
    bc.play_card(0)
    assert bc.player.special.get("creative_ai") == 1
    setup_hand_upgraded(bc, CREATIVE_AI)
    bc.player.energy = 2
    bc.play_card(0)
    assert bc.player.energy == 0  # 升级 3→2
    assert bc.player.special.get("creative_ai") == 2


def test_echo_form_slot():
    bc = BattleContext(seed=898)
    setup_hand(bc, ECHO_FORM)
    bc.player.energy = 9
    bc.play_card(0)
    assert bc.player.special.get("echo_form") == 1


def test_electrodynamics_electro_and_lightning():
    bc = BattleContext(seed=899)
    setup_hand(bc, ELECTRODYNAMICS)
    bc.player.energy = 9
    bc.play_card(0)
    assert bc.player.statuses.get(PlayerStatus.ELECTRO) == 1
    assert bc.player.orbs == [Orb.LIGHTNING, Orb.LIGHTNING]
    # 升级 3 个
    bc2 = BattleContext(seed=899)
    setup_hand_upgraded(bc2, ELECTRODYNAMICS)
    bc2.play_card(0)
    assert bc2.player.orbs == [Orb.LIGHTNING] * 3


def test_electrodynamics_lightning_hits_all():
    bc = BattleContext(seed=900)
    add_cultist(bc, idx=1)
    m1, m2 = bc.monsters.monsters
    hp1, hp2 = m1.hp, m2.hp
    setup_hand(bc, ELECTRODYNAMICS)
    bc.player.energy = 9
    bc.play_card(0)
    bc.end_turn()  # 回合结束 passive：ELECTRO 下 2 个闪电球各全体 3 伤
    assert m1.hp == hp1 - 6 and m2.hp == hp2 - 6


def test_fission_remove_all_orbs():
    bc = BattleContext(seed=901)
    fill_draw(bc, 10)
    setup_hand(bc, ZAP, COOLHEADED, FISSION)
    bc.player.energy = 9
    bc.play_card(0)
    bc.play_card(0)
    e0 = bc.player.energy
    bc.play_card(0)
    assert bc.player.orbs == []
    assert bc.player.energy == e0 + 2  # 每球 +1 能量（0 费打出）
    assert len(bc.cards.hand) == 3  # 冷静抽 1 + 每球抽 1×2
    assert pile_names(bc, bc.cards.exhaust_pile) == ["Fission"]


def test_fission_upgraded_evoke_all():
    bc = BattleContext(seed=902)
    m = bc.monsters.monsters[0]
    hp0 = m.hp
    fill_draw(bc, 10)
    setup_hand(bc, ZAP, COOLHEADED)
    add_upgraded(bc, FISSION)
    bc.player.energy = 9
    bc.play_card(0)
    bc.play_card(0)
    bc.play_card(0)
    assert bc.player.orbs == []
    assert m.hp == hp0 - 3  # 唤起闪电 3 伤（冰球唤起得 2 格挡）
    assert bc.player.block == 2
    assert len(bc.cards.hand) == 3  # 冷静抽 1 + 每球抽 1×2
    assert bc.player.energy == 9 - 2 + 2


def test_hyperbeam_aoe_and_focus_loss():
    bc = BattleContext(seed=903)
    add_cultist(bc, idx=1)
    m1, m2 = bc.monsters.monsters
    hp1, hp2 = m1.hp, m2.hp
    bc.player.statuses.add(PlayerStatus.FOCUS, 1)
    setup_hand(bc, HYPERBEAM)
    bc.player.energy = 9
    bc.play_card(0)
    assert m1.hp == hp1 - 26 and m2.hp == hp2 - 26
    assert bc.player.statuses.get(PlayerStatus.FOCUS) == -2  # 1 - 3
    setup_hand_upgraded(bc, HYPERBEAM)
    bc.play_card(0)
    assert bc.player.statuses.get(PlayerStatus.FOCUS) == -5


def test_machine_learning_extra_draw_full_flow():
    """DRAW_REDUCTION 负层 = 每回合多抽 1（引擎 draw_cards 语义，全流程）。"""
    bc = BattleContext(seed=904, deck=[STRIKE] * 10)
    fill_draw(bc, 30)
    setup_hand(bc, MACHINE_LEARNING)
    bc.play_card(0)
    assert bc.player.statuses.get(PlayerStatus.DRAW_REDUCTION) == -1
    bc.end_turn()
    assert len(bc.cards.hand) == 6  # 5 + 1
    bc.end_turn()
    assert len(bc.cards.hand) == 6  # 持续生效
    # 叠加：第二张 ML → DRAW_REDUCTION -2 → 每回合 7 张
    setup_hand(bc, MACHINE_LEARNING)
    bc.play_card(0)
    bc.end_turn()
    assert len(bc.cards.hand) == 7


def test_meteor_strike_damage_and_plasma():
    bc = BattleContext(seed=905)
    m = bc.monsters.monsters[0]
    hp0 = m.hp
    setup_hand(bc, METEOR_STRIKE)
    bc.player.energy = 5
    bc.play_card(0)
    assert bc.player.energy == 0
    assert m.hp == hp0 - 24
    assert bc.player.orbs == [Orb.PLASMA] * 3


def test_meteor_strike_upgraded_30():
    bc = BattleContext(seed=906)
    m = bc.monsters.monsters[0]
    hp0 = m.hp
    setup_hand_upgraded(bc, METEOR_STRIKE)
    bc.player.energy = 5
    bc.play_card(0)
    assert m.hp == hp0 - 30


def test_multi_cast_x_evokes():
    """X=2 唤起 2 次（2 个球）：2×3=6 伤；升级 X+1。"""
    bc = BattleContext(seed=907)
    m = bc.monsters.monsters[0]
    hp0 = m.hp
    setup_hand(bc, ZAP, ZAP, MULTI_CAST)
    bc.player.energy = 9
    bc.play_card(0)
    bc.play_card(0)
    bc.player.energy = 2
    bc.play_card(0)
    assert bc.player.energy == 0
    assert bc.player.orbs == []
    assert m.hp == hp0 - 6
    # 升级 X+1：能量 2 → 3 次唤起（3 个球）
    bc2 = BattleContext(seed=907)
    m2 = bc2.monsters.monsters[0]
    hp1 = m2.hp
    setup_hand(bc2, ZAP, ZAP, ZAP)
    add_upgraded(bc2, MULTI_CAST)
    bc2.player.energy = 9
    for _ in range(3):
        bc2.play_card(0)
    bc2.player.energy = 2
    bc2.play_card(0)
    assert m2.hp == hp1 - 9


def test_rainbow_three_orbs_and_upgrade_no_exhaust():
    bc = BattleContext(seed=908)
    setup_hand(bc, RAINBOW)
    bc.player.energy = 9
    bc.play_card(0)
    assert bc.player.orbs == [Orb.LIGHTNING, Orb.FROST, Orb.DARK]
    assert pile_names(bc, bc.cards.exhaust_pile) == ["Rainbow"]
    setup_hand_upgraded(bc, RAINBOW)
    bc.play_card(0)
    assert pile_names(bc, bc.cards.exhaust_pile) == ["Rainbow"]
    assert pile_names(bc, bc.cards.discard_pile) == ["Rainbow"]  # 升级不再消耗


def test_reboot_shuffles_and_draws():
    bc = BattleContext(seed=909)
    fill_draw(bc, 4)
    bc.cards.discard_pile.clear()
    to_discard(bc, STRIKE_D, STRIKE_D, STRIKE_D)
    setup_hand(bc, STRIKE_D, STRIKE_D, REBOOT)
    bc.play_card(2)
    # 手牌 2 + 弃牌堆 3 洗回抽牌堆（Reboot 自身已消耗不参与），再抽 4
    assert pile_names(bc, bc.cards.exhaust_pile) == ["Reboot"]
    assert len(bc.cards.hand) == 4
    assert len(bc.cards.draw_pile) == 5 + 4 - 4


def test_reboot_upgraded_draws_6():
    bc = BattleContext(seed=910)
    fill_draw(bc, 10)
    bc.cards.discard_pile.clear()
    to_discard(bc, STRIKE_D)
    setup_hand_upgraded(bc, REBOOT)
    bc.play_card(0)
    assert len(bc.cards.hand) == 6
    assert len(bc.cards.draw_pile) == 10 + 1 - 6


def test_seek_draw_pile_to_hand():
    bc = BattleContext(seed=911)
    bc.cards.draw_pile.clear()
    for card in (CLAW, DEFEND_D, STRIKE_D, STRIKE_D, STRIKE_D):
        bc.cards.draw_pile.append(bc.cards.instantiate(card))
    setup_hand(bc, SEEK)
    bc.play_card(0)
    assert bc.input_state == InputState.CARD_SELECT
    assert len(bc.card_select_info.candidates) == 5
    bc.choose_card(0)  # 基础版选 1 张（爪击）
    assert pile_names(bc, bc.cards.hand) == ["Claw"]
    assert len(bc.cards.draw_pile) == 4
    assert pile_names(bc, bc.cards.exhaust_pile) == ["Seek"]


def test_seek_upgraded_two_cards():
    bc = BattleContext(seed=911)
    bc.cards.draw_pile.clear()
    for card in (CLAW, DEFEND_D, STRIKE_D):
        bc.cards.draw_pile.append(bc.cards.instantiate(card))
    setup_hand_upgraded(bc, SEEK)
    bc.play_card(0)
    bc.choose_cards([0, 1])
    assert pile_names(bc, bc.cards.hand) == ["Claw", "Defend"]
    assert len(bc.cards.draw_pile) == 1


def test_seek_base_one_card():
    bc = BattleContext(seed=912)
    fill_draw(bc, 2)
    setup_hand(bc, SEEK)
    bc.play_card(0)
    bc.choose_card(0)
    assert len(bc.cards.hand) == 1
    assert len(bc.cards.draw_pile) == 1


def test_seek_empty_draw_pile_noop():
    bc = BattleContext(seed=913)
    bc.cards.draw_pile.clear()
    setup_hand(bc, SEEK)
    bc.play_card(0)
    assert bc.cards.hand == []
    assert pile_names(bc, bc.cards.exhaust_pile) == ["Seek"]


def test_thunder_strike_per_lightning_channeled():
    bc = BattleContext(seed=914)
    m = bc.monsters.monsters[0]
    hp0 = m.hp
    setup_hand(bc, ZAP, ZAP, THUNDER_STRIKE)
    bc.player.energy = 9
    bc.play_card(0)
    bc.play_card(0)
    assert bc.player.special.get("chan_lightning") == 2
    bc.play_card(0)
    assert m.hp == hp0 - 14  # 2 × 7，每段独立随机目标（单怪全中）


def test_thunder_strike_upgraded_9():
    bc = BattleContext(seed=915)
    m = bc.monsters.monsters[0]
    hp0 = m.hp
    setup_hand_upgraded(bc, ZAP, THUNDER_STRIKE)
    bc.player.energy = 9
    bc.play_card(0)
    bc.play_card(0)
    assert m.hp == hp0 - 9

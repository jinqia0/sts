"""无色卡 34 张移植断言（数值/结算以 lightspeed C++ + wiki 交叉核对）。

沿用 test_cards.py 的构造模式（setup_hand / add_cultist / setup_hand_upgraded），
保证出牌序列确定、不依赖初始洗牌。随机生成类（Discovery/Chrysalis/
Metamorphosis/Jack of All Trades/Transmutation/Violence/Madness）只断言结构性
性质（张数/类型/费用/落堆），不锁随机结果。

引擎接线状态（见 cards/colorless.py 模块注释）：
- Mayhem / Magnetism：钩子已接（前置提交 8de8f33），全流程可测；
- Panache / Sadistic Nature / Dark Shackles(SHACKLED 回补)：仅标记/状态落地，
  触发段待引擎接线——对应测试只断言标记。
"""

import subprocess
import sys

from sts.combat import BattleContext
from sts.combat.types import InputState, MonsterStatus, PlayerStatus
from sts.content.cards import (
    APOTHEOSIS,
    BANDAGE_UP,
    BLIND,
    BLUDGEON,
    CHRYSALIS,
    CLEAVE,
    DARK_SHACKLES,
    DEEP_BREATH,
    DEFEND,
    DISCOVERY,
    DRAMATIC_ENTRANCE,
    ENLIGHTENMENT,
    FINESSE,
    FLASH_OF_STEEL,
    FORETHOUGHT,
    GOOD_INSTINCTS,
    IMPATIENCE,
    JACK_OF_ALL_TRADES,
    MADNESS,
    MAGNETISM,
    MASTER_OF_STRATEGY,
    MAYHEM,
    METAMORPHOSIS,
    MIND_BLAST,
    PANACEA,
    PANACHE,
    PANIC_BUTTON,
    PURITY,
    SADISTIC_NATURE,
    SECRET_TECHNIQUE,
    SECRET_WEAPON,
    SEARING_BLOW,
    SLIMED,
    STRIKE,
    SWIFT_STRIKE,
    THE_BOMB,
    THINKING_AHEAD,
    TRANSMUTATION,
    TRIP,
    VIOLENCE,
    WHIRLWIND,
    BURN,
)
from sts.content.monsters import Cultist


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


def add_cultist(bc: BattleContext, idx: int = 1, hp: int = 50) -> Cultist:
    m = Cultist(idx=idx, hp=hp, max_hp=hp)
    m.set_move(Cultist.INCANTATION)
    bc.monsters.add(m)
    return m


def clear_piles(bc: BattleContext) -> None:
    bc.cards.draw_pile.clear()
    bc.cards.discard_pile.clear()
    bc.cards.exhaust_pile.clear()


def pile_names(bc, pile) -> list:
    return [c.card.name for c in pile]


# ---- re-export 与导入顺序 ----


def test_colorless_reexport_via_cards_module():
    import sts.content.cards.colorless as cc
    import sts.content.cards as cards_mod

    assert cards_mod.BANDAGE_UP is cc.BANDAGE_UP
    assert cards_mod.TRANSMUTATION is cc.TRANSMUTATION
    assert cards_mod.HAND_OF_GREED.colorless is True  # 定义在 cards.py 的第 35 张无色卡


def test_colorless_first_import_order_keeps_reexport():
    """cards.colorless 被先行导入时，包根 eager re-export 仍可用。"""
    code = (
        "import sts.content.cards.colorless as cc; "
        "from sts.content import cards; "
        "assert cards.BANDAGE_UP is cc.BANDAGE_UP; "
        "from sts.content.cards import REGRET"  # 诅咒 re-export 不受影响
    )
    subprocess.run([sys.executable, "-c", code], check=True, timeout=60)


# ---- 非普通（uncommon）20 张 ----


def test_bandage_up_heals_and_exhausts():
    bc = BattleContext(seed=300)
    bc.player.hp = 40
    setup_hand(bc, BANDAGE_UP)
    bc.play_card(0)
    assert bc.player.hp == 44
    assert pile_names(bc, bc.cards.exhaust_pile) == ["Bandage Up"]
    assert bc.cards.discard_pile == []


def test_bandage_up_upgraded_heals_6():
    bc = BattleContext(seed=301)
    bc.player.hp = 40
    setup_hand_upgraded(bc, BANDAGE_UP)
    bc.play_card(0)
    assert bc.player.hp == 46


def test_blind_single_target_weak():
    bc = BattleContext(seed=302)
    c2 = add_cultist(bc)
    setup_hand(bc, BLIND)
    bc.play_card(0, target=1)
    assert c2.statuses.get(MonsterStatus.WEAK) == 2
    assert not bc.monsters.monsters[0].statuses.has(MonsterStatus.WEAK)


def test_blind_upgraded_all_enemies_weak():
    bc = BattleContext(seed=303)
    add_cultist(bc)
    setup_hand_upgraded(bc, BLIND)
    bc.play_card(0, target=0)
    assert all(m.statuses.get(MonsterStatus.WEAK) == 2 for m in bc.monsters.monsters)


def test_dark_shackles_strength_down_and_shackled():
    bc = BattleContext(seed=304)
    m = bc.monsters.monsters[0]
    m.statuses.add(MonsterStatus.STRENGTH, 5)
    setup_hand(bc, DARK_SHACKLES)
    bc.play_card(0)
    assert m.statuses.get(MonsterStatus.STRENGTH) == -4
    assert m.statuses.get(MonsterStatus.SHACKLED) == 9  # 回合末回补的配对状态（引擎接线待补）
    assert pile_names(bc, bc.cards.exhaust_pile) == ["Dark Shackles"]


def test_dark_shackles_upgraded_15():
    bc = BattleContext(seed=305)
    m = bc.monsters.monsters[0]
    setup_hand_upgraded(bc, DARK_SHACKLES)
    bc.play_card(0)
    assert m.statuses.get(MonsterStatus.STRENGTH) == -15
    assert m.statuses.get(MonsterStatus.SHACKLED) == 15


def test_dark_shackles_blocked_by_artifact():
    bc = BattleContext(seed=306)
    m = bc.monsters.monsters[0]
    m.statuses.add(MonsterStatus.ARTIFACT, 1)
    m.statuses.add(MonsterStatus.STRENGTH, 5)
    setup_hand(bc, DARK_SHACKLES)
    bc.play_card(0)
    assert m.statuses.get(MonsterStatus.ARTIFACT) == 0
    assert m.statuses.get(MonsterStatus.STRENGTH) == 5  # 抵消则力量与 SHACKLED 均不落地
    assert m.statuses.get(MonsterStatus.SHACKLED) == 0


def test_deep_breath_shuffles_discard_and_draws():
    bc = BattleContext(seed=307)
    clear_piles(bc)
    for _ in range(3):
        bc.cards.discard_pile.append(bc.cards.instantiate(STRIKE))
    setup_hand(bc, DEEP_BREATH)
    bc.play_card(0)
    # 洗回 3 张打击（打出的自身不参与——对齐 C++ OnAfterCardUsed 的落堆时序）、抽走 1
    assert len(bc.cards.draw_pile) == 2
    assert len(bc.cards.hand) == 1
    assert pile_names(bc, bc.cards.discard_pile) == ["Deep Breath"]
    assert not any(c.card.name == "Deep Breath" for c in bc.cards.exhaust_pile)  # 不消耗


def test_deep_breath_empty_discard_still_draws():
    bc = BattleContext(seed=308)
    clear_piles(bc)
    bc.cards.draw_pile.append(bc.cards.instantiate(STRIKE))
    setup_hand(bc, DEEP_BREATH)
    bc.play_card(0)
    assert len(bc.cards.hand) == 1
    assert bc.cards.draw_pile == []
    assert pile_names(bc, bc.cards.discard_pile) == ["Deep Breath"]  # 空堆不洗


def test_deep_breath_upgraded_draws_2():
    bc = BattleContext(seed=309)
    clear_piles(bc)
    for _ in range(3):
        bc.cards.discard_pile.append(bc.cards.instantiate(STRIKE))
    setup_hand_upgraded(bc, DEEP_BREATH)
    bc.play_card(0)
    assert len(bc.cards.draw_pile) == 1  # 洗回 3、抽走 2
    assert len(bc.cards.hand) == 2


def test_discovery_choose_one_of_three_zero_cost():
    bc = BattleContext(seed=310)
    clear_piles(bc)
    setup_hand(bc, DISCOVERY)
    bc.play_card(0)
    assert bc.input_state == InputState.CARD_SELECT
    names = [c.card.name for c in bc.card_select_info.candidates]
    assert len(names) == 3 and len(set(names)) == 3  # 三张互不相同
    bc.choose_card(0)
    assert len(bc.cards.hand) == 1
    gen = bc.cards.hand[0]
    assert gen.card.ctype in ("Attack", "Skill", "Power")
    assert gen.cost == 0  # 本回合 0 费（cost_for_turn）
    assert pile_names(bc, bc.cards.exhaust_pile) == ["Discovery"]


def test_discovery_upgraded_no_exhaust():
    bc = BattleContext(seed=311)
    clear_piles(bc)
    setup_hand_upgraded(bc, DISCOVERY)
    bc.play_card(0)
    bc.choose_card(1)
    assert pile_names(bc, bc.cards.discard_pile) == ["Discovery"]


def test_dramatic_entrance_aoe_innate_exhausts():
    bc = BattleContext(seed=312)
    add_cultist(bc)
    hp0 = [m.hp for m in bc.monsters.monsters]
    setup_hand(bc, DRAMATIC_ENTRANCE)
    bc.play_card(0)
    assert [m.hp for m in bc.monsters.monsters] == [h - 8 for h in hp0]
    assert DRAMATIC_ENTRANCE.innate
    assert pile_names(bc, bc.cards.exhaust_pile) == ["Dramatic Entrance"]


def test_dramatic_entrance_upgraded_12():
    bc = BattleContext(seed=313)
    m = bc.monsters.monsters[0]
    hp0 = m.hp
    setup_hand_upgraded(bc, DRAMATIC_ENTRANCE)
    bc.play_card(0)
    assert m.hp == hp0 - 12


def test_enlightenment_reduces_hand_costs_this_turn():
    bc = BattleContext(seed=314)
    setup_hand(bc, ENLIGHTENMENT, BLUDGEON, CLEAVE, WHIRLWIND)
    bludgeon, cleave, whirl = bc.cards.hand[1], bc.cards.hand[2], bc.cards.hand[3]
    bc.play_card(0)
    assert bludgeon.cost == 1
    assert cleave.cost == 1
    assert whirl.cost == -1  # X 费不受影响
    bc.cards.reset_attributes_at_end_of_turn()
    assert bludgeon.cost == 3  # 本回合结束复原
    assert cleave.cost == 1  # 原本就 1 费


def test_enlightenment_upgraded_permanent():
    bc = BattleContext(seed=315)
    setup_hand_upgraded(bc, ENLIGHTENMENT, BLUDGEON)
    bludgeon = bc.cards.hand[1]
    bc.play_card(0)
    assert bludgeon.cost == 1
    bc.cards.reset_attributes_at_end_of_turn()
    assert bludgeon.cost == 1  # 升级版永久 1 费（cost_override）


def test_finesse_block_and_draw():
    bc = BattleContext(seed=316)
    bc.player.block = 0
    setup_hand(bc, FINESSE)
    bc.play_card(0)
    assert bc.player.block == 2
    assert len(bc.cards.hand) == 1  # 抽 1


def test_finesse_upgraded_block_4():
    bc = BattleContext(seed=317)
    setup_hand_upgraded(bc, FINESSE)
    bc.play_card(0)
    assert bc.player.block == 4


def test_flash_of_steel_damage_and_draw():
    bc = BattleContext(seed=318)
    m = bc.monsters.monsters[0]
    hp0 = m.hp
    setup_hand(bc, FLASH_OF_STEEL)
    bc.play_card(0)
    assert m.hp == hp0 - 3
    assert len(bc.cards.hand) == 1
    assert not any(c.card.name == "Flash of Steel" for c in bc.cards.exhaust_pile)  # 不消耗


def test_flash_of_steel_upgraded_6():
    bc = BattleContext(seed=319)
    m = bc.monsters.monsters[0]
    hp0 = m.hp
    setup_hand_upgraded(bc, FLASH_OF_STEEL)
    bc.play_card(0)
    assert m.hp == hp0 - 6


def test_forethought_bottom_of_draw_pile_free():
    bc = BattleContext(seed=320)
    clear_piles(bc)
    bc.cards.draw_pile.append(bc.cards.instantiate(STRIKE))
    setup_hand(bc, FORETHOUGHT, BLUDGEON)
    bludgeon = bc.cards.hand[1]
    bc.play_card(0)
    # 单候选直执：不进选卡状态
    assert bc.input_state == InputState.PLAYER_NORMAL
    assert bc.cards.draw_pile[0] is bludgeon  # 堆底（堆顶 = 列表尾）
    assert bc.cards.draw_pile[-1].card.name == "Strike"
    assert bludgeon.cost == 0  # 0 费直到打出
    assert bc.cards.hand == []


def test_forethought_upgraded_any_number():
    bc = BattleContext(seed=321)
    clear_piles(bc)
    setup_hand_upgraded(bc, FORETHOUGHT, STRIKE, DEFEND)
    strike, defend = bc.cards.hand[1], bc.cards.hand[2]
    bc.play_card(0)
    assert bc.input_state == InputState.CARD_SELECT
    bc.choose_cards([0, 1])
    assert strike.cost == 0 and defend.cost == 0
    assert {c.card.name for c in bc.cards.draw_pile} == {"Strike", "Defend"}
    assert bc.cards.hand == []


def test_good_instincts_block():
    bc = BattleContext(seed=322)
    setup_hand(bc, GOOD_INSTINCTS)
    bc.play_card(0)
    assert bc.player.block == 6


def test_good_instincts_upgraded_block_9():
    bc = BattleContext(seed=323)
    setup_hand_upgraded(bc, GOOD_INSTINCTS)
    bc.play_card(0)
    assert bc.player.block == 9


def test_impatience_draws_when_no_attacks():
    bc = BattleContext(seed=324)
    setup_hand(bc, IMPATIENCE, DEFEND, DEFEND)
    bc.play_card(0)
    assert len(bc.cards.hand) == 4  # 剩 2 + 抽 2


def test_impatience_no_draw_with_attack_in_hand():
    bc = BattleContext(seed=325)
    setup_hand(bc, IMPATIENCE, STRIKE)
    bc.play_card(0)
    assert len(bc.cards.hand) == 1  # 有攻击牌不抽


def test_impatience_upgraded_draws_3():
    bc = BattleContext(seed=326)
    setup_hand_upgraded(bc, IMPATIENCE, DEFEND, DEFEND)
    bc.play_card(0)
    assert len(bc.cards.hand) == 5


def test_jack_of_all_trades_random_colorless_in_hand():
    bc = BattleContext(seed=327)
    clear_piles(bc)
    setup_hand(bc, JACK_OF_ALL_TRADES)
    bc.play_card(0)
    assert len(bc.cards.hand) == 1
    gen = bc.cards.hand[0]
    assert gen.card.colorless
    assert gen.card.name != "Bandage Up"  # CombatColorlessCardPool 排除
    assert pile_names(bc, bc.cards.exhaust_pile) == ["Jack of All Trades"]


def test_jack_of_all_trades_upgraded_two_cards():
    bc = BattleContext(seed=328)
    clear_piles(bc)
    setup_hand_upgraded(bc, JACK_OF_ALL_TRADES)
    bc.play_card(0)
    assert len(bc.cards.hand) == 2
    assert all(c.card.colorless for c in bc.cards.hand)


def test_madness_random_card_zero_cost():
    bc = BattleContext(seed=329)
    setup_hand(bc, MADNESS, BLUDGEON, DEFEND)
    bludgeon, defend = bc.cards.hand[1], bc.cards.hand[2]
    bc.play_card(0)
    assert (bludgeon.cost == 0) != (defend.cost == 0)  # 恰一张被改为 0 费
    assert pile_names(bc, bc.cards.exhaust_pile) == ["Madness"]


def test_madness_noop_without_positive_cost():
    bc = BattleContext(seed=330)
    setup_hand(bc, MADNESS, GOOD_INSTINCTS, FINESSE)  # 全 0 费手牌
    bc.play_card(0)
    assert all(c.cost == 0 for c in bc.cards.hand)
    assert len(bc.cards.hand) == 2


def test_madness_upgraded_cost_zero():
    inst = BattleContext(seed=331).cards.instantiate(MADNESS)
    assert inst.cost == 1
    inst.upgrade()
    assert inst.cost == 0


def test_mind_blast_damage_equals_draw_pile():
    bc = BattleContext(seed=332)
    clear_piles(bc)
    for _ in range(7):
        bc.cards.draw_pile.append(bc.cards.instantiate(DEFEND))
    m = bc.monsters.monsters[0]
    m.hp = m.max_hp = 100
    setup_hand(bc, MIND_BLAST)
    bc.play_card(0)
    assert m.hp == 100 - 7


def test_mind_blast_innate_and_upgrade_cost():
    assert MIND_BLAST.innate
    inst = BattleContext(seed=333).cards.instantiate(MIND_BLAST)
    assert inst.cost == 2
    inst.upgrade()
    assert inst.cost == 1


def test_panacea_grants_artifact_and_exhausts():
    bc = BattleContext(seed=334)
    setup_hand(bc, PANACEA, BLIND)
    bc.play_card(0)
    assert bc.player.statuses.get(PlayerStatus.ARTIFACT) == 1
    bc.play_card(0, target=0)  # 后续出牌不受影响
    assert pile_names(bc, bc.cards.exhaust_pile) == ["Panacea"]
    # ARTIFACT 拦的是"对玩家的 debuff"（怪物施加），此处仅验证状态与消耗落地


def test_panacea_upgraded_two_artifacts():
    bc = BattleContext(seed=335)
    setup_hand_upgraded(bc, PANACEA)
    bc.play_card(0)
    assert bc.player.statuses.get(PlayerStatus.ARTIFACT) == 2


def test_panic_button_block_and_no_block():
    bc = BattleContext(seed=336)
    setup_hand(bc, PANIC_BUTTON, DEFEND)
    bc.play_card(0)
    assert bc.player.block == 30
    assert bc.player.statuses.get(PlayerStatus.NO_BLOCK) == 2
    bc.play_card(0)
    assert bc.player.block == 30  # NO_BLOCK：后续格挡被拦
    assert pile_names(bc, bc.cards.exhaust_pile) == ["Panic Button"]


def test_panic_button_upgraded_block_40():
    bc = BattleContext(seed=337)
    setup_hand_upgraded(bc, PANIC_BUTTON)
    bc.play_card(0)
    assert bc.player.block == 40


def test_purity_exhaust_up_to_three():
    bc = BattleContext(seed=338)
    setup_hand(bc, PURITY, STRIKE, STRIKE, DEFEND)
    strike2, defend = bc.cards.hand[2], bc.cards.hand[3]
    bc.play_card(0)
    assert bc.input_state == InputState.CARD_SELECT
    assert bc.card_select_info.pick_count == 3
    bc.choose_cards([1, 2])  # 候选（自身已离手）中选 STRIKE2 + DEFEND，少于上限
    assert {c.card.name for c in bc.cards.exhaust_pile} == {"Purity", "Strike", "Defend"}
    assert strike2 in bc.cards.exhaust_pile and defend in bc.cards.exhaust_pile
    assert [c.card.name for c in bc.cards.hand] == ["Strike"]  # 未选中的 STRIKE1 留手


def test_purity_upgraded_pick_count_5():
    bc = BattleContext(seed=339)
    setup_hand_upgraded(bc, PURITY, STRIKE, STRIKE)
    bc.play_card(0)
    assert bc.card_select_info.pick_count == 5
    bc.choose_cards([0])  # 选 1 张
    assert len(bc.cards.exhaust_pile) == 2


def test_swift_strike_damage():
    bc = BattleContext(seed=340)
    m = bc.monsters.monsters[0]
    hp0 = m.hp
    setup_hand(bc, SWIFT_STRIKE)
    bc.play_card(0)
    assert m.hp == hp0 - 7
    assert not any(c.card.name == "Swift Strike" for c in bc.cards.exhaust_pile)  # 不消耗


def test_swift_strike_upgraded_10():
    bc = BattleContext(seed=341)
    m = bc.monsters.monsters[0]
    hp0 = m.hp
    setup_hand_upgraded(bc, SWIFT_STRIKE)
    bc.play_card(0)
    assert m.hp == hp0 - 10


def test_trip_single_target_vulnerable():
    bc = BattleContext(seed=342)
    c2 = add_cultist(bc)
    setup_hand(bc, TRIP)
    bc.play_card(0, target=1)
    assert c2.statuses.get(MonsterStatus.VULNERABLE) == 2
    assert not bc.monsters.monsters[0].statuses.has(MonsterStatus.VULNERABLE)
    assert bc.player.energy == 3  # 0 费（wiki 口径，此前误记 1）


def test_trip_upgraded_all_enemies_vulnerable():
    bc = BattleContext(seed=343)
    add_cultist(bc)
    setup_hand_upgraded(bc, TRIP)
    bc.play_card(0, target=0)
    assert all(m.statuses.get(MonsterStatus.VULNERABLE) == 2 for m in bc.monsters.monsters)


# ---- 稀有（rare）14 张 ----


def test_apotheosis_upgrades_all_piles():
    bc = BattleContext(seed=344)
    clear_piles(bc)
    strike = bc.cards.instantiate(STRIKE)
    defend = bc.cards.instantiate(DEFEND)
    burn = bc.cards.instantiate(BURN)
    slimed = bc.cards.instantiate(SLIMED)
    bc.cards.draw_pile.append(strike)
    bc.cards.discard_pile.append(defend)
    bc.cards.exhaust_pile.extend([burn, slimed])
    setup_hand(bc, APOTHEOSIS)
    apo = bc.cards.hand[0]
    bc.play_card(0)
    assert strike.upgraded and defend.upgraded
    assert not burn.upgraded and not slimed.upgraded  # 状态/诅咒卡不升级
    assert not apo.upgraded  # 自身已落消耗堆但不被升级（对齐 C++ 时序）
    assert pile_names(bc, bc.cards.exhaust_pile) == ["Burn", "Slimed", "Apotheosis"]


def test_apotheosis_advances_searing_blow_count():
    bc = BattleContext(seed=345)
    setup_hand(bc, APOTHEOSIS)
    sb = bc.cards.instantiate(SEARING_BLOW)
    sb.upgraded = True
    bc.cards.hand.append(sb)
    bc.play_card(0)
    assert sb.misc_data == 1  # 可多次升级：已升级实例递增计数


def test_apotheosis_upgraded_cost_1():
    inst = BattleContext(seed=346).cards.instantiate(APOTHEOSIS)
    assert inst.cost == 2
    inst.upgrade()
    assert inst.cost == 1


def test_chrysalis_random_skills_into_draw_zero_cost():
    bc = BattleContext(seed=347)
    clear_piles(bc)
    setup_hand(bc, CHRYSALIS)
    bc.play_card(0)
    assert len(bc.cards.draw_pile) == 3
    assert all(c.card.ctype == "Skill" for c in bc.cards.draw_pile)
    assert all(c.cost == 0 for c in bc.cards.draw_pile)  # 本场 0 费
    assert pile_names(bc, bc.cards.exhaust_pile) == ["Chrysalis"]


def test_chrysalis_upgraded_five_cards():
    bc = BattleContext(seed=348)
    clear_piles(bc)
    setup_hand_upgraded(bc, CHRYSALIS)
    bc.play_card(0)
    assert len(bc.cards.draw_pile) == 5


def test_metamorphosis_random_attacks_into_draw():
    bc = BattleContext(seed=349)
    clear_piles(bc)
    setup_hand(bc, METAMORPHOSIS)
    bc.play_card(0)
    assert len(bc.cards.draw_pile) == 3
    assert all(c.card.ctype == "Attack" for c in bc.cards.draw_pile)
    assert all(c.cost == 0 for c in bc.cards.draw_pile)


def test_metamorphosis_upgraded_five_cards():
    bc = BattleContext(seed=350)
    clear_piles(bc)
    setup_hand_upgraded(bc, METAMORPHOSIS)
    bc.play_card(0)
    assert len(bc.cards.draw_pile) == 5
    assert all(c.card.ctype == "Attack" for c in bc.cards.draw_pile)


def test_magnetism_status_and_turn_start_generation():
    bc = BattleContext(seed=351)
    clear_piles(bc)
    for _ in range(5):  # 留牌避免"牌耗尽即败"哨兵，并供下回合抽 5
        bc.cards.draw_pile.append(bc.cards.instantiate(STRIKE))
    bc.player.energy = 2
    setup_hand(bc, MAGNETISM)
    bc.play_card(0)
    assert bc.player.statuses.get(PlayerStatus.MAGNETISM) == 1
    assert callable(bc.player.special["magnetism_gen"])
    bc.end_turn()
    # 新回合：钩子生成 1 张无色卡 + 正常抽 5
    gen = [c for c in bc.cards.hand if c.card.colorless]
    assert len(gen) == 1
    assert gen[0].card.name != "Bandage Up"
    assert len([c for c in bc.cards.hand if not c.card.colorless]) == 5
    assert bc.player.statuses.has(PlayerStatus.MAGNETISM)  # Power 持续


def test_magnetism_upgraded_cost_1():
    inst = BattleContext(seed=352).cards.instantiate(MAGNETISM)
    assert inst.cost == 2
    inst.upgrade()
    assert inst.cost == 1


def test_master_of_strategy_draws_and_exhausts():
    bc = BattleContext(seed=353)
    clear_piles(bc)
    for _ in range(4):
        bc.cards.draw_pile.append(bc.cards.instantiate(STRIKE))
    setup_hand(bc, MASTER_OF_STRATEGY)
    bc.play_card(0)
    assert len(bc.cards.hand) == 3
    assert len(bc.cards.draw_pile) == 1
    assert pile_names(bc, bc.cards.exhaust_pile) == ["Master of Strategy"]


def test_master_of_strategy_upgraded_draws_4():
    bc = BattleContext(seed=354)
    clear_piles(bc)
    for _ in range(5):
        bc.cards.draw_pile.append(bc.cards.instantiate(STRIKE))
    setup_hand_upgraded(bc, MASTER_OF_STRATEGY)
    bc.play_card(0)
    assert len(bc.cards.hand) == 4


def test_mayhem_plays_top_card_each_turn():
    bc = BattleContext(seed=355)
    clear_piles(bc)
    m = bc.monsters.monsters[0]
    m.hp = m.max_hp = 100
    top = bc.cards.instantiate(STRIKE)
    bc.cards.draw_pile.append(top)  # 列表尾 = 堆顶
    setup_hand(bc, MAYHEM)
    bc.play_card(0)
    assert bc.player.statuses.get(PlayerStatus.MAYHEM) == 1
    bc.end_turn()
    # 新回合开始：钩子自动打出抽牌堆顶（不消耗该牌）
    assert m.hp == 100 - 6
    assert any(c is top for c in bc.cards.discard_pile)
    assert not any(c is top for c in bc.cards.exhaust_pile)
    assert bc.player.statuses.has(PlayerStatus.MAYHEM)


def test_mayhem_upgraded_cost_1():
    inst = BattleContext(seed=356).cards.instantiate(MAYHEM)
    assert inst.cost == 2
    inst.upgrade()
    assert inst.cost == 1


def test_panache_markers_land():
    bc = BattleContext(seed=357)
    setup_hand(bc, PANACHE)
    bc.play_card(0)
    assert bc.player.special["panache"] == 10
    assert bc.player.special["panache_counter"] == 5
    # Power：打出后移出战斗，不进弃牌/消耗堆
    assert bc.cards.discard_pile == [] and bc.cards.exhaust_pile == []


def test_panache_upgraded_14():
    bc = BattleContext(seed=358)
    setup_hand_upgraded(bc, PANACHE)
    bc.play_card(0)
    assert bc.player.special["panache"] == 14


def test_sadistic_nature_status_lands():
    bc = BattleContext(seed=359)
    setup_hand(bc, SADISTIC_NATURE)
    bc.play_card(0)
    assert bc.player.statuses.get(PlayerStatus.SADISTIC) == 5
    assert bc.cards.discard_pile == [] and bc.cards.exhaust_pile == []


def test_sadistic_nature_upgraded_7():
    bc = BattleContext(seed=360)
    setup_hand_upgraded(bc, SADISTIC_NATURE)
    bc.play_card(0)
    assert bc.player.statuses.get(PlayerStatus.SADISTIC) == 7


def test_secret_technique_auto_single_candidate():
    bc = BattleContext(seed=361)
    clear_piles(bc)
    skill = bc.cards.instantiate(DEFEND)
    attack = bc.cards.instantiate(STRIKE)
    bc.cards.draw_pile.extend([skill, attack])
    setup_hand(bc, SECRET_TECHNIQUE)
    bc.play_card(0)
    assert bc.input_state == InputState.PLAYER_NORMAL  # 单候选直执
    assert skill in bc.cards.hand and skill not in bc.cards.draw_pile
    assert attack in bc.cards.draw_pile
    assert pile_names(bc, bc.cards.exhaust_pile) == ["Secret Technique"]


def test_secret_technique_select_among_many():
    bc = BattleContext(seed=362)
    clear_piles(bc)
    s1 = bc.cards.instantiate(DEFEND)
    s2 = bc.cards.instantiate(FINESSE)  # 0 费技能也入候选
    bc.cards.draw_pile.extend([s1, s2])
    setup_hand(bc, SECRET_TECHNIQUE)
    bc.play_card(0)
    assert bc.input_state == InputState.CARD_SELECT
    bc.choose_card(0)
    assert s1 in bc.cards.hand and s2 in bc.cards.draw_pile


def test_secret_technique_empty_noop():
    bc = BattleContext(seed=363)
    clear_piles(bc)
    bc.cards.draw_pile.append(bc.cards.instantiate(STRIKE))  # 无技能
    setup_hand(bc, SECRET_TECHNIQUE)
    bc.play_card(0)
    assert len(bc.cards.hand) == 0
    assert len(bc.cards.draw_pile) == 1
    assert pile_names(bc, bc.cards.exhaust_pile) == ["Secret Technique"]


def test_secret_technique_upgraded_no_exhaust():
    bc = BattleContext(seed=364)
    clear_piles(bc)
    bc.cards.draw_pile.append(bc.cards.instantiate(DEFEND))
    setup_hand_upgraded(bc, SECRET_TECHNIQUE)
    bc.play_card(0)
    assert pile_names(bc, bc.cards.discard_pile) == ["Secret Technique"]


def test_secret_weapon_auto_single_candidate():
    bc = BattleContext(seed=365)
    clear_piles(bc)
    attack = bc.cards.instantiate(SWIFT_STRIKE)
    bc.cards.draw_pile.append(attack)
    setup_hand(bc, SECRET_WEAPON)
    bc.play_card(0)
    assert attack in bc.cards.hand
    assert pile_names(bc, bc.cards.exhaust_pile) == ["Secret Weapon"]


def test_secret_weapon_empty_noop():
    bc = BattleContext(seed=366)
    clear_piles(bc)
    setup_hand(bc, SECRET_WEAPON)
    bc.play_card(0)
    assert bc.cards.hand == []
    assert pile_names(bc, bc.cards.exhaust_pile) == ["Secret Weapon"]


def test_the_bomb_explodes_after_three_turns():
    bc = BattleContext(seed=367)
    m = bc.monsters.monsters[0]
    m.hp = m.max_hp = 100
    setup_hand(bc, THE_BOMB)
    bc.play_card(0)
    assert bc.player.statuses.get(PlayerStatus.THE_BOMB) == 3
    assert bc.player.special["the_bomb"] == 40
    bc.end_turn()
    assert bc.player.statuses.get(PlayerStatus.THE_BOMB) == 2
    bc.end_turn()
    assert bc.player.statuses.get(PlayerStatus.THE_BOMB) == 1
    bc.end_turn()
    assert m.hp == 100 - 40  # 第 3 个回合末爆发
    assert not bc.player.statuses.has(PlayerStatus.THE_BOMB)


def test_the_bomb_upgraded_50():
    bc = BattleContext(seed=368)
    m = bc.monsters.monsters[0]
    m.hp = m.max_hp = 100
    setup_hand_upgraded(bc, THE_BOMB)
    bc.play_card(0)
    assert bc.player.special["the_bomb"] == 50
    for _ in range(3):
        bc.end_turn()
    assert m.hp == 100 - 50


def test_thinking_ahead_draw2_and_put_on_top():
    bc = BattleContext(seed=369)
    clear_piles(bc)
    for _ in range(2):
        bc.cards.draw_pile.append(bc.cards.instantiate(STRIKE))
    setup_hand(bc, THINKING_AHEAD, DEFEND)
    defend = bc.cards.hand[1]
    bc.play_card(0)
    assert bc.input_state == InputState.CARD_SELECT
    assert len(bc.cards.hand) == 3  # 抽 2 后选卡前
    bc.choose_card(0)  # 选 Defend
    assert bc.cards.draw_pile[-1] is defend  # 堆顶（列表尾）
    assert pile_names(bc, bc.cards.exhaust_pile) == ["Thinking Ahead"]


def test_thinking_ahead_upgraded_no_exhaust():
    bc = BattleContext(seed=370)
    clear_piles(bc)
    for _ in range(2):
        bc.cards.draw_pile.append(bc.cards.instantiate(STRIKE))
    setup_hand_upgraded(bc, THINKING_AHEAD)
    bc.play_card(0)
    bc.choose_card(0)
    assert pile_names(bc, bc.cards.discard_pile) == ["Thinking Ahead"]


def test_transmutation_x_energy_cards():
    bc = BattleContext(seed=371)
    clear_piles(bc)
    bc.player.energy = 2
    setup_hand(bc, TRANSMUTATION)
    bc.play_card(0)
    assert bc.player.energy == 0
    assert len(bc.cards.hand) == 2
    assert all(c.card.colorless and c.cost == 0 for c in bc.cards.hand)
    assert pile_names(bc, bc.cards.exhaust_pile) == ["Transmutation"]


def test_transmutation_zero_energy_noop():
    bc = BattleContext(seed=372)
    clear_piles(bc)
    bc.player.energy = 0
    setup_hand(bc, TRANSMUTATION)
    bc.play_card(0)  # X 费 0 能量仍可打出
    assert bc.cards.hand == []
    assert bc.player.energy == 0


def test_transmutation_upgraded_generates_upgraded_cards():
    bc = BattleContext(seed=373)
    clear_piles(bc)
    bc.player.energy = 1
    setup_hand_upgraded(bc, TRANSMUTATION)
    bc.play_card(0)
    assert len(bc.cards.hand) == 1
    assert bc.cards.hand[0].upgraded
    assert bc.cards.hand[0].cost == 0


def test_transmutation_hand_full_overflows_to_discard():
    bc = BattleContext(seed=374)
    clear_piles(bc)
    bc.player.energy = 2
    setup_hand(bc, TRANSMUTATION, *([STRIKE] * 9))  # 10 张满手
    bc.play_card(0)
    assert len(bc.cards.hand) == 10  # 9 + 1
    assert len(bc.cards.discard_pile) == 1  # 第 2 张溢出弃牌堆
    assert bc.cards.discard_pile[0].card.colorless


def test_violence_pulls_attacks_from_draw():
    bc = BattleContext(seed=375)
    clear_piles(bc)
    attacks = [bc.cards.instantiate(STRIKE) for _ in range(3)]
    defends = [bc.cards.instantiate(DEFEND) for _ in range(2)]
    bc.cards.draw_pile.extend(attacks + defends)
    setup_hand(bc, VIOLENCE)
    bc.play_card(0)
    assert len(bc.cards.hand) == 3  # 移动非复制
    assert all(c.card.ctype == "Attack" for c in bc.cards.hand)
    assert all(c in bc.cards.draw_pile for c in defends)
    assert not any(c in bc.cards.draw_pile for c in attacks)
    assert pile_names(bc, bc.cards.exhaust_pile) == ["Violence"]


def test_violence_upgraded_four():
    bc = BattleContext(seed=376)
    clear_piles(bc)
    for _ in range(5):
        bc.cards.draw_pile.append(bc.cards.instantiate(STRIKE))
    setup_hand_upgraded(bc, VIOLENCE)
    bc.play_card(0)
    assert len(bc.cards.hand) == 4
    assert len(bc.cards.draw_pile) == 1


def test_violence_fewer_attacks_than_count():
    bc = BattleContext(seed=377)
    clear_piles(bc)
    for _ in range(2):
        bc.cards.draw_pile.append(bc.cards.instantiate(SWIFT_STRIKE))
    setup_hand(bc, VIOLENCE)  # 要 3 张只有 2
    bc.play_card(0)
    assert len(bc.cards.hand) == 2


def test_violence_empty_draw_noop():
    bc = BattleContext(seed=378)
    clear_piles(bc)
    for _ in range(2):
        bc.cards.draw_pile.append(bc.cards.instantiate(DEFEND))  # 无攻击牌
    setup_hand(bc, VIOLENCE)
    bc.play_card(0)
    assert bc.cards.hand == []
    assert len(bc.cards.draw_pile) == 2


def test_violence_hand_full_overflows_to_discard():
    bc = BattleContext(seed=379)
    clear_piles(bc)
    for _ in range(3):
        bc.cards.draw_pile.append(bc.cards.instantiate(STRIKE))
    setup_hand(bc, VIOLENCE, *([DEFEND] * 9))  # 10 张满手
    bc.play_card(0)
    assert len(bc.cards.hand) == 10  # 9 + 1
    assert len(bc.cards.discard_pile) == 2  # 溢出 2 张


# ---- 生成池口径 ----


def test_colorless_combat_pool_excludes_bandage_up():
    from sts.content.cards.colorless import _random_colorless_card

    bc = BattleContext(seed=380)
    names = {_random_colorless_card(bc).name for _ in range(300)}
    assert "Bandage Up" not in names
    assert "Hand of Greed" in names  # 定义在 cards.py 的无色卡同样入池
    assert len(names) >= 30

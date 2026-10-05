"""Stance 子系统（批次 E 前置）测试：姿态切换钩子链 / 伤害乘区 /
真言-Divinity 链 / LIKE_WATER / DEVOTION / WRATH_NEXT_TURN / DIVINITY 回中性。"""

from sts.combat import BattleContext
from sts.combat.actions import Actions
from sts.combat.types import InputState, PlayerStatus, Stance
from sts.content.cards import STRIKE

from tests.test_engine_batch0 import run_queue, setup_hand


def test_change_stance_same_is_noop():
    bc = BattleContext(seed=301)
    assert bc.player.stance == Stance.NEUTRAL
    bc.player.change_stance(bc, Stance.CALM)
    assert bc.player.stance == Stance.CALM
    block0 = bc.player.block
    bc.player.change_stance(bc, Stance.CALM)  # 同姿态：no-op（不触发 MENTAL_FORTRESS 等）
    assert bc.player.block == block0


def test_wrath_doubles_player_damage():
    bc = BattleContext(seed=302)
    m = bc.monsters.monsters[0]
    setup_hand(bc, STRIKE)
    hp0 = m.hp
    bc.player.change_stance(bc, Stance.WRATH)
    bc.play_card(0)
    assert m.hp == hp0 - 12  # 6 × 2


def test_divinity_triples_and_resets():
    bc = BattleContext(seed=303, deck=[STRIKE] * 15)
    m = bc.monsters.monsters[0]
    bc.player.change_stance(bc, Stance.DIVINITY)
    setup_hand(bc, STRIKE)
    hp0 = m.hp
    bc.play_card(0)
    assert m.hp == hp0 - 18  # 6 × 3
    bc.end_turn()  # 下回合开始回 NEUTRAL
    assert bc.player.stance == Stance.NEUTRAL


def test_rushdown_draws_on_wrath_entry():
    bc = BattleContext(seed=304, deck=[STRIKE] * 15)
    bc.player.statuses.add(PlayerStatus.RUSHDOWN, 1)
    bc.cards.hand.clear()
    bc.player.change_stance(bc, Stance.WRATH)
    run_queue(bc)
    assert len(bc.cards.hand) == 2


def test_mental_fortress_blocks_on_any_stance_entry():
    bc = BattleContext(seed=305)
    bc.player.statuses.add(PlayerStatus.MENTAL_FORTRESS, 2)
    bc.player.change_stance(bc, Stance.CALM)
    run_queue(bc)
    assert bc.player.block == 6  # 3 × 2 层


def test_mantra_ten_enters_divinity():
    bc = BattleContext(seed=306, deck=[STRIKE] * 15)
    bc.add_to_bot(Actions.gain_mantra(9))
    run_queue(bc)
    assert bc.player.statuses.get(PlayerStatus.MANTRA) == 9
    assert bc.player.stance == Stance.NEUTRAL
    bc.add_to_bot(Actions.gain_mantra(1))
    run_queue(bc)
    assert not bc.player.statuses.has(PlayerStatus.MANTRA)  # 清零
    run_queue(bc)
    assert bc.player.stance == Stance.DIVINITY


def test_devotion_grants_mantra_per_turn():
    bc = BattleContext(seed=307, deck=[STRIKE] * 15)
    bc.player.statuses.add(PlayerStatus.DEVOTION, 3)
    bc.end_turn()
    assert bc.player.statuses.get(PlayerStatus.MANTRA) == 3
    bc.end_turn()
    assert bc.player.statuses.get(PlayerStatus.MANTRA) == 6


def test_like_water_calm_end_of_turn_block():
    """CALM 回合末得格挡：格挡只在敌方回合有效（回合开始清零），观察点
    是敌方攻击的吸收量（Cultist 第 2 回合 Dark Strike 6 伤）。"""
    bc = BattleContext(seed=308, deck=[STRIKE] * 15)
    m = bc.monsters.monsters[0]
    m.set_move(m.__class__.DARK_STRIKE)  # 强制下回合攻击
    bc.player.statuses.add(PlayerStatus.LIKE_WATER, 3)
    bc.player.change_stance(bc, Stance.CALM)
    bc.end_turn()
    assert bc.player.hp == 80 - 3  # 6 攻击 - 3 如水格挡（回合 2：仪式 skipFirst 尚无力量）
    # 非平静（WRATH）不触发：受满额伤害。set 的 DARK_STRIKE 在敌方回合 2
    # 执行（ Ritual 的 +3 要到回合 2 末才结算，故攻击仍 6）——全额命中
    m.set_move(m.__class__.DARK_STRIKE)
    bc.player.change_stance(bc, Stance.WRATH)
    bc.end_turn()
    assert bc.player.hp == 80 - 3 - 6  # WRATH 下无如水格挡


def test_wrath_next_turn_enters_wrath():
    bc = BattleContext(seed=309, deck=[STRIKE] * 15)
    bc.player.statuses.add(PlayerStatus.WRATH_NEXT_TURN, 1)
    bc.end_turn()
    assert bc.player.stance == Stance.WRATH
    assert not bc.player.statuses.has(PlayerStatus.WRATH_NEXT_TURN)

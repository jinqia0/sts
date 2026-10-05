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
    assert bc.player.block == 8  # 4 × 2 层（wiki 常量）


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
    是敌方攻击的吸收量（Cultist Dark Strike 6 伤）。wiki：5/7 格挡按层直读。"""
    bc = BattleContext(seed=308, deck=[STRIKE] * 15)
    m = bc.monsters.monsters[0]
    m.set_move(m.__class__.DARK_STRIKE)
    bc.player.statuses.add(PlayerStatus.LIKE_WATER, 5)
    bc.player.change_stance(bc, Stance.CALM)
    bc.end_turn()
    assert bc.player.hp == 80 - 6 + 5  # 6 攻击 - 5 如水格挡
    # 非平静（WRATH）不触发如水；且 WRATH 承伤 ×2 → 12 伤全额
    m.set_move(m.__class__.DARK_STRIKE)
    bc.player.change_stance(bc, Stance.WRATH)
    bc.end_turn()
    assert bc.player.hp == 80 - 6 + 5 - 12

def test_wrath_next_turn_enters_wrath():
    bc = BattleContext(seed=309, deck=[STRIKE] * 15)
    bc.player.statuses.add(PlayerStatus.WRATH_NEXT_TURN, 1)
    bc.end_turn()
    assert bc.player.stance == Stance.WRATH
    assert not bc.player.statuses.has(PlayerStatus.WRATH_NEXT_TURN)


# ---- Watcher 批次 E 补接线回归 ----


def test_nirvana_scry_grants_block():
    from sts.combat import BattleContext
    from sts.content.cards import STRIKE, WOUND

    bc = BattleContext(seed=320, deck=[STRIKE] * 10)
    bc.cards.draw_pile.clear()
    bc.cards.draw_pile.append(bc.cards.instantiate(WOUND))
    bc.cards.draw_pile.append(bc.cards.instantiate(STRIKE))
    bc.cards.draw_pile.append(bc.cards.instantiate(STRIKE))
    bc.player.special["nirvana"] = 3
    bc.open_scry(3)
    bc.choose_scry(1)  # 弃 2 张 → +6 格挡
    assert bc.player.block == 6
    assert "nirvana" not in bc.player.special


def test_swivel_makes_next_attack_free():
    from sts.combat import BattleContext
    from sts.content.cards import STRIKE

    bc = BattleContext(seed=321, deck=[STRIKE] * 10)
    bc.cards.hand.clear()
    bc.cards.hand.append(bc.cards.instantiate(STRIKE))
    bc.player.energy = 1
    bc.player.special["swivel"] = True
    bc.play_card(0)
    assert bc.player.energy == 1  # 0 费打出
    assert "swivel" not in bc.player.special


def test_retained_card_increments():
    from sts.combat import BattleContext
    from sts.content.watcher_cards import PERSEVERANCE, WINDMILL_STRIKE, SANDS_OF_TIME

    bc = BattleContext(seed=322, deck=[STRIKE] * 10)
    bc.cards.hand.clear()
    p = bc.cards.instantiate(PERSEVERANCE)
    w = bc.cards.instantiate(WINDMILL_STRIKE)
    sd = bc.cards.instantiate(SANDS_OF_TIME)
    sd.cost_override = 2
    for inst in (p, w, sd):
        bc.cards.hand.append(inst)
        inst.retain = True
    bc.end_turn()
    assert p.misc_data == 2  # 保留一回合 +2
    assert w.misc_data == 4
    assert sd.cost == 1  # -1 费


def test_establishment_discounts_retained():
    from sts.combat import BattleContext
    from sts.content.cards import STRIKE
    from sts.content.watcher_cards import PROTECT

    bc = BattleContext(seed=323, deck=[STRIKE] * 10)
    bc.player.special["establishment"] = 1
    bc.cards.hand.clear()
    inst = bc.cards.instantiate(PROTECT)
    bc.cards.hand.append(inst)
    inst.retain = True
    cost0 = inst.cost
    bc.end_turn()
    assert inst.cost == max(0, cost0 - 1)

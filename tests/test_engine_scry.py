"""Scry 子系统（批次 E 前置）测试：堆顶展示序/保留弃置/不触发弃牌触发器/
抽牌堆耗尽/空堆跳过。"""

from sts.combat import BattleContext
from sts.combat.actions import Actions
from sts.combat.types import InputState
from sts.content.cards import STRIKE, WOUND
from sts.content.monsters import Cultist

from tests.test_engine_batch0 import run_queue


def _scry_battle():
    bc = BattleContext(seed=401, deck=[STRIKE] * 10)
    bc.cards.draw_pile.clear()
    # 构造已知堆序：draw_pile 尾 = 堆顶。自底向上放 A,B,C,D（堆顶 D）
    for name in ("A", "B", "C", "D"):
        pass
    return bc


def test_scry_shows_top_and_orders():
    bc = BattleContext(seed=402, deck=[STRIKE] * 10)
    bc.cards.draw_pile.clear()
    top = bc.cards.instantiate(WOUND)
    second = bc.cards.instantiate(STRIKE)
    bc.cards.draw_pile.append(second)  # 先放
    bc.cards.draw_pile.append(top)  # 后放 = 堆顶（尾）
    bc.open_scry(2)
    assert bc.input_state == InputState.SCRY
    assert bc.scry_cards[0] is top  # [0] = 堆顶
    assert bc.scry_cards[1] is second
    bc.choose_scry(1)  # 保留堆顶 1 张，弃 second
    assert top in bc.cards.draw_pile
    assert second in bc.cards.discard_pile
    # 选择后主循环恢复推进，回 PLAYER_NORMAL
    assert bc.input_state == InputState.PLAYER_NORMAL


def test_scry_keeps_all_or_none():
    bc = BattleContext(seed=403, deck=[STRIKE] * 10)
    bc.cards.draw_pile.clear()
    for _ in range(3):
        bc.cards.draw_pile.append(bc.cards.instantiate(STRIKE))
    bc.open_scry(3)
    assert len(bc.scry_cards) == 3
    bc.choose_scry(3)  # 全保留
    assert len(bc.cards.draw_pile) == 3
    assert len(bc.cards.discard_pile) == 0
    bc.open_scry(3)
    bc.choose_scry(0)  # 全弃
    assert len(bc.cards.draw_pile) == 0
    assert len(bc.cards.discard_pile) == 3


def test_scry_discard_not_manual():
    """Scry 弃置不触发 Tingsha（手动弃牌触发器）。"""
    from sts.combat.relics import RelicId

    bc = BattleContext(seed=404, deck=[STRIKE] * 10, relics=[RelicId.TINGSHA])
    m = bc.monsters.monsters[0]
    hp0 = m.hp
    bc.cards.draw_pile.clear()
    bc.cards.draw_pile.append(bc.cards.instantiate(STRIKE))
    bc.open_scry(1)
    bc.choose_scry(0)
    assert m.hp == hp0  # 无 3 伤（非 manual_discard）


def test_scry_empty_draw_pile_skips():
    bc = BattleContext(seed=405, deck=[STRIKE] * 5)
    bc.cards.draw_pile.clear()
    bc.cards.discard_pile.clear()
    bc.open_scry(2)
    assert bc.input_state == InputState.PLAYER_NORMAL or bc.input_state == InputState.EXECUTING_ACTIONS
    assert bc.scry_cards == []


def test_scry_count_capped_by_pile():
    bc = BattleContext(seed=406, deck=[STRIKE] * 10)
    bc.cards.draw_pile.clear()
    bc.cards.draw_pile.append(bc.cards.instantiate(STRIKE))
    bc.open_scry(5)  # 只 1 张
    assert len(bc.scry_cards) == 1
    bc.choose_scry(0)
    assert len(bc.cards.discard_pile) == 1

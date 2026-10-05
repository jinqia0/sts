"""铁甲战士 Act 1 卡牌移植断言（对齐 lightspeed useXxxCard 的逐卡 switch）。

构造手牌沿用 test_combat.py::test_bash_vulnerable_window 的模式：
bc.cards.instantiate(CardDef) + bc.cards.hand.append(...) + bc.play_card(...)，
保证出牌序列确定、不依赖初始洗牌。

多敌人卡（Cleave/Thunderclap）在默认单怪遭遇上追加一个邪教徒
（仅测试内构造，不出现在 encounters 注册表）。
"""

from sts.combat import BattleContext
from sts.combat.types import MonsterStatus, PlayerStatus
from sts.content.cards import (
    ANGER,
    BATTLE_TRANCE,
    BODY_SLAM,
    CLEAVE,
    CLOTHESLINE,
    DEFEND,
    FLEX,
    INFLAME,
    IRON_WAVE,
    METALLICIZE,
    POMMEL_STRIKE,
    SHRUG_IT_OFF,
    STRIKE,
    THUNDERCLAP,
    TWIN_STRIKE,
    WILD_STRIKE,
)
from sts.content.monsters import Cultist


def setup_hand(bc: BattleContext, *cards) -> None:
    """清空手牌并按序放入指定卡（初始 5 张手牌直接丢弃，不进任何牌堆）。"""
    bc.cards.hand.clear()
    for c in cards:
        bc.cards.hand.append(bc.cards.instantiate(c))


def add_cultist(bc: BattleContext, idx: int = 1, hp: int = 50) -> Cultist:
    """追加一个邪教徒（多敌人全体效果测试用）。"""
    m = Cultist(idx=idx, hp=hp, max_hp=hp)
    m.set_move(Cultist.INCANTATION)
    bc.monsters.add(m)
    return m


# ---- 攻击卡：数值 ----


def test_cleave_hits_all_enemies():
    """顺劈斩：对所有敌人 8 伤（逐怪走完整伤害管线）。"""
    bc = BattleContext(seed=30)
    m1 = add_cultist(bc)
    hp0 = [m.hp for m in bc.monsters.monsters]
    setup_hand(bc, CLEAVE)
    bc.play_card(0)
    assert [m.hp for m in bc.monsters.monsters] == [hp0[0] - 8, hp0[1] - 8]


def test_cleave_settles_in_order_skipping_dead():
    """顺劈斩按索引序结算：前一个怪被打死，后一个怪仍然吃满伤害。"""
    bc = BattleContext(seed=31)
    m1 = add_cultist(bc)
    bc.monsters.monsters[0].hp = 8
    setup_hand(bc, CLEAVE)
    bc.play_card(0)
    assert bc.monsters.monsters[0].hp == 0
    assert m1.hp == 50 - 8


def test_twin_strike_two_hits():
    """双斩：两段 5 伤，共 10。"""
    bc = BattleContext(seed=32)
    m = bc.monsters.monsters[0]
    hp0 = m.hp
    setup_hand(bc, TWIN_STRIKE)
    bc.play_card(0)
    assert m.hp == hp0 - 10


def test_twin_strike_breaks_block_between_hits():
    """双斩逐段结算：7 格挡吃掉第一段 5，第二段 5 打穿 → HP 掉 3。"""
    bc = BattleContext(seed=33)
    m = bc.monsters.monsters[0]
    m.block = 7
    hp0 = m.hp
    setup_hand(bc, TWIN_STRIKE)
    bc.play_card(0)
    assert m.hp == hp0 - 3
    assert m.block == 0


def test_iron_wave_block_and_damage():
    """铁波：5 格挡 + 5 伤（先格挡后攻击，addToBot 顺序）。"""
    bc = BattleContext(seed=34)
    m = bc.monsters.monsters[0]
    hp0 = m.hp
    setup_hand(bc, IRON_WAVE)
    bc.play_card(0)
    assert bc.player.block == 5
    assert m.hp == hp0 - 5


def test_pommel_strike_damage_and_draw():
    """剑柄打击：9 伤 + 抽 1。"""
    bc = BattleContext(seed=35)
    m = bc.monsters.monsters[0]
    hp0 = m.hp
    draw0 = len(bc.cards.draw_pile)
    setup_hand(bc, POMMEL_STRIKE)
    bc.play_card(0)
    assert m.hp == hp0 - 9
    assert len(bc.cards.hand) == 1  # 抽到 1 张
    assert len(bc.cards.draw_pile) == draw0 - 1


def test_clothesline_damage_and_weak():
    """锁喉：12 伤 + 2 层虚弱（玩家施加，当轮回合末即递减）。"""
    bc = BattleContext(seed=36)
    m = bc.monsters.monsters[0]
    hp0 = m.hp
    setup_hand(bc, CLOTHESLINE)
    bc.play_card(0)
    assert m.hp == hp0 - 12
    assert m.statuses.get(MonsterStatus.WEAK) == 2


def test_thunderclap_all_damage_and_all_vulnerable():
    """雷霆骤雨：全体 4 伤 + 全体 1 层易伤。"""
    bc = BattleContext(seed=37)
    m1 = add_cultist(bc)
    hp0 = [m.hp for m in bc.monsters.monsters]
    setup_hand(bc, THUNDERCLAP)
    bc.play_card(0)
    assert [m.hp for m in bc.monsters.monsters] == [hp0[0] - 4, hp0[1] - 4]
    assert [m.statuses.get(MonsterStatus.VULNERABLE) for m in bc.monsters.monsters] == [1, 1]


def test_body_slam_damage_equals_current_block():
    """猛击：伤害 = 出牌结算时的当前格挡（仍走伤害管线）。"""
    bc = BattleContext(seed=38)
    m = bc.monsters.monsters[0]
    hp0 = m.hp
    setup_hand(bc, DEFEND, BODY_SLAM)
    bc.play_card(0)  # Defend → 格挡 5
    assert bc.player.block == 5
    bc.play_card(0)  # Body Slam → 5 伤
    assert m.hp == hp0 - 5


def test_wild_strike_damage_and_wound():
    """狂野打击：12 伤 + 1 张伤口洗入抽牌堆（随机位置）。"""
    bc = BattleContext(seed=39)
    m = bc.monsters.monsters[0]
    hp0 = m.hp
    draw0 = len(bc.cards.draw_pile)
    setup_hand(bc, WILD_STRIKE)
    bc.play_card(0)
    assert m.hp == hp0 - 12
    assert len(bc.cards.draw_pile) == draw0 + 1
    wounds = [c for c in bc.cards.draw_pile if c.card.name == "Wound"]
    assert len(wounds) == 1
    # 伤口不可打出
    wound = wounds[0]
    bc.cards.draw_pile.remove(wound)
    bc.cards.hand.append(wound)
    try:
        bc.play_card(len(bc.cards.hand) - 1)
        raise AssertionError("伤口不可打出，应当抛出 ValueError")
    except ValueError as e:
        assert "不可打出" in str(e)
    # 回合末随整手牌弃置
    bc.end_turn()
    assert any(c is wound for c in bc.cards.discard_pile)


def test_anger_copy_redrawable():
    """怒火：6 伤 + 副本进弃牌堆（独立实例），副本可再被抽到并再次结算。"""
    bc = BattleContext(seed=40)
    m = bc.monsters.monsters[0]
    hp0 = m.hp
    bc.cards.hand.clear()
    bc.cards.draw_pile.clear()
    bc.cards.discard_pile.clear()
    bc.cards.hand.append(bc.cards.instantiate(ANGER))
    bc.play_card(0)
    assert m.hp == hp0 - 6
    assert len(bc.cards.discard_pile) == 2  # 打出的本体 + 生成的副本
    assert len({c.unique_id for c in bc.cards.discard_pile}) == 2
    assert all(c.card.name == "Anger" for c in bc.cards.discard_pile)
    # 弃牌堆洗回 → 抽到副本 → 再次打出：又 -6，又生成一份新副本
    bc.cards.move_discard_pile_into_draw_pile()
    bc.draw_cards(1)
    assert len(bc.cards.hand) == 1
    assert bc.cards.hand[0].card.name == "Anger"
    bc.play_card(0)
    assert m.hp == hp0 - 12
    assert len(bc.cards.discard_pile) == 2


# ---- 技能卡：格挡 + 抽牌 ----


def test_shrug_it_off_block_and_draw():
    """耸肩：8 格挡 + 抽 1。"""
    bc = BattleContext(seed=41)
    draw0 = len(bc.cards.draw_pile)
    setup_hand(bc, SHRUG_IT_OFF)
    bc.play_card(0)
    assert bc.player.block == 8
    assert len(bc.cards.hand) == 1
    assert len(bc.cards.draw_pile) == draw0 - 1


def test_flex_temporary_strength():
    """展示肌肉：本回合 +2 力量，回合末扣回（下回合攻击不再享受）。"""
    bc = BattleContext(seed=42)
    m = bc.monsters.monsters[0]
    hp0 = m.hp
    setup_hand(bc, FLEX, STRIKE)
    bc.play_card(0)  # Flex：力量 2（本回合有效）
    assert bc.player.statuses.get(PlayerStatus.STRENGTH) == 2
    assert bc.player.statuses.get(PlayerStatus.LOSE_STRENGTH) == 2
    bc.play_card(0)  # Strike：6+2=8
    assert m.hp == hp0 - 8
    bc.end_turn()  # 回合末：力量扣回，LOSE_STRENGTH 移除（敌回合 1 为咒语）
    assert bc.player.statuses.get(PlayerStatus.STRENGTH) == 0
    assert not bc.player.statuses.has(PlayerStatus.LOSE_STRENGTH)
    bc.cards.hand.append(bc.cards.instantiate(STRIKE))
    bc.play_card(len(bc.cards.hand) - 1)  # 下回合：力量已消失，6 伤
    assert m.hp == hp0 - 8 - 6


def test_battle_trance_draw_then_no_draw():
    """战斗恍惚：抽 3；本回合后续抽牌被 NO_DRAW 拦截；回合末解除。"""
    bc = BattleContext(seed=43)
    draw0 = len(bc.cards.draw_pile)
    setup_hand(bc, BATTLE_TRANCE, SHRUG_IT_OFF)
    bc.play_card(0)  # 抽 3
    assert len(bc.cards.hand) == 1 + 3  # 剩下的耸肩 + 抽到的 3 张
    assert bc.player.statuses.get(PlayerStatus.NO_DRAW) == 1
    assert len(bc.cards.draw_pile) == draw0 - 3
    bc.play_card(0)  # 耸肩：格挡照常，但抽 1 被 NO_DRAW 拦截
    assert bc.player.block == 8
    assert len(bc.cards.hand) == 3
    assert len(bc.cards.draw_pile) == draw0 - 3
    bc.end_turn()  # 回合末解除禁抽 → 回合 2 正常抽 5
    assert not bc.player.statuses.has(PlayerStatus.NO_DRAW)
    assert len(bc.cards.hand) == 5


# ---- 能力卡：打出即移出战斗 ----


def test_inflame_permanent_strength():
    """燃烧：+2 力量，跨回合保留；能力卡打出后不进任何牌堆。"""
    bc = BattleContext(seed=44)
    m = bc.monsters.monsters[0]
    hp0 = m.hp
    setup_hand(bc, INFLAME, STRIKE)
    bc.play_card(0)
    assert bc.player.statuses.get(PlayerStatus.STRENGTH) == 2
    bc.play_card(0)  # Strike：6+2=8
    assert m.hp == hp0 - 8
    all_cards = (
        bc.cards.hand + bc.cards.draw_pile + bc.cards.discard_pile + bc.cards.exhaust_pile
    )
    assert all(c.card.name != "Inflame" for c in all_cards)
    bc.end_turn()  # 敌回合 1 为咒语；力量跨回合保留
    assert bc.player.statuses.get(PlayerStatus.STRENGTH) == 2
    bc.cards.hand.append(bc.cards.instantiate(STRIKE))
    bc.play_card(len(bc.cards.hand) - 1)  # 回合 2 的 Strike 仍享受 +2
    assert m.hp == hp0 - 8 - 8


def test_metallicize_end_of_turn_block():
    """金属化：每回合末 +3 格挡——在下次玩家回合开始清零前吸收过敌方攻击。"""
    bc = BattleContext(seed=45)
    setup_hand(bc, METALLICIZE)
    bc.play_card(0)
    assert bc.player.statuses.get(PlayerStatus.METALLICIZE) == 3
    assert bc.player.hp == 80
    bc.end_turn()  # 回合 1 末 +3 格挡（敌回合 1 咒语不攻击）；回合 2 开始清零
    assert bc.player.hp == 80
    assert bc.player.block == 0
    bc.end_turn()  # 回合 2 末 +3 格挡 → 敌回合 2 黑暗打击 6：吸收 3，掉 3 血
    assert bc.player.hp == 80 - 3
    assert bc.player.block == 0

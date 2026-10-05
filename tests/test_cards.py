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
    BLUDGEON,
    BLOODLETTING,
    BODY_SLAM,
    CLASH,
    CLEAVE,
    CLOTHESLINE,
    DEFEND,
    DISARM,
    DROPKICK,
    ENTRENCH,
    FLEX,
    HEAVY_BLADE,
    HEMOKINESIS,
    IMPERVIOUS,
    INFLAME,
    INTIMIDATE,
    IRON_WAVE,
    LIMIT_BREAK,
    METALLICIZE,
    OFFERING,
    PERFECTED_STRIKE,
    POMMEL_STRIKE,
    PUMMEL,
    REAPER,
    SEEING_RED,
    SHOCKWAVE,
    SHRUG_IT_OFF,
    SPOT_WEAKNESS,
    STRIKE,
    SWORD_BOOMERANG,
    THUNDERCLAP,
    TWIN_STRIKE,
    UPPERCUT,
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


def setup_hand_upgraded(bc: BattleContext, *cards) -> None:
    """清空手牌并按序放入指定卡的升级版。"""
    bc.cards.hand.clear()
    for c in cards:
        inst = bc.cards.instantiate(c)
        inst.upgraded = True
        bc.cards.hand.append(inst)


# ---- 简单档批次 1：20 张卡 ----


def test_clash_requires_all_attack_hand():
    """冲突：手牌含非攻击牌时拒绝打出；全攻击手牌可打出。"""
    bc = BattleContext(seed=46)
    m = bc.monsters.monsters[0]
    hp0 = m.hp
    setup_hand(bc, CLASH, DEFEND)
    try:
        bc.play_card(0)
        raise AssertionError("手牌含防御，冲突不应可打出")
    except ValueError as e:
        assert "打出条件" in str(e)
    setup_hand(bc, CLASH, STRIKE)
    bc.play_card(0)  # Clash 0 费
    assert m.hp == hp0 - 14
    # 升级版 18 伤
    setup_hand_upgraded(bc, CLASH, STRIKE)
    bc.play_card(0)
    assert m.hp == hp0 - 14 - 18


def test_heavy_blade_strength_multiplier():
    """重刃：力量计入 3 次（升级 5 次），基准伤害 14 不随升级变。"""
    bc = BattleContext(seed=47)
    m = bc.monsters.monsters[0]
    bc.player.statuses.add(PlayerStatus.STRENGTH, 2)
    bc.player.energy = 5  # 一回合内连打基础+升级两张
    hp0 = m.hp
    setup_hand(bc, HEAVY_BLADE)
    bc.play_card(0)
    assert m.hp == hp0 - (14 + 2 * 3)  # 14 + 3×2
    setup_hand_upgraded(bc, HEAVY_BLADE)
    bc.play_card(0)
    assert m.hp == hp0 - 20 - (14 + 2 * 5)  # 14 + 5×2


def test_perfected_strike_counts_strikes():
    """完美打击：伤害 = 6 + 2×战斗内打击数（含自身；消耗堆不计）。"""
    bc = BattleContext(seed=48)
    m = bc.monsters.monsters[0]
    hp0 = m.hp
    bc.player.energy = 7  # 三张 2 费
    bc.cards.draw_pile.clear()
    bc.cards.discard_pile.clear()
    # 手牌：2 张打击 + 完美打击本身 → 计数 3（出牌时自身仍按 C++ 时序计入）
    setup_hand(bc, STRIKE, STRIKE, PERFECTED_STRIKE)
    bc.play_card(2)
    assert m.hp == hp0 - (6 + 3 * 2)
    # 清场后再来：弃牌堆的打击也计入 → 计数 = 双斩 1 + 自身 1 = 2
    bc.cards.discard_pile.clear()
    bc.cards.discard_pile.append(bc.cards.instantiate(TWIN_STRIKE))
    setup_hand(bc, PERFECTED_STRIKE)
    bc.play_card(0)
    assert m.hp == hp0 - 12 - (6 + 2 * 2)
    # 升级：每张 +3
    bc.cards.discard_pile.clear()
    bc.cards.discard_pile.append(bc.cards.instantiate(TWIN_STRIKE))
    setup_hand_upgraded(bc, PERFECTED_STRIKE)
    bc.play_card(0)
    assert m.hp == hp0 - 12 - 10 - (6 + 2 * 3)


def test_uppercut_damage_and_debuffs():
    """上勾拳：13 伤 + 1 虚弱 + 1 易伤；升级版伤害仍 13（对齐 C++），层数 2。"""
    bc = BattleContext(seed=49)
    m = bc.monsters.monsters[0]
    bc.player.energy = 4
    hp0 = m.hp
    setup_hand(bc, UPPERCUT)
    bc.play_card(0)
    assert m.hp == hp0 - 13
    assert m.statuses.get(MonsterStatus.WEAK) == 1
    assert m.statuses.get(MonsterStatus.VULNERABLE) == 1
    setup_hand_upgraded(bc, UPPERCUT)
    bc.play_card(0)
    # 升级不加伤（wiki 为 17，以 C++ 为准）；第一张施加的易伤使第二张 13×1.5=19
    assert m.hp == hp0 - 13 - 19
    assert m.statuses.get(MonsterStatus.WEAK) == 3
    assert m.statuses.get(MonsterStatus.VULNERABLE) == 3


def test_dropkick_no_bonus_without_vulnerable():
    """飞踢：目标无易伤 → 仅 5 伤，不回能不抽牌。"""
    bc = BattleContext(seed=50)
    m = bc.monsters.monsters[0]
    hp0 = m.hp
    setup_hand(bc, DROPKICK)
    bc.play_card(0)
    assert m.hp == hp0 - 5
    assert bc.player.energy == 2  # 3 - 1 费，无加成
    assert len(bc.cards.hand) == 0


def test_dropkick_bonus_on_vulnerable():
    """飞踢：目标有易伤 → 伤害 7（5×1.5）+ 1 能量 + 抽 1。"""
    bc = BattleContext(seed=51)
    m = bc.monsters.monsters[0]
    m.statuses.add(MonsterStatus.VULNERABLE, 1)
    hp0 = m.hp
    setup_hand(bc, DROPKICK)
    bc.play_card(0)
    assert m.hp == hp0 - 7  # floor(5 × 1.5)
    assert bc.player.energy == 3  # 3 - 1 费 + 1
    assert len(bc.cards.hand) == 1
    # 升级：8×1.5 = 12，同样 +1 能量 +抽 1
    setup_hand_upgraded(bc, DROPKICK)
    bc.play_card(0)
    assert m.hp == hp0 - 7 - 12
    assert bc.player.energy == 3  # 3 - 1 + 1
    assert len(bc.cards.hand) == 1


def test_hemokinesis_hp_cost_and_damage():
    """血液激发：失去 2 HP + 15 伤；升级 20 伤（HP 消耗不变）。"""
    bc = BattleContext(seed=52)
    m = bc.monsters.monsters[0]
    hp0 = m.hp
    setup_hand(bc, HEMOKINESIS)
    bc.play_card(0)
    assert bc.player.hp == 80 - 2
    assert m.hp == hp0 - 15
    setup_hand_upgraded(bc, HEMOKINESIS)
    bc.play_card(0)
    assert bc.player.hp == 80 - 4
    assert m.hp == hp0 - 35


def test_pummel_multi_hit_and_exhaust():
    """连续痛击：4 段各 2 伤、逐段结算格挡；消耗。"""
    bc = BattleContext(seed=53)
    m = bc.monsters.monsters[0]
    m.block = 5
    hp0 = m.hp
    setup_hand(bc, PUMMEL)
    bc.play_card(0)
    # 4×2：格挡吸收 5（2+2+1），HP 掉 1+2 = 3
    assert m.hp == hp0 - 3
    assert m.block == 0
    assert any(c.card.name == "Pummel" for c in bc.cards.exhaust_pile)
    # 升级：5 段（对齐 C++：升级加段不加伤）
    m2 = add_cultist(bc, idx=1)
    hp1 = m2.hp
    setup_hand_upgraded(bc, PUMMEL)
    bc.play_card(0, target=1)
    assert m2.hp == hp1 - 10


def test_intimidate_all_weak_and_exhaust():
    """威吓：全体 1 层虚弱；消耗；升级 2 层。"""
    bc = BattleContext(seed=54)
    add_cultist(bc)
    setup_hand(bc, INTIMIDATE)
    bc.play_card(0)
    assert [m.statuses.get(MonsterStatus.WEAK) for m in bc.monsters.monsters] == [1, 1]
    assert any(c.card.name == "Intimidate" for c in bc.cards.exhaust_pile)
    setup_hand_upgraded(bc, INTIMIDATE)
    bc.play_card(0)
    assert [m.statuses.get(MonsterStatus.WEAK) for m in bc.monsters.monsters] == [3, 3]


def test_shockwave_all_weak_vulnerable():
    """震波：全体 3 层虚弱 + 3 层易伤；消耗；升级 5/5。"""
    bc = BattleContext(seed=55)
    bc.player.energy = 4
    add_cultist(bc)
    setup_hand(bc, SHOCKWAVE)
    bc.play_card(0)
    for m in bc.monsters.monsters:
        assert m.statuses.get(MonsterStatus.WEAK) == 3
        assert m.statuses.get(MonsterStatus.VULNERABLE) == 3
    assert any(c.card.name == "Shockwave" for c in bc.cards.exhaust_pile)
    setup_hand_upgraded(bc, SHOCKWAVE)
    bc.play_card(0)
    for m in bc.monsters.monsters:
        assert m.statuses.get(MonsterStatus.WEAK) == 8
        assert m.statuses.get(MonsterStatus.VULNERABLE) == 8


def test_disarm_reduces_strength_and_exhausts():
    """缴械：敌 -2 力量（升级仍 -2，对齐 C++）；吃 ARTIFACT 抵消；消耗。"""
    bc = BattleContext(seed=56)
    m = bc.monsters.monsters[0]
    m.statuses.add(MonsterStatus.STRENGTH, 4)
    setup_hand(bc, DISARM)
    bc.play_card(0)
    assert m.statuses.get(MonsterStatus.STRENGTH) == 2
    assert any(c.card.name == "Disarm" for c in bc.cards.exhaust_pile)
    setup_hand_upgraded(bc, DISARM)
    bc.play_card(0)
    assert m.statuses.get(MonsterStatus.STRENGTH) == 0  # wiki 为 -3，C++ 恒 -2


def test_disarm_blocked_by_artifact():
    """缴械：怪物有 ARTIFACT 时消耗一层神器并完全抵消。"""
    bc = BattleContext(seed=57)
    m = bc.monsters.monsters[0]
    m.statuses.add(MonsterStatus.STRENGTH, 4)
    m.statuses.add(MonsterStatus.ARTIFACT, 1)
    setup_hand(bc, DISARM)
    bc.play_card(0)
    assert m.statuses.get(MonsterStatus.STRENGTH) == 4
    assert not m.statuses.has(MonsterStatus.ARTIFACT)


def test_seeing_red_gains_energy_no_exhaust():
    """怒目而视：+2 能量；升级 0 费；不消耗（对齐 C++，wiki 为消耗）。"""
    bc = BattleContext(seed=58)
    setup_hand(bc, SEEING_RED)
    bc.play_card(0)
    assert bc.player.energy == 4  # 3 - 1 费 + 2
    assert any(c.card.name == "Seeing Red" for c in bc.cards.discard_pile)
    assert not any(c.card.name == "Seeing Red" for c in bc.cards.exhaust_pile)
    setup_hand_upgraded(bc, SEEING_RED)
    bc.play_card(0)
    assert bc.player.energy == 4 + 2  # 0 费


def test_bloodletting_hp_for_energy():
    """放血：失去 3 HP（对齐 C++，wiki 为 1），+2 能量；升级 +3。"""
    bc = BattleContext(seed=59)
    setup_hand(bc, BLOODLETTING)
    bc.play_card(0)
    assert bc.player.hp == 80 - 3
    assert bc.player.energy == 5
    setup_hand_upgraded(bc, BLOODLETTING)
    bc.play_card(0)
    assert bc.player.hp == 80 - 6
    assert bc.player.energy == 8


def test_spot_weakness_only_on_attack_intent():
    """洞察弱点：意图为攻击时 +3 力量；非攻击意图不加；升级 +4。"""
    bc = BattleContext(seed=60)
    m = bc.monsters.monsters[0]
    assert m.current_move.kind == "buff"  # 邪教徒首回合咒语
    setup_hand(bc, SPOT_WEAKNESS)
    bc.play_card(0)
    assert bc.player.statuses.get(PlayerStatus.STRENGTH) == 0
    m.set_move(Cultist.DARK_STRIKE)  # 攻击意图
    setup_hand(bc, SPOT_WEAKNESS)
    bc.play_card(0)
    assert bc.player.statuses.get(PlayerStatus.STRENGTH) == 3
    setup_hand_upgraded(bc, SPOT_WEAKNESS)
    bc.play_card(0)
    assert bc.player.statuses.get(PlayerStatus.STRENGTH) == 7


def test_entrench_doubles_block():
    """堑壕：当前格挡翻倍（执行时读取）；升级费用 2→1。"""
    bc = BattleContext(seed=61)
    setup_hand(bc, DEFEND, ENTRENCH)
    bc.play_card(0)  # Defend：格挡 5
    bc.play_card(0)  # Entrench：翻倍
    assert bc.player.block == 10
    assert bc.player.energy == 0  # 3 - 1 - 2
    # 升级版单独验证费用 2→1
    bc2 = BattleContext(seed=61)
    setup_hand_upgraded(bc2, ENTRENCH)
    bc2.play_card(0)  # 0 格挡翻倍仍 0
    assert bc2.player.block == 0
    assert bc2.player.energy == 3 - 1


def test_limit_break_doubles_strength_and_upgrade_keeps():
    """极限突破：力量翻倍；基础版消耗、升级版不消耗（对齐 doesCardExhaust）。"""
    bc = BattleContext(seed=62)
    bc.player.statuses.add(PlayerStatus.STRENGTH, 3)
    setup_hand(bc, LIMIT_BREAK)
    base_inst = bc.cards.hand[0]
    bc.play_card(0)
    assert bc.player.statuses.get(PlayerStatus.STRENGTH) == 6
    assert any(c is base_inst for c in bc.cards.exhaust_pile)
    setup_hand_upgraded(bc, LIMIT_BREAK)
    up_inst = bc.cards.hand[0]
    bc.play_card(0)
    assert bc.player.statuses.get(PlayerStatus.STRENGTH) == 12
    assert any(c is up_inst for c in bc.cards.discard_pile)
    assert not any(c is up_inst for c in bc.cards.exhaust_pile)


def test_bludgeon_damage():
    """重击：32 伤；升级 42。"""
    bc = BattleContext(seed=63)
    bc.player.energy = 6  # 两张 3 费
    m = bc.monsters.monsters[0]
    m.hp = 100  # 抬高 HP 避免第二张直接打死（死后的 HP=0 无法断言）
    setup_hand(bc, BLUDGEON)
    bc.play_card(0)
    assert m.hp == 100 - 32
    setup_hand_upgraded(bc, BLUDGEON)
    bc.play_card(0)
    assert m.hp == 100 - 32 - 42


def test_offering_hp_energy_draw_exhaust():
    """献祭：失 6 HP + 2 能量 + 抽 3；消耗；升级抽 5。"""
    bc = BattleContext(seed=64)
    setup_hand(bc, OFFERING)
    bc.play_card(0)
    assert bc.player.hp == 80 - 6
    assert bc.player.energy == 5  # 0 费 + 2
    assert len(bc.cards.hand) == 3
    assert any(c.card.name == "Offering" for c in bc.cards.exhaust_pile)
    # 升级抽 5：初始抽牌堆只剩 2（首手 5 张已被 setup 丢弃），实际抽到 2
    setup_hand_upgraded(bc, OFFERING)
    bc.play_card(0)
    assert len(bc.cards.hand) == 2
    assert bc.player.energy == 5 + 2


def test_impervious_block_and_exhaust():
    """金刚不坏：30 格挡；消耗；升级 40。"""
    bc = BattleContext(seed=65)
    bc.player.energy = 4  # 两张 2 费
    setup_hand(bc, IMPERVIOUS)
    bc.play_card(0)
    assert bc.player.block == 30
    assert any(c.card.name == "Impervious" for c in bc.cards.exhaust_pile)
    setup_hand_upgraded(bc, IMPERVIOUS)
    bc.play_card(0)
    assert bc.player.block == 70


def test_reaper_heals_unblocked_damage():
    """收割：全体 4 伤，吸血 = 实际掉落的 HP（被格挡吸收的不计）；消耗。"""
    bc = BattleContext(seed=66)
    bc.player.energy = 4  # 两张 2 费
    add_cultist(bc)  # idx 1
    bc.monsters.monsters[0].block = 9  # 两次收割的 4+5 全被格挡吸收，不掉血
    bc.player.hp = 60
    hp0 = [m.hp for m in bc.monsters.monsters]
    setup_hand(bc, REAPER)
    bc.play_card(0)
    assert bc.monsters.monsters[0].hp == hp0[0]  # 全被格挡吸收
    assert bc.monsters.monsters[0].block == 5
    assert bc.monsters.monsters[1].hp == hp0[1] - 4
    assert bc.player.hp == 60 + 4  # 只吸到第二只掉的 4 血
    assert any(c.card.name == "Reaper" for c in bc.cards.exhaust_pile)
    # 升级：全体 5 伤；第一只剩余格挡 5 恰好吸收，仍不掉血
    setup_hand_upgraded(bc, REAPER)
    bc.play_card(0)
    assert bc.monsters.monsters[0].hp == hp0[0]
    assert bc.monsters.monsters[0].block == 0
    assert bc.monsters.monsters[1].hp == hp0[1] - 9
    assert bc.player.hp == 60 + 4 + 5


def test_reaper_no_heal_when_all_blocked():
    """收割：全部伤害被格挡吸收时吸血为 0（HP 不变）。"""
    bc = BattleContext(seed=67)
    bc.monsters.monsters[0].block = 99
    bc.player.hp = 60
    hp0 = bc.monsters.monsters[0].hp
    setup_hand(bc, REAPER)
    bc.play_card(0)
    assert bc.monsters.monsters[0].hp == hp0
    assert bc.player.hp == 60  # 无吸血


def test_reaper_per_monster_vulnerable_pipeline():
    """收割：逐怪独立走管线——第二只有易伤吃 4×1.5=6。"""
    bc = BattleContext(seed=68)
    m1 = add_cultist(bc)
    m1.statuses.add(MonsterStatus.VULNERABLE, 1)
    hp0 = [m.hp for m in bc.monsters.monsters]
    bc.player.hp = 60
    setup_hand(bc, REAPER)
    bc.play_card(0)
    assert bc.monsters.monsters[0].hp == hp0[0] - 4
    assert m1.hp == hp0[1] - 6
    assert bc.player.hp == 60 + 4 + 6


def test_sword_boomerang_multi_random_hits():
    """回旋剑：3 段各 3 伤、独立随机目标（单怪全中；双怪合计守恒）。"""
    bc = BattleContext(seed=69)
    m = bc.monsters.monsters[0]
    hp0 = m.hp
    setup_hand(bc, SWORD_BOOMERANG)
    bc.play_card(0)
    assert m.hp == hp0 - 9
    # 升级：4 段；双怪场景合计 12
    m2 = add_cultist(bc)
    hp1 = [x.hp for x in bc.monsters.monsters]
    setup_hand_upgraded(bc, SWORD_BOOMERANG)
    bc.play_card(0)
    total = sum(hp1[i] - x.hp for i, x in enumerate(bc.monsters.monsters))
    assert total == 12


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

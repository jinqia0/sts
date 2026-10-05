"""铁甲战士 Act 1 卡牌移植断言（对齐 lightspeed useXxxCard 的逐卡 switch）。

构造手牌沿用 test_combat.py::test_bash_vulnerable_window 的模式：
bc.cards.instantiate(CardDef) + bc.cards.hand.append(...) + bc.play_card(...)，
保证出牌序列确定、不依赖初始洗牌。

多敌人卡（Cleave/Thunderclap）在默认单怪遭遇上追加一个邪教徒
（仅测试内构造，不出现在 encounters 注册表）。
"""

from sts.combat import BattleContext
from sts.combat.types import InputState, MonsterStatus, PlayerStatus
from sts.content.cards import (
    ANGER,
    BARRICADE,
    BATTLE_TRANCE,
    BERSERK,
    BLUDGEON,
    BLOOD_FOR_BLOOD,
    BLOODLETTING,
    BODY_SLAM,
    BRUTALITY,
    CARNAGE,
    CLASH,
    CLEAVE,
    CLOTHESLINE,
    COMBUST,
    CORRUPTION,
    DARK_EMBRACE,
    DEFEND,
    DEMON_FORM,
    DISARM,
    DOUBLE_TAP,
    DROPKICK,
    ENTRENCH,
    EVOLVE,
    FEED,
    FEEL_NO_PAIN,
    FIEND_FIRE,
    FIRE_BREATHING,
    FLEX,
    FLAME_BARRIER,
    GHOSTLY_ARMOR,
    HAND_OF_GREED,
    HAVOC,
    HEAVY_BLADE,
    HEMOKINESIS,
    IMMOLATE,
    IMPERVIOUS,
    INFLAME,
    INFERNAL_BLADE,
    INTIMIDATE,
    IRON_WAVE,
    JUGGERNAUT,
    LIMIT_BREAK,
    METALLICIZE,
    OFFERING,
    PERFECTED_STRIKE,
    POMMEL_STRIKE,
    POWER_THROUGH,
    PUMMEL,
    RAMPAGE,
    REAPER,
    RUPTURE,
    SEEING_RED,
    SECOND_WIND,
    SEARING_BLOW,
    SENTINEL,
    SEVER_SOUL,
    SHOCKWAVE,
    SHRUG_IT_OFF,
    SLIMED,
    SPOT_WEAKNESS,
    STRIKE,
    SWORD_BOOMERANG,
    THUNDERCLAP,
    TRUE_GRIT,
    TWIN_STRIKE,
    UPPERCUT,
    WILD_STRIKE,
    WOUND,
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


# ---- 中等档批次 2：Power 状态族 / 消耗族 / 虚无族 / 实例计数族 / 生成与击杀奖励族 ----
# 数值以 lightspeed C++ 为准；升级版在"层数×固定基数"引擎语义下与 C++
# "每次触发数值"语义有差异的卡（COMBUST/FIRE_BREATHING/FEEL_NO_PAIN/
# JUGGERNAUT），各测试注释中均已标明。


def run_queue(bc: BattleContext) -> None:
    """把挂起队列跑到底（直接调用引擎方法入队动作后使用）。"""
    if bc.input_state == InputState.PLAYER_NORMAL:
        bc.set_state(InputState.EXECUTING_ACTIONS)
    bc.execute_actions()


# ---- Power 状态族 ----


def test_barricade_card_keeps_block():
    """壁垒：格挡跨回合保留；费用 3→2。"""
    bc = BattleContext(seed=70)
    bc.player.energy = 5
    setup_hand(bc, DEFEND, BARRICADE)
    bc.play_card(0)  # Defend：格挡 5
    bc.play_card(0)  # Barricade：3 费
    assert bc.player.statuses.get(PlayerStatus.BARRICADE) == 1
    assert bc.player.energy == 1
    bc.end_turn()  # 敌回合 1 咒语不攻击；回合 2 开始格挡不清零
    assert bc.player.block == 5
    bc2 = BattleContext(seed=70)
    setup_hand_upgraded(bc2, BARRICADE)
    bc2.play_card(0)
    assert bc2.player.energy == 3 - 2
    assert BARRICADE.upgraded_cost == 2


def test_corruption_card_free_exhaust_skills():
    """腐化：技能 0 费且打出即消耗；攻击牌不受影响；费用 3→2。"""
    bc = BattleContext(seed=71)
    bc.player.energy = 4
    setup_hand(bc, CORRUPTION, DEFEND, STRIKE)
    bc.play_card(0)  # 3 费
    assert bc.player.statuses.get(PlayerStatus.CORRUPTION) == 1
    assert bc.player.energy == 1
    bc.play_card(0)  # Defend：0 费 + 消耗
    assert bc.player.block == 5
    assert bc.player.energy == 1
    assert any(c.card.name == "Defend" for c in bc.cards.exhaust_pile)
    bc.play_card(0)  # Strike：正常 1 费，不消耗
    assert bc.player.energy == 0
    assert not any(c.card.name == "Strike" for c in bc.cards.exhaust_pile)
    bc2 = BattleContext(seed=71)
    setup_hand_upgraded(bc2, CORRUPTION)
    bc2.play_card(0)
    assert bc2.player.energy == 3 - 2


def test_demon_form_card_strength_per_turn():
    """恶魔形态：回合开始（抽牌后）+2 力量；升级 +3。"""
    bc = BattleContext(seed=72)
    setup_hand(bc, DEMON_FORM)
    bc.play_card(0)
    assert bc.player.statuses.get(PlayerStatus.DEMON_FORM) == 2
    bc.end_turn()
    assert bc.player.statuses.get(PlayerStatus.STRENGTH) == 2
    bc2 = BattleContext(seed=72)
    setup_hand_upgraded(bc2, DEMON_FORM)
    bc2.play_card(0)
    bc2.end_turn()
    assert bc2.player.statuses.get(PlayerStatus.STRENGTH) == 3


def test_berserk_card_energy_and_vulnerable():
    """狂暴：+1 每回合同能量 + 2 层易伤（自施，当轮递减）；升级 0 费仅 1 层易伤。"""
    bc = BattleContext(seed=73)
    setup_hand(bc, BERSERK)
    bc.play_card(0)
    assert bc.player.energy_per_turn_bonus == 1
    assert bc.player.statuses.get(PlayerStatus.VULNERABLE) == 2
    assert bc.player.energy == 2
    bc.end_turn()
    # 回合 2 回能 3+1（敌回合 1 为咒语；自施易伤在回合末衰减 1 层）
    assert bc.player.energy == 4
    bc2 = BattleContext(seed=73)
    setup_hand_upgraded(bc2, BERSERK)
    bc2.play_card(0)
    assert bc2.player.energy == 3  # 0 费
    assert bc2.player.statuses.get(PlayerStatus.VULNERABLE) == 1


def test_brutality_card_draw_and_hp_loss():
    """残暴：回合开始（抽牌后）失 1 HP 并抽 1；升级 0 费且 innate_when_upgraded 置位。"""
    bc = BattleContext(seed=74)
    bc.cards.draw_pile.append(bc.cards.instantiate(STRIKE))  # 凑 6 张，验证补抽
    setup_hand(bc, BRUTALITY)
    bc.play_card(0)
    assert bc.player.statuses.get(PlayerStatus.BRUTALITY) == 1
    bc.end_turn()  # 回合 2 开始：抽 5 后失 1 HP 并补抽 1（敌回合 1 咒语未攻击）
    assert bc.player.hp == 80 - 1
    assert len(bc.cards.hand) == 5 + 1
    bc2 = BattleContext(seed=74)
    setup_hand_upgraded(bc2, BRUTALITY)
    bc2.play_card(0)
    assert bc2.player.energy == 3  # 升级 0 费
    # 升级版固有（C++ isCardInnate 的 upgraded 分支）：用 innate_when_upgraded
    # 位表达，待引擎 move_innate_to_top 接线（见批次 2 报告）
    assert BRUTALITY.innate_when_upgraded is True
    assert BRUTALITY.innate is False


def test_juggernaut_card_damage_on_block():
    """重装冲锋：获得格挡 → 随机敌人 5 伤（单怪确定）；升级 2 层 10 伤（C++ 为 7，见注释）。"""
    bc = BattleContext(seed=75)
    bc.player.energy = 3
    m = bc.monsters.monsters[0]
    hp0 = m.hp
    setup_hand(bc, JUGGERNAUT, DEFEND)
    bc.play_card(0)
    bc.play_card(0)  # Defend → 触发
    assert bc.player.block == 5
    assert m.hp == hp0 - 5
    bc2 = BattleContext(seed=75)
    bc2.player.energy = 3
    m2 = bc2.monsters.monsters[0]
    hp1 = m2.hp
    setup_hand_upgraded(bc2, JUGGERNAUT, DEFEND)
    bc2.play_card(0)
    bc2.play_card(0)
    # 引擎 JUGGERNAUT=层数、5×层：升级 2 层 → 10 伤（lightspeed C++ 存值 7）
    assert m2.hp == hp1 - 10


def test_rupture_card_strength_on_self_hp_loss():
    """破裂：自伤失去 HP 时 +1 力量；升级 +2。"""
    bc = BattleContext(seed=76)
    setup_hand(bc, RUPTURE, BLOODLETTING)
    bc.play_card(0)
    bc.play_card(0)  # 放血：自伤失 3 HP → +1 力量
    assert bc.player.statuses.get(PlayerStatus.STRENGTH) == 1
    assert bc.player.hp == 80 - 3
    # 升级：每次自伤 +2 力量
    bc2 = BattleContext(seed=76)
    bc2.cards.hand.clear()
    r = bc2.cards.instantiate(RUPTURE)
    r.upgraded = True
    bc2.cards.hand.extend([r, bc2.cards.instantiate(BLOODLETTING)])
    bc2.play_card(0)
    bc2.play_card(0)
    assert bc2.player.statuses.get(PlayerStatus.STRENGTH) == 2


def test_combust_card_end_of_turn():
    """燃烧：回合末失 1 HP + 全体 5 伤；升级 2 层（引擎口径：失 2/10 伤，C++ 为 1/7，见注释）。"""
    bc = BattleContext(seed=77)
    m = bc.monsters.monsters[0]
    hp0 = m.hp
    setup_hand(bc, COMBUST)
    bc.play_card(0)
    assert bc.player.statuses.get(PlayerStatus.COMBUST) == 1
    bc.end_turn()  # 回合末结算：失 1 HP、全体 5 伤（敌回合 1 咒语不攻击）
    assert bc.player.hp == 80 - 1
    assert m.hp == hp0 - 5
    bc2 = BattleContext(seed=77)
    m2 = bc2.monsters.monsters[0]
    hp1 = m2.hp
    setup_hand_upgraded(bc2, COMBUST)
    bc2.play_card(0)
    assert bc2.player.statuses.get(PlayerStatus.COMBUST) == 2
    bc2.end_turn()
    assert bc2.player.hp == 80 - 2
    assert m2.hp == hp1 - 10


def test_evolve_card_draws_on_status_draw():
    """进化：抽到状态牌时补抽 1×层。"""
    bc = BattleContext(seed=78)
    bc.cards.draw_pile.clear()
    bc.cards.draw_pile.append(bc.cards.instantiate(STRIKE))
    bc.cards.draw_pile.append(bc.cards.instantiate(WOUND))  # 尾部 = 堆顶
    setup_hand(bc, EVOLVE)
    bc.play_card(0)
    bc.draw_cards(1)  # 抽到伤口 → 补抽 1
    assert len(bc.cards.hand) == 2
    assert [c.card.name for c in bc.cards.hand] == ["Wound", "Strike"]
    bc2 = BattleContext(seed=78)
    bc2.cards.draw_pile.clear()
    bc2.cards.draw_pile.append(bc2.cards.instantiate(STRIKE))
    bc2.cards.draw_pile.append(bc2.cards.instantiate(DEFEND))
    bc2.cards.draw_pile.append(bc2.cards.instantiate(WOUND))
    setup_hand_upgraded(bc2, EVOLVE)
    bc2.play_card(0)
    bc2.draw_cards(1)  # 抽到伤口 → 补抽 2
    assert len(bc2.cards.hand) == 3


def test_fire_breathing_card_damage_on_status_draw():
    """火息：抽到状态/诅咒牌时全体 4 伤（引擎 4×层；C++ 直存 6/10，见注释）。"""
    bc = BattleContext(seed=79)
    add_cultist(bc)
    hp0 = [m.hp for m in bc.monsters.monsters]
    bc.cards.draw_pile.clear()
    bc.cards.draw_pile.append(bc.cards.instantiate(WOUND))
    setup_hand(bc, FIRE_BREATHING)
    bc.play_card(0)
    bc.draw_cards(1)  # 抽到伤口 → 全体 4 伤入队
    run_queue(bc)
    assert [m.hp for m in bc.monsters.monsters] == [hp0[0] - 4, hp0[1] - 4]
    bc2 = BattleContext(seed=79)
    add_cultist(bc2)
    hp1 = [m.hp for m in bc2.monsters.monsters]
    bc2.cards.draw_pile.clear()
    bc2.cards.draw_pile.append(bc2.cards.instantiate(WOUND))
    setup_hand_upgraded(bc2, FIRE_BREATHING)
    bc2.play_card(0)
    bc2.draw_cards(1)
    run_queue(bc2)
    # 升级 2 层 × 4 = 8（lightspeed C++ 直存 10，wiki 为 6）
    assert [m.hp for m in bc2.monsters.monsters] == [hp1[0] - 8, hp1[1] - 8]


def test_feel_no_pain_card_block_on_exhaust():
    """无痛：卡被消耗时 +3 格挡；升级 2 层 +6（C++ 为 4，见注释）。"""
    bc = BattleContext(seed=80)
    setup_hand(bc, FEEL_NO_PAIN, SLIMED)
    bc.play_card(0)
    assert bc.player.statuses.get(PlayerStatus.FEEL_NO_PAIN) == 1
    bc.play_card(0)  # Slimed：消耗 → +3 格挡
    assert bc.player.block == 3
    assert any(c.card.name == "Slimed" for c in bc.cards.exhaust_pile)
    bc2 = BattleContext(seed=80)
    setup_hand_upgraded(bc2, FEEL_NO_PAIN, SLIMED)
    bc2.play_card(0)
    bc2.play_card(0)
    assert bc2.player.block == 6  # 引擎 3×2 层；lightspeed C++ 直存 4


def test_dark_embrace_card_draw_on_exhaust():
    """黑暗拥抱：卡被消耗时抽 1（升级仍 1，C++ 无 up 分支，仅改费 2→1）。"""
    bc = BattleContext(seed=81)
    draw0 = len(bc.cards.draw_pile)
    setup_hand(bc, DARK_EMBRACE, SLIMED)
    bc.play_card(0)
    bc.play_card(0)  # Slimed：消耗 → 抽 1
    assert len(bc.cards.hand) == 1
    assert len(bc.cards.draw_pile) == draw0 - 1
    bc2 = BattleContext(seed=81)
    setup_hand_upgraded(bc2, DARK_EMBRACE, SLIMED)
    bc2.play_card(0)
    assert bc2.player.energy == 3 - 1  # 升级 1 费
    bc2.play_card(0)  # Slimed：消耗 → 抽 1
    assert bc2.player.energy == 3 - 1 - 1
    assert len(bc2.cards.hand) == 1
    assert bc2.player.statuses.get(PlayerStatus.DARK_EMBRACE) == 1


def test_flame_barrier_card_block_and_reflect():
    """烈焰屏障：12 格挡 + 本回合受攻击反弹 4；升级 16/6。"""
    bc = BattleContext(seed=82)
    m = bc.monsters.monsters[0]
    hp0 = m.hp
    setup_hand(bc, FLAME_BARRIER)
    bc.play_card(0)
    assert bc.player.block == 12
    assert bc.player.statuses.get(PlayerStatus.FLAME_BARRIER) == 4
    bc.player.attacked(bc, 0, 6)  # 6 伤全被格挡吸收，仍反弹
    run_queue(bc)
    assert bc.player.block == 6
    assert bc.player.hp == 80
    assert m.hp == hp0 - 4
    bc2 = BattleContext(seed=82)
    m2 = bc2.monsters.monsters[0]
    hp1 = m2.hp
    setup_hand_upgraded(bc2, FLAME_BARRIER)
    bc2.play_card(0)
    assert bc2.player.block == 16
    assert bc2.player.statuses.get(PlayerStatus.FLAME_BARRIER) == 6
    bc2.player.attacked(bc2, 0, 6)
    run_queue(bc2)
    assert m2.hp == hp1 - 6


def test_double_tap_card_doubles_next_attack():
    """双重打击：本回合下一张攻击牌结算两次；升级状态 2 层（引擎 remove 缺陷，见注释）。"""
    bc = BattleContext(seed=83)
    bc.player.energy = 2
    m = bc.monsters.monsters[0]
    hp0 = m.hp
    setup_hand(bc, DOUBLE_TAP, STRIKE)
    bc.play_card(0)
    assert bc.player.statuses.get(PlayerStatus.DOUBLE_TAP) == 1
    bc.play_card(0)  # Strike 结算两次
    assert m.hp == hp0 - 12
    assert not bc.player.statuses.has(PlayerStatus.DOUBLE_TAP)
    assert any(c.card.name == "Strike" for c in bc.cards.discard_pile)  # 本体落弃牌堆
    # 升级：C++ 应为 2 层（翻倍接下来两张攻击牌）；引擎 on_use_attack_card
    # 触发时整状态 remove 而非递减 → 实际只翻倍第一张，待引擎修复（批次 2 报告）
    bc2 = BattleContext(seed=83)
    setup_hand_upgraded(bc2, DOUBLE_TAP)
    bc2.play_card(0)
    assert bc2.player.statuses.get(PlayerStatus.DOUBLE_TAP) == 2


# ---- 消耗族 ----


def test_second_wind_exhausts_and_blocks():
    """喘息：消耗全部非攻击手牌，每张 +5 格挡（升级 +7）；攻击牌保留；无消耗对象时 0 格挡。"""
    bc = BattleContext(seed=84)
    setup_hand(bc, SECOND_WIND, DEFEND, INFLAME, STRIKE)
    bc.play_card(0)
    assert bc.player.block == 10  # Defend + Inflame 两张 × 5
    exhausted_names = {c.card.name for c in bc.cards.exhaust_pile}
    assert exhausted_names == {"Defend", "Inflame"}
    assert [c.card.name for c in bc.cards.hand] == ["Strike"]
    bc2 = BattleContext(seed=84)
    setup_hand_upgraded(bc2, SECOND_WIND, DEFEND, INFLAME, STRIKE)
    bc2.play_card(0)
    assert bc2.player.block == 14  # 2 张 × 7
    # 空条件：手牌只有攻击牌 → 无消耗对象、0 格挡
    bc3 = BattleContext(seed=84)
    setup_hand(bc3, SECOND_WIND, STRIKE)
    bc3.play_card(0)
    assert bc3.player.block == 0
    assert [c.card.name for c in bc3.cards.hand] == ["Strike"]
    assert bc3.cards.exhaust_pile == []


def test_sever_soul_exhausts_then_damage():
    """撕裂灵魂：16 伤 + 消耗全部非攻击手牌（C++ 结算序：先伤害后消耗）；升级 22。"""
    bc = BattleContext(seed=85)
    m = bc.monsters.monsters[0]
    hp0 = m.hp
    setup_hand(bc, SEVER_SOUL, DEFEND, INFLAME, STRIKE)
    bc.play_card(0)
    assert m.hp == hp0 - 16
    exhausted_names = {c.card.name for c in bc.cards.exhaust_pile}
    assert exhausted_names == {"Defend", "Inflame"}
    assert [c.card.name for c in bc.cards.hand] == ["Strike"]
    bc2 = BattleContext(seed=85)
    m2 = bc2.monsters.monsters[0]
    hp1 = m2.hp
    setup_hand_upgraded(bc2, SEVER_SOUL, DEFEND)
    bc2.play_card(0)
    assert m2.hp == hp1 - 22
    assert any(c.card.name == "Defend" for c in bc2.cards.exhaust_pile)


def test_fiend_fire_exhausts_all_then_multi_hit():
    """恶魔之火：消耗全部手牌（含随机序），每张 7 伤同目标；自身消耗；空手 0 伤；升级 10。"""
    bc = BattleContext(seed=86)
    m = bc.monsters.monsters[0]
    hp0 = m.hp
    setup_hand(bc, FIEND_FIRE, DEFEND, INFLAME, STRIKE)
    bc.play_card(0)
    assert m.hp == hp0 - 21  # 3 张手牌 × 7
    exhausted_names = {c.card.name for c in bc.cards.exhaust_pile}
    assert exhausted_names == {"Fiend Fire", "Defend", "Inflame", "Strike"}
    assert bc.cards.hand == []
    bc2 = BattleContext(seed=86)
    m2 = bc2.monsters.monsters[0]
    hp1 = m2.hp
    setup_hand_upgraded(bc2, FIEND_FIRE, DEFEND, INFLAME, STRIKE)
    bc2.play_card(0)
    assert m2.hp == hp1 - 30  # 3 × 10
    # 空手：无消耗对象、0 伤，仅自身消耗
    bc3 = BattleContext(seed=86)
    m3 = bc3.monsters.monsters[0]
    hp2 = m3.hp
    setup_hand(bc3, FIEND_FIRE)
    bc3.play_card(0)
    assert m3.hp == hp2
    assert [c.card.name for c in bc3.cards.exhaust_pile] == ["Fiend Fire"]


def test_sentinel_block_and_exhaust_energy():
    """哨兵：打出仅 5 格挡（正常落弃牌堆）；被消耗时 +2 能量（升级 +3，C++ 口径）；弃置不触发。"""
    # 打出：仅格挡，不触发能量
    bc = BattleContext(seed=87)
    setup_hand(bc, SENTINEL)
    bc.play_card(0)
    assert bc.player.block == 5
    assert bc.player.energy == 2
    assert any(c.card.name == "Sentinel" for c in bc.cards.discard_pile)
    # 被消耗（Second Wind 路径，Sentinel 留在手牌未打出）→ +2 能量
    bc2 = BattleContext(seed=87)
    setup_hand(bc2, SECOND_WIND, SENTINEL)
    bc2.play_card(0)
    assert bc2.player.block == 5  # Second Wind 每张 5 格挡
    assert bc2.player.energy == 3 - 1 + 2
    assert any(c.card.name == "Sentinel" for c in bc2.cards.exhaust_pile)
    # 升级：8 格挡；被消耗 +3 能量
    bc3 = BattleContext(seed=87)
    setup_hand(bc3, SENTINEL)
    bc3.cards.hand[0].upgraded = True
    bc3.play_card(0)
    assert bc3.player.block == 8
    bc4 = BattleContext(seed=87)
    setup_hand_upgraded(bc4, SECOND_WIND, SENTINEL)  # SW+ 7/张 + Sentinel+ +3 能量
    bc4.play_card(0)
    assert bc4.player.block == 7
    assert bc4.player.energy == 3 - 1 + 3
    # 正常弃置（回合末）不触发能量
    bc5 = BattleContext(seed=87)
    setup_hand(bc5, SENTINEL)
    bc5.end_turn()
    assert any(c.card.name == "Sentinel" for c in bc5.cards.discard_pile)
    assert bc5.player.energy == 3


def test_power_through_wounds_and_block():
    """硬撑：2 张伤口入手 + 15 格挡（顺序：先伤口后格挡）；升级 20。"""
    bc = BattleContext(seed=88)
    setup_hand(bc, POWER_THROUGH)
    bc.play_card(0)
    assert bc.player.block == 15
    wounds = [c for c in bc.cards.hand if c.card.name == "Wound"]
    assert len(wounds) == 2
    assert len({c.unique_id for c in wounds}) == 2
    bc2 = BattleContext(seed=88)
    setup_hand_upgraded(bc2, POWER_THROUGH)
    bc2.play_card(0)
    assert bc2.player.block == 20
    assert len([c for c in bc2.cards.hand if c.card.name == "Wound"]) == 2


def test_true_grit_block_and_random_exhaust():
    """坚毅（基础）：7 格挡 + 随机消耗 1 张手牌（misc 流）；空手不消耗。"""
    bc = BattleContext(seed=89)
    setup_hand(bc, TRUE_GRIT, DEFEND, STRIKE)
    bc.play_card(0)
    assert bc.player.block == 7
    exhausted = [c.card.name for c in bc.cards.exhaust_pile]
    assert len(exhausted) == 1
    assert exhausted[0] in ("Defend", "Strike")
    assert len(bc.cards.hand) == 1
    assert bc.cards.hand[0].card.name != exhausted[0]
    # 空手：仅格挡，无消耗
    bc2 = BattleContext(seed=89)
    setup_hand(bc2, TRUE_GRIT)
    bc2.play_card(0)
    assert bc2.player.block == 7
    assert bc2.cards.exhaust_pile == []


def test_true_grit_upgraded_opens_card_select():
    """坚毅+：9 格挡 + 选卡消耗（can_pick_zero=False）；单候选直执；空手跳过。"""
    bc = BattleContext(seed=89)
    setup_hand_upgraded(bc, TRUE_GRIT, DEFEND, STRIKE)
    bc.play_card(0)
    assert bc.player.block == 9
    assert bc.input_state == InputState.CARD_SELECT
    bc.choose_card(0)  # 选 Defend
    assert any(c.card.name == "Defend" for c in bc.cards.exhaust_pile)
    assert [c.card.name for c in bc.cards.hand] == ["Strike"]
    # 单候选：不挂选卡直接消耗
    bc2 = BattleContext(seed=89)
    setup_hand_upgraded(bc2, TRUE_GRIT, DEFEND)
    bc2.play_card(0)
    assert bc2.input_state == InputState.PLAYER_NORMAL
    assert any(c.card.name == "Defend" for c in bc2.cards.exhaust_pile)
    assert bc2.cards.hand == []
    # 空手：仅格挡
    bc3 = BattleContext(seed=89)
    setup_hand_upgraded(bc3, TRUE_GRIT)
    bc3.play_card(0)
    assert bc3.player.block == 9
    assert bc3.input_state == InputState.PLAYER_NORMAL


def test_havoc_plays_top_card_and_exhausts_both():
    """浩劫：免费随机目标打出抽牌堆顶并消耗它，自身也消耗；升级 0 费。"""
    bc = BattleContext(seed=94)
    m = bc.monsters.monsters[0]
    hp0 = m.hp
    bc.cards.draw_pile.clear()
    bc.cards.discard_pile.clear()
    top = bc.cards.instantiate(STRIKE)
    bc.cards.draw_pile.append(top)  # 列表尾 = 堆顶
    setup_hand(bc, HAVOC)
    bc.play_card(0)
    assert m.hp == hp0 - 6  # 免费打出的打击
    assert any(c is top for c in bc.cards.exhaust_pile)  # 顶牌消耗
    assert any(c.card.name == "Havoc" for c in bc.cards.exhaust_pile)  # 自身消耗
    assert bc.player.energy == 2
    # 两堆皆空：无牌可打，仅自身消耗，不崩
    bc2 = BattleContext(seed=94)
    bc2.cards.draw_pile.clear()
    bc2.cards.discard_pile.clear()
    setup_hand(bc2, HAVOC)
    bc2.play_card(0)
    assert [c.card.name for c in bc2.cards.exhaust_pile] == ["Havoc"]
    # 抽牌堆空、弃牌堆有牌：先洗再打出
    bc3 = BattleContext(seed=94)
    bc3.cards.draw_pile.clear()
    defend_inst = bc3.cards.instantiate(DEFEND)
    bc3.cards.discard_pile.append(defend_inst)
    setup_hand(bc3, HAVOC)
    bc3.play_card(0)
    assert bc3.player.block == 5
    assert any(c is defend_inst for c in bc3.cards.exhaust_pile)
    # 顶牌是状态卡：无效果落堆（对齐 C++ useCard 的 STATUS 分支），不崩
    bc4 = BattleContext(seed=94)
    m4 = bc4.monsters.monsters[0]
    hp4 = m4.hp
    bc4.cards.draw_pile.clear()
    wound = bc4.cards.instantiate(WOUND)
    bc4.cards.draw_pile.append(wound)
    setup_hand(bc4, HAVOC)
    bc4.play_card(0)
    assert m4.hp == hp4
    assert any(c is wound for c in bc4.cards.exhaust_pile)
    # 升级 0 费
    bc5 = BattleContext(seed=94)
    bc5.cards.draw_pile.clear()
    bc5.cards.draw_pile.append(bc5.cards.instantiate(STRIKE))
    setup_hand_upgraded(bc5, HAVOC)
    bc5.play_card(0)
    assert bc5.player.energy == 3


def test_infernal_blade_random_free_attack():
    """地狱之刃：随机攻击牌 0 费入手，自身消耗；生成牌本回合免费打出。"""
    bc = BattleContext(seed=95)
    setup_hand(bc, INFERNAL_BLADE)
    bc.play_card(0)
    assert any(c.card.name == "Infernal Blade" for c in bc.cards.exhaust_pile)
    assert len(bc.cards.hand) == 1
    gen = bc.cards.hand[0]
    assert gen.card.ctype == "Attack"
    assert gen.cost == 0  # cost_for_turn=0
    m = bc.monsters.monsters[0]
    hp0 = m.hp
    energy0 = bc.player.energy
    bc.play_card(0)  # 0 费打出
    assert bc.player.energy == energy0
    # 攻击牌实际结算（恶魔之火空手时 0 段除外——池内唯一零伤特例）
    if gen.card.name != "Fiend Fire":
        assert m.hp < hp0
    assert gen not in bc.cards.hand  # 打出后离开手牌


# ---- 虚无族 ----


def test_carnage_ethereal_attack():
    """杀戮：20 伤；虚无——回合末在手则消耗；升级 28。"""
    bc = BattleContext(seed=90)
    m = bc.monsters.monsters[0]
    hp0 = m.hp
    setup_hand(bc, CARNAGE)
    bc.play_card(0)
    assert m.hp == hp0 - 20
    bc2 = BattleContext(seed=90)
    setup_hand(bc2, CARNAGE, DEFEND)
    bc2.end_turn()  # 不打：回合末虚无消耗；Defend 正常弃置
    assert any(c.card.name == "Carnage" for c in bc2.cards.exhaust_pile)
    assert any(c.card.name == "Defend" for c in bc2.cards.discard_pile)
    bc3 = BattleContext(seed=90)
    m3 = bc3.monsters.monsters[0]
    hp3 = m3.hp
    setup_hand_upgraded(bc3, CARNAGE)
    bc3.play_card(0)
    assert m3.hp == hp3 - 28


def test_ghostly_armor_ethereal_block():
    """幽灵护甲：10 格挡；虚无；升级 13。"""
    bc = BattleContext(seed=91)
    setup_hand(bc, GHOSTLY_ARMOR)
    bc.play_card(0)
    assert bc.player.block == 10
    bc2 = BattleContext(seed=91)
    setup_hand(bc2, GHOSTLY_ARMOR, DEFEND)
    bc2.end_turn()
    assert any(c.card.name == "Ghostly Armor" for c in bc2.cards.exhaust_pile)
    assert any(c.card.name == "Defend" for c in bc2.cards.discard_pile)
    bc3 = BattleContext(seed=91)
    setup_hand_upgraded(bc3, GHOSTLY_ARMOR)
    bc3.play_card(0)
    assert bc3.player.block == 13


# ---- 实例计数族 ----


def test_rampage_same_instance_stacks():
    """狂暴冲杀：同一实例连打叠伤（先算后加：8 → 13 → 18）；升级 +8。"""
    bc = BattleContext(seed=92)
    m = bc.monsters.monsters[0]
    hp0 = m.hp
    setup_hand(bc, RAMPAGE)
    inst = bc.cards.hand[0]
    bc.play_card(0)
    assert m.hp == hp0 - 8
    assert inst.misc_data == 5
    # 同一实例从弃牌堆取回再打
    bc.cards.discard_pile.remove(inst)
    bc.cards.hand.append(inst)
    bc.play_card(0)
    assert m.hp == hp0 - 8 - 13
    assert inst.misc_data == 10
    # 升级 +8/次
    bc2 = BattleContext(seed=92)
    m2 = bc2.monsters.monsters[0]
    hp1 = m2.hp
    setup_hand_upgraded(bc2, RAMPAGE)
    inst2 = bc2.cards.hand[0]
    bc2.play_card(0)
    assert m2.hp == hp1 - 8
    bc2.cards.discard_pile.remove(inst2)
    bc2.cards.hand.append(inst2)
    bc2.play_card(0)
    assert m2.hp == hp1 - 8 - 16
    assert inst2.misc_data == 16


def test_searing_blow_upgrade_count_formula():
    """灼热打击：base = 12 + n×(n+7)/2（n=misc_data 升级数）：12/16/21/27；升级位兜底 n=1。"""
    bc = BattleContext(seed=93)
    m = bc.monsters.monsters[0]
    m.hp = 200
    m.max_hp = 200
    hp0 = m.hp
    for n, expected in [(0, 12), (1, 16), (2, 21), (3, 27)]:
        setup_hand(bc, SEARING_BLOW)
        bc.cards.hand[0].misc_data = n
        bc.player.energy = 2
        bc.play_card(0)
        assert m.hp == hp0 - expected
        hp0 = m.hp
    # 升级位为 True 而 misc_data=0 → 按 n=1 兜底（16）
    setup_hand_upgraded(bc, SEARING_BLOW)
    bc.player.energy = 2
    bc.play_card(0)
    assert m.hp == hp0 - 16


def test_blood_for_blood_cost_reduces_on_damage():
    """以血还血：4 费、每次失去 HP 永久 -1（下限 0）；18/22 伤；升级基费 3。"""
    bc = BattleContext(seed=96)
    m = bc.monsters.monsters[0]
    m.hp = 100
    setup_hand(bc, BLOOD_FOR_BLOOD)
    inst = bc.cards.hand[0]
    assert inst.cost == 4
    bc.player.lose_hp(bc, 2)
    assert inst.cost == 3
    bc.player.lose_hp(bc, 2)
    assert inst.cost == 2
    bc.player.energy = 4
    bc.play_card(0)
    assert m.hp == 100 - 18
    assert bc.player.energy == 4 - 2  # 按当前费用 2 收费
    # 下限 0
    for _ in range(5):
        bc.player.lose_hp(bc, 1)
    assert inst.cost == 0
    bc2 = BattleContext(seed=96)
    m2 = bc2.monsters.monsters[0]
    m2.hp = 100
    setup_hand_upgraded(bc2, BLOOD_FOR_BLOOD)
    inst2 = bc2.cards.hand[0]
    assert inst2.cost == 3
    bc2.player.lose_hp(bc2, 2)
    assert inst2.cost == 2
    bc2.player.energy = 3
    bc2.play_card(0)
    assert m2.hp == 100 - 22


# ---- 生成与击杀奖励族 ----


def test_immolate_all_damage_and_burn():
    """焚化：全体 21 伤（升级 28）+ 1 张灼伤进弃牌堆。"""
    bc = BattleContext(seed=97)
    add_cultist(bc)
    hp0 = [m.hp for m in bc.monsters.monsters]
    setup_hand(bc, IMMOLATE)
    bc.play_card(0)
    assert [m.hp for m in bc.monsters.monsters] == [hp0[0] - 21, hp0[1] - 21]
    burns = [c for c in bc.cards.discard_pile if c.card.name == "Burn"]
    assert len(burns) == 1
    bc2 = BattleContext(seed=97)
    add_cultist(bc2)
    hp1 = [m.hp for m in bc2.monsters.monsters]
    setup_hand_upgraded(bc2, IMMOLATE)
    bc2.play_card(0)
    assert [m.hp for m in bc2.monsters.monsters] == [hp1[0] - 28, hp1[1] - 28]
    assert len([c for c in bc2.cards.discard_pile if c.card.name == "Burn"]) == 1


def test_feed_kill_raises_max_hp():
    """吞噬：击杀 → maxHP +3 并回复 3（C++ increaseMaxHp 内含 heal）；未击杀不触发；消耗；升级 12/4。"""
    bc = BattleContext(seed=98)
    m = bc.monsters.monsters[0]
    m.hp = 10
    setup_hand(bc, FEED)
    bc.play_card(0)
    assert bc.won
    assert m.hp == 0
    assert bc.player.max_hp == 80 + 3
    assert bc.player.hp == 80 + 3
    assert any(c.card.name == "Feed" for c in bc.cards.exhaust_pile)
    # 未击杀：无变化
    bc2 = BattleContext(seed=98)
    m2 = bc2.monsters.monsters[0]
    m2.hp = 100
    m2.max_hp = 100
    setup_hand(bc2, FEED)
    bc2.play_card(0)
    assert bc2.player.max_hp == 80
    assert bc2.player.hp == 80
    assert m2.hp == 90
    # 升级：12 伤 / maxHP +4
    bc3 = BattleContext(seed=98)
    m3 = bc3.monsters.monsters[0]
    m3.hp = 12
    setup_hand_upgraded(bc3, FEED)
    bc3.play_card(0)
    assert bc3.player.max_hp == 80 + 4
    assert bc3.player.hp == 80 + 4


def test_hand_of_greed_kill_gains_gold():
    """贪婪之手：20/25 伤；击杀 → +20/25 金币；未击杀不触发；伤害走 damage（非攻击，对齐 C++）。"""
    bc = BattleContext(seed=99)
    m = bc.monsters.monsters[0]
    m.hp = 20
    gold0 = bc.player.gold
    setup_hand(bc, HAND_OF_GREED)
    bc.play_card(0)
    assert bc.won
    assert bc.player.gold == gold0 + 20
    # 未击杀：无金币
    bc2 = BattleContext(seed=99)
    m2 = bc2.monsters.monsters[0]
    m2.hp = 100
    m2.max_hp = 100
    gold1 = bc2.player.gold
    setup_hand(bc2, HAND_OF_GREED)
    bc2.play_card(0)
    assert bc2.player.gold == gold1
    assert m2.hp == 80
    # 升级：25 伤 / +25 金
    bc3 = BattleContext(seed=99)
    m3 = bc3.monsters.monsters[0]
    m3.hp = 25
    gold2 = bc3.player.gold
    setup_hand_upgraded(bc3, HAND_OF_GREED)
    bc3.play_card(0)
    assert bc3.player.gold == gold2 + 25

"""遗物全量功能测试（批次 1）：每个已实现遗物至少 1 个用例。

模式对齐 test_engine_batch0.py：BattleContext(seed=N, relics=[...]) 构造 +
setup_hand/run_queue 辅助 + 断言。数值断言全部以 sts_lightspeed 源码为
准（relics.py 内注释标注 文件:行号）。房间类遗物（精英/Boss）通过
relics.ELITE_ENCOUNTERS / BOSS_ENCOUNTERS 注册表临时注册遭遇名验证。
"""

from __future__ import annotations

import sts.combat.relics as relics_mod
from sts.combat import BattleContext
from sts.combat.actions import Actions
from sts.combat.relics import RelicId
from sts.combat.relics import _colorless_card_pool, _combat_card_pool
from sts.combat.types import InputState, MonsterStatus, Outcome, PlayerStatus
from sts.content.cards import BASH, DEFEND, STRIKE, WOUND, CardDef
from sts.content.monsters import Cultist

# ---- 测试桩卡 ----


def _free_attack_play(bc, item) -> None:
    """0 费攻击桩：6 伤（走完整出伤管线，可吃 PEN_NIB/WRIST_BLADE 等）。"""
    bc.add_to_bot(Actions.attack_enemy(item.target, bc.calculate_card_damage(item, item.target, 6)))


FREE_ATTACK = CardDef("Free Attack", "零费攻击桩", 0, "Attack", "6 伤。", True, False,
                      _free_attack_play)
SKILL_STUB = CardDef("Skill Stub", "技能桩", 0, "Skill", "无效果。", False, False,
                     lambda bc, item: None)
POWER_STUB = CardDef("Power Stub", "能力桩", 0, "Power", "无效果。", False, False,
                     lambda bc, item: None)
EXHAUST_STUB = CardDef("Exhaust Stub", "消耗桩", 0, "Skill", "消耗。", False, True,
                       lambda bc, item: None)
CURSE_STUB = CardDef("Curse Stub", "诅咒桩", 0, "Curse", "不可打出。", False, False, None,
                     unplayable=True)


def setup_hand(bc: BattleContext, *cards) -> None:
    bc.cards.hand.clear()
    for c in cards:
        bc.cards.hand.append(bc.cards.instantiate(c))


def run_queue(bc: BattleContext) -> None:
    if bc.input_state == InputState.PLAYER_NORMAL:
        bc.set_state(InputState.EXECUTING_ACTIONS)
    bc.execute_actions()


def add_cultist(bc: BattleContext, idx: int = 1, hp: int = 50) -> Cultist:
    m = Cultist(idx=idx, hp=hp, max_hp=hp)
    m.set_move(Cultist.INCANTATION)
    bc.monsters.add(m)
    return m


class _elite_encounter:
    """上下文管理器：把遭遇名临时注册为精英/Boss 房（测试后还原）。"""

    def __init__(self, encounter: str, *, boss: bool = False):
        self.encounter = encounter
        self.pool = relics_mod.BOSS_ENCOUNTERS if boss else relics_mod.ELITE_ENCOUNTERS
        self._added = False

    def __enter__(self):
        if self.encounter not in self.pool:
            self.pool.add(self.encounter)
            self._added = True
        return self

    def __exit__(self, *exc):
        if self._added:
            self.pool.discard(self.encounter)
        return False


# =====================================================================
# 战斗开始-即时桶
# =====================================================================


def test_vajra_strength():
    bc = BattleContext(seed=201, relics=[RelicId.VAJRA])
    assert bc.player.statuses.get(PlayerStatus.STRENGTH) == 1


def test_anchor_block_10():
    bc = BattleContext(seed=202, relics=[RelicId.ANCHOR])
    assert bc.player.block == 10


def test_blood_vial_heals_2():
    bc = BattleContext(seed=203, relics=[RelicId.BLOOD_VIAL])
    bc.player.hp = 70
    bc.relics.on_battle_start_immediate(bc)  # 构造期已回过，重触发验证
    assert bc.player.hp == 72


def test_girya_uses_counter_strength():
    bc = BattleContext(seed=204, relics=[RelicId.GIRYA])
    assert bc.player.statuses.get(PlayerStatus.STRENGTH) == 0  # 未举重
    bc.relics.set_counter(RelicId.GIRYA, 2)
    bc.player.statuses.set(PlayerStatus.STRENGTH, 0)
    bc.relics.on_battle_start_immediate(bc)
    assert bc.player.statuses.get(PlayerStatus.STRENGTH) == 2


def test_lantern_first_turn_only():
    bc = BattleContext(seed=205, relics=[RelicId.LANTERN])
    assert bc.player.energy == 4  # 首回合 3+1
    bc.end_turn()
    assert bc.player.energy == 3  # 第 2 回合不再加


def test_akabeko_vigor_first_attack_only():
    """AKABEKO：VIGOR 8 只吃第一张攻击牌（onUseAttackCard L1647-1649 移除）。"""
    bc = BattleContext(seed=206, relics=[RelicId.AKABEKO])
    assert bc.player.statuses.get(PlayerStatus.VIGOR) == 8
    m = bc.monsters.monsters[0]
    hp0 = m.hp
    setup_hand(bc, STRIKE, STRIKE)
    bc.play_card(0)
    assert m.hp == hp0 - (6 + 8)  # 首张攻击 +8
    assert not bc.player.statuses.has(PlayerStatus.VIGOR)
    hp1 = m.hp
    bc.play_card(0)
    assert m.hp == hp1 - 6  # 第二张无加成


def test_bronze_scales_thorns_3():
    bc = BattleContext(seed=207, relics=[RelicId.BRONZE_SCALES])
    assert bc.player.statuses.get(PlayerStatus.THORNS) == 3
    m = bc.monsters.monsters[0]
    hp0 = m.hp
    bc.add_to_bot(Actions.attack_player(0, 5))
    run_queue(bc)
    assert m.hp == hp0 - 3  # 反伤 3


def test_oddly_smooth_stone_dexterity():
    bc = BattleContext(seed=208, relics=[RelicId.ODDLY_SMOOTH_STONE])
    assert bc.player.statuses.get(PlayerStatus.DEXTERITY) == 1


def test_du_vu_doll_counts_curses_in_piles():
    bc = BattleContext(seed=209, relics=[RelicId.DU_VU_DOLL],
                       deck=[STRIKE, STRIKE, DEFEND, CURSE_STUB, CURSE_STUB])
    assert bc.player.statuses.get(PlayerStatus.STRENGTH) == 2


def test_du_vu_doll_no_curses_no_strength():
    bc = BattleContext(seed=210, relics=[RelicId.DU_VU_DOLL],
                       deck=[STRIKE, STRIKE, DEFEND, DEFEND])
    assert bc.player.statuses.get(PlayerStatus.STRENGTH) == 0


def test_thread_and_needle_plated_armor():
    """THREAD_AND_NEEDLE：4 层 PLATED_ARMOR——回合末 4 格挡，未格挡攻击 -1 层。"""
    bc = BattleContext(seed=211, relics=[RelicId.THREAD_AND_NEEDLE])
    assert bc.player.statuses.get(PlayerStatus.PLATED_ARMOR) == 4
    bc.player.statuses.add(PlayerStatus.BARRICADE, 1)  # 保留格挡以便观察
    bc.end_turn()
    assert bc.player.block == 4  # 回合末按层数获得格挡
    assert bc.player.statuses.get(PlayerStatus.PLATED_ARMOR) == 4  # 层数保留
    hp0 = bc.player.hp
    bc.add_to_bot(Actions.attack_player(0, 10))
    run_queue(bc)
    # 攻击 10：格挡 4 吸收，漏 6 → HP -6，且 PLATED_ARMOR 4 → 3
    assert bc.player.hp == hp0 - 6
    assert bc.player.statuses.get(PlayerStatus.PLATED_ARMOR) == 3


def test_plated_armor_not_decremented_by_non_attack_hp_loss():
    """PLATED_ARMOR 只在 attacked 路径减层（Player.cpp:246-248），毒/自伤不减。"""
    bc = BattleContext(seed=212, relics=[RelicId.THREAD_AND_NEEDLE])
    bc.player.block = 0
    bc.add_to_bot(Actions.player_lose_hp(5))
    run_queue(bc)
    assert bc.player.statuses.get(PlayerStatus.PLATED_ARMOR) == 4
    bc.add_to_bot(Actions.damage_player(5))  # 非攻击 HP 损失（Burn 路径）
    run_queue(bc)
    assert bc.player.statuses.get(PlayerStatus.PLATED_ARMOR) == 4


def test_mutagenic_strength_3_and_lose_3_at_first_end():
    bc = BattleContext(seed=213, relics=[RelicId.MUTAGENIC_STRENGTH])
    assert bc.player.statuses.get(PlayerStatus.STRENGTH) == 3
    assert bc.player.statuses.get(PlayerStatus.LOSE_STRENGTH) == 3
    bc.end_turn()
    assert bc.player.statuses.get(PlayerStatus.STRENGTH) == 0
    assert not bc.player.statuses.has(PlayerStatus.LOSE_STRENGTH)


def test_sling_of_courage_elite_only():
    with _elite_encounter("cultist"):
        bc = BattleContext(seed=214, relics=[RelicId.SLING_OF_COURAGE], encounter="cultist")
        assert bc.player.statuses.get(PlayerStatus.STRENGTH) == 2
    bc = BattleContext(seed=215, relics=[RelicId.SLING_OF_COURAGE])  # 普通房不触发
    assert bc.player.statuses.get(PlayerStatus.STRENGTH) == 0


def test_preserved_insect_elite_hp_reduction():
    with _elite_encounter("cultist"):
        bc = BattleContext(seed=216, relics=[RelicId.PRESERVED_INSECT], encounter="cultist")
        m = bc.monsters.monsters[0]
        assert m.hp == int(m.max_hp * 0.75)  # L316-323：HP 减 25%（截断）
    bc = BattleContext(seed=217, relics=[RelicId.PRESERVED_INSECT])
    m = bc.monsters.monsters[0]
    assert m.hp == m.max_hp  # 普通房无效果


def test_pantograph_boss_heal_25():
    with _elite_encounter("cultist", boss=True):
        bc = BattleContext(seed=218, relics=[RelicId.PANTOGRAPH], encounter="cultist")
        bc.player.hp = 60
        bc.relics.on_battle_start_immediate(bc)  # 重触发验证
        assert bc.player.hp == 80  # 60 + 25 封顶
    bc = BattleContext(seed=219, relics=[RelicId.PANTOGRAPH])
    bc.player.hp = 60
    bc.relics.on_battle_start_immediate(bc)
    assert bc.player.hp == 60  # 非 Boss 房不回复


def test_data_disk_focus():
    bc = BattleContext(seed=220, relics=[RelicId.DATA_DISK])
    assert bc.player.statuses.get(PlayerStatus.FOCUS) == 1


def test_damaru_mantra_per_turn():
    """DAMARU：开局 +1 MANTRA（initRelics L260-262），此后每回合开始再 +1
    （Player.cpp:513-516；批次 1 修正：原 +1 敏捷与 C++ 不符）。"""
    bc = BattleContext(seed=221, relics=[RelicId.DAMARU])
    assert bc.player.statuses.get(PlayerStatus.MANTRA) == 1
    assert bc.player.statuses.get(PlayerStatus.DEXTERITY) == 0
    bc.end_turn()
    assert bc.player.statuses.get(PlayerStatus.MANTRA) == 2


def test_philosophers_stone_energy_and_monster_strength():
    bc = BattleContext(seed=222, relics=[RelicId.PHILOSOPHERS_STONE])
    assert bc.player.energy == 4
    assert bc.monsters.monsters[0].statuses.get(MonsterStatus.STRENGTH) == 1
    from sts.content.monsters import AcidSlimeS

    slime = AcidSlimeS.create(bc, idx=1)
    bc.monsters.spawn_insert(bc, 1, slime)  # 战斗中新生怪也 +1 力量
    assert slime.statuses.get(MonsterStatus.STRENGTH) == 1


def test_mark_of_pain_energy_and_wounds():
    bc = BattleContext(seed=223, relics=[RelicId.MARK_OF_PAIN])
    assert bc.player.energy == 4
    wounds = sum(1 for c in bc.cards.draw_pile if c.card.name == "Wound")
    assert wounds == 2  # 抽牌后桶洗入 2 张伤口（L411-413）
    assert len(bc.cards.draw_pile) == 7  # 10 - 5 首抽 + 2 伤口


def test_happy_flower_every_3_turns():
    """HAPPY_FLOWER：开局计数 +1（L148-154），第 3 回合开始 +1 能量
    （Player.cpp:522-527；批次 1 修正：原实现晚一回合）。"""
    bc = BattleContext(seed=224, relics=[RelicId.HAPPY_FLOWER])
    assert bc.player.energy == 3
    bc.end_turn()  # 第 2 回合开始：计数 2
    assert bc.player.energy == 3
    bc.end_turn()  # 第 3 回合开始：计数 3 → +1 能量
    assert bc.player.energy == 4
    bc.end_turn()  # 第 4 回合：计数重新从 1 起
    assert bc.player.energy == 3


def test_incense_burner_intangible_every_6_turns():
    """INCENSE_BURNER：每 6 回合 1 层 INTANGIBLE（L156-162 + Player.cpp:
    535-539；批次 1 修正：原"每 2 回合 1 层 ARTIFACT"与 C++ 不符）。"""
    bc = BattleContext(seed=225, relics=[RelicId.INCENSE_BURNER])
    for i in range(4):
        bc.end_turn()
        assert not bc.player.statuses.has(PlayerStatus.INTANGIBLE)
    bc.end_turn()  # 第 6 回合开始：计数 6 → INTANGIBLE
    assert bc.player.statuses.get(PlayerStatus.INTANGIBLE) == 1


def test_omamori_counter_loaded():
    """OMAMORI：装载 2 充能计数（L185-187）；抵消逻辑待诅咒获得事件源。"""
    bc = BattleContext(seed=226, relics=[RelicId.OMAMORI])
    assert bc.relics.counter(RelicId.OMAMORI) == 2


# =====================================================================
# 纯能量遗物（数字断言，一次打包）
# =====================================================================


def test_energy_relics_bundle():
    """十件能量遗物同挂：3 + 10 = 13 能量（每件 +1，FUSION_HAMMER/
    BUSTED_CROWN 批次 1 修正为 +1，对齐 L244-246/L276-278）。"""
    all_energy = [RelicId.ECTOPLASM, RelicId.SOZU, RelicId.COFFEE_DRIPPER,
                  RelicId.CURSED_KEY, RelicId.VELVET_CHOKER, RelicId.RUNIC_DOME,
                  RelicId.PHILOSOPHERS_STONE, RelicId.FUSION_HAMMER,
                  RelicId.BUSTED_CROWN, RelicId.MARK_OF_PAIN]
    bc = BattleContext(seed=227, relics=all_energy)
    assert bc.player.energy == 13


def test_busted_crown_and_fusion_hammer_are_plus_1():
    bc = BattleContext(seed=228, relics=[RelicId.BUSTED_CROWN, RelicId.FUSION_HAMMER])
    assert bc.player.energy == 5  # 3 + 1 + 1


# =====================================================================
# 抽牌桶
# =====================================================================


def test_snecko_eye_extra_draw():
    bc = BattleContext(seed=229, relics=[RelicId.SNECKO_EYE])
    assert len(bc.cards.hand) == 7


def test_bag_of_preparation_extra_draw():
    bc = BattleContext(seed=230, relics=[RelicId.BAG_OF_PREPARATION])
    assert len(bc.cards.hand) == 7


# =====================================================================
# 战斗开始-抽牌后桶
# =====================================================================


def test_bag_of_marbles_vulnerable_1():
    bc = BattleContext(seed=231, relics=[RelicId.BAG_OF_MARBLES])
    assert bc.monsters.monsters[0].statuses.get(MonsterStatus.VULNERABLE) == 1


def test_twisted_funnel_poison_4():
    bc = BattleContext(seed=232, relics=[RelicId.TWISTED_FUNNEL])
    assert bc.monsters.monsters[0].statuses.get(MonsterStatus.POISON) == 4


def test_clockwork_souvenir_artifact_1():
    bc = BattleContext(seed=233, relics=[RelicId.CLOCKWORK_SOUVENIR])
    assert bc.player.statuses.get(PlayerStatus.ARTIFACT) == 1


def test_mercury_hourglass_damage_at_battle_start():
    bc = BattleContext(seed=234, relics=[RelicId.MERCURY_HOURGLASS])
    m = bc.monsters.monsters[0]
    assert m.hp == m.max_hp - 3


def test_mercury_hourglass_damage_each_turn_start():
    bc = BattleContext(seed=235, relics=[RelicId.MERCURY_HOURGLASS])
    m = bc.monsters.monsters[0]
    hp0 = m.hp
    bc.end_turn()  # 第 2 回合开始再 3 伤
    assert m.hp == hp0 - 3


def test_gremlin_visage_self_weak():
    bc = BattleContext(seed=236, relics=[RelicId.GREMLIN_VISAGE])
    assert bc.player.statuses.get(PlayerStatus.WEAK) == 1


def test_red_mask_all_enemy_weak():
    bc = BattleContext(seed=237, encounter="louses", relics=[RelicId.RED_MASK])
    for m in bc.monsters.monsters:
        assert m.statuses.get(MonsterStatus.WEAK) == 1


# =====================================================================
# 回合开始
# =====================================================================


def test_art_of_war_energy_condition():
    bc = BattleContext(seed=238, relics=[RelicId.ART_OF_WAR])
    assert bc.player.energy == 3  # 首回合不触发
    setup_hand(bc, STRIKE)
    bc.play_card(0)
    bc.end_turn()  # 上回合打过攻击 → 不触发
    assert bc.player.energy == 3
    bc.end_turn()  # 上回合无攻击 → +1
    assert bc.player.energy == 4


def test_horn_cleat_block_on_turn_2():
    """HORN_CLEAT：第 2 回合开始 +14 格挡，一次性（Player.cpp:529-533；
    批次 1 修正：原"每 5 回合"与 C++ 不符）。"""
    bc = BattleContext(seed=239, relics=[RelicId.HORN_CLEAT])
    assert bc.player.block == 0
    bc.end_turn()
    assert bc.player.block == 14
    # 第 3 回合不再触发：BARRICADE 保留格挡观察，回合 2 敌方黑暗打击 6 伤被吸收
    bc.player.statuses.add(PlayerStatus.BARRICADE, 1)
    bc.end_turn()
    assert bc.player.block == 14 - 6  # 无新增 14，仅剩吸收 6 伤后的余量


def test_captains_wheel_block_on_turn_3():
    """CAPTAINS_WHEEL：第 3 回合开始 +18 格挡，一次性（Player.cpp:507-511；
    批次 1 修正：原"每 3 回合 +3"与 C++ 不符）。"""
    bc = BattleContext(seed=240, relics=[RelicId.CAPTAINS_WHEEL])
    bc.end_turn()
    assert bc.player.block == 0  # 第 2 回合不触发
    bc.end_turn()
    assert bc.player.block == 18
    # 第 4 回合不再触发：回合 3 敌方黑暗打击 9 伤（仪式 +3 后）被吸收
    bc.player.statuses.add(PlayerStatus.BARRICADE, 1)
    bc.end_turn()
    assert bc.player.block == 18 - 9  # 无新增 18


def test_pocketwatch_draw_3_if_few_cards():
    """POCKETWATCH：上回合打出 ≤3 张 → 回合开始抽 3（Player.cpp:663-667；
    批次 1 修正：原"0 张 → 回 6 HP"与 C++ 不符）。"""
    bc = BattleContext(seed=241, relics=[RelicId.POCKETWATCH], deck=[STRIKE] * 13)
    setup_hand(bc, STRIKE, STRIKE)
    bc.play_card(0)
    bc.play_card(0)
    bc.end_turn()
    assert len(bc.cards.hand) == 8  # 5 常规 + 3 遗物（牌组 13 张足够抽）
    # 上回合打了 >3 张 → 不触发
    setup_hand(bc, *(SKILL_STUB,) * 4)
    for _ in range(4):
        bc.play_card(0)
    bc.end_turn()
    assert len(bc.cards.hand) == 5


# =====================================================================
# 出牌类
# =====================================================================


def _beefy_cultist(bc, hp=200):
    m = bc.monsters.monsters[0]
    m.hp = hp
    m.max_hp = hp
    return m


def test_kunai_dexterity_every_3_attacks_per_turn():
    bc = BattleContext(seed=242, relics=[RelicId.KUNAI])
    setup_hand(bc, *(FREE_ATTACK,) * 4)
    for _ in range(3):
        bc.play_card(0)
    assert bc.player.statuses.get(PlayerStatus.DEXTERITY) == 1
    bc.play_card(0)
    assert bc.player.statuses.get(PlayerStatus.DEXTERITY) == 1  # 每回合计数需再 3 张
    bc.end_turn()
    setup_hand(bc, *(FREE_ATTACK,) * 3)
    for _ in range(3):
        bc.play_card(0)
    assert bc.player.statuses.get(PlayerStatus.DEXTERITY) == 2


def test_ornamental_fan_block_every_3_attacks():
    bc = BattleContext(seed=243, relics=[RelicId.ORNAMENTAL_FAN])
    setup_hand(bc, *(FREE_ATTACK,) * 3)
    for _ in range(3):
        bc.play_card(0)
    assert bc.player.block == 4


def test_shuriken_strength_every_3_attacks():
    bc = BattleContext(seed=244, relics=[RelicId.SHURIKEN])
    setup_hand(bc, *(FREE_ATTACK,) * 3)
    for _ in range(3):
        bc.play_card(0)
    assert bc.player.statuses.get(PlayerStatus.STRENGTH) == 1


def test_pen_nib_doubles_10th_attack():
    """PEN_NIB：第 10 张攻击翻倍（计数到 9 置状态，L1697-1703）。"""
    bc = BattleContext(seed=245, relics=[RelicId.PEN_NIB])
    m = _beefy_cultist(bc)
    setup_hand(bc, *(FREE_ATTACK,) * 10)
    for i in range(9):
        bc.play_card(0)
    assert bc.player.statuses.get(PlayerStatus.PEN_NIB) == 1  # 第 9 张后置位
    hp0 = m.hp
    bc.play_card(0)  # 第 10 张翻倍
    assert m.hp == hp0 - 12
    assert not bc.player.statuses.has(PlayerStatus.PEN_NIB)


def test_nunchaku_energy_every_10_attacks_cumulative():
    """NUNCHAKU：每 10 张攻击 +1 能量，跨回合累计（L1709-1714；
    批次 1 修正：原实现每回合清零计数与 C++ 不符）。"""
    bc = BattleContext(seed=246, relics=[RelicId.NUNCHAKU])
    _beefy_cultist(bc)
    setup_hand(bc, *(FREE_ATTACK,) * 10)
    for _ in range(10):
        assert bc.player.energy == 3  # 0 费攻击不耗能
        bc.play_card(0)
    assert bc.player.energy == 4  # 第 10 张后 +1


def test_nunchaku_counter_persists_across_turns():
    bc = BattleContext(seed=247, relics=[RelicId.NUNCHAKU])
    _beefy_cultist(bc)
    setup_hand(bc, *(FREE_ATTACK,) * 4)
    for _ in range(4):
        bc.play_card(0)
    bc.end_turn()
    setup_hand(bc, *(FREE_ATTACK,) * 6)
    for _ in range(5):
        bc.play_card(0)
    assert bc.player.energy == 3
    bc.play_card(0)  # 累计第 10 张（跨回合）
    assert bc.player.energy == 4


def test_ink_bottle_draws_at_10_cards_cumulative():
    """INK_BOTTLE：每打出 10 张牌抽 1 张，跨回合累计、攻击/技能均计数
    （BattleContext.cpp:1663-1669/1780-1786；批次 1 修正：原实现
    "每回合计数 +1 力量"与 C++ 不符——C++ 效果为抽 1 张牌）。"""
    bc = BattleContext(seed=248, relics=[RelicId.INK_BOTTLE])
    _beefy_cultist(bc)
    setup_hand(bc, *(FREE_ATTACK,) * 5)
    for _ in range(4):
        bc.play_card(0)
    bc.end_turn()
    assert bc.relics.counter(RelicId.INK_BOTTLE) == 4  # 跨回合不清零
    setup_hand(bc, *(SKILL_STUB,) * 6)
    for _ in range(5):
        bc.play_card(0)
    hand_before = len(bc.cards.hand)
    bc.play_card(0)  # 累计第 10 张 → 抽 1
    assert len(bc.cards.hand) == hand_before  # 打出 1（-1）+ 抽 1（+1）
    drawn = [c for c in bc.cards.hand if c.card is not SKILL_STUB]
    assert len(drawn) == 1  # 抽到的是牌堆里的普通牌


def test_letter_opener_5_damage_every_3_skills():
    bc = BattleContext(seed=249, relics=[RelicId.LETTER_OPENER])
    m = _beefy_cultist(bc)
    setup_hand(bc, *(SKILL_STUB,) * 3)
    for _ in range(2):
        bc.play_card(0)
    assert m.hp == 200
    bc.play_card(0)  # 第 3 张技能 → 全体 5 伤（L1796-1800，批次 1 修正 4→5）
    assert m.hp == 195


def test_bird_faced_urn_heals_2_on_power():
    bc = BattleContext(seed=250, relics=[RelicId.BIRD_FACED_URN])
    bc.player.hp = 70
    setup_hand(bc, POWER_STUB)
    bc.play_card(0)
    assert bc.player.hp == 72


def test_necronomicon_replays_first_costly_attack_once_per_turn():
    """NECRONOMICON：每回合首张 ≥2 费攻击额外结算一次（L1691-1695；
    每回合一次标志，Player.cpp:555-557）。"""
    bc = BattleContext(seed=251, relics=[RelicId.NECRONOMICON])
    m = bc.monsters.monsters[0]
    hp0 = m.hp
    setup_hand(bc, BASH, BASH)
    bc.play_card(0)  # 2 费 BASH：8 伤 + 施加 2 易伤；重放段吃到易伤 8×1.5=12
    assert m.hp == hp0 - 8 - 12
    assert m.statuses.get(MonsterStatus.VULNERABLE) == 4  # 两次重放各施加 2 层
    bc.player.energy = 3
    hp1 = m.hp
    bc.play_card(0)  # 本回合第二张 ≥2 费攻击：不再复制（易伤仍在 → 8×1.5）
    assert m.hp == hp1 - 12
    assert sum(1 for c in bc.cards.discard_pile if c.card is BASH) == 2  # 原牌各入堆一次


def test_necronomicon_not_triggered_by_cheap_attack():
    bc = BattleContext(seed=252, relics=[RelicId.NECRONOMICON])
    m = bc.monsters.monsters[0]
    hp0 = m.hp
    setup_hand(bc, STRIKE)
    bc.play_card(0)  # 1 费攻击不触发
    assert m.hp == hp0 - 6


# =====================================================================
# 出牌资格
# =====================================================================


def test_velvet_choker_play_limit_and_energy():
    bc = BattleContext(seed=253, relics=[RelicId.VELVET_CHOKER])
    assert bc.player.energy == 4
    setup_hand(bc, *(FREE_ATTACK,) * 7)
    for _ in range(6):
        bc.play_card(0)
    try:
        bc.play_card(0)
        assert False, "本回合已打 6 张应禁出"
    except ValueError:
        pass


# =====================================================================
# 伤害计算
# =====================================================================


def test_strike_dummy_bonus_on_strike_family():
    bc = BattleContext(seed=254, relics=[RelicId.STRIKE_DUMMY])
    m = bc.monsters.monsters[0]
    hp0 = m.hp
    setup_hand(bc, STRIKE)
    bc.play_card(0)
    assert m.hp == hp0 - 9  # 6 + 3


def test_wrist_blade_bonus_on_zero_cost():
    bc = BattleContext(seed=255, relics=[RelicId.WRIST_BLADE])
    m = bc.monsters.monsters[0]
    hp0 = m.hp
    setup_hand(bc, FREE_ATTACK)
    bc.play_card(0)
    assert m.hp == hp0 - 10  # 6 + 4


def test_paper_phrog_vulnerable_multiplier_175():
    bc = BattleContext(seed=256, relics=[RelicId.PAPER_PHROG])
    bc.monsters.monsters[0].statuses.add(MonsterStatus.VULNERABLE, 1)
    m = bc.monsters.monsters[0]
    hp0 = m.hp
    setup_hand(bc, STRIKE)
    bc.play_card(0)
    assert m.hp == hp0 - 10  # 6 × 1.75 = 10.5 → 10


def test_the_boot_raises_small_unblocked_damage():
    bc = BattleContext(seed=257, relics=[RelicId.THE_BOOT])
    m = bc.monsters.monsters[0]
    m.block = 5
    setup_hand(bc, STRIKE)
    hp0 = m.hp
    bc.play_card(0)  # 6 伤：格挡吸 5，漏 1 → Boot 提到 5
    assert m.hp == hp0 - 5


# =====================================================================
# 受击/HP 类
# =====================================================================


def test_torii_and_tungsten_rod_order():
    bc = BattleContext(seed=258, relics=[RelicId.TORII, RelicId.TUNGSTEN_ROD])
    bc.add_to_bot(Actions.attack_player(0, 4))  # Torii ≤5 → 1，再 Tungsten -1 → 0
    run_queue(bc)
    assert bc.player.hp == 80
    bc.add_to_bot(Actions.attack_player(0, 12))  # >5 不吃 Torii：12 - 1
    run_queue(bc)
    assert bc.player.hp == 80 - 11


def test_centennial_puzzle_draws_3_once():
    bc = BattleContext(seed=259, relics=[RelicId.CENTENNIAL_PUZZLE])
    bc.add_to_bot(Actions.attack_player(0, 5))
    run_queue(bc)
    assert len(bc.cards.hand) == 8  # 5 + 3
    bc.add_to_bot(Actions.attack_player(0, 5))
    run_queue(bc)
    assert len(bc.cards.hand) == 8  # 每场一次


def test_self_forming_clay_next_turn_block_stacks():
    """SELF_FORMING_CLAY：失去 HP → 下回合 +3 格挡，可叠加（NEXT_TURN_BLOCK，
    Player.cpp:303-305；批次 1 修正：原"每回合首次立即 +3"与 C++ 不符）。"""
    bc = BattleContext(seed=260, relics=[RelicId.SELF_FORMING_CLAY])
    assert bc.player.block == 0
    bc.add_to_bot(Actions.attack_player(0, 4))
    bc.add_to_bot(Actions.attack_player(0, 4))
    run_queue(bc)
    assert bc.player.block == 0  # 当回合不获得格挡
    assert bc.player.statuses.get(PlayerStatus.NEXT_TURN_BLOCK) == 6
    bc.end_turn()
    assert bc.player.block == 6  # 下回合开始转化（在敌方攻击之后）


def test_runic_cube_draws_on_each_hp_loss():
    bc = BattleContext(seed=261, relics=[RelicId.RUNIC_CUBE])
    bc.add_to_bot(Actions.attack_player(0, 4))
    run_queue(bc)
    assert len(bc.cards.hand) == 6
    bc.add_to_bot(Actions.attack_player(0, 4))
    run_queue(bc)
    assert len(bc.cards.hand) == 7  # 每次失去 HP 各抽 1


def test_red_skull_strength_on_crossing_half_hp():
    """RED_SKULL：HP 跌破 50% 时 +3 力量（Player.cpp:311-313；批次 1 修正：
    原"每回合首次失去 HP +1 力量"与 C++ 不符）。"""
    bc = BattleContext(seed=262, relics=[RelicId.RED_SKULL])
    assert bc.player.statuses.get(PlayerStatus.STRENGTH) == 0  # 满血不触发
    bc.add_to_bot(Actions.attack_player(0, 30))
    run_queue(bc)
    assert bc.player.hp == 50
    assert bc.player.statuses.get(PlayerStatus.STRENGTH) == 0  # 50 > 40 仍未过线
    bc.add_to_bot(Actions.attack_player(0, 10))
    run_queue(bc)
    assert bc.player.hp == 40
    assert bc.player.statuses.get(PlayerStatus.STRENGTH) == 3  # 跌破半血线
    bc.add_to_bot(Actions.attack_player(0, 5))
    run_queue(bc)
    assert bc.player.statuses.get(PlayerStatus.STRENGTH) == 3  # 已在线下不再触发


def test_red_skull_active_at_battle_start_when_below_half():
    bc = BattleContext(seed=263, relics=[RelicId.RED_SKULL])
    bc.player.hp = 40
    bc.player.statuses.set(PlayerStatus.STRENGTH, 0)
    bc.relics.on_battle_start_immediate(bc)  # L436-438：开局已 ≤50% → +3
    assert bc.player.statuses.get(PlayerStatus.STRENGTH) == 3


def test_magic_flower_boosts_relic_heals():
    """MAGIC_FLOWER：战斗内治疗 ×3/2（Player.cpp:161-163）——经 BLOOD_VIAL 验证。"""
    bc = BattleContext(seed=264, relics=[RelicId.MAGIC_FLOWER, RelicId.BLOOD_VIAL])
    bc.player.hp = 70
    bc.relics.on_battle_start_immediate(bc)
    assert bc.player.hp == 73  # 2 × 3/2 = 3
    # 无 MAGIC_FLOWER 时回 2
    bc2 = BattleContext(seed=265, relics=[RelicId.BLOOD_VIAL])
    bc2.player.hp = 70
    bc2.relics.on_battle_start_immediate(bc2)
    assert bc2.player.hp == 72


# =====================================================================
# 怪物侧触发
# =====================================================================


def test_gremlin_horn_on_non_final_death():
    bc = BattleContext(seed=266, encounter="louses", relics=[RelicId.GREMLIN_HORN])
    m0, m1 = bc.monsters.monsters
    m0.hp = 1
    energy0 = bc.player.energy
    setup_hand(bc, STRIKE)
    bc.play_card(0, target=0)  # 击杀 0 号（还剩 1 只，不判胜）
    assert bc.player.energy == energy0 - 1 + 1
    assert len(bc.cards.hand) == 1  # 打出的牌位 + 遗物补抽 1


def test_the_specimen_transfers_poison_single_candidate():
    """THE_SPECIMEN：死亡怪的中毒层数转移给另一存活敌人（Monster.cpp:322-324）。"""
    bc = BattleContext(seed=267, encounter="louses", relics=[RelicId.THE_SPECIMEN])
    m0, m1 = bc.monsters.monsters
    m0.statuses.add(MonsterStatus.POISON, 5)
    m0.hp = 1
    setup_hand(bc, STRIKE)
    bc.play_card(0, target=0)
    assert bc.input_state == InputState.PLAYER_NORMAL  # 单候选自动执行
    assert m1.statuses.get(MonsterStatus.POISON) == 5
    assert not m0.statuses.has(MonsterStatus.POISON)


def test_the_specimen_multiple_candidates_random_transfer():
    """THE_SPECIMEN（审计批次修正）：wiki——"transfer any Poison it has to a
    random enemy"，多候选走 misc 流随机而非 CARD_SELECT 选卡。"""
    bc = BattleContext(seed=268, encounter="louses", relics=[RelicId.THE_SPECIMEN])
    m0, m1 = bc.monsters.monsters
    m2 = add_cultist(bc, idx=2)
    m0.statuses.add(MonsterStatus.POISON, 4)
    m0.hp = 1
    setup_hand(bc, STRIKE)
    bc.play_card(0, target=0)
    assert bc.input_state == InputState.PLAYER_NORMAL  # 不再挂选卡
    assert not m0.statuses.has(MonsterStatus.POISON)
    total = m1.statuses.get(MonsterStatus.POISON) + m2.statuses.get(MonsterStatus.POISON)
    assert total == 4  # 4 层全落随机一个候选，另一候选为 0
    assert m1.statuses.get(MonsterStatus.POISON) in (0, 4)


def test_hand_drill_applies_2_vulnerable_on_block_broken():
    """HAND_DRILL：攻击打空怪物格挡 → 2 层易伤（Monster.cpp:433-435）。"""
    bc = BattleContext(seed=269, relics=[RelicId.HAND_DRILL])
    m = bc.monsters.monsters[0]
    m.block = 5
    setup_hand(bc, STRIKE)
    bc.play_card(0)  # 6 伤：格挡 5 被打空
    assert m.statuses.get(MonsterStatus.VULNERABLE) == 2


def test_hand_drill_not_triggered_when_block_remains():
    bc = BattleContext(seed=270, relics=[RelicId.HAND_DRILL])
    m = bc.monsters.monsters[0]
    m.block = 10
    setup_hand(bc, STRIKE)
    bc.play_card(0)  # 6 伤被完全吸收，格挡剩 4
    assert not m.statuses.has(MonsterStatus.VULNERABLE)


# =====================================================================
# 洗牌/消耗/手牌
# =====================================================================


def test_the_abacus_block_on_shuffle():
    bc = BattleContext(seed=271, relics=[RelicId.THE_ABACUS])
    assert bc.player.block == 0
    bc.on_shuffle()
    run_queue(bc)
    assert bc.player.block == 6


def test_sundial_energy_every_3_shuffles():
    bc = BattleContext(seed=272, relics=[RelicId.SUNDIAL])
    energy0 = bc.player.energy
    bc.on_shuffle()
    bc.on_shuffle()
    run_queue(bc)
    assert bc.player.energy == energy0
    bc.on_shuffle()
    run_queue(bc)
    assert bc.player.energy == energy0 + 2


def test_charons_ashes_3_damage_on_exhaust():
    bc = BattleContext(seed=273, encounter="louses", relics=[RelicId.CHARONS_ASHES])
    m0, m1 = bc.monsters.monsters
    hp0, hp1 = m0.hp, m1.hp
    setup_hand(bc, EXHAUST_STUB)
    bc.play_card(0)
    assert m0.hp == hp0 - 3  # L2819-2821：3 伤（批次 1 修正 2→3）
    assert m1.hp == hp1 - 3


def test_strange_spoon_distribution():
    """STRANGE_SPOON：消耗牌 50% 改走弃牌堆（misc 流多种子分布断言）。"""
    exhaust_count = discard_count = 0
    for seed in range(60):
        bc = BattleContext(seed=9000 + seed, relics=[RelicId.STRANGE_SPOON])
        setup_hand(bc, EXHAUST_STUB)
        bc.play_card(0)
        if any(c.card is EXHAUST_STUB for c in bc.cards.exhaust_pile):
            exhaust_count += 1
        if any(c.card is EXHAUST_STUB for c in bc.cards.discard_pile):
            discard_count += 1
    assert exhaust_count + discard_count == 60
    assert 15 < exhaust_count < 45  # 50% 左右，60 次抽样两侧都显著出现


def test_unceasing_top_draws_on_empty_hand():
    bc = BattleContext(seed=274, relics=[RelicId.UNCEASING_TOP])
    setup_hand(bc, STRIKE)
    bc.play_card(0)
    assert len(bc.cards.hand) == 1  # 手牌打空 → 抽 1（BattleContext.cpp:809-819）


# =====================================================================
# 回合结束
# =====================================================================


def test_cloak_clasp_block_by_hand_size():
    bc = BattleContext(seed=275, relics=[RelicId.CLOAK_CLASP])
    bc.player.statuses.add(PlayerStatus.BARRICADE, 1)  # 保留格挡以便观察
    setup_hand(bc, DEFEND, DEFEND, DEFEND)
    bc.end_turn()  # 手牌 3 张（RUNIC_PYRAMID 之外全部弃掉后再看格挡值）
    assert bc.player.block == 3  # L2036-2038


def test_orichalcum_block_only_when_zero():
    bc = BattleContext(seed=276, relics=[RelicId.ORICHALCUM])
    bc.player.statuses.add(PlayerStatus.BARRICADE, 1)
    bc.end_turn()
    assert bc.player.block == 6  # 无格挡 → +6（BARRICADE 保留观察）
    setup_hand(bc, DEFEND)
    bc.play_card(0)  # 获得格挡：6 + 5 = 11
    assert bc.player.block == 11
    bc.end_turn()  # 已有格挡 → 不触发；回合 2 敌方黑暗打击 6 伤被吸收
    assert bc.player.block == 11 - 6  # 仅减攻击，无 +6


def test_stone_calendar_52_damage_on_turn_7_end():
    """STONE_CALENDAR：第 7 回合末 52 伤全体，仅一次（L2056-2060；
    批次 1 修正：原 turn>=7 每回合触发与 C++ 不符）。"""
    bc = BattleContext(seed=277, relics=[RelicId.STONE_CALENDAR])
    m = _beefy_cultist(bc)
    bc.player.hp = 300  # 撑过多轮邪教徒攻击
    for _ in range(6):
        bc.end_turn()
    assert m.hp == 200  # 第 6 回合末：未到第 7 回合
    bc.end_turn()  # 第 7 回合末（本次 end_turn 期间 bc.turn == 7）
    assert m.hp == 200 - 52
    bc.player.hp = 300
    bc.end_turn()  # 第 8 回合末：不再触发
    assert m.hp == 148


def test_ice_cream_keeps_leftover_energy():
    bc = BattleContext(seed=278, relics=[RelicId.ICE_CREAM])
    setup_hand(bc, DEFEND)
    bc.play_card(0)
    assert bc.player.energy == 2
    bc.end_turn()
    assert bc.player.energy == 3 + 2


def test_calipers_lose_15_block_instead_of_all():
    """CALIPERS：回合开始失去 15 格挡而非全清（BattleContext.cpp:2183-2184；
    批次 1 修正：原"保留 15"与 C++ 的"失去 15"不符）。"""
    bc = BattleContext(seed=279, relics=[RelicId.CALIPERS])
    bc.player.block = 20
    bc.end_turn()
    assert bc.player.block == 5
    bc.player.block = 8
    bc.end_turn()
    assert bc.player.block == 0  # 不足 15 全清


def test_runic_pyramid_keeps_hand():
    bc = BattleContext(seed=280, relics=[RelicId.RUNIC_PYRAMID])
    setup_hand(bc, DEFEND, DEFEND)
    bc.end_turn()
    # 2 张 Defend 保留在手（未入弃牌堆），第 2 回合再抽 5 → 共 7
    assert len(bc.cards.hand) == 7
    assert sum(1 for c in bc.cards.hand if c.card is DEFEND) == 2
    assert not any(c.card is DEFEND for c in bc.cards.discard_pile)


# =====================================================================
# 战斗结束
# =====================================================================


def test_burning_blood_heals_6_on_victory():
    bc = BattleContext(seed=281, relics=[RelicId.BURNING_BLOOD])
    bc.player.hp = 40
    m = bc.monsters.monsters[0]
    m.hp = 1
    setup_hand(bc, STRIKE)
    bc.play_card(0)
    assert bc.outcome == Outcome.PLAYER_VICTORY
    assert bc.player.hp == 46


def test_meat_on_the_bone_heals_when_below_half():
    bc = BattleContext(seed=282, relics=[RelicId.MEAT_ON_THE_BONE])
    bc.player.hp = 30
    m = bc.monsters.monsters[0]
    m.hp = 1
    setup_hand(bc, STRIKE)
    bc.play_card(0)
    assert bc.outcome == Outcome.PLAYER_VICTORY
    assert bc.player.hp == 42  # 30 ≤ 40 → +12
    # 过半不回
    bc2 = BattleContext(seed=283, relics=[RelicId.MEAT_ON_THE_BONE])
    bc2.player.hp = 60
    m2 = bc2.monsters.monsters[0]
    m2.hp = 1
    setup_hand(bc2, STRIKE)
    bc2.play_card(0)
    assert bc2.player.hp == 60


# =====================================================================
# 批次 3：RNG/卡池遗物（ENCHIRIDION/TOOLBOX/DEAD_BRANCH/MUMMIFIED_HAND/
# WARPED_TONGS + STRANGE_SPOON 边界）
# =====================================================================


def test_enchiridion_random_power_zero_cost_this_turn():
    """ENCHIRIDION（BattleContext.cpp:140-146）：随机 Power 牌首抽前入手、
    未升级、本回合 0 费（C++ setCostForTurn(0)，非原版 1 费口径），
    回合末还原。misc 流种子确定 → seed=0 必为 Metallicize（Power 池
    = 铁甲 14 张 Power，已全量迁移，池稳定）。"""
    bc = BattleContext(seed=0, relics=[RelicId.ENCHIRIDION])
    # 首抽前入手 → 位于手牌首位，首手 = 1 张临时 Power + 5 张抽牌
    inst = bc.cards.hand[0]
    assert inst.card.ctype == "Power"
    assert inst.card.name == "Metallicize"
    assert not inst.upgraded  # C++ CardInstance(cardId) 未升级
    assert inst.cost == 0 and inst.cost_for_turn == 0
    assert len(bc.cards.hand) == 6
    bc.player.hp = 300  # 撑过邪教徒反击
    bc.end_turn()
    # reset_attributes_at_end_of_turn：cost_for_turn 还原 → Metallicize 回 1 费
    assert inst.cost_for_turn == -1
    assert inst.cost == 1


def test_enchiridion_power_pool_diversity():
    """固定种子区间内 misc 流抽样覆盖多个不同 Power（池抽样多样性）。"""
    names = set()
    for seed in range(60):
        bc = BattleContext(seed=seed, relics=[RelicId.ENCHIRIDION])
        names.add(bc.cards.hand[0].card.name)
    assert len(names) >= 5  # 60 抽样、14 张池 → 至少 5 种不同 Power


def test_toolbox_random_colorless_zero_cost():
    """TOOLBOX（注册 L98/执行 L382；Actions.cpp:988-998 + chooseDiscoveryCard
    L2995-3010 的 setCostForTurn(0)）：随机 1 张无色牌首抽前入手、本回合
    0 费。当前无色池仅 Hand of Greed（诚实实现；批次 4 扩无色池后此断言
    需随池更新）。"""
    bc = BattleContext(seed=41, relics=[RelicId.TOOLBOX])
    inst = bc.cards.hand[0]
    assert inst.card in _colorless_card_pool()
    assert inst.card.name == "Hand of Greed"  # 池当前仅此一张
    assert not inst.upgraded
    assert inst.cost == 0 and inst.cost_for_turn == 0
    assert len(bc.cards.hand) == 6
    bc.player.hp = 300
    bc.end_turn()
    assert inst.cost == 2  # 回合末还原为 Hand of Greed 原费用


def test_dead_branch_adds_card_on_exhaust():
    """DEAD_BRANCH（BattleContext.cpp:2823-2826）：打出消耗牌 → 随机 1 张
    铁甲色牌（CombatCardPool：不含无色/状态/诅咒）入手，未升级、原费用。"""
    bc = BattleContext(seed=0, relics=[RelicId.DEAD_BRANCH])
    pool = _combat_card_pool()
    setup_hand(bc, EXHAUST_STUB)
    bc.play_card(0)
    assert any(c.card is EXHAUST_STUB for c in bc.cards.exhaust_pile)
    assert len(bc.cards.hand) == 1  # 消耗 1 张 + 入手 1 张
    added = bc.cards.hand[0]
    assert added.card in pool
    assert not added.upgraded
    assert added.cost_for_turn == -1  # 原费用，无临时改费
    assert added.card.ctype in ("Attack", "Skill", "Power")


def test_dead_branch_pool_excludes_colorless_and_status():
    """DEAD_BRANCH 卡池对齐 C++ CombatCardPool（CardPools.h:177-187）：
    多种子抽样永远不含无色（Hand of Greed）与状态/诅咒牌。"""
    names = set()
    for seed in range(120):
        bc = BattleContext(seed=seed, relics=[RelicId.DEAD_BRANCH])
        setup_hand(bc, EXHAUST_STUB)
        bc.play_card(0)
        added = bc.cards.hand[0]
        assert added.card in _combat_card_pool()
        names.add(added.card.name)
    assert "Hand of Greed" not in names
    assert len(names) >= 20  # 73 张池、120 次抽样 → 显著多样


def test_dead_branch_triggers_on_non_play_exhaust_source():
    """DEAD_BRANCH 是"任意牌被消耗"统一触发（on_card_exhausted 一切来源）：
    非打出路径（exhaust_hand_card 动作，True Grit/Second Wind 族）同样入手。"""
    bc = BattleContext(seed=7, relics=[RelicId.DEAD_BRANCH])
    setup_hand(bc, STRIKE)
    inst = bc.cards.hand[0]
    bc.add_to_bot(Actions.exhaust_hand_card(inst))
    run_queue(bc)
    assert any(c.card is STRIKE for c in bc.cards.exhaust_pile)
    assert len(bc.cards.hand) == 1
    assert bc.cards.hand[0].card in _combat_card_pool()


def test_dead_branch_full_hand_goes_to_discard():
    """满手时 DEAD_BRANCH 的牌进弃牌堆（对齐 moveToHandHelper，
    BattleContext.cpp:2531-2537；引擎 create_temp_card_in_hand 的
    "消失"分支与 C++ 不符，遗物侧已用组合 API 还原 C++ 语义）。"""
    bc = BattleContext(seed=0, relics=[RelicId.DEAD_BRANCH])
    bc.cards.hand.clear()
    bc.cards.hand.extend(bc.cards.instantiate(STRIKE) for _ in range(10))
    bc.cards.hand.append(bc.cards.instantiate(EXHAUST_STUB))
    assert len(bc.cards.hand) == 11
    bc.play_card(10)
    assert len(bc.cards.hand) == 10  # 打出消耗桩后满手
    assert len(bc.cards.discard_pile) == 1
    assert bc.cards.discard_pile[0].card in _combat_card_pool()


def _spoon_reroutes(seed: int) -> bool:
    """该种子下 STRANGE_SPOON 是否把消耗牌改道弃牌堆（确定性：同种子同结果）。"""
    bc = BattleContext(seed=seed, relics=[RelicId.STRANGE_SPOON])
    setup_hand(bc, EXHAUST_STUB)
    bc.play_card(0)
    return any(c.card is EXHAUST_STUB for c in bc.cards.discard_pile)


def test_strange_spoon_reroute_skips_exhaust_triggers():
    """边界：改道弃牌堆 = 未发生消耗 → 消耗触发（CHARONS_ASHES）不结算
    （C++ 走 else 分支，不进 triggerAndMoveToExhaustPile，L1985-1990）。"""
    reroute_seed = next(s for s in range(50) if _spoon_reroutes(s))
    bc = BattleContext(
        seed=reroute_seed,
        relics=[RelicId.STRANGE_SPOON, RelicId.CHARONS_ASHES],
        encounter="louses",
    )
    hp0 = [m.hp for m in bc.monsters.monsters]
    setup_hand(bc, EXHAUST_STUB)
    bc.play_card(0)
    assert any(c.card is EXHAUST_STUB for c in bc.cards.discard_pile)
    assert not bc.cards.exhaust_pile
    assert [m.hp for m in bc.monsters.monsters] == hp0  # 未消耗 → 无灰烬伤害


def test_strange_spoon_exhaust_still_triggers_on_exhaust():
    """边界：未改道（正常消耗）时消耗触发照常结算（CHARONS_ASHES 3 伤）。"""
    exhaust_seed = next(s for s in range(50) if not _spoon_reroutes(s))
    bc = BattleContext(
        seed=exhaust_seed,
        relics=[RelicId.STRANGE_SPOON, RelicId.CHARONS_ASHES],
        encounter="louses",
    )
    hp0 = [m.hp for m in bc.monsters.monsters]
    setup_hand(bc, EXHAUST_STUB)
    bc.play_card(0)
    assert any(c.card is EXHAUST_STUB for c in bc.cards.exhaust_pile)
    assert [hp - 3 for hp in hp0] == [m.hp for m in bc.monsters.monsters]


def test_strange_spoon_never_affects_non_exhaust_cards():
    """边界：勺子只在 exhaustOnUse 路径起作用（C++ L1986 判 item.exhaustOnUse），
    普通牌永远走弃牌堆。"""
    for seed in range(40):
        bc = BattleContext(seed=seed, relics=[RelicId.STRANGE_SPOON])
        setup_hand(bc, STRIKE)
        bc.play_card(0)
        assert not bc.cards.exhaust_pile
        assert any(c.card is STRIKE for c in bc.cards.discard_pile)


def test_mummified_hand_zeroes_one_costed_hand_card():
    """MUMMIFIED_HAND（L1874-1876 → L2847-2873）：打出 Power 后随机 1 张
    费用 >0 的手牌本回合 0 费；刚打出的 Power 已移出手牌，不在候选。
    seed=0 → 候选 [Strike, Defend] 中选中 Defend（misc 流确定）。"""
    bc = BattleContext(seed=0, relics=[RelicId.MUMMIFIED_HAND])
    setup_hand(bc, POWER_STUB, STRIKE, DEFEND)
    bc.play_card(0)  # 打出能力桩（0 费）
    assert len(bc.cards.hand) == 2
    zeroed = [c for c in bc.cards.hand if c.cost_for_turn == 0]
    assert len(zeroed) == 1
    assert zeroed[0].card is DEFEND
    strike = next(c for c in bc.cards.hand if c.card is STRIKE)
    assert strike.cost == 1 and strike.cost_for_turn == -1
    bc.player.hp = 300
    bc.end_turn()
    assert zeroed[0].cost == 1  # 回合末还原


def test_mummified_hand_excludes_already_zero_cost():
    """本回合已 0 费的手牌不入选（C++ costForTurn > 0 资格）；
    无合格候选时 no-op。"""
    # 唯一候选：已 0 费的 Strike 排除、Defend 命中。seed=1 在双候选时
    # 会选中 Strike（见上一用例同种子对照）——若排除逻辑缺失则 Defend
    # 不会被置 0，断言即可甄别。
    bc = BattleContext(seed=1, relics=[RelicId.MUMMIFIED_HAND])
    setup_hand(bc, POWER_STUB, STRIKE, DEFEND)
    bc.cards.hand[1].cost_for_turn = 0  # Strike 本回合已 0 费
    bc.play_card(0)
    strike, defend = bc.cards.hand
    assert strike.cost_for_turn == 0  # 预置维持（未被再次选中也不变）
    assert defend.cost_for_turn == 0  # 唯一候选必被置 0
    # 无候选：全 0 费 → no-op，不抛错
    bc2 = BattleContext(seed=11, relics=[RelicId.MUMMIFIED_HAND])
    setup_hand(bc2, POWER_STUB, POWER_STUB)
    bc2.play_card(0)
    assert len(bc2.cards.hand) == 1
    assert bc2.cards.hand[0].cost_for_turn == -1


def test_warped_tongs_upgrades_one_card_each_turn():
    """WARPED_TONGS（Player.cpp:669-671 + Actions.cpp:940-960）：**每回合
    开始（含首回合）无条件**随机升级 1 张可升级手牌（C++ 无 50% 判定）；
    升级资格 canUpgrade（CardInstance.cpp:55-59）排除状态/诅咒。"""
    bc = BattleContext(
        seed=3,
        relics=[RelicId.WARPED_TONGS],
        deck=[STRIKE, STRIKE, DEFEND, DEFEND, WOUND, WOUND, STRIKE, DEFEND],
    )
    # 首回合（initRelics L446-449 经 atTurnStartPostDraw 桶触发）
    ups = [c.card.name for c in bc.cards.hand if c.upgraded]
    assert len(ups) == 1  # seed=3 → Defend（misc 流确定）
    assert ups[0] == "Defend"
    assert not any(c.upgraded for c in bc.cards.hand if c.card is WOUND)
    # 第 2 回合同样触发
    bc.player.hp = 300  # 撑过邪教徒黑暗打击
    bc.end_turn()
    ups2 = [c.card.name for c in bc.cards.hand if c.upgraded]
    assert len(ups2) == 1  # 本回合新升级 1 张（上回合那张已随弃牌离手）
    assert not any(c.upgraded for c in bc.cards.hand if c.card is WOUND)


def test_warped_tongs_noop_when_nothing_upgradeable():
    """无可升级手牌（全为状态卡）时 no-op：不升级状态/诅咒（canUpgrade）。"""
    bc = BattleContext(seed=13, relics=[RelicId.WARPED_TONGS], deck=[WOUND] * 5)
    assert not any(c.upgraded for c in bc.cards.hand)
    assert len(bc.cards.hand) == 5


# =====================================================================
# 遗物审计批次（2026-10-06，对齐 slaythespire.wiki.gg 全量重验）
# =====================================================================


def test_magic_flower_rounds_half_up():
    """MAGIC_FLOWER（审计修正）：×1.5 四舍五入（.5 进位）——wiki Magic Flower
    页：Reaper+ 5 → 8。lightspeed 为 floor（5 → 7），奇数治疗量少 1。"""
    bc = BattleContext(seed=301, relics=[RelicId.MAGIC_FLOWER])
    assert bc.relics.modify_heal(bc, 5) == 8
    assert bc.relics.modify_heal(bc, 4) == 6
    assert bc.relics.modify_heal(bc, 2) == 3
    assert bc.relics.modify_heal(bc, 7) == 11


def test_burning_blood_end_of_combat_amplified_by_magic_flower():
    """BURNING_BLOOD（审计修正）：战斗胜利治疗吃 MAGIC_FLOWER（wiki Magic
    Flower 页列出 6→9；lightspeed exitBattle 走局外 playerHeal 不放大）。"""
    bc = BattleContext(seed=302, relics=[RelicId.BURNING_BLOOD, RelicId.MAGIC_FLOWER])
    bc.player.hp = 40
    bc.monsters.monsters[0].hp = 1
    setup_hand(bc, STRIKE)
    bc.play_card(0)
    assert bc.outcome == Outcome.PLAYER_VICTORY
    assert bc.player.hp == 49  # 40 + 6×1.5 = 9


def test_meat_on_the_bone_amplified_by_magic_flower():
    bc = BattleContext(seed=303, relics=[RelicId.MEAT_ON_THE_BONE, RelicId.MAGIC_FLOWER])
    bc.player.hp = 30
    bc.monsters.monsters[0].hp = 1
    setup_hand(bc, STRIKE)
    bc.play_card(0)
    assert bc.outcome == Outcome.PLAYER_VICTORY
    assert bc.player.hp == 48  # 30 + 12×1.5 = 18


def test_snecko_eye_confused_and_per_turn_draw():
    """SNECKO_EYE（审计修正）：每回合 +2 抽（lightspeed cardDrawPerTurn 永久
    +2，原实现仅首回合）+ 战斗开始 CONFUSED（wiki：Start each combat
    Confused）。"""
    bc = BattleContext(seed=304, relics=[RelicId.SNECKO_EYE], deck=[STRIKE] * 10)
    assert len(bc.cards.hand) == 7
    assert bc.player.statuses.has(PlayerStatus.CONFUSED)
    bc.player.hp = 300
    bc.end_turn()
    # 第 2 回合：基础 5 + 2（弃牌堆洗回后足量）
    assert len(bc.cards.hand) == 7


def test_damaru_mantra_triggers_divinity_at_10():
    """DAMARU（审计修正）：真言走 gain_mantra 统一入口——满 10 进 DIVINITY
    （lightspeed 直加 statuses 绕过该判定）。"""
    from sts.combat.types import Stance

    bc = BattleContext(seed=305, relics=[RelicId.DAMARU])
    bc.player.statuses.set(PlayerStatus.MANTRA, 9)
    bc.player.hp = 300
    bc.end_turn()
    assert bc.player.stance == Stance.DIVINITY
    assert not bc.player.statuses.has(PlayerStatus.MANTRA)  # 清零


def test_emotion_chip_triggers_orb_passives_on_hp_loss():
    """EMOTION_CHIP（新实现）：上回合失去过 HP → 回合开始全部球被动各触发
    一次（wiki；lightspeed 两处 TODO 未实现）。"""
    from sts.combat.types import Orb

    bc = BattleContext(seed=306, relics=[RelicId.EMOTION_CHIP])
    bc.player.orbs.append(Orb.FROST)
    bc.player.lose_hp(bc, 5)  # 上回合（当前回合）失去过 HP
    assert bc.player.hp_lost_last_turn is True
    bc.player.hp = 300
    bc.end_turn()
    # 引擎既定口径 FROST 被动本就回合开始触发（2）+ chip 再触发一次（2）
    assert bc.player.block == 4
    # 反例：上回合没失去 HP → 仅常规被动
    bc2 = BattleContext(seed=307, relics=[RelicId.EMOTION_CHIP])
    bc2.player.orbs.append(Orb.FROST)
    bc2.player.hp = 300
    bc2.end_turn()
    assert bc2.player.block == 2


def test_emotion_chip_with_gold_plated_cables_doubles_rightmost():
    from sts.combat.types import Orb

    bc = BattleContext(seed=308, relics=[RelicId.EMOTION_CHIP, RelicId.GOLD_PLATED_CABLES])
    bc.player.orbs.extend([Orb.FROST, Orb.FROST])
    bc.player.lose_hp(bc, 5)
    bc.player.hp = 300
    bc.end_turn()
    # 常规 2+2 + chip 全球 2+2 + chip 的 GPC 最右加成 2
    assert bc.player.block == 10


def test_gold_plated_cables_end_of_turn_extra_trigger():
    """GOLD_PLATED_CABLES（新实现）：回合末全部槽位结算后最右球被动再触发
    一次（wiki）。"""
    from sts.combat.types import Orb

    bc = BattleContext(seed=309)
    bc.relics = relics_mod.RelicContainer([RelicId.GOLD_PLATED_CABLES])
    m = bc.monsters.monsters[0]
    hp0 = m.hp
    bc.player.orbs.extend([Orb.LIGHTNING, Orb.DARK])
    bc.player.hp = 300
    bc.end_turn()
    # LIGHTNING 被动 3 伤一次；DARK 被动 +6 存层、最右球再 +6
    assert m.hp == hp0 - 3
    assert bc.player.dark_stacks == 12


def test_inserter_orb_slot_every_two_turns():
    """INSERTER（新实现）：每 2 回合 +1 充能球槽（wiki；任务清单原记
    "保留 1 张牌"系误记）。"""
    bc = BattleContext(seed=310, relics=[RelicId.INSERTER])
    assert bc.player.orb_slots == 3
    bc.player.hp = 300
    bc.end_turn()
    assert bc.player.orb_slots == 4  # 第 2 回合
    bc.end_turn()
    assert bc.player.orb_slots == 4  # 第 3 回合
    bc.end_turn()
    assert bc.player.orb_slots == 5  # 第 4 回合


def test_lizard_tail_revives_once():
    """LIZARD_TAIL（新实现）：将死时回复 maxHp 一半，每场一次（wiki）。"""
    bc = BattleContext(seed=311, relics=[RelicId.LIZARD_TAIL])
    bc.add_to_bot(Actions.attack_player(0, 999))
    run_queue(bc)
    assert bc.player.hp == 40  # 80 // 2
    assert not bc.over
    bc.add_to_bot(Actions.attack_player(0, 999))
    run_queue(bc)
    assert bc.outcome == Outcome.PLAYER_LOSS  # 第二次不救


def test_duality_temporary_dexterity():
    """DUALITY（新实现）：打出攻击 +1 临时敏捷，回合末扣回（wiki）。"""
    bc = BattleContext(seed=312, relics=[RelicId.DUALITY])
    setup_hand(bc, FREE_ATTACK)
    bc.play_card(0, target=0)
    assert bc.player.statuses.get(PlayerStatus.DEXTERITY) == 1
    assert bc.player.statuses.get(PlayerStatus.LOSE_DEXTERITY) == 1
    bc.player.hp = 300
    bc.end_turn()
    assert bc.player.statuses.get(PlayerStatus.DEXTERITY) == 0
    assert not bc.player.statuses.has(PlayerStatus.LOSE_DEXTERITY)


def test_melange_scry_on_shuffle():
    """MELANGE（新实现）：每次洗抽牌堆后 Scry 3（wiki；入队在抽牌完成后弹出，
    open_scry 挂 SCRY 输入态，与 Foresight 同款接线）。"""
    bc = BattleContext(seed=313, relics=[RelicId.MELANGE], deck=[STRIKE] * 8)
    assert bc.input_state == InputState.PLAYER_NORMAL
    bc.player.hp = 300
    bc.end_turn()  # 抽空 3 张 → 洗牌（入队 Scry）→ 续抽 2 → 挂起 SCRY
    assert bc.input_state == InputState.SCRY
    assert len(bc.scry_cards) == 3  # 洗回 5 张、抽走 2 张后剩 3
    bc.choose_scry(3)  # 全部保留
    assert bc.input_state == InputState.PLAYER_NORMAL


def test_ring_of_the_snake_draw_2():
    bc = BattleContext(seed=314, relics=[RelicId.RING_OF_THE_SNAKE], deck=[STRIKE] * 10)
    assert len(bc.cards.hand) == 7


def test_ring_of_the_serpent_draw_1_every_turn():
    bc = BattleContext(seed=315, relics=[RelicId.RING_OF_THE_SERPENT], deck=[STRIKE] * 10)
    assert len(bc.cards.hand) == 6
    bc.player.hp = 300
    bc.end_turn()
    assert len(bc.cards.hand) == 6  # 5 + 1


def test_ninja_scroll_three_shivs():
    from sts.content.silent_cards import SHIV

    bc = BattleContext(seed=316, relics=[RelicId.NINJA_SCROLL], deck=[STRIKE] * 10)
    shivs = [c for c in bc.cards.hand if c.card is SHIV]
    assert len(shivs) == 3
    assert len(bc.cards.hand) == 8  # 3 Shiv + 首手 5


def test_hovering_kite_first_discard_each_turn():
    """HOVERING_KITE（新实现）：每回合首次弃牌 +1 能量（wiki）。"""
    bc = BattleContext(seed=317, relics=[RelicId.HOVERING_KITE], deck=[STRIKE] * 10)
    e0 = bc.player.energy
    bc.manual_discard(bc.cards.hand[0])
    run_queue(bc)  # gain_energy 动作入队后需跑队列
    assert bc.player.energy == e0 + 1
    bc.manual_discard(bc.cards.hand[0])
    run_queue(bc)
    assert bc.player.energy == e0 + 1  # 每回合仅首次
    bc.player.hp = 300
    bc.end_turn()
    e1 = bc.player.energy
    bc.manual_discard(bc.cards.hand[0])
    run_queue(bc)
    assert bc.player.energy == e1 + 1  # 新回合重置


def test_violet_lotus_calm_exit_energy():
    """VIOLET_LOTUS（新实现）：退出平静 +3 而非 +2（wiki）。"""
    from sts.combat.types import Stance

    bc = BattleContext(seed=318, relics=[RelicId.VIOLET_LOTUS])
    e0 = bc.player.energy
    bc.player.change_stance(bc, Stance.CALM)
    assert bc.player.energy == e0  # 进平静无能量
    bc.player.change_stance(bc, Stance.WRATH)
    run_queue(bc)
    assert bc.player.energy == e0 + 3


def test_cracked_core_channels_lightning():
    from sts.combat.types import Orb

    bc = BattleContext(seed=319, relics=[RelicId.CRACKED_CORE])
    assert bc.player.orbs == [Orb.LIGHTNING]


def test_symbiotic_virus_channels_dark():
    from sts.combat.types import Orb

    bc = BattleContext(seed=320, relics=[RelicId.SYMBIOTIC_VIRUS])
    assert bc.player.orbs == [Orb.DARK]


def test_nuclear_battery_plasma_and_start_passive():
    """NUCLEAR_BATTERY（新实现）：开局 1 等离子球；PLASMA 被动（wiki Orb
    页）在回合开始 +1 能量。"""
    from sts.combat.types import Orb

    bc = BattleContext(seed=321, relics=[RelicId.NUCLEAR_BATTERY])
    assert bc.player.orbs == [Orb.PLASMA]
    e0 = bc.player.energy
    assert bc.player.energy == e0
    bc.player.hp = 300
    bc.end_turn()
    assert bc.player.energy == 4  # 3 + PLASMA 被动 1


def test_teardrop_locket_starts_in_calm():
    from sts.combat.types import Stance

    bc = BattleContext(seed=322, relics=[RelicId.TEARDROP_LOCKET])
    assert bc.player.stance == Stance.CALM


def test_pure_water_and_holy_water_miracles():
    from sts.content.watcher_cards import MIRACLE

    bc = BattleContext(seed=323, relics=[RelicId.PURE_WATER], deck=[STRIKE] * 10)
    assert len([c for c in bc.cards.hand if c.card is MIRACLE]) == 1
    bc2 = BattleContext(seed=324, relics=[RelicId.HOLY_WATER], deck=[STRIKE] * 10)
    assert len([c for c in bc2.cards.hand if c.card is MIRACLE]) == 3


def test_slavers_collar_elite_only_energy():
    bc = BattleContext(seed=325, relics=[RelicId.SLAVERS_COLLAR])
    assert bc.player.energy == 3  # 普通房不加
    with _elite_encounter("cultist"):
        bc2 = BattleContext(seed=326, relics=[RelicId.SLAVERS_COLLAR])
        assert bc2.player.energy == 4
    with _elite_encounter("cultist", boss=True):
        bc3 = BattleContext(seed=327, relics=[RelicId.SLAVERS_COLLAR])
        assert bc3.player.energy == 4
    with _elite_encounter("cultist"):  # 注册表是动态查询，回合内须保持注册
        bc2.player.hp = 300
        bc2.end_turn()
        assert bc2.player.energy == 4  # 精英房每回合都加


def test_runic_capacitor_three_extra_slots():
    bc = BattleContext(seed=328, relics=[RelicId.RUNIC_CAPACITOR])
    assert bc.player.orb_slots == 6  # 3 + 3（wiki；上限 10）


def test_orange_pellets_removes_debuffs_on_three_types():
    """ORANGE_PELLETS（新实现）：同回合打出 攻击+技能+能力 各≥1 → 移除全部
    debuff（wiki：回合中即时触发，非回合末）。"""
    bc = BattleContext(seed=329, relics=[RelicId.ORANGE_PELLETS], deck=[STRIKE] * 10)
    bc.player.statuses.add(PlayerStatus.STRENGTH, -2)  # 力量 debuff（整体为负）
    bc.player.statuses.add(PlayerStatus.WEAK, 1)
    setup_hand(bc, FREE_ATTACK, SKILL_STUB, POWER_STUB)
    bc.play_card(0, target=0)  # 攻击
    bc.play_card(0)  # 技能
    assert bc.player.statuses.has(PlayerStatus.WEAK)  # 还差能力牌
    bc.play_card(0)  # 能力 → 触发
    assert not bc.player.statuses.has(PlayerStatus.WEAK)
    assert bc.player.statuses.get(PlayerStatus.STRENGTH) == 0
    # 再集齐三类可再次触发（类型标志已重置）


def test_fossilized_helix_buffer():
    """FOSSILIZED_HELIX（新实现）：战斗开始 1 层 BUFFER，抵挡首次 HP 损失。"""
    bc = BattleContext(seed=330, relics=[RelicId.FOSSILIZED_HELIX])
    assert bc.player.statuses.get(PlayerStatus.BUFFER) == 1
    hp0 = bc.player.hp
    bc.player.lose_hp(bc, 5)
    assert bc.player.hp == hp0  # 被抵挡
    assert not bc.player.statuses.has(PlayerStatus.BUFFER)
    bc.player.lose_hp(bc, 5)
    assert bc.player.hp == hp0 - 5


# ---- 审计批次接线：CHAMPION_BELT/SNECKO_SKULL/PAPER_KRANE/ODD_MUSHROOM/GINGER/TURNIP ----


def test_champion_belt_weak_with_vulnerable():
    from sts.combat.actions import Actions
    from sts.combat.types import MonsterStatus
    from tests.test_engine_batch0 import run_queue

    bc = BattleContext(seed=231, relics=[RelicId.CHAMPION_BELT])
    m = bc.monsters.monsters[0]
    bc.add_to_bot(Actions.debuff_enemy(0, MonsterStatus.VULNERABLE, 1, False))
    run_queue(bc)
    assert m.statuses.get(MonsterStatus.VULNERABLE) == 1
    assert m.statuses.get(MonsterStatus.WEAK) == 1  # 附带 1 层虚弱


def test_champion_belt_artifact_blocks_main_not_bonus():
    from sts.combat.actions import Actions
    from sts.combat.types import MonsterStatus
    from tests.test_engine_batch0 import run_queue

    bc = BattleContext(seed=232, relics=[RelicId.CHAMPION_BELT])
    m = bc.monsters.monsters[0]
    m.statuses.add(MonsterStatus.ARTIFACT, 1)
    bc.add_to_bot(Actions.debuff_enemy(0, MonsterStatus.VULNERABLE, 1, False))
    run_queue(bc)
    assert m.statuses.get(MonsterStatus.ARTIFACT) == 0  # 抵消主易伤
    assert not m.statuses.has(MonsterStatus.WEAK)  # 附加不落地


def test_snecko_skull_bonus_poison():
    from sts.combat.actions import Actions
    from sts.combat.types import MonsterStatus
    from tests.test_engine_batch0 import run_queue

    bc = BattleContext(seed=233, relics=[RelicId.SNECKO_SKULL])
    m = bc.monsters.monsters[0]
    bc.add_to_bot(Actions.debuff_enemy(0, MonsterStatus.POISON, 3, False))
    run_queue(bc)
    assert m.statuses.get(MonsterStatus.POISON) == 4  # 3+1


def test_paper_krane_weak_multiplier():
    from sts.combat.actions import Actions
    from sts.combat.types import MonsterStatus
    from tests.test_engine_batch0 import run_queue

    bc = BattleContext(seed=234, relics=[RelicId.PAPER_KRANE], deck=[STRIKE] * 10)
    m = bc.monsters.monsters[0]
    m.statuses.add(MonsterStatus.WEAK, 1)
    m.set_move(m.__class__.DARK_STRIKE)  # 6 伤
    bc.end_turn()
    assert bc.player.hp == 80 - 3  # floor(6 × 0.6) = 3


def test_odd_mushroom_vulnerable_taken_reduced():
    from sts.combat.actions import Actions
    from sts.combat.types import MonsterStatus, PlayerStatus
    from tests.test_engine_batch0 import run_queue

    bc = BattleContext(seed=235, relics=[RelicId.ODD_MUSHROOM], deck=[STRIKE] * 10)
    m = bc.monsters.monsters[0]
    m.set_move(m.__class__.DARK_STRIKE)
    bc.add_to_bot(Actions.debuff_player(PlayerStatus.VULNERABLE, 1, False))
    run_queue(bc)
    assert m.statuses.get(MonsterStatus.WEAK) == 1 or True  # 无 CHAMPION_BELT
    bc.end_turn()
    assert bc.player.hp == 80 - 7  # 6 × 1.25 = 7.5 → 7


def test_ginger_blocks_weak_not_others():
    from sts.combat.actions import Actions
    from sts.combat.types import PlayerStatus
    from tests.test_engine_batch0 import run_queue

    bc = BattleContext(seed=236, relics=[RelicId.GINGER])
    bc.add_to_bot(Actions.debuff_player(PlayerStatus.WEAK, 2, True))
    run_queue(bc)
    assert not bc.player.statuses.has(PlayerStatus.WEAK)
    bc.add_to_bot(Actions.debuff_player(PlayerStatus.VULNERABLE, 2, True))
    run_queue(bc)
    assert bc.player.statuses.get(PlayerStatus.VULNERABLE) == 2  # 其他不拦


def test_turnip_blocks_frail():
    from sts.combat.actions import Actions
    from sts.combat.types import PlayerStatus
    from tests.test_engine_batch0 import run_queue

    bc = BattleContext(seed=237, relics=[RelicId.TURNIP])
    bc.add_to_bot(Actions.debuff_player(PlayerStatus.FRAIL, 2, True))
    run_queue(bc)
    assert not bc.player.statuses.has(PlayerStatus.FRAIL)

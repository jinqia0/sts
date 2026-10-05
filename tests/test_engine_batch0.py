"""批次 0 引擎能力测试：X 费 / 选卡 / 虚无 / 固有 / 自动结算诅咒 / 触发钩子 /
逃跑与生成 / 偷金 / 缠绕 / 格挡与能量管线 / 遗物框架。

全部用"无来源状态"门控设计：不设状态/不挂遗物时引擎行为与既有 103 用例
完全一致（由既有测试守护）；本文件只验证新能力本身。测试卡用局部 CardDef
桩（对齐 test_cards.py 的 instantiate 模式）。
"""

from sts.combat import BattleContext
from sts.combat.actions import Actions
from sts.combat.card_manager import CardInstance
from sts.combat.queue import CardQueueItem
from sts.combat.relics import RelicId
from sts.combat.types import InputState, MonsterStatus, Outcome, PlayerStatus
from sts.content.cards import DEFEND, STRIKE, CardDef
from sts.content.monsters import AcidSlimeS, Cultist, JawWorm

# ---- 测试桩卡 ----


def _x_play(bc, item) -> None:
    """X 费桩：每 1 点能量入队 3 伤攻击（读取 energy_on_use 快照）。"""
    n = max(item.energy_on_use, 0)
    for _ in range(n):
        bc.add_to_bot(Actions.attack_enemy(item.target, 3))


X_TEST = CardDef("X Test", "X费桩", -1, "Attack", "X 费：每点能量 3 伤。", True, False, _x_play, x_cost=True)


def _select_play(bc, item) -> None:
    """选卡桩：从手中其余牌里选 1 张，放到抽牌堆顶。"""
    cands = [c for c in bc.cards.hand if c is not item.card]

    def on_choose(bc2, chosen):
        for inst in chosen:
            bc2.cards.hand.remove(inst)
            bc2.cards.append_to_draw_top(inst)

    bc.open_card_select(cands, on_choose, prompt="选 1 张放到抽牌堆顶")


SELECT_TEST = CardDef("Select Test", "选卡桩", 0, "Skill", "选 1 张手牌置顶。", False, False, _select_play)

SELECT_EXHAUST = CardDef("Select Exhaust", "多选消耗桩", 0, "Skill", "消耗全部其他手牌。", False, False,
                         _select_play)  # 复用选卡效果


def _burn_effect(bc, item) -> None:
    up = item.card is not None and item.card.upgraded
    bc.add_to_bot(Actions.damage_player(4 if up else 2))


BURN_TEST = CardDef("Burn Test", "灼伤桩", 0, "Status", "回合末受 2 伤。", False, False, None,
                    unplayable=True, no_trigger_effect=_burn_effect)

ETHEREAL_TEST = CardDef("Ethereal Test", "虚无桩", 0, "Skill", "虚无。回合末在手则消耗。", False, False,
                        lambda bc, item: None, ethereal=True)


def _noop_play(bc, item) -> None:
    pass


EXHAUSTING_TEST = CardDef("Exhausting Test", "消耗桩", 0, "Skill", "消耗。", False, True, _noop_play)
PAIN_TEST = CardDef("Pain Test", "痛苦桩", 0, "Curse", "打出其他牌时失去 1 HP。", False, False, None,
                    unplayable=True, on_play_other_lose_hp=1)
VOID_TEST = CardDef("Void Test", "虚空桩", 0, "Status", "虚无。抽到时失去 1 能量。", False, False, None,
                    unplayable=True, ethereal=True, lose_energy_when_drawn=1)


def _whirlwind_like(bc, item) -> None:
    bc.add_to_bot(Actions.gain_block(1))


SNECKO_FREE = CardDef("Free Cost", "零费桩", 0, "Attack", "0 费攻击。", True, False,
                      lambda bc, item: bc.add_to_bot(
                          Actions.attack_enemy(item.target, bc.calculate_card_damage(item, item.target, 6))))


def setup_hand(bc: BattleContext, *cards) -> None:
    bc.cards.hand.clear()
    for c in cards:
        bc.cards.hand.append(bc.cards.instantiate(c))


def run_queue(bc: BattleContext) -> None:
    """把挂起队列跑到底（用于直接入队动作的测试）。"""
    if bc.input_state == InputState.PLAYER_NORMAL:
        bc.set_state(InputState.EXECUTING_ACTIONS)
    bc.execute_actions()


def add_cultist(bc: BattleContext, idx: int = 1, hp: int = 50) -> Cultist:
    m = Cultist(idx=idx, hp=hp, max_hp=hp)
    m.set_move(Cultist.INCANTATION)
    bc.monsters.add(m)
    return m


# ---- X 费 ----


def test_x_cost_consumes_all_energy_and_snapshots():
    bc = BattleContext(seed=101)
    setup_hand(bc, X_TEST, DEFEND)
    m = bc.monsters.monsters[0]
    hp0 = m.hp
    assert bc.player.energy == 3
    bc.play_card(0)
    assert bc.player.energy == 0
    assert m.hp == hp0 - 9  # 3 能量 × 3 伤


def test_x_cost_with_zero_energy():
    bc = BattleContext(seed=102)
    setup_hand(bc, X_TEST)
    bc.player.energy = 0
    m = bc.monsters.monsters[0]
    hp0 = m.hp
    bc.play_card(0)
    assert m.hp == hp0  # 0 能量 = 0 次（费用检查跳过，允许打出）


# ---- 选卡状态机 ----


def test_card_select_multi_candidate_suspends():
    bc = BattleContext(seed=103)
    setup_hand(bc, SELECT_TEST, STRIKE, STRIKE, DEFEND)
    top_id = bc.cards.draw_pile[-1].unique_id
    bc.play_card(0)
    assert bc.input_state == InputState.CARD_SELECT
    assert bc.card_select_info is not None and len(bc.card_select_info.candidates) == 3
    # 选择第 1 张（STRIKE）：移出手中、置抽牌堆顶（抽牌堆尾）
    chosen = bc.card_select_info.candidates[0]
    bc.choose_cards([0])
    assert bc.input_state == InputState.PLAYER_NORMAL
    assert chosen not in bc.cards.hand
    assert bc.cards.draw_pile[-1] is chosen
    assert bc.cards.draw_pile[-1].unique_id != top_id


def test_card_select_single_candidate_auto_executes():
    bc = BattleContext(seed=104)
    setup_hand(bc, SELECT_TEST, STRIKE)
    bc.play_card(0)
    # 候选恰好 1 张：直接执行，不进入选卡状态
    assert bc.input_state == InputState.PLAYER_NORMAL
    assert bc.cards.hand == []  # STRIKE 已被选走置顶
    assert bc.cards.draw_pile[-1].card is STRIKE


def test_card_select_empty_candidates_skips():
    bc = BattleContext(seed=105)
    setup_hand(bc, SELECT_TEST)
    bc.play_card(0)
    assert bc.input_state == InputState.PLAYER_NORMAL  # 空候选：效果跳过


def test_card_select_cannot_pick_zero_when_required():
    bc = BattleContext(seed=106)
    setup_hand(bc, SELECT_TEST, STRIKE, STRIKE)
    bc.play_card(0)
    try:
        bc.choose_cards([])
        assert False, "应拒绝空选"
    except ValueError:
        assert bc.input_state == InputState.CARD_SELECT  # 挂起状态保持
    bc.choose_cards([0])
    assert bc.input_state == InputState.PLAYER_NORMAL


def test_card_select_play_during_select_rejected():
    bc = BattleContext(seed=107)
    setup_hand(bc, SELECT_TEST, STRIKE, STRIKE)
    bc.play_card(0)
    try:
        bc.play_card(0)
        assert False, "选卡阶段不可出牌"
    except ValueError:
        pass


# ---- 虚无 / 固有 / 自动结算 ----


def test_ethereal_exhausts_at_end_of_turn():
    bc = BattleContext(seed=108)
    setup_hand(bc, DEFEND, ETHEREAL_TEST)
    bc.end_turn()
    # 敌方回合结束后回到玩家回合：虚无牌已消耗
    assert all(c.card is not ETHEREAL_TEST for c in bc.cards.hand)
    assert any(c.card is ETHEREAL_TEST for c in bc.cards.exhaust_pile)
    assert not any(c.card is ETHEREAL_TEST for c in bc.cards.discard_pile)


def test_ethereal_not_in_hand_stays_in_discard():
    bc = BattleContext(seed=109)
    # 打出虚无牌（效果为空）→ 直接进弃牌堆；回合末不在手，不消耗
    setup_hand(bc, ETHEREAL_TEST)
    bc.play_card(0)
    assert any(c.card is ETHEREAL_TEST for c in bc.cards.discard_pile)
    bc.end_turn()
    assert any(c.card is ETHEREAL_TEST for c in bc.cards.discard_pile)
    assert not any(c.card is ETHEREAL_TEST for c in bc.cards.exhaust_pile)


def test_innate_card_starts_in_hand():
    innate = CardDef("Innate Test", "固有桩", 0, "Skill", "固有。", False, False, _noop_play, innate=True)
    bc = BattleContext(seed=110, deck=[STRIKE] * 4 + [DEFEND] * 4 + [innate])
    names = [c.card.name for c in bc.cards.hand]
    assert "Innate Test" in names


def test_no_trigger_card_resolves_at_end_of_turn():
    bc = BattleContext(seed=111)
    bc.player.hp = 80
    setup_hand(bc, DEFEND, BURN_TEST)
    burn = bc.cards.hand[1]
    bc.end_turn()
    # Burn 走 DamagePlayer：2 点伤害被格挡吸收（Defend 未打出在手里，格挡 0）→ HP -2
    assert bc.player.hp == 80 - 2
    # Burn 结算后进弃牌堆
    assert burn in bc.cards.discard_pile


# ---- 诅咒 Pain / Void ----


def test_curse_pain_drains_hp_when_playing_other_cards():
    bc = BattleContext(seed=112)
    setup_hand(bc, STRIKE, PAIN_TEST)
    hp0 = bc.player.hp
    bc.play_card(0)
    assert bc.player.hp == hp0 - 1
    # 两张 Pain 叠加
    setup_hand(bc, STRIKE, PAIN_TEST, PAIN_TEST)
    bc.player.hp = 80
    bc.play_card(0)
    assert bc.player.hp == 80 - 2


def test_void_loses_energy_when_drawn():
    bc = BattleContext(seed=113)
    # 抽牌堆顶塞 Void（抽牌从尾弹出）
    bc.cards.draw_pile.append(bc.cards.instantiate(VOID_TEST))
    energy0 = bc.player.energy
    run_queue(bc)
    bc.add_to_bot(Actions.draw_cards(1))
    run_queue(bc)
    assert bc.player.energy == energy0 - 1
    assert any(c.card is VOID_TEST for c in bc.cards.hand)


# ---- 缠绕 / 壁垒 / 格挡钩子 ----


def test_entangled_blocks_attacks_only_and_clears_at_end_of_turn():
    bc = BattleContext(seed=114)
    setup_hand(bc, STRIKE, DEFEND)
    bc.player.statuses.add(PlayerStatus.ENTANGLED, 1)
    try:
        bc.play_card(0)
        assert False, "缠绕中不可打出攻击牌"
    except ValueError:
        pass
    # 技能牌不受缠绕限制（对齐本体：Entangle 只拦攻击）
    bc.play_card(1)  # DEFEND
    assert bc.player.block == 5
    bc.end_turn()
    assert not bc.player.statuses.has(PlayerStatus.ENTANGLED)
    # 下回合可正常出攻击牌
    setup_hand(bc, STRIKE)
    bc.play_card(0)
    assert not bc.player.statuses.has(PlayerStatus.ENTANGLED)


def test_barricade_keeps_block():
    bc = BattleContext(seed=115)
    bc.player.statuses.add(PlayerStatus.BARRICADE, 1)
    setup_hand(bc, DEFEND)
    bc.play_card(0)
    assert bc.player.block == 5
    bc.end_turn()
    # 敌方回合结束、新回合开始：BARRICADE 保留格挡
    assert bc.player.block == 5


def test_juggernaut_triggers_on_block_gain():
    bc = BattleContext(seed=116)
    bc.player.statuses.add(PlayerStatus.JUGGERNAUT, 1)
    setup_hand(bc, DEFEND)
    m = bc.monsters.monsters[0]
    hp0 = m.hp
    bc.play_card(0)
    assert bc.player.block == 5
    assert m.hp == hp0 - 5  # 随机敌人（仅 1 只）吃 5 伤


def test_juggernaut_stacks():
    bc = BattleContext(seed=117)
    bc.player.statuses.add(PlayerStatus.JUGGERNAUT, 2)
    setup_hand(bc, DEFEND)
    m = bc.monsters.monsters[0]
    hp0 = m.hp
    bc.play_card(0)
    assert m.hp == hp0 - 10  # 2 层 × 5


def test_no_block_gates_juggernaut():
    """NO_BLOCK：格挡归零且不触发 Juggernaut（"获得格挡"本身被拦截）；回合末衰减。"""
    bc = BattleContext(seed=117)
    bc.player.statuses.add(PlayerStatus.JUGGERNAUT, 1)
    bc.player.statuses.add(PlayerStatus.NO_BLOCK, 1)
    setup_hand(bc, DEFEND)
    m = bc.monsters.monsters[0]
    hp0 = m.hp
    bc.play_card(0)
    assert bc.player.block == 0
    assert m.hp == hp0
    bc.end_turn()
    assert not bc.player.statuses.has(PlayerStatus.NO_BLOCK)


# ---- 自伤 / 反伤 / 无实体 ----


def test_rupture_triggers_on_self_damage_only():
    bc = BattleContext(seed=118)
    bc.player.statuses.add(PlayerStatus.RUPTURE, 1)
    bc.add_to_bot(Actions.player_lose_hp(2, self_inflicted=True))
    run_queue(bc)
    assert bc.player.statuses.get(PlayerStatus.STRENGTH) == 1
    # 非自伤（怪物攻击）不触发：受 2 点非自伤 HP 损失
    bc.add_to_bot(Actions.player_lose_hp(2))
    run_queue(bc)
    assert bc.player.statuses.get(PlayerStatus.STRENGTH) == 1


def test_flame_barrier_and_thorns_reflect():
    bc = BattleContext(seed=119)
    bc.player.statuses.add(PlayerStatus.FLAME_BARRIER, 4)
    bc.player.statuses.add(PlayerStatus.THORNS, 1)
    m = bc.monsters.monsters[0]
    hp0 = m.hp
    bc.add_to_bot(Actions.attack_player(0, 3))
    run_queue(bc)
    assert m.hp == hp0 - 4 - 1  # 火焰屏障 4 + 反伤 1
    # 回合开始火焰屏障清除（"this turn"），THORNS 保留
    bc.end_turn()
    assert not bc.player.statuses.has(PlayerStatus.FLAME_BARRIER)
    assert bc.player.statuses.has(PlayerStatus.THORNS)


def test_intangible_reduces_damage_to_one():
    bc = BattleContext(seed=120)
    bc.player.statuses.add(PlayerStatus.INTANGIBLE, 1)
    bc.add_to_bot(Actions.attack_player(0, 12))
    run_queue(bc)
    assert bc.player.hp == 80 - 1
    # 回合末衰减（无 just_applied → 递减移除）
    bc.end_turn()
    assert not bc.player.statuses.has(PlayerStatus.INTANGIBLE)


# ---- 抽牌触发 / 消耗触发 ----


def test_evolve_and_fire_breathing_on_status_draw():
    bc = BattleContext(seed=121)
    bc.player.statuses.add(PlayerStatus.EVOLVE, 1)
    bc.player.statuses.add(PlayerStatus.FIRE_BREATHING, 1)
    # 抽牌堆顶塞状态卡：抽到它 → Evolve 补抽 1 张普通牌 + 火息 4 伤全体
    bc.cards.hand.clear()  # 清初始手牌，只观察本次抽牌
    bc.cards.draw_pile.append(bc.cards.instantiate(BURN_TEST))
    m = bc.monsters.monsters[0]
    hp0 = m.hp
    bc.add_to_bot(Actions.draw_cards(1))
    run_queue(bc)
    assert len(bc.cards.hand) == 2  # 状态卡 + Evolve 补抽的普通牌
    assert any(c.card is BURN_TEST for c in bc.cards.hand)
    assert m.hp == hp0 - 4


def test_feel_no_pain_and_dark_embrace_on_exhaust():
    bc = BattleContext(seed=122)
    bc.player.statuses.add(PlayerStatus.FEEL_NO_PAIN, 1)
    bc.player.statuses.add(PlayerStatus.DARK_EMBRACE, 1)
    setup_hand(bc, EXHAUSTING_TEST)
    hand_len = len(bc.cards.hand)  # 0（刚 setup 后只剩消耗桩——打出后手牌空）
    m = bc.monsters.monsters[0]
    bc.play_card(0)
    assert bc.player.block == 3  # Feel No Pain
    # Dark Embrace 抽 1
    assert len(bc.cards.hand) == 1


def test_double_tap_replays_next_attack():
    bc = BattleContext(seed=123)
    bc.player.statuses.add(PlayerStatus.DOUBLE_TAP, 1)
    setup_hand(bc, STRIKE, STRIKE)
    m = bc.monsters.monsters[0]
    hp0 = m.hp
    bc.play_card(0)
    assert m.hp == hp0 - 12  # 6 × 2
    assert not bc.player.statuses.has(PlayerStatus.DOUBLE_TAP)
    # 只触发一次：第二张 Strike 正常
    hp1 = m.hp
    bc.play_card(0)
    assert m.hp == hp1 - 6
    # 原牌进弃牌堆一次、重放体 purge 不重复入堆
    assert sum(1 for c in bc.cards.discard_pile if c.card is STRIKE) == 2


# ---- 回合钩子：Demon Form / Brutality / Combust / The Bomb ----


def test_demon_form_post_draw():
    bc = BattleContext(seed=124)
    bc.player.statuses.add(PlayerStatus.DEMON_FORM, 2)
    bc.end_turn()
    assert bc.player.statuses.get(PlayerStatus.STRENGTH) == 2
    bc.end_turn()
    assert bc.player.statuses.get(PlayerStatus.STRENGTH) == 4


def test_brutality_post_draw():
    bc = BattleContext(seed=125)
    bc.player.statuses.add(PlayerStatus.BRUTALITY, 1)
    bc.end_turn()
    assert bc.player.hp == 80 - 1
    assert len(bc.cards.hand) == 6  # 正常 5 抽 + Brutality 额外 1


def test_combust_end_of_turn():
    bc = BattleContext(seed=126)
    bc.player.statuses.add(PlayerStatus.COMBUST, 1)
    m = bc.monsters.monsters[0]
    hp0 = m.hp
    bc.end_turn()
    assert bc.player.hp == 80 - 1
    assert m.hp == hp0 - 5


def test_the_bomb_three_turn_countdown():
    bc = BattleContext(seed=127)
    bc.player.special["the_bomb"] = 40
    bc.player.statuses.add(PlayerStatus.THE_BOMB, 3)
    m = bc.monsters.monsters[0]
    hp0 = m.hp
    bc.end_turn()  # 第 1 回合末：3 → 2
    assert m.hp == hp0
    assert bc.player.statuses.get(PlayerStatus.THE_BOMB) == 2
    bc.end_turn()  # 2 → 1
    assert m.hp == hp0
    bc.end_turn()  # 1 → 0：爆发
    assert m.hp == hp0 - 40
    assert not bc.player.statuses.has(PlayerStatus.THE_BOMB)


# ---- 怪物：逃跑 / 生成 / 偷金 / 中毒 ----


def test_monster_escape_yields_victory_when_alone():
    bc = BattleContext(seed=128)
    m = bc.monsters.monsters[0]
    m.escape(bc)
    assert m.is_dead_or_escaped()
    assert not m.is_targetable()
    assert bc.outcome == Outcome.PLAYER_VICTORY
    assert bc.is_battle_over


def test_escape_action_and_targetability():
    bc = BattleContext(seed=129)
    m2 = add_cultist(bc, idx=1, hp=50)
    m1 = bc.monsters.monsters[0]
    m1.escape(bc)
    assert bc.outcome == Outcome.UNDECIDED  # 还剩 1 只
    # 目标校验拒绝逃跑怪
    setup_hand(bc, STRIKE)
    try:
        bc.play_card(0, target=0)
        assert False
    except ValueError:
        pass
    # 剩余怪物仍可正常指定
    bc.play_card(0, target=1)


def test_spawn_replace_and_insert():
    bc = BattleContext(seed=130)
    m2 = add_cultist(bc, idx=1, hp=50)
    # 杀掉槽 1，原位替换为酸液史莱姆（分裂语义）
    m2.statuses.set(MonsterStatus.THIEVERY, 0)
    m2.hp = 0
    m2.die(bc)
    assert bc.monsters.alive_count == 1
    slime = AcidSlimeS.create(bc, idx=1)
    bc.monsters.spawn_replace(bc, 1, slime)
    assert bc.monsters.alive_count == 2
    assert slime.idx == 1
    # 前插一只到槽 1：原槽 1 后移为槽 2
    slime2 = AcidSlimeS.create(bc, idx=1)
    bc.monsters.spawn_insert(bc, 1, slime2)
    assert slime2.idx == 1 and slime.idx == 2
    assert [mm.idx for mm in bc.monsters.monsters] == [0, 1, 2]


def test_thievery_gold_returned_on_death():
    bc = BattleContext(seed=131)
    gold0 = bc.player.gold
    m = bc.monsters.monsters[0]
    m.statuses.add(MonsterStatus.THIEVERY, 1)
    m.misc_info = 15
    bc.player.gold -= 15
    bc.monsters.alive_count += 1  # 防死亡判胜：临时多算一只（测试语义）
    m.hp = 0
    m.die(bc)
    assert bc.player.gold == gold0
    assert m.misc_info == 0


def test_poison_ticks_at_monster_turn_start():
    bc = BattleContext(seed=132)
    m = bc.monsters.monsters[0]
    m.statuses.add(MonsterStatus.POISON, 2)
    hp0 = m.hp
    bc.end_turn()
    # 怪物回合开始：中毒 -2 HP、层数 -1
    assert m.hp == hp0 - 2
    assert m.statuses.get(MonsterStatus.POISON) == 1


# ---- Corruption / deck override ----


def test_corruption_makes_skills_free_and_exhaust():
    bc = BattleContext(seed=133)
    bc.player.statuses.add(PlayerStatus.CORRUPTION, 1)
    setup_hand(bc, DEFEND)
    energy0 = bc.player.energy
    bc.play_card(0)
    assert bc.player.energy == energy0  # 技能 0 费
    assert any(c.card is DEFEND for c in bc.cards.exhaust_pile)
    assert not any(c.card is DEFEND for c in bc.cards.discard_pile)


def test_deck_override():
    bc = BattleContext(seed=134, deck=[STRIKE] * 10)
    # 抽牌堆只含 10 张 Strike：抽 5 后剩 5
    assert len(bc.cards.draw_pile) == 5
    assert all(c.card is STRIKE for c in bc.cards.draw_pile)
    assert all(c.card is STRIKE for c in bc.cards.hand)


# ---- 遗物框架 ----


def test_relic_vajra_anchor_blood_vial_lantern():
    bc = BattleContext(seed=135, relics=[RelicId.VAJRA, RelicId.ANCHOR, RelicId.LANTERN])
    assert bc.player.statuses.get(PlayerStatus.STRENGTH) == 1
    assert bc.player.block == 10
    assert bc.player.energy == 4  # 3 + LANTERN 1


def test_relic_blood_vial_heals():
    bc = BattleContext(seed=136, relics=[RelicId.BLOOD_VIAL])
    bc.player.hp = 70
    # 构造期已回满过——重新触发一次即时桶验证
    bc.relics.on_battle_start_immediate(bc)
    assert bc.player.hp == 72


def test_relic_bag_of_marbles_vulnerable_all():
    bc = BattleContext(seed=137, relics=[RelicId.BAG_OF_MARBLES])
    assert bc.monsters.monsters[0].statuses.has(MonsterStatus.VULNERABLE)


def test_relic_burning_blood_heals_on_victory():
    bc = BattleContext(seed=138, relics=[RelicId.BURNING_BLOOD])
    bc.player.hp = 40
    m = bc.monsters.monsters[0]
    m.hp = 1
    m.statuses.remove(MonsterStatus.RITUAL) if m.statuses.has(MonsterStatus.RITUAL) else None
    setup_hand(bc, STRIKE)
    bc.play_card(0)
    assert bc.outcome == Outcome.PLAYER_VICTORY
    assert bc.player.hp == 46


def test_relic_paper_phrog_vulnerable_multiplier():
    bc = BattleContext(seed=139, relics=[RelicId.PAPER_PHROG])
    m = bc.monsters.monsters[0]
    m.statuses.add(MonsterStatus.VULNERABLE, 1)
    setup_hand(bc, STRIKE)
    hp0 = m.hp
    bc.play_card(0)
    assert m.hp == hp0 - 10  # 6 × 1.75 = 10.5 → 10


def test_relic_strike_dummy_and_wrist_blade():
    bc = BattleContext(seed=140, relics=[RelicId.STRIKE_DUMMY, RelicId.WRIST_BLADE])
    m = bc.monsters.monsters[0]
    setup_hand(bc, STRIKE, SNECKO_FREE)
    hp0 = m.hp
    bc.play_card(0)  # Strike：6 + 3 = 9
    assert m.hp == hp0 - 9
    hp1 = m.hp
    bc.play_card(0)  # 0 费攻击：6 + 4 = 10
    assert m.hp == hp1 - 10


def test_relic_torii_and_tungsten_rod():
    bc = BattleContext(seed=141, relics=[RelicId.TORII, RelicId.TUNGSTEN_ROD])
    # Torii 先（≤5 → 1），Tungsten Rod 后（-1）：4 伤攻击 → 1 → 0（两遗物叠加，对齐 lightspeed 顺序）
    bc.add_to_bot(Actions.attack_player(0, 4))
    run_queue(bc)
    assert bc.player.hp == 80
    bc.player.hp = 80
    bc.add_to_bot(Actions.attack_player(0, 12))  # 12 > 5 不吃 Torii：12 - 1 = 11
    run_queue(bc)
    assert bc.player.hp == 80 - 11


def test_relic_the_boot_raises_small_unblocked_damage():
    bc = BattleContext(seed=142, relics=[RelicId.THE_BOOT])
    m = bc.monsters.monsters[0]
    m.block = 5
    setup_hand(bc, STRIKE)
    hp0 = m.hp
    bc.play_card(0)  # 6 伤：格挡吸 5，未格挡 1 → Boot 提到 5
    assert m.hp == hp0 - 5


def test_relic_gremlin_horn_on_monster_death():
    bc = BattleContext(seed=143, relics=[RelicId.GREMLIN_HORN])
    m2 = add_cultist(bc, idx=1, hp=1)
    setup_hand(bc, STRIKE)
    energy0 = bc.player.energy
    bc.play_card(0, target=1)  # 击杀槽 1：+1 能量 +1 抽
    assert bc.player.energy == energy0 - 1 + 1
    assert len(bc.cards.hand) == 1  # 打出的 1 张 + 遗物补抽的 1 张 = 1（净持平）


def test_relic_abacus_and_sundial_on_shuffle():
    bc = BattleContext(seed=144, relics=[RelicId.THE_ABACUS, RelicId.SUNDIAL])
    assert bc.player.block == 0
    bc.on_shuffle()
    run_queue(bc)  # 洗牌钩子入队的动作跑完
    assert bc.player.block == 6
    energy0 = bc.player.energy
    bc.on_shuffle()
    bc.on_shuffle()  # 第 3 次：+2 能量
    run_queue(bc)
    assert bc.player.energy == energy0 + 2


def test_relic_art_of_war_energy():
    bc = BattleContext(seed=145, relics=[RelicId.ART_OF_WAR])
    # 对齐 lightspeed：首回合不触发（applyStartOfTurnRelics 只在 afterMonsterTurns 调用）
    assert bc.player.energy == 3
    setup_hand(bc, STRIKE)
    bc.play_card(0)
    bc.end_turn()  # 回合 1 打了攻击牌 → 回合 2 不触发
    assert bc.player.energy == 3
    bc.end_turn()  # 回合 2 无攻击 → 回合 3 触发
    assert bc.player.energy == 4


def test_relic_ice_cream_keeps_leftover_energy():
    bc = BattleContext(seed=146, relics=[RelicId.ICE_CREAM])
    setup_hand(bc, DEFEND)
    bc.play_card(0)
    assert bc.player.energy == 2
    bc.end_turn()
    assert bc.player.energy == 3 + 2


def test_relic_velvet_choker_blocks_play_at_six_hand():
    """VELVET_CHOKER：每回合至多打 6 张牌（isCardPlayAllowed L709-712 按
    cardsPlayedThisTurn 计，非手牌数——批次 1 核对修正）。"""
    bc = BattleContext(seed=147, relics=[RelicId.VELVET_CHOKER])
    assert bc.player.energy == 4  # +1 能量
    setup_hand(bc, *(SNECKO_FREE,) * 7)  # 0 费攻击桩，绕开能量限制
    for _ in range(6):
        bc.play_card(0)
    assert bc.player.cards_played_this_turn == 6
    try:
        bc.play_card(0)
        assert False, "本回合已打 6 张应禁出"
    except ValueError:
        pass


def test_relic_orichalcum_not_triggered_with_block():
    """本回合已获得格挡 → 回合末不触发（BARRICADE 让格挡存活到回合末后可观察）。"""
    bc = BattleContext(seed=148, relics=[RelicId.ORICHALCUM])
    bc.player.statuses.add(PlayerStatus.BARRICADE, 1)
    setup_hand(bc, DEFEND)
    bc.play_card(0)
    assert bc.player.block == 5
    bc.end_turn()
    assert bc.player.block == 5  # 不加 6


def test_relic_orichalcum_triggers_with_zero_block():
    bc = BattleContext(seed=149, relics=[RelicId.ORICHALCUM])
    bc.player.statuses.add(PlayerStatus.BARRICADE, 1)  # 用 BARRICADE 保留观察
    bc.end_turn()
    assert bc.player.block == 6


def test_relic_strange_spoon_distribution():
    exhaust_count = 0
    for seed in range(40):
        bc = BattleContext(seed=seed, relics=[RelicId.STRANGE_SPOON])
        setup_hand(bc, EXHAUSTING_TEST)
        bc.play_card(0)
        if any(c.card is EXHAUSTING_TEST for c in bc.cards.exhaust_pile):
            exhaust_count += 1
    assert 8 < exhaust_count < 32  # 50% 左右，40 次抽样内两侧都出现


def test_relic_mutagenic_strength_temporary():
    """MUTAGENIC_STRENGTH：+3 力量，首回合末 -3（initRelics L288-291）。"""
    bc = BattleContext(seed=150, relics=[RelicId.MUTAGENIC_STRENGTH])
    assert bc.player.statuses.get(PlayerStatus.STRENGTH) == 3
    assert bc.player.statuses.get(PlayerStatus.LOSE_STRENGTH) == 3
    bc.end_turn()
    assert bc.player.statuses.get(PlayerStatus.STRENGTH) == 0  # 首回合末扣回


def test_relic_twisted_funnel_poison():
    bc = BattleContext(seed=151, relics=[RelicId.TWISTED_FUNNEL])
    m = bc.monsters.monsters[0]
    assert m.statuses.get(MonsterStatus.POISON) == 4


def test_relic_philosophers_stone_spawns_stronger():
    bc = BattleContext(seed=152, relics=[RelicId.PHILOSOPHERS_STONE])
    assert bc.player.energy == 4
    assert bc.monsters.monsters[0].statuses.get(MonsterStatus.STRENGTH) == 1
    # 战斗中新生怪也 +1 力量
    slime = AcidSlimeS.create(bc, idx=1)
    bc.monsters.spawn_insert(bc, 1, slime)
    assert slime.statuses.get(MonsterStatus.STRENGTH) == 1


# ---- 批次 2 引擎接线回归（DOUBLE_TAP decrement / 升级固有 / play_top_card 工厂）----


def test_double_tap_upgraded_replays_two_attacks():
    """Double Tap+（2 层）：连翻两张攻击牌；状态递减而非整除移除。"""
    from sts.content.cards import DOUBLE_TAP

    bc = BattleContext(seed=160)
    bc.player.statuses.add(PlayerStatus.DOUBLE_TAP, 2)
    setup_hand(bc, STRIKE, STRIKE)
    m = bc.monsters.monsters[0]
    hp0 = m.hp
    bc.play_card(0)
    assert m.hp == hp0 - 12
    assert bc.player.statuses.get(PlayerStatus.DOUBLE_TAP) == 1  # 递减非移除
    hp1 = m.hp
    bc.play_card(0)
    assert m.hp == hp1 - 12
    assert not bc.player.statuses.has(PlayerStatus.DOUBLE_TAP)


def test_innate_when_upgraded_starts_in_hand():
    from sts.content.cards import BRUTALITY

    plain = [STRIKE] * 4 + [DEFEND] * 4 + [BRUTALITY]
    upgraded = [STRIKE] * 4 + [DEFEND] * 4 + [BRUTALITY]
    bc = BattleContext(seed=161, deck=plain)
    assert not any(c.card is BRUTALITY and c.upgraded for c in bc.cards.hand), "未升级不应在手"
    bc2 = BattleContext(seed=161, deck=upgraded)
    inst = bc2.cards.instantiate(BRUTALITY)
    inst.upgraded = True
    bc2.cards.draw_pile.append(inst)  # 附加一张升级版
    # 重新构造触发固有置顶（简化：直接构造带升级实例的战斗）
    bc3 = BattleContext(seed=162, deck=[STRIKE] * 9)
    bc3.cards.draw_pile.clear()
    bc3.cards.hand.clear()
    for c in [STRIKE] * 4 + [DEFEND] * 4:
        bc3.cards.create_deck_card_in_draw_pile(c)
    u = bc3.cards.instantiate(BRUTALITY)
    u.upgraded = True
    bc3.cards.create_deck_card_in_draw_pile(BRUTALITY)
    bc3.cards.draw_pile[-1].upgraded = True
    bc3.rngs.shuffle.shuffle(bc3.cards.draw_pile)
    bc3.cards.move_innate_to_top()
    bc3.draw_cards(5)
    assert any(c.card is BRUTALITY and c.upgraded for c in bc3.cards.hand), "升级版 Brutality 应固有在手"


def test_play_top_card_factory_resolves_target_and_free():
    """引擎工厂版 PlayTopCard：随机目标 + 免费打出 + 可消耗（Havoc 语义）。"""
    bc = BattleContext(seed=163)
    m = bc.monsters.monsters[0]
    hp0 = m.hp
    energy0 = bc.player.energy
    bc.cards.hand.clear()
    bc.cards.draw_pile.append(bc.cards.instantiate(STRIKE))
    bc.add_to_bot(Actions.play_top_card(exhaust=True))
    run_queue(bc)
    assert m.hp < hp0  # 免费打出并造成伤害
    assert bc.player.energy == energy0
    assert any(c.card is STRIKE for c in bc.cards.exhaust_pile), "顶牌打完消耗"


def test_temp_card_in_hand_full_goes_to_discard():
    """临时牌满手进弃牌堆（对齐 moveToHandHelper else 分支）。"""
    from sts.content.cards import WOUND as W  # noqa: N813
    from sts.combat.actions import Actions as A  # noqa: N813

    bc = BattleContext(seed=170)
    setup_hand(bc, *[STRIKE] * 10)  # 满 10 张
    assert len(bc.cards.hand) == 10
    bc.add_to_bot(A.make_temp_card_in_hand(W))
    run_queue(bc)
    assert len(bc.cards.hand) == 10
    assert any(c.card is W for c in bc.cards.discard_pile)

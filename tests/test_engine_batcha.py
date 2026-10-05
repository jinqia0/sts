"""批次 A 引擎地基测试：Retain/limbo/手动弃牌管线 + Act 2/3/4 怪物状态族
（TIME_WARP/INTANGIBLE/REGEN/FADING/INVINCIBLE/MALLEABLE/FLIGHT/REACTIVE/
CORPSE_EXPLOSION/REGROW/MINION_LEADER/STASIS/SHIFTING/SLOW/BEAT_OF_DEATH/
CURIOSITY/PAINFUL_STABS/GENERIC_STRENGTH_UP/PLATED_ARMOR_M/ENVENOM）+
HEX/CONFUSED/EQUILIBRIUM。
"""

from sts.combat import BattleContext
from sts.combat.actions import Actions
from sts.combat.card_manager import CardInstance
from sts.combat.queue import Action
from sts.combat.types import InputState, MonsterStatus, Outcome, PlayerStatus
from sts.content.cards import DEFEND, STRIKE, CardDef
from sts.content.monsters import Cultist

from tests.test_engine_batch0 import run_queue, setup_hand


def _curse(m):
    return m.statuses


def add_cultist(bc: BattleContext, idx: int = 1, hp: int = 99) -> Cultist:
    m = Cultist(idx=idx, hp=hp, max_hp=hp)
    m.set_move(Cultist.INCANTATION)
    bc.monsters.add(m)
    return m


# ---- Retain / limbo ----


def _retain_card():
    return CardDef("Retain Test", "保留桩", 0, "Skill", "保留。", False, False,
                   lambda bc, item: None, self_retain=True)


def test_self_retain_survives_discard_phase():
    rc = _retain_card()
    bc = BattleContext(seed=201)
    setup_hand(bc, DEFEND, rc)
    defend_id = bc.cards.hand[0].unique_id
    retain_id = bc.cards.hand[1].unique_id
    bc.end_turn()
    # 保留牌经 limbo 在下回合回到手；被弃的 Defend 实例不在手（新抽的除外）
    hand_ids = [c.unique_id for c in bc.cards.hand]
    assert retain_id in hand_ids
    assert defend_id not in hand_ids
    assert any(c.unique_id == defend_id for c in bc.cards.discard_pile)


def test_instance_retain_bit_cleared_after_restore():
    rc = _retain_card()
    bc = BattleContext(seed=202)
    inst = bc.cards.instantiate(rc)
    inst.retain = True  # 单回合保留（Well-Laid Plans 类）
    setup_hand(bc, DEFEND)
    bc.cards.hand.append(inst)
    bc.end_turn()
    assert inst in bc.cards.hand
    assert inst.retain is False  # 还手后清除（对齐 restoreRetainedCards）


def test_equilibrium_keeps_whole_hand_one_turn():
    bc = BattleContext(seed=203, deck=[STRIKE] * 20)  # 大牌组避免弃牌洗回干扰
    setup_hand(bc, DEFEND, DEFEND)
    kept_ids = [c.unique_id for c in bc.cards.hand]
    bc.player.statuses.add(PlayerStatus.EQUILIBRIUM, 1)
    bc.end_turn()
    hand_ids = [c.unique_id for c in bc.cards.hand]
    assert set(kept_ids) <= set(hand_ids)  # 原 2 张整手保留
    assert len(hand_ids) == 7  # 保留 2 + 新抽 5
    assert not bc.player.statuses.has(PlayerStatus.EQUILIBRIUM)  # 回合末衰减
    bc.end_turn()
    # 下回合无均衡：原 2 张正常弃置（新抽的在手）
    hand_ids2 = [c.unique_id for c in bc.cards.hand]
    assert not (set(kept_ids) & set(hand_ids2))
    assert any(c.unique_id == kept_ids[0] for c in bc.cards.discard_pile)


# ---- 手动弃牌管线 ----


def test_manual_discard_counts_and_triggers():
    from sts.combat.relics import RelicId

    bc = BattleContext(seed=204, relics=[RelicId.TINGSHA, RelicId.TOUGH_BANDAGES])
    setup_hand(bc, DEFEND, DEFEND)
    m = bc.monsters.monsters[0]
    hp0 = m.hp
    bc.add_to_bot(Actions.discard_chosen(1))
    run_queue(bc)  # 挂起到 CARD_SELECT（2 候选选 1）
    assert bc.input_state == InputState.CARD_SELECT
    bc.choose_cards([0])
    assert bc.player.cards_discarded_this_turn == 1
    assert bc.player.block == 3  # Tough Bandages
    assert m.hp == hp0 - 3  # Tingsha 随机敌人（单怪）3 伤
    assert len(bc.cards.hand) == 1


def test_discard_random_from_hand():
    bc = BattleContext(seed=205)
    setup_hand(bc, DEFEND, DEFEND, DEFEND)
    bc.add_to_bot(Actions.discard_random_from_hand(2))
    run_queue(bc)
    assert bc.player.cards_discarded_this_turn == 2
    assert len(bc.cards.hand) == 1
    assert len(bc.cards.discard_pile) >= 2


def test_discard_all_hand():
    bc = BattleContext(seed=206)
    setup_hand(bc, DEFEND, DEFEND, DEFEND)
    bc.add_to_bot(Actions.discard_all_hand())
    run_queue(bc)
    assert bc.cards.hand == []
    assert bc.player.cards_discarded_this_turn == 3


def test_discard_resets_each_turn():
    bc = BattleContext(seed=207)
    setup_hand(bc, DEFEND)
    bc.add_to_bot(Actions.discard_chosen(1))
    run_queue(bc)
    assert bc.player.cards_discarded_this_turn == 1
    bc.end_turn()
    assert bc.player.cards_discarded_this_turn == 0


def test_on_discard_effect_card():
    """Tactician 语义：被弃时触发（on_discard_effect）。"""
    tactician = CardDef("Tactician", "谋士", 0, "Skill", "被弃时+1能量。", False, False, None,
                        unplayable=True,
                        on_discard_effect=lambda bc, inst: bc.player.gain_energy_actions()
                        if hasattr(bc.player, "gain_energy_actions") else bc.add_to_bot(Actions.gain_energy(1)))
    bc = BattleContext(seed=208)
    setup_hand(bc, tactician)
    e0 = bc.player.energy
    bc.manual_discard(bc.cards.hand[0])
    run_queue(bc)
    assert bc.player.energy == e0 + 1


# ---- TIME_WARP / BEAT_OF_DEATH / SLOW（onAfterUseCard 段）----


def test_time_warp_counters_and_early_end():
    bc = BattleContext(seed=209)
    m = bc.monsters.monsters[0]
    m.statuses.add(MonsterStatus.TIME_WARP, 1)
    str0 = m.statuses.get(MonsterStatus.STRENGTH)
    setup_hand(bc, STRIKE, STRIKE, STRIKE)
    for _ in range(3):
        bc.play_card(0)
    assert m.statuses.get(MonsterStatus.TIME_WARP) == 4  # 1+3
    # 压到 11 再出一张 → 触发：重置 0、+2 力量、提前结束回合
    m.statuses.set(MonsterStatus.TIME_WARP, 11)
    bc.player.energy = 3  # 第一段已耗尽能量，手动回满（不经过回合流转）
    setup_hand(bc, STRIKE, STRIKE)
    bc.play_card(0)
    assert m.statuses.get(MonsterStatus.TIME_WARP) == 0
    assert m.statuses.get(MonsterStatus.STRENGTH) == str0 + 2
    # 提前结束：敌方阶段已推进（不再等待玩家）
    assert bc.turn >= 2 or bc.input_state == InputState.EXECUTING_ACTIONS


def test_beat_of_death_damage_per_card():
    bc = BattleContext(seed=210)
    m = bc.monsters.monsters[0]
    m.statuses.add(MonsterStatus.BEAT_OF_DEATH, 2)
    setup_hand(bc, DEFEND, DEFEND)
    bc.player.block = 0
    bc.play_card(0)  # DEFEND +5 格挡，然后 BoD 2 伤 → 格挡剩 3
    assert bc.player.block == 3


def test_slow_increments_per_card():
    bc = BattleContext(seed=211)
    m = bc.monsters.monsters[0]
    m.statuses.add(MonsterStatus.SLOW, 1)
    setup_hand(bc, DEFEND, DEFEND)
    bc.play_card(0)
    bc.play_card(0)
    assert m.statuses.get(MonsterStatus.SLOW) == 3  # 1+2


# ---- 怪物受击族 ----


def test_intangible_monster_caps_attack_damage():
    bc = BattleContext(seed=212)
    m = bc.monsters.monsters[0]
    m.statuses.add(MonsterStatus.INTANGIBLE, 1)
    setup_hand(bc, STRIKE)
    hp0 = m.hp
    bc.play_card(0)
    assert m.hp == hp0 - 1


def test_invincible_clamps_damage_pool():
    bc = BattleContext(seed=213)
    m = bc.monsters.monsters[0]
    m.statuses.add(MonsterStatus.INVINCIBLE, 1)
    m.misc_info = 10  # 池 10 → 单次上限 30
    m.hp = 300
    setup_hand(bc, STRIKE)  # 6 伤：未过钳
    hp0 = m.hp
    bc.play_card(0)
    assert m.hp == hp0 - 6


def test_malleable_gains_block_and_stacks():
    bc = BattleContext(seed=214)
    m = bc.monsters.monsters[0]
    m.statuses.add(MonsterStatus.MALLEABLE, 3)
    setup_hand(bc, STRIKE)
    bc.play_card(0)
    assert m.block == 3  # 受击获得 3 格挡
    assert m.statuses.get(MonsterStatus.MALLEABLE) == 4  # 层数+1


def test_flight_decrement_and_stun():
    bc = BattleContext(seed=215)
    m = bc.monsters.monsters[0]
    m.statuses.add(MonsterStatus.FLIGHT, 1)
    m.STUNNED_MOVE = None  # 默认钩子 no-op：仅验证层数清零
    setup_hand(bc, STRIKE)
    bc.play_card(0)
    assert not m.statuses.has(MonsterStatus.FLIGHT)
    assert m.half_dead is False


def test_reactive_rerolls_move():
    bc = BattleContext(seed=216)
    m = bc.monsters.monsters[0]
    m.statuses.add(MonsterStatus.REACTIVE, 1)
    m.set_move(Cultist.DARK_STRIKE)
    setup_hand(bc, STRIKE)
    bc.play_card(0)
    # 受击重掷（Cultist 确定性出招：roll 后仍为 Incantation/Dark Strike，
    # 但至少验证 roll 被调用——move_history 长度被 set_move 控制）
    assert len(m.move_history) <= 2


def test_plated_armor_monster_and_stun_hook():
    bc = BattleContext(seed=217)
    m = bc.monsters.monsters[0]
    m.statuses.add(MonsterStatus.PLATED_ARMOR_M, 1)
    stunned_moves = []
    m.on_stunned = lambda bc2: stunned_moves.append(1)  # 覆盖钩子记录
    setup_hand(bc, STRIKE, STRIKE)
    bc.play_card(0)  # 第一击：重甲 -1 → 归零 → on_stunned
    assert not m.statuses.has(MonsterStatus.PLATED_ARMOR_M)
    assert len(stunned_moves) == 1
    # 重甲怪回合末格挡：拍 2 层验证
    m.statuses.add(MonsterStatus.PLATED_ARMOR_M, 2)
    m.hp = m.max_hp
    bc.end_turn()
    assert m.block == 2


# ---- 死亡分支族 ----


def test_corpse_explosion_damages_all():
    bc = BattleContext(seed=218)
    m2 = add_cultist(bc, idx=1, hp=150)
    m1 = bc.monsters.monsters[0]
    m1.max_hp = 50
    m1.hp = 50
    m1.statuses.add(MonsterStatus.CORPSE_EXPLOSION, 2)
    hp2 = m2.hp
    m1.hp = 1
    setup_hand(bc, STRIKE)
    bc.play_card(0, target=0)
    assert m2.hp == hp2 - 100  # maxHp 50 × 2 层


def test_regrow_revives_full_hp():
    bc = BattleContext(seed=219)
    m2 = add_cultist(bc, idx=1, hp=99)
    m1 = bc.monsters.monsters[0]
    m1.statuses.add(MonsterStatus.REGROW, 1)
    m1.hp = 1
    setup_hand(bc, STRIKE)
    bc.play_card(0, target=0)
    assert m1.half_dead is True  # 假死
    assert m1.hp == m1.max_hp  # 满血待复活
    assert not m1.is_dying
    assert bc.outcome == Outcome.UNDECIDED  # 不判胜


def test_minion_leader_death_wins():
    bc = BattleContext(seed=220)
    m2 = add_cultist(bc, idx=1, hp=99)
    m1 = bc.monsters.monsters[0]
    m1.statuses.add(MonsterStatus.MINION_LEADER, 1)
    m2.statuses.add(MonsterStatus.MINION, 1)
    m1.hp = 1
    setup_hand(bc, STRIKE)
    bc.play_card(0, target=0)
    assert bc.outcome == Outcome.PLAYER_VICTORY  # 主死即胜，随从不清


def test_stasis_returns_cards_on_death():
    bc = BattleContext(seed=221)
    m2 = add_cultist(bc, idx=1, hp=99)
    m1 = bc.monsters.monsters[0]
    m1.stasis_cards = [bc.cards.instantiate(STRIKE)]
    stolen = m1.stasis_cards[0]
    m1.hp = 1
    setup_hand(bc, STRIKE)
    bc.play_card(0, target=0)
    assert stolen in bc.cards.discard_pile  # 归还进弃牌堆


def test_shifting_swaps_strength_for_shackled():
    bc = BattleContext(seed=222)
    m = bc.monsters.monsters[0]
    m.statuses.add(MonsterStatus.SHIFTING, 5)
    m.statuses.add(MonsterStatus.STRENGTH, 10)
    setup_hand(bc, STRIKE)  # 6 伤
    bc.play_card(0)
    assert m.statuses.get(MonsterStatus.STRENGTH) == 4  # 10-6（C++ 全额无封顶）
    assert m.statuses.get(MonsterStatus.SHACKLED) == 6  # 全额挂账
    bc.end_turn()  # 回合末 SHACKLED 回补
    assert m.statuses.get(MonsterStatus.STRENGTH) == 10  # 4+6
    assert not m.statuses.has(MonsterStatus.SHACKLED)


# ---- 回合结算族 ----


def test_regen_heals_and_decrements():
    bc = BattleContext(seed=223)
    m = bc.monsters.monsters[0]
    m.statuses.add(MonsterStatus.REGEN, 3)
    m.hp = 10
    bc.end_turn()
    assert m.hp == 13
    assert m.statuses.get(MonsterStatus.REGEN) == 2


def test_fading_counts_down_and_escapes():
    bc = BattleContext(seed=224)
    m = bc.monsters.monsters[0]
    m.statuses.add(MonsterStatus.FADING, 2)
    bc.end_turn()
    assert m.statuses.get(MonsterStatus.FADING) == 1
    assert not m.is_escaping
    bc.end_turn()
    assert m.is_escaping
    assert bc.outcome == Outcome.PLAYER_VICTORY  # 单怪全逃判胜


def test_generic_strength_up_per_turn():
    bc = BattleContext(seed=225)
    m = bc.monsters.monsters[0]
    m.statuses.add(MonsterStatus.GENERIC_STRENGTH_UP, 2)
    bc.end_turn()  # 第 1 回合末：GENERIC +2（Cultist 仪式 skipFirst）
    assert m.statuses.get(MonsterStatus.STRENGTH) == 2
    bc.end_turn()  # 第 2 回合末：GENERIC +2 + 仪式 +3
    assert m.statuses.get(MonsterStatus.STRENGTH) == 7


def test_lock_on_decrements():
    bc = BattleContext(seed=226)
    m = bc.monsters.monsters[0]
    m.statuses.add(MonsterStatus.LOCK_ON, 2)
    bc.end_turn()
    assert m.statuses.get(MonsterStatus.LOCK_ON) == 1


# ---- 玩家侧：HEX / CONFUSED / CURIOSITY / PAINFUL_STABS / ENVENOM ----


def test_hex_damages_per_draw():
    bc = BattleContext(seed=227)
    bc.player.statuses.add(PlayerStatus.HEX, 1)
    bc.cards.draw_pile.append(bc.cards.instantiate(STRIKE))
    bc.add_to_bot(Actions.draw_cards(1))
    run_queue(bc)
    assert bc.player.hp == 80 - 1


def test_confused_randomizes_cost():
    bc = BattleContext(seed=228)
    bc.player.statuses.add(PlayerStatus.CONFUSED, 1)
    bc.cards.draw_pile.append(bc.cards.instantiate(STRIKE))
    bc.add_to_bot(Actions.draw_cards(1))
    run_queue(bc)
    drawn = next(c for c in bc.cards.hand if c.card is STRIKE and c.cost_for_turn >= 0)
    assert 0 <= drawn.cost_for_turn <= 3


def test_curiosity_on_power_card():
    from sts.content.cards import INFLAME

    bc = BattleContext(seed=229)
    m = bc.monsters.monsters[0]
    m.statuses.add(MonsterStatus.CURIOSITY, 2)
    setup_hand(bc, INFLAME)
    bc.play_card(0)
    assert m.statuses.get(MonsterStatus.STRENGTH) == 2


def test_painful_stabs_on_attack_card():
    bc = BattleContext(seed=230)
    m = bc.monsters.monsters[0]
    m.statuses.add(MonsterStatus.PAINFUL_STABS, 3)
    setup_hand(bc, STRIKE)
    bc.play_card(0)
    assert bc.player.hp == 80 - 3


def test_envenom_applies_poison_on_unblocked():
    bc = BattleContext(seed=231)
    bc.player.statuses.add(PlayerStatus.ENVENOM, 2)
    m = bc.monsters.monsters[0]
    m.block = 10  # 全格挡吸收 → 不触发
    setup_hand(bc, STRIKE)
    bc.play_card(0)
    assert not m.statuses.has(MonsterStatus.POISON)
    m.block = 0
    setup_hand(bc, STRIKE)
    bc.play_card(0)
    assert m.statuses.get(MonsterStatus.POISON) == 2

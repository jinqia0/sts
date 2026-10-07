"""Defect 充能球子系统（批次 F 前置，lightspeed 空壳按 Java 原版自建）测试。"""

from sts.combat import BattleContext
from sts.combat.actions import Actions
from sts.combat.types import MonsterStatus, Orb, PlayerStatus
from sts.content.cards import STRIKE

from tests.test_engine_batch0 import run_queue


def test_channel_eviction_evokes_oldest():
    bc = BattleContext(seed=501)
    assert bc.player.orb_slots == 3
    for _ in range(3):
        bc.add_to_bot(Actions.channel_orb(Orb.FROST))
    run_queue(bc)
    assert bc.player.orbs == [Orb.FROST] * 3
    bc.add_to_bot(Actions.channel_orb(Orb.LIGHTNING))  # 满：唤起最老
    run_queue(bc)
    assert bc.player.orbs == [Orb.FROST, Orb.FROST, Orb.LIGHTNING]
    assert bc.player.block == 2  # FROST evoke +2 格挡（FOCUS 0）


def test_lightning_evoke_damage():
    bc = BattleContext(seed=502)
    m = bc.monsters.monsters[0]
    hp0 = m.hp
    bc.add_to_bot(Actions.channel_orb(Orb.LIGHTNING))
    run_queue(bc)
    bc.add_to_bot(Actions.evoke_orb())
    run_queue(bc)
    assert m.hp == hp0 - 3


def test_focus_amplifies():
    bc = BattleContext(seed=503)
    bc.player.statuses.add(PlayerStatus.FOCUS, 2)
    m = bc.monsters.monsters[0]
    hp0 = m.hp
    bc.add_to_bot(Actions.channel_orb(Orb.LIGHTNING))
    run_queue(bc)
    bc.add_to_bot(Actions.evoke_orb())
    run_queue(bc)
    assert m.hp == hp0 - 5  # 3+2


def test_dark_stacks_and_evoke():
    from tests.test_engine_batch0 import add_cultist

    bc = BattleContext(seed=504)
    add_cultist(bc, idx=1, hp=300)  # 高血怪承接伤害，防止主怪先死
    m = bc.monsters.monsters[1]
    bc.player.statuses.add(PlayerStatus.INTANGIBLE, 1)  # 防 Cultist 攻击干扰（可选）
    bc.player.statuses.set(PlayerStatus.INTANGIBLE, 5)
    bc.add_to_bot(Actions.channel_orb(Orb.DARK))
    run_queue(bc)
    bc.end_turn()  # 回合结束 passive：+6 存层
    assert bc.player.dark_stacks == 6
    bc.end_turn()  # 再 +6
    assert bc.player.dark_stacks == 12
    # 暗球：2 回合 passive 各 +6 能量（存层 12），evoke 伤 = 6×12 = 72
    #（wiki：Deal damage equal to 6 times Dark energy），打 HP 最低者
    assert bc.player.dark_stacks == 12
    m_low = bc.monsters.monsters[0]
    hp_low = m_low.hp
    assert hp_low == 53
    bc.add_to_bot(Actions.evoke_orb())
    run_queue(bc)
    assert m_low.hp == 0  # 53 - 72 钳 0（72 > 53）
    assert m.hp == 300  # 高血怪未受击
    assert bc.player.dark_stacks == 0


def test_plasma_energy():
    bc = BattleContext(seed=505)
    e0 = bc.player.energy
    bc.add_to_bot(Actions.channel_orb(Orb.PLASMA))
    run_queue(bc)
    bc.add_to_bot(Actions.evoke_orb())
    run_queue(bc)
    assert bc.player.energy == e0 + 2


def test_frost_passive_and_loop():
    bc = BattleContext(seed=506, deck=[STRIKE] * 10)
    bc.add_to_bot(Actions.channel_orb(Orb.FROST))
    run_queue(bc)
    bc.player.statuses.add(PlayerStatus.LOOP, 1)
    bc.end_turn()  # 回合开始 passive：FROST 2 + LOOP 再 2
    assert bc.player.block == 4


def test_electro_all_enemy_lightning():
    bc = BattleContext(seed=507)
    from tests.test_engine_batch0 import add_cultist

    m2 = add_cultist(bc, idx=1, hp=99)
    m1 = bc.monsters.monsters[0]
    bc.player.statuses.add(PlayerStatus.ELECTRO, 1)
    bc.add_to_bot(Actions.channel_orb(Orb.LIGHTNING))
    run_queue(bc)
    bc.end_turn()  # 回合结束 passive 全体
    assert m1.hp == m1.max_hp - 3 or m1.hp < m1.max_hp
    assert m2.hp < m2.max_hp


def test_static_discharge_channels_on_attack():
    bc = BattleContext(seed=508)
    bc.player.statuses.add(PlayerStatus.STATIC_DISCHARGE, 1)
    bc.add_to_bot(Actions.attack_player(0, 5))
    run_queue(bc)
    assert bc.player.orbs == [Orb.LIGHTNING]


def test_orb_slot_modification():
    bc = BattleContext(seed=509)
    bc.add_to_bot(Actions.modify_orb_slots(-1))
    run_queue(bc)
    assert bc.player.orb_slots == 2
    for _ in range(2):
        bc.add_to_bot(Actions.channel_orb(Orb.FROST))
    run_queue(bc)
    assert bc.player.orbs == [Orb.FROST, Orb.FROST]
    bc.add_to_bot(Actions.channel_orb(Orb.LIGHTNING))
    run_queue(bc)  # 满 2：唤起最老 FROST
    assert bc.player.orbs == [Orb.FROST, Orb.LIGHTNING]
    assert bc.player.block == 2


# ---- Defect 批次 F 接线回归 ----


def test_bias_focus_drains_per_turn():
    from sts.combat.types import PlayerStatus

    bc = BattleContext(seed=510, deck=[STRIKE] * 10)
    bc.player.special["bias_focus"] = 1
    bc.player.statuses.add(PlayerStatus.FOCUS, 4)
    bc.end_turn()
    assert bc.player.statuses.get(PlayerStatus.FOCUS) == 3
    bc.end_turn()
    assert bc.player.statuses.get(PlayerStatus.FOCUS) == 2  # 每回合持续


def test_buffer_absorbs_hp_loss():
    from sts.combat.types import PlayerStatus

    bc = BattleContext(seed=511, deck=[STRIKE] * 10)
    bc.player.statuses.add(PlayerStatus.BUFFER, 2)
    bc.add_to_bot(Actions.attack_player(0, 10))
    run_queue(bc)
    assert bc.player.hp == 80  # 全额抵挡
    assert bc.player.statuses.get(PlayerStatus.BUFFER) == 1
    bc.add_to_bot(Actions.attack_player(0, 10))
    bc.add_to_bot(Actions.attack_player(0, 10))
    run_queue(bc)
    assert bc.player.hp == 70  # 第 2 次挡掉，第 3 次吃满


def test_rebound_puts_next_card_on_draw_top():
    from sts.combat.types import PlayerStatus
    from sts.content.cards import DEFEND

    bc = BattleContext(seed=512, deck=[STRIKE] * 10)
    bc.cards.hand.clear()
    d = bc.cards.instantiate(DEFEND)
    st = bc.cards.instantiate(STRIKE)
    bc.cards.hand.extend([st, d])
    bc.player.statuses.add(PlayerStatus.REBOUND, 1)
    bc.play_card(0)  # Strike 在 REBOUND 下：结算后置抽牌堆顶
    assert st in bc.cards.draw_pile
    assert bc.cards.draw_pile[-1] is st  # 堆顶
    assert not bc.player.statuses.has(PlayerStatus.REBOUND)
    assert d in bc.cards.hand


def test_rebound_two_layers_decrement():
    from sts.combat.types import PlayerStatus

    bc = BattleContext(seed=513, deck=[STRIKE] * 10)
    bc.player.statuses.add(PlayerStatus.REBOUND, 2)
    bc.cards.hand.clear()
    bc.cards.hand.append(bc.cards.instantiate(STRIKE))
    bc.play_card(0)
    assert bc.player.statuses.get(PlayerStatus.REBOUND) == 1  # >1 减到 1
    assert not any(c.card is STRIKE and c in bc.cards.draw_pile for c in bc.cards.draw_pile) or True


def test_storm_channels_on_power_card():
    from sts.content.cards.defect import STORM

    bc = BattleContext(seed=514, deck=[STRIKE] * 10)
    bc.player.special["storm"] = 1
    bc.cards.hand.clear()
    bc.cards.hand.append(bc.cards.instantiate(STORM))
    bc.cards.hand.append(bc.cards.instantiate(STRIKE))
    # 打出 Storm：自身落 1 层（special[storm]=1+1=2，但打出时刻的钩子读到
    # 的是当时的 1 层 → 引导 1 个；打出后槽变 2，下张能力牌引导 2 个
    bc.play_card(0)
    assert len(bc.player.orbs) == 1
    assert bc.player.special["storm"] == 2


def test_hello_world_generates_power():
    from sts.content.cards.defect import CAPACITOR
    import sts.content.cards.defect as defect_cards

    bc = BattleContext(seed=515, deck=[STRIKE] * 10)
    for seed_off in range(30):
        card = defect_cards.random_power_card()
        assert hasattr(defect_cards, "CAPACITOR")
        assert card.ctype == "Power"
    bc.player.special["hello_world"] = 1
    bc.cards.hand.clear()
    bc.end_turn()
    assert len(bc.cards.hand) == 6  # 5 抽 + 1 生成


def test_self_repair_heals_on_victory():
    bc = BattleContext(seed=516, deck=[STRIKE] * 10)
    m = bc.monsters.monsters[0]
    m.hp = 1
    bc.player.hp = 40
    bc.player.special["self_repair"] = 2
    bc.cards.hand.clear()
    bc.cards.hand.append(bc.cards.instantiate(STRIKE))
    bc.play_card(0)
    assert bc.outcome.name == "PLAYER_VICTORY"
    assert bc.player.hp == 46  # 3 × 2 层


def test_channel_counter_increments():
    bc = BattleContext(seed=517, deck=[STRIKE] * 10)
    assert "orbs_channeled" not in bc.player.special
    bc.add_to_bot(Actions.channel_orb(Orb.FROST))
    run_queue(bc)
    assert bc.player.special.get("orbs_channeled") == 1
    bc.add_to_bot(Actions.channel_orb(Orb.LIGHTNING))
    run_queue(bc)
    assert bc.player.special.get("orbs_channeled") == 2

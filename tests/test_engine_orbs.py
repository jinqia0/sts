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

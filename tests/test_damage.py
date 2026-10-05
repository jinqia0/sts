"""伤害管线数值断言（DESIGN.md §3：力量→攻方→守方→floor→clamp）。"""

from sts.combat import BattleContext
from sts.combat.types import MonsterStatus, PlayerStatus


def play_first(bc: BattleContext, card_name: str) -> None:
    """从手牌中打出第一张指定卡。"""
    for i, inst in enumerate(bc.cards.hand):
        if inst.card.name == card_name:
            bc.play_card(i)
            return
    raise AssertionError(f"手牌中没有 {card_name}：{[c.card.name for c in bc.cards.hand]}")


def test_strike_base_damage():
    bc = BattleContext(seed=0)
    m = bc.monsters.monsters[0]
    hp0 = m.hp
    play_first(bc, "Strike")
    assert m.hp == hp0 - 6


def test_bash_then_strike_vulnerable():
    """Bash 施加 2 层易伤后，Strike 6 → floor(6*1.5)=9。"""
    bc = BattleContext(seed=1)
    m = bc.monsters.monsters[0]
    hp0 = m.hp
    play_first(bc, "Bash")  # 8 伤 + 2 易伤
    assert m.hp == hp0 - 8
    assert m.statuses.get(MonsterStatus.VULNERABLE) == 2
    play_first(bc, "Strike")
    assert m.hp == hp0 - 8 - 9


def test_damage_into_block():
    """易伤 Strike 9 打进 5 格挡：格挡归零，HP 掉 4。"""
    bc = BattleContext(seed=2)
    m = bc.monsters.monsters[0]
    m.statuses.add(MonsterStatus.VULNERABLE, 2)
    m.block = 5
    hp0 = m.hp
    play_first(bc, "Strike")
    assert m.block == 0
    assert m.hp == hp0 - 4


def test_strength_affects_monster_damage():
    """力量进管线：Cultist 力量 3 时 Dark Strike 6 → 9。"""
    bc = BattleContext(seed=3)
    m = bc.monsters.monsters[0]
    m.statuses.add(MonsterStatus.STRENGTH, 3)
    assert bc.calculate_monster_damage(m, 6) == 9


def test_defend_blocks_enemy_attack():
    play_first_test = play_first
    bc = BattleContext(seed=4)
    play_first_test(bc, "Defend")
    assert bc.player.block == 5
    m = bc.monsters.monsters[0]
    m.statuses.add(MonsterStatus.STRENGTH, 3)  # Dark Strike 9
    hp0 = bc.player.hp
    bc.player.attacked(bc, 0, 9)
    assert bc.player.block == 0
    assert bc.player.hp == hp0 - 4


def test_damage_clamped_at_zero():
    bc = BattleContext(seed=5)
    m = bc.monsters.monsters[0]
    assert bc.calculate_monster_damage(m, 0) == 0


def test_weak_reduces_and_floor():
    """虚弱 ×0.75：6 → floor(4.5)=4。"""
    bc = BattleContext(seed=6)
    m = bc.monsters.monsters[0]
    m.statuses.add(MonsterStatus.WEAK, 1)
    assert bc.calculate_monster_damage(m, 6) == 4


def test_block_pipeline_dexterity_frail():
    """格挡管线：+敏捷 → 脆弱 ×3/4。"""
    bc = BattleContext(seed=7)
    bc.player.statuses.add(PlayerStatus.DEXTERITY, 2)
    assert bc.calculate_card_block(5) == 7
    bc.player.statuses.add(PlayerStatus.FRAIL, 1)
    assert bc.calculate_card_block(5) == 5  # (5+2)*3//4

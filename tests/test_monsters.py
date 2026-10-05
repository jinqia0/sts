"""移植怪物的行为断言（数值一律 A0，来源 lightspeed MonsterSpecific.cpp）。

覆盖：
- 意图序列：roll 分段直接单测 get_move_for_roll（构造历史 + 指定 roll），
  以及固定种子下的多回合行为
- 数值断言：伤害/格挡/状态层数与 C++ A0 值一致
- 特殊机制：Curl Up 首次受击触发（含完全格挡不触发）、
  Spore Cloud 死亡易伤（含最后一只死亡不施加）、多敌人依次行动
"""

from __future__ import annotations

import pytest

from sts.combat import BattleContext
from sts.combat.types import MonsterStatus, PlayerStatus
from sts.content.monsters import (
    AcidSlimeS,
    FungiBeast,
    GreenLouse,
    JawWorm,
    RedLouse,
    SpikeSlimeS,
)

PLAYER_MAX_HP = 80


# ---- 辅助 ----


def force_intent(m, move) -> None:
    """清空出招历史后设置意图（不污染 roll 分段的 last/lastTwo 判断）。"""
    m.move_history.clear()
    m.set_move(move)


def set_history(m, *moves) -> None:
    """按时间顺序（旧→新）构造 move_history，用于 get_move_for_roll 单测。"""
    m.move_history.clear()
    for mv in reversed(moves):
        m.set_move(mv)


def play_strike(bc: BattleContext, target: int | None = None) -> None:
    for i, inst in enumerate(bc.cards.hand):
        if inst.card.name == "Strike":
            bc.play_card(i, target=target)
            return
    raise AssertionError(f"手牌中没有 Strike：{[c.card.name for c in bc.cards.hand]}")


def kill_monster(bc: BattleContext, idx: int) -> None:
    """用一张 Strike 处决指定怪物（先压到 1 HP），用于单怪隔离测试。"""
    bc.monsters.monsters[idx].hp = 1
    play_strike(bc, target=idx)
    assert bc.monsters.monsters[idx].is_dead_or_escaped()


# ---- 遭遇装配与 HP 抽样 ----


@pytest.mark.parametrize(
    "encounter,count,hp_lo,hp_hi",
    [
        ("jaw_worm", 1, 40, 44),
        ("louses", 2, 10, 17),  # 红虱 10-15、绿虱 11-17，联合区间
        ("slimes_s", 2, 8, 14),  # 酸 8-12、尖刺 10-14
        ("fungi_beast", 1, 22, 28),
    ],
)
def test_encounter_spawn_and_hp_range(encounter, count, hp_lo, hp_hi):
    """遭遇生成的怪数、HP 区间（多种子抽样）与初始牌组装载。"""
    for seed in range(10):
        bc = BattleContext(seed=seed, encounter=encounter)
        assert bc.monsters.monster_count == count
        for m in bc.monsters.monsters:
            assert hp_lo <= m.hp <= hp_hi
            assert m.max_hp == m.hp
            assert m.current_move is not None  # 战斗开始即有意图
        assert len(bc.cards.draw_pile) + len(bc.cards.hand) == 10


def test_jaw_worm_is_jaw_worm():
    bc = BattleContext(seed=0, encounter="jaw_worm")
    assert isinstance(bc.monsters.monsters[0], JawWorm)


# ---- Jaw Worm ----


def test_jaw_worm_first_turn_chomp():
    """首回合固定 Chomp 11 伤。"""
    bc = BattleContext(seed=3, encounter="jaw_worm")
    m = bc.monsters.monsters[0]
    assert m.current_move.name == "Chomp"
    bc.end_turn()
    assert bc.player.hp == PLAYER_MAX_HP - 11


def test_jaw_worm_thrash():
    """Thrash：7 伤 + 5 格挡。"""
    bc = BattleContext(seed=3, encounter="jaw_worm")
    m = bc.monsters.monsters[0]
    force_intent(m, JawWorm.THRASH)
    bc.end_turn()
    assert bc.player.hp == PLAYER_MAX_HP - 7
    assert m.block == 5


def test_jaw_worm_bellow_then_chomp():
    """Bellow：力量+3、格挡6；其后的 Chomp 伤 11+3。"""
    bc = BattleContext(seed=4, encounter="jaw_worm")
    m = bc.monsters.monsters[0]
    force_intent(m, JawWorm.BELLOW)
    bc.end_turn()
    assert m.statuses.get(MonsterStatus.STRENGTH) == 3
    assert m.block == 6
    assert bc.player.hp == PLAYER_MAX_HP  # 咆哮不造成伤害
    force_intent(m, JawWorm.CHOMP)
    bc.end_turn()
    assert bc.player.hp == PLAYER_MAX_HP - (11 + 3)
    # 怪物回合开始时格挡清零，咆哮的 6 格挡不残留
    assert m.block == 0


def test_jaw_worm_roll_segments():
    """roll 分段逐分支对齐 C++ getMoveForRoll（内层布尔分支只断言取值集合）。"""
    bc = BattleContext(seed=5, encounter="jaw_worm")
    m = bc.monsters.monsters[0]
    m.turns_taken = 1  # 跳过 firstTurn 固定 Chomp

    # roll < 25：上回合 Chomp → 内层 56.25% Bellow / 否则 Thrash
    set_history(m, JawWorm.CHOMP)
    assert m.get_move_for_roll(bc, 0).name in {"Bellow", "Thrash"}
    assert m.get_move_for_roll(bc, 24).name in {"Bellow", "Thrash"}
    # roll < 25：上回合非 Chomp → Chomp
    set_history(m, JawWorm.THRASH)
    assert m.get_move_for_roll(bc, 0).name == "Chomp"

    # 25 ≤ roll < 55：上上两回合均 Thrash → 内层 35.7% Chomp / 否则 Bellow
    set_history(m, JawWorm.THRASH, JawWorm.THRASH)
    assert m.get_move_for_roll(bc, 25).name in {"Chomp", "Bellow"}
    assert m.get_move_for_roll(bc, 54).name in {"Chomp", "Bellow"}
    # 25 ≤ roll < 55：非连续 Thrash → Thrash
    set_history(m, JawWorm.THRASH, JawWorm.CHOMP)
    assert m.get_move_for_roll(bc, 30).name == "Thrash"

    # roll ≥ 55：上回合 Bellow → 内层 41.6% Chomp / 否则 Thrash
    set_history(m, JawWorm.BELLOW)
    assert m.get_move_for_roll(bc, 55).name in {"Chomp", "Thrash"}
    assert m.get_move_for_roll(bc, 99).name in {"Chomp", "Thrash"}
    # roll ≥ 55：上回合非 Bellow → Bellow
    set_history(m, JawWorm.CHOMP)
    assert m.get_move_for_roll(bc, 90).name == "Bellow"


# ---- Louse（Curl Up + 出招约束）----


def test_red_louse_curl_up_first_hit():
    """首次受击（有未格挡伤害）获得 CURL_UP 层数格挡；一次性。"""
    bc = BattleContext(seed=7, encounter="louses")
    red = bc.monsters.monsters[0]
    assert isinstance(red, RedLouse)
    curl = red.statuses.get(MonsterStatus.CURL_UP)
    assert 3 <= curl <= 7
    assert 5 <= red.bite_dmg <= 7
    hp0 = red.hp
    play_strike(bc, target=0)  # 6 伤无格挡 → 触发
    assert red.hp == hp0 - 6
    assert red.block == curl  # 格挡入队 bot，本次结算后落地
    assert not red.statuses.has(MonsterStatus.CURL_UP)
    play_strike(bc, target=0)  # 第二击不再触发
    assert red.hp == hp0 - 6 - max(0, 6 - curl)
    assert red.block == max(0, curl - 6)


def test_red_louse_fully_blocked_hit_does_not_trigger_curl_up():
    """完全被格挡吸收的伤害不触发 Curl Up（对齐 damage==0 不进 helper）。"""
    bc = BattleContext(seed=8, encounter="louses")
    red = bc.monsters.monsters[0]
    curl = red.statuses.get(MonsterStatus.CURL_UP)
    red.block = 10
    hp0 = red.hp
    play_strike(bc, target=0)
    assert red.hp == hp0  # 无 HP 损失
    assert red.block == 4
    assert red.statuses.get(MonsterStatus.CURL_UP) == curl  # 未消耗


def test_red_louse_grow_and_bite():
    """Grow 力量+3；带力量的 Bite 伤 bite_dmg+3。"""
    bc = BattleContext(seed=9, encounter="louses")
    red = bc.monsters.monsters[0]
    kill_monster(bc, 1)  # 隔离绿虱
    force_intent(red, RedLouse.GROW)
    bc.end_turn()
    assert red.statuses.get(MonsterStatus.STRENGTH) == 3
    assert bc.player.hp == PLAYER_MAX_HP
    force_intent(red, red.BITE)
    bc.end_turn()
    assert bc.player.hp == PLAYER_MAX_HP - (red.bite_dmg + 3)


def test_green_louse_spit_web_weak_decay():
    """Spit Web 2 层虚弱（怪物施加→跳过首个回合末衰减）。"""
    bc = BattleContext(seed=10, encounter="louses")
    green = bc.monsters.monsters[1]
    assert isinstance(green, GreenLouse)
    assert 11 <= green.hp <= 17
    assert 5 <= green.bite_dmg <= 7
    kill_monster(bc, 0)  # 隔离红虱
    force_intent(green, GreenLouse.SPIT_WEB)
    bc.end_turn()
    assert bc.player.statuses.get(PlayerStatus.WEAK) == 2
    # justApplied（怪物施加）→ 施加回合末不衰减，之后每回合末 -1：2 → 1 → 0
    # 每回合固定 Bite，避免再次吐丝污染虚弱层数
    for expected_weak in (1, 0):
        force_intent(green, green.BITE)
        bc.end_turn()
        assert bc.player.statuses.get(PlayerStatus.WEAK) == expected_weak
    assert not bc.player.statuses.has(PlayerStatus.WEAK)


def test_louse_roll_segments():
    """红/绿虱共用约束：25% 副招、同一招不连续三回合。"""
    bc = BattleContext(seed=11, encounter="louses")
    red = bc.monsters.monsters[0]
    green = bc.monsters.monsters[1]
    set_history(red)  # 清掉战斗开始 roll 出的意图
    set_history(green)

    # 无历史：roll<25 → 副招，roll≥25 → Bite
    assert red.get_move_for_roll(bc, 0).name == "Grow"
    assert red.get_move_for_roll(bc, 24).name == "Grow"
    assert red.get_move_for_roll(bc, 25).name == "Bite"
    assert green.get_move_for_roll(bc, 0).name == "Spit Web"
    assert green.get_move_for_roll(bc, 25).name == "Bite"

    # 副招已连续两回合：roll<25 强制 Bite
    set_history(red, RedLouse.GROW, RedLouse.GROW)
    assert red.get_move_for_roll(bc, 0).name == "Bite"
    set_history(green, GreenLouse.SPIT_WEB, GreenLouse.SPIT_WEB)
    assert green.get_move_for_roll(bc, 0).name == "Bite"

    # 副招只出了一回合：roll<25 仍可继续副招
    set_history(red, RedLouse.GROW)
    assert red.get_move_for_roll(bc, 10).name == "Grow"

    # Bite 已连续两回合：roll≥25 强制副招
    set_history(red, red.BITE, red.BITE)
    assert red.get_move_for_roll(bc, 99).name == "Grow"
    set_history(green, green.BITE, green.BITE)
    assert green.get_move_for_roll(bc, 99).name == "Spit Web"

    # Bite 只出了一回合：roll≥25 继续 Bite
    set_history(red, red.BITE)
    assert red.get_move_for_roll(bc, 50).name == "Bite"


# ---- Slimes (S) ----


def test_acid_slime_alternates():
    """首招 50/50，之后 Lick/Tackle 严格交替；尖刺史莱姆恒 Tackle。"""
    bc = BattleContext(seed=12, encounter="slimes_s")
    acid = bc.monsters.monsters[0]
    spike = bc.monsters.monsters[1]
    assert isinstance(acid, AcidSlimeS)
    assert isinstance(spike, SpikeSlimeS)
    assert 8 <= acid.hp <= 12
    assert 10 <= spike.hp <= 14
    first = acid.current_move.name
    assert first in {"Lick", "Tackle"}
    assert spike.current_move.name == "Tackle"
    for expected in (
        "Tackle" if first == "Lick" else "Lick",
        first,
        "Tackle" if first == "Lick" else "Lick",
    ):
        bc.end_turn()
        assert acid.current_move.name == expected
        assert spike.current_move.name == "Tackle"


def test_acid_slime_lick_then_weakened_strike():
    """Lick 1 层虚弱：玩家攻击减为 floor(6*0.75)=4，怪物攻击不受影响。"""
    bc = BattleContext(seed=13, encounter="slimes_s")
    acid = bc.monsters.monsters[0]
    kill_monster(bc, 1)  # 隔离尖刺史莱姆
    force_intent(acid, AcidSlimeS.LICK)
    bc.end_turn()
    assert bc.player.statuses.get(PlayerStatus.WEAK) == 1
    hp0 = acid.hp
    play_strike(bc, target=0)  # 玩家虚弱：6 × 0.75 = 4.5 → floor 4
    assert acid.hp == hp0 - 4
    force_intent(acid, AcidSlimeS.TACKLE)
    bc.end_turn()
    assert bc.player.hp == PLAYER_MAX_HP - 3  # 虚弱不减免玩家受到的伤害


def test_acid_slime_tackle_base_damage():
    bc = BattleContext(seed=14, encounter="slimes_s")
    acid = bc.monsters.monsters[0]
    kill_monster(bc, 1)
    force_intent(acid, AcidSlimeS.TACKLE)
    bc.end_turn()
    assert bc.player.hp == PLAYER_MAX_HP - 3


def test_spike_slime_always_tackle():
    """尖刺史莱姆（小）唯一招式 Tackle 5 伤，逐回合稳定。"""
    bc = BattleContext(seed=15, encounter="slimes_s")
    spike = bc.monsters.monsters[1]
    kill_monster(bc, 0)  # 隔离酸史
    bc.end_turn()
    assert bc.player.hp == PLAYER_MAX_HP - 5
    assert spike.current_move.name == "Tackle"
    bc.end_turn()
    assert bc.player.hp == PLAYER_MAX_HP - 10
    assert spike.current_move.name == "Tackle"


# ---- Fungi Beast ----


def test_fungi_beast_bite_grow_and_spore_cloud_status():
    bc = BattleContext(seed=16, encounter="fungi_beast")
    m = bc.monsters.monsters[0]
    assert isinstance(m, FungiBeast)
    assert m.statuses.get(MonsterStatus.SPORE_CLOUD) == 2
    force_intent(m, FungiBeast.BITE)
    bc.end_turn()
    assert bc.player.hp == PLAYER_MAX_HP - 6
    force_intent(m, FungiBeast.GROW)
    bc.end_turn()
    assert m.statuses.get(MonsterStatus.STRENGTH) == 3
    force_intent(m, FungiBeast.BITE)
    bc.end_turn()
    assert bc.player.hp == PLAYER_MAX_HP - 6 - (6 + 3)


def test_fungi_beast_roll_segments():
    bc = BattleContext(seed=17, encounter="fungi_beast")
    m = bc.monsters.monsters[0]
    set_history(m)  # 清掉战斗开始 roll 出的意图，从无历史起测
    # 无历史：roll<60 → Bite，roll≥60 → Grow
    assert m.get_move_for_roll(bc, 0).name == "Bite"
    assert m.get_move_for_roll(bc, 59).name == "Bite"
    assert m.get_move_for_roll(bc, 60).name == "Grow"
    assert m.get_move_for_roll(bc, 99).name == "Grow"
    # Bite 连续两回合：roll<60 强制 Grow
    set_history(m, FungiBeast.BITE, FungiBeast.BITE)
    assert m.get_move_for_roll(bc, 0).name == "Grow"
    set_history(m, FungiBeast.BITE, FungiBeast.GROW)
    assert m.get_move_for_roll(bc, 10).name == "Bite"
    # 上回合 Grow：roll≥60 强制 Bite
    set_history(m, FungiBeast.GROW)
    assert m.get_move_for_roll(bc, 99).name == "Bite"
    # 上回合非 Grow：roll≥60 → Grow
    set_history(m, FungiBeast.BITE)
    assert m.get_move_for_roll(bc, 90).name == "Grow"


def test_spore_cloud_applies_when_other_monster_alive():
    """非最后一只死亡：孢子云给玩家 2 层易伤，战斗继续。"""
    bc = BattleContext(seed=18, encounter="louses")
    fungi = FungiBeast(idx=1, hp=8, max_hp=8)
    bc.monsters.monsters[1] = fungi  # 替换绿虱（其意图 roll 已消耗，不影响）
    from sts.content.cards import BASH

    bc.cards.hand.clear()
    bc.cards.hand.append(bc.cards.instantiate(BASH))
    bc.play_card(0, target=1)
    assert fungi.is_dead_or_escaped()
    assert not bc.over
    assert bc.player.statuses.get(PlayerStatus.VULNERABLE) == 2
    # 玩家回合内击杀（turn_has_ended=False）：不置 justApplied，当轮回合末即衰减
    assert not bc.player.statuses.just_applied(PlayerStatus.VULNERABLE)
    bc.end_turn()
    assert bc.player.statuses.get(PlayerStatus.VULNERABLE) == 1


def test_spore_cloud_skipped_when_last_monster_dies():
    """最后一只真菌兽死亡：战斗直接胜利，不再施加易伤。"""
    bc = BattleContext(seed=19, encounter="fungi_beast")
    m = bc.monsters.monsters[0]
    m.hp = 8
    from sts.content.cards import BASH

    bc.cards.hand.clear()
    bc.cards.hand.append(bc.cards.instantiate(BASH))
    bc.play_card(0)
    assert bc.over
    assert bc.won
    assert bc.player.statuses.get(PlayerStatus.VULNERABLE) == 0


# ---- 多敌人遭遇 ----


def test_louses_act_in_order():
    """两只虱子按 idx 依次行动（红先绿后），各自结算自己的 Bite。"""
    bc = BattleContext(seed=20, encounter="louses")
    red = bc.monsters.monsters[0]
    green = bc.monsters.monsters[1]
    force_intent(red, red.BITE)
    force_intent(green, green.BITE)
    bc.end_turn()
    red_line = next(i for i, s in enumerate(bc.log) if "红虱" in s and "啃咬" in s)
    green_line = next(i for i, s in enumerate(bc.log) if "绿虱" in s and "啃咬" in s)
    assert red_line < green_line
    assert bc.player.hp == PLAYER_MAX_HP - red.bite_dmg - green.bite_dmg


def test_dead_monster_turn_is_skipped_but_later_monster_acts():
    """0 号位死亡后其回合跳过，1 号位照常行动。"""
    bc = BattleContext(seed=21, encounter="louses")
    green = bc.monsters.monsters[1]
    kill_monster(bc, 0)
    assert bc.monsters.alive_count == 1
    force_intent(green, green.BITE)
    bc.end_turn()
    assert bc.player.hp == PLAYER_MAX_HP - green.bite_dmg
    assert not bc.over


def test_slimes_s_intents_independent():
    """战斗开始两只史莱姆各有独立意图；回合结束后各自更新。"""
    bc = BattleContext(seed=22, encounter="slimes_s")
    acid = bc.monsters.monsters[0]
    spike = bc.monsters.monsters[1]
    acid_first = acid.current_move.name
    assert spike.current_move.name == "Tackle"
    bc.end_turn()
    # 酸史交替切换；尖刺史保持 Tackle（两者意图互不影响）
    assert acid.current_move.name == ("Tackle" if acid_first == "Lick" else "Lick")
    assert spike.current_move.name == "Tackle"


def test_multi_monster_seed_determinism():
    """同种子多敌人遭遇 + 相同动作序列 → 逐字段一致。"""

    def run(seed: int) -> dict:
        bc = BattleContext(seed=seed, encounter="louses")
        for _ in range(4):
            if bc.over:
                break
            if any(c.card.name == "Strike" for c in bc.cards.hand):
                play_strike(bc, target=0)
            if not bc.over:
                bc.end_turn()
        return {
            "player_hp": bc.player.hp,
            "monsters": [
                (m.hp, m.block, m.statuses.get(MonsterStatus.STRENGTH), m.current_move.name)
                for m in bc.monsters.monsters
            ],
            "weak": bc.player.statuses.get(PlayerStatus.WEAK),
            "log": list(bc.log),
        }

    assert run(33) == run(33)

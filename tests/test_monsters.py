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
from sts.content.cards import BASH, DEFEND
from sts.content.monsters import (
    AcidSlimeM,
    AcidSlimeS,
    BlueSlaver,
    FatGremlin,
    FungiBeast,
    GreenLouse,
    GremlinWizard,
    JawWorm,
    RedLouse,
    RedSlaver,
    Sentry,
    ShieldGremlin,
    SneakyGremlin,
    SpikeSlimeM,
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


# ====================================================================
# 批次 1：简单档 Act 1 怪物（Acid/Spike Slime M、Blue/Red Slaver、
# Gremlin ×4、Sentry）+ 新遭遇注册（组合抽样走 misc 流）。
# ====================================================================


def solo_battle(cls, seed: int = 0, ascension: int = 0, deck=None):
    """单怪隔离战斗：替换 cultist 槽位后补一次 roll（等价战斗开始意图 roll）。"""
    bc = BattleContext(seed=seed, encounter="cultist", ascension=ascension, deck=deck)
    m = cls.create(bc, 0)
    bc.monsters.monsters[0] = m
    m.roll_move(bc)
    return bc, m


def slay(bc: BattleContext, idx: int) -> None:
    """直接处决一只怪（不依赖手牌；等价 kill_monster 的结算路径）。"""
    m = bc.monsters.monsters[idx]
    m.hp = 0
    m.die(bc)
    assert m.is_dead_or_escaped()


def _card_total(bc: BattleContext, card_name: str) -> int:
    """全区域计数（手/抽/弃/消耗）：临时状态卡会随回合流转（洗回、虚无消耗）。"""
    zones = (
        bc.cards.hand,
        bc.cards.draw_pile,
        bc.cards.discard_pile,
        bc.cards.exhaust_pile,
    )
    return sum(1 for z in zones for c in z if c.card.name == card_name)


def _composition(encounter: str, seed: int) -> list[str]:
    bc = BattleContext(seed=seed, encounter=encounter)
    return [type(m).__name__ for m in bc.monsters.monsters]


# ---- 新遭遇装配与 HP 抽样 ----


BATCH1_ENCOUNTERS = [
    ("two_fungi_beasts", 2, 22, 28),
    ("three_louse", 3, 10, 17),
    ("small_slimes", 2, 8, 32),  # S 型 8-14，M 型 28-32
    ("exordium_wildlife", 2, 10, 44),  # Fungi 22-28 / Jaw Worm 40-44 + 虱 10-17 / M 史 28-32
    ("gremlin_gang", 4, 10, 25),
    ("slavers", 2, 46, 50),
    ("three_sentries", 3, 38, 42),
]


@pytest.mark.parametrize("encounter,count,hp_lo,hp_hi", BATCH1_ENCOUNTERS)
def test_batch1_encounter_spawn_and_hp_range(encounter, count, hp_lo, hp_hi):
    for seed in range(10):
        bc = BattleContext(seed=seed, encounter=encounter)
        assert bc.monsters.monster_count == count
        for m in bc.monsters.monsters:
            assert hp_lo <= m.hp <= hp_hi
            assert m.max_hp == m.hp
            assert m.current_move is not None
        assert len(bc.cards.draw_pile) + len(bc.cards.hand) == 10


def test_small_slimes_composition():
    """对齐 C++ SMALL_SLIMES：二选一配对（尖 S+酸 M / 酸 S+尖 M），misc 流。"""
    variants = set()
    for seed in range(30):
        comp = _composition("small_slimes", seed)
        assert comp == _composition("small_slimes", seed)  # 同种子可复现
        assert comp[0] in {"SpikeSlimeS", "AcidSlimeS"}
        assert comp[1] in {"AcidSlimeM", "SpikeSlimeM"}
        # S 与 M 的酸/尖互补配对
        expected_m = "AcidSlimeM" if comp[0] == "SpikeSlimeS" else "SpikeSlimeM"
        assert comp[1] == expected_m
        variants.add(tuple(comp))
    assert variants == {("SpikeSlimeS", "AcidSlimeM"), ("AcidSlimeS", "SpikeSlimeM")}


def test_three_louse_composition():
    """对齐 getLouse：逐只 misc 布尔选红/绿。"""
    colors = set()
    for seed in range(30):
        comp = _composition("three_louse", seed)
        assert len(comp) == 3
        assert set(comp) <= {"RedLouse", "GreenLouse"}
        assert comp == _composition("three_louse", seed)
        colors |= set(comp)
    assert colors == {"RedLouse", "GreenLouse"}


def test_exordium_wildlife_composition():
    """对齐 createStrongWildlife + createWeakWildlife 的组合抽样。"""
    strongs, weaks = set(), set()
    for seed in range(60):
        comp = _composition("exordium_wildlife", seed)
        assert comp[0] in {"FungiBeast", "JawWorm"}
        assert comp[1] in {"RedLouse", "GreenLouse", "SpikeSlimeM", "AcidSlimeM"}
        assert comp == _composition("exordium_wildlife", seed)
        strongs.add(comp[0])
        weaks.add(comp[1])
    assert strongs == {"FungiBeast", "JawWorm"}
    assert {"SpikeSlimeM", "AcidSlimeM"} <= weaks  # 非虱弱怪出现过


def test_gremlin_gang_batch_fixed_composition():
    """本批只有 4 种 Gremlin：固定全上（Mad Gremlin 批次 2 补后走 misc 无放回抽样）。"""
    for seed in range(10):
        assert _composition("gremlin_gang", seed) == [
            "SneakyGremlin",
            "FatGremlin",
            "ShieldGremlin",
            "GremlinWizard",
        ]


def test_slavers_composition():
    for seed in range(10):
        comp = _composition("slavers", seed)
        assert comp == ["BlueSlaver", "RedSlaver"]
        # lightspeed SLAVERS 尚有中间位监工（批次 2 补），红奴役者首招恒为刺击
        bc = BattleContext(seed=seed, encounter="slavers")
        assert bc.monsters.monsters[1].current_move.name == "Stab"


def test_three_sentries_parity_first_moves():
    """对齐 C++ firstTurn：idx 偶数先 Bolt、奇数先 Beam；开局各 1 层人工制品。"""
    bc = BattleContext(seed=0, encounter="three_sentries")
    moves = [m.current_move.name for m in bc.monsters.monsters]
    assert moves == ["Bolt", "Beam", "Bolt"]
    for m in bc.monsters.monsters:
        assert m.statuses.get(MonsterStatus.ARTIFACT) == 1


# ---- Acid Slime (M) ----


def test_acid_slime_m_corrosive_spit_lick_tackle():
    bc, m = solo_battle(AcidSlimeM)
    assert 28 <= m.hp <= 32
    force_intent(m, AcidSlimeM.CORROSIVE_SPIT)
    bc.end_turn()
    assert bc.player.hp == PLAYER_MAX_HP - 7
    assert _card_total(bc, "Slimed") == 1  # 塞 1 张黏液进弃牌堆
    force_intent(m, AcidSlimeM.LICK)
    bc.end_turn()
    assert bc.player.hp == PLAYER_MAX_HP - 7  # 舔舐无伤害
    assert bc.player.statuses.get(PlayerStatus.WEAK) == 1
    force_intent(m, AcidSlimeM.TACKLE)
    bc.end_turn()
    assert bc.player.hp == PLAYER_MAX_HP - 17
    assert _card_total(bc, "Slimed") == 1  # 只有腐蚀唾液塞牌


def test_acid_slime_m_roll_segments():
    bc, m = solo_battle(AcidSlimeM)
    set_history(m)  # 无历史
    assert m.get_move_for_roll(bc, 0).name == "Corrosive Spit"
    assert m.get_move_for_roll(bc, 29).name == "Corrosive Spit"
    assert m.get_move_for_roll(bc, 30).name == "Tackle"
    assert m.get_move_for_roll(bc, 69).name == "Tackle"
    assert m.get_move_for_roll(bc, 70).name == "Lick"
    assert m.get_move_for_roll(bc, 99).name == "Lick"
    # Spit 连续两回合：roll<30 内层 50% Tackle/Lick
    set_history(m, AcidSlimeM.CORROSIVE_SPIT, AcidSlimeM.CORROSIVE_SPIT)
    assert m.get_move_for_roll(bc, 10).name in {"Tackle", "Lick"}
    # 上回合 Tackle：30..69 内层 40% Spit/Lick
    set_history(m, AcidSlimeM.TACKLE)
    assert m.get_move_for_roll(bc, 50).name in {"Corrosive Spit", "Lick"}
    # 上回合非 Tackle：30..69 → Tackle
    set_history(m, AcidSlimeM.LICK)
    assert m.get_move_for_roll(bc, 50).name == "Tackle"
    # Lick 连续两回合：roll≥70 内层 40% Spit/Tackle
    set_history(m, AcidSlimeM.LICK, AcidSlimeM.LICK)
    assert m.get_move_for_roll(bc, 85).name in {"Corrosive Spit", "Tackle"}


# ---- Spike Slime (M) ----


def test_spike_slime_m_lick_frail_and_flame_tackle():
    bc, m = solo_battle(SpikeSlimeM, seed=1, deck=[DEFEND, DEFEND])
    assert 28 <= m.hp <= 32
    force_intent(m, SpikeSlimeM.LICK)
    bc.end_turn()
    assert bc.player.statuses.get(PlayerStatus.FRAIL) == 1
    assert not bc.player.statuses.has(PlayerStatus.WEAK)  # 施加的是脆弱，不是虚弱
    # 脆弱：防御 5 → floor(5 × 0.75) = 3
    defend = next(i for i, c in enumerate(bc.cards.hand) if c.card.name == "Defend")
    bc.play_card(defend)
    assert bc.player.block == 3
    force_intent(m, SpikeSlimeM.FLAME_TACKLE)
    bc.end_turn()
    # 8 伤被防御的 3 格挡吸收 3 点
    assert bc.player.hp == PLAYER_MAX_HP - (8 - 3)
    assert _card_total(bc, "Slimed") == 1  # 烈焰冲撞塞 1 张黏液


def test_spike_slime_m_roll_segments():
    bc, m = solo_battle(SpikeSlimeM)
    set_history(m)  # 无历史
    assert m.get_move_for_roll(bc, 0).name == "Flame Tackle"
    assert m.get_move_for_roll(bc, 29).name == "Flame Tackle"
    assert m.get_move_for_roll(bc, 30).name == "Lick"
    assert m.get_move_for_roll(bc, 99).name == "Lick"
    # Flame Tackle 连续两回合：roll<30 强制 Lick
    set_history(m, SpikeSlimeM.FLAME_TACKLE, SpikeSlimeM.FLAME_TACKLE)
    assert m.get_move_for_roll(bc, 0).name == "Lick"
    # Lick 连续两回合：roll≥30 强制 Flame Tackle；只出一回合则仍可 Lick
    set_history(m, SpikeSlimeM.LICK, SpikeSlimeM.LICK)
    assert m.get_move_for_roll(bc, 50).name == "Flame Tackle"
    set_history(m, SpikeSlimeM.LICK)
    assert m.get_move_for_roll(bc, 99).name == "Lick"


# ---- Blue Slaver ----


def test_blue_slaver_rake_and_stab():
    bc, m = solo_battle(BlueSlaver)
    assert 46 <= m.hp <= 50
    force_intent(m, BlueSlaver.RAKE)
    bc.end_turn()
    assert bc.player.hp == PLAYER_MAX_HP - 7
    assert bc.player.statuses.get(PlayerStatus.WEAK) == 1
    force_intent(m, BlueSlaver.STAB)
    bc.end_turn()
    assert bc.player.hp == PLAYER_MAX_HP - 19  # 虚弱不减怪物造成的伤害
    assert bc.player.statuses.get(PlayerStatus.WEAK) == 0  # 首轮回合末不衰减、次轮归零


def test_blue_slaver_roll_segments():
    bc, m = solo_battle(BlueSlaver)
    set_history(m)  # 无历史（无首回合特例）
    assert m.get_move_for_roll(bc, 0).name == "Rake"
    assert m.get_move_for_roll(bc, 39).name == "Rake"
    assert m.get_move_for_roll(bc, 40).name == "Stab"
    assert m.get_move_for_roll(bc, 99).name == "Stab"
    # Stab 连续两回合：roll≥40 改出 Rake
    set_history(m, BlueSlaver.STAB, BlueSlaver.STAB)
    assert m.get_move_for_roll(bc, 40).name == "Rake"
    # Rake 连续两回合：roll<40 改出 Stab
    set_history(m, BlueSlaver.RAKE, BlueSlaver.RAKE)
    assert m.get_move_for_roll(bc, 0).name == "Stab"
    # Rake 只出一回合：roll<40 仍可 Rake
    set_history(m, BlueSlaver.RAKE)
    assert m.get_move_for_roll(bc, 10).name == "Rake"


# ---- Red Slaver ----


def test_red_slaver_first_move_stab():
    for seed in range(5):
        bc, m = solo_battle(RedSlaver, seed=seed)
        assert m.current_move.name == "Stab"  # lastMove(INVALID) → 首招固定刺击


def test_red_slaver_scrape_and_stab():
    bc, m = solo_battle(RedSlaver)
    assert 46 <= m.hp <= 50
    force_intent(m, RedSlaver.SCRAPE)
    bc.end_turn()
    assert bc.player.hp == PLAYER_MAX_HP - 8
    assert bc.player.statuses.get(PlayerStatus.VULNERABLE) == 1  # justApplied：当轮回合末不衰减
    force_intent(m, RedSlaver.STAB)
    bc.end_turn()
    # 刺击结算时玩家仍带易伤（衰减在全部怪物行动后才发生）：floor(13 × 1.5) = 19
    assert bc.player.hp == PLAYER_MAX_HP - 8 - 19
    assert bc.player.statuses.get(PlayerStatus.VULNERABLE) == 0  # 次轮回合末归零


def test_red_slaver_entangle_blocks_cards_and_is_once():
    bc, m = solo_battle(RedSlaver)
    force_intent(m, RedSlaver.ENTANGLE)
    bc.end_turn()
    assert bc.player.statuses.get(PlayerStatus.ENTANGLED) == 1
    assert m.misc_info == 1  # 已用标记（本体"整场一次"；lightspeed 漏写）
    card = next(i for i, c in enumerate(bc.cards.hand) if c.card.name == "Strike")
    with pytest.raises(ValueError, match="缠绕"):
        bc.play_card(card)  # 缠绕期间不能打出攻击牌（对齐本体：只拦攻击）
    defend = next(i for i, c in enumerate(bc.cards.hand) if c.card.name == "Defend")
    bc.play_card(defend)  # 技能牌不受缠绕限制
    bc.end_turn()  # 玩家空过一回合，回合末解除缠绕
    assert not bc.player.statuses.has(PlayerStatus.ENTANGLED)
    # 已用缠绕后：roll≥75 也不再出缠绕
    set_history(m, RedSlaver.SCRAPE)
    assert m.get_move_for_roll(bc, 99).name == "Stab"


def test_red_slaver_roll_segments():
    bc, m = solo_battle(RedSlaver)
    set_history(m)  # 无历史 → 首招固定 Stab（与 roll 无关）
    for roll in (0, 50, 99):
        assert m.get_move_for_roll(bc, roll).name == "Stab"
    set_history(m, RedSlaver.SCRAPE)
    assert m.get_move_for_roll(bc, 75).name == "Entangle"
    assert m.get_move_for_roll(bc, 74).name == "Scrape"
    assert m.get_move_for_roll(bc, 0).name == "Scrape"
    # 已用缠绕（misc_info=1）：roll≥50 且 Stab 未连续两回合 → Stab
    m.misc_info = 1
    set_history(m, RedSlaver.SCRAPE)
    assert m.get_move_for_roll(bc, 99).name == "Stab"
    assert m.get_move_for_roll(bc, 40).name == "Scrape"  # roll<50 走 Scrape 分支
    # Scrape 连续两回合被拦 → Stab
    set_history(m, RedSlaver.SCRAPE, RedSlaver.SCRAPE)
    assert m.get_move_for_roll(bc, 10).name == "Stab"
    # Stab 连续两回合 + 已用缠绕 → 回落 Scrape
    set_history(m, RedSlaver.STAB, RedSlaver.STAB)
    assert m.get_move_for_roll(bc, 99).name == "Scrape"


# ---- Sneaky Gremlin ----


def test_sneaky_gremlin_fixed_puncture():
    bc, m = solo_battle(SneakyGremlin)
    assert 10 <= m.hp <= 14
    assert m.current_move.name == "Puncture"
    bc.end_turn()
    assert bc.player.hp == PLAYER_MAX_HP - 9
    assert m.current_move.name == "Puncture"  # 无 roll：意图恒为穿刺
    bc.end_turn()
    assert bc.player.hp == PLAYER_MAX_HP - 18
    assert m.current_move.name == "Puncture"


# ---- Fat Gremlin ----


def test_fat_gremlin_smash_weak():
    bc, m = solo_battle(FatGremlin)
    assert 13 <= m.hp <= 17
    assert m.current_move.name == "Smash"
    bc.end_turn()
    assert bc.player.hp == PLAYER_MAX_HP - 4
    assert bc.player.statuses.get(PlayerStatus.WEAK) == 1
    assert m.current_move.name == "Smash"
    # 每回合重击都重施加虚弱（isSourceMonster=True 恒置 justApplied，
    # 对齐 lightspeed：衰减每轮都被跳过 → 层数逐回合累积为 2）
    bc.end_turn()
    assert bc.player.hp == PLAYER_MAX_HP - 8
    assert bc.player.statuses.get(PlayerStatus.WEAK) == 2
    assert m.current_move.name == "Smash"


def test_fat_gremlin_a17_adds_frail():
    bc, m = solo_battle(FatGremlin, ascension=17)
    bc.end_turn()
    assert bc.player.statuses.get(PlayerStatus.WEAK) == 1
    assert bc.player.statuses.get(PlayerStatus.FRAIL) == 1  # A17 追加脆弱


# ---- Shield Gremlin ----


def test_shield_gremlin_protect_random_ally():
    bc = BattleContext(seed=2, encounter="gremlin_gang")
    # 本批固定顺序：[Sneaky, Fat, Shield, Wizard]，盾牌小鬼在 idx 2
    shield = bc.monsters.monsters[2]
    assert isinstance(shield, ShieldGremlin)
    others = [bc.monsters.monsters[0], bc.monsters.monsters[1], bc.monsters.monsters[3]]
    bc.end_turn()
    # 恰好一只存活友军获得 7 格挡（misc 流随机），盾牌小鬼自己没有
    assert sum(m.block for m in others) == 7
    assert shield.block == 0
    assert shield.current_move.name == "Protect"  # 有友军时不切盾击


def test_shield_gremlin_alone_switches_to_shield_bash():
    bc = BattleContext(seed=3, encounter="gremlin_gang")
    shield = bc.monsters.monsters[2]
    for i in (0, 1, 3):
        slay(bc, i)
    assert bc.monsters.alive_count == 1
    assert shield.current_move.name == "Protect"
    bc.end_turn()
    assert shield.block == 7  # 无存活友军 → 格挡给自己
    assert shield.current_move.name == "Shield Bash"
    bc.end_turn()
    assert bc.player.hp == PLAYER_MAX_HP - 6
    assert shield.current_move.name == "Shield Bash"  # 之后保持盾击


# ---- Gremlin Wizard ----


def test_gremlin_wizard_charge_blast_cycle():
    bc, m = solo_battle(GremlinWizard)
    assert 21 <= m.hp <= 25
    assert m.current_move.name == "Charging"
    # 首轮充 2 回合后冲击；重充后每轮充 3 回合（充能计数挂 misc_info）
    expected_hp = [
        PLAYER_MAX_HP, PLAYER_MAX_HP, PLAYER_MAX_HP - 25,
        PLAYER_MAX_HP - 25, PLAYER_MAX_HP - 25, PLAYER_MAX_HP - 25,
        PLAYER_MAX_HP - 50,
    ]
    expected_moves = [
        "Charging", "Ultimate Blast", "Charging", "Charging",
        "Charging", "Ultimate Blast", "Charging",
    ]
    for hp, mv in zip(expected_hp, expected_moves):
        bc.end_turn()
        assert bc.player.hp == hp
        assert m.current_move.name == mv


def test_gremlin_wizard_a17_never_recharges():
    bc, m = solo_battle(GremlinWizard, ascension=17)
    for _ in range(2):
        bc.end_turn()  # 充能两回合
    assert m.current_move.name == "Ultimate Blast"
    bc.end_turn()
    # A17 同时满足 A2：终极冲击 30 伤
    assert bc.player.hp == PLAYER_MAX_HP - 30
    assert m.current_move.name == "Ultimate Blast"  # A17 冲击后不重充
    bc.end_turn()
    assert bc.player.hp == PLAYER_MAX_HP - 60


# ---- Sentry ----


def test_sentry_artifact_blocks_debuff():
    bc, m = solo_battle(Sentry, deck=[BASH])
    assert m.statuses.get(MonsterStatus.ARTIFACT) == 1
    bash = next(i for i, c in enumerate(bc.cards.hand) if c.card.name == "Bash")
    bc.play_card(bash, target=0)
    # 人工制品消耗 1 层抵消易伤
    assert m.statuses.get(MonsterStatus.ARTIFACT) == 0
    assert not m.statuses.has(MonsterStatus.VULNERABLE)


def test_sentry_beam_bolt_alternation():
    bc, m = solo_battle(Sentry)
    assert 38 <= m.hp <= 42
    assert m.current_move.name == "Bolt"  # idx 0（偶数槽位）先 Bolt
    bc.end_turn()
    assert _card_total(bc, "Dazed") == 2
    assert bc.player.hp == PLAYER_MAX_HP  # Bolt 无伤害
    assert m.current_move.name == "Beam"
    bc.end_turn()
    assert bc.player.hp == PLAYER_MAX_HP - 9
    assert m.current_move.name == "Bolt"
    bc.end_turn()
    assert _card_total(bc, "Dazed") == 4


def test_sentry_a18_three_dazed_and_high_hp():
    bc, m = solo_battle(Sentry, seed=0, ascension=18)
    assert 39 <= m.hp <= 45  # A8 起高位 HP 区间
    force_intent(m, Sentry.BOLT)
    bc.end_turn()
    assert _card_total(bc, "Dazed") == 3  # A18 起 Bolt 塞 3 张眩晕


# ---- 进阶分支（A0 之外的取值读 bc.ascension）----


def test_ascension_hp_and_damage_branches():
    # A7 起酸史（中）用高位 HP 区间
    for seed in range(10):
        bc, m = solo_battle(AcidSlimeM, seed=seed, ascension=7)
        assert 29 <= m.hp <= 34
    # A2 起腐蚀唾液 8 伤
    bc, m = solo_battle(AcidSlimeM, ascension=2)
    force_intent(m, AcidSlimeM.CORROSIVE_SPIT)
    bc.end_turn()
    assert bc.player.hp == PLAYER_MAX_HP - 8

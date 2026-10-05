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
from sts.content.cards import BASH, BLUDGEON, DEFEND, STRIKE
from sts.content.monsters import (
    AcidSlimeL,
    AcidSlimeM,
    AcidSlimeS,
    BlueSlaver,
    BookOfStabbing,
    BronzeAutomaton,
    BronzeOrb,
    Byrd,
    Centurion,
    Chosen,
    FatGremlin,
    FungiBeast,
    GremlinLeader,
    GremlinNob,
    GreenLouse,
    GremlinWizard,
    Hexaghost,
    JawWorm,
    Lagavulin,
    Looter,
    MadGremlin,
    Mugger,
    Mystic,
    RedLouse,
    RedSlaver,
    Sentry,
    ShelledParasite,
    ShieldGremlin,
    SlimeBoss,
    SneakyGremlin,
    Snecko,
    SnakePlant,
    SpikeSlimeL,
    SpikeSlimeM,
    SpikeSlimeS,
    SphericGuardian,
    Taskmaster,
    TheChamp,
    TheCollector,
    TheGuardian,
    TorchHead,
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


def test_gremlin_gang_sampling_composition():
    """批次 2 起 Mad Gremlin 入池：8 槽无放回抽 4，重数不超池内份数。"""
    from collections import Counter

    pool_cap = {
        "MadGremlin": 2,
        "SneakyGremlin": 2,
        "FatGremlin": 2,
        "ShieldGremlin": 1,
        "GremlinWizard": 1,
    }
    comps = set()
    for seed in range(60):
        comp = _composition("gremlin_gang", seed)
        assert len(comp) == 4
        assert comp == _composition("gremlin_gang", seed)  # 同种子可复现
        cnt = Counter(comp)
        for name, n in cnt.items():
            assert name in pool_cap
            assert n <= pool_cap[name]
        comps.add(tuple(comp))
    # 抽样确实生效：组合多样，且 Mad Gremlin 有机会出现
    assert len(comps) > 10
    assert any("MadGremlin" in c for c in comps)


def test_slavers_composition():
    """对齐 C++ SLAVERS：蓝奴役者 + 监工 + 红奴役者（监工在中间位）。"""
    for seed in range(10):
        comp = _composition("slavers", seed)
        assert comp == ["BlueSlaver", "Taskmaster", "RedSlaver"]
        bc = BattleContext(seed=seed, encounter="slavers")
        assert isinstance(bc.monsters.monsters[1], Taskmaster)
        assert bc.monsters.monsters[1].current_move.name == "Scouring Whip"
        assert bc.monsters.monsters[2].current_move.name == "Stab"  # 红奴役者首招恒为刺击


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


def staged_battle(seed: int, classes, ascension: int = 0, deck=None):
    """自定义怪物组的隔离战斗（gremlin_gang 已改抽样， Shield Gremlin 测试
    用固定组合取代旧的无抽样路径；等价 solo_battle 的多怪版）。"""
    bc = BattleContext(seed=seed, encounter="cultist", ascension=ascension, deck=deck)
    bc.monsters.monsters = [cls.create(bc, i) for i, cls in enumerate(classes)]
    bc.monsters.alive_count = len(classes)
    for m in bc.monsters.monsters:
        m.roll_move(bc)
    return bc


def test_shield_gremlin_protect_random_ally():
    bc = staged_battle(2, [SneakyGremlin, FatGremlin, ShieldGremlin, GremlinWizard])
    shield = bc.monsters.monsters[2]
    assert isinstance(shield, ShieldGremlin)
    others = [bc.monsters.monsters[0], bc.monsters.monsters[1], bc.monsters.monsters[3]]
    bc.end_turn()
    # 恰好一只存活友军获得 7 格挡（misc 流随机），盾牌小鬼自己没有
    assert sum(m.block for m in others) == 7
    assert shield.block == 0
    assert shield.current_move.name == "Protect"  # 有友军时不切盾击


def test_shield_gremlin_alone_switches_to_shield_bash():
    bc = staged_battle(3, [SneakyGremlin, FatGremlin, ShieldGremlin, GremlinWizard])
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


# ====================================================================
# 批次 2：中等档 Act 1 怪物（Mad Gremlin、Gremlin Nob、Lagavulin、
# The Guardian、Hexaghost、Taskmaster）+ 精英/Boss 遭遇注册。
# ====================================================================


BATCH2_ENCOUNTERS = [
    ("gremlin_nob", 1, 82, 86),
    ("lagavulin", 1, 109, 111),
    ("guardian", 1, 240, 240),
    ("hexaghost", 1, 250, 250),
    ("slavers", 3, 46, 60),  # 蓝/红奴役者 46-50，监工 54-60
]


@pytest.mark.parametrize("encounter,count,hp_lo,hp_hi", BATCH2_ENCOUNTERS)
def test_batch2_encounter_spawn_and_hp_range(encounter, count, hp_lo, hp_hi):
    for seed in range(10):
        bc = BattleContext(seed=seed, encounter=encounter)
        assert bc.monsters.monster_count == count
        for m in bc.monsters.monsters:
            assert hp_lo <= m.hp <= hp_hi
            assert m.max_hp == m.hp
            assert m.current_move is not None
        assert len(bc.cards.draw_pile) + len(bc.cards.hand) == 10


def test_batch2_encounter_types():
    bc = BattleContext(seed=0, encounter="gremlin_nob")
    assert isinstance(bc.monsters.monsters[0], GremlinNob)
    bc = BattleContext(seed=0, encounter="lagavulin")
    assert isinstance(bc.monsters.monsters[0], Lagavulin)
    bc = BattleContext(seed=0, encounter="guardian")
    assert isinstance(bc.monsters.monsters[0], TheGuardian)
    bc = BattleContext(seed=0, encounter="hexaghost")
    assert isinstance(bc.monsters.monsters[0], Hexaghost)


def test_batch2_ascension_hp_ranges():
    """精英 A8 / Boss A9 起用高位 HP 区间（对齐 C++ initHp 分桶）。"""
    for seed in range(10):
        bc = BattleContext(seed=seed, encounter="gremlin_nob", ascension=8)
        assert 85 <= bc.monsters.monsters[0].hp <= 90
        bc = BattleContext(seed=seed, encounter="lagavulin", ascension=8)
        assert 112 <= bc.monsters.monsters[0].hp <= 115
        bc = BattleContext(seed=seed, encounter="guardian", ascension=9)
        assert bc.monsters.monsters[0].hp == 250
        bc = BattleContext(seed=seed, encounter="hexaghost", ascension=9)
        assert bc.monsters.monsters[0].hp == 264
        # slavers A8：监工 57-64，红蓝奴役者 48-52
        bc = BattleContext(seed=seed, encounter="slavers", ascension=8)
        assert 57 <= bc.monsters.monsters[1].hp <= 64
        for i in (0, 2):
            assert 48 <= bc.monsters.monsters[i].hp <= 52


# ---- Mad Gremlin ----


def test_mad_gremlin_scratch_and_angry():
    """固定抓挠 4 伤；受击 ANGRY → +1 力量，下一抓挠 5 伤。"""
    bc, m = solo_battle(MadGremlin)
    assert 20 <= m.hp <= 24
    assert m.statuses.get(MonsterStatus.ANGRY) == 1
    assert m.current_move.name == "Scratch"
    bc.end_turn()
    assert bc.player.hp == PLAYER_MAX_HP - 4
    assert m.current_move.name == "Scratch"  # 无 roll：意图恒为抓挠
    play_strike(bc, target=0)
    assert m.statuses.get(MonsterStatus.STRENGTH) == 1  # ANGRY×1
    bc.end_turn()
    assert bc.player.hp == PLAYER_MAX_HP - 4 - 5
    play_strike(bc, target=0)
    assert m.statuses.get(MonsterStatus.STRENGTH) == 2  # 再次受击继续涨


def test_mad_gremlin_ascension_branches():
    for seed in range(10):
        bc, m = solo_battle(MadGremlin, seed=seed, ascension=7)
        assert 21 <= m.hp <= 25  # A7 起高位 HP
    bc, m = solo_battle(MadGremlin, ascension=17)
    assert m.statuses.get(MonsterStatus.ANGRY) == 2  # A17 起两层愤怒
    bc.end_turn()
    assert bc.player.hp == PLAYER_MAX_HP - 5  # A17 同时满足 A2：抓挠 5 伤
    bc, m = solo_battle(MadGremlin, ascension=2)
    bc.end_turn()
    assert bc.player.hp == PLAYER_MAX_HP - 5  # A2 起抓挠 5 伤


# ---- Gremlin Nob ----


def test_gremlin_nob_bellow_enrage():
    """首回合固定怒吼（激怒 2，无格挡）；玩家打技能牌 +2 力量/张，攻击牌不触发。"""
    bc, m = solo_battle(GremlinNob, deck=[DEFEND, DEFEND, STRIKE])
    assert 82 <= m.hp <= 86
    assert m.current_move.name == "Bellow"
    bc.end_turn()
    assert m.statuses.get(MonsterStatus.ENRAGE) == 2
    assert m.block == 0  # Bellow 无格挡（对齐 C++）
    assert bc.player.hp == PLAYER_MAX_HP
    # 打出技能牌 → Nob +2 力量/张（引擎 on_use_skill_card 的 ENRAGE 钩子）
    for expected_str in (2, 4):
        defend = next(i for i, c in enumerate(bc.cards.hand) if c.card.name == "Defend")
        bc.play_card(defend)
        assert m.statuses.get(MonsterStatus.STRENGTH) == expected_str
    # 打出攻击牌不触发 ENRAGE
    play_strike(bc, target=0)
    assert m.statuses.get(MonsterStatus.STRENGTH) == 4


def test_gremlin_nob_rush_and_skull_bash():
    """Rush 14 伤；Skull Bash 6 伤 + 2 层易伤（A3 起 16/8）。"""
    bc, m = solo_battle(GremlinNob)
    force_intent(m, GremlinNob.RUSH)
    bc.end_turn()
    assert bc.player.hp == PLAYER_MAX_HP - 14
    force_intent(m, GremlinNob.SKULL_BASH)
    bc.end_turn()
    assert bc.player.hp == PLAYER_MAX_HP - 14 - 6
    assert bc.player.statuses.get(PlayerStatus.VULNERABLE) == 2
    # 怪物施加→justApplied：施加轮回合末跳过衰减（仍为 2），此后每轮 -1
    force_intent(m, GremlinNob.RUSH)
    bc.end_turn()  # 本轮起正常衰减（Rush 被易伤放大，不在断言范围）
    assert bc.player.statuses.get(PlayerStatus.VULNERABLE) == 1
    force_intent(m, GremlinNob.RUSH)
    bc.end_turn()
    assert not bc.player.statuses.has(PlayerStatus.VULNERABLE)
    # A3：Rush 16 / Skull Bash 8（易伤仍为 2）
    bc, m = solo_battle(GremlinNob, ascension=3)
    force_intent(m, GremlinNob.RUSH)
    bc.end_turn()
    assert bc.player.hp == PLAYER_MAX_HP - 16
    force_intent(m, GremlinNob.SKULL_BASH)
    bc.end_turn()
    assert bc.player.hp == PLAYER_MAX_HP - 16 - 8
    assert bc.player.statuses.get(PlayerStatus.VULNERABLE) == 2


def test_gremlin_nob_roll_segments():
    """首回合固定 Bellow；A0 分段 33/67 + Rush 连续两回合强制 Skull Bash。"""
    bc, m = solo_battle(GremlinNob)
    set_history(m)  # 无历史 → 首回合 Bellow（与 roll 无关）
    for roll in (0, 50, 99):
        assert m.get_move_for_roll(bc, roll).name == "Bellow"
    set_history(m, GremlinNob.RUSH)
    assert m.get_move_for_roll(bc, 0).name == "Skull Bash"
    assert m.get_move_for_roll(bc, 32).name == "Skull Bash"
    assert m.get_move_for_roll(bc, 33).name == "Rush"
    assert m.get_move_for_roll(bc, 99).name == "Rush"
    # Rush 连续两回合：任意 roll 强制 Skull Bash
    set_history(m, GremlinNob.RUSH, GremlinNob.RUSH)
    assert m.get_move_for_roll(bc, 0).name == "Skull Bash"
    assert m.get_move_for_roll(bc, 99).name == "Skull Bash"
    # 上回合 Skull Bash：不影响 33/67 分段
    set_history(m, GremlinNob.SKULL_BASH)
    assert m.get_move_for_roll(bc, 32).name == "Skull Bash"
    assert m.get_move_for_roll(bc, 33).name == "Rush"


def test_gremlin_nob_a18_rush_only():
    """A18 分支逐行翻译：Skull Bash 不可达（lightspeed 疑似笔误，按字面保留）。"""
    bc, m = solo_battle(GremlinNob, ascension=18)
    assert m.current_move.name == "Bellow"
    for history in (
        (GremlinNob.RUSH,),
        (GremlinNob.SKULL_BASH,),
        (GremlinNob.RUSH, GremlinNob.RUSH),
        (GremlinNob.SKULL_BASH, GremlinNob.SKULL_BASH),
        (GremlinNob.RUSH, GremlinNob.SKULL_BASH),
    ):
        set_history(m, *history)
        for roll in (0, 33, 50, 99):
            assert m.get_move_for_roll(bc, roll).name == "Rush"
    # A18 的 Bellow 激怒为 3 层（重开一局走执行路径）
    bc, m = solo_battle(GremlinNob, ascension=18)
    bc.end_turn()
    assert m.statuses.get(MonsterStatus.ENRAGE) == 3


# ---- Lagavulin ----


def test_lagavulin_initial_state_and_natural_wake():
    """开局沉睡（金属化 8 + 8 格挡）；3 回合自然醒，保留金属化。"""
    bc, m = solo_battle(Lagavulin)
    assert 109 <= m.hp <= 111
    assert m.statuses.get(MonsterStatus.ASLEEP) == 1
    assert m.statuses.get(MonsterStatus.METALLICIZE) == 8
    assert m.block == 8
    assert m.current_move.name == "Sleep"
    for round_ in (1, 2):
        bc.end_turn()
        assert m.current_move.name == "Sleep"
        assert m.block == 8  # 回合开始清零后金属化补回 8
        assert bc.player.hp == PLAYER_MAX_HP
    bc.end_turn()  # 第 3 回合：自然醒 → 下一回合攻击
    assert m.current_move.name == "Attack"
    # 本体语义：自然醒移除 Asleep 且金属化常驻（C++ 漏移除，见类注释）
    assert not m.statuses.has(MonsterStatus.ASLEEP)
    assert m.statuses.get(MonsterStatus.METALLICIZE) == 8
    bc.end_turn()  # 第 4 回合：攻击 18
    assert bc.player.hp == PLAYER_MAX_HP - 18
    # 醒后受击：金属化 8 仍在（格挡吸收），不再被剥除
    hp0 = m.hp
    play_strike(bc, target=0)
    assert m.hp == hp0  # 6 伤全被金属化格挡吸收
    assert m.statuses.get(MonsterStatus.METALLICIZE) == 8


def test_lagavulin_sequence_and_siphon_soul():
    """醒后循环：攻-攻-汲取灵魂；汲取 -1 力量 -1 敏捷（A18 起 -2）。"""
    bc, m = solo_battle(Lagavulin)
    for _ in range(3):
        bc.end_turn()  # r1-r3 沉睡，r3 末自然醒
    assert m.current_move.name == "Attack"
    bc.end_turn()  # r4 攻击
    assert bc.player.hp == PLAYER_MAX_HP - 18
    assert m.current_move.name == "Attack"  # 上回合是沉睡 → 继续攻击
    bc.end_turn()  # r5 攻击（攻-攻连续）
    assert bc.player.hp == PLAYER_MAX_HP - 36
    assert m.current_move.name == "Siphon Soul"
    bc.end_turn()  # r6 汲取灵魂
    assert bc.player.hp == PLAYER_MAX_HP - 36  # 汲取无伤害
    assert bc.player.statuses.get(PlayerStatus.STRENGTH) == -1
    assert bc.player.statuses.get(PlayerStatus.DEXTERITY) == -1
    assert m.current_move.name == "Attack"  # 汲取后回攻击（循环重启）
    bc.end_turn()  # r7 攻击（玩家 -1 力量不影响怪物出伤）
    assert bc.player.hp == PLAYER_MAX_HP - 54
    # A18：攻击 20（A18 ⊇ A3），汲取 -2/-2
    bc, m = solo_battle(Lagavulin, ascension=18)
    for _ in range(6):
        bc.end_turn()  # r1-r3 睡、r4-r5 攻、r6 汲取
    assert bc.player.hp == PLAYER_MAX_HP - 40
    assert bc.player.statuses.get(PlayerStatus.STRENGTH) == -2
    assert bc.player.statuses.get(PlayerStatus.DEXTERITY) == -2


def test_lagavulin_damage_wake_strips_metallicize():
    """打醒：漏格挡伤害即醒并移除金属化；当回合仍空转（stunned），下回合才攻击。"""
    bc, m = solo_battle(Lagavulin, deck=[BLUDGEON])
    hp0 = m.hp
    bludgeon = next(i for i, c in enumerate(bc.cards.hand) if c.card.name == "Bludgeon")
    bc.play_card(bludgeon, target=0)
    # 32 伤：8 格挡吸收 → 24 漏过 → 醒 + 剥金属化
    assert m.hp == hp0 - 24
    assert not m.statuses.has(MonsterStatus.ASLEEP)
    assert not m.statuses.has(MonsterStatus.METALLICIZE)
    assert m.current_move.name == "Sleep"  # 意图仍是沉睡（当回合行动时切换）
    assert bc.player.hp == PLAYER_MAX_HP
    bc.end_turn()  # Sleep 分支：已醒 → 切攻击，本回合不攻击
    assert m.current_move.name == "Attack"
    assert bc.player.hp == PLAYER_MAX_HP
    bc.end_turn()  # 攻击 18；金属化已剥 → 无格挡
    assert bc.player.hp == PLAYER_MAX_HP - 18
    assert m.block == 0


def test_lagavulin_small_hit_fully_absorbed_does_not_wake():
    """开局 8 格挡完全吸收的伤害不唤醒（漏格挡才醒）。"""
    bc, m = solo_battle(Lagavulin)
    hp0 = m.hp
    play_strike(bc, target=0)  # 6 伤 < 8 格挡
    assert m.hp == hp0
    assert m.block == 2
    assert m.statuses.has(MonsterStatus.ASLEEP)
    assert m.statuses.get(MonsterStatus.METALLICIZE) == 8


# ---- The Guardian ----


def test_guardian_initial_and_attack_mode_cycle():
    """开局阈值 30 / 意图蓄能；攻击模式循环：蓄能→猛烈重击→排放蒸汽→旋风。"""
    bc, m = solo_battle(TheGuardian)
    assert m.hp == 240
    assert m.misc_info == 30
    assert m.statuses.get(MonsterStatus.MODE_SHIFT) == 30
    assert m.current_move.name == "Charging Up"
    bc.end_turn()  # r1 蓄能：+9 格挡
    assert m.block == 9
    assert m.current_move.name == "Fierce Bash"
    bc.end_turn()  # r2 猛烈重击 32
    assert bc.player.hp == PLAYER_MAX_HP - 32
    assert m.current_move.name == "Vent Steam"
    bc.end_turn()  # r3 排放蒸汽：2 易伤 + 2 虚弱
    assert bc.player.statuses.get(PlayerStatus.VULNERABLE) == 2
    assert bc.player.statuses.get(PlayerStatus.WEAK) == 2
    assert m.current_move.name == "Whirlwind"
    bc.end_turn()  # r4 旋风：玩家带 2 层易伤 → floor(5×1.5)=7/段 ×4 = 28
    assert bc.player.hp == PLAYER_MAX_HP - 32 - 28
    assert m.current_move.name == "Charging Up"  # 回到循环起点


def test_guardian_mode_shift_full_chain():
    """全链路：打够阈值→防御模式（+20 格挡、强改意图）→利爪隐蔽反伤→
    滚动攻击→双重猛击（阈值 +10、重设 MODE_SHIFT）→回攻击模式。"""
    bc, m = solo_battle(TheGuardian, deck=[BLUDGEON, STRIKE, DEFEND])
    # 玩家回合 1：重击 32 > 阈值 30 → 立即切防御模式
    bludgeon = next(i for i, c in enumerate(bc.cards.hand) if c.card.name == "Bludgeon")
    bc.play_card(bludgeon, target=0)
    assert m.hp == 240 - 32
    assert m.block == 20  # 切模式 +20 格挡入队落地
    assert m.current_move.name == "Defensive Mode"  # 意图被强改
    assert not m.statuses.has(MonsterStatus.MODE_SHIFT)
    bc.end_turn()  # 防御模式回合：利爪隐蔽 3（20 格挡在其回合开始时清零）
    assert m.statuses.get(MonsterStatus.SHARP_HIDE) == 3
    assert m.current_move.name == "Roll Attack"
    # 玩家回合 2：打攻击牌吃 3 点反伤；打技能牌不触发
    play_strike(bc, target=0)
    assert m.hp == 240 - 32 - 6
    assert bc.player.hp == PLAYER_MAX_HP - 3
    defend = next(i for i, c in enumerate(bc.cards.hand) if c.card.name == "Defend")
    bc.play_card(defend)
    assert bc.player.hp == PLAYER_MAX_HP - 3  # 技能牌无反伤
    bc.end_turn()  # 滚动攻击 9（玩家 5 格挡吸收 5）
    assert bc.player.hp == PLAYER_MAX_HP - 3 - (9 - 5)
    assert m.current_move.name == "Twin Slam"
    bc.end_turn()  # 双重猛击 8×2 = 16
    assert bc.player.hp == PLAYER_MAX_HP - 3 - 4 - 16
    assert not m.statuses.has(MonsterStatus.SHARP_HIDE)  # 利爪隐蔽移除
    assert m.misc_info == 40  # 阈值 +10
    assert m.statuses.get(MonsterStatus.MODE_SHIFT) == 40  # 重设
    assert m.current_move.name == "Whirlwind"  # 回攻击模式（跳过蓄能）
    bc.end_turn()  # 旋风 5×4 = 20
    assert bc.player.hp == PLAYER_MAX_HP - 43
    assert m.current_move.name == "Charging Up"
    bc.end_turn()  # 蓄能 +9
    assert m.block == 9
    assert m.current_move.name == "Fierce Bash"


def test_guardian_mode_shift_accumulation_and_defensive_damage():
    """阈值按漏格挡伤害累积扣减；恰好归零也切换；防御模式期间伤害不再累积。"""
    bc, m = solo_battle(TheGuardian)
    m.damage(bc, 29)
    assert m.statuses.get(MonsterStatus.MODE_SHIFT) == 1
    assert m.current_move.name == "Charging Up"  # 未到阈值：意图不变
    m.damage(bc, 1)  # 恰好归零（对齐 C++ <= 0）
    assert m.current_move.name == "Defensive Mode"
    # +20 格挡为入队动作（对齐 C++ addToBot），直接调用时手动出队结算
    while not bc.action_queue.is_empty():
        bc.action_queue.pop_front().fn(bc)
    assert m.block == 20
    assert not m.statuses.has(MonsterStatus.MODE_SHIFT)
    # 防御模式期间（双重猛击重设前）伤害不再累积：意图不再强改
    m.damage(bc, 25)  # 20 格挡吸收 → 5 漏过
    assert m.current_move.name == "Defensive Mode"
    assert m.block == 0
    assert m.hp == 240 - 29 - 1 - 5
    # 超额一击直接切换（余额不结转）
    bc, m = solo_battle(TheGuardian)
    m.damage(bc, 40)
    assert m.current_move.name == "Defensive Mode"


def test_guardian_ascension_branches():
    """A9 阈值 35 / HP 250；A19 阈值 40、利爪隐蔽 4。"""
    bc, m = solo_battle(TheGuardian, ascension=9)
    assert m.hp == 250
    assert m.misc_info == 35
    assert m.statuses.get(MonsterStatus.MODE_SHIFT) == 35
    bc, m = solo_battle(TheGuardian, ascension=19)
    assert m.hp == 250
    assert m.misc_info == 40
    m.damage(bc, 40)
    assert m.current_move.name == "Defensive Mode"
    bc.end_turn()
    assert m.statuses.get(MonsterStatus.SHARP_HIDE) == 4
    # A4 起：猛烈重击 36 / 滚动攻击 10
    bc, m = solo_battle(TheGuardian, ascension=4)
    force_intent(m, TheGuardian.FIERCE_BASH)
    bc.end_turn()
    assert bc.player.hp == PLAYER_MAX_HP - 36
    force_intent(m, TheGuardian.ROLL_ATTACK)
    bc.end_turn()
    assert bc.player.hp == PLAYER_MAX_HP - 36 - 10


# ---- Hexaghost ----


def test_hexaghost_activate_and_divider():
    """激活锁定分割伤害 = 玩家HP//12+1；分割 ×6 段。"""
    bc, m = solo_battle(Hexaghost)
    assert m.hp == 250
    assert m.current_move.name == "Activate"
    assert m.misc_info == 0
    bc.end_turn()  # r1 激活：80 // 12 + 1 = 7
    assert m.misc_info == 7
    assert m.current_move.name == "Divider"
    bc.end_turn()  # r2 分割 7×6 = 42
    assert bc.player.hp == PLAYER_MAX_HP - 42
    assert m.current_move.name == "Sear"
    # 分割伤害随玩家当前 HP 变化
    bc, m = solo_battle(Hexaghost, seed=1)
    bc.player.hp = 13
    bc.end_turn()
    assert m.misc_info == 2  # 13 // 12 + 1


def test_hexaghost_cycle_and_burn_upgrade():
    """火球轮转：灼烧-冲撞-灼烧-燃焰-冲撞-灼烧-炼狱；灼伤第 10 回合起升级。

    用 50 张防御的大牌组避免洗牌（防止灼伤被抽进手触发回合末自伤，
    保持逐回合伤害断言确定）。
    """
    bc, m = solo_battle(Hexaghost, deck=[DEFEND] * 50)
    bc.end_turn()  # r1 激活（misc 7）
    assert bc.player.hp == PLAYER_MAX_HP
    bc.end_turn()  # r2 分割 42
    assert bc.player.hp == PLAYER_MAX_HP - 42
    bc.player.hp = PLAYER_MAX_HP  # 测试续命，后续按 80 重算
    bc.end_turn()  # r3 灼烧 6 + 1 张灼伤
    assert bc.player.hp == PLAYER_MAX_HP - 6
    assert _card_total(bc, "Burn") == 1
    assert not any(c.upgraded for c in bc.cards.discard_pile if c.card.name == "Burn")
    assert m.current_move.name == "Tackle"
    bc.end_turn()  # r4 冲撞 5×2
    assert bc.player.hp == PLAYER_MAX_HP - 16
    assert m.current_move.name == "Sear"
    bc.end_turn()  # r5 灼烧 6 + 灼伤
    assert bc.player.hp == PLAYER_MAX_HP - 22
    assert _card_total(bc, "Burn") == 2
    assert m.current_move.name == "Inflame"
    bc.end_turn()  # r6 燃焰：+12 格挡、力量 +2
    assert bc.player.hp == PLAYER_MAX_HP - 22
    assert m.block == 12
    assert m.statuses.get(MonsterStatus.STRENGTH) == 2
    assert m.current_move.name == "Tackle"
    bc.end_turn()  # r7 冲撞 (5+2)×2 = 14
    assert bc.player.hp == PLAYER_MAX_HP - 36
    assert m.current_move.name == "Sear"
    bc.end_turn()  # r8 灼烧 6+2 = 8 + 灼伤（第 8 回合未到升级线）
    assert bc.player.hp == PLAYER_MAX_HP - 44
    assert _card_total(bc, "Burn") == 3
    assert not any(
        c.upgraded
        for z in (bc.cards.hand, bc.cards.draw_pile, bc.cards.discard_pile, bc.cards.exhaust_pile)
        for c in z
        if c.card.name == "Burn"
    )
    assert m.current_move.name == "Inferno"
    bc.end_turn()  # r9 炼狱 (2+2)×6 = 24
    assert bc.player.hp == PLAYER_MAX_HP - 68
    assert m.unique_power0 == 0  # 火球计数清零，循环重启
    assert m.current_move.name == "Sear"
    bc.end_turn()  # r10 灼烧 8 + 升级灼伤（bc.turn > 9，对齐 C++ turn > 8）
    assert bc.player.hp == PLAYER_MAX_HP - 76
    assert _card_total(bc, "Burn") == 4
    assert sum(
        c.upgraded
        for z in (bc.cards.hand, bc.cards.draw_pile, bc.cards.discard_pile, bc.cards.exhaust_pile)
        for c in z
        if c.card.name == "Burn"
    ) == 1
    assert m.current_move.name == "Tackle"


def test_hexaghost_ascension_branches():
    """A4 起冲撞 6×2、炼狱 3×6；A19 起灼烧塞 2 张灼伤（分割/灼烧伤害不变）。"""
    bc, m = solo_battle(Hexaghost, ascension=4)
    force_intent(m, Hexaghost.TACKLE)
    bc.end_turn()
    assert bc.player.hp == PLAYER_MAX_HP - 12
    force_intent(m, Hexaghost.INFERNO)
    bc.end_turn()
    assert bc.player.hp == PLAYER_MAX_HP - 12 - 18
    bc, m = solo_battle(Hexaghost, ascension=19)
    force_intent(m, Hexaghost.SEAR)
    bc.end_turn()
    assert bc.player.hp == PLAYER_MAX_HP - 6  # 灼烧伤害恒 6（无进阶加成）
    assert _card_total(bc, "Burn") == 2


# ---- Taskmaster ----


def test_taskmaster_scouring_whip():
    """固定鞭挞 7 伤 + 塞 1 张伤口；A3 起 2 张；A18 起 3 张且自身力量 +1。"""
    bc, m = solo_battle(Taskmaster)
    assert 54 <= m.hp <= 60
    assert m.current_move.name == "Scouring Whip"
    bc.end_turn()
    assert bc.player.hp == PLAYER_MAX_HP - 7  # 伤害恒 7（无 A2 加成，wiki 同）
    assert _card_total(bc, "Wound") == 1
    bc.end_turn()
    assert bc.player.hp == PLAYER_MAX_HP - 14
    assert _card_total(bc, "Wound") == 2
    # A3：每次塞 2 张
    bc, m = solo_battle(Taskmaster, ascension=3)
    bc.end_turn()
    assert _card_total(bc, "Wound") == 2
    # A18：每次塞 3 张 + 自身力量 +1 → 下一鞭 8 伤
    bc, m = solo_battle(Taskmaster, ascension=18)
    bc.end_turn()
    assert bc.player.hp == PLAYER_MAX_HP - 7
    assert _card_total(bc, "Wound") == 3
    assert m.statuses.get(MonsterStatus.STRENGTH) == 1
    bc.end_turn()
    assert bc.player.hp == PLAYER_MAX_HP - 7 - 8
    assert _card_total(bc, "Wound") == 6


# ====================================================================
# 批次 3：困难档（Acid/Spike Slime L、Slime Boss、Looter、Mugger）
# + 遭遇注册（large_slime / slime_boss / looter / exordium_thugs /
# lots_of_slimes）+ Gremlin 逃跑考证定案（本体无此机制，负向断言）。
# ====================================================================


BATCH3_ENCOUNTERS = [
    ("large_slime", 1, 64, 70),  # 酸 65-69 / 尖 64-70
    ("slime_boss", 1, 140, 140),
    ("looter", 1, 44, 48),
    ("exordium_thugs", 2, 10, 54),  # 弱位 10-32，强位 44-54
    ("lots_of_slimes", 5, 8, 14),
]


@pytest.mark.parametrize("encounter,count,hp_lo,hp_hi", BATCH3_ENCOUNTERS)
def test_batch3_encounter_spawn_and_hp_range(encounter, count, hp_lo, hp_hi):
    for seed in range(10):
        bc = BattleContext(seed=seed, encounter=encounter)
        assert bc.monsters.monster_count == count
        for m in bc.monsters.monsters:
            assert hp_lo <= m.hp <= hp_hi
            assert m.max_hp == m.hp
            assert m.current_move is not None
        assert len(bc.cards.draw_pile) + len(bc.cards.hand) == 10


def test_batch3_ascension_hp_ranges():
    """A7 起大史莱姆/窃贼用高位 HP；A9 起 Slime Boss 高位 HP（对齐 initHp 分桶）。"""
    for seed in range(10):
        bc = BattleContext(seed=seed, encounter="large_slime", ascension=7)
        m = bc.monsters.monsters[0]
        assert 68 <= m.hp <= 72 if isinstance(m, AcidSlimeL) else 67 <= m.hp <= 73
        bc = BattleContext(seed=seed, encounter="looter", ascension=7)
        assert 46 <= bc.monsters.monsters[0].hp <= 50
        bc = BattleContext(seed=seed, encounter="slime_boss", ascension=9)
        assert bc.monsters.monsters[0].hp == 150


def test_large_slime_composition():
    """对齐 LARGE_SLIME：misc 布尔二选一（酸 L / 尖 L）。"""
    kinds = set()
    for seed in range(20):
        comp = _composition("large_slime", seed)
        assert comp == _composition("large_slime", seed)
        assert comp in (["AcidSlimeL"], ["SpikeSlimeL"])
        kinds.add(tuple(comp))
    assert kinds == {("AcidSlimeL",), ("SpikeSlimeL",)}


def test_exordium_thugs_composition():
    """对齐 EXORDIUM_THUGS：弱野生动物三选一 + 强人形三选一（misc 流）。"""
    weaks, strongs = set(), set()
    for seed in range(80):
        comp = _composition("exordium_thugs", seed)
        assert len(comp) == 2
        assert comp == _composition("exordium_thugs", seed)
        assert comp[0] in {"RedLouse", "GreenLouse", "SpikeSlimeM", "AcidSlimeM"}
        assert comp[1] in {"Cultist", "RedSlaver", "BlueSlaver", "Looter"}
        weaks.add(comp[0])
        strongs.add(comp[1])
    assert weaks == {"RedLouse", "GreenLouse", "SpikeSlimeM", "AcidSlimeM"}
    assert strongs == {"Cultist", "RedSlaver", "BlueSlaver", "Looter"}


def test_lots_of_slimes_composition():
    """对齐 LOTS_OF_SLIMES：尖 S×3 + 酸 S×2 无放回随机排列。"""
    from collections import Counter

    orders = set()
    for seed in range(30):
        comp = _composition("lots_of_slimes", seed)
        assert comp == _composition("lots_of_slimes", seed)
        assert Counter(comp) == {"SpikeSlimeS": 3, "AcidSlimeS": 2}
        orders.add(tuple(comp))
    assert len(orders) > 5  # 排列确实随机


# ---- Acid Slime (L) ----


def test_acid_slime_l_corrosive_spit_lick_tackle():
    bc, m = solo_battle(AcidSlimeL)
    assert 65 <= m.hp <= 69
    force_intent(m, AcidSlimeL.CORROSIVE_SPIT)
    bc.end_turn()
    assert bc.player.hp == PLAYER_MAX_HP - 11
    assert _card_total(bc, "Slimed") == 2  # 大型塞 2 张黏液
    force_intent(m, AcidSlimeL.LICK)
    bc.end_turn()
    assert bc.player.hp == PLAYER_MAX_HP - 11  # 舔舐无伤害
    assert bc.player.statuses.get(PlayerStatus.WEAK) == 2  # 大型舔舐 2 层虚弱
    force_intent(m, AcidSlimeL.TACKLE)
    bc.end_turn()
    assert bc.player.hp == PLAYER_MAX_HP - 11 - 16
    assert _card_total(bc, "Slimed") == 2
    # A2：腐蚀唾液 12 / 冲撞 18
    bc, m = solo_battle(AcidSlimeL, ascension=2)
    force_intent(m, AcidSlimeL.CORROSIVE_SPIT)
    bc.end_turn()
    assert bc.player.hp == PLAYER_MAX_HP - 12
    force_intent(m, AcidSlimeL.TACKLE)
    bc.end_turn()
    assert bc.player.hp == PLAYER_MAX_HP - 12 - 18


def test_acid_slime_l_roll_segments():
    """A0 分段 30/70，边界与内层布尔分支对齐 C++ ACID_SLIME_L。"""
    bc, m = solo_battle(AcidSlimeL)
    set_history(m)
    assert m.get_move_for_roll(bc, 0).name == "Corrosive Spit"
    assert m.get_move_for_roll(bc, 29).name == "Corrosive Spit"
    assert m.get_move_for_roll(bc, 30).name == "Tackle"
    assert m.get_move_for_roll(bc, 69).name == "Tackle"
    assert m.get_move_for_roll(bc, 70).name == "Lick"
    # 腐蚀唾液连续两回合：roll<30 内层 50% 冲撞/舔舐
    set_history(m, AcidSlimeL.CORROSIVE_SPIT, AcidSlimeL.CORROSIVE_SPIT)
    assert m.get_move_for_roll(bc, 10).name in {"Tackle", "Lick"}
    # 上回合冲撞：30..69 内层 40% 腐蚀唾液/舔舐
    set_history(m, AcidSlimeL.TACKLE)
    assert m.get_move_for_roll(bc, 50).name in {"Corrosive Spit", "Lick"}
    # 上回合非冲撞 → 冲撞
    set_history(m, AcidSlimeL.LICK)
    assert m.get_move_for_roll(bc, 50).name == "Tackle"
    # 舔舐连续两回合：roll≥70 内层 40% 腐蚀唾液/冲撞
    set_history(m, AcidSlimeL.LICK, AcidSlimeL.LICK)
    assert m.get_move_for_roll(bc, 85).name in {"Corrosive Spit", "Tackle"}


def test_acid_slime_l_a17_roll_segments():
    """A17 分段 40/70；第二段判冲撞连续两回合、第三段只判上回合舔舐。"""
    bc, m = solo_battle(AcidSlimeL, ascension=17)
    set_history(m)
    assert m.get_move_for_roll(bc, 0).name == "Corrosive Spit"
    assert m.get_move_for_roll(bc, 40).name == "Tackle"
    assert m.get_move_for_roll(bc, 70).name == "Lick"
    set_history(m, AcidSlimeL.TACKLE, AcidSlimeL.TACKLE)
    assert m.get_move_for_roll(bc, 50).name in {"Corrosive Spit", "Lick"}
    set_history(m, AcidSlimeL.TACKLE)  # 只出一回合冲撞 → 冲撞
    assert m.get_move_for_roll(bc, 50).name == "Tackle"
    set_history(m, AcidSlimeL.LICK)  # A17 上回合舔舐即触发内层
    assert m.get_move_for_roll(bc, 85).name in {"Corrosive Spit", "Tackle"}


# ---- Spike Slime (L) ----


def test_spike_slime_l_lick_frail_and_flame_tackle():
    bc, m = solo_battle(SpikeSlimeL)
    assert 64 <= m.hp <= 70
    force_intent(m, SpikeSlimeL.LICK)
    bc.end_turn()
    assert bc.player.statuses.get(PlayerStatus.FRAIL) == 2
    assert not bc.player.statuses.has(PlayerStatus.WEAK)  # 施加脆弱而非虚弱
    force_intent(m, SpikeSlimeL.FLAME_TACKLE)
    bc.end_turn()
    assert bc.player.hp == PLAYER_MAX_HP - 16
    assert _card_total(bc, "Slimed") == 2
    # A17：舔舐 3 层脆弱；A17 ⊇ A2：烈焰冲撞 18 伤
    bc, m = solo_battle(SpikeSlimeL, ascension=17)
    force_intent(m, SpikeSlimeL.LICK)
    bc.end_turn()
    assert bc.player.statuses.get(PlayerStatus.FRAIL) == 3
    force_intent(m, SpikeSlimeL.FLAME_TACKLE)
    bc.end_turn()
    assert bc.player.hp == PLAYER_MAX_HP - 18


def test_spike_slime_l_roll_segments():
    bc, m = solo_battle(SpikeSlimeL)
    set_history(m)
    assert m.get_move_for_roll(bc, 0).name == "Flame Tackle"
    assert m.get_move_for_roll(bc, 29).name == "Flame Tackle"
    assert m.get_move_for_roll(bc, 30).name == "Lick"
    # 烈焰冲撞连续两回合：roll<30 强制舔舐
    set_history(m, SpikeSlimeL.FLAME_TACKLE, SpikeSlimeL.FLAME_TACKLE)
    assert m.get_move_for_roll(bc, 0).name == "Lick"
    # 舔舐连续两回合：roll≥30 强制烈焰冲撞；只出一回合仍可舔舐
    set_history(m, SpikeSlimeL.LICK, SpikeSlimeL.LICK)
    assert m.get_move_for_roll(bc, 50).name == "Flame Tackle"
    set_history(m, SpikeSlimeL.LICK)
    assert m.get_move_for_roll(bc, 50).name == "Lick"
    # A17：上回合舔舐即切烈焰冲撞
    bc, m = solo_battle(SpikeSlimeL, ascension=17)
    set_history(m, SpikeSlimeL.LICK)
    assert m.get_move_for_roll(bc, 50).name == "Flame Tackle"


# ---- 大史莱姆分裂（两型共用断言）----


@pytest.mark.parametrize("big_cls,mid_cls", [(AcidSlimeL, AcidSlimeM), (SpikeSlimeL, SpikeSlimeM)])
def test_large_slime_half_hp_forces_split_intent(big_cls, mid_cls):
    """HP 掉到 ≤ maxHp/2 时 onHpLost 强改意图为 SPLIT；半血以上不改。"""
    bc, m = solo_battle(big_cls)
    m.damage(bc, m.max_hp - m.max_hp // 2)  # 恰好掉到 maxHp//2
    assert m.hp == m.max_hp // 2
    assert m.current_move.name == "Split"
    bc, m = solo_battle(big_cls, seed=1)
    m.damage(bc, m.max_hp - m.max_hp // 2 - 1)  # 半血以上 1 点
    assert m.current_move.name != "Split"


@pytest.mark.parametrize("big_cls,mid_cls", [(AcidSlimeL, AcidSlimeM), (SpikeSlimeL, SpikeSlimeM)])
def test_large_slime_split_spawns_two_mids_inheriting_hp(big_cls, mid_cls):
    """SPLIT 执行：原槽 + 下一槽生成 2 只 M 级，curHp=maxHp=父体当前 HP；
    分裂体本回合不行动（玩家无伤、turns_taken=0），下回合起正常行动。"""
    bc, m = solo_battle(big_cls)
    m.damage(bc, m.max_hp - m.max_hp // 2 + 10)  # 掉到半血以下（保留可观的继承 HP）
    assert m.current_move.name == "Split"
    inherited = m.hp
    assert inherited == m.max_hp - (m.max_hp - m.max_hp // 2 + 10) > 0
    bc.end_turn()  # SPLIT 招式执行
    group = bc.monsters
    assert group.monster_count == 2
    assert group.alive_count == 2
    a, b = group.monsters
    assert isinstance(a, mid_cls) and isinstance(b, mid_cls)
    assert (a.hp, a.max_hp) == (inherited, inherited)
    assert (b.hp, b.max_hp) == (inherited, inherited)
    # 继承的 max_hp 即再分裂阈值的一半基础（initSpawnedMonster 双字段同写）
    # 分裂体本回合不再行动：玩家未掉血、两者尚未行动
    assert bc.player.hp == PLAYER_MAX_HP
    assert a.turns_taken == 0 and b.turns_taken == 0
    assert a.current_move is not None and b.current_move is not None  # 生成即 roll 意图
    # 下回合起两只 M 级都行动（不再分裂——M 级无 SPLIT）
    bc.end_turn()
    assert a.turns_taken == 1 and b.turns_taken == 1
    assert not bc.over


# ---- Slime Boss ----


def test_slime_boss_goop_preparing_slam_cycle():
    """序列：黏液喷射（3 张黏液）→ 蓄势（无动作、无格挡）→ 猛击 35，循环。"""
    bc, m = solo_battle(SlimeBoss)
    assert m.hp == 140
    assert m.current_move.name == "Goop Spray"
    bc.end_turn()  # r1
    assert _card_total(bc, "Slimed") == 3
    assert bc.player.hp == PLAYER_MAX_HP
    assert m.current_move.name == "Preparing"
    bc.end_turn()  # r2
    assert bc.player.hp == PLAYER_MAX_HP
    assert m.block == 0  # 蓄势无格挡（对齐 C++ 空分支）
    assert m.current_move.name == "Slam"
    bc.end_turn()  # r3 猛击 35
    assert bc.player.hp == PLAYER_MAX_HP - 35
    assert m.current_move.name == "Goop Spray"
    bc.end_turn()  # r4
    assert _card_total(bc, "Slimed") == 6


def test_slime_boss_ascension_branches():
    """A9 HP 150；A19 黏液 5 张；A4 猛击 38。"""
    bc, m = solo_battle(SlimeBoss, ascension=19)
    assert m.hp == 150
    assert m.current_move.name == "Goop Spray"
    bc.end_turn()
    assert _card_total(bc, "Slimed") == 5
    force_intent(m, SlimeBoss.SLAM)
    bc.end_turn()
    assert bc.player.hp == PLAYER_MAX_HP - 38


def test_slime_boss_half_hp_forces_split_intent():
    """HP ≤ 70 强改 SPLIT（每次漏格挡掉血重判）；71 时不改。"""
    bc, m = solo_battle(SlimeBoss)
    m.damage(bc, 70)
    assert m.hp == 70
    assert m.current_move.name == "Split"
    bc, m = solo_battle(SlimeBoss, seed=1)
    m.damage(bc, 69)
    assert m.hp == 71
    assert m.current_move.name != "Split"


def test_slime_boss_split_replaces_group():
    """分裂整组替换：槽 0 尖 L、槽 1 死亡占位、槽 2 酸 L；两 L 继承当前 HP
    为 curHp=maxHp；本回合敌方阶段收束（玩家无伤），下回合槽 0/2 行动。"""
    bc, m = solo_battle(SlimeBoss)
    m.damage(bc, 80)  # 140 → 60（半血以下）
    assert m.current_move.name == "Split"
    inherited = m.hp
    assert inherited == 60
    bc.end_turn()
    group = bc.monsters
    assert group.monster_count == 3
    assert group.alive_count == 2
    spike, mid, acid = group.monsters
    assert isinstance(spike, SpikeSlimeL) and spike.idx == 0
    assert mid.is_dead_or_escaped()  # 槽 1 死亡占位（Boss 本体）
    assert isinstance(acid, AcidSlimeL) and acid.idx == 2
    assert (spike.hp, spike.max_hp) == (inherited, inherited)
    assert (acid.hp, acid.max_hp) == (inherited, inherited)
    assert spike.current_move is not None and acid.current_move is not None
    assert bc.player.hp == PLAYER_MAX_HP  # 分裂回合不再攻击
    assert spike.turns_taken == 0 and acid.turns_taken == 0
    bc.end_turn()  # 下回合：槽 0 与槽 2 行动，槽 1 跳过
    assert spike.turns_taken == 1
    assert acid.turns_taken == 1
    assert not bc.over


def test_slime_boss_split_descendants_split_again():
    """Boss 分裂出的两只 L 各自半血再分裂：尖 L 覆写槽 1 死亡占位（不后移
    存活怪），酸 L 落槽 2/3——同回合内两连分裂后整组 4 只 M 级
    （对齐 C++ arr[idx+1] 覆写 + monsterCount=min(count+1,4) 的可达效果：
    插入语义会得到 5 只，覆写语义得到 4 只）。"""
    bc, m = solo_battle(SlimeBoss)
    m.damage(bc, 100)  # 140 → 40
    inherited = m.hp
    assert inherited == 40
    bc.end_turn()  # Boss 分裂 → [SpikeL(40), 死占位, AcidL(40)]
    spike = bc.monsters.monsters[0]
    acid = bc.monsters.monsters[2]
    # 两只 L 都打到半血以下（强改 SPLIT；阈值 = 继承 HP 的一半 = 20）
    spike.damage(bc, 25)
    acid.damage(bc, 25)
    assert spike.hp == 15 <= spike.max_hp // 2
    assert spike.current_move.name == "Split"
    assert acid.current_move.name == "Split"
    # 尖 L（槽 0）先分裂（覆写槽 1 占位），酸 L（槽 2）同回合随后分裂
    bc.end_turn()
    group = bc.monsters
    assert [type(x).__name__ for x in group.monsters] == [
        "SpikeSlimeM", "SpikeSlimeM", "AcidSlimeM", "AcidSlimeM",
    ]
    assert group.monster_count == 4  # 覆写而非插入：没有第 5 个槽位
    assert group.alive_count == 4
    assert all(x.hp == 15 and x.max_hp == 15 for x in group.monsters)  # 继承分裂时 HP
    assert not any(x.is_dead_or_escaped() for x in group.monsters)
    assert not bc.over


# ---- Looter ----


def test_looter_mugs_first_turn_then_rolls():
    """第 1 回合打劫（偷 15 + 10 伤）后意图仍为打劫；第 2 回合打劫后
    50/50 切突进/烟雾弹（打劫不再回归）。"""
    bc, m = solo_battle(Looter)
    assert 44 <= m.hp <= 48
    assert m.current_move.name == "Mug"
    assert bc.player.gold == 99
    bc.end_turn()  # r1 打劫
    assert bc.player.gold == 84
    assert m.misc_info == 15
    assert bc.player.hp == PLAYER_MAX_HP - 10
    assert m.current_move.name == "Mug"
    bc.end_turn()  # r2 打劫
    assert bc.player.gold == 69
    assert m.misc_info == 30
    assert bc.player.hp == PLAYER_MAX_HP - 20
    assert m.current_move.name in {"Lunge", "Smoke Bomb"}


def test_looter_lunge_steals_and_smoke_then_escapes():
    """突进（偷 15 + 12 伤）→ 烟雾弹（+6 格挡）→ 逃跑（全员逃跑判胜）。"""
    bc, m = solo_battle(Looter)
    force_intent(m, Looter.LUNGE)
    bc.end_turn()
    assert bc.player.gold == 84  # 突进也偷 15
    assert bc.player.hp == PLAYER_MAX_HP - 12
    assert m.current_move.name == "Smoke Bomb"
    bc.end_turn()  # 烟雾弹
    assert m.block == 6
    assert m.current_move.name == "Escape"
    assert bc.monsters.alive_count == 1
    bc.end_turn()  # 逃跑
    assert m.is_escaping
    assert not m.is_targetable()  # 逃跑怪不可被指定
    assert bc.monsters.alive_count == 0
    assert bc.won  # 全员死亡/逃跑判胜
    assert bc.player.gold == 84  # 只偷过突进一次 15；逃跑不返还偷金


def test_looter_death_returns_stolen_gold():
    """死亡返还累计偷金（引擎 THIEVERY 分支）；偷取不超过玩家现有。"""
    bc, m = solo_battle(Looter)
    force_intent(m, Looter.MUG)
    bc.end_turn()
    assert bc.player.gold == 84
    slay(bc, 0)
    assert bc.player.gold == 99  # 全额返还
    # 玩家金币不足时只偷到现有数量
    bc, m = solo_battle(Looter, seed=1)
    bc.player.gold = 7
    force_intent(m, Looter.LUNGE)
    bc.end_turn()
    assert bc.player.gold == 0
    assert m.misc_info == 7
    slay(bc, 0)
    assert bc.player.gold == 7


def test_looter_ascension_branches():
    """A17 偷 20；A2 打劫 11 / 突进 14。"""
    bc, m = solo_battle(Looter, ascension=17)
    force_intent(m, Looter.MUG)
    bc.end_turn()
    assert bc.player.gold == 79
    assert bc.player.hp == PLAYER_MAX_HP - 11
    force_intent(m, Looter.LUNGE)
    bc.end_turn()
    assert bc.player.hp == PLAYER_MAX_HP - 11 - 14


# ---- Mugger ----


def test_mugger_mugs_twice_then_rolls():
    """打劫前 2 回合固定（每回合偷 15 + 10 伤），第 2 回合后 50/50 切换。"""
    bc, m = solo_battle(Mugger)
    assert 48 <= m.hp <= 52
    assert m.current_move.name == "Mug"
    bc.end_turn()  # r1
    assert m.current_move.name == "Mug"
    assert m.misc_info == 15
    bc.end_turn()  # r2
    assert m.misc_info == 30
    assert bc.player.gold == 69
    assert bc.player.hp == PLAYER_MAX_HP - 20
    assert m.current_move.name in {"Lunge", "Smoke Bomb"}


def test_mugger_numbers_and_escape():
    """突进 16 伤 + 偷 15；烟雾弹 11 格挡；逃跑判胜。A17 烟雾弹 17、A2 突进 18。"""
    bc, m = solo_battle(Mugger)
    force_intent(m, Mugger.LUNGE)
    bc.end_turn()
    assert bc.player.hp == PLAYER_MAX_HP - 16
    assert bc.player.gold == 84
    assert m.current_move.name == "Smoke Bomb"
    bc.end_turn()
    assert m.block == 11
    assert m.current_move.name == "Escape"
    bc.end_turn()
    assert m.is_escaping
    assert bc.won
    # A17：烟雾弹 17 格挡；A17 ⊇ A2：突进 18 伤、偷 20
    bc, m = solo_battle(Mugger, ascension=17)
    force_intent(m, Mugger.MUG)
    bc.end_turn()
    assert bc.player.gold == 79  # A17 偷 20
    force_intent(m, Mugger.SMOKE_BOMB)
    bc.end_turn()
    assert m.block == 17
    force_intent(m, Mugger.LUNGE)
    bc.end_turn()
    assert bc.player.hp == PLAYER_MAX_HP - 11 - 18  # A17 ⊇ A2：打劫 11、突进 18


def test_mugger_death_returns_stolen_gold():
    bc, m = solo_battle(Mugger)
    force_intent(m, Mugger.MUG)
    bc.end_turn()
    assert bc.player.gold == 84
    slay(bc, 0)
    assert bc.player.gold == 99


# ---- Gremlin 逃跑考证（批次 3 定案：本体无逃跑机制）----


def test_gremlin_gang_gremlins_never_escape():
    """负向断言：多回合后小鬼不逃跑、战斗不因逃跑提前结束。

    考证（见 monsters.py 模块头）：lightspeed escapeNext 从不置位（死代码，
    且仅 Fat/Mad/Sneaky 残留分支）；本体 wiki 记载各小鬼招式无限循环、
    无逃跑条目。"3 回合后逃跑"为 StS2 的 Escape Artist 机制。
    """
    bc = staged_battle(5, [FatGremlin, SneakyGremlin, ShieldGremlin, GremlinWizard])
    for _ in range(6):
        bc.end_turn()
        assert not any(m.is_escaping for m in bc.monsters.monsters)
        assert not bc.over
        bc.player.hp = PLAYER_MAX_HP  # 测试续命，隔离逃跑断言
    for m in bc.monsters.monsters:
        assert m.is_targetable()
        assert not m.is_escaping


# ====================================================================
# 批次 B：Act 2 全部新怪（15 种）+ 19 个 Act 2 遭遇注册。
# 数值/分段逐行对齐 lightspeed MonsterSpecific.cpp，wiki 交叉校验。
# ====================================================================


def act2_battle(encounter: str, seed: int = 0, ascension: int = 0) -> BattleContext:
    return BattleContext(seed=seed, encounter=encounter, ascension=ascension)


ACT2_ENCOUNTERS = [
    ("spheric_guardian", 1, 20, 20),
    ("chosen", 1, 95, 99),
    ("shell_parasite", 1, 68, 72),
    ("three_byrds", 3, 25, 31),
    ("two_thieves", 2, 44, 52),
    ("chosen_and_byrds", 2, 25, 99),
    ("sentry_and_sphere", 2, 20, 42),
    ("cultist_and_chosen", 2, 48, 99),
    ("three_cultist", 3, 48, 54),
    ("shelled_parasite_and_fungi", 2, 22, 72),
    ("snecko", 1, 114, 120),
    ("snake_plant", 1, 75, 79),
    ("centurion_and_healer", 2, 48, 80),
    ("book_of_stabbing", 1, 160, 164),
    ("champ", 1, 420, 420),
]


@pytest.mark.parametrize("encounter,count,hp_lo,hp_hi", ACT2_ENCOUNTERS)
def test_act2_encounter_spawn_and_hp_range(encounter, count, hp_lo, hp_hi):
    for seed in range(10):
        bc = act2_battle(encounter, seed=seed)
        assert bc.monsters.monster_count == count
        for m in bc.monsters.monsters:
            assert hp_lo <= m.hp <= hp_hi
            assert m.max_hp == m.hp
            assert m.current_move is not None
        assert len(bc.cards.draw_pile) + len(bc.cards.hand) == 10


def test_act2_compositions():
    """多怪遭遇的槽位构成（对齐 MonsterGroup.cpp 的 Act 2 分支）。"""
    for seed in range(5):
        assert [type(m).__name__ for m in act2_battle("three_byrds", seed).monsters.monsters] == ["Byrd"] * 3
        comp = [type(m).__name__ for m in act2_battle("two_thieves", seed).monsters.monsters]
        assert comp == ["Looter", "Mugger"]
        comp = [type(m).__name__ for m in act2_battle("chosen_and_byrds", seed).monsters.monsters]
        assert comp == ["Byrd", "Chosen"]
        comp = [type(m).__name__ for m in act2_battle("sentry_and_sphere", seed).monsters.monsters]
        assert comp == ["Sentry", "SphericGuardian"]
        comp = [type(m).__name__ for m in act2_battle("cultist_and_chosen", seed).monsters.monsters]
        assert comp == ["Cultist", "Chosen"]
        comp = [type(m).__name__ for m in act2_battle("three_cultist", seed).monsters.monsters]
        assert comp == ["Cultist"] * 3
        comp = [type(m).__name__ for m in act2_battle("shelled_parasite_and_fungi", seed).monsters.monsters]
        assert comp == ["ShelledParasite", "FungiBeast"]
        comp = [type(m).__name__ for m in act2_battle("centurion_and_healer", seed).monsters.monsters]
        assert comp == ["Centurion", "Mystic"]


def test_act2_ascension_hp_ranges():
    """A7/A8/A9 高位 HP 区间（C++ initHp 的分档与 lightspeed 一致）。"""
    for seed in range(10):
        for enc, lo, hi in [("chosen", 98, 103), ("snecko", 120, 125), ("snake_plant", 78, 82),
                            ("three_byrds", 26, 33), ("shell_parasite", 70, 75)]:
            m = act2_battle(enc, seed=seed, ascension=7).monsters.monsters[0]
            assert lo <= m.hp <= hi
        bc = act2_battle("centurion_and_healer", seed=seed, ascension=7)
        assert 76 <= bc.monsters.monsters[0].hp <= 83
        assert 50 <= bc.monsters.monsters[1].hp <= 58
        m = act2_battle("gremlin_leader", seed=seed, ascension=8).monsters.monsters[3]
        assert 145 <= m.hp <= 155
        m = act2_battle("book_of_stabbing", seed=seed, ascension=8).monsters.monsters[0]
        assert 168 <= m.hp <= 172
        m = act2_battle("automaton", seed=seed, ascension=9).monsters.monsters[1]
        assert m.hp == 320
        m = act2_battle("collector", seed=seed, ascension=9).monsters.monsters[2]
        assert m.hp == 300
        m = act2_battle("champ", seed=seed, ascension=9).monsters.monsters[0]
        assert m.hp == 440


# ---- Spheric Guardian ----


def test_spheric_guardian_initial_state():
    """开局：HP 恒 20（不抽样）、人工制品 3、40 格挡 + 壁垒。"""
    for seed in range(10):
        m = act2_battle("spheric_guardian", seed=seed).monsters.monsters[0]
        assert isinstance(m, SphericGuardian)
        assert m.hp == 20 and m.max_hp == 20
        assert m.statuses.get(MonsterStatus.ARTIFACT) == 3
        assert m.block == 40
        assert m.current_move.name == "Activate"


def test_spheric_guardian_activate_and_barricade():
    """激活 +25 格挡；壁垒：回合开始不清格挡（引擎无 MS::BARRICADE，
    子类覆盖 apply_start_of_turn_powers 实现）。"""
    bc = act2_battle("spheric_guardian")
    m = bc.monsters.monsters[0]
    bc.end_turn()
    assert bc.player.hp == PLAYER_MAX_HP
    assert m.block == 40 + 25  # 激活
    assert m.current_move.name == "Attack Debuff"
    bc.end_turn()
    # 壁垒：第 2 回合怪物阶段开始时 65 格挡仍在
    assert m.block == 65
    assert bc.player.hp == PLAYER_MAX_HP - 10
    assert bc.player.statuses.get(PlayerStatus.FRAIL) == 5
    assert m.current_move.name == "Slam"
    bc.end_turn()
    assert m.block == 65  # 壁垒持续
    assert bc.player.hp == PLAYER_MAX_HP - 10 - 20  # Slam 10×2
    assert m.current_move.name == "Harden"


def test_spheric_guardian_harden_and_ascension():
    """硬化：+15 格挡 + 10 伤；A17 激活 35 格挡、A2 起攻击 11。"""
    bc = act2_battle("spheric_guardian")
    m = bc.monsters.monsters[0]
    force_intent(m, SphericGuardian.HARDEN)
    bc.end_turn()
    assert m.block == 40 + 15
    assert bc.player.hp == PLAYER_MAX_HP - 10

    bc = act2_battle("spheric_guardian", ascension=2)
    m = bc.monsters.monsters[0]
    force_intent(m, SphericGuardian.SLAM)
    bc.end_turn()
    assert bc.player.hp == PLAYER_MAX_HP - 22  # 11×2

    bc = act2_battle("spheric_guardian", ascension=17)
    m = bc.monsters.monsters[0]
    bc.end_turn()
    assert m.block == 40 + 35
    assert bc.player.hp == PLAYER_MAX_HP  # 激活无伤害


# ---- Chosen ----


def test_chosen_opening_poke_then_hex():
    """A0 开局 Poke（5×2），第二次 roll 固定 Hex（施 1 层 HEX）。"""
    bc = act2_battle("chosen")
    m = bc.monsters.monsters[0]
    assert m.current_move.name == "Poke"
    bc.end_turn()
    assert bc.player.hp == PLAYER_MAX_HP - 10
    # 回合末自动 roll：仅一招历史（lastMoveBefore INVALID）→ Hex
    assert m.current_move.name == "Hex"
    force_intent(m, Chosen.HEX)
    bc.end_turn()
    assert bc.player.statuses.get(PlayerStatus.HEX) == 1
    # 引擎 HEX 语义（已对齐 C++ BattleContext.cpp:1765）：每打出一张牌
    # 洗入 1 张 DAZED。玩家空过回合 → 无 DAZED 增加、不掉血。
    from sts.content.cards import DAZED

    assert bc.player.hp == PLAYER_MAX_HP - 10
    assert not any(c.card is DAZED for c in bc.cards.draw_pile)
    # 打 1 张牌 → +1 DAZED 洗入抽牌堆
    bc.cards.hand.clear()
    bc.cards.hand.append(bc.cards.instantiate(STRIKE))
    bc.play_card(0)
    assert sum(1 for c in bc.cards.draw_pile if c.card is DAZED) == 1


def test_chosen_move_values():
    bc = act2_battle("chosen")
    m = bc.monsters.monsters[0]
    force_intent(m, Chosen.ZAP)
    bc.end_turn()
    assert bc.player.hp == PLAYER_MAX_HP - 18
    force_intent(m, Chosen.DRAIN)
    bc.end_turn()
    assert bc.player.statuses.get(PlayerStatus.WEAK) == 3
    assert m.statuses.get(MonsterStatus.STRENGTH) == 3
    assert bc.player.hp == PLAYER_MAX_HP - 18
    force_intent(m, Chosen.DEBILITATE)
    bc.end_turn()
    assert bc.player.hp == PLAYER_MAX_HP - 18 - 13  # 汲取给被选者 +3 力量
    assert bc.player.statuses.get(PlayerStatus.VULNERABLE) == 2


def test_chosen_roll_segments():
    bc = act2_battle("chosen")
    m = bc.monsters.monsters[0]
    m.move_history.clear()
    assert m.get_move_for_roll(bc, 99).name == "Poke"  # 首回合
    m.move_history.clear()
    m.set_move(Chosen.POKE)
    assert m.get_move_for_roll(bc, 99).name == "Hex"  # 仅一招历史 → Hex
    set_history(m, Chosen.HEX, Chosen.POKE)
    assert m.get_move_for_roll(bc, 49).name == "Debilitate"
    assert m.get_move_for_roll(bc, 50).name == "Drain"
    set_history(m, Chosen.DEBILITATE, Chosen.HEX)
    assert m.get_move_for_roll(bc, 39).name == "Zap"
    assert m.get_move_for_roll(bc, 40).name == "Poke"
    # A17：首回合固定 Hex
    bc17 = act2_battle("chosen", ascension=17)
    m17 = bc17.monsters.monsters[0]
    m17.move_history.clear()
    assert m17.get_move_for_roll(bc17, 99).name == "Hex"


def test_chosen_ascension_damage():
    bc = act2_battle("chosen", ascension=2)
    m = bc.monsters.monsters[0]
    force_intent(m, Chosen.ZAP)
    bc.end_turn()
    assert bc.player.hp == PLAYER_MAX_HP - 21
    force_intent(m, Chosen.POKE)
    bc.end_turn()
    assert bc.player.hp == PLAYER_MAX_HP - 21 - 12  # 6×2
    force_intent(m, Chosen.DEBILITATE)
    bc.end_turn()
    assert bc.player.hp == PLAYER_MAX_HP - 21 - 12 - 12


# ---- Shelled Parasite ----


def test_shelled_parasite_initial_state():
    for seed in range(10):
        m = act2_battle("shell_parasite", seed=seed).monsters.monsters[0]
        assert isinstance(m, ShelledParasite)
        assert m.statuses.get(MonsterStatus.PLATED_ARMOR_M) == 14
        assert m.block == 14


def test_shelled_parasite_moves_and_suck_heal():
    bc = act2_battle("shell_parasite")
    m = bc.monsters.monsters[0]
    force_intent(m, ShelledParasite.FELL)
    bc.end_turn()
    assert bc.player.hp == PLAYER_MAX_HP - 18
    assert bc.player.statuses.get(PlayerStatus.FRAIL) == 2
    force_intent(m, ShelledParasite.DOUBLE_STRIKE)
    bc.end_turn()
    assert bc.player.hp == PLAYER_MAX_HP - 18 - 12  # 6×2
    # 吸血：先打掉 10 HP，Suck 漏格挡 10 → 回 10
    m.hp -= 10
    force_intent(m, ShelledParasite.SUCK)
    bc.end_turn()
    assert bc.player.hp == PLAYER_MAX_HP - 18 - 12 - 10
    assert m.hp == m.max_hp - 10 + 10


def test_shelled_parasite_suck_heal_capped_by_unblocked():
    """吸血量 = min(伤害, 漏格挡量)：玩家有 6 格挡时只回 4。"""
    bc = act2_battle("shell_parasite")
    m = bc.monsters.monsters[0]
    m.hp -= 10
    bc.player.block = 6
    force_intent(m, ShelledParasite.SUCK)
    bc.end_turn()
    assert bc.player.hp == PLAYER_MAX_HP - 4  # 10 伤被 6 格挡吸收，漏 4
    assert m.hp == m.max_hp - 10 + 4  # 吸血 = min(伤害 10, 漏格挡 4)


def test_shelled_parasite_plated_armor_stun_chain():
    """重甲归零 → 眩晕：空转一回合后按 roll 出招。"""
    bc = act2_battle("shell_parasite")
    m = bc.monsters.monsters[0]
    m.statuses.set(MonsterStatus.PLATED_ARMOR_M, 1)
    m.block = 0  # 绕过开局 14 格挡，保证 6 伤漏过
    play_strike(bc, target=0)  # 未格挡 → 层数归零 → 眩晕
    assert not m.statuses.has(MonsterStatus.PLATED_ARMOR_M)
    assert m.current_move.name == "Stunned"
    hp0 = bc.player.hp
    bc.end_turn()  # 眩晕空转
    assert bc.player.hp == hp0
    # 眩晕后 setMove(FELL) 再 roll：意图是任意常规招
    assert m.current_move.name in {"Fell", "Double Strike", "Suck"}
    # 重甲在回合开始按剩余层数给格挡：归零后不再给
    assert m.block == 0


def test_shelled_parasite_roll_segments():
    bc = act2_battle("shell_parasite")
    m = bc.monsters.monsters[0]
    m.move_history.clear()
    assert m.get_move_for_roll(bc, 0).name in {"Double Strike", "Suck"}  # 首回合 50/50
    set_history(m, ShelledParasite.DOUBLE_STRIKE)
    assert m.get_move_for_roll(bc, 19).name == "Fell"  # roll<20 且上回合非 Fell
    set_history(m, ShelledParasite.FELL)
    # roll<20 且上回合 Fell → roll2∈[20,99] 内层，落点按 roll2<60 判
    assert m.get_move_for_roll(bc, 19).name in {"Double Strike", "Suck"}
    set_history(m, ShelledParasite.DOUBLE_STRIKE, ShelledParasite.DOUBLE_STRIKE)
    assert m.get_move_for_roll(bc, 30).name == "Suck"  # DS 连续两回合
    set_history(m, ShelledParasite.SUCK, ShelledParasite.SUCK)
    assert m.get_move_for_roll(bc, 80).name == "Double Strike"  # Suck 连续两回合


def test_shelled_parasite_a17_opens_fell():
    bc = act2_battle("shell_parasite", ascension=17)
    m = bc.monsters.monsters[0]
    m.move_history.clear()
    assert m.get_move_for_roll(bc, 99).name == "Fell"


# ---- Byrd ----


def test_byrd_initial_flight_and_a17():
    for seed in range(10):
        m = act2_battle("three_byrds", seed=seed).monsters.monsters[0]
        assert m.statuses.get(MonsterStatus.FLIGHT) == 3
        m17 = act2_battle("three_byrds", seed=seed, ascension=17).monsters.monsters[0]
        assert m17.statuses.get(MonsterStatus.FLIGHT) == 4


def test_byrd_moves():
    bc = act2_battle("three_byrds")
    b0, b1, b2 = bc.monsters.monsters
    force_intent(b0, Byrd.PECK)
    force_intent(b1, Byrd.SWOOP)
    force_intent(b2, Byrd.CAW)
    hp0 = bc.player.hp
    bc.end_turn()
    assert bc.player.hp == hp0 - 5 - 12  # Peck 1×5 + Swoop 12（Caw 无伤害）
    assert b2.statuses.get(MonsterStatus.STRENGTH) == 1


def test_byrd_flight_loss_stun_headbutt_fly_chain():
    """受未格挡攻击 -1 层飞行；归零落地 → 眩晕 → 头槌 → 起飞。"""
    bc = act2_battle("three_byrds")
    slay(bc, 1)
    slay(bc, 2)
    b = bc.monsters.monsters[0]
    for _ in range(3):
        b.attacked(bc, 5)  # 无格挡直伤
    assert not b.statuses.has(MonsterStatus.FLIGHT)
    assert b.current_move.name == "Stunned"
    hp0 = bc.player.hp
    bc.end_turn()  # 眩晕空转
    assert bc.player.hp == hp0
    assert b.current_move.name == "Headbutt"
    bc.end_turn()
    assert bc.player.hp == hp0 - 3
    assert b.current_move.name == "Fly"
    bc.end_turn()
    assert b.statuses.get(MonsterStatus.FLIGHT) == 3


def test_byrd_flight_resets_each_turn_while_flying():
    """回合开始仍在飞则回满 3 层（对齐 C++ applyStartOfTurnPowers）。"""
    bc = act2_battle("three_byrds")
    slay(bc, 1)
    slay(bc, 2)
    b = bc.monsters.monsters[0]
    b.attacked(bc, 5)
    assert b.statuses.get(MonsterStatus.FLIGHT) == 2
    bc.end_turn()
    assert b.statuses.get(MonsterStatus.FLIGHT) == 3


def test_byrd_roll_segments():
    bc = act2_battle("three_byrds")
    m = bc.monsters.monsters[0]
    m.move_history.clear()
    assert m.get_move_for_roll(bc, 0).name in {"Caw", "Peck"}  # 首回合 37.5% Caw
    set_history(m, Byrd.PECK, Byrd.PECK)
    assert m.get_move_for_roll(bc, 49).name in {"Swoop", "Caw"}
    set_history(m, Byrd.PECK)
    assert m.get_move_for_roll(bc, 49).name == "Peck"  # 未连续两回合
    set_history(m, Byrd.SWOOP)
    assert m.get_move_for_roll(bc, 69).name in {"Caw", "Peck"}
    set_history(m, Byrd.PECK)
    assert m.get_move_for_roll(bc, 69).name == "Swoop"
    set_history(m, Byrd.CAW)
    assert m.get_move_for_roll(bc, 99).name in {"Swoop", "Peck"}
    set_history(m, Byrd.PECK)
    assert m.get_move_for_roll(bc, 99).name == "Caw"


def test_byrd_peck_a2_hits():
    bc = act2_battle("three_byrds", ascension=2)
    slay(bc, 1)
    slay(bc, 2)
    b = bc.monsters.monsters[0]
    force_intent(b, Byrd.PECK)
    hp0 = bc.player.hp
    bc.end_turn()
    assert bc.player.hp == hp0 - 6  # A2 起 1×6 段


# ---- Snake Plant ----


def test_snake_plant_malleable_and_reset():
    bc = act2_battle("snake_plant")
    m = bc.monsters.monsters[0]
    assert m.statuses.get(MonsterStatus.MALLEABLE) == 3
    play_strike(bc, target=0)  # 6 伤未格挡 → +3 格挡，层数 4
    assert m.block == 3
    assert m.statuses.get(MonsterStatus.MALLEABLE) == 4
    bc.end_turn()
    # 回合末重置回 3（对齐 C++ applyEndOfTurnTriggers）
    assert m.statuses.get(MonsterStatus.MALLEABLE) == 3


def test_snake_plant_moves():
    bc = act2_battle("snake_plant")
    m = bc.monsters.monsters[0]
    force_intent(m, SnakePlant.CHOMP)
    bc.end_turn()
    assert bc.player.hp == PLAYER_MAX_HP - 21  # 7×3
    force_intent(m, SnakePlant.ENFEEBLING_SPORES)
    bc.end_turn()
    assert bc.player.statuses.get(PlayerStatus.FRAIL) == 2
    assert bc.player.statuses.get(PlayerStatus.WEAK) == 2


def test_snake_plant_roll_segments():
    bc = act2_battle("snake_plant")
    m = bc.monsters.monsters[0]
    set_history(m, SnakePlant.CHOMP)
    assert m.get_move_for_roll(bc, 64).name == "Chomp"
    set_history(m, SnakePlant.CHOMP, SnakePlant.CHOMP)
    assert m.get_move_for_roll(bc, 64).name == "Enfeebling Spores"
    set_history(m, SnakePlant.ENFEEBLING_SPORES)
    assert m.get_move_for_roll(bc, 65).name == "Chomp"  # A0：上回合孢子 → Chomp
    set_history(m, SnakePlant.CHOMP)
    assert m.get_move_for_roll(bc, 65).name == "Enfeebling Spores"
    # A17：第三段改判孢子连续两回合
    bc17 = act2_battle("snake_plant", ascension=17)
    m17 = bc17.monsters.monsters[0]
    set_history(m17, SnakePlant.ENFEEBLING_SPORES)
    assert m17.get_move_for_roll(bc17, 65).name == "Enfeebling Spores"  # A17 需连续两回合
    set_history(m17, SnakePlant.ENFEEBLING_SPORES, SnakePlant.ENFEEBLING_SPORES)
    assert m17.get_move_for_roll(bc17, 65).name == "Chomp"


# ---- Snecko ----


def test_snecko_first_turn_glare_confuses_draw_costs():
    bc = act2_battle("snecko")
    m = bc.monsters.monsters[0]
    assert m.current_move.name == "Perplexing Glare"
    bc.end_turn()
    assert bc.player.statuses.get(PlayerStatus.CONFUSED) == 1
    # 引擎 CONFUSED：本回合抽到的牌费用随机 0~3
    assert all(0 <= c.cost_for_turn <= 3 for c in bc.cards.hand)


def test_snecko_moves_and_segments():
    bc = act2_battle("snecko")
    m = bc.monsters.monsters[0]
    force_intent(m, Snecko.BITE)
    bc.end_turn()
    assert bc.player.hp == PLAYER_MAX_HP - 15
    force_intent(m, Snecko.TAIL_WHIP)
    bc.end_turn()
    assert bc.player.hp == PLAYER_MAX_HP - 15 - 8
    assert bc.player.statuses.get(PlayerStatus.VULNERABLE) == 2
    set_history(m, Snecko.BITE)
    assert m.get_move_for_roll(bc, 39).name == "Tail Whip"
    assert m.get_move_for_roll(bc, 40).name == "Bite"
    set_history(m, Snecko.BITE, Snecko.BITE)
    assert m.get_move_for_roll(bc, 40).name == "Tail Whip"  # Bite 连续两回合


def test_snecko_a17_tail_whip_adds_weak():
    bc = act2_battle("snecko", ascension=17)
    m = bc.monsters.monsters[0]
    force_intent(m, Snecko.TAIL_WHIP)
    bc.end_turn()
    assert bc.player.statuses.get(PlayerStatus.WEAK) == 2
    assert bc.player.statuses.get(PlayerStatus.VULNERABLE) == 2


# ---- Centurion & Mystic ----


def test_centurion_slash_fury_and_defend():
    bc = act2_battle("centurion_and_healer")
    cent, mystic = bc.monsters.monsters
    force_intent(mystic, Mystic.HEAL)  # 隔离秘术师（治疗无玩家伤害）
    force_intent(cent, Centurion.SLASH)
    hp0 = bc.player.hp
    bc.end_turn()
    assert bc.player.hp == hp0 - 12
    assert mystic.block == 0  # 秘术师未防御
    force_intent(mystic, Mystic.HEAL)
    force_intent(cent, Centurion.DEFEND)
    bc.end_turn()
    assert mystic.block == 15
    slay(bc, 1)  # 孤军 → Fury
    force_intent(cent, Centurion.FURY)
    hp0 = bc.player.hp
    bc.end_turn()
    assert bc.player.hp == hp0 - 18  # 6×3


def test_centurion_roll_segments():
    bc = act2_battle("centurion_and_healer")
    m = bc.monsters.monsters[0]
    set_history(m, Centurion.SLASH)
    assert m.get_move_for_roll(bc, 64).name == "Slash"
    assert m.get_move_for_roll(bc, 65).name == "Defend"  # 秘术师在场
    set_history(m, Centurion.SLASH, Centurion.SLASH)
    assert m.get_move_for_roll(bc, 0).name == "Defend"
    set_history(m, Centurion.DEFEND, Centurion.DEFEND)
    assert m.get_move_for_roll(bc, 0).name == "Slash"  # 防御不能三连
    slay(bc, 1)
    set_history(m, Centurion.SLASH, Centurion.SLASH)
    assert m.get_move_for_roll(bc, 0).name == "Fury"  # 秘术师死后 Fury


def test_mystic_heal_buff_attack_debuff():
    """百夫长固定防御（不攻击玩家），隔离验证秘术师三个招式。"""
    bc = act2_battle("centurion_and_healer")
    cent, mystic = bc.monsters.monsters
    cent.hp -= 20
    mystic.hp -= 20
    force_intent(cent, Centurion.DEFEND)
    force_intent(mystic, Mystic.HEAL)
    hp0 = bc.player.hp
    bc.end_turn()
    assert cent.hp == cent.max_hp - 20 + 16
    assert mystic.hp == mystic.max_hp - 20 + 16
    assert bc.player.hp == hp0  # 治疗/防御均无玩家伤害
    force_intent(cent, Centurion.DEFEND)
    force_intent(mystic, Mystic.BUFF)
    bc.end_turn()
    assert mystic.statuses.get(MonsterStatus.STRENGTH) == 2
    assert cent.statuses.get(MonsterStatus.STRENGTH) == 2
    force_intent(cent, Centurion.DEFEND)
    force_intent(mystic, Mystic.ATTACK_DEBUFF)
    hp0 = bc.player.hp
    bc.end_turn()
    assert bc.player.hp == hp0 - 10  # 8 + 秘术师自身增益的 +2 力量
    assert bc.player.statuses.get(PlayerStatus.FRAIL) == 2


def test_mystic_roll_segments():
    bc = act2_battle("centurion_and_healer")
    cent, mystic = bc.monsters.monsters
    cent.hp -= 20  # 百夫长缺血 ≥16 → 治疗
    assert mystic.get_move_for_roll(bc, 99).name == "Heal"
    cent.hp = cent.max_hp
    set_history(mystic, Mystic.BUFF)
    assert mystic.get_move_for_roll(bc, 39).name == "Buff"
    assert mystic.get_move_for_roll(bc, 40).name == "Attack Debuff"
    set_history(mystic, Mystic.ATTACK_DEBUFF)
    assert mystic.get_move_for_roll(bc, 40).name == "Attack Debuff"  # 未连续两回合
    set_history(mystic, Mystic.ATTACK_DEBUFF, Mystic.ATTACK_DEBUFF)
    assert mystic.get_move_for_roll(bc, 40).name == "Buff"
    set_history(mystic, Mystic.BUFF, Mystic.BUFF)
    assert mystic.get_move_for_roll(bc, 99).name == "Attack Debuff"  # Buff 不能三连


def test_mystic_a17_branches():
    bc = act2_battle("centurion_and_healer", ascension=17)
    cent, mystic = bc.monsters.monsters
    cent.hp -= 16  # 16 < 21：A17 治疗阈值提高到 21 → 不再治疗
    set_history(mystic, Mystic.BUFF)
    assert mystic.get_move_for_roll(bc, 99).name == "Attack Debuff"  # A17 上回合出过即禁


# ---- Gremlin Leader ----


def test_gremlin_leader_encounter_layout():
    for seed in range(20):
        bc = act2_battle("gremlin_leader", seed=seed)
        group = bc.monsters
        assert group.monster_count == 4
        assert group.alive_count == 3
        assert group.monsters[0].is_dead_or_escaped()  # 槽 0 死亡占位
        gremlin_types = {"MadGremlin", "SneakyGremlin", "FatGremlin", "ShieldGremlin", "GremlinWizard"}
        assert type(group.monsters[1]).__name__ in gremlin_types
        assert type(group.monsters[2]).__name__ in gremlin_types
        for i in (1, 2):
            assert group.monsters[i].statuses.has(MonsterStatus.MINION)
        leader = group.monsters[3]
        assert isinstance(leader, GremlinLeader)
        assert 140 <= leader.hp <= 148
        assert leader.statuses.has(MonsterStatus.MINION_LEADER)


def test_gremlin_leader_encourage_and_stab():
    """Encourage：存活小鬼力量 +3、格挡 +6（Shield Gremlin 的 Protect 可能
    追加随机格挡，故格挡断言下界）；Stab 6×3。"""
    bc = act2_battle("gremlin_leader")
    group = bc.monsters
    g1, g2, leader = group.monsters[1], group.monsters[2], group.monsters[3]
    force_intent(leader, GremlinLeader.ENCOURAGE)
    bc.end_turn()
    assert g1.statuses.get(MonsterStatus.STRENGTH) == 3
    assert g1.block >= 6
    assert g2.statuses.get(MonsterStatus.STRENGTH) == 3
    assert g2.block >= 6
    assert leader.statuses.get(MonsterStatus.STRENGTH) == 3
    slay(bc, 1)
    slay(bc, 2)
    force_intent(leader, GremlinLeader.STAB)
    hp0 = bc.player.hp
    bc.end_turn()
    assert bc.player.hp == hp0 - 27  # (6+3 鼓动力量)×3


def test_gremlin_leader_rally_summons_into_open_slots():
    bc = act2_battle("gremlin_leader")
    group = bc.monsters
    slay(bc, 1)
    slay(bc, 2)
    leader = group.monsters[3]
    force_intent(leader, GremlinLeader.RALLY)
    bc.end_turn()
    assert group.alive_count == 3
    gremlin_types = {"MadGremlin", "SneakyGremlin", "FatGremlin", "ShieldGremlin", "GremlinWizard"}
    for i in (1, 2):
        assert type(group.monsters[i]).__name__ in gremlin_types
        assert group.monsters[i].statuses.has(MonsterStatus.MINION)
        assert group.monsters[i].current_move is not None


def test_gremlin_leader_death_wins_despite_minions():
    bc = act2_battle("gremlin_leader")
    group = bc.monsters
    assert group.alive_count == 3
    slay(bc, 3)
    assert bc.won  # MINION_LEADER：主死即胜，小鬼仍在场
    # die() 的 MINION_LEADER 分支立即判胜返回，存活数不减（引擎既有语义）
    assert group.alive_count == 3


def _leader_battle(n_gremlins: int, seed: int = 0, ascension: int = 0):
    """按存活小鬼数构造 4 槽布局（首领恒在槽 3）。"""
    from sts.content.monsters import _SlotPlaceholder

    bc = BattleContext(seed=seed, encounter="cultist", ascension=ascension)
    layout = [_SlotPlaceholder(0), _SlotPlaceholder(1), _SlotPlaceholder(2), None]
    for i in range(n_gremlins):
        layout[i + 1] = MadGremlin.create(bc, i + 1)
    layout[3] = GremlinLeader.create(bc, 3)
    bc.monsters.monsters = layout
    bc.monsters.alive_count = n_gremlins + 1
    for m in layout:
        if not m.is_dead_or_escaped():
            m.roll_move(bc)
    return bc, layout[3]


def test_gremlin_leader_roll_segments():
    bc, leader = _leader_battle(0)
    force_intent(leader, GremlinLeader.RALLY)
    assert leader.get_move_for_roll(bc, 74).name == "Stab"
    assert leader.get_move_for_roll(bc, 0).name == "Stab"
    force_intent(leader, GremlinLeader.STAB)
    assert leader.get_move_for_roll(bc, 0).name == "Rally"
    assert leader.get_move_for_roll(bc, 74).name == "Rally"
    assert leader.get_move_for_roll(bc, 75).name == "Rally"  # 上回合 Stab
    force_intent(leader, GremlinLeader.RALLY)
    assert leader.get_move_for_roll(bc, 75).name == "Stab"

    bc, leader = _leader_battle(1)
    force_intent(leader, GremlinLeader.RALLY)
    assert leader.get_move_for_roll(bc, 49).name in {"Encourage", "Stab"}  # 内层 roll2
    force_intent(leader, GremlinLeader.STAB)
    assert leader.get_move_for_roll(bc, 49).name == "Rally"
    force_intent(leader, GremlinLeader.ENCOURAGE)
    assert leader.get_move_for_roll(bc, 79).name == "Stab"
    force_intent(leader, GremlinLeader.STAB)
    assert leader.get_move_for_roll(bc, 80).name in {"Rally", "Encourage"}  # 内层 roll2
    force_intent(leader, GremlinLeader.RALLY)
    assert leader.get_move_for_roll(bc, 80).name == "Stab"

    bc, leader = _leader_battle(2)
    force_intent(leader, GremlinLeader.ENCOURAGE)
    assert leader.get_move_for_roll(bc, 65).name == "Stab"
    force_intent(leader, GremlinLeader.STAB)
    assert leader.get_move_for_roll(bc, 65).name == "Encourage"
    force_intent(leader, GremlinLeader.RALLY)
    assert leader.get_move_for_roll(bc, 0).name == "Encourage"


# ---- Book of Stabbing ----


def test_book_of_stabbing_initial_state():
    bc = act2_battle("book_of_stabbing")
    m = bc.monsters.monsters[0]
    assert isinstance(m, BookOfStabbing)
    assert m.statuses.get(MonsterStatus.PAINFUL_STABS) == 1
    # 计数起点 1；开局 roll 若选中 Multi Stab 则已 +1（C++ 同此行为）
    assert m.misc_info in (1, 2)
    assert m.current_move.name in {"Single Stab", "Multi Stab"}


def test_book_of_stabbing_painful_stabs_trigger():
    """玩家每打出攻击牌受 1 伤（引擎 on_use_attack_card）。"""
    bc = act2_battle("book_of_stabbing")
    m = bc.monsters.monsters[0]
    hp0 = m.hp
    play_strike(bc, target=0)
    assert m.hp == hp0 - 6  # Strike 打怪
    assert bc.player.hp == PLAYER_MAX_HP - 1  # 痛苦刺击：玩家打攻击牌受 1 伤


def test_book_of_stabbing_moves_and_count_growth():
    bc = act2_battle("book_of_stabbing")
    m = bc.monsters.monsters[0]
    force_intent(m, BookOfStabbing.SINGLE_STAB)
    bc.end_turn()
    assert bc.player.hp == PLAYER_MAX_HP - 21
    # 计数在选 Multi Stab 时 +1：首段 2
    m.misc_info = 1
    m.move_history.clear()
    assert m.get_move_for_roll(bc, 50).name == "Multi Stab"
    assert m.misc_info == 2
    m.misc_info = 2
    force_intent(m, BookOfStabbing.MULTI_STAB)
    hp0 = bc.player.hp
    bc.end_turn()
    assert bc.player.hp == hp0 - 12  # 6×2


def test_book_of_stabbing_roll_segments():
    bc = act2_battle("book_of_stabbing")
    m = bc.monsters.monsters[0]
    force_intent(m, BookOfStabbing.SINGLE_STAB)
    assert m.get_move_for_roll(bc, 14).name == "Multi Stab"
    force_intent(m, BookOfStabbing.MULTI_STAB)
    assert m.get_move_for_roll(bc, 14).name == "Single Stab"
    set_history(m, BookOfStabbing.MULTI_STAB, BookOfStabbing.MULTI_STAB)
    c0 = m.misc_info
    assert m.get_move_for_roll(bc, 50).name == "Single Stab"
    assert m.misc_info == c0  # Single Stab 不加计数
    set_history(m, BookOfStabbing.SINGLE_STAB, BookOfStabbing.MULTI_STAB)
    assert m.get_move_for_roll(bc, 50).name == "Multi Stab"
    assert m.misc_info == c0 + 1


# ---- Bronze Automaton & Bronze Orb ----


def test_bronze_automaton_encounter_layout():
    for seed in range(10):
        bc = act2_battle("automaton", seed=seed)
        group = bc.monsters
        assert group.monster_count == 3
        assert group.alive_count == 1
        assert group.monsters[0].is_dead_or_escaped()
        assert group.monsters[2].is_dead_or_escaped()
        m = group.monsters[1]
        assert isinstance(m, BronzeAutomaton)
        assert m.hp == 300
        assert m.statuses.get(MonsterStatus.ARTIFACT) == 3
        assert m.statuses.has(MonsterStatus.MINION_LEADER)
        assert m.current_move.name == "Spawn Orbs"


def test_bronze_automaton_spawn_orbs_first_turn():
    """首回合召球：槽 0/2 各生成青铜球（MINION、有意图），本回合不行动。"""
    bc = act2_battle("automaton")
    group = bc.monsters
    bc.end_turn()
    assert group.alive_count == 3
    orb1, orb2 = group.monsters[0], group.monsters[2]
    assert isinstance(orb1, BronzeOrb) and isinstance(orb2, BronzeOrb)
    assert 52 <= orb1.hp <= 58 and 52 <= orb2.hp <= 58
    for orb in (orb1, orb2):
        assert orb.statuses.has(MonsterStatus.MINION)
        assert orb.current_move is not None
        assert orb.turns_taken == 0  # 本回合不行动（C++ ++monsterTurnIdx）
    assert group.monsters[1].current_move.name == "Flail"


def test_bronze_automaton_flail_boost_hyper_beam_cycle():
    bc = act2_battle("automaton")
    m = bc.monsters.monsters[1]
    # 槽 0/2 是死亡占位（不行动、不可 slay——占位 die 会误判全员死亡）
    force_intent(m, BronzeAutomaton.FLAIL)
    hp0 = bc.player.hp
    bc.end_turn()
    assert bc.player.hp == hp0 - 14  # 7×2
    assert m.current_move.name == "Boost"
    force_intent(m, BronzeAutomaton.BOOST)
    m.misc_info = 0
    bc.end_turn()
    assert m.statuses.get(MonsterStatus.STRENGTH) == 3
    assert m.block == 9
    assert m.current_move.name == "Flail"  # misc 翻转：首 Boost 后接 Flail
    force_intent(m, BronzeAutomaton.BOOST)
    m.misc_info = 1
    bc.end_turn()
    assert m.current_move.name == "Hyper Beam"  # 第二次 Boost 后接超光束
    force_intent(m, BronzeAutomaton.HYPER_BEAM)
    hp0 = bc.player.hp
    bc.end_turn()
    assert bc.player.hp == hp0 - 51  # 45 + 两次充能累计的 6 力量
    assert m.current_move.name == "Stunned"  # A0：超光束后眩晕
    force_intent(m, BronzeAutomaton.STUNNED)
    bc.end_turn()
    assert m.current_move.name == "Flail"


def test_bronze_automaton_a19_hyper_beam_skips_stun():
    bc = act2_battle("automaton", ascension=19)
    m = bc.monsters.monsters[1]
    force_intent(m, BronzeAutomaton.HYPER_BEAM)
    bc.end_turn()
    assert m.current_move.name == "Boost"


def test_bronze_automaton_a4_a9_boost():
    bc = act2_battle("automaton", ascension=4)
    m = bc.monsters.monsters[1]
    force_intent(m, BronzeAutomaton.FLAIL)
    bc.end_turn()
    assert bc.player.hp == PLAYER_MAX_HP - 16  # 8×2
    force_intent(m, BronzeAutomaton.BOOST)
    bc.end_turn()
    assert m.statuses.get(MonsterStatus.STRENGTH) == 4
    assert m.block == 9  # 格挡要 A9 才 +12（C++ 与 wiki 的分歧点，以 C++ 为准）
    bc9 = act2_battle("automaton", ascension=9)
    m9 = bc9.monsters.monsters[1]
    force_intent(m9, BronzeAutomaton.BOOST)
    bc9.end_turn()
    assert m9.block == 12


def test_bronze_automaton_death_wins_with_orbs_alive():
    bc = act2_battle("automaton")
    bc.end_turn()  # 召球
    slay(bc, 1)
    assert bc.won  # MINION_LEADER：主死即胜，青铜球仍在场


def test_bronze_orb_stasis_steals_once():
    """静滞：从抽牌堆偷 1 张（misc 流随机），每场一次；死后归还弃牌堆。"""
    bc = act2_battle("automaton")
    bc.end_turn()  # 召球（球意图已 roll）
    orb, automaton, orb2 = bc.monsters.monsters[0], bc.monsters.monsters[1], bc.monsters.monsters[2]
    force_intent(automaton, BronzeAutomaton.STUNNED)  # 隔离自律机（眩晕无动作）
    force_intent(orb2, BronzeOrb.SUPPORT_BEAM)  # 隔离另一只球（不动牌堆）
    total_before = len(bc.cards.draw_pile) + len(bc.cards.hand) + len(bc.cards.discard_pile)
    force_intent(orb, BronzeOrb.STASIS)
    bc.end_turn()
    total_after = len(bc.cards.draw_pile) + len(bc.cards.hand) + len(bc.cards.discard_pile)
    assert total_after == total_before - 1  # 一张牌离开所有可见区
    assert len(orb.stasis_cards) == 1
    assert orb.misc_info == 1
    assert orb.statuses.has(MonsterStatus.STASIS)
    # 已用过 Stasis：此后 roll 永不再出
    assert orb.get_move_for_roll(bc, 99).name == "Support Beam"
    assert orb.get_move_for_roll(bc, 99).name != "Stasis"
    # 归还：球死亡时进弃牌堆（引擎 die() 的 STASIS 分支）
    slay(bc, 0)
    assert len(orb.stasis_cards) == 0
    total_final = len(bc.cards.draw_pile) + len(bc.cards.hand) + len(bc.cards.discard_pile)
    assert total_final == total_before


def test_bronze_orb_roll_segments():
    bc = act2_battle("automaton")
    bc.end_turn()
    orb = bc.monsters.monsters[0]
    orb.misc_info = 0
    set_history(orb, BronzeOrb.BEAM)
    assert orb.get_move_for_roll(bc, 25).name == "Stasis"  # 未用 + roll≥25
    assert orb.get_move_for_roll(bc, 24).name == "Beam"  # roll<25 跳过 Stasis
    orb.misc_info = 1  # 已用 Stasis
    set_history(orb, BronzeOrb.BEAM)
    assert orb.get_move_for_roll(bc, 70).name == "Support Beam"
    set_history(orb, BronzeOrb.BEAM, BronzeOrb.BEAM)
    assert orb.get_move_for_roll(bc, 71).name == "Support Beam"  # Beam 连续两回合
    set_history(orb, BronzeOrb.SUPPORT_BEAM, BronzeOrb.SUPPORT_BEAM)
    assert orb.get_move_for_roll(bc, 71).name == "Beam"  # Support 连续两回合 → Beam


def test_bronze_orb_beam_and_support_beam():
    bc = act2_battle("automaton")
    bc.end_turn()  # 召球
    group = bc.monsters
    orb, automaton, orb2 = group.monsters[0], group.monsters[1], group.monsters[2]
    force_intent(automaton, BronzeAutomaton.STUNNED)  # 隔离自律机
    force_intent(orb2, BronzeOrb.SUPPORT_BEAM)  # 隔离另一只球（其支援给自律机格挡）
    force_intent(orb, BronzeOrb.BEAM)
    hp0 = bc.player.hp
    bc.end_turn()
    assert bc.player.hp == hp0 - 8
    force_intent(automaton, BronzeAutomaton.STUNNED)
    force_intent(orb2, BronzeOrb.SUPPORT_BEAM)
    force_intent(orb, BronzeOrb.SUPPORT_BEAM)
    block0 = automaton.block
    bc.end_turn()
    assert automaton.block == block0 + 12


# ---- The Collector & Torch Head ----


def test_collector_encounter_layout():
    for seed in range(10):
        bc = act2_battle("collector", seed=seed)
        group = bc.monsters
        assert group.monster_count == 3
        assert group.alive_count == 1
        assert group.monsters[0].is_dead_or_escaped()
        assert group.monsters[1].is_dead_or_escaped()
        m = group.monsters[2]
        assert isinstance(m, TheCollector)
        assert m.hp == 282
        assert m.statuses.has(MonsterStatus.MINION_LEADER)
        assert m.current_move.name == "Spawn"


def test_collector_spawn_fills_torch_heads():
    """首回合 Spawn：槽 1、0 各生成火把头（MINION、意图固定冲撞）。"""
    bc = act2_battle("collector")
    group = bc.monsters
    bc.end_turn()
    assert group.alive_count == 3
    torch1, torch0 = group.monsters[1], group.monsters[0]
    assert isinstance(torch1, TorchHead) and isinstance(torch0, TorchHead)
    for t in (torch0, torch1):
        assert 38 <= t.hp <= 40
        assert t.statuses.has(MonsterStatus.MINION)
        assert t.current_move.name == "Tackle"
        assert t.turns_taken == 0  # 本回合不行动（在收藏家之后生成）
    assert group.monsters[2].current_move.name != "Spawn"  # 上回合 Spawn 不重复


def test_collector_fireball_buff_mega_debuff():
    bc = act2_battle("collector")
    bc.end_turn()  # Spawn
    group = bc.monsters
    collector = group.monsters[2]
    t0, t1 = group.monsters[0], group.monsters[1]
    force_intent(collector, TheCollector.FIREBALL)
    hp0 = bc.player.hp
    bc.end_turn()
    assert bc.player.hp == hp0 - 18 - 14  # 火球 18 + 两只火把头冲撞 7×2
    force_intent(collector, TheCollector.BUFF)
    bc.end_turn()
    assert t0.statuses.get(MonsterStatus.STRENGTH) == 3
    assert t1.statuses.get(MonsterStatus.STRENGTH) == 3
    assert collector.statuses.get(MonsterStatus.STRENGTH) == 3
    assert collector.block == 15
    # 第 3 回合末的 roll 恒出 Mega Debuff（getMonsterTurnNumber()==3）
    assert collector.current_move.name == "Mega Debuff"
    bc.end_turn()  # 第 4 回合执行
    assert bc.player.statuses.get(PlayerStatus.WEAK) == 3
    assert bc.player.statuses.get(PlayerStatus.VULNERABLE) == 3
    assert bc.player.statuses.get(PlayerStatus.FRAIL) == 3


def test_collector_spawn_refills_dead_slots():
    bc = act2_battle("collector")
    bc.end_turn()  # Spawn 补满
    group = bc.monsters
    slay(bc, 0)  # 杀一只火把头
    assert group.alive_count == 2
    collector = group.monsters[2]
    force_intent(collector, TheCollector.SPAWN)
    bc.end_turn()
    assert group.alive_count == 3
    assert isinstance(group.monsters[0], TorchHead)
    assert group.monsters[0].current_move.name == "Tackle"


def test_collector_death_wins_with_torch_heads():
    bc = act2_battle("collector")
    bc.end_turn()  # Spawn
    slay(bc, 2)
    assert bc.won  # MINION_LEADER：主死即胜


# ---- The Champ ----


def _fresh_champ(ascension: int = 0, seed: int = 0):
    bc = act2_battle("champ", seed=seed, ascension=ascension)
    m = bc.monsters.monsters[0]
    m.misc_info = 0  # 重置开局 roll 可能消耗的防御姿态计数
    m.move_history.clear()
    return bc, m


def test_champ_phase1_roll_segments():
    bc, m = _fresh_champ()
    assert m.get_move_for_roll(bc, 0).name == "Defensive Stance"
    assert m.misc_info & 0x3 == 1
    m.misc_info = 0
    m.move_history.clear()
    assert m.get_move_for_roll(bc, 15).name == "Defensive Stance"
    assert m.get_move_for_roll(bc, 16).name == "Gloat"
    assert m.get_move_for_roll(bc, 30).name == "Gloat"
    assert m.get_move_for_roll(bc, 31).name == "Face Slap"
    assert m.get_move_for_roll(bc, 55).name == "Face Slap"
    assert m.get_move_for_roll(bc, 56).name == "Heavy Slash"
    set_history(m, TheChamp.HEAVY_SLASH)
    assert m.get_move_for_roll(bc, 99).name == "Face Slap"
    set_history(m, TheChamp.DEFENSIVE_STANCE)
    m.misc_info = 0
    assert m.get_move_for_roll(bc, 0).name == "Face Slap"  # 上回合防御 → 本回合非防御
    # 防御姿态最多 2 次（低 2 位计数）
    m.misc_info = 2
    set_history(m, TheChamp.GLOAT)
    assert m.get_move_for_roll(bc, 0).name == "Face Slap"


def test_champ_taunt_every_fourth_turn():
    """(turn+1)%4==0 → Taunt（roll 无关；第 3 回合末 roll 出第 4 回合的嘲讽）。"""
    bc, m = _fresh_champ()
    bc.turn = 3
    assert m.get_move_for_roll(bc, 99).name == "Taunt"
    assert m.get_move_for_roll(bc, 0).name == "Taunt"
    bc.turn = 4
    m.move_history.clear()
    assert m.get_move_for_roll(bc, 50).name != "Taunt"
    # 全程模拟：第 4 回合执行 Taunt
    bc2 = act2_battle("champ")
    champ = bc2.monsters.monsters[0]
    executed = []
    for _ in range(5):
        executed.append(champ.current_move.name)
        bc2.end_turn()
    assert executed[3] == "Taunt"  # 第 4 回合执行的是第 3 回合末 roll 的意图


def test_champ_anger_phase_transition():
    """HP < 半 → Anger（移除削弱 + 力量）→ 二阶段 Execute 主导。"""
    bc, m = _fresh_champ()
    m.statuses.add(MonsterStatus.WEAK, 2)
    m.statuses.add(MonsterStatus.VULNERABLE, 3)
    m.statuses.add(MonsterStatus.POISON, 2)
    m.hp = m.max_hp // 2 - 1
    assert m.get_move_for_roll(bc, 99).name == "Anger"
    assert m.misc_info & 0x4
    force_intent(m, TheChamp.ANGER)
    bc.end_turn()
    assert not m.statuses.has(MonsterStatus.WEAK)
    assert not m.statuses.has(MonsterStatus.VULNERABLE)
    assert not m.statuses.has(MonsterStatus.POISON)
    assert m.statuses.get(MonsterStatus.STRENGTH) == 6
    # 二阶段：Execute 未连续 → Execute
    m.move_history.clear()
    assert m.get_move_for_roll(bc, 0).name == "Execute"
    set_history(m, TheChamp.EXECUTE)
    # Execute 出现过一次后回落通用段（防御/嘲讽/掌掴/重斩）
    assert m.get_move_for_roll(bc, 0).name in {"Gloat", "Face Slap", "Defensive Stance", "Taunt"}
    set_history(m, TheChamp.EXECUTE, TheChamp.EXECUTE)
    assert m.get_move_for_roll(bc, 56).name == "Heavy Slash"


def test_champ_move_values():
    bc, m = _fresh_champ()
    force_intent(m, TheChamp.HEAVY_SLASH)
    bc.end_turn()
    assert bc.player.hp == PLAYER_MAX_HP - 16
    force_intent(m, TheChamp.FACE_SLAP)
    bc.end_turn()
    assert bc.player.hp == PLAYER_MAX_HP - 16 - 12
    assert bc.player.statuses.get(PlayerStatus.FRAIL) == 2
    assert bc.player.statuses.get(PlayerStatus.VULNERABLE) == 2
    force_intent(m, TheChamp.GLOAT)
    bc.end_turn()
    assert m.statuses.get(MonsterStatus.STRENGTH) == 3
    force_intent(m, TheChamp.EXECUTE)
    hp0 = bc.player.hp
    bc.end_turn()
    # (10 + 得意 3 力量) × 1.5（掌掴的 2 层易伤仍在）× 2 段 = 19×2
    assert bc.player.hp == hp0 - 38
    force_intent(m, TheChamp.TAUNT)
    bc.end_turn()
    assert bc.player.statuses.get(PlayerStatus.WEAK) == 2
    assert bc.player.statuses.get(PlayerStatus.VULNERABLE) == 2
    force_intent(m, TheChamp.DEFENSIVE_STANCE)
    bc.end_turn()
    assert m.block == 15
    assert m.statuses.get(MonsterStatus.METALLICIZE) == 5


def test_champ_ascension_branches():
    bc, m = _fresh_champ(ascension=4)
    force_intent(m, TheChamp.HEAVY_SLASH)
    bc.end_turn()
    assert bc.player.hp == PLAYER_MAX_HP - 18
    force_intent(m, TheChamp.FACE_SLAP)
    bc.end_turn()
    assert bc.player.hp == PLAYER_MAX_HP - 18 - 14
    force_intent(m, TheChamp.GLOAT)
    bc.end_turn()
    assert m.statuses.get(MonsterStatus.STRENGTH) == 4  # A4：+4（wiki 记 +3，以 C++ 为准）
    m.hp = 100
    force_intent(m, TheChamp.ANGER)
    bc.end_turn()
    assert m.statuses.get(MonsterStatus.STRENGTH) == 4 + 9  # 得意 4 + 愤怒 9

    # A9：防御姿态 18 格挡 + 6 金属化；A19：20/7、Gloat+5、Anger+12、阈值 30
    bc9, m9 = _fresh_champ(ascension=9)
    force_intent(m9, TheChamp.DEFENSIVE_STANCE)
    bc9.end_turn()
    assert m9.block == 18
    assert m9.statuses.get(MonsterStatus.METALLICIZE) == 6

    bc19, m19 = _fresh_champ(ascension=19)
    m19.move_history.clear()
    assert m19.get_move_for_roll(bc19, 30).name == "Defensive Stance"  # 阈值 30
    force_intent(m19, TheChamp.DEFENSIVE_STANCE)
    bc19.end_turn()
    assert m19.block == 20
    assert m19.statuses.get(MonsterStatus.METALLICIZE) == 7
    m19.statuses.remove(MonsterStatus.METALLICIZE)
    force_intent(m19, TheChamp.GLOAT)
    bc19.end_turn()
    assert m19.statuses.get(MonsterStatus.STRENGTH) == 5
    m19.hp = 100
    force_intent(m19, TheChamp.ANGER)
    bc19.end_turn()
    assert m19.statuses.get(MonsterStatus.STRENGTH) == 5 + 12

"""遭遇装配：把牌组与敌人实例化进 BattleContext。

引擎层 BattleContext._init_content 调用本模块的 setup_encounter(bc)。
扩遭遇 = 注册新的 encounter 名 + 装配函数（多敌人战斗在此生成怪物组，
怪物按加入顺序 = 索引 = 行动顺序，HP 依次从 monster_hp 流抽样）。

已注册遭遇（A0）：
    cultist      邪教徒 ×1
    jaw_worm     颚虫 ×1
    louses       红虱 ×1 + 绿虱 ×1
    slimes_s     酸液史莱姆（小）×1 + 尖刺史莱姆（小）×1
    fungi_beast  真菌兽 ×1
    two_fungi_beasts   真菌兽 ×2
    three_louse        虱子 ×3（红绿按 misc 流逐只抽样）
    small_slimes       小史莱姆：1×S + 1×M（尖 S+酸 M / 酸 S+尖 M 二选一）
    exordium_wildlife  荒野生物：Fungi/Jaw Worm + 虱/M 史莱姆（misc 流组合）
    gremlin_gang       小鬼帮：从 8 槽 Gremlin 池无放回抽 4（批次 2 起）
    slavers            蓝奴役者 + 监工 + 红奴役者（批次 2 补中间位监工）
    three_sentries     哨卫 ×3（首招按 idx 奇偶分 Bolt/Beam）
    gremlin_nob        小鬼巨汉 ×1（精英）
    lagavulin          拉格维林 ×1（精英）
    guardian           守卫者 ×1（Boss）
    hexaghost          六火幽灵 ×1（Boss）

组合抽样统一走 misc 流（对齐 lightspeed 的 miscRng 用途划分；
DESIGN.md §3 不做轨迹对齐，分布级等价即可）。
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from sts.content.cards import starting_deck
from sts.content.monsters import (
    AcidSlimeM,
    AcidSlimeS,
    BlueSlaver,
    Cultist,
    FatGremlin,
    FungiBeast,
    GremlinNob,
    GreenLouse,
    GremlinWizard,
    Hexaghost,
    JawWorm,
    Lagavulin,
    MadGremlin,
    RedLouse,
    RedSlaver,
    Sentry,
    ShieldGremlin,
    SneakyGremlin,
    SpikeSlimeM,
    SpikeSlimeS,
    Taskmaster,
    TheGuardian,
)

if TYPE_CHECKING:
    from sts.combat.battle import BattleContext
    from sts.combat.entities import Monster


def _add_starting_deck(bc: BattleContext) -> None:
    for card in starting_deck():
        bc.cards.create_deck_card_in_draw_pile(card)


def _spawn(bc: BattleContext, *monster_classes: type[Monster]) -> None:
    """按顺序生成怪物组（idx = 行动顺序），再装入玩家牌组。"""
    for idx, cls in enumerate(monster_classes):
        bc.monsters.add(cls.create(bc, idx))
    _add_starting_deck(bc)


def _setup_cultist(bc: BattleContext) -> None:
    _spawn(bc, Cultist)


def _setup_jaw_worm(bc: BattleContext) -> None:
    _spawn(bc, JawWorm)


def _setup_louses(bc: BattleContext) -> None:
    _spawn(bc, RedLouse, GreenLouse)


def _setup_slimes_s(bc: BattleContext) -> None:
    _spawn(bc, AcidSlimeS, SpikeSlimeS)


def _setup_fungi_beast(bc: BattleContext) -> None:
    _spawn(bc, FungiBeast)


# ---- 批次 1：含组合抽样的遭遇（misc 流，对齐 lightspeed MonsterGroup.cpp）----


def _misc_boolean(bc: BattleContext) -> bool:
    """misc 流 50/50 布尔（对齐 lightspeed miscRng.randomBoolean()）。"""
    return bc.rngs.misc.int_inclusive(0, 1) == 1


def _sample_without_replacement(bc: BattleContext, pool: list, n: int) -> list:
    """无放回抽 n 个（对齐 lightspeed 的 lastIdx 前移删法，misc 流）。

    C++ 逐个抽 pool[miscRng.random(lastIdx)] 后把尾部前移压缩；等价于
    抽中即删。gremlin_gang 自批次 2（Mad Gremlin 入池）起走此路径。
    """
    pool = list(pool)
    picked = []
    last = len(pool) - 1
    for _ in range(n):
        i = bc.rngs.misc.int_inclusive(0, last)
        picked.append(pool[i])
        del pool[i]
        last -= 1
    return picked


def _get_louse(bc: BattleContext) -> type[Monster]:
    """对齐 MonsterGroup::getLouse：misc 布尔选红/绿虱。"""
    return RedLouse if _misc_boolean(bc) else GreenLouse


def _setup_two_fungi_beasts(bc: BattleContext) -> None:
    _spawn(bc, FungiBeast, FungiBeast)


def _setup_three_louse(bc: BattleContext) -> None:
    _spawn(bc, _get_louse(bc), _get_louse(bc), _get_louse(bc))


def _setup_small_slimes(bc: BattleContext) -> None:
    # 对齐 MonsterGroup SMALL_SLIMES：二选一配对（尖 S+酸 M / 酸 S+尖 M）
    if _misc_boolean(bc):
        _spawn(bc, SpikeSlimeS, AcidSlimeM)
    else:
        _spawn(bc, AcidSlimeS, SpikeSlimeM)


def _setup_exordium_wildlife(bc: BattleContext) -> None:
    # 对齐 EXORDIUM_WILDLIFE = createStrongWildlife + createWeakWildlife。
    # 虚构候选怪的 HP roll 消耗（C++ temp 数组）不做——无轨迹对齐诉求。
    strong = [FungiBeast, JawWorm][bc.rngs.misc.int_inclusive(0, 1)]
    weak = [_get_louse(bc), SpikeSlimeM, AcidSlimeM][bc.rngs.misc.int_inclusive(0, 2)]
    _spawn(bc, strong, weak)


# Gremlin 池（对齐 C++ 8 槽：Mad×2、Sneaky×2、Fat×2、Shield、Wizard）。
# 批次 2 起 Mad Gremlin 入池，走 misc 无放回抽样。
_GREMLIN_POOL: list = [
    MadGremlin,
    MadGremlin,
    SneakyGremlin,
    SneakyGremlin,
    FatGremlin,
    FatGremlin,
    ShieldGremlin,
    GremlinWizard,
]


def _setup_gremlin_gang(bc: BattleContext) -> None:
    classes = _sample_without_replacement(bc, _GREMLIN_POOL, 4)
    _spawn(bc, *classes)


def _setup_slavers(bc: BattleContext) -> None:
    # 对齐 C++ SLAVERS 槽位顺序：Blue Slaver + Taskmaster + Red Slaver
    _spawn(bc, BlueSlaver, Taskmaster, RedSlaver)


# ---- 批次 2：精英 / Boss 遭遇（单怪）----


def _setup_gremlin_nob(bc: BattleContext) -> None:
    _spawn(bc, GremlinNob)


def _setup_lagavulin(bc: BattleContext) -> None:
    _spawn(bc, Lagavulin)


def _setup_guardian(bc: BattleContext) -> None:
    _spawn(bc, TheGuardian)


def _setup_hexaghost(bc: BattleContext) -> None:
    _spawn(bc, Hexaghost)


def _setup_three_sentries(bc: BattleContext) -> None:
    _spawn(bc, Sentry, Sentry, Sentry)


ENCOUNTERS = {
    "cultist": _setup_cultist,
    "jaw_worm": _setup_jaw_worm,
    "louses": _setup_louses,
    "slimes_s": _setup_slimes_s,
    "fungi_beast": _setup_fungi_beast,
    "two_fungi_beasts": _setup_two_fungi_beasts,
    "three_louse": _setup_three_louse,
    "small_slimes": _setup_small_slimes,
    "exordium_wildlife": _setup_exordium_wildlife,
    "gremlin_gang": _setup_gremlin_gang,
    "slavers": _setup_slavers,
    "three_sentries": _setup_three_sentries,
    "gremlin_nob": _setup_gremlin_nob,
    "lagavulin": _setup_lagavulin,
    "guardian": _setup_guardian,
    "hexaghost": _setup_hexaghost,
}


def setup_encounter(bc: BattleContext) -> None:
    if bc.encounter not in ENCOUNTERS:
        raise ValueError(f"未知遭遇：{bc.encounter}（可选：{sorted(ENCOUNTERS)}）")
    ENCOUNTERS[bc.encounter](bc)

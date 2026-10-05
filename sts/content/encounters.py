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
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from sts.content.cards import starting_deck
from sts.content.monsters import (
    AcidSlimeS,
    Cultist,
    FungiBeast,
    GreenLouse,
    JawWorm,
    RedLouse,
    SpikeSlimeS,
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


ENCOUNTERS = {
    "cultist": _setup_cultist,
    "jaw_worm": _setup_jaw_worm,
    "louses": _setup_louses,
    "slimes_s": _setup_slimes_s,
    "fungi_beast": _setup_fungi_beast,
}


def setup_encounter(bc: BattleContext) -> None:
    if bc.encounter not in ENCOUNTERS:
        raise ValueError(f"未知遭遇：{bc.encounter}（可选：{sorted(ENCOUNTERS)}）")
    ENCOUNTERS[bc.encounter](bc)

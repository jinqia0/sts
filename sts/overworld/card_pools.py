"""局外卡池（Phase 3a，2026-10-08）。

卡牌奖励/商店/事件"变化"用的稀有度分层池，数据源与 run_env 同：
wiki_data/cards.json（rarity/color 字段，官方 dump 归档）+ 源码补齐两张
（Rage、Hand of Greed，见 run_env.py 模块头说明）。

池语义对齐本体 AbstractDungeon.initializeCardPools（java:1115-1199）：
- 本职业池（红）按 rarity 分桶——卡牌奖励 / 商店彩色槽 / 事件"变化"默认池
- 全职业池——棱镜碎片（PrismaticShard）持有时的奖励池
- 无色池（uncommon/rare）——商店两个无色槽
- 诅咒池——事件掉诅咒用，排除不可移除类（AscendersBane /
  CurseOfTheBell / Necronomicurse / Pride，java:1189-1199）

池为模块级只读常量（CardDef 单例不可变），初始化不洗牌、不耗 RNG。
"""

from __future__ import annotations

import json
import pathlib

from sts.content.cards import CardDef
from sts.content.cards import colorless as cards_colorless
from sts.content.cards import ironclad as cards_ironclad

_NON_REMOVABLE_CURSES = {"Ascender's Bane", "Curse of the Bell", "Necronomicurse", "Pride"}


def _wiki_index() -> dict[str, dict]:
    path = pathlib.Path(__file__).parent.parent.parent / "wiki_data" / "cards.json"
    return {c["name"]: c for c in json.load(open(path))["cards"]}


def _module_cards(module) -> list[CardDef]:
    """模块级 CardDef 单例扫描（vars() 动态发现，新卡即自动入池）。"""
    seen: set[int] = set()
    out: list[CardDef] = []
    for k, d in vars(module).items():
        if k.startswith("_") or not isinstance(d, CardDef) or id(d) in seen:
            continue
        seen.add(id(d))
        out.append(d)
    return out


def _build() -> tuple[dict[str, list[CardDef]], dict[str, list[CardDef]], dict[str, list[CardDef]], list[CardDef]]:
    wiki = _wiki_index()
    own: dict[str, list[CardDef]] = {"common": [], "uncommon": [], "rare": []}
    any_color: dict[str, list[CardDef]] = {"common": [], "uncommon": [], "rare": []}
    colorless: dict[str, list[CardDef]] = {"uncommon": [], "rare": []}

    for d in _module_cards(cards_ironclad):
        w = wiki.get(d.name)
        if w is None:
            continue
        rar = (w.get("rarity") or "").lower()
        if rar in own:
            own[rar].append(d)
            any_color[rar].append(d)
    # 源码补齐两张（wiki 缺页；本体分类 Ironclad）
    own["uncommon"].append(cards_ironclad.RAGE)
    any_color["uncommon"].append(cards_ironclad.RAGE)
    own["rare"].append(cards_colorless.HAND_OF_GREED)
    any_color["rare"].append(cards_colorless.HAND_OF_GREED)

    # 全职业池（棱镜碎片）：绿/蓝/紫模块按 wiki rarity 入桶
    from sts.content.cards import defect as cards_defect
    from sts.content.cards import silent as cards_silent
    from sts.content.cards import watcher as cards_watcher

    for module in (cards_silent, cards_defect, cards_watcher):
        for d in _module_cards(module):
            w = wiki.get(d.name)
            if w is None:
                continue
            rar = (w.get("rarity") or "").lower()
            if rar in any_color:
                any_color[rar].append(d)

    for d in _module_cards(cards_colorless):
        w = wiki.get(d.name)
        if w is None:
            continue
        rar = (w.get("rarity") or "").lower()
        if rar in colorless and w.get("color") == "Colorless":
            colorless[rar].append(d)

    from sts.content.cards import curses as cards_curses

    curse_pool = [d for d in _module_cards(cards_curses) if d.name not in _NON_REMOVABLE_CURSES]
    return own, any_color, colorless, curse_pool


OWN_POOLS, ANY_COLOR_POOLS, COLORLESS_POOLS, CURSE_POOL = _build()
# 短名（relic_effects 等模块用）
POOLS = OWN_POOLS

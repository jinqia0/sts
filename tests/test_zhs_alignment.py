"""官方本地化对齐锁：content 层中文名/描述与 sts_game_data/localization/zhs
一致（2026-10-07 对齐批次后防回归）。

对齐口径见 scripts/align_zhs.py 模块注释。此处校验不依赖反编译源码
（那属于数值层），只锁名称与文本格式：
- 卡牌 zh == 官方 NAME；text 无占位符/图标标记/自造升级注记残留
- 怪物类 zh == 官方 NAME
- 药水 zh == 官方 NAME
- RELIC_ZH 覆盖全部 RelicId 且无英文回落
"""

from __future__ import annotations

import json
import re
import sys
from collections import defaultdict
from importlib.util import module_from_spec, spec_from_file_location
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from sts.combat.relics import RelicId, RELIC_ZH  # noqa: E402
from sts.content.cards import CardDef  # noqa: E402
from sts.content.cards import colorless as cards_colorless  # noqa: E402
from sts.content.cards import curses as cards_curses  # noqa: E402
from sts.content.cards import defect as cards_defect  # noqa: E402
from sts.content.cards import ironclad as cards_ironclad  # noqa: E402
from sts.content.cards import silent as cards_silent  # noqa: E402
from sts.content.cards import status as cards_status  # noqa: E402
from sts.content.cards import watcher as cards_watcher  # noqa: E402
from sts.content import monsters as monsters_mod  # noqa: E402
from sts.content.monsters import Monster  # noqa: E402
from sts.content.potions import ALL_POTIONS  # noqa: E402

_spec = spec_from_file_location("align_zhs", ROOT / "scripts/align_zhs.py")
align = module_from_spec(_spec)
_spec.loader.exec_module(align)


def _load_zhs(name: str) -> dict:
    with open(ROOT / f"sts_game_data/localization/zhs/{name}.json",
              encoding="utf-8") as f:
        return json.load(f)


# ---------------------------------------------------------------- 卡牌

_CARD_MODULES = [
    ("ironclad", cards_ironclad), ("silent", cards_silent),
    ("defect", cards_defect), ("watcher", cards_watcher),
    ("colorless", cards_colorless), ("curses", cards_curses),
    ("status", cards_status),
]

_TEXT_FORBIDDEN = re.compile(r"!D!|!B!|!M!|NL|\[[RGBW]\]|#[a-z]|（升级")


def test_all_cards_match_official_names():
    zhs = _load_zhs("cards")
    n = 0
    for module_key, mod in _CARD_MODULES:
        for varname, obj in vars(mod).items():
            if varname.startswith("_") or not isinstance(obj, CardDef):
                continue
            key = align.card_key_for(obj.name, module_key)
            assert key is not None, f"{module_key}:{varname} 官方无条目"
            assert obj.zh == zhs[key]["NAME"], (
                f"{module_key}:{obj.name} 中文名 {obj.zh!r} != 官方 "
                f"{zhs[key]['NAME']!r}")
            n += 1
    assert n >= 370  # 全量内容迁移规模下限


def test_card_texts_are_processed_official_text():
    """描述已代入数值、无占位符/图标/自造注记残留。"""
    for module_key, mod in _CARD_MODULES:
        for varname, obj in vars(mod).items():
            if varname.startswith("_") or not isinstance(obj, CardDef):
                continue
            m = _TEXT_FORBIDDEN.search(obj.text)
            assert m is None, (
                f"{module_key}:{obj.name} 描述残留官方标记 {m.group(0)!r}："
                f"{obj.text!r}")


# ---------------------------------------------------------------- 怪物

def test_all_monsters_match_official_names():
    zhs = _load_zhs("monsters")
    for varname, obj in vars(monsters_mod).items():
        if (varname.startswith("_") or not isinstance(obj, type)
                or not issubclass(obj, Monster) or obj is Monster
                or obj.__module__ != monsters_mod.__name__):
            continue
        loc_key = align._monster_loc_key(varname, getattr(obj, "name", varname))
        if loc_key is None:
            # 事件占位怪（_SlotPlaceholder 等已过滤）；基类 Louse 无独立条目
            assert varname in ("Louse",), f"{varname} 官方无条目"
            continue
        assert obj.zh == zhs[loc_key]["NAME"], (
            f"{varname} 中文名 {obj.zh!r} != 官方 {zhs[loc_key]['NAME']!r}")


# ---------------------------------------------------------------- 药水

def test_all_potions_match_official_names():
    zhs = _load_zhs("potions")
    by_norm = {re.sub(r"[^a-z0-9]", "", k.lower()): v["NAME"]
               for k, v in zhs.items()}
    for pd in ALL_POTIONS:
        key = re.sub(r"[^a-z0-9]", "", pd.pid.lower())
        official = by_norm.get(key) or by_norm.get(
            re.sub(r"[^a-z0-9]", "", pd.name.lower()))
        assert official is not None, f"{pd.pid} 官方无条目"
        assert pd.zh == official, (
            f"{pd.pid} 中文名 {pd.zh!r} != 官方 {official!r}")


# ---------------------------------------------------------------- 遗物

def test_relic_zh_covers_all_relic_ids():
    for rid in RelicId:
        zh = RELIC_ZH.get(rid)
        assert zh is not None, f"{rid.name} 未收录中文名"
        assert re.search(r"[㐀-鿿]", zh), (
            f"{rid.name} 中文名为英文回落：{zh!r}")

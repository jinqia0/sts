"""词表锁测试（批次 5a）：sts/vocab.py 的字面量必须与内容层活枚举一致。

内容层任何改动（增删卡/怪/药水）若没有重跑 scripts/gen_vocab.py，
本文件直接失败——迫使改动者显式重生成，保证已分配词表索引永不
重排（DESIGN.md §5.2：旧 checkpoint 的观测语义不能漂移）。
"""

import importlib.util

import pytest

from sts.combat.relics import RelicId
from sts.combat.entities import Monster
from sts.content import monsters as monsters_mod
from sts.content import potions as potions_mod
from sts.content.cards import CardDef
from sts.content.potions import PotionDef
from sts.vocab import (
    CARD_INDEX,
    CARD_VOCAB,
    CARD_VOCAB_SIZE,
    CARD_MODULES,
    CHARACTERS,
    CHARACTER_MAX_HP,
    MONSTER_INDEX,
    MONSTER_VOCAB_SIZE,
    POTION_INDEX,
    POTION_VOCAB_SIZE,
    card_vocab_index,
)

# 与生成器同一枚举逻辑（scripts/gen_vocab.py 按路径加载，单一事实源）
_spec = importlib.util.spec_from_file_location(
    "gen_vocab", __file__.rsplit("/", 2)[0] + "/scripts/gen_vocab.py"
)
_gen = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_gen)


# ---- 卡牌词表 ----


def test_card_vocab_locked_to_content():
    """字面量 CARD_VOCAB 与活枚举逐项一致（内容变动未重生成即失败）。"""
    live = _gen.enumerate_card_ids()
    assert CARD_VOCAB == live
    assert len(CARD_VOCAB) == 368
    assert CARD_VOCAB_SIZE == 736
    # id → 词表位一致，全部为偶数（升级版 = 基础位 + 1）
    for cid, base in CARD_INDEX.items():
        assert 0 <= base < CARD_VOCAB_SIZE
        assert base % 2 == 0
        assert CARD_VOCAB[base // 2] == cid


def test_card_vocab_resolves_every_definition():
    """每个 CardDef 定义都能解析到词表位；同名跨职业是不同对象、
    必须得到不同词表位（值相等撞哈希是设计明示的坑）。"""
    from sts.content.cards import STRIKE
    from sts.content.cards.silent import STRIKE_S

    seen: dict[int, str] = {}
    for _modkey, mod in CARD_MODULES:
        for varname, obj in vars(mod).items():
            if varname.startswith("_") or not isinstance(obj, CardDef):
                continue
            idx = card_vocab_index(obj)
            assert idx is not None, f"{varname} 未收录进词表"
            assert idx % 2 == 0
            # 同一对象只允许一个词表位（跨模块 re-export 去重）
            assert seen.setdefault(id(obj), CARD_VOCAB[idx // 2]) == CARD_VOCAB[idx // 2]
    # 铁甲 Strike 与静默 Strike_S：值全同的不同对象 → 词表位必须不同
    assert card_vocab_index(STRIKE) != card_vocab_index(STRIKE_S)
    # 状态卡归属定义模块（职业模块 re-export 不抢注）
    from sts.content.cards.status import BURN

    assert CARD_VOCAB[card_vocab_index(BURN) // 2] == "status:BURN"


def test_card_vocab_upgrade_slot_layout():
    """升级版词表位 = 基础位 + 1（观测四堆计数按 (卡, 升级) 分维）。"""
    from sts.content.cards import STRIKE

    base = card_vocab_index(STRIKE)
    assert CARD_INDEX["ironclad:STRIKE"] == base


# ---- 怪物词表 ----


def test_monster_vocab_locked_to_content():
    """MONSTER_INDEX 键集与活枚举一致；索引连续、在词表界内。"""
    live = _gen.enumerate_monster_names()
    assert set(MONSTER_INDEX) == set(live)
    assert len(MONSTER_INDEX) == 68
    values = sorted(MONSTER_INDEX.values())
    assert values == list(range(68))
    assert MONSTER_VOCAB_SIZE >= len(MONSTER_INDEX)
    # 每个怪物类的 name 都有词表位（观测种类段全覆盖）
    for obj in vars(monsters_mod).values():
        if isinstance(obj, type) and issubclass(obj, Monster) and obj is not Monster:
            assert obj.name in MONSTER_INDEX


# ---- 药水词表 ----


def test_potion_vocab_locked_to_content():
    live = _gen.enumerate_potion_pids()
    assert set(POTION_INDEX) == set(live)
    assert len(POTION_INDEX) == 42
    values = sorted(POTION_INDEX.values())
    assert values == list(range(42))
    assert POTION_VOCAB_SIZE >= len(POTION_INDEX)
    for obj in vars(potions_mod).values():
        if isinstance(obj, PotionDef):
            assert obj.pid in POTION_INDEX


# ---- 遗物与职业 ----


def test_relic_enum_stable():
    """RelicId 是观测编码直接使用的稳定 IntEnum：值连续无重复、且
    历史 0..128 段不被重排（Phase 3a 局外遗物按 129+ 追加——追加合法，
    重排/插位非法：旧 checkpoint 的观测语义漂移）。"""
    values = sorted(r.value for r in RelicId)
    assert values == list(range(len(values)))  # 连续无空洞
    assert len(set(values)) == len(values)  # 无重复
    # 首批 129 个战斗遗物的值域仍在 0..128（追加不重排）
    historical = [v for v in values if v <= 128]
    assert historical == list(range(129))


def test_characters():
    assert CHARACTERS == ("ironclad", "silent", "defect", "watcher")
    assert CHARACTER_MAX_HP == {"ironclad": 80, "silent": 70, "defect": 75, "watcher": 72}

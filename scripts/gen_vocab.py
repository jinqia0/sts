"""生成 sts/vocab.py：全量内容词表的字面量固化（批次 5a，2026-10-07）。

用法：uv run python scripts/gen_vocab.py

内容层已冻结（全量迁移完成），本脚本把当前内容枚举固化成
sts/vocab.py 的字面量列表。**任何内容层改动（增删卡/怪/药水）后必须
重跑本脚本**——tests/test_vocab.py 锁测试会对比字面量与活枚举，不一致
即失败，迫使改动者显式重生成，保证已分配词表索引永不重排
（DESIGN.md §5.2：旧 checkpoint 的观测语义不能漂移）。

顺序与键约定（稳定性的根基）：
- 卡牌 id = "模块:常量名"。CardDef.name 跨职业重名（4 个 Strike），且
  frozen dataclass 值相等（铁甲 Strike 与静默 Strike_S 值全同）——
  所以反查表必须按对象身份（id()）而非值。枚举顺序：中立模块
  （status/curses/colorless）在前、四职业在后——职业模块会 re-export
  状态卡（ironclad 引 BURN/DAZED/WOUND、defect 引 BURN/VOID），先到先得
  保证 id 归属定义模块。同一对象跨模块只计一次（身份去重）。
- 怪物：monsters.py 内定义序，display name（.name 类属性）全 68 个唯一。
- 药水：potions.py 内定义序，pid 全 42 个唯一。
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from sts.combat.entities import Monster
from sts.combat.relics import RelicId
from sts.content import monsters as monsters_mod
from sts.content import potions as potions_mod
from sts.content.cards import CardDef
from sts.content.potions import PotionDef
from sts.content.cards import colorless as cards_colorless
from sts.content.cards import curses as cards_curses
from sts.content.cards import defect as cards_defect
from sts.content.cards import ironclad as cards_ironclad
from sts.content.cards import silent as cards_silent
from sts.content.cards import status as cards_status
from sts.content.cards import watcher as cards_watcher

# 中立模块在前（re-export 的归属仲裁，见模块注释）
CARD_MODULES = [
    ("status", cards_status),
    ("curses", cards_curses),
    ("colorless", cards_colorless),
    ("ironclad", cards_ironclad),
    ("silent", cards_silent),
    ("defect", cards_defect),
    ("watcher", cards_watcher),
]


def enumerate_card_ids() -> list[str]:
    """身份去重的卡牌 id 枚举（先到先得，见模块注释）。"""
    ids: list[str] = []
    seen: set[int] = set()
    for modkey, mod in CARD_MODULES:
        for varname, obj in vars(mod).items():
            if varname.startswith("_") or not isinstance(obj, CardDef):
                continue
            if id(obj) in seen:
                continue
            seen.add(id(obj))
            ids.append(f"{modkey}:{varname}")
    return ids


def enumerate_monster_names() -> list[str]:
    names: list[str] = []
    for obj in vars(monsters_mod).values():
        if isinstance(obj, type) and issubclass(obj, Monster) and obj is not Monster:
            name = obj.name
            if not isinstance(name, str):
                raise SystemExit(f"{obj.__name__}.name 非字符串：{name!r}")
            names.append(name)
    if len(set(names)) != len(names):
        raise SystemExit("怪物 display name 出现重复，词表键失效")
    return names


def enumerate_potion_pids() -> list[str]:
    pids: list[str] = []
    for obj in vars(potions_mod).values():
        if isinstance(obj, PotionDef):
            pids.append(obj.pid)
    if len(set(pids)) != len(pids):
        raise SystemExit("药水 pid 出现重复，词表键失效")
    return pids


def _fmt_list(items: list[str], per_line: int = 4, indent: str = "    ") -> str:
    """把已格式化的字面量条目按行拼接（调用方负责引号）。"""
    lines = []
    for i in range(0, len(items), per_line):
        lines.append(f"{indent}{', '.join(items[i : i + per_line])},")
    return "\n".join(lines)


def main() -> None:
    card_ids = enumerate_card_ids()
    monster_names = enumerate_monster_names()
    potion_pids = enumerate_potion_pids()
    n_relics = len(RelicId)

    content = f'''"""全量内容词表：观测编码的稳定 ID 层（批次 5a，2026-10-07 生成）。

由 scripts/gen_vocab.py 从内容层枚举生成，**手写改动无效**（会被
tests/test_vocab.py 锁测试与再生成覆盖）。内容层改动后重跑生成脚本。

- 卡牌：id = "模块:常量名"。CardDef.name 跨职业重名（4 个 Strike）且
  frozen dataclass 值相等（不同职业的同名 Strike 是值全同的不同对象），
  反查表按对象身份（id()）键。枚举序：中立模块（status/curses/colorless）
  在前——职业模块 re-export 的状态卡（BURN/DAZED/WOUND/VOID）归属定义
  模块；同一对象跨模块只计一次。共 {len(card_ids)} 个唯一定义 × 2 = {len(card_ids) * 2} 维
  （基础版 = 2k、升级版 = 2k+1——升级是性能不同的牌，四堆计数必须
  分维，DESIGN.md §5.2）。
- 怪物：display name 唯一键，{len(monster_names)} 种，词表 {len(monster_names) + 4} 留追加余量。
- 药水：pid 唯一键，{len(potion_pids)} 种，词表 {len(potion_pids) + 6} 留追加余量。
- 遗物：RelicId 本身是稳定 IntEnum（0..{n_relics - 1}），直接用 value，无需词表。
- 职业：CHARACTERS + CHARACTER_MAX_HP（引擎 Player(80) 固定，非铁甲职业
  构造后修正——与 webapp 同款近似）。
"""

from __future__ import annotations

from sts.content.cards import CardDef
from sts.content.potions import PotionDef
from sts.content.cards import colorless as cards_colorless
from sts.content.cards import curses as cards_curses
from sts.content.cards import defect as cards_defect
from sts.content.cards import ironclad as cards_ironclad
from sts.content.cards import silent as cards_silent
from sts.content.cards import status as cards_status
from sts.content.cards import watcher as cards_watcher

# ---- 卡牌 ----
CARD_MODULES = [
    ("status", cards_status),
    ("curses", cards_curses),
    ("colorless", cards_colorless),
    ("ironclad", cards_ironclad),
    ("silent", cards_silent),
    ("defect", cards_defect),
    ("watcher", cards_watcher),
]
CARD_MODULE_ORDER = {tuple(k for k, _ in CARD_MODULES)!r}

CARD_VOCAB: list[str] = [
{_fmt_list([f'"{c}"' for c in card_ids])}
]
CARD_VOCAB_SIZE = {len(card_ids) * 2}  # (定义, 升级) 各占一位
# id → 基础版词表位（升级版 = 基础位 + 1）
CARD_INDEX: dict[str, int] = {{cid: 2 * i for i, cid in enumerate(CARD_VOCAB)}}

# CardDef 对象身份（id()）→ 卡牌 id。不能按值键：不同职业的同名 Strike
# 是值全同的不同对象（值哈希会撞）；模块级单例身份在进程内稳定
_CARD_ID_BY_DEF: dict[int, str] = {{}}

# ---- 怪物 ----
MONSTER_VOCAB_SIZE = {len(monster_names) + 4}
MONSTER_INDEX: dict[str, int] = {{
{_fmt_list([f'"{n}": {i}' for n, i in zip(monster_names, range(len(monster_names)))], per_line=3)}
}}

# ---- 药水 ----
POTION_VOCAB_SIZE = {len(potion_pids) + 6}
POTION_INDEX: dict[str, int] = {{
{_fmt_list([f'"{p}": {i}' for p, i in zip(potion_pids, range(len(potion_pids)))], per_line=3)}
}}

# ---- 职业 ----
CHARACTERS = ("ironclad", "silent", "defect", "watcher")
CHARACTER_MAX_HP = {{"ironclad": 80, "silent": 70, "defect": 75, "watcher": 72}}


def card_vocab_index(card) -> int | None:
    """CardDef → 基础版词表位；未收录返回 None（该维恒 0，不崩）。"""
    cid = _CARD_ID_BY_DEF.get(id(card))
    return None if cid is None else CARD_INDEX[cid]


def _build() -> None:
    """建立 CardDef 对象身份 → id 反查表（导入期执行一次，身份去重）。"""
    seen: set[int] = set()
    for modkey, mod in CARD_MODULES:
        for varname, obj in vars(mod).items():
            if varname.startswith("_") or not isinstance(obj, CardDef):
                continue
            if id(obj) in seen:
                continue
            seen.add(id(obj))
            _CARD_ID_BY_DEF[id(obj)] = f"{{modkey}}:{{varname}}"


_build()
'''
    with open("sts/vocab.py", "w", encoding="utf-8") as f:
        f.write(content)
    print(
        f"sts/vocab.py 已生成：卡 {len(card_ids)} 唯一定义（{len(card_ids) * 2} 词表位）、"
        f"怪 {len(monster_names)}、药水 {len(potion_pids)}、遗物 {n_relics}"
    )


if __name__ == "__main__":
    main()

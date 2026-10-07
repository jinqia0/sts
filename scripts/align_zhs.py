#!/usr/bin/env python3
"""内容层中文名/描述对齐 codemod：把 sts/content 的卡牌/怪物/药水中文名与
描述替换为官方简体中文本地化（sts_game_data/localization/zhs/）。

对齐口径（2026-10-07 用户决策）：
- 卡牌 text = 官方 DESCRIPTION，!D!/!B!/!M! 代入基础数值（反编译源码
  baseDamage/baseBlock/baseMagicNumber，4 张特殊卡手工覆写），去掉项目
  自造的「（升级 X）」注记
- 怪物名 + 招式名（MoveDef.zh）逐怪对齐官方 NAME/MOVES；官方 MOVES
  无名的招式保留项目现名（报告中标注）
- 药水 zh/description = 官方 NAME + DESCRIPTIONS 拼接（数值插入点按
  反编译 AbstractPotion 子类的 description 构造行）
- 遗物：combat/relics.py 追加 RELIC_ZH（官方中文名，webapp 改读引擎侧）

文件改写走 ast（定位 CardDef/MoveDef/PotionDef 字面量的源码 span），
bottom-up 逐 span 替换，不碰周边代码。运行两次幂等（第二次零 diff）。

用法：uv run python scripts/align_zhs.py [--dry]
"""

from __future__ import annotations

import argparse
import ast
import json
import re
import sys
from collections import defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from sts.combat.relics import RelicId  # noqa: E402

LOC = ROOT / "sts_game_data/localization"
DEC = ROOT / "sts_game_data/decompiled/com/megacrit/cardcrawl"

# ============================================================
# 官方数据加载
# ============================================================

def _load(lang: str, name: str) -> dict:
    with open(LOC / lang / f"{name}.json", encoding="utf-8") as f:
        return json.load(f)


ZHS_CARDS = _load("zhs", "cards")
ENG_CARDS = _load("eng", "cards")
ZHS_MONSTERS = _load("zhs", "monsters")
ENG_MONSTERS = _load("eng", "monsters")
ZHS_POTIONS = _load("zhs", "potions")
ZHS_RELICS = _load("zhs", "relics")


def _norm(s: str) -> str:
    return re.sub(r"[^a-z0-9]", "", s.lower())


# 显示名 → 本体内部卡牌 ID（eng NAME 与 wiki 名一致；Strike/Defend 带
# 职业后缀消歧）
_CARD_KEYS_BY_NAME: dict[str, list[str]] = defaultdict(list)
for _k, _v in ENG_CARDS.items():
    _CARD_KEYS_BY_NAME[_v["NAME"].strip()].append(_k)

# 本体内部卡牌 ID → 反编译源码（cards/*/*.java 的 String ID）；
# 惰性构建——测试导入本模块做名称对齐校验时不必扫 2000 个 Java 文件
_JAVA_CARD: dict[str, str] | None = None


def _java_cards() -> dict[str, str]:
    global _JAVA_CARD
    if _JAVA_CARD is None:
        cache: dict[str, str] = {}
        for _f in DEC.glob("cards/*/*.java"):
            if _f.parent.name in ("deprecated", "optionCards"):
                continue  # 废弃/选项卡与正式卡同 ID，会覆盖真数值
            _src = _f.read_text(encoding="utf-8", errors="replace")
            _m = re.search(r'String ID = "([^"]+)"', _src)
            if _m:
                cache[_m.group(1)] = _src
        _JAVA_CARD = cache
    return _JAVA_CARD

# 数值特例（Java 构造器用 misc/条件表达式的 4 张卡，取项目已验证数值；
# 键 = 本体内部卡牌 ID，即 card_key_for 的返回值）
NUM_OVERRIDES: dict[str, dict[str, int]] = {
    "RitualDagger": {"D": 15, "M": 3},
    "Genetic Algorithm": {"B": 1, "M": 2},
    "Shiv": {"D": 4},
    "PathToVictory": {"M": 8},  # Pressure Points
}


def card_key_for(name: str, module: str) -> str | None:
    keys = _CARD_KEYS_BY_NAME.get(name.strip(), [])
    suffix = {"ironclad": "_R", "silent": "_G", "defect": "_B",
               "watcher": "_P"}.get(module, "")
    if len(keys) == 1:
        return keys[0] if keys[0] in ZHS_CARDS else None
    for k in keys:
        if k.endswith(suffix) and k in ZHS_CARDS:
            return k
    for k in keys:
        if k in ZHS_CARDS:
            return k
    return None


def java_nums(key: str) -> dict[str, int]:
    if key in NUM_OVERRIDES:
        return dict(NUM_OVERRIDES[key])
    src = _java_cards().get(key)
    if src is None:
        return {}
    nums: dict[str, int] = {}
    for token, field in (("D", "baseDamage"), ("B", "baseBlock"),
                         ("M", "baseMagicNumber")):
        m = re.search(rf"this\.{field} = (-?\d+)", src)
        if m:
            nums[token] = int(m.group(1))
    if "M" not in nums:
        m = re.search(r"this\.magicNumber = (-?\d+)", src)
        if m:
            nums["M"] = int(m.group(1))
    return nums


# ============================================================
# 描述文本清洗
# ============================================================

_ICON = r"\[[RGBW]\]"  # 能量图标（各职业配色）


def clean_text(desc: str, nums: dict[str, int], potency: int | None = None
               ) -> tuple[str, list[str]]:
    """官方描述 → 展示文本：占位符代数值、图标转文字、NL 转换行、
    CJK 邻接空格规整。返回 (新文本, 未解决问题清单)。"""
    issues: list[str] = []
    s = desc

    # 数值占位符（代不上的保留原样并记录）
    for token, val in (("D", nums.get("D")), ("B", nums.get("B")),
                       ("M", nums.get("M"))):
        ph = f"!{token}!"
        if ph in s:
            if val is None:
                issues.append(f"占位符 {ph} 无基础数值，保留原样")
            else:
                s = s.replace(ph, str(val))

    # 药水分段拼接的数字插入点（脚本调用方先行拼接，此处兜底）
    if potency is not None:
        s = s.replace("#POT#", str(potency))

    # 「一点 [B]」型：量词后的图标由计数接管（获得一点 [B] → 获得 1 点能量）
    s = re.sub(rf"一[点张个]\s*(?={_ICON})", "", s)

    # 能量图标：数字+单个图标 → 「N 点能量」；连续图标 → 「N 点能量」
    s = re.sub(rf"(\d+)\s*{_ICON}", r"\1 点能量", s)

    def _icon_run(m: re.Match) -> str:
        n = m.group(0).count("[")
        return f"{n} 点能量"

    s = re.sub(rf"(?:{_ICON}\s*)+", _icon_run, s)

    # 关键字卡名高亮星号（*小刀 / *奇迹 …）
    s = s.replace("*", "")

    # 颜色标记（药水）
    s = re.sub(r"#[a-z]", "", s)

    # NL → 换行；首尾与重复换行收敛
    s = re.sub(r"\s*NL\s*", "\n", s)
    s = "\n".join(part.strip() for part in s.split("\n"))
    s = s.strip()

    s = _cjk_spaces(s)
    return s, issues


def _cjk_spaces(s: str) -> str:
    """官方文本的关键字两侧空格是高亮标记残留：CJK-CJK / CJK-标点之间
    的空格去掉；CJK 与数字之间补一个空格（官方数值排版风格）。"""

    def is_cjk(ch: str) -> bool:
        return "\u3400" <= ch <= "\u9fff" or ch in "，。；：、！？（）"

    out = []
    for i, ch in enumerate(s):
        if ch == " ":
            prev = s[i - 1] if i > 0 else ""
            nxt = s[i + 1] if i + 1 < len(s) else ""
            if prev and nxt and is_cjk(prev) and is_cjk(nxt):
                continue
            out.append(ch)
        else:
            out.append(ch)
    s = "".join(out)
    s = re.sub(r"([\u3400-\u9fff])(\d)", r"\1 \2", s)
    s = re.sub(r"(\d)([\u3400-\u9fff])", r"\1 \2", s)
    s = re.sub(r"\s+([，。；：、！？）])", r"\1", s)
    return s


# ============================================================
# AST span 改写基建
# ============================================================

class FileRewriter:
    """收集 (start, end, replacement) span，bottom-up 应用到文件。

    ast 的 col_offset 是 UTF-8 字节偏移（非字符位），故全程按字节切片。
    """

    def __init__(self, path: Path):
        self.path = path
        self.src = path.read_bytes()
        self.lines = self.src.splitlines(keepends=True)
        self.edits: list[tuple[tuple[int, int], tuple[int, int], bytes]] = []

    def replace_node(self, node: ast.expr, new_text: str) -> None:
        self.edits.append(((node.lineno - 1, node.col_offset),
                           (node.end_lineno - 1, node.end_col_offset),
                           new_text.encode("utf-8")))

    def apply(self) -> bool:
        if not self.edits:
            return False
        # 冲突检查（同一位置只改一次）
        seen = set()
        for (sl, sc), _, _ in self.edits:
            assert (sl, sc) not in seen, f"{self.path}: 跨界编辑冲突 @ {sl + 1}"
            seen.add((sl, sc))
        for (sl, sc), (el, ec), new in sorted(
                self.edits, key=lambda e: (e[0][0], e[0][1]), reverse=True):
            if sl == el:
                line = self.lines[sl]
                self.lines[sl] = line[:sc] + new + line[ec:]
            else:
                self.lines[sl] = self.lines[sl][:sc] + new
                for i in range(sl + 1, el):
                    self.lines[i] = b""
                self.lines[el] = self.lines[el][ec:]
        self.path.write_bytes(b"".join(self.lines))
        return True


# ============================================================
# 卡牌模块改写
# ============================================================

CARD_MODULES = {
    "ironclad": ROOT / "sts/content/cards/ironclad.py",
    "silent": ROOT / "sts/content/cards/silent.py",
    "defect": ROOT / "sts/content/cards/defect.py",
    "watcher": ROOT / "sts/content/cards/watcher.py",
    "colorless": ROOT / "sts/content/cards/colorless.py",
    "curses": ROOT / "sts/content/cards/curses.py",
    "status": ROOT / "sts/content/cards/status.py",
}

_report: list[str] = []


def rep(msg: str) -> None:
    _report.append(msg)


def rewrite_cards(dry: bool) -> None:
    for module, path in CARD_MODULES.items():
        rw = FileRewriter(path)
        tree = ast.parse(rw.src)
        for node in ast.walk(tree):
            if not (isinstance(node, ast.Call)
                    and isinstance(node.func, ast.Name)
                    and node.func.id == "CardDef"):
                continue
            if len(node.args) < 5 or not (
                    isinstance(node.args[0], ast.Constant) and isinstance(node.args[0].value, str)
                    and isinstance(node.args[1], ast.Constant) and isinstance(node.args[1].value, str)
                    and isinstance(node.args[3], ast.Constant) and isinstance(node.args[3].value, str)
                    and isinstance(node.args[4], ast.Constant) and isinstance(node.args[4].value, str)):
                rep(f"[卡牌][跳过] {path.name}:{node.lineno} 非标准字面量调用")
                continue
            name, _old_zh = (node.args[0].value, node.args[1].value)
            key = card_key_for(name, module)
            if key is None:
                rep(f"[卡牌][未匹配] {module}:{name} 官方无条目")
                continue
            entry = ZHS_CARDS[key]
            nums = java_nums(key)
            new_text, issues = clean_text(entry["DESCRIPTION"], nums)
            rw.replace_node(node.args[1], _py_str(entry["NAME"]))
            rw.replace_node(node.args[4], _py_str(new_text))
            for iss in issues:
                rep(f"[卡牌][注意] {module}:{name} {iss}")
        if not dry:
            rw.apply()


def _py_str(s: str) -> str:
    """Python 源码里的字符串字面量（双引号，转义换行）。"""
    return '"' + s.replace("\\", "\\\\").replace('"', '\\"').replace("\n", "\\n") + '"'


# ============================================================
# 药水改写
# ============================================================

def _potion_desc(pid: str, segments: list[str], potency: int) -> tuple[str, list[str]]:
    """按反编译 Potion 子类的 description 构造行拼接官方描述。"""
    java = None
    for f in (DEC / "potions").glob("*.java"):
        src = f.read_text(encoding="utf-8", errors="replace")
        if f'String POTION_ID = "{pid}"' in src or f'ID = "{pid}"' in src:
            java = src
            break
    if java is None:
        return "", ["反编译源码未找到，无法确定拼接方式"]
    m = re.search(r"this\.description = (.+?);", java, re.S)
    if not m:
        return "", ["无 description 构造行"]
    expr = " ".join(m.group(1).split())
    # 常见三型：DESCRIPTIONS[0] / 三元选 [0]:[1]（SacredBark 翻倍变体，取基础）/ [0]+potency+[1](+potency+[2]…)
    if "?" in expr and "DESCRIPTIONS[0]" in expr and "DESCRIPTIONS[1]" in expr:
        base = segments[0]
    elif "+ this.potency +" in expr or "+ this.potency " in expr or "this.potency +" in expr:
        parts = re.split(r"\+?\s*this\.potency\s*\+?", expr)
        # 逐段取 DESCRIPTIONS[i] 索引，中间插 potency
        idxs = []
        for p in parts:
            for mm in re.finditer(r"DESCRIPTIONS\[(\d+)\]", p):
                idxs.append(int(mm.group(1)))
        base = ""
        for j, idx in enumerate(idxs):
            if j > 0:
                base += "#POT#"
            base += segments[idx]
    else:
        mm = re.search(r"DESCRIPTIONS\[(\d+)\]", expr)
        if not mm:
            return "", [f"无法解析构造行：{expr[:80]}"]
        base = segments[int(mm.group(1))]
    txt, issues = clean_text(base, {}, potency)
    return txt, issues


def rewrite_potions(dry: bool) -> None:
    path = ROOT / "sts/content/potions.py"
    rw = FileRewriter(path)
    tree = ast.parse(rw.src)
    for node in ast.walk(tree):
        if not (isinstance(node, ast.Call)
                and isinstance(node.func, ast.Name)
                and node.func.id == "PotionDef"):
            continue
        if len(node.args) < 5 or not all(
                isinstance(a, ast.Constant) and isinstance(a.value, str)
                for a in node.args[:4]):
            rep(f"[药水][跳过] {path.name}:{node.lineno} 非标准字面量调用")
            continue
        pid, _name, _old_zh, _old_desc = [a.value for a in node.args[:4]]
        potency = node.args[4].value if isinstance(node.args[4], ast.Constant) else None
        zkey = next((k for k in ZHS_POTIONS if _norm(k) == _norm(pid)), None)
        if zkey is None:
            rep(f"[药水][未匹配] {pid} 官方无条目")
            continue
        entry = ZHS_POTIONS[zkey]
        if potency is None:
            rep(f"[药水][注意] {pid} potency 非字面量，数值插入点待人工")
            new_desc = _old_desc
        else:
            new_desc, issues = _potion_desc(pid, entry["DESCRIPTIONS"], int(potency))
            for iss in issues:
                rep(f"[药水][注意] {pid} {iss}")
            if not new_desc:
                new_desc = _old_desc
        rw.replace_node(node.args[2], _py_str(entry["NAME"]))
        if new_desc != _old_desc:
            rw.replace_node(node.args[3], _py_str(new_desc))
    if not dry:
        rw.apply()


# ============================================================
# 怪物改写
# ============================================================

# 项目怪类 → 反编译 Java 文件名（内部类名与 wiki 名不同的全部在此）
MONSTER_JAVA = {
    "Cultist": "Cultist", "JawWorm": "JawWorm", "Louse": None,
    "RedLouse": "LouseNormal", "GreenLouse": "LouseDefensive",
    "AcidSlimeS": "AcidSlime_S", "SpikeSlimeS": "SpikeSlime_S",
    "FungiBeast": "FungiBeast", "AcidSlimeM": "AcidSlime_M",
    "SpikeSlimeM": "SpikeSlime_M", "BlueSlaver": "SlaverBlue",
    "RedSlaver": "SlaverRed", "SneakyGremlin": "GremlinThief",
    "FatGremlin": "GremlinFat", "ShieldGremlin": "GremlinTsundere",
    "GremlinWizard": "GremlinWizard", "Sentry": "Sentry",
    "MadGremlin": "GremlinWarrior", "GremlinNob": "GremlinNob",
    "Lagavulin": "Lagavulin", "TheGuardian": "TheGuardian",
    "Hexaghost": "Hexaghost", "Taskmaster": "Taskmaster",
    "AcidSlimeL": "AcidSlime_L", "SpikeSlimeL": "SpikeSlime_L",
    "SlimeBoss": "SlimeBoss", "Looter": "Looter", "Mugger": "Mugger",
    "SphericGuardian": "SphericGuardian", "Chosen": "Chosen",
    "ShelledParasite": "ShelledParasite", "Byrd": "Byrd",
    "SnakePlant": "SnakePlant", "Snecko": "Snecko", "Centurion": "Centurion",
    "Mystic": "Healer", "GremlinLeader": "GremlinLeader",
    "BookOfStabbing": "BookOfStabbing", "BronzeAutomaton": "BronzeAutomaton",
    "BronzeOrb": "BronzeOrb", "TheCollector": "TheCollector",
    "TorchHead": "TorchHead", "TheChamp": "Champ", "Darkling": "Darkling",
    "OrbWalker": "OrbWalker", "Repulsor": "Repulsor", "Exploder": "Exploder",
    "Spiker": "Spiker", "SpireGrowth": "SpireGrowth", "Transient": "Transient",
    "TheMaw": "Maw", "WrithingMass": "WrithingMass", "GiantHead": "GiantHead",
    "Nemesis": "Nemesis", "Reptomancer": "Reptomancer", "Dagger": "SnakeDagger",
    "AwakenedOne": "AwakenedOne", "TimeEater": "TimeEater", "Deca": "Deca",
    "Donu": "Donu", "SpireShield": "SpireShield", "SpireSpear": "SpireSpear",
    "CorruptHeart": "CorruptHeart", "Pointy": "BanditPointy",
    "Romeo": "BanditLeader", "Bear": "BanditBear",
    "ApologySlime": "ApologySlime",
}

# 项目怪类 → 本地化键（大部分同名，以下为内部键不同的）
MONSTER_LOC_KEY = {
    "RedLouse": "FuzzyLouseNormal", "GreenLouse": "FuzzyLouseDefensive",
    "BlueSlaver": "SlaverBlue", "RedSlaver": "SlaverRed",
    "BronzeOrb": "BronzeOrb",
}


def _monster_loc_key(cls_name: str, wiki_name: str) -> str | None:
    if cls_name in MONSTER_LOC_KEY:
        return MONSTER_LOC_KEY[cls_name]
    for k, v in ENG_MONSTERS.items():
        if v.get("NAME", "").strip().lower() == wiki_name.strip().lower():
            return k
    return None


def _parse_monster_java(java_name: str) -> dict:
    """解析反编译怪类：byte 值 → MOVES 索引 + 常量名表。"""
    f = None
    for sub in ("exordium", "city", "beyond", "ending"):
        cand = DEC / "monsters" / sub / f"{java_name}.java"
        if cand.exists():
            f = cand
            break
    if f is None:
        return {"byte_moves": {}, "const_names": {}}
    src = f.read_text(encoding="utf-8", errors="replace")
    name_consts: dict[str, int] = {}  # 名称常量 → MOVES 索引
    for m in re.finditer(r"String (\w+) = MOVES\[(\d+)\]", src):
        name_consts[m.group(1)] = int(m.group(2))
    byte_of: dict[int, int] = {}  # setMove 的 byte 值 → MOVES 索引
    for m in re.finditer(
            r"setMove\(\s*(MOVES\[(\d+)\]|\w+)\s*,\s*\(byte\)(\d+)", src):
        const, idx_s, byte_v = m.group(1), m.group(2), int(m.group(3))
        if idx_s is not None:
            byte_of[byte_v] = int(idx_s)
        elif const in name_consts:
            byte_of[byte_v] = name_consts[const]
    const_names: dict[int, str] = {}  # byte 值 → 常量名
    for m in re.finditer(r"final byte (\w+) = (\d+)", src):
        const_names[int(m.group(2))] = m.group(1)
    return {"byte_moves": byte_of, "const_names": const_names}


# 项目 MoveDef 英文名 → Java byte 常量名（规范化后同名则自动匹配；
# 以下只列名字对不上的：键 = (项目怪类名, 项目 MoveDef 英文名)。
# 每条都经反编译 setMove(NAME 常量, (byte)N) 绑定核对——常量名与项目
# 英文名不同义（WOUND_TACKLE=Corrosive Spit 等）的都在这里）
MOVE_CONST_ALIAS: dict[tuple[str, str], str] = {
    ("RedLouse", "Grow"): "STRENGTHEN",
    ("GreenLouse", "Spit Web"): "WEAKEN",
    ("AcidSlimeM", "Corrosive Spit"): "WOUND_TACKLE",
    ("AcidSlimeM", "Lick"): "WEAK_LICK",
    ("SpikeSlimeM", "Lick"): "FRAIL_LICK",
    ("FatGremlin", "Smash"): "BLUNT",
    ("ShieldGremlin", "Shield Bash"): "BASH",
    ("GremlinWizard", "Charging"): "CHARGE",
    ("GremlinWizard", "Ultimate Blast"): "DOPE_MAGIC",
    ("Lagavulin", "Siphon Soul"): "DEBUFF",
    ("TheGuardian", "Charging Up"): "CHARGE_UP",
    ("TheGuardian", "Defensive Mode"): "CLOSE_UP",
    ("AcidSlimeL", "Corrosive Spit"): "SLIME_TACKLE",
    ("AcidSlimeL", "Lick"): "WEAK_LICK",
    ("SpikeSlimeL", "Lick"): "FRAIL_LICK",
    ("SlimeBoss", "Preparing"): "PREP_SLAM",
    ("SlimeBoss", "Goop Spray"): "STICKY",
    ("SnakePlant", "Enfeebling Spores"): "SPORES",
    ("Snecko", "Perplexing Glare"): "GLARE",
    ("Snecko", "Tail Whip"): "TAIL",
    ("Donu", "Circle of Power"): "CIRCLE_OF_PROTECTION",
}


def rewrite_monsters(dry: bool) -> None:
    path = ROOT / "sts/content/monsters.py"
    rw = FileRewriter(path)
    tree = ast.parse(rw.src)
    renames: dict[str, list[tuple[str, str, str]]] = {}  # 类名 → [(en, old, new)]

    # (类名, MoveDef 英文名) → 官方中文 的总映射
    for node in ast.walk(tree):
        if not isinstance(node, ast.ClassDef):
            continue
        cls_name = node.name
        if cls_name not in MONSTER_JAVA:
            continue
        renames[cls_name] = []
        wiki_name = None
        moves: list[ast.Call] = []
        zh_assigns: list[ast.Assign] = []
        display_calls: list[ast.Call] = []
        for sub in ast.walk(node):
            if (isinstance(sub, ast.Call)
                    and isinstance(sub.func, ast.Name)
                    and sub.func.id == "MoveDef"):
                moves.append(sub)
            if (isinstance(sub, ast.Assign) and len(sub.targets) == 1
                    and isinstance(sub.targets[0], ast.Name)
                    and sub.targets[0].id == "zh"):
                zh_assigns.append(sub)
            if (isinstance(sub, ast.Call)
                    and isinstance(sub.func, ast.Attribute)
                    and sub.func.attr == "__init__"
                    and len(sub.args) >= 4
                    and isinstance(sub.args[3], ast.Constant)
                    and isinstance(sub.args[3].value, str)):
                display_calls.append(sub)

        # 怪物官方名
        for a in zh_assigns:
            if not (isinstance(a.value, ast.Constant)
                    and isinstance(a.value.value, str)):
                continue
            wiki_name = a.value.value  # zh 属性存的是项目旧名，仅类内定位用
        # wiki 英文名从类属性 name 拿
        name_val = None
        for sub in ast.walk(node):
            if (isinstance(sub, ast.Assign) and len(sub.targets) == 1
                    and isinstance(sub.targets[0], ast.Name)
                    and sub.targets[0].id == "name"
                    and isinstance(sub.value, ast.Constant)):
                name_val = sub.value.value
                break
        loc_key = _monster_loc_key(cls_name, name_val or cls_name)
        official_name = ZHS_MONSTERS.get(loc_key, {}).get("NAME") if loc_key else None
        official_moves = ZHS_MONSTERS.get(loc_key, {}).get("MOVES") or [] if loc_key else []

        if official_name:
            for a in zh_assigns:
                if isinstance(a.value, ast.Constant):
                    rw.replace_node(a.value, _py_str(official_name))
            for c in display_calls:
                old = c.args[3].value
                new_display = f"{official_name}({name_val})"
                if old != new_display:
                    rw.replace_node(c.args[3], _py_str(new_display))

        # 招式名：项目英文名 → Java 常量名 → byte → MOVES 索引 → 官方中文
        java = _parse_monster_java(MONSTER_JAVA[cls_name]) if MONSTER_JAVA[cls_name] else {}
        for mv in moves:
            if len(mv.args) < 2 or not all(
                    isinstance(a, ast.Constant) and isinstance(a.value, str)
                    for a in mv.args[:2]):
                rep(f"[怪物][跳过] {cls_name} 非标准 MoveDef @{mv.lineno}")
                continue
            en, old_zh = mv.args[0].value, mv.args[1].value
            want_const = MOVE_CONST_ALIAS.get((cls_name, en), en)
            new_zh = None
            hit_const = None
            for byte_v, const in java.get("const_names", {}).items():
                if _norm(const) == _norm(want_const):
                    hit_const = (const, byte_v)
                    if byte_v in java.get("byte_moves", {}):
                        idx = java["byte_moves"][byte_v]
                        if idx < len(official_moves) and official_moves[idx]:
                            new_zh = official_moves[idx]
                        else:
                            rep(f"[怪物][官方无名] {cls_name}.{en} "
                                f"MOVES[{idx}] 为空，保留「{old_zh}」")
                    else:
                        rep(f"[怪物][官方无名] {cls_name}.{en} 常量 {const} "
                            f"在 setMove 中不带名字，保留「{old_zh}」")
                    break
            if new_zh and new_zh != old_zh:
                rw.replace_node(mv.args[1], _py_str(new_zh))
                renames.setdefault(cls_name, []).append((en, old_zh, new_zh))
            elif new_zh is None and hit_const is None:
                # Java 常量表里找不到对应常量：该怪可能共用基类（Louse.Bite
                # 在子类 java 里）或官方确无此招式名
                rep(f"[怪物][官方无名] {cls_name}.{en} 无对应 Java 常量，"
                    f"保留「{old_zh}」")

    if not dry:
        rw.apply()
        _sync_monster_log_names(path, renames, tree)


def _sync_monster_log_names(path: Path,
                            renames: dict[str, list[tuple[str, str, str]]],
                            tree: ast.Module) -> None:
    """take_turn 等日志文案里硬编码的「旧招式名(EN)」同步为新名。

    按类源码区间做文本替换（AST span 与正则替换不混用）；同名 EN 招式
    在不同类里旧名不同（Slam 粉碎/猛击/重击）靠类区间消歧。
    """
    if not any(renames.values()):
        return
    lines = path.read_text(encoding="utf-8").splitlines(keepends=True)
    class_spans = []
    for node in tree.body:
        if isinstance(node, ast.ClassDef) and renames.get(node.name):
            class_spans.append((node.lineno - 1, node.end_lineno, node.name))
    n = 0
    for lo, hi, cls_name in class_spans:
        for en, old, new in renames[cls_name]:
            pat = re.compile(re.escape(old) + r"[（(]" + re.escape(en) + r"[)）]")
            for i in range(lo, hi):
                new_line, cnt = pat.subn(f"{new}({en})", lines[i])
                if cnt:
                    lines[i] = new_line
                    n += cnt
    path.write_text("".join(lines), encoding="utf-8")
    rep(f"[怪物][日志同步] 招式名引用更新 {n} 处")


# ============================================================
# 遗物：RELIC_ZH 追加到 combat/relics.py
# ============================================================

def append_relic_zh(dry: bool) -> None:
    path = ROOT / "sts/combat/relics.py"
    src = path.read_text(encoding="utf-8")
    if "RELIC_ZH" in src:
        return
    # 本体内部键名与 RelicId 成员名不一致的遗物（变体匹配兜不住的）
    relic_key_fix = {
        "SLING_OF_COURAGE": "Sling", "NEOWS_LAMENT": "NeowsBlessing",
        "GREMLIN_VISAGE": "GremlinMask", "DUALITY": "Yang",
        "PAPER_PHROG": "Paper Frog", "THE_BOOT": "Boot",
        "GOLD_PLATED_CABLES": "Cables", "SNECKO_SKULL": "Snake Skull",
        "PAPER_KRANE": "Paper Crane",
    }
    zhs_by_norm = {_norm(k): v["NAME"] for k, v in ZHS_RELICS.items()}
    rows, unresolved = [], []
    for rid in RelicId:
        cands = [relic_key_fix.get(rid.name, rid.name),
                 rid.name.replace("_", ""), rid.name.replace("_", " ")]
        zh = next((zhs_by_norm[_norm(c)] for c in cands
                   if _norm(c) in zhs_by_norm), None)
        if zh is None:
            unresolved.append(rid.name)
            zh = rid.name.replace("_", " ").title()
        rows.append((rid.name, zh))
    for u in unresolved:
        rep(f"[遗物][未匹配] {u} 官方无条目，回落英文名")
    block = (
        "\n\n# ---- 官方简体中文名（sts_game_data/localization/zhs/relics.json；\n"
        "# webapp/CLI 展示用，引擎逻辑不读取）----\n"
        "RELIC_ZH: dict[RelicId, str] = {\n"
        + "\n".join(f"    RelicId.{rid}: \"{zh}\"," for rid, zh in rows)
        + "\n}\n"
    )
    if not dry:
        path.write_text(src + block, encoding="utf-8")


# ============================================================
# 主流程
# ============================================================

def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry", action="store_true", help="只出报告不改文件")
    args = ap.parse_args()

    rewrite_cards(args.dry)
    rewrite_potions(args.dry)
    rewrite_monsters(args.dry)
    append_relic_zh(args.dry)

    print(f"{'[DRY] ' if args.dry else ''}对齐完成，报告 {len(_report)} 条：")
    for line in _report:
        print("  " + line)


if __name__ == "__main__":
    main()

"""战斗网页调试器：本地端口起一个 HTTP 服务，在浏览器里自定义
角色 / 卡组 / 遗物 / 药水 / 怪物，手动打完整场战斗——用于肉眼校验
战斗系统的结算（伤害管线、触发顺序、卡牌交互）是否符合预期。

用法：
    uv run python -m sts.webapp [--port 8765]

实现约定（2026-10-07 用户决策）：
- stdlib-only（http.server），零新依赖，不动 uv.lock
- 引擎零改动：自定义组怪通过向 ENCOUNTERS 注册 "custom_web" 条目
  实现（场景 = 数据的既定扩展方式，sts/content/encounters.py 注释）；
  卡组 / 遗物 / 药水走 BattleContext 构造参数
- http.server 单线程：本地调试工具无并发需求，也天然避免自定义组怪
  PENDING 全局的竞态
- 信息边界（DESIGN.md §4，2026-10-07）：抽牌堆序列化只暴露构成——
  同名聚合计数 + 名称排序，不泄露内部顺序（对齐本体牌堆查看按字母序
  的口径）；选卡候选（Seek 类从抽牌堆选卡）展示按名称排序，engine_idx
  内部映射回引擎下标。Scry 展示堆顶 N 张是游戏机制合法可见，不受限
- 已知近似：职业最大生命（引擎固定 Player(80)）在构造后修正，开局
  遗物回复的血量以 min(hp, max_hp) 钳制——只影响「带治疗遗物 + 非
  铁甲职业」的组合
- 前端为 sts/web/ 下的纯静态文件（index.html / app.js / style.css），
  fetch JSON 交互；意外异常（引擎 bug）以 traceback 原文返回给页面，
  方便定位

策略演示 + 手操录制（2026-10-08 新增）：
- env 模式：会话附带一个 StsBattleEnv（观测 = 训练同款 OBS_DIM 维 /
  动作 Discrete(120)，与训练完全同构），所有动作（人操与 AI）都经
  env.step 以训练同款
  动作 id 执行——前端交互协议不变，后端把 webapp 动作体映射成 env
  动作（body_to_env_actions）。choose_cards 的自由多选在 env 侧是
  「窗口内单调选择 + 确认」的自回归序列（DESIGN.md §5.2 的既定近似：
  候选窗口 10）；超窗候选映射失败，前端置灰提示
- AI 演示：MaskablePPO 模型懒加载（首次使用才 import torch，平时
  启动保持轻量）；模型默认按遭遇难度自动匹配（弱/强/精英/Boss 四档，
  EXPERIMENTS.md 当前基准），页面可手选 models/ 下任意 zip；单步 /
  自动连打 / 人随时接管（同一动作空间，无模式切换成本）
- 录制：env 模式下逐动作记录 (env 动作 id, 执行者, 人类可读标签)，
  战斗结束保存为 records/*.json（含完整配置与种子，确定性可回放）；
  scripts/export_records.py 重放生成 BC 训练用 (obs, action, mask)
  npz——回放与实录逐位一致由测试保证
- 固定评测集 EVAL_SETS：遭遇 × 固定种子（1001 起，与训练种子 ≥10_000、
  评估种子 0..99 均不相交），人与 AI 打同一局面直接对比
"""

from __future__ import annotations

import argparse
import itertools
import json
import time
import traceback
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path

import numpy as np

from sts.combat import BattleContext
from sts.combat.queue import CardSelectInfo
from sts.combat.relics import RelicId
from sts.combat.types import (
    InputState,
    MonsterStatus,
    Outcome,
    PlayerStatus,
    Stance,
)
from sts.content import encounters as encounters_mod
from sts.content.cards import CardDef
from sts.content.cards import colorless as cards_colorless
from sts.content.cards import curses as cards_curses
from sts.content.cards import defect as cards_defect
from sts.content.cards import ironclad as cards_ironclad
from sts.content.cards import silent as cards_silent
from sts.content.cards import status as cards_status
from sts.content.cards import watcher as cards_watcher
from sts.content.monsters import Monster
from sts.content import monsters as monsters_mod
from sts.content.potions import ALL_POTIONS, PotionDef
from sts.env import (
    ACTION_END_TURN,
    HAND_SLOT_BASE,
    N_HAND_SLOTS,
    N_TARGET_SLOTS,
    POTION_BASE,
    POTION_STANCE_BASE,
    SCRY_BASE,
    SCRY_KEEP_MAX,
    SELECT_BASE,
    SELECT_CONFIRM,
    STANCE_CHOICES,
    TARGETED_BASE,
    StsBattleEnv,
)
from sts.run_env import (
    BOSSES,
    CARD_POOLS,
    CARD_PITY_FLOOR,
    CARD_PITY_GROWTH,
    CARD_PITY_START,
    CARD_RARE,
    CARD_UNCOMMON,
    ELITES,
    RELIC_POOLS,
    RELIC_TIER_COMMON,
    RELIC_TIER_RARE,
    STRONG_POOL,
    WEAK_POOL,
)

ROOT = Path(__file__).resolve().parent.parent
WEB_DIR = Path(__file__).resolve().parent / "web"
MODELS_DIR = ROOT / "models"
RECORDS_DIR = ROOT / "records"

# ============================================================
# 中文名称（本地化数据 + 少量手工对齐）
# ============================================================

def _load_json(path: Path):
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def _norm(s: str) -> str:
    return "".join(ch for ch in s.lower() if ch.isalnum())


# powers.json 的键名与状态枚举名存在少量拼写差异，手工对齐
_POWER_KEY_FIX = {
    "WEAK": "Weakened",
    "LOCK_ON": "Lockon",
    "NO_BLOCK": "NoBlockPower",
    "CORPSE_EXPLOSION": "CorpseExplosionPower",
    "BEAT_OF_DEATH": "BeatOfDeath",
    "A_THOUSAND_CUTS": "Thousand Cuts",
    "PLATED_ARMOR_M": "Plated Armor",
    "GENERIC_STRENGTH_UP": "Strength",
    "BLOCK_RETURN": "BlockReturnPower",
    "SURROUNDED": "Surrounded",
    "CONFUSED": "Confusion",
    "MALLEABLE": "Malleable",
    "CHOKED": "Choke",
    "SHIFTING": "Shift",
    "STASIS": "Stasis",
    "REGROW": "Regrow",
    "REACTIVE": "Reactive",
    "ASLEEP": "Asleep",
    "ENRAGE": "Enrage",
    "REGEN": "Regeneration",
    "MARK": "Mark",
    "MINION_LEADER": "Minion",
}
_powers_zh: dict[str, str] = {}
for _k, _v in _load_json(ROOT / "sts_game_data/localization/zhs/powers.json").items():
    _powers_zh[_norm(_k)] = _v["NAME"]


def _status_zh(member) -> str:
    key = _POWER_KEY_FIX.get(member.name) or member.name.title().replace("_", " ")
    return _powers_zh.get(_norm(key), member.name)


# 遗物：中文名走引擎侧 RELIC_ZH（combat/relics.py，官方本地化对齐）；
# 英文描述与 tier 取 wiki_data/relics.json
_WIKI_RELIC: dict[str, dict] = {}
for _r in _load_json(ROOT / "wiki_data/relics.json")["relics"]:
    _WIKI_RELIC[_r.get("relic_id", _norm(_r["name"]))] = _r


def _relic_meta(rid: RelicId) -> dict:
    wiki = _WIKI_RELIC.get(rid.name)
    en_name = wiki["name"] if wiki else rid.name.replace("_", " ").title()
    from sts.combat.relics import RELIC_ZH
    zh = RELIC_ZH.get(rid, en_name)
    return {"id": rid.name, "name": en_name, "zh": zh,
            "text": (wiki or {}).get("text", "")}


_ORB_ZH = {"LIGHTNING": "闪电", "FROST": "霜", "DARK": "暗", "PLASMA": "等离子"}
_STANCE_ZH = {"NEUTRAL": "中立", "CALM": "平静", "WRATH": "愤怒", "DIVINITY": "神威"}

# ============================================================
# 内容目录（前端配置面板的数据源）
# ============================================================

# 卡牌：id = "模块:常量名"（CardDef.name 跨职业重名，如 4 个 Strike）
_CARD_MODULES = [
    ("ironclad", cards_ironclad, "铁甲"),
    ("silent", cards_silent, "静默"),
    ("defect", cards_defect, "故障"),
    ("watcher", cards_watcher, "观者"),
    ("colorless", cards_colorless, "无色"),
    ("curses", cards_curses, "诅咒"),
    ("status", cards_status, "状态"),
]

CARDS: dict[str, CardDef] = {}
CARD_META: list[dict] = []
for _modkey, _mod, _modzh in _CARD_MODULES:
    for _varname, _obj in vars(_mod).items():
        if _varname.startswith("_") or not isinstance(_obj, CardDef):
            continue
        _cid = f"{_modkey}:{_varname}"
        CARDS[_cid] = _obj
        CARD_META.append({
            "id": _cid, "module": _modkey, "module_zh": _modzh,
            "name": _obj.name, "zh": _obj.zh, "cost": _obj.cost,
            "ctype": _obj.ctype, "text": _obj.text,
            "unplayable": _obj.unplayable, "x_cost": _obj.x_cost,
            "needs_target": _obj.needs_target,
        })
CARD_META.sort(key=lambda c: (c["module"], c["ctype"], c["zh"]))


def _deck_entry(cid: str, count: int = 1, upgraded: int = 0) -> dict:
    return {"id": cid, "count": count, "upgraded": upgraded}


# 四职业初始牌组（本体：铁甲 80 HP / 静默 70 / 故障 75 / 观者 72）
CHARACTERS: dict[str, dict] = {
    "ironclad": {
        "zh": "铁甲战士", "max_hp": 80,
        "deck": [_deck_entry("ironclad:STRIKE", 5), _deck_entry("ironclad:DEFEND", 4),
                 _deck_entry("ironclad:BASH")],
    },
    "silent": {
        "zh": "静默", "max_hp": 70,
        "deck": [_deck_entry("silent:STRIKE_S", 5), _deck_entry("silent:DEFEND_S", 5),
                 _deck_entry("silent:NEUTRALIZE"), _deck_entry("silent:SURVIVOR")],
    },
    "defect": {
        "zh": "故障", "max_hp": 75,
        "deck": [_deck_entry("defect:STRIKE_D", 4), _deck_entry("defect:DEFEND_D", 4),
                 _deck_entry("defect:ZAP"), _deck_entry("defect:DUALCAST")],
    },
    "watcher": {
        "zh": "观者", "max_hp": 72,
        "deck": [_deck_entry("watcher:STRIKE_W", 4), _deck_entry("watcher:DEFEND_W", 4),
                 _deck_entry("watcher:ERUPTION"), _deck_entry("watcher:VIGILANCE")],
    },
}

# 怪物：可自由组队的全部怪种（排除内部占位类）
MONSTER_CLASSES: dict[str, type[Monster]] = {}
MONSTER_META: list[dict] = []
for _varname, _obj in vars(monsters_mod).items():
    if (_varname.startswith("_") or not isinstance(_obj, type)
            or not issubclass(_obj, Monster) or _obj is Monster
            or _obj.__module__ != monsters_mod.__name__):
        continue
    MONSTER_CLASSES[_varname] = _obj
    MONSTER_META.append({
        "key": _varname, "zh": getattr(_obj, "zh", _varname),
        "name": getattr(_obj, "name", _varname),
        "hp_range": list(getattr(_obj, "hp_range", ())),
    })
MONSTER_META.sort(key=lambda m: m["zh"])

RELIC_META = [_relic_meta(rid) for rid in RelicId]
RELIC_BY_ID = {m["id"]: m for m in RELIC_META}

POTION_BY_PID = {pd.pid: pd for pd in ALL_POTIONS}
POTION_META = [{
    "pid": pd.pid, "name": pd.name, "zh": pd.zh, "description": pd.description,
    "targeting": pd.targeting, "choices": list(pd.choices),
    "auto_only": pd.auto_only, "escape_only": pd.escape_only, "rarity": pd.rarity,
} for pd in ALL_POTIONS]

ENCOUNTER_KEYS = sorted(k for k in encounters_mod.ENCOUNTERS if k != "custom_web")

# ---- 自定义组怪：注册为一个遭遇条目（PENDING 在构造 BattleContext 前装填）----
_PENDING_MONSTERS: list[type[Monster]] = []


def _setup_custom_web(bc: BattleContext) -> None:
    for idx, cls in enumerate(_PENDING_MONSTERS):
        bc.monsters.add(cls.create(bc, idx))
    encounters_mod._add_starting_deck(bc)  # 牌组由 deck 参数覆盖，此处仅占位


encounters_mod.ENCOUNTERS["custom_web"] = _setup_custom_web


# ============================================================
# 战斗会话
# ============================================================

SESSIONS: dict[str, dict] = {}
_SEQ = itertools.count(1)
_MAX_SESSIONS = 12  # 超出丢最旧（内存保护；本地调试重开成本低）


def build_battle(cfg: dict) -> tuple[BattleContext, str]:
    """配置 → BattleContext（create_battle 与录制回放共用，保证逐位一致）。

    返回 (bc, character)。升级张数经 deck 元组条目 (CardDef, upgraded)
    表达（引擎原生支持）——比旧「构造后标记」路径更可回放：实例的升级
    位在洗牌前就确定，同种子同配置必然重建出同一场战斗。
    """
    char = cfg.get("character", "ironclad")
    character = char if char in CHARACTERS else "ironclad"

    deck: list = []  # CardDef 或 (CardDef, upgraded) 元组
    for e in cfg.get("deck") or CHARACTERS[character]["deck"]:
        card = CARDS[e["id"]]
        n = max(0, int(e.get("count", 1)))
        u = max(0, min(int(e.get("upgraded", 0)), n))
        if u:
            deck.extend([card] * (n - u))
            deck.extend([(card, True)] * u)
        else:
            deck.extend([card] * n)

    relics = [RelicId[r] for r in cfg.get("relics") or []]
    potions = [POTION_BY_PID[p] for p in cfg.get("potions") or [] if p]

    raw_seed = cfg.get("seed")
    seed = int(raw_seed) if raw_seed not in (None, "") else None
    ascension = max(0, min(20, int(cfg.get("ascension", 0))))

    monster_keys = cfg.get("monsters") or []
    if monster_keys:
        _PENDING_MONSTERS.clear()
        _PENDING_MONSTERS.extend(MONSTER_CLASSES[k] for k in monster_keys)
        encounter = "custom_web"
    else:
        encounter = cfg.get("encounter") or "cultist"

    bc = BattleContext(
        seed=seed, encounter=encounter, ascension=ascension,
        deck=deck or None, relics=relics, potions=potions,
    )
    _PENDING_MONSTERS.clear()

    # 职业最大生命（引擎固定 Player(80)，构造后修正；见模块注释的近似说明）
    max_hp = CHARACTERS[character]["max_hp"]
    if max_hp != 80:
        bc.player.max_hp = max_hp
        bc.player.hp = min(bc.player.hp, max_hp)
    return bc, character


def attach_env(bc: BattleContext, character: str) -> StsBattleEnv:
    """把 StsBattleEnv 挂到已构造好的 BattleContext 上（不 reset）。

    观测/动作掩码全部从 self.bc 现算（env._get_obs / action_masks 不读
    构造参数中的 relics/potions/deck），挂接即生效；select 窗口状态由
    _refresh_select_state 按引擎挂起态自动同步。
    """
    env = StsBattleEnv(encounter=bc.encounter, character=character)
    env.bc = bc
    env.battle_seed = bc.seed
    env.current_encounter = bc.encounter
    return env


def create_battle(cfg: dict) -> str:
    """按配置构造战斗并登记会话，返回会话 id。"""
    bc, character = build_battle(cfg)

    env_mode = bool(cfg.get("env_mode") or cfg.get("record"))
    record = bool(cfg.get("record"))
    eval_tag = None
    if cfg.get("eval_set") and cfg.get("eval_index") is not None:
        eval_tag = {"set": cfg["eval_set"], "index": int(cfg["eval_index"])}

    sid = f"b{next(_SEQ)}"
    SESSIONS[sid] = {
        "bc": bc, "offset": 0, "cfg": cfg,
        "env": attach_env(bc, character) if env_mode else None,
        "record": record,
        "steps": [] if record else None,
        "model": cfg.get("model") or None,  # None = 按遭遇难度自动匹配
        "eval": eval_tag,
        "saved": False,
    }
    while len(SESSIONS) > _MAX_SESSIONS:
        SESSIONS.pop(next(iter(SESSIONS)))
    return sid


def apply_action(sid: str, body: dict) -> None:
    """对会话执行一个玩家动作。ValueError = 引擎拒绝（返回给前端提示），
    其余异常 = 引擎 bug，向上抛给调用方附 traceback。

    env 模式：动作映射成 env 动作 id 经 env.step 执行（录制同款路径），
    语义与直调引擎一致（env.step 的动作分发即引擎调用）。
    """
    sess = SESSIONS[sid]
    if sess["env"] is not None:
        for a, label in body_to_env_actions(sess["env"], body):
            step_env_action(sid, a, label, by="human")
        return
    bc: BattleContext = sess["bc"]
    t = body.get("type")
    if t == "play":
        bc.play_card(int(body["index"]), body.get("target"))
    elif t == "end":
        bc.end_turn()
    elif t == "choose_cards":
        bc.choose_cards([int(i) for i in body.get("indices", [])])
    elif t == "scry":
        bc.choose_scry(int(body.get("keep_top_n", 0)))
    elif t == "use_potion":
        bc.use_potion(int(body["slot"]), body.get("target"), body.get("choice"))
    else:
        raise ValueError(f"未知动作类型：{t}")


# ============================================================
# env 动作模式：webapp 动作体 ↔ 训练动作空间（Discrete(120)）
# ============================================================

def body_to_env_actions(env: StsBattleEnv, body: dict) -> list[tuple[int, str]]:
    """webapp 动作体 → [(env 动作 id, 人类可读标签)] 序列。

    多数动作一对一；choose_cards 的自由多选展开为 env 的自回归序列
    [SELECT(窗口位)…] + CONFIRM（DESIGN.md §5.2 窗口 10 近似：候选按
    词表位稳定排序截前 10，超窗候选无法表达 → ValueError 回显前端）。
    返回的标签基于当前（执行前）状态，调用方应在 step 前取用。
    """
    env.action_masks()  # 触发 _refresh_select_state，同步选卡窗口
    bc = env.bc
    t = body.get("type")
    if t == "end":
        return [(ACTION_END_TURN, "结束回合")]
    if t == "play":
        i = int(body["index"])
        if i >= N_HAND_SLOTS:
            raise ValueError(f"手牌第 {i + 1} 张超出策略手牌槽（10），无法以策略动作表达")
        target = body.get("target")
        if target is None:
            a = HAND_SLOT_BASE + i
        else:
            a = TARGETED_BASE + i * N_TARGET_SLOTS + int(target)
        return [(a, _play_label(env, a))]
    if t == "choose_cards":
        if bc.input_state != InputState.CARD_SELECT or bc.card_select_info is None:
            raise ValueError("当前不在选卡状态")
        indices = [int(i) for i in body.get("indices", [])]
        # 引擎候选下标 → 窗口位（窗口序 = 词表位稳定排序，与展示序无关）
        eng2win = {e: w for w, e in enumerate(env._select_engine_idx)}
        seq: list[tuple[int, str]] = []
        for idx in indices:
            w = eng2win.get(idx)
            if w is None:
                raise ValueError(
                    "所选候选超出策略选卡窗口（10 张，按词表位排序截断）——"
                    "训练动作空间无法表达该选择（DESIGN.md §5.2 已记录近似）")
            seq.append((SELECT_BASE + w, f"选卡：{_inst_zh(env._select_window[w])}"))
        seq.append((SELECT_CONFIRM, f"确认选卡（{len(indices)} 张）"))
        return seq
    if t == "scry":
        k = max(0, min(int(body.get("keep_top_n", 0)), SCRY_KEEP_MAX))
        return [(SCRY_BASE + k, f"检视：保留堆顶 {k} 张")]
    if t == "use_potion":
        slot = int(body["slot"])
        pd = bc.player.potions[slot]
        if pd is None:
            raise ValueError(f"药水槽 {slot + 1} 为空")
        choice = body.get("choice")
        if choice is not None:
            c = STANCE_CHOICES.index(choice)
            a = POTION_STANCE_BASE + slot * len(STANCE_CHOICES) + c
            return [(a, f"喝药水：{pd.zh}（{choice}）")]
        j = 0 if body.get("target") is None else int(body["target"]) + 1
        a = POTION_BASE + slot * (N_TARGET_SLOTS + 1) + j
        text = f"喝药水：{pd.zh}"
        monsters = bc.monsters.monsters
        if j and j - 1 < len(monsters):
            text += f"（→ {monsters[j - 1].display_name}）"
        elif j:
            text += f"（→ 目标 {j - 1}）"
        return [(a, text)]
    raise ValueError(f"未知动作类型：{t}")


def _inst_zh(inst) -> str:
    return inst.card.zh + ("+" if inst.upgraded else "")


def _play_label(env: StsBattleEnv, a: int) -> str:
    if TARGETED_BASE <= a < POTION_BASE:
        i, j = divmod(a - TARGETED_BASE, N_TARGET_SLOTS)
        inst = env.bc.cards.hand[i]
        monsters = env.bc.monsters.monsters
        target = f"（→ {monsters[j].display_name}）" if j < len(monsters) else f"（→ 目标 {j}）"
        return f"打出 {_inst_zh(inst)}{target}"
    i = a - HAND_SLOT_BASE
    inst = env.bc.cards.hand[i]
    return f"打出 {_inst_zh(inst)}"


def action_label(env: StsBattleEnv, a: int) -> str:
    """env 动作 id → 人类可读标签（基于当前未执行状态）。"""
    if a == ACTION_END_TURN:
        return "结束回合"
    if a == SELECT_CONFIRM:
        return "确认选卡"
    if SELECT_BASE <= a < SELECT_CONFIRM:
        w = a - SELECT_BASE
        if w < len(env._select_window):
            return f"选卡：{_inst_zh(env._select_window[w])}"
        return f"选卡（窗口位 {w}）"
    if SCRY_BASE <= a <= SCRY_BASE + SCRY_KEEP_MAX:
        return f"检视：保留堆顶 {a - SCRY_BASE} 张"
    if POTION_STANCE_BASE <= a:
        s, c = divmod(a - POTION_STANCE_BASE, len(STANCE_CHOICES))
        pd = env.bc.player.potions[s]
        zh = pd.zh if pd is not None else f"槽{s + 1}"
        return f"喝药水：{zh}（{STANCE_CHOICES[c]}）"
    if POTION_BASE <= a < POTION_STANCE_BASE:
        s, j = divmod(a - POTION_BASE, N_TARGET_SLOTS + 1)
        pd = env.bc.player.potions[s]
        zh = pd.zh if pd is not None else f"槽{s + 1}"
        monsters = env.bc.monsters.monsters
        if j and j - 1 < len(monsters):
            return f"喝药水：{zh}（→ {monsters[j - 1].display_name}）"
        if j:
            return f"喝药水：{zh}（→ 目标 {j - 1}）"
        return f"喝药水：{zh}"
    return _play_label(env, a)


def step_env_action(sid: str, action: int, label: str, by: str) -> None:
    """在 env 模式会话上执行一个 env 动作（人操 / AI 共用，录制同源）。"""
    sess = SESSIONS[sid]
    env: StsBattleEnv = sess["env"]
    mask = env.action_masks()
    if not mask[action]:
        raise ValueError(
            f"动作不合法（env 动作 {action}·{label}）——掩码与操作不一致，"
            "可能是引擎边界情况，请把局面反馈给开发者")
    env.step(action)
    if sess["steps"] is not None:
        sess["steps"].append({"action": int(action), "by": by, "label": label})


# ============================================================
# 随机配置生成（2026-10-09）：自由参数 → 随机卡组/遗物/遭遇
# ============================================================

# CardDef 模板 → 前端卡 id（"模块:常量名"）的反查表
CARD_ID_BY_OBJ: dict[int, str] = {id(obj): cid for cid, obj in CARDS.items()}

_CHAR_COLOR = {"ironclad": "Red", "silent": "Green", "defect": "Blue", "watcher": "Purple"}


def _build_reward_pools() -> dict[str, dict[str, list[CardDef]]]:
    """各职业奖励池（稀有度分桶）。铁甲直接用 run_env.CARD_POOLS（与
    sampled_env 训练分布逐位同源，含 RAGE / HAND_OF_GREED 补齐）；其余
    职业按 wiki cards.json 的 rarity + color 现建（口径同 run_env 的
    构建法；color 过滤防跨职业同名卡误入，如 4 个 Strike 都叫 "Strike"）。
    """
    out: dict[str, dict[str, list[CardDef]]] = {"ironclad": CARD_POOLS}
    wiki = _load_json(ROOT / "wiki_data/cards.json")["cards"]
    by_name = {c["name"]: c for c in wiki}
    for char, color in _CHAR_COLOR.items():
        if char == "ironclad":
            continue
        mod = {"silent": cards_silent, "defect": cards_defect,
               "watcher": cards_watcher}[char]
        pools = {"common": [], "uncommon": [], "rare": []}
        seen: set[int] = set()
        for _varname, d in vars(mod).items():
            if _varname.startswith("_") or not isinstance(d, CardDef) or id(d) in seen:
                continue
            seen.add(id(d))
            w = by_name.get(d.name)
            if w is None or w.get("color") != color:
                continue
            rar = (w.get("rarity") or "").lower()
            if rar in pools:
                pools[rar].append(d)
        out[char] = pools
    return out


REWARD_POOLS = _build_reward_pools()

_ENCOUNTER_POOLS = {"weak": WEAK_POOL, "strong": STRONG_POOL,
                    "elite": ELITES, "boss": BOSSES}


def random_config(params: dict) -> dict:
    """按自由参数随机生成一套战斗配置（返回给前端填表，可继续手改）。

    - 基础打/防张数直接指定；职业起手的非基础牌（痛击/中和等）保留
    - 新增卡补到目标张数：职业奖励池按真实稀有度分布（3/37/60 + 保底
      计数器，sampled_env 同款口径），每张按 upgrade_pct 概率为升级版
    - 遗物：源码 tier 池 50/32/17 roll + 去重（sampled_env 同款）
    - 遭遇：从指定难度池均匀抽（可选，空 = 保留手选）
    - seed 可选：同 seed 同参数必然生成同一套配置
    """
    import random as _random

    character = params.get("character") or "ironclad"
    if character not in CHARACTERS:
        raise ValueError(f"未知职业：{character}")

    def _clamp(key: str, lo: int, hi: int, default: int) -> int:
        try:
            return max(lo, min(hi, int(params.get(key, default))))
        except (TypeError, ValueError):
            return default

    strikes = _clamp("strikes", 0, 20, 5)
    defends = _clamp("defends", 0, 20, 4)
    deck_size = _clamp("deck_size", 1, 60, 10)
    n_relics = _clamp("relics", 0, 10, 0)
    upgrade_pct = _clamp("upgrade_pct", 0, 100, 30)
    pool_key = params.get("encounter_pool") or ""
    if pool_key and pool_key not in _ENCOUNTER_POOLS:
        raise ValueError(f"未知遭遇池：{pool_key}（可选：weak/strong/elite/boss 或留空）")
    raw_seed = params.get("seed")
    seed = int(raw_seed) if raw_seed not in (None, "") else None
    rng = _random.Random(seed)

    # 基础牌 + 职业起手非基础牌（各职业前两条固定为打击/防御）
    starters = CHARACTERS[character]["deck"]
    deck: list[tuple[str, bool]] = [(starters[0]["id"], False)] * strikes \
        + [(starters[1]["id"], False)] * defends \
        + [(e["id"], False) for e in starters[2:]]

    # 新增卡补到目标张数（目标低于基础张数时按基础为准）
    pools = REWARD_POOLS[character]
    pity = CARD_PITY_START
    for _ in range(max(0, deck_size - len(deck))):
        roll = rng.randint(0, 99) + pity
        if roll < CARD_RARE:
            rar, pity = "rare", CARD_PITY_START
        elif roll < CARD_RARE + CARD_UNCOMMON:
            rar = "uncommon"
        else:
            rar = "common"
            pity = max(CARD_PITY_FLOOR, pity - CARD_PITY_GROWTH)
        pool = pools[rar]
        cid = CARD_ID_BY_OBJ[id(pool[rng.randint(0, len(pool) - 1)])]
        deck.append((cid, rng.randint(1, 100) <= upgrade_pct))

    # 聚合为前端卡组条目 {id, count, upgraded}（同名卡升级/非升级合并）
    counts: dict[str, int] = {}
    upgs: dict[str, int] = {}
    for cid, upgraded in deck:
        counts[cid] = counts.get(cid, 0) + 1
        upgs[cid] = upgs.get(cid, 0) + (1 if upgraded else 0)
    entries = [{"id": cid, "count": n, "upgraded": upgs[cid]}
               for cid, n in counts.items()]

    # 遗物：tier roll + 去重 + 桶枯竭回退（sampled_env 同款）
    relics: list[RelicId] = []
    for _ in range(n_relics):
        roll = rng.randint(0, 99)
        tier = ("COMMON" if roll < RELIC_TIER_COMMON
                else "RARE" if roll > RELIC_TIER_RARE else "UNCOMMON")
        pool = [r for r in RELIC_POOLS[tier] if r not in relics]
        if not pool:
            for alt in ("COMMON", "UNCOMMON", "RARE"):
                pool = [r for r in RELIC_POOLS[alt] if r not in relics]
                if pool:
                    break
        if pool:
            relics.append(pool[rng.randint(0, len(pool) - 1)])

    encounter = (rng.choice(_ENCOUNTER_POOLS[pool_key])
                 if pool_key else None)
    return {
        "character": character,
        "deck": entries,
        "relics": [r.name for r in relics],
        "encounter": encounter,
        "gen_seed": seed,
    }


# ============================================================
# 策略模型：懒加载 + 遭遇难度自动匹配
# ============================================================

# 各档当前基准（EXPERIMENTS.md 四档 v3 终值，训练链更新后手动改这里）
DEFAULT_MODELS = {
    "weak": "sampled_a1_weak_struct_v2.zip",
    "strong": "sampled_a1_strong_struct_v3.zip",
    "elite": "sampled_a1_elite_struct_v3.zip",
    "boss": "sampled_boss_ms_25_70.zip",
}


def encounter_tier(encounter: str) -> str | None:
    """遭遇 → 难度档（run_env 怪池口径；自定义组怪无档）。"""
    if encounter in BOSSES:
        return "boss"
    if encounter in ELITES:
        return "elite"
    if encounter in STRONG_POOL:
        return "strong"
    if encounter in WEAK_POOL:
        return "weak"
    return None


def list_models() -> list[dict]:
    out = []
    for f in sorted(MODELS_DIR.glob("*.zip")):
        defaults = [tier for tier, n in DEFAULT_MODELS.items() if n == f.name]
        out.append({
            "name": f.stem,
            "size_mb": round(f.stat().st_size / 1e6, 1),
            "default_for": defaults[0] if defaults else None,
        })
    return out


_MODEL_CACHE: dict[str, object] = {}  # 名 → 已加载模型（测试可注入 stub）


def load_model(name: str):
    """懒加载 models/<name>.zip（MaskablePPO，CPU）。torch 只在此 import，
    平时启动 webapp 不付出深度学习栈的加载成本。缓存保留最近 2 个
    （单个模型 20~320MB，全存会吃穿内存）。name 可带可不带 .zip 后缀。"""
    name = name.removesuffix(".zip")
    if name in _MODEL_CACHE:
        _MODEL_CACHE[name] = _MODEL_CACHE.pop(name)  # 移到末尾 = LRU
        return _MODEL_CACHE[name]
    path = MODELS_DIR / f"{name}.zip"
    if not path.exists():
        raise ValueError(f"模型不存在：{path}（models/ 下共 {len(list_models())} 个）")
    from sb3_contrib import MaskablePPO  # 懒导入（见模块注释）
    model = MaskablePPO.load(str(path), device="cpu")
    _MODEL_CACHE[name] = model
    while len(_MODEL_CACHE) > 2:
        _MODEL_CACHE.pop(next(iter(_MODEL_CACHE)))
    return model


def resolve_model(sid: str, model_name: str | None):
    """会话模型解析：显式指定 > 会话创建时的选择 > 遭遇难度默认档。"""
    sess = SESSIONS[sid]
    name = model_name or sess["model"]
    if name is None:
        tier = encounter_tier(sess["bc"].encounter)
        if tier is None:
            raise ValueError(
                "自定义组怪无法自动匹配模型——请在控制条手动选择 models/ 下的模型")
        name = DEFAULT_MODELS[tier]
    name = name.removesuffix(".zip")
    if name in _MODEL_CACHE or (MODELS_DIR / f"{name}.zip").exists():
        return name, load_model(name)
    raise ValueError(f"模型不存在：{name}")


def action_detail(env: StsBattleEnv, a: int) -> dict:
    """env 动作 id → 结构化详情（前端高亮 AI 选中的手牌/药水用）。"""
    if a == ACTION_END_TURN:
        return {"kind": "end"}
    if a == SELECT_CONFIRM:
        return {"kind": "confirm"}
    if SELECT_BASE <= a < SELECT_CONFIRM:
        return {"kind": "select", "window": a - SELECT_BASE}
    if SCRY_BASE <= a <= SCRY_BASE + SCRY_KEEP_MAX:
        return {"kind": "scry", "keep_top_n": a - SCRY_BASE}
    if POTION_STANCE_BASE <= a:
        s, c = divmod(a - POTION_STANCE_BASE, len(STANCE_CHOICES))
        return {"kind": "potion", "slot": s, "choice": STANCE_CHOICES[c]}
    if POTION_BASE <= a < POTION_STANCE_BASE:
        s, j = divmod(a - POTION_BASE, N_TARGET_SLOTS + 1)
        return {"kind": "potion", "slot": s,
                "target": None if j == 0 else j - 1}
    if TARGETED_BASE <= a < POTION_BASE:
        i, j = divmod(a - TARGETED_BASE, N_TARGET_SLOTS)
        return {"kind": "play", "hand_index": i, "target": j}
    return {"kind": "play", "hand_index": a - HAND_SLOT_BASE, "target": None}


def ai_step(sid: str, model_name: str | None = None, deterministic: bool = True) -> dict:
    """策略走一步：观测 → mask 过滤预测 → env.step（与训练完全同路径）。"""
    sess = SESSIONS[sid]
    env: StsBattleEnv = sess["env"]
    if env is None:
        raise ValueError("本会话未启用 env 模式（策略演示 / 录制）")
    if env.bc.over:
        raise ValueError("战斗已结束")
    mask = env.action_masks()
    if not mask.any():
        raise ValueError("当前无可执行动作（结算中或战斗已结束）")
    obs = env._get_obs()

    name, model = resolve_model(sid, model_name)
    action, _ = model.predict(obs, action_masks=mask, deterministic=deterministic)
    action = int(action)
    label = action_label(env, action)
    labels = {int(a): action_label(env, a) for a in np.flatnonzero(mask)}
    topk = _masked_topk(model, obs, mask, labels=labels, k=5)
    detail = action_detail(env, action)  # 须在 step 前取（读的是执行前状态）
    step_env_action(sid, action, label, by="ai")
    return {"model": name, "action": action, "label": label,
            "detail": detail, "probs": topk}


def _masked_topk(model, obs, mask, labels: dict, k: int = 5) -> list[dict] | None:
    """掩码后的 top-k 动作概率（演示用；策略无 get_distribution 时返回 None）。"""
    try:
        import torch
        obs_t = torch.as_tensor(obs, dtype=torch.float32).unsqueeze(0)
        with torch.no_grad():
            dist = model.policy.get_distribution(obs_t)
        logits = dist.distribution.logits[0].clone()
        logits[~torch.as_tensor(mask, dtype=torch.bool)] = -float("inf")
        probs = torch.softmax(logits, dim=-1)
        top = torch.topk(probs, k)
        return [{"action": int(i), "p": round(float(p), 4),
                 "label": labels.get(int(i), "")}
                for p, i in zip(top.values.tolist(), top.indices.tolist())]
    except Exception:  # noqa: BLE001 —— 演示附加信息，任何失败都不挡出牌
        return None


# ============================================================
# 固定评测集（人机同局面对比；种子 1001 起，与训练 ≥10_000、评估 0..99 不相交）
# ============================================================

EVAL_SETS: dict[str, list[dict]] = {
    "act1_v1": [
        {"tier": "weak", "encounter": "jaw_worm", "seed": 1001},
        {"tier": "weak", "encounter": "louses", "seed": 1002},
        {"tier": "weak", "encounter": "small_slimes", "seed": 1003},
        {"tier": "strong", "encounter": "large_slime", "seed": 1004},
        {"tier": "strong", "encounter": "three_sentries", "seed": 1005},
        {"tier": "elite", "encounter": "gremlin_nob", "seed": 1006},
        {"tier": "elite", "encounter": "lagavulin", "seed": 1007},
        {"tier": "boss", "encounter": "guardian", "seed": 1008},
        {"tier": "boss", "encounter": "hexaghost", "seed": 1009},
    ],
}


# ============================================================
# 录制：保存 / 列举 / 确定性回放
# ============================================================

RECORD_VERSION = 1


def _record_stem(cfg: dict) -> str:
    if cfg.get("monsters"):
        enc = f"custom{len(cfg['monsters'])}"
    else:
        enc = cfg.get("encounter") or "cultist"
    seed = cfg.get("seed")
    return f"{enc}_{seed if seed is not None else 'rnd'}"


def record_source(steps: list[dict]) -> str:
    by = {s["by"] for s in steps}
    if by == {"human"}:
        return "human"
    if by == {"ai"}:
        return "ai"
    return "mixed"


def save_record(sid: str) -> dict:
    """把已结束的录制会话落盘为 records/*.json（确定性可回放）。"""
    sess = SESSIONS[sid]
    bc: BattleContext = sess["bc"]
    if not sess["record"]:
        raise ValueError("本局未开启录制")
    if not bc.over:
        raise ValueError("战斗尚未结束（录制保存需要终局状态）")
    if sess["steps"] is None or not sess["steps"]:
        raise ValueError("本局没有任何已记录动作")
    source = record_source(sess["steps"])
    rec = {
        "version": RECORD_VERSION,
        "recorded_at": time.strftime("%Y-%m-%dT%H:%M:%S"),
        "source": source,
        "model": sess["model"],
        "eval": sess["eval"],
        "config": sess["cfg"],
        "outcome": bc.outcome.name,
        "final_hp": bc.player.hp,
        "max_hp": bc.player.max_hp,
        "turns": bc.turn,
        "n_steps": len(sess["steps"]),
        "actions": sess["steps"],
    }
    RECORDS_DIR.mkdir(exist_ok=True)
    fname = f"{time.strftime('%Y%m%d_%H%M%S')}_{source}_{_record_stem(sess['cfg'])}.json"
    path = RECORDS_DIR / fname
    with open(path, encoding="utf-8", mode="w") as f:
        json.dump(rec, f, ensure_ascii=False, indent=1)
    sess["saved"] = True
    sess["record_path"] = str(path)
    return {"path": str(path), "source": source, "outcome": rec["outcome"],
            "final_hp": rec["final_hp"], "turns": rec["turns"],
            "n_steps": rec["n_steps"]}


def list_records() -> list[dict]:
    if not RECORDS_DIR.exists():
        return []
    out = []
    for f in sorted(RECORDS_DIR.glob("*.json"), reverse=True):
        try:
            with open(f, encoding="utf-8") as fh:
                rec = json.load(fh)
        except (OSError, json.JSONDecodeError):
            continue
        out.append({
            "file": f.name, "recorded_at": rec.get("recorded_at"),
            "source": rec.get("source"), "model": rec.get("model"),
            "eval": rec.get("eval"), "config": rec.get("config"),
            "outcome": rec.get("outcome"), "final_hp": rec.get("final_hp"),
            "turns": rec.get("turns"), "n_steps": rec.get("n_steps"),
        })
    return out


def replay_record(rec: dict) -> dict:
    """确定性回放录制：重建战斗 → 逐步重演 env 动作，返回训练元组。

    返回 {obs: (N, OBS_DIM), actions: (N,), masks: (N, 120), bc}——
    每步观测/掩码取自执行前状态，与训练时策略所见完全一致。回放终局
    与录制终局不一致会 raise（引擎或记录被改动）。
    """
    bc, character = build_battle(rec["config"])
    env = attach_env(bc, character)
    obs_list, act_list, mask_list = [], [], []
    for i, step in enumerate(rec["actions"]):
        mask = env.action_masks()
        a = int(step["action"])
        if not mask[a]:
            raise ValueError(
                f"回放失配：第 {i + 1} 步动作 {a}（{step.get('label', '')}）"
                "在重建局面下不合法——引擎或记录文件与录制时不一致")
        obs_list.append(env._get_obs())
        mask_list.append(mask)
        act_list.append(a)
        env.step(a)
    if bc.outcome.name != rec.get("outcome") or bc.player.hp != rec.get("final_hp"):
        raise ValueError(
            f"回放终局不一致：实录 {rec.get('outcome')}/HP {rec.get('final_hp')}"
            f" vs 回放 {bc.outcome.name}/HP {bc.player.hp}")
    return {
        "obs": np.stack(obs_list).astype(np.int32),
        "actions": np.array(act_list, dtype=np.int16),
        "masks": np.stack(mask_list),
        "bc": bc,
    }


# ============================================================
# 状态序列化
# ============================================================

def _card_inst(inst) -> dict:
    card: CardDef = inst.card
    return {
        "name": card.name, "zh": card.zh, "cost": inst.cost,
        "ctype": card.ctype, "text": card.text,
        "upgraded": inst.upgraded, "needs_target": card.needs_target,
    }


def _statuses(sts) -> list[dict]:
    out = []
    for s, n in sts.items():
        out.append({"name": s.name, "zh": _status_zh(s), "n": n,
                    "just_applied": sts.just_applied(s)})
    return out


def _intent(bc: BattleContext, m) -> dict | None:
    if not m.move_history:
        return None
    move = m.move_history[0]
    if move.kind == "attack" and move.base_damage is not None:
        dmg = bc.calculate_monster_damage(m, move.base_damage)
        return {"kind": "attack", "zh": move.zh, "damage": dmg,
                "text": move.intent_text}
    return {"kind": move.kind, "zh": move.zh, "damage": None,
            "text": move.intent_text}


_INTENT_KIND_ZH = {"attack": "攻击", "defend": "防御", "buff": "增益",
                   "debuff": "减益", "unknown": "特殊"}


def _playable(bc: BattleContext, inst) -> tuple[bool, str]:
    """与 BattleContext.play_card 的校验逐条对齐（前端置灰 + 提示用）。"""
    if bc.input_state != InputState.PLAYER_NORMAL:
        return False, "结算中"
    card = inst.card
    if card.unplayable and not bc.relics.makes_unplayable_playable(inst):
        return False, "不可打出"
    if card.play_condition is not None and not card.play_condition(bc, inst):
        return False, "不满足打出条件"
    if bc.player.statuses.has(PlayerStatus.ENTANGLED) and card.ctype == "Attack":
        return False, "被缠绕"
    if not bc.relics.check_play_allowed(bc, inst):
        return False, "遗物限制"
    if not card.x_cost:
        cost = inst.cost
        if getattr(card, "dynamic_cost", None) is not None:
            cost = card.dynamic_cost(bc, inst)
        if cost > bc.player.energy:
            return False, f"能量不足（需 {cost}）"
    return True, ""


def serialize(bc: BattleContext, env: StsBattleEnv | None = None) -> dict:
    p = bc.player
    state = {
        "input_state": bc.input_state.name,
        "over": bc.over,
        "outcome": bc.outcome.name,
        "turn": bc.turn,
        "seed": bc.seed,
        "player": {
            "hp": p.hp, "max_hp": p.max_hp, "block": p.block,
            "energy": p.energy, "gold": p.gold,
            "stance": _STANCE_ZH.get(p.stance.name, p.stance.name),
            "raw_stance": p.stance.name,
            "statuses": _statuses(p.statuses),
            "orbs": [_ORB_ZH.get(o.name, o.name) for o in p.orbs],
            "orb_slots": p.orb_slots,
            "dark_stacks": p.dark_stacks,
            "potions": [{
                "pid": pd.pid, "zh": pd.zh, "name": pd.name,
                "description": pd.description, "targeting": pd.targeting,
                "choices": list(pd.choices), "auto_only": pd.auto_only,
                "escape_only": pd.escape_only,
            } if pd is not None else None for pd in p.potions],
            "special": {k: v for k, v in p.special.items()},
        },
        "relics": [{
            **RELIC_BY_ID.get(r.name, {"id": r.name, "name": r.name,
                                        "zh": r.name, "text": ""}),
            "counter": bc.relics.counter(r),
        } for r in bc.relics.relics],
        "monsters": [],
        "hand": [],
        "draw_pile": [],   # 仅构成：按名称聚合 + 计数（顺序不可见，DESIGN.md §4）
        "discard_pile": [],
        "exhaust_pile": [],
        "limbo": [],
        "card_select": None,
        "scry": None,
    }
    for i, m in enumerate(bc.monsters.monsters):
        entry = {
            "pos": i, "zh": m.display_name, "name": getattr(type(m), "name", ""),
            "hp": m.hp, "max_hp": m.max_hp, "block": m.block,
            "alive": m.alive, "escaping": m.is_escaping,
            "half_dead": m.half_dead, "is_dying": m.is_dying,
            "statuses": _statuses(m.statuses),
            "intent": _intent(bc, m),
        }
        if entry["intent"]:
            entry["intent"]["kind_zh"] = _INTENT_KIND_ZH.get(
                entry["intent"]["kind"], entry["intent"]["kind"])
        state["monsters"].append(entry)

    for i, inst in enumerate(bc.cards.hand):
        ok, reason = _playable(bc, inst)
        state["hand"].append({**_card_inst(inst), "index": i,
                              "playable": ok, "reason": reason})

    # 抽牌堆：玩家不可见实际顺序（信息边界，DESIGN.md §4；对齐本体牌堆
    # 查看界面按字母序的口径）——同名（含升级位）聚合计数、按名称排序。
    # Scry 展示的堆顶 N 张是游戏机制合法可见，走 scry 字段不在此列。
    draw_groups: dict[tuple[int, bool], list] = {}
    for inst in bc.cards.draw_pile:
        # 按模板身份（id(CardDef)）分组：同名卡跨职业模板不同（4 个 Strike）
        draw_groups.setdefault((id(inst.card), inst.upgraded), []).append(inst)
    state["draw_pile"] = [
        {**_card_inst(reps[0]), "count": len(reps)}
        for reps in sorted(draw_groups.values(),
                           key=lambda lst: (lst[0].card.name, lst[0].upgraded))
    ]
    state["discard_pile"] = [_card_inst(inst) for inst in bc.cards.discard_pile]
    state["exhaust_pile"] = [_card_inst(inst) for inst in bc.cards.exhaust_pile]
    state["limbo"] = [_card_inst(inst) for inst in bc.cards.limbo]

    if bc.input_state == InputState.CARD_SELECT and bc.card_select_info is not None:
        info: CardSelectInfo = bc.card_select_info
        # 展示顺序按名称排序（对齐本体选卡界面），engine_idx 映射回引擎
        # 候选下标——玩家按牌面选择，不感知抽牌堆内部顺序
        order = sorted(range(len(info.candidates)),
                       key=lambda i: (info.candidates[i].card.name,
                                      info.candidates[i].upgraded))
        # env 模式：候选必须在策略选卡窗口内（词表位稳定序前 10）才能
        # 以训练动作表达——超窗候选前端置灰（DESIGN.md §5.2 近似）
        window_ids = set(env._select_engine_idx) if env is not None else None
        state["card_select"] = {
            "prompt": info.prompt or "请选择卡牌",
            "pick_count": info.pick_count,
            "can_pick_zero": info.can_pick_zero,
            "can_pick_any_number": info.can_pick_any_number,
            "candidates": [{
                **_card_inst(info.candidates[i]), "engine_idx": i,
                **({"in_window": i in window_ids} if window_ids is not None else {}),
            } for i in order],
        }
    if bc.input_state == InputState.SCRY and bc.scry_cards:
        state["scry"] = [_card_inst(inst) for inst in bc.scry_cards]
    return state


def drain_log(sid: str) -> list[str]:
    sess = SESSIONS[sid]
    bc: BattleContext = sess["bc"]
    lines = bc.log[sess["offset"]:]
    sess["offset"] = len(bc.log)
    return lines


# ============================================================
# HTTP 层
# ============================================================

_STATIC_FILES = {
    "/": ("index.html", "text/html; charset=utf-8"),
    "/index.html": ("index.html", "text/html; charset=utf-8"),
    "/app.js": ("app.js", "text/javascript; charset=utf-8"),
    "/style.css": ("style.css", "text/css; charset=utf-8"),
}


def _meta_payload() -> dict:
    return {
        "cards": CARD_META,
        "characters": {k: {"zh": v["zh"], "max_hp": v["max_hp"],
                           "deck": v["deck"]}
                       for k, v in CHARACTERS.items()},
        "encounters": ENCOUNTER_KEYS,
        "monsters": MONSTER_META,
        "relics": RELIC_META,
        "potions": POTION_META,
        "models": list_models(),
        "default_models": DEFAULT_MODELS,
        "eval_sets": {name: [{**e, "i": i} for i, e in enumerate(entries)]
                      for name, entries in EVAL_SETS.items()},
    }


class Handler(BaseHTTPRequestHandler):
    def log_message(self, fmt, *args):  # 默认打 stderr 即可，静默掉逐请求噪音
        pass

    # ---- 响应辅助 ----
    def _json(self, obj, status: int = 200) -> None:
        body = json.dumps(obj, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Cache-Control", "no-store")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _static(self, fname: str, ctype: str) -> None:
        path = WEB_DIR / fname
        try:
            body = path.read_bytes()
        except OSError:
            self._json({"error": "not found"}, 404)
            return
        self.send_response(200)
        self.send_header("Content-Type", ctype)
        self.send_header("Cache-Control", "no-store")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _body(self) -> dict:
        length = int(self.headers.get("Content-Length") or 0)
        raw = self.rfile.read(length) if length else b"{}"
        return json.loads(raw or b"{}")

    # ---- 路由 ----
    def do_GET(self):
        if self.path == "/api/meta":
            self._json(_meta_payload())
            return
        if self.path == "/api/records":
            self._json({"ok": True, "records": list_records()})
            return
        if self.path in _STATIC_FILES:
            fname, ctype = _STATIC_FILES[self.path]
            self._static(fname, ctype)
            return
        self._json({"error": "not found"}, 404)

    def _battle_response(self, sid: str, extra: dict | None = None, ok: bool = True,
                         error: str | None = None, status: int = 200) -> None:
        sess = SESSIONS[sid]
        payload = {
            "ok": ok,
            "state": serialize(sess["bc"], sess["env"]),
            "log": drain_log(sid),
        }
        if extra:
            payload.update(extra)
        if error:
            payload["error"] = error
        self._json(payload, status)

    def do_POST(self):
        try:
            body = self._body()
        except json.JSONDecodeError as e:
            self._json({"error": f"JSON 解析失败：{e}"}, 400)
            return
        if self.path == "/api/random_config":
            try:
                cfg = random_config(body)
            except ValueError as e:
                self._json({"ok": False, "error": str(e)}, 400)
                return
            except Exception:
                self._json({"ok": False, "error": traceback.format_exc()}, 400)
                return
            self._json({"ok": True, **cfg})
            return
        if self.path == "/api/battle/new":
            try:
                sid = create_battle(body)
            except Exception:
                self._json({"ok": False, "error": traceback.format_exc()}, 400)
                return
            self._battle_response(sid, extra={"id": sid})
            return
        if self.path == "/api/battle/action":
            sid = body.get("id")
            if sid not in SESSIONS:
                self._json({"ok": False, "error": f"会话不存在：{sid}"}, 404)
                return
            try:
                apply_action(sid, body)
            except ValueError as e:  # 引擎拒绝 / env 动作映射失败：合法输入的边界情况
                self._battle_response(sid, ok=False, error=str(e))
                return
            except Exception:  # 引擎 bug：原样抛出 traceback 供定位
                self._battle_response(
                    sid, ok=False,
                    error="引擎异常：\n" + traceback.format_exc())
                return
            self._battle_response(sid)
            return
        if self.path == "/api/battle/ai_step":
            sid = body.get("id")
            if sid not in SESSIONS:
                self._json({"ok": False, "error": f"会话不存在：{sid}"}, 404)
                return
            try:
                info = ai_step(sid, body.get("model"),
                               deterministic=bool(body.get("deterministic", True)))
            except ValueError as e:
                self._battle_response(sid, ok=False, error=str(e))
                return
            except Exception:
                self._battle_response(
                    sid, ok=False,
                    error="引擎/模型异常：\n" + traceback.format_exc())
                return
            self._battle_response(sid, extra={"ai": info})
            return
        if self.path == "/api/battle/record_save":
            sid = body.get("id")
            if sid not in SESSIONS:
                self._json({"ok": False, "error": f"会话不存在：{sid}"}, 404)
                return
            try:
                saved = save_record(sid)
            except ValueError as e:
                self._json({"ok": False, "error": str(e)}, 400)
                return
            self._json({"ok": True, **saved})
            return
        self._json({"error": "not found"}, 404)


def main() -> None:
    parser = argparse.ArgumentParser(description="STS 战斗网页调试器")
    parser.add_argument("--port", type=int, default=8765)
    parser.add_argument("--host", default="127.0.0.1")
    args = parser.parse_args()
    server = HTTPServer((args.host, args.port), Handler)
    print(f"战斗调试器已启动：http://{args.host}:{args.port}/")
    print("角色 / 卡组 / 遗物 / 药水 / 怪物均可在页面自定义；Ctrl+C 退出。")
    print("「策略演示 / 录制」面板：AI 单步/自动出牌（模型按遭遇难度自动匹配）、"
          "人操录制保存 records/（scripts/export_records.py 可转 npz）。")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\n已退出。")


if __name__ == "__main__":
    main()

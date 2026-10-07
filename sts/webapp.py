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
"""

from __future__ import annotations

import argparse
import itertools
import json
import traceback
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path

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

ROOT = Path(__file__).resolve().parent.parent
WEB_DIR = Path(__file__).resolve().parent / "web"

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


def create_battle(cfg: dict) -> str:
    """按配置构造 BattleContext 并登记会话，返回会话 id。"""
    char = CHARACTERS[cfg.get("character", "ironclad")]

    deck: list[CardDef] = []
    up_counts: dict[int, int] = {}  # id(CardDef) → 待标记升级的实例数
    for e in cfg.get("deck") or char["deck"]:
        card = CARDS[e["id"]]
        n = max(0, int(e.get("count", 1)))
        u = max(0, min(int(e.get("upgraded", 0)), n))
        deck.extend([card] * n)
        if u:
            up_counts[id(card)] = up_counts.get(id(card), 0) + u

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

    # 升级位标记：deck 参数只传 CardDef 模板，upgraded 是实例属性——
    # 构造时首回合手牌已抽好，draw_pile 与 hand 都要走
    for inst in list(bc.cards.draw_pile) + list(bc.cards.hand):
        left = up_counts.get(id(inst.card), 0)
        if left > 0:
            inst.upgraded = True
            up_counts[id(inst.card)] = left - 1

    # 职业最大生命（引擎固定 Player(80)，构造后修正；见模块注释的近似说明）
    if char["max_hp"] != 80:
        bc.player.max_hp = char["max_hp"]
        bc.player.hp = min(bc.player.hp, char["max_hp"])

    sid = f"b{next(_SEQ)}"
    SESSIONS[sid] = {"bc": bc, "offset": 0, "cfg": cfg}
    while len(SESSIONS) > _MAX_SESSIONS:
        SESSIONS.pop(next(iter(SESSIONS)))
    return sid


def apply_action(sid: str, body: dict) -> None:
    """对会话执行一个玩家动作。ValueError = 引擎拒绝（返回给前端提示），
    其余异常 = 引擎 bug，向上抛给调用方附 traceback。"""
    bc: BattleContext = SESSIONS[sid]["bc"]
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


def serialize(bc: BattleContext) -> dict:
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
        state["card_select"] = {
            "prompt": info.prompt or "请选择卡牌",
            "pick_count": info.pick_count,
            "can_pick_zero": info.can_pick_zero,
            "can_pick_any_number": info.can_pick_any_number,
            "candidates": [{**_card_inst(info.candidates[i]), "engine_idx": i}
                           for i in order],
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
        if self.path in _STATIC_FILES:
            fname, ctype = _STATIC_FILES[self.path]
            self._static(fname, ctype)
            return
        self._json({"error": "not found"}, 404)

    def do_POST(self):
        try:
            body = self._body()
        except json.JSONDecodeError as e:
            self._json({"error": f"JSON 解析失败：{e}"}, 400)
            return
        if self.path == "/api/battle/new":
            try:
                sid = create_battle(body)
            except Exception:
                self._json({"ok": False, "error": traceback.format_exc()}, 400)
                return
            self._json({"ok": True, "id": sid,
                        "state": serialize(SESSIONS[sid]["bc"]),
                        "log": drain_log(sid)})
            return
        if self.path == "/api/battle/action":
            sid = body.get("id")
            if sid not in SESSIONS:
                self._json({"ok": False, "error": f"会话不存在：{sid}"}, 404)
                return
            try:
                apply_action(sid, body)
            except ValueError as e:  # 引擎拒绝：合法输入的边界情况
                self._json({"ok": False, "error": str(e),
                            "state": serialize(SESSIONS[sid]["bc"]),
                            "log": drain_log(sid)})
                return
            except Exception:  # 引擎 bug：原样抛出 traceback 供定位
                self._json({"ok": False, "error": "引擎异常：\n" + traceback.format_exc(),
                            "state": serialize(SESSIONS[sid]["bc"]),
                            "log": drain_log(sid)}, 200)
                return
            self._json({"ok": True,
                        "state": serialize(SESSIONS[sid]["bc"]),
                        "log": drain_log(sid)})
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
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\n已退出。")


if __name__ == "__main__":
    main()

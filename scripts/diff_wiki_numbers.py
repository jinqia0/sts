"""数值级自动对照脚本：铁甲战士 + 无色 + 诅咒 vs wiki_data/cards.json。

scripts/diff_wiki.py 只做结构层（费用/类型/关键词/HP）；本脚本补数值层
（伤害/格挡/层数），方法为**行为探针**：

对每张 wiki 含 damage / block / magic_number 的卡，构造干净战斗
（无 buff、无遗物、无 relic、jaw_worm / two_fungi_beasts 遭遇），
把该卡（升级 / 未升级各一次）塞入手牌并 bc.play_card 打出，在引擎
效果入口包一层记录器采集净效果：

  - damage：所有 calculate_card_damage(item, target, BASE) 的 BASE
    入参。wiki 的 damage 是**单段基础值**（不含力量/虚弱/易伤管线），
    BASE 即同一语义——多段卡（Twin Strike×2 / Pummel×4 / Sword
    Boomerang×3）每段的 BASE 须全等于 wiki 值，另校验段数。
  - block：所有 calculate_card_block(BASE) 的 BASE 入参。
  - magic：逐卡定义的可观察映射——debuff 层数（statuses.add 事件）/
    抽牌数（draw_cards 请求值）/ 力量等 Power 层数 / 自伤 HP /
    特殊计数槽（fnp_base / the_bomb / panache 等）。
  - 段数：attack_enemy / attack_random_enemy(count) /
    attack_all_enemy(×存活怪数) 的工厂调用计数。

AoE 卡用双怪遭遇（two_fungi_beasts），逐怪的 BASE 各对照一次；
X 费（Whirlwind）以固定 3 能量探针；需要局面条件的卡做受控前置
（Clash 手牌全攻击 / Impatience 手牌无攻击 / Dropkick 预置易伤 /
Spot Weakness 用首回合必为攻击意图的 jaw_worm）。

动态值卡排除（行为依赖局面，无法用固定基础值对照，已人工审计）：
  Perfected Strike（伤害 = "打击"牌计数；受控计数下查每张加伤 2/3）/
  Feed 击杀奖励（MaxHP+3/4）/ Hand of Greed 击杀奖励（金币 20/25）/
  Reaper 吸血量 / Body Slam / Mind Blast / Regret（后四者 wiki 无数值字段）。
  见运行报告"动态排除清单"。

另覆盖回合末自动结算的诅咒/状态（Burn/Decay/Doubt/Shame：end_turn 探针）、
Heavy Blade 力量乘区（1 力量受控探针，wiki magic 3/5）与 2026-10-07
wiki_data 抓取补值批的 23 张卡（见 wiki_data/cards.json meta.manual_fixes）。

用法：uv run python scripts/diff_wiki_numbers.py
输出：每张卡 PASS / FAIL（含 wiki 期望 vs 实现观测）/ 动态跳过，
      末尾汇总。FAIL 为 0 即数值层全对齐。
"""

from __future__ import annotations

import json
import sys
import traceback
from dataclasses import dataclass
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from sts.combat.actions import Actions  # noqa: E402
from sts.combat.battle import BattleContext  # noqa: E402
from sts.combat.types import InputState, MonsterStatus, PlayerStatus  # noqa: E402
from sts.content.cards._base import CardDef  # noqa: E402
from sts.content.cards import colorless as CL  # noqa: E402
from sts.content.cards import curses as CU  # noqa: E402
from sts.content.cards import ironclad as IC  # noqa: E402

PROBE_SEED = 20261007
SINGLE = "jaw_worm"          # 单怪（首回合意图必为攻击 Chomp）
AOE = "two_fungi_beasts"     # 双怪（AoE / 全体 debuff 逐怪校验）

# ---------------------------------------------------------------------------
# 探针规格
# ---------------------------------------------------------------------------


@dataclass
class Spec:
    encounter: str = SINGLE
    fillers: tuple = ()               # 探针卡之外的手牌填充（CardDef 元组）
    hand_override: tuple | None = None  # (手牌 CardDef 列表, 出牌下标)——Pain 特例
    energy: int = 9                   # 探针能量（覆盖一切费用；Whirlwind 固定 3）
    pre: object = None                # 出牌前布置（如 Dropkick 预置易伤）
    hits: tuple | None = (1, 1)       # 期望段数 (基础, 升级)；None = 不校验段数
    mode: str = "play"                # play=打出探针卡 / end_turn=回合末自动结算（诅咒/灼伤）
    draw_pile: tuple | None = None    # 抽牌堆覆盖（CardDef 元组；() = 清空——Perfected Strike/Violence）
    choose: object = None             # 选卡解析策略 (info)->indices（默认 [0]；Purity 取满 pick_count）
    dmg_expect: object = None         # calc 基础值期望覆盖 (upgraded)->int（Heavy Blade 力量乘区）
    # damage / block 的观测来源：
    #   "calc"            —— 走 calculate_card_damage/block 管线（默认）
    #   ("special", key)  —— player.special[key] 计数槽（FNP/The Bomb 等）
    #   ("pstatus", st)   —— 玩家状态层数（Flame Barrier 反伤/Metallicize）
    #   ("ev", kind)      —— 事件流里该类事件的全部取值（Burn/Decay 回合末伤害）
    #   "skip"           —— 动态值，跳过
    dmg: object = "calc"
    blk: object = "calc"
    magic: tuple = ()                 # (标签, 提取器) 列表，对照 wiki magic_number
    magic_skip: bool = False          # wiki magic 条件性/动态（如 Feed 击杀奖励）
    note: str = ""                    # 报告附注（动态原因等）


# ---- magic 提取器（返回观测值集合，须恰好 == wiki 值）----


def m_debuff(status: MonsterStatus):
    def ext(ev, bc, pre):
        return {e[3] for e in ev if e[0] == "m_status" and e[2] == status}
    return ext


def m_pstatus(status: PlayerStatus):
    def ext(ev, bc, pre):
        return {e[2] for e in ev if e[0] == "p_status" and e[1] == status}
    return ext


def m_draw():
    def ext(ev, bc, pre):
        return {e[1] for e in ev if e[0] == "draw"}
    return ext


def m_lose_hp():
    def ext(ev, bc, pre):
        return {e[1] for e in ev if e[0] == "lose_hp"}
    return ext


def m_special(key: str):
    def ext(ev, bc, pre):
        return {bc.player.special.get(key, 0)}
    return ext


def m_exhaust_delta():
    def ext(ev, bc, pre):
        return {len(bc.cards.exhaust_pile) - pre["exhaust"]}
    return ext


def m_heal():
    def ext(ev, bc, pre):
        return {e[1] for e in ev if e[0] == "heal"}
    return ext


def m_debuff_abs(status: MonsterStatus):
    """力量减益类（Disarm/Dark Shackles）：实现侧为负数事件，取绝对值。"""
    def ext(ev, bc, pre):
        return {abs(e[3]) for e in ev if e[0] == "m_status" and e[2] == status}
    return ext


def _attack_times(ev, bc, pre):
    """攻击段数（Pummel 的 wiki magic = 次数）：单怪口径。"""
    n = sum(1 for e in ev if e[0] == "attack_enemy")
    n += sum(e[2] for e in ev if e[0] == "attack_random_enemy")
    n += sum(1 for e in ev if e[0] == "attack_all_enemy")
    return {n}


def _hand_size(ev, bc, pre):
    """打出后手牌数（Jack of All Trades/Violence 的生成张数，无其他手牌变动）。"""
    return {len(bc.cards.hand)}


def _draw_pile_delta(ev, bc, pre):
    """抽牌堆增量（Chrysalis/Metamorphosis 的洗入张数）。"""
    return {len(bc.cards.draw_pile) - pre["draw"]}


def _rampage_misc(ev, bc, pre):
    """Rampage 打出后的永久叠伤（落弃牌堆实例的 misc_data）。"""
    return {c.misc_data for c in bc.cards.discard_pile if c.card.name == "Rampage"}


def _dual_wield_copies(ev, bc, pre):
    """Dual Wield 复制份数 = 手中 Strike 数 - 1（原 filler 不算复制）。"""
    return {sum(1 for c in bc.cards.hand if c.card.name == "Strike") - 1}


def _purity_exhaust(ev, bc, pre):
    """Purity 消耗上限 = 消耗堆增量 - 1（自身消耗不计）。"""
    return {len(bc.cards.exhaust_pile) - pre["exhaust"] - 1}


def _heavy_blade_mult(ev, bc, pre):
    """Heavy Blade 力量计入次数 = 最终伤害 - 14（pre 置 1 力量）。"""
    return {e[2] - 14 for e in ev if e[0] == "attack_enemy"}


def _perfected_per_strike(ev, bc, pre):
    """Perfected Strike 每张打击加伤 = 最终伤害 - 6（抽/弃/手清空，计数=自身 1 张）。"""
    return {e[2] - 6 for e in ev if e[0] == "attack_enemy"}


def _str1(bc: BattleContext) -> None:
    bc.player.statuses.add(PlayerStatus.STRENGTH, 1)


def _choose_up_to(info) -> list[int]:
    """选满 pick_count（Purity 的 up to N 语义）。"""
    return list(range(min(info.pick_count, len(info.candidates))))


def _vuln_target0(bc: BattleContext) -> None:
    bc.monsters.monsters[0].statuses.add(MonsterStatus.VULNERABLE, 1)


V, W = MonsterStatus.VULNERABLE, MonsterStatus.WEAK
S = PlayerStatus

SPECS: dict[str, Spec] = {
    # ---- 铁甲战士 ----
    "Anger": Spec(),
    "Armaments": Spec(),
    "Bash": Spec(magic=(("易伤层数", m_debuff(V)),)),
    "Battle Trance": Spec(magic=(("抽牌数", m_draw()),)),
    "Blood for Blood": Spec(),
    "Bloodletting": Spec(magic=(("失去HP", m_lose_hp()),)),
    "Bludgeon": Spec(),
    "Brutality": Spec(magic=(("残暴层数", m_pstatus(S.BRUTALITY)),)),
    "Carnage": Spec(),
    "Clash": Spec(fillers=(IC.STRIKE, IC.STRIKE)),  # 打出条件：手牌全攻击
    "Cleave": Spec(encounter=AOE, hits=(2, 2)),
    "Clothesline": Spec(magic=(("虚弱层数", m_debuff(W)),)),
    "Combust": Spec(dmg=("special", "combust_base"),
                    magic=(("COMBUST层数", m_pstatus(S.COMBUST)),)),
    "Dark Embrace": Spec(magic=(("DARK_EMBRACE层数", m_pstatus(S.DARK_EMBRACE)),)),
    "Defend": Spec(),
    "Demon Form": Spec(magic=(("恶魔形态层数", m_pstatus(S.DEMON_FORM)),)),
    "Dropkick": Spec(pre=_vuln_target0, hits=None,
                     magic=(("易伤奖励抽牌", m_draw()),)),
    "Evolve": Spec(magic=(("进化层数", m_pstatus(S.EVOLVE)),)),
    "Feed": Spec(hits=None, magic_skip=True,
                 note="magic=击杀奖励 MaxHP+3/4（条件性，跳过）"),
    "Feel No Pain": Spec(blk=("special", "fnp_base")),
    "Fiend Fire": Spec(fillers=(IC.DEFEND, IC.DEFEND), hits=(2, 2),
                       note="段数=打出时手牌数（受控 2 张）"),
    "Fire Breathing": Spec(dmg=("special", "fire_breathing_base")),
    "Flame Barrier": Spec(dmg=("pstatus", S.FLAME_BARRIER)),  # wiki damage=反伤值
    "Flex": Spec(magic=(("力量层数", m_pstatus(S.STRENGTH)),)),
    "Ghostly Armor": Spec(),
    "Hand of Greed": Spec(hits=None),
    "Headbutt": Spec(),
    "Heavy Blade": Spec(),
    "Hemokinesis": Spec(magic=(("失去HP", m_lose_hp()),)),
    "Immolate": Spec(encounter=AOE, hits=(2, 2)),
    "Impervious": Spec(),
    "Inflame": Spec(magic=(("力量层数", m_pstatus(S.STRENGTH)),)),
    "Intimidate": Spec(encounter=AOE, magic=(("全体虚弱层数", m_debuff(W)),)),
    "Iron Wave": Spec(),
    "Juggernaut": Spec(dmg=("special", "juggernaut_base")),
    "Metallicize": Spec(blk=("pstatus", S.METALLICIZE)),  # wiki block=回合末格挡层数
    "Perfected Strike": Spec(dmg="skip", blk="skip", hits=None,
                             note="伤害=打击牌计数（动态，人工审计过）"),
    "Pommel Strike": Spec(magic=(("抽牌数", m_draw()),)),
    "Power Through": Spec(),
    "Pummel": Spec(hits=(4, 5)),
    "Reaper": Spec(encounter=AOE, hits=None, note="吸血量动态；仅基础值/段外对照"),
    "Reckless Charge": Spec(),
    "Rupture": Spec(magic=(("破裂层数", m_pstatus(S.RUPTURE)),)),
    "Searing Blow": Spec(note="升级版按 n=1 次升级对照（12→16）"),
    "Second Wind": Spec(),
    "Sentinel": Spec(),
    "Sever Soul": Spec(),
    "Shockwave": Spec(encounter=AOE, magic=(("全体虚弱层数", m_debuff(W)),
                                           ("全体易伤层数", m_debuff(V)))),
    "Shrug It Off": Spec(magic=(("抽牌数", m_draw()),)),
    "Spot Weakness": Spec(magic=(("力量层数", m_pstatus(S.STRENGTH)),)),
    "Strike": Spec(),
    "Sword Boomerang": Spec(hits=(3, 4)),
    "Thunderclap": Spec(encounter=AOE, hits=(2, 2),
                        magic=(("全体易伤层数", m_debuff(V)),)),
    "True Grit": Spec(fillers=(IC.DEFEND,), magic=(("消耗手牌数", m_exhaust_delta()),)),
    "Twin Strike": Spec(hits=(2, 2)),
    "Uppercut": Spec(magic=(("虚弱层数", m_debuff(W)), ("易伤层数", m_debuff(V)))),
    "Warcry": Spec(magic=(("抽牌数", m_draw()),)),
    "Whirlwind": Spec(energy=3, hits=None, note="X 费以 3 能量探针（基础值）"),
    "Wild Strike": Spec(),
    # ---- 铁甲战士（wiki_data 抓取补值批：2026-10-07 数值对照补齐 magic 字段）----
    "Berserk": Spec(magic=(("易伤层数", m_pstatus(S.VULNERABLE)),)),
    "Burning Pact": Spec(magic=(("抽牌数", m_draw()),)),
    "Disarm": Spec(magic=(("力量减益", m_debuff_abs(MonsterStatus.STRENGTH)),)),
    "Heavy Blade": Spec(pre=_str1, dmg_expect=lambda up: 14 + (4 if up else 2),
                        magic=(("力量计入次数", _heavy_blade_mult),)),
    "Offering": Spec(magic=(("抽牌数", m_draw()),)),
    "Dual Wield": Spec(fillers=(IC.STRIKE,), magic=(("复制份数", _dual_wield_copies),)),
    "Perfected Strike": Spec(dmg="skip", draw_pile=(),
                             magic=(("每张打击加伤", _perfected_per_strike),),
                             note="受控计数=1（仅自身）：伤害=6+2/3，基础伤害 6 恒定"),
    "Pummel": Spec(hits=(4, 5), magic=(("攻击次数", _attack_times),)),
    "Rampage": Spec(magic=(("每次叠伤", _rampage_misc),),
                    note="对照首次打出的基础值（+5/8 叠加不查）"),
    "Hand of Greed": Spec(hits=None, magic_skip=True,
                          note="magic=击杀奖励金币 20/25（条件性，跳过）"),
    # ---- 无色（同批补值）----
    "Bandage Up": Spec(magic=(("回复HP", m_heal()),)),
    "Chrysalis": Spec(magic=(("洗入技能张数", _draw_pile_delta),)),
    "Dark Shackles": Spec(magic=(("力量减益", m_debuff_abs(MonsterStatus.STRENGTH)),)),
    "Jack of All Trades": Spec(magic=(("生成张数", _hand_size),)),
    "Metamorphosis": Spec(magic=(("洗入攻击张数", _draw_pile_delta),)),
    "Panacea": Spec(magic=(("人工制品层数", m_pstatus(S.ARTIFACT)),)),
    "Purity": Spec(fillers=(IC.DEFEND,) * 5, choose=_choose_up_to,
                   magic=(("消耗上限", _purity_exhaust),)),
    "Sadistic Nature": Spec(magic=(("施虐层数", m_pstatus(S.SADISTIC)),)),
    "Violence": Spec(draw_pile=(IC.STRIKE,) * 5, magic=(("入手攻击张数", _hand_size),)),
    # ---- 无色 ----
    "Blind": Spec(encounter=AOE, magic=(("虚弱层数", m_debuff(W)),)),
    "Deep Breath": Spec(magic=(("抽牌数", m_draw()),)),
    "Dramatic Entrance": Spec(encounter=AOE, hits=(2, 2)),
    "Finesse": Spec(magic=(("抽牌数", m_draw()),)),
    "Flash of Steel": Spec(magic=(("抽牌数", m_draw()),)),
    "Good Instincts": Spec(),
    "Impatience": Spec(fillers=(IC.DEFEND, IC.DEFEND),  # 条件：手牌无攻击
                       magic=(("抽牌数", m_draw()),)),
    "Master of Strategy": Spec(magic=(("抽牌数", m_draw()),)),
    "Panache": Spec(dmg=("special", "panache")),
    "Panic Button": Spec(),
    "Swift Strike": Spec(),
    "The Bomb": Spec(dmg=("special", "the_bomb")),
    "Thinking Ahead": Spec(magic=(("抽牌数", m_draw()),)),
    "Trip": Spec(encounter=AOE, magic=(("易伤层数", m_debuff(V)),)),
    # ---- 诅咒 ----
    "Pain": Spec(hand_override=((CU.PAIN, IC.STRIKE), 1), dmg="skip", blk="skip",
                hits=None, magic=(("每牌失HP", m_lose_hp()),),
                note="探针打出手牌中的 Strike，观测 Pain 的每牌失 HP"),
    # ---- 诅咒/状态（回合末自动结算：end_turn 探针）----
    "Burn": Spec(mode="end_turn", dmg=("ev", "dmg_player"), hits=None),
    "Decay": Spec(mode="end_turn", dmg=("ev", "dmg_player"), hits=None),
    "Doubt": Spec(mode="end_turn", magic=(("虚弱层数", m_pstatus(S.WEAK)),), hits=None),
    "Shame": Spec(mode="end_turn", magic=(("脆弱层数", m_pstatus(S.FRAIL)),), hits=None),
}


# ---------------------------------------------------------------------------
# 记录器：在引擎效果入口包一层（实例方法 + Actions 工厂），用后即还原
# ---------------------------------------------------------------------------

_ACTIONS_RECORD = ("attack_enemy", "attack_all_enemy", "attack_random_enemy",
                   "gain_energy", "gain_block")


class Recorder:
    def __init__(self, bc: BattleContext):
        self.bc = bc
        self.ev: list[tuple] = []
        self._undo: list = []

    # -- 安装 / 还原 --
    def _wrap_bound(self, obj, name, emit):
        orig = getattr(obj, name)

        def wrap(*a, **k):
            emit(a)
            return orig(*a, **k)

        setattr(obj, name, wrap)
        self._undo.append(lambda: setattr(obj, name, orig))

    def _wrap_actions(self):
        for name in _ACTIONS_RECORD:
            orig = Actions.__dict__[name]

            def make(orig_fn, name):
                def rec(*a, **k):
                    self.ev.append((name,) + tuple(a))
                    return orig_fn(*a, **k)
                return rec

            setattr(Actions, name, staticmethod(make(orig.__func__, name)))
            self._undo.append(lambda o=orig, n=name: setattr(Actions, n, o))

    def install(self) -> None:
        bc = self.bc
        self._wrap_bound(bc, "calculate_card_damage",
                         lambda a: self.ev.append(("dmg_calc", a[2], a[1])))
        self._wrap_bound(bc, "calculate_card_block",
                         lambda a: self.ev.append(("blk_calc", a[0])))
        self._wrap_bound(bc, "draw_cards",
                         lambda a: self.ev.append(("draw", a[0])))
        p = bc.player
        self._wrap_bound(p, "lose_hp", lambda a: self.ev.append(("lose_hp", a[1])))
        self._wrap_bound(p, "damage", lambda a: self.ev.append(("dmg_player", a[1])))
        self._wrap_bound(p, "heal", lambda a: self.ev.append(("heal", a[0])))
        self._wrap_bound(p.statuses, "add",
                         lambda a: self.ev.append(("p_status", a[0], a[1])))
        for m in bc.monsters.monsters:
            self._wrap_bound(m.statuses, "add",
                             lambda a, m=m: self.ev.append(("m_status", m.idx, a[0], a[1])))
        self._wrap_actions()

    def restore(self) -> None:
        for undo in reversed(self._undo):
            undo()
        self._undo.clear()

    # -- 观测聚合 --
    def calc_dmg_bases(self) -> set[int]:
        return {e[1] for e in self.ev if e[0] == "dmg_calc"}

    def calc_blk_bases(self) -> set[int]:
        return {e[1] for e in self.ev if e[0] == "blk_calc"}

    def attack_hits(self, alive: int) -> int:
        n = sum(1 for e in self.ev if e[0] == "attack_enemy")
        n += sum(e[2] for e in self.ev if e[0] == "attack_random_enemy")
        n += alive * sum(1 for e in self.ev if e[0] == "attack_all_enemy")
        return n


# ---------------------------------------------------------------------------
# 探针执行
# ---------------------------------------------------------------------------


def probe(card_def: CardDef, upgraded: bool, spec: Spec):
    """干净战斗中打出一张卡（升级位可调），返回 (事件流, 战斗上下文, 前置快照)。"""
    bc = BattleContext(seed=PROBE_SEED, encounter=spec.encounter)
    bc.cards.hand.clear()  # 初始 5 张移出战斗（只留探针手牌）
    if spec.hand_override is not None:
        cards, play_idx = spec.hand_override
        bc.cards.hand = [bc.cards.instantiate(c) for c in cards]
    else:
        inst = bc.cards.instantiate(card_def)
        inst.upgraded = upgraded
        bc.cards.hand = [inst] + [bc.cards.instantiate(f) for f in spec.fillers]
        play_idx = 0
    if spec.draw_pile is not None:
        bc.cards.draw_pile = [bc.cards.instantiate(c) for c in spec.draw_pile]
    if spec.pre is not None:
        spec.pre(bc)
    pre = {
        "exhaust": len(bc.cards.exhaust_pile),
        "draw": len(bc.cards.draw_pile),
        "alive": sum(1 for m in bc.monsters.monsters if not m.is_dead_or_escaped()),
    }
    bc.player.energy = spec.energy
    rec = Recorder(bc)
    rec.install()
    try:
        if spec.mode == "end_turn":
            # 诅咒/灼伤的回合末自动结算（no-trigger）：留在手中直接结束回合
            bc.end_turn()
        else:
            bc.play_card(play_idx, target=0)
            guard = 0
            while bc.input_state == InputState.CARD_SELECT and guard < 10:
                indices = ([0] if spec.choose is None
                           else spec.choose(bc.card_select_info))
                bc.choose_cards(indices)
                guard += 1
            if bc.input_state == InputState.CARD_SELECT:
                raise RuntimeError("选卡解析循环超限")
    finally:
        rec.restore()
    return rec, bc, pre


# ---------------------------------------------------------------------------
# 对照逻辑
# ---------------------------------------------------------------------------


def _observed(src, rec: Recorder, bc: BattleContext) -> set:
    if src == "calc":
        return None  # 由调用方区分 dmg/blk
    if isinstance(src, tuple) and src[0] == "special":
        return {bc.player.special.get(src[1], 0)}
    if isinstance(src, tuple) and src[0] == "pstatus":
        return {e[2] for e in rec.ev if e[0] == "p_status" and e[1] == src[1]}
    if isinstance(src, tuple) and src[0] == "ev":
        return {e[1] for e in rec.ev if e[0] == src[1]}
    return set()


def check_card(card_def: CardDef, wiki: dict) -> tuple[str, list[str], list[str]]:
    """返回 (结论, 明细行, 附注)。结论：PASS / FAIL / SKIP / ERR。"""
    spec = SPECS.get(card_def.name)
    if spec is None:
        return "SKIP", [], [f"无探针规格（wiki 有数值字段）——需补 SPECS 表"]

    fails: list[str] = []
    notes = [spec.note] if spec.note else []
    played_other = spec.hand_override is not None  # Pain：出的是别的牌

    for upgraded in (False, True):
        wdmg = wiki["damage_upgraded"] if upgraded else wiki["damage"]
        wblk = wiki["block_upgraded"] if upgraded else wiki["block"]
        wmag = wiki["magic_number_upgraded"] if upgraded else wiki["magic_number"]
        tag = f"{card_def.name}{'+' if upgraded else ''}"
        if wdmg is None and wblk is None and wmag is None:
            continue  # 该升级位无 wiki 数值（如诅咒不可升级）
        try:
            rec, bc, pre = probe(card_def, upgraded, spec)
        except Exception:
            fails.append(f"[{tag}] 探针异常:\n{traceback.format_exc(limit=3)}")
            continue

        # ---- damage ----
        if wdmg is not None:
            if spec.dmg == "skip":
                notes.append(f"{tag} damage={wdmg} 动态跳过")
            elif spec.dmg == "calc":
                # Heavy Blade 等：力量乘区在 play 内先并入 base，期望值随之覆盖
                exp = spec.dmg_expect(upgraded) if spec.dmg_expect else wdmg
                obs = rec.calc_dmg_bases()
                if not obs or obs != {exp}:
                    fails.append(f"[{tag}] 伤害基础值: wiki {wdmg} / 实现 {sorted(obs) or '无'}")
            else:
                obs = _observed(spec.dmg, rec, bc)
                if obs != {wdmg}:
                    fails.append(f"[{tag}] 伤害{spec.dmg[1]}: wiki {wdmg} / 实现 {sorted(obs)}")
        elif not played_other:
            # wiki 无 damage：实现不应走伤害管线
            if spec.dmg == "calc" and rec.calc_dmg_bases():
                fails.append(f"[{tag}] wiki 无 damage / 实现有伤害基础值 {sorted(rec.calc_dmg_bases())}")

        # ---- block ----
        if wblk is not None:
            if spec.blk == "skip":
                notes.append(f"{tag} block={wblk} 动态跳过")
            elif spec.blk == "calc":
                obs = rec.calc_blk_bases()
                if not obs or obs != {wblk}:
                    fails.append(f"[{tag}] 格挡基础值: wiki {wblk} / 实现 {sorted(obs) or '无'}")
            else:
                obs = _observed(spec.blk, rec, bc)
                if obs != {wblk}:
                    fails.append(f"[{tag}] 格挡{spec.blk[1]}: wiki {wblk} / 实现 {sorted(obs)}")
        elif not played_other:
            if spec.blk == "calc" and rec.calc_blk_bases():
                fails.append(f"[{tag}] wiki 无 block / 实现有格挡基础值 {sorted(rec.calc_blk_bases())}")

        # ---- magic ----
        if wmag is not None and spec.magic_skip:
            notes.append(f"{tag} magic={wmag} 条件性跳过")
        elif wmag is not None:
            if not spec.magic:
                fails.append(f"[{tag}] wiki magic={wmag} / 探针无提取器（补 SPECS）")
            for label, ext in spec.magic:
                obs = ext(rec.ev, bc, pre)
                if obs != {wmag}:
                    fails.append(f"[{tag}] {label}: wiki {wmag} / 实现 {sorted(obs) or '无'}")

        # ---- 段数 ----
        if spec.hits is not None and spec.dmg == "calc" and wdmg is not None:
            expected = spec.hits[1 if upgraded else 0]
            got = rec.attack_hits(pre["alive"])
            if got != expected:
                fails.append(f"[{tag}] 攻击段数: 期望 {expected} / 实现 {got}")

    if not any([wiki["damage"], wiki["block"], wiki["magic_number"]]):
        return "SKIP", [], ["wiki 无数值字段"]  # 不会发生（入参已过滤）
    return ("FAIL" if fails else "PASS"), fails, [n for n in notes if n]


# ---------------------------------------------------------------------------
# 主流程
# ---------------------------------------------------------------------------


def module_cards() -> list[tuple[CardDef, str]]:
    out = []
    for mod, label in ((IC, "Ironclad"), (CL, "Colorless"), (CU, "Curse")):
        seen = set()
        for x in mod.__dict__.values():
            if isinstance(x, CardDef) and x.name not in seen:
                seen.add(x.name)
                out.append((x, label))
    return out


def main() -> None:
    with open(ROOT / "wiki_data" / "cards.json") as f:
        wiki = {c["name"]: c for c in json.load(f)["cards"]}

    print("=" * 68)
    print("数值级对照：铁甲战士 + 无色 + 诅咒（行为探针 vs wiki_data/cards.json）")
    print("=" * 68)

    counts = {"PASS": 0, "FAIL": 0, "SKIP": 0}
    no_numbers: list[str] = []
    dynamic: list[str] = []

    # 无 wiki 数值字段、且值依赖局面的卡（行为探针无固定基础值可对照）
    STATIC_DYNAMIC = {
        "Body Slam": "伤害 = 当前格挡",
        "Mind Blast": "伤害 = 抽牌堆张数",
        "Regret": "失去 HP = 手牌数",
    }

    for card_def, cls_label in module_cards():
        w = wiki.get(card_def.name)
        if w is None:
            print(f"[{cls_label}] {card_def.name}: wiki_data 缺页（结构层脚本已报）")
            continue
        has_numbers = any(w.get(k) is not None
                          for k in ("damage", "block", "magic_number"))
        if not has_numbers:
            label = f"{card_def.name}（{cls_label}）"
            if card_def.name in STATIC_DYNAMIC:
                dynamic.append(f"{label}: {STATIC_DYNAMIC[card_def.name]}（无数值字段）")
            no_numbers.append(label)
            continue
        verdict, fails, notes = check_card(card_def, w)
        counts[verdict] += 1
        mark = {"PASS": "✓", "FAIL": "✗", "SKIP": "⊘"}[verdict]
        line = f"[{cls_label}] {mark} {card_def.name}"
        if verdict == "SKIP":
            dynamic.append(f"{card_def.name}（{cls_label}）: {notes[0] if notes else ''}")
        elif spec_d := SPECS.get(card_def.name):
            if spec_d.dmg == "skip" or spec_d.magic_skip:
                why = spec_d.note or "动态值"
                dynamic.append(f"{card_def.name}（{cls_label}）: {why}")
        if fails or (verdict == "SKIP") or notes:
            suffix = ""
            if w.get("damage") is not None:
                suffix += f" dmg {w['damage']}/{w['damage_upgraded']}"
            if w.get("block") is not None:
                suffix += f" blk {w['block']}/{w['block_upgraded']}"
            if w.get("magic_number") is not None:
                suffix += f" magic {w['magic_number']}/{w['magic_number_upgraded']}"
            print(f"{line:<58}{suffix}")
        else:
            print(line)
        for n in notes:
            print(f"    · {n}")
        for d in fails:
            print(f"    ✗ {d}")

    print("\n" + "=" * 68)
    print(f"PASS {counts['PASS']} / FAIL {counts['FAIL']} / 整卡跳过 {counts['SKIP']}"
          f"（字段级动态排除见下清单）")
    if dynamic:
        print("\n动态排除清单（行为依赖局面，人工审计口径）：")
        for d in dynamic:
            print(f"  - {d}")
    if no_numbers:
        print(f"\nwiki 无数值字段、不在对照范围：{len(no_numbers)} 张")
        print("  " + "、".join(no_numbers))
    print("\n" + ("数值层全对齐。" if counts["FAIL"] == 0
                  else f"存在 {counts['FAIL']} 张 FAIL，逐个查证修正。"))


if __name__ == "__main__":
    main()

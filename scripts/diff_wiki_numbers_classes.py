"""数值级自动对照（scripts/diff_wiki_numbers_classes.py）：静默/故障/观者
三职业卡牌的伤害/格挡基础值 vs wiki_data/cards.json。

与 diff_wiki.py（结构层）和 diff_wiki_numbers.py（铁甲侧，另一会话维护）
互补，本脚本覆盖 silent.py / defect.py / watcher.py 三模块。

方法论（DESIGN.md 口径）：
- wiki 的 damage/block 是**基础值**（不含力量/虚弱/易伤/FOCUS 管线）；实现
  卡牌 play 调 bc.calculate_card_damage(item, target, BASE)，BASE 即基础值。
- 干净战斗（jaw_worm 单怪、无 buff）下打出卡（基础/升级各一次），净效果
  反推基础值：怪 HP 差 = 伤害，block 差 = 格挡。多段卡按段数折算。
- X 费卡固定能量（energy=2）测试；球相关卡引导后看 bc.player.orbs，
  唤起类（Dualcast/Multi-Cast 等）FOCUS=0 时每球基础伤 3 直接对照。
- 动态/条件卡（状态依赖，净效果推不出基础值）按清单排除打印"动态跳过"
  ——这些已人工审计过（含任务清单指定的 All for One/Claw/Genetic
  Algorithm/Blizzard/Flying Knee）。
- 触发型数值（Caltrops 反伤/After Image 每牌格挡/Omega 回合末等）只跳过
  对应字段，不误报 FAIL。

用法：uv run python scripts/diff_wiki_numbers_classes.py [--verbose]
输出：控制台报告（PASS/FAIL/SKIP/无字段），FAIL 时退出码 1。
"""

from __future__ import annotations

import json
import sys
from dataclasses import dataclass, field
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from sts.combat.battle import BattleContext  # noqa: E402
from sts.combat.types import InputState, Orb, Outcome  # noqa: E402
from sts.content.cards import CardDef  # noqa: E402
import sts.content.cards.silent as m_silent  # noqa: E402
import sts.content.cards.defect as m_defect  # noqa: E402
import sts.content.cards.watcher as m_watcher  # noqa: E402

SEED = 20261007
MONSTER_HP = 9999  # 防击杀（Grand Finale 60/Ragnarok 36 等均远小于）
DEFAULT_ENERGY = 9  # 非 X 费卡：足量能量（Meteor Strike 5 费亦可）
X_ENERGY = 2  # X 费卡：固定 2 能量

MODULES = [
    ("Silent", m_silent, "DEFEND_S"),
    ("Defect", m_defect, "DEFEND_D"),
    ("Watcher", m_watcher, "DEFEND_W"),
]


def load_wiki() -> dict[tuple[str, str], dict]:
    with open(ROOT / "wiki_data" / "cards.json") as f:
        cards = json.load(f)["cards"]
    return {(c["name"], c["class"]): c for c in cards if c.get("name") and c.get("class")}


# ============================================================
# 逐卡测试规格
# ============================================================
# 字段（标量或 (基础, 升级) 元组）：
#   hits        伤害段数（净伤 ÷ 段数 = 每段基础值）
#   energy      打出前设定的能量（默认 9；X 费卡设 2）
#   preset_orbs 打出前预置的球（唤起/倍率类需要；绕过 channel 直接入槽）
#   orbs_after  打出后期望的球序列（精确列表）
#   orb_count   打出后期望的球数（类型不定，Chaos 随机球）
#   evoke_count 唤起次数（FOCUS=0 → 引擎自洽净伤 = 次数×3，非 wiki 对照）
#   misc_data   实例 misc_data 预置（Expunger 段数由 Conjure Blade 写入）
#   empty_draw  清空抽牌堆（Grand Finale 打出条件）
#   draw_skill  抽牌堆顶垫 1 张技能牌（Escape Plan 的条件分支取真）
#   hand_fillers额外垫手牌数（Spirit Shield 按手牌数给格挡）
#   block_mult  格挡乘数（Spirit Shield：每张手牌一份）
#   hp_loss     以 HP 直损结算（Pressure Points：对照 wiki magic_number）

SPECS: dict[str, dict] = {
    # ---- Silent ----
    "Dagger Spray": {"hits": 2},
    "Eviscerate": {"hits": 3},
    "Glass Knife": {"hits": 2},
    "Riddle with Holes": {"hits": 5},
    "Skewer": {"hits": 2, "energy": X_ENERGY},
    "Grand Finale": {"empty_draw": True},
    "Escape Plan": {"draw_skill": True},
    # ---- Defect ----
    "Reinforced Body": {"energy": X_ENERGY, "block_mult": 2},
    "Rip and Tear": {"hits": 2},
    "Zap": {"orbs_after": [Orb.LIGHTNING]},
    # Dualcast/Multi-Cast 唤起 = 连弹最老球：预置 N 球才有 N 次唤起
    #（单球 Dualcast 只唤起一次，对齐本体 EvokeOrb 逐次弹最老位）
    "Dualcast": {"preset_orbs": [Orb.LIGHTNING] * 2, "orbs_after": [], "evoke_count": 2},
    "Ball Lightning": {"orbs_after": [Orb.LIGHTNING]},
    "Barrage": {"preset_orbs": [Orb.LIGHTNING],
                "orbs_after": [Orb.LIGHTNING]},
    "Cold Snap": {"orbs_after": [Orb.FROST]},
    "Coolheaded": {"orbs_after": [Orb.FROST]},
    "Chill": {"orbs_after": [Orb.FROST]},
    "Darkness": {"orbs_after": [Orb.DARK]},
    "Fusion": {"orbs_after": [Orb.PLASMA]},
    "Glacier": {"orbs_after": [Orb.FROST, Orb.FROST]},
    "Doom and Gloom": {"orbs_after": [Orb.DARK]},
    "Rainbow": {"orbs_after": [Orb.LIGHTNING, Orb.FROST, Orb.DARK]},
    "Electrodynamics": {"orbs_after": ([Orb.LIGHTNING] * 2, [Orb.LIGHTNING] * 3)},
    "Tempest": {"energy": X_ENERGY,
                "orbs_after": ([Orb.LIGHTNING] * 2, [Orb.LIGHTNING] * 3)},
    "Meteor Strike": {"orbs_after": [Orb.PLASMA] * 3},
    "Chaos": {"orb_count": (1, 2)},
    "Multi-Cast": {"energy": X_ENERGY,
                   "preset_orbs": ([Orb.LIGHTNING] * 2, [Orb.LIGHTNING] * 3),
                   "orbs_after": [], "evoke_count": (2, 3)},
    "Recursion": {"preset_orbs": [Orb.LIGHTNING],
                  "orbs_after": [Orb.LIGHTNING], "evoke_count": 1},
    "Fission": {"preset_orbs": [Orb.LIGHTNING, Orb.LIGHTNING],
                "orbs_after": [], "evoke_count": (0, 2)},
    # ---- Watcher ----
    "Flying Sleeves": {"hits": 2},
    "Tantrum": {"hits": (3, 4)},
    "Ragnarok": {"hits": (5, 6)},
    "Expunger": {"hits": 2, "misc_data": 2},
    "Spirit Shield": {"hand_fillers": 2, "block_mult": 2},
    "Pressure Points": {"hp_loss": True},
}

# 动态/条件卡：净效果依赖战斗状态，无法反推基础值（已人工审计）
DYNAMIC_SKIP: dict[str, str] = {
    # Silent
    "Finisher": "伤害 = 本回合打出的攻击牌数",
    "Flechettes": "伤害 = 手中技能牌数",
    "Flying Knee": "条件能量（任务清单指定排除，伤害已人工审计）",
    # Defect
    "Claw": "全场爪击叠加计数",
    "Genetic Algorithm": "永久格挡成长",
    "Stack": "格挡 = 弃牌堆卡数",
    "Blizzard": "伤害 = 本场引导冰球数",
    "Thunder Strike": "段数 = 本场引导闪电球数",
    "All for One": "弃牌堆 0 费回收（任务清单指定排除，伤害已人工审计）",
    # Watcher
    "Judgment": "阈值直杀（HP≤30/40 置 0，非数值伤害）",
    "Omniscience": "重放抽牌堆他牌两次",
}

# 触发型数值：wiki 字段有值但不是"打出即得"，只跳过对应字段
TRIGGER_SKIP: dict[str, dict[str, str]] = {
    # Silent
    "A Thousand Cuts": {"dmg": "触发型（每打出一张牌全体 1/2 伤）"},
    "Caltrops": {"dmg": "触发型（受击反弹 3/5）"},
    "After Image": {"blk": "触发型（每打出一张牌得 1 格挡）"},
    # Watcher
    "Omega": {"dmg": "触发型（回合末全体 50/60）"},
    "Like Water": {"blk": "触发型（平静回合末 5/7）"},
    "Mental Fortress": {"blk": "触发型（每切姿态 4/6）"},
    "Nirvana": {"blk": "触发型（每次检视 3/4）"},
    "Talk to the Hand": {"blk": "触发型（每次攻击该敌 2/3）"},
}


def variant(x, upgraded: bool):
    """标量恒等；(基础, 升级) 元组按升级位取侧。"""
    if isinstance(x, tuple):
        return x[1] if upgraded else x[0]
    return x


@dataclass
class Result:
    name: str
    lines: list = field(default_factory=list)
    ok: bool = True
    played: bool = False


def drain_pending_input(bc: BattleContext) -> None:
    """清空挂起的交互（CARD_SELECT 最少选择 / SCRY 全弃），把队列结算到底。"""
    for _ in range(50):
        st = bc.input_state
        if st == InputState.CARD_SELECT and bc.card_select_info is not None:
            info = bc.card_select_info
            if info.can_pick_zero:
                bc.choose_cards([])
            else:
                k = min(info.pick_count, len(info.candidates))
                bc.choose_cards(list(range(k)))
        elif st == InputState.SCRY:
            bc.choose_scry(0)
        else:
            break


def measure(mod, filler_defend: CardDef, carddef: CardDef, upgraded: bool,
            spec: dict) -> tuple[int, int, BattleContext]:
    """干净战斗打出一张卡，返回 (净伤害, 净格挡, bc)。"""
    bc = BattleContext(seed=SEED, encounter="jaw_worm")
    m = bc.monsters.monsters[0]
    m.hp = MONSTER_HP  # 防击杀（不触 die/战局判定，纯数值观察）
    # 手牌清空后只塞被测卡（升级/未升级各测）
    bc.cards.hand.clear()
    inst = bc.cards.instantiate(carddef)
    if upgraded:
        inst.upgraded = True
    if "misc_data" in spec:
        inst.misc_data = variant(spec["misc_data"], upgraded)
    bc.cards.hand.append(inst)
    # 环境预置
    for orb in variant(spec.get("preset_orbs", []), upgraded):
        bc.player.orbs.append(orb)
    if spec.get("empty_draw"):
        bc.cards.draw_pile.clear()
    if spec.get("draw_skill"):
        bc.cards.draw_pile.clear()
        bc.cards.draw_pile.append(bc.cards.instantiate(filler_defend))
    for _ in range(variant(spec.get("hand_fillers", 0), upgraded)):
        bc.cards.hand.append(bc.cards.instantiate(carddef))
    bc.player.energy = variant(spec.get("energy", DEFAULT_ENERGY), upgraded)
    hp0, blk0 = m.hp, bc.player.block
    bc.play_card(0, 0)
    drain_pending_input(bc)
    return hp0 - m.hp, bc.player.block - blk0, bc


def check_card(mod, filler_defend: CardDef, carddef: CardDef, wiki: dict,
               verbose: bool) -> Result:
    name = carddef.name
    res = Result(name)

    if name in DYNAMIC_SKIP:
        res.lines.append(f"[SKIP] {name}：动态卡（{DYNAMIC_SKIP[name]}）")
        return res
    # 同名跨职业卡（Strike/Defend）按 (name, class) 精确取 wiki 页
    w = wiki.get((name, mod_wiki_class[mod.__name__]))
    if w is None:
        res.ok = False
        res.lines.append(f"[FAIL] {name}：wiki_data 缺页（class="
                         f"{mod_wiki_class[mod.__name__]}）")
        return res

    spec = SPECS.get(name, {})
    trig = TRIGGER_SKIP.get(name, {})
    wdmg = (w.get("damage"), w.get("damage_upgraded"))
    wblk = (w.get("block"), w.get("block_upgraded"))
    hp_loss = bool(spec.get("hp_loss"))
    has_dmg = wdmg != (None, None) and "dmg" not in trig and not hp_loss
    has_blk = wblk != (None, None) and "blk" not in trig
    has_orb = any(k in spec for k in ("orbs_after", "orb_count", "evoke_count"))
    if not (has_dmg or has_blk or has_orb or hp_loss):
        res.lines.append(f"[ — ] {name}：无直接伤害/格挡字段（{'/'.join(trig.values()) if trig else '纯生成/状态/抽弃类'}）")
        return res

    for upgraded in (False, True):
        dmg, blk, bc = measure(mod, filler_defend, carddef, upgraded, spec)
        if bc.outcome != Outcome.UNDECIDED:
            res.ok = False
            res.lines.append(f"[FAIL] {name}{'+' if upgraded else ''}：战斗异常结束"
                             f"（outcome={bc.outcome}）")
            continue
        tag = name + ("+" if upgraded else "")
        # ---- 伤害 ----
        if has_dmg:
            expect = wdmg[1] if upgraded else wdmg[0]
            hits = variant(spec.get("hits", 1), upgraded)
            if dmg % hits:
                res.ok = False
                res.lines.append(f"[FAIL] {tag}：净伤 {dmg} 不能被段数 {hits} 整除")
            else:
                per = dmg // hits
                if per != expect:
                    res.ok = False
                    res.lines.append(f"[FAIL] {tag}：wiki 伤 {expect} / 实测 {per}"
                                     f"（净伤 {dmg} ÷ {hits} 段）")
                else:
                    res.played = True
                    res.lines.append(f"[PASS] {tag} 伤 {per}（÷{hits} 段）")
        elif hp_loss:
            # HP 直损类（Pressure Points）：wiki magic_number = 直损值
            expect = (w.get("magic_number_upgraded") if upgraded
                      else w.get("magic_number"))
            if dmg != expect:
                res.ok = False
                res.lines.append(f"[FAIL] {tag}：wiki HP 直损 {expect} / 实测 {dmg}")
            else:
                res.lines.append(f"[PASS] {tag} HP 直损 {dmg}")
        # ---- 格挡 ----
        if has_blk:
            expect = (wblk[1] if upgraded else wblk[0]) * variant(
                spec.get("block_mult", 1), upgraded)
            if blk != expect:
                res.ok = False
                res.lines.append(f"[FAIL] {tag}：wiki 格 {expect} / 实测 {blk}")
            else:
                res.lines.append(f"[PASS] {tag} 格 {blk}")
        # ---- 球位 ----
        if "orbs_after" in spec:
            expect = variant(spec["orbs_after"], upgraded)
            if list(bc.player.orbs) != list(expect):
                res.ok = False
                res.lines.append(f"[FAIL] {tag}：wiki 语义球序 {[o.name for o in expect]}"
                                 f" / 实测 {[o.name for o in bc.player.orbs]}")
            else:
                res.lines.append(f"[PASS] {tag} 球 {[o.name for o in expect]}")
        if "orb_count" in spec:
            expect = variant(spec["orb_count"], upgraded)
            if len(bc.player.orbs) != expect:
                res.ok = False
                res.lines.append(f"[FAIL] {tag}：期望 {expect} 个随机球 / 实测 {len(bc.player.orbs)}")
            else:
                res.lines.append(f"[PASS] {tag} 随机球 × {expect}")
        if "evoke_count" in spec:
            # FOCUS=0 时闪电球唤起基础伤 3：引擎自洽对照（非 wiki 字段）
            n = variant(spec["evoke_count"], upgraded)
            if dmg != 3 * n:
                res.ok = False
                res.lines.append(f"[FAIL] {tag}：唤起 {n} 次期望净伤 {3 * n}"
                                 f"（3+FOCUS0）/ 实测 {dmg}")
            else:
                res.lines.append(f"[PASS] {tag} 唤起伤 {dmg}（{n}×3）")
    return res


mod_wiki_class = {
    "sts.content.cards.silent": "Silent",
    "sts.content.cards.defect": "Defect",
    "sts.content.cards.watcher": "Watcher",
}


def main() -> None:
    verbose = "--verbose" in sys.argv
    wiki = load_wiki()
    total = pass_n = fail_n = skip_n = nofield_n = 0
    failures: list[str] = []

    for cls_name, mod, defend_var in MODULES:
        filler = getattr(mod, defend_var)  # 本职业 Defend（垫牌/技能判定用）
        print("=" * 72)
        print(f"{cls_name}（{len(mod.__all__)} 卡）")
        print("=" * 72)
        for var_name in mod.__all__:
            carddef = getattr(mod, var_name)
            assert isinstance(carddef, CardDef)
            total += 1
            res = check_card(mod, filler, carddef, wiki, verbose)
            for line in res.lines:
                if line.startswith("[FAIL]"):
                    failures.append(f"{cls_name}: {line}")
                if verbose or not line.startswith("[PASS]"):
                    print("  " + line)
            if res.ok:
                if any(l.startswith("[SKIP]") for l in res.lines):
                    skip_n += 1
                elif any(l.startswith("[ — ]") for l in res.lines):
                    nofield_n += 1
                elif res.lines:
                    pass_n += 1
            else:
                fail_n += 1

    print()
    print("=" * 72)
    print(f"合计 {total} 卡：PASS {pass_n} / FAIL {fail_n} / 动态跳过 {skip_n} "
          f"/ 无直接数值 {nofield_n} / 未计入 {total - pass_n - fail_n - skip_n - nofield_n}")
    if failures:
        print(f"\n{len(failures)} 处 FAIL：")
        for f in failures:
            print("  " + f)
        sys.exit(1)
    print("全部对照一致。")


if __name__ == "__main__":
    main()

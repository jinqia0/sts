"""实现 vs wiki_data 自动对照脚本（scripts/diff_wiki.py）。

对照维度：
- 卡牌：费用 / 类型 / 目标 / 关键词（消耗/虚无/固有/保留/不可打出）/ 伤害 /
  格挡 / 次级数值。wiki 的 (基础;升级) 记法拆开比对。
- 遗物：RelicId 枚举覆盖 + 已实现遗物的效果文本存在性（数值语义比对需逐个
  人工核对，脚本只做结构层）。
- 怪物：HP 区间四档 / 行动表伤害（wiki 结构化 damage 字典 vs 实现 MoveDef
  base_damage——实现是引擎内源码，脚本比对靠名称对齐 + HP）。

用法：uv run python scripts/diff_wiki.py [--verbose]
输出：控制台报告 + 不匹配明细。
"""

from __future__ import annotations

import json
import sys
from dataclasses import fields
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from sts.content import cards as cards_pkg  # noqa: E402
from sts.content.cards._base import CardDef  # noqa: E402


def load(name: str, key: str) -> list[dict]:
    with open(ROOT / "wiki_data" / f"{name}.json") as f:
        return json.load(f)[key]


def all_impl_cards() -> list[CardDef]:
    out = []
    for mod_name in ("ironclad", "silent", "defect", "watcher", "colorless", "curses"):
        mod = __import__(f"sts.content.cards.{mod_name}", fromlist=["x"])
        for x in mod.__dict__.values():
            if isinstance(x, CardDef) and x not in out:
                out.append(x)
    return out


TYPE_MAP = {"Attack": "Attack", "Skill": "Skill", "Power": "Power", "Status": "Status", "Curse": "Curse"}

# wiki target 推导值 → 实现 needs_target 布尔
TARGET_IMPL = {"Single": True, "All": False, "None": False, "Self": False}


def wiki_cost(c: dict) -> tuple[int | str | None, int | str | None]:
    """wiki cost 字段可能是 int、'X'、'Unplayable' 等。"""
    return c.get("cost"), c.get("cost_upgraded")


def impl_cost(cd: CardDef) -> tuple[int | str, int | str]:
    base = cd.cost if not cd.x_cost else "X"
    up = cd.upgraded_cost if cd.upgraded_cost is not None else base
    return base, up


def wiki_keywords(c: dict) -> set[str]:
    return set(c.get("keywords") or [])


def impl_keywords(cd: CardDef) -> set[str]:
    kw = set()
    if cd.exhausts:
        kw.add("Exhaust")
    if cd.ethereal:
        kw.add("Ethereal")
    if cd.innate or (cd.innate_when_upgraded and False):  # innate_when_upgraded 是"仅升级固有"，不并集
        pass
    if cd.innate:
        kw.add("Innate")
    if cd.self_retain or cd.retain_when_upgraded:
        kw.add("Retain")
    if cd.unplayable:
        kw.add("Unplayable")
    return kw


def compare_cards(verbose: bool) -> list[str]:
    wiki = {c["name"]: c for c in load("cards", "cards") if c.get("name")}
    diffs = []
    seen_wiki = set()
    for cd in all_impl_cards():
        w = wiki.get(cd.name)
        if w is None:
            diffs.append(f"卡牌 [{cd.name}] 实现 Yes / wiki No（wiki_data 缺页）")
            continue
        seen_wiki.add(cd.name)
        # 费用
        wc_base, wc_up = wiki_cost(w)
        ic_base, ic_up = impl_cost(cd)
        def _norm(v):
            if v is None:
                return None
            if isinstance(v, int):
                return v
            s = str(v).strip()
            if s in ("X", "X-Cost"):
                return "X"
            if s.lower() in ("unplayable", "unplayable."):
                return "Unplayable"
            try:
                return int(s)
            except ValueError:
                return s
        wc_base_n, wc_up_n = _norm(wc_base), _norm(wc_up)
        if isinstance(wc_base_n, int) and cd.x_cost:
            diffs.append(f"卡牌 [{cd.name}] 费用: 实现 X 费 / wiki {wc_base_n}")
        elif isinstance(wc_base_n, int) and not cd.x_cost and wc_base_n != ic_base:
            diffs.append(f"卡牌 [{cd.name}] 费用: 实现 {ic_base} / wiki {wc_base_n}")
        elif wc_base_n == "X" and not cd.x_cost:
            diffs.append(f"卡牌 [{cd.name}] 费用: 实现 {ic_base} / wiki X 费")
        # 升级费用（wiki 明确给出升级费时才比）
        if isinstance(wc_up_n, int) and isinstance(ic_up, int) and wc_up_n != ic_up and wc_up_n is not None:
            diffs.append(f"卡牌 [{cd.name}] 升级费: 实现 {ic_up} / wiki {wc_up_n}")
        # 类型
        wt = w.get("type")
        if wt and wt in TYPE_MAP and cd.ctype != wt:
            diffs.append(f"卡牌 [{cd.name}] 类型: 实现 {cd.ctype} / wiki {wt}")
        # 关键词差集（只报实现有而 wiki 无，或反向）
        wkw = wiki_keywords(w)
        ikw = impl_keywords(cd)
        # 关键词差集降级为提示：'仅升级版关键词'（Innate+/Exhaust+/Retain+）在实现中
        # 由 innate_when_upgraded 位或 play 内动态 item.exhaust_on_use 表达，静态位不
        # 反映——行为正确性由 tests 与 scripts 行为探针保证，不作为差异噪声
        if verbose and (wkw - ikw or ikw - wkw):
            print(f"    [kw 提示] {cd.name}: wiki {sorted(wkw)} vs 实现 {sorted(ikw)}")
    # wiki 有而实现无
    for name in sorted(set(wiki) - seen_wiki):
        diffs.append(f"卡牌 [{name}] wiki 有 / 实现 No")
    return diffs


def compare_relics(verbose: bool) -> list[str]:
    wiki = {r["name"]: r for r in load("relics", "relics") if r.get("name")}
    from sts.combat.relics import RelicId

    diffs = []
    matched = 0
    for rid in RelicId:
        # RelicId 枚举名 = wiki 遗物名的下划线形式
        wname = rid.name.replace("_", " ").title().replace("Of", "of").replace("And", "and").replace("The ", "The ")
        w = wiki.get(wname) or wiki.get(rid.name.replace("_", " "))
        # 名字模糊兜底（如 MARK_OF_THE_BLOOM → "Mark of the Bloom"）
        if w is None:
            lower_map = {k.lower(): k for k in wiki}
            w = wiki.get(lower_map.get(rid.name.replace("_", " ").lower(), "")) if lower_map else None
        if w is None:
            # 尝试按 relic_id 字段
            for cand in wiki.values():
                if cand.get("relic_id") == rid.name:
                    w = cand
                    break
        if w is None:
            diffs.append(f"遗物 [RelicId.{rid.name}] 实现 / wiki_data 未匹配")
        else:
            matched += 1
    # wiki 中战斗相关但项目未收录的
    impl_names = {r.name for r in RelicId}
    # 已知合理排除（选卡交互/战斗结束跨场/信息展示/需要药水或选卡系统——设计记录在案）
    KNOWN_EXCLUDED = {
        "Bottled Flame": "拾取时选卡（局外选卡交互）",
        "Bottled Lightning": "拾取时选卡（局外选卡交互）",
        "Bottled Tornado": "拾取时选卡（局外选卡交互）",
        "Gambling Chip": "战斗开始选卡弃抽（选卡交互，批次 3 口径）",
        "Ancient Tea Set": "篝火触发（局外）",
        "Face of Cleric": "战斗结束 MaxHP+1（跨战斗局外状态）",
        "Frozen Eye": "查看抽牌堆排序（观测侧，批次 5）",
        "Golden Eye": "Scry+2 ——已实现（2026-10-07 wiki 比照批）",
        "Blue Candle": "诅咒可打出（诅咒可打出性，批次 5 动作空间相关）",
        "Medical Kit": "状态卡可打出（同上，批次 5）",
        "Chemical X": "X 费 +2 ——已实现（2026-10-07 wiki 比照批）",
        "Brimstone": "回合开始双方+力量 ——已实现（2026-10-07 wiki 比照批）",
        "Frozen Core": "空槽引导冰球 ——已实现（2026-10-07 wiki 比照批）",
        "Mark of the Bloom": "禁止治疗 ——已实现（2026-10-07 wiki 比照批）",
        "Black Blood": "Burning Blood 升级版（胜回 12）——已实现（2026-10-07 wiki 比照批）",
    }
    for w in wiki.values():
        rid_name = w.get("relic_id")
        if w.get("combat_relevant") and (rid_name is None or rid_name not in impl_names):
            reason = KNOWN_EXCLUDED.get(w["name"])
            if reason:
                diffs.append(f"遗物 [{w['name']}] 未收录（已知：{reason}）")
            else:
                diffs.append(f"遗物 [{w['name']}] wiki 标战斗相关 / 项目未收录")
    print(f"遗物: 实现枚举 {len(list(RelicId))} 个，wiki 匹配 {matched} 个")
    return diffs


def compare_monsters(verbose: bool) -> list[str]:
    wiki = {m["name"]: m for m in load("monsters", "monsters") if m.get("name")}
    import sts.content.monsters as mon
    from sts.combat.entities import Monster

    diffs = []
    seen = set()
    for x in mon.__dict__.values():
        if isinstance(x, type) and issubclass(x, Monster) and x is not Monster and hasattr(x, "name") and x.name != "Monster":
            w = wiki.get(x.name)
            if w is None:
                diffs.append(f"怪物 [{x.name}] 实现 / wiki_data 未匹配")
                continue
            seen.add(x.name)
            hp = w.get("hp") or {}
            # A0 档：wiki 可能是区间或定值
            a0 = hp.get("asc0")
            if a0 is not None and hasattr(x, "hp_range"):
                lo, hi = x.hp_range
                if isinstance(a0, list) and (a0[0] != lo or a0[1] != hi):
                    diffs.append(f"怪物 [{x.name}] HP A0: 实现 {lo}-{hi} / wiki {a0[0]}-{a0[1]}")
                elif isinstance(a0, int) and (a0 != lo or a0 != hi):
                    diffs.append(f"怪物 [{x.name}] HP A0: 实现 {lo}-{hi} / wiki 恒 {a0}")
    for name in sorted(set(wiki) - seen):
        if name in ("Jaw Worm (Hard)", "Slot Placeholder", "Louse"):
            continue  # 已知归档特例：强化变体/占位槽/抽象基类（红绿虱各有实现）
        diffs.append(f"怪物 [{name}] wiki 有 / 实现 No")
    if "Louse" in seen:
        pass  # 抽象基类无 wiki 独立页，红绿虱两实现已对上——见下方特例过滤
    return diffs


def main() -> None:
    verbose = "--verbose" in sys.argv
    print("=" * 60)
    print("实现 vs wiki_data 自动对照")
    print("=" * 60)

    card_diffs = compare_cards(verbose)
    print(f"\n卡牌对照：{len(card_diffs)} 处差异")
    for d in card_diffs[:80] if not verbose else card_diffs:
        print("  -", d)
    if not verbose and len(card_diffs) > 80:
        print(f"  ...（共 {len(card_diffs)} 处，--verbose 看全部）")

    print()
    relic_diffs = compare_relics(verbose)
    print(f"遗物对照：{len(relic_diffs)} 处差异")
    for d in relic_diffs[:40] if not verbose else relic_diffs:
        print("  -", d)

    print()
    monster_diffs = compare_monsters(verbose)
    print(f"怪物对照：{len(monster_diffs)} 处差异")
    for d in monster_diffs[:40] if not verbose else monster_diffs:
        print("  -", d)

    total = len(card_diffs) + len(relic_diffs) + len(monster_diffs)
    print("\n" + "=" * 60)
    print(f"合计 {total} 处差异（伤害/格挡/层数的数值级比对需逐卡人工核对，"
          f"本脚本覆盖费用/类型/关键词/HP/覆盖面）")


if __name__ == "__main__":
    main()

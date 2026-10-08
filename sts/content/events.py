"""Act 1 事件定义（Phase 3a，2026-10-08）。

框架：EventDef（frozen dataclass + 选项回调，照 CardDef 模式）+ EventContext
（事件效果可用的局外服务）。事件规格逐条对照本体反编译源码
（sts_game_data/decompiled/com/megacrit/cardcrawl/events/，V2.3.4），
中文名取 zhs/events.json。

池构成（Exordium.java:221-243 + AbstractDungeon.java:1320-1338）：
- eventList 11：Big Fish / The Cleric / Dead Adventurer / Golden Idol /
  Golden Wing / World of Goop / Liars Game / Living Wall / Mushrooms /
  Scrap Ooze / Shining Light
- shrineList 6：Match and Keep! / Golden Shrine / Transmorgrifier /
  Purifier / Upgrade Shrine / Wheel of Change
- one-time 7（NoteForYourself 跳过——跨 run 持久状态 playerPref，模拟器
  无对应物，已知省略）：Accursed Blacksmith / Bonfire Elementals /
  FaceTrader / Fountain of Cleansing / Lab / WeMeetAgain / The Woman in Blue

事件内部随机走 misc 流（对齐本体 miscRng 语义，分布级）。
含战斗事件产出 PendingCombat（run 循环直连 BattleContext）。
A15 数值差异不实现（A0 范围），注释标明出处。
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass

from sts.combat.relics import RelicId
from sts.content.cards import CardDef
from sts.content.potions import PotionDef
from sts.overworld.card_pools import COLORLESS_POOLS, CURSE_POOL, OWN_POOLS
from sts.overworld.relic_effects import PendingRelicChoice
from sts.overworld.relic_pools import RelicPools, roll_tier
from sts.overworld.rng import OverworldRngStreams
from sts.overworld.state import RunState


# ---- 效果返回结构 ----


@dataclass(frozen=True)
class PendingCombat:
    """事件触发的战斗（run 循环接 BattleContext，胜后按 reopen 回到事件或收尾）。"""

    encounter: str  # encounters.py 注册名
    elite: bool = False
    gold: tuple[int, int] | None = None  # 战斗金币范围（None = 按房类型默认）
    reward_relic: RelicId | None = None  # 固定遗物奖励（Mushrooms 的 Odd Mushroom）


@dataclass(frozen=True)
class CardChoice:
    """事件挂起的选牌任务（policy 决策后由 run 循环执行）。

    kind：
      remove / transform / upgrade / duplicate —— 对卡组选 n 张
      bonfire_sacrifice —— 篝火精灵献祭（奖励随牌稀有度，run 循环特判）
      gain_colorless —— 从 3 张随机无色牌选 1 加入（DreamCatcher 路径）
    """

    kind: str
    n: int = 1


@dataclass(frozen=True)
class EventOutcome:
    log: str = ""
    reopen: bool = False  # 重开同一事件（Dead Adventurer / Scrap Ooze 搜索循环、金神像陷阱）
    pending_combat: PendingCombat | None = None
    card_choice: CardChoice | None = None


@dataclass(frozen=True)
class EventOption:
    label: str
    effect: Callable[[RunState, OverworldRngStreams, "EventContext"], EventOutcome]
    available: Callable[[RunState], bool] | None = None  # None = 恒可选


@dataclass(frozen=True)
class EventDef:
    eid: str  # 本体事件 ID（zhs/events.json 键）
    zh: str
    options: tuple[EventOption, ...]
    category: str = "event"  # event | shrine | onetime
    # 入池过滤（AbstractDungeon.getEvent/getShrine 的按名条件）
    pool_available: Callable[[RunState], bool] | None = None
    # 动态选项（金神像陷阱相）：None = 用 options
    options_fn: Callable[[RunState], tuple[EventOption, ...]] | None = None


class EventContext:
    """事件效果可用的局外服务（run 循环构造）。

    选择型后果（选牌/拾取选择）不入 EventOutcome 而进 pending 队列，
    由 run 循环在事件结束后统一交给策略——与 PendingRelicChoice 同构。
    """

    def __init__(self, state: RunState, rngs: OverworldRngStreams, pools: RelicPools):
        self.state = state
        self.rngs = rngs
        self.pools = pools
        self.pending_cards: list[CardChoice] = []
        self.pending_relic_choices: list[PendingRelicChoice] = []
        self.gained_relics: list[RelicId] = []

    # ---- 遗物 ----

    def gain_random_relic(self) -> RelicId:
        """随机非屏幕遗物（tier roll 50/33/17 + 头取 + 拾取效果）。"""
        relic = self.pools.take_drop(roll_tier(self.rngs.relic), self.state)
        self._obtain(relic)
        return relic

    def gain_relic(self, relic: RelicId) -> RelicId:
        """固定遗物（GoldenIdol / 面具 / WarpedTongs 等事件专属）。"""
        self._obtain(relic)
        return relic

    def _obtain(self, relic: RelicId) -> None:
        from sts.overworld.relic_effects import apply_pickup

        if relic in (RelicId.CIRCLET, RelicId.RED_CIRCLET):
            # 兜底头环：可叠加、无拾取效果
            self.state.relics.append(relic)
        else:
            self.pending_relic_choices.extend(apply_pickup(self.state, relic, self.rngs))
        self.gained_relics.append(relic)

    # ---- 诅咒 / 卡牌 ----

    def gain_random_curse(self) -> CardDef:
        """随机可移除诅咒（returnRandomCurse：诅咒池均匀抽，misc 流）。"""
        curse = CURSE_POOL[self.rngs.misc.int_inclusive(0, len(CURSE_POOL) - 1)]
        self.state.add_card(curse)
        return curse

    def transform_deck_card(self, index: int) -> None:
        """变化卡组第 index 张（同稀有度随机替换；基础/其他 → common 池）。"""
        from sts.overworld.state import DeckCard

        pool = OWN_POOLS[_card_rarity(self.state.deck[index].card)]
        new_card = pool[self.rngs.misc.int_inclusive(0, len(pool) - 1)]
        self.state.deck[index] = DeckCard(new_card, False)

    def upgrade_random_cards(self, n: int, ctype: str | None = None) -> int:
        """随机升级 n 张（可按类型过滤），返回实际升级数。"""
        count = 0
        for _ in range(n):
            idxs = [
                i
                for i, dc in enumerate(self.state.deck)
                if not dc.upgraded and (ctype is None or getattr(dc.card, "ctype", "") == ctype)
            ]
            if not idxs:
                break
            self.state.upgrade_card(idxs[self.rngs.misc.int_inclusive(0, len(idxs) - 1)])
            count += 1
        return count

    # ---- 药水 ----

    def gain_random_potion(self) -> PotionDef | None:
        """随机药水 1 瓶（33 池均匀，misc 流；满槽返回 None，弃瓶由 run 循环处理）。"""
        from sts.content.potions import IRONCLAD_POTION_POOL

        pd = IRONCLAD_POTION_POOL[self.rngs.misc.int_inclusive(0, len(IRONCLAD_POTION_POOL) - 1)]
        return pd if self.state.obtain_potion(pd) is not None else None


def card_wiki_rarity(card: CardDef) -> str:
    """卡牌 wiki 稀有度（basic/curse/special 等原样返回；缺页返回 ""）。"""
    from sts.overworld.card_pools import _wiki_index

    w = _wiki_index().get(card.name)
    return (w.get("rarity") or "").lower() if w else ""


def _card_rarity(card: CardDef) -> str:
    """变化口径的稀有度（基础/诅咒/特殊 → common，PandorasBox/transform 语义）。"""
    rar = card_wiki_rarity(card)
    return rar if rar in ("common", "uncommon", "rare") else "common"


# ============================================================================
# Act 1 事件定义
# ============================================================================


def _out(log: str, **kw) -> EventOutcome:
    return EventOutcome(log=log, **kw)


# ---- eventList 11 个 ----


def _bigfish_banana(s: RunState, r: OverworldRngStreams, c: EventContext) -> EventOutcome:
    return _out(f"大鱼：香蕉，回复 {s.heal(s.max_hp // 3)} HP")


def _bigfish_donut(s: RunState, r: OverworldRngStreams, c: EventContext) -> EventOutcome:
    s.gain_max_hp(5)
    return _out("大鱼：甜甜圈，最大生命 +5")


def _bigfish_box(s: RunState, r: OverworldRngStreams, c: EventContext) -> EventOutcome:
    curse = c.gain_random_curse()
    relic = c.gain_random_relic()
    return _out(f"大鱼：盒子，{curse.zh} + 遗物 {relic.name}")


BIG_FISH = EventDef(
    eid="Big Fish",
    zh="大鱼",
    options=(
        EventOption("香蕉（回复 1/3 最大生命）", _bigfish_banana),
        EventOption("甜甜圈（最大生命 +5）", _bigfish_donut),
        EventOption("盒子（悔恨诅咒 + 随机遗物）", _bigfish_box),
    ),
)


def _cleric_heal(s: RunState, r: OverworldRngStreams, c: EventContext) -> EventOutcome:
    s.spend_gold(35)
    return _out(f"牧师：治疗，回复 {s.heal(s.max_hp // 4)} HP")


def _cleric_purify(s: RunState, r: OverworldRngStreams, c: EventContext) -> EventOutcome:
    s.spend_gold(50)
    return _out("牧师：净化", card_choice=CardChoice("remove", 1))


def _leave(log: str) -> EventOutcome:
    return _out(log)


THE_CLERIC = EventDef(
    eid="The Cleric",
    zh="牧师",
    pool_available=lambda s: s.gold >= 35,  # getEvent 过滤（java:1946）
    options=(
        EventOption("治疗（35 金回 25% 最大生命）", _cleric_heal, lambda s: s.gold >= 35),
        EventOption("净化（50 金移除 1 牌）", _cleric_purify, lambda s: s.gold >= 50),
        EventOption("离开", lambda s, r, c: _leave("牧师：离开")),
    ),
)

# 冒险者尸体：搜索遇敌三选一（miscRng，java:59,153-162）
_DEAD_ADVENTURER_ENEMIES = ("three_sentries", "gremlin_nob", "lagavulin")


def _dead_adventurer_search(s: RunState, r: OverworldRngStreams, c: EventContext) -> EventOutcome:
    scratch = s.event_scratch.setdefault("Dead Adventurer", {})
    fail = scratch.get("fail", 0)
    if r.misc.int_inclusive(0, 99) < 25 + 25 * fail:  # 首次 25%，每次失败 +25%（java:58,97,167）
        scratch["fail"] = fail + 1
        encounter = _DEAD_ADVENTURER_ENEMIES[r.misc.int_inclusive(0, 2)]
        return EventOutcome(
            log=f"冒险者尸体：搜索遇敌（{encounter}）",
            pending_combat=PendingCombat(encounter=encounter, elite=True, gold=(25, 35)),
            reopen=True,
        )
    # 成功：预设奖励序列 金币30 / 空 / 遗物，miscRng 洗牌（java:57,165-183）
    if "order" not in scratch:
        order = ["gold", "nothing", "relic"]
        r.misc.shuffle(order)
        scratch["order"] = order
        scratch["idx"] = 0
    idx = scratch["idx"]
    if idx >= len(scratch["order"]):
        return _out("冒险者尸体：已搜空")
    kind = scratch["order"][idx]
    scratch["idx"] = idx + 1
    if kind == "gold":
        s.add_gold(30)
        return _out("冒险者尸体：搜得 30 金", reopen=True)
    if kind == "relic":
        relic = c.gain_random_relic()
        return _out(f"冒险者尸体：搜得遗物 {relic.name}", reopen=True)
    return _out("冒险者尸体：什么都没有", reopen=True)


DEAD_ADVENTURER = EventDef(
    eid="Dead Adventurer",
    zh="冒险者尸体",
    pool_available=lambda s: s.floor > 6,  # floorNum > 6（java:1931）
    options=(
        EventOption("搜索（25% 遇精英，成功得奖励，可反复）", _dead_adventurer_search),
        EventOption("离开", lambda s, r, c: _leave("冒险者尸体：离开")),
    ),
)


def _golden_idol_take(s: RunState, r: OverworldRngStreams, c: EventContext) -> EventOutcome:
    c.gain_relic(RelicId.GOLDEN_IDOL)
    s.event_scratch.setdefault("Golden Idol", {})["trap"] = True
    return _out("金神像：拿走（得金神像），触发陷阱", reopen=True)


def _golden_idol_run(s: RunState, r: OverworldRngStreams, c: EventContext) -> EventOutcome:
    from sts.content.cards.curses import INJURY

    s.add_card(INJURY)
    return _out("金神像：逃跑，受伤诅咒")


def _golden_idol_tank(s: RunState, r: OverworldRngStreams, c: EventContext) -> EventOutcome:
    loss = s.max_hp * 25 // 100  # A15：35%（java:47-52,108）
    s.lose_hp(loss)
    return _out(f"金神像：硬抗，损 {loss} HP")


def _golden_idol_hide(s: RunState, r: OverworldRngStreams, c: EventContext) -> EventOutcome:
    loss = max(1, s.max_hp * 8 // 100)  # A15：10%（java:49-56,117）
    s.lose_hp(loss)
    return _out(f"金神像：躲藏，损 {loss} HP")


def _golden_idol_options(s: RunState) -> tuple[EventOption, ...]:
    if s.event_scratch.get("Golden Idol", {}).get("trap"):
        return (
            EventOption("逃跑（受伤诅咒）", _golden_idol_run),
            EventOption("硬抗（损 25% 最大生命）", _golden_idol_tank),
            EventOption("躲藏（损 8% 最大生命）", _golden_idol_hide),
        )
    return (
        EventOption("拿走（得金神像遗物，触发陷阱）", _golden_idol_take),
        EventOption("离开", lambda s, r, c: _leave("金神像：离开")),
    )


GOLDEN_IDOL = EventDef(
    eid="Golden Idol",
    zh="金神像",
    options=(),
    options_fn=_golden_idol_options,
)


def _golden_wing_pray(s: RunState, r: OverworldRngStreams, c: EventContext) -> EventOutcome:
    s.lose_hp(7)
    return _out("翅膀雕像：祈祷，损 7 HP + 移除 1 牌", card_choice=CardChoice("remove", 1))


def _golden_wing_smash(s: RunState, r: OverworldRngStreams, c: EventContext) -> EventOutcome:
    g = r.misc.int_inclusive(50, 80)
    s.add_gold(g)
    return _out(f"翅膀雕像：摧毁，得 {g} 金")


def _has_strong_attack(state: RunState) -> bool:
    """摧毁需卡组有 baseDamage ≥ 10 的攻击牌（CardHelper.java:54-61）。"""
    from sts.overworld.card_pools import _wiki_index

    wiki = _wiki_index()
    return any(
        getattr(dc.card, "ctype", "") == "Attack" and (wiki.get(dc.card.name, {}).get("damage") or 0) >= 10
        for dc in state.deck
    )


GOLDEN_WING = EventDef(
    eid="Golden Wing",
    zh="翅膀雕像",
    options=(
        EventOption("祈祷（损 7 HP + 移除 1 牌）", _golden_wing_pray),
        EventOption("摧毁（得 50-80 金）", _golden_wing_smash, _has_strong_attack),
        EventOption("离开", lambda s, r, c: _leave("翅膀雕像：离开")),
    ),
)


def _goop_collect(s: RunState, r: OverworldRngStreams, c: EventContext) -> EventOutcome:
    s.add_gold(75)
    s.lose_hp(11)
    return _out("黏液世界：收集，得 75 金损 11 HP")


def _goop_leave(s: RunState, r: OverworldRngStreams, c: EventContext) -> EventOutcome:
    g = min(r.misc.int_inclusive(20, 50), s.gold)  # A15：35-75（java:30-36,67）
    s.spend_gold(g)
    return _out(f"黏液世界：放手，失 {g} 金")


WORLD_OF_GOOP = EventDef(
    eid="World of Goop",
    zh="黏液世界",
    options=(EventOption("收集（得 75 金，损 11 HP）", _goop_collect), EventOption("放手", _goop_leave)),
)


def _liars_agree(s: RunState, r: OverworldRngStreams, c: EventContext) -> EventOutcome:
    s.add_gold(175)  # A15：150（java:30-32）
    curse = c.gain_random_curse()
    return _out(f"说谎游戏：同意，得 175 金 + {curse.zh}")


LIARS_GAME = EventDef(
    eid="Liars Game",
    zh="蛇～",
    options=(
        EventOption("同意（得 175 金 + 随机诅咒）", _liars_agree),
        EventOption("反对（无事）", lambda s, r, c: _leave("说谎游戏：反对")),
    ),
)


def _wall_forget(s: RunState, r: OverworldRngStreams, c: EventContext) -> EventOutcome:
    return _out("活墙壁：遗忘", card_choice=CardChoice("remove", 1))


def _wall_change(s: RunState, r: OverworldRngStreams, c: EventContext) -> EventOutcome:
    return _out("活墙壁：改变", card_choice=CardChoice("transform", 1))


def _wall_grow(s: RunState, r: OverworldRngStreams, c: EventContext) -> EventOutcome:
    return _out("活墙壁：成长", card_choice=CardChoice("upgrade", 1))


LIVING_WALL = EventDef(
    eid="Living Wall",
    zh="活墙壁",
    options=(
        EventOption("遗忘（移除 1 牌）", _wall_forget),
        EventOption("改变（变化 1 牌）", _wall_change),
        EventOption("成长（升级 1 牌）", _wall_grow, lambda s: bool(s.upgradable_indices())),
    ),
)


def _mushrooms_stomp(s: RunState, r: OverworldRngStreams, c: EventContext) -> EventOutcome:
    return EventOutcome(
        log="蘑菇：踩扁，进入蘑菇巢穴战斗",
        pending_combat=PendingCombat(
            encounter="mushrooms_event", gold=(20, 30), reward_relic=RelicId.ODD_MUSHROOM
        ),
    )


def _mushrooms_eat(s: RunState, r: OverworldRngStreams, c: EventContext) -> EventOutcome:
    from sts.content.cards.curses import PARASITE

    healed = s.heal(s.max_hp // 4)
    s.add_card(PARASITE)
    return _out(f"蘑菇：吃下，回复 {healed} HP + 寄生诅咒")


MUSHROOMS = EventDef(
    eid="Mushrooms",
    zh="蘑菇",
    pool_available=lambda s: s.floor > 6,  # floorNum > 6（java:1936）
    options=(EventOption("踩扁（进战斗，胜得 20-30 金 + 奇怪蘑菇遗物）", _mushrooms_stomp), EventOption("吃下", _mushrooms_eat)),
)


def _scrap_ooze_reach(s: RunState, r: OverworldRngStreams, c: EventContext) -> EventOutcome:
    scratch = s.event_scratch.setdefault("Scrap Ooze", {})
    fail = scratch.get("fail", 0)
    s.lose_hp(3 + fail)  # 每次失败伤害 +1（java:71-72）；A15 首次 5
    if r.misc.int_inclusive(0, 99) < 25 + 10 * fail:
        relic = c.gain_random_relic()
        return _out(f"破烂软泥：得遗物 {relic.name}")
    scratch["fail"] = fail + 1
    return _out("破烂软泥：失败，可再伸手", reopen=True)


SCRAP_OOZE = EventDef(
    eid="Scrap Ooze",
    zh="破烂软泥",
    options=(
        EventOption("伸手（损 3+ HP；25% 得随机遗物，每次失败 +10%）", _scrap_ooze_reach),
        EventOption("离开", lambda s, r, c: _leave("破烂软泥：离开")),
    ),
)


def _shining_light(s: RunState, r: OverworldRngStreams, c: EventContext) -> EventOutcome:
    s.lose_hp(s.max_hp * 20 // 100)  # A15：30%（java:40,65）
    n = c.upgrade_random_cards(2)
    return _out(f"闪耀之光：损 {s.max_hp * 20 // 100} HP，升级 {n} 张")


SHINING_LIGHT = EventDef(
    eid="Shining Light",
    zh="闪耀之光",
    options=(EventOption("走进（损 20% 最大生命，随机升级 2 张）", _shining_light), EventOption("离开", lambda s, r, c: _leave("闪耀之光：离开"))),
)


# ---- shrineList 6 个 ----


def _match_and_keep(s: RunState, r: OverworldRngStreams, c: EventContext) -> EventOutcome:
    """对对碰（5 次翻牌机会，配成加入卡组；GremlinMatchGame.java:56-71,228）。

    本体为交互式翻牌（玩家记忆策略）；分布级近似：每次机会按 1/3 成功
    配对（6 对 12 张、5 次机会下的乐观近似），配成的对加入卡组。
    已声明近似（DESIGN.md §3 分布级保真）。
    """
    from sts.content.cards.ironclad import STRIKE

    pair_cards = [
        OWN_POOLS["rare"][r.misc.int_inclusive(0, len(OWN_POOLS["rare"]) - 1)],
        OWN_POOLS["uncommon"][r.misc.int_inclusive(0, len(OWN_POOLS["uncommon"]) - 1)],
        OWN_POOLS["common"][r.misc.int_inclusive(0, len(OWN_POOLS["common"]) - 1)],
        COLORLESS_POOLS["rare"][r.misc.int_inclusive(0, len(COLORLESS_POOLS["rare"]) - 1)],
        CURSE_POOL[r.misc.int_inclusive(0, len(CURSE_POOL) - 1)],
        STRIKE,  # 角色初始牌（A15 版本换成第 2 张诅咒，不实现）
    ]
    matched = sum(1 for _ in range(5) if r.misc.int_inclusive(0, 99) < 33)
    for card in pair_cards[:matched]:
        s.add_card(card)
    return _out(f"对对碰：配成 {matched} 对，已加入卡组")


MATCH_AND_KEEP = EventDef(
    eid="Match and Keep!",
    zh="对对碰！",
    category="shrine",
    options=(EventOption("开始翻牌配对", _match_and_keep),),
)


def _goldshrine_pray(s: RunState, r: OverworldRngStreams, c: EventContext) -> EventOutcome:
    s.add_gold(100)  # A15：50（java:36）
    return _out("金色神龛：+100 金")


def _goldshrine_desecrate(s: RunState, r: OverworldRngStreams, c: EventContext) -> EventOutcome:
    s.add_gold(275)
    curse = c.gain_random_curse()
    return _out(f"金色神龛：+275 金 + {curse.zh}")


GOLDEN_SHRINE = EventDef(
    eid="Golden Shrine",
    zh="金色神龛",
    category="shrine",
    options=(
        EventOption("祈祷（+100 金）", _goldshrine_pray),
        EventOption("亵渎（+275 金 + 随机诅咒）", _goldshrine_desecrate),
        EventOption("离开", lambda s, r, c: _leave("金色神龛：离开")),
    ),
)

TRANSMOGRIFIER = EventDef(
    eid="Transmorgrifier",
    zh="转化神龛",
    category="shrine",
    options=(
        EventOption("祈祷（变化 1 张牌）", lambda s, r, c: _out("转化神龛：变化 1 张", card_choice=CardChoice("transform", 1))),
        EventOption("离开", lambda s, r, c: _leave("转化神龛：离开")),
    ),
)

PURIFIER = EventDef(
    eid="Purifier",
    zh="净化",
    category="shrine",
    options=(
        EventOption("祈祷（移除 1 张牌）", lambda s, r, c: _out("净化：移除 1 张", card_choice=CardChoice("remove", 1))),
        EventOption("离开", lambda s, r, c: _leave("净化：离开")),
    ),
)

UPGRADE_SHRINE = EventDef(
    eid="Upgrade Shrine",
    zh="升级神龛",
    category="shrine",
    options=(
        EventOption("祈祷（升级 1 张牌）", lambda s, r, c: _out("升级神龛：升级 1 张", card_choice=CardChoice("upgrade", 1))),
        EventOption("离开", lambda s, r, c: _leave("升级神龛：离开")),
    ),
)


def _wheel_of_change(s: RunState, r: OverworldRngStreams, c: EventContext) -> EventOutcome:
    """6 面等概率转盘（不可拒绝；GremlinWheelGame.java:220,72-98,283-289）。"""
    roll = r.misc.int_inclusive(0, 5)
    if roll == 0:
        s.add_gold(100)  # Act 1 面额（City 200 / Beyond 300）
        return _out("变化大转盘：+100 金")
    if roll == 1:
        relic = c.gain_random_relic()
        return _out(f"变化大转盘：遗物 {relic.name}")
    if roll == 2:
        healed = s.heal(s.max_hp - s.hp)
        return _out(f"变化大转盘：回满 HP（+{healed}）")
    if roll == 3:
        curse = c.gain_random_curse()
        return _out(f"变化大转盘：{curse.zh} 诅咒")
    if roll == 4:
        return _out("变化大转盘：移除 1 张", card_choice=CardChoice("remove", 1))
    loss = s.max_hp // 10  # A15：15%（java:72-83,283-289）
    s.lose_hp(loss)
    return _out(f"变化大转盘：损 {loss} HP")


WHEEL_OF_CHANGE = EventDef(
    eid="Wheel of Change",
    zh="变化大转盘",
    category="shrine",
    options=(EventOption("转动（不可拒绝）", _wheel_of_change),),
)


# ---- one-time 7 个（NoteForYourself 跳过：跨 run 持久状态） ----


def _blacksmith_forge(s: RunState, r: OverworldRngStreams, c: EventContext) -> EventOutcome:
    return _out("邪恶熔炉：锻造", card_choice=CardChoice("upgrade", 1))


def _blacksmith_rummage(s: RunState, r: OverworldRngStreams, c: EventContext) -> EventOutcome:
    c.gain_relic(RelicId.WARPED_TONGS)
    curse = c.gain_random_curse()
    return _out(f"邪恶熔炉：怪钳 + {curse.zh}")


ACCURSED_BLACKSMITH = EventDef(
    eid="Accursed Blacksmith",
    zh="邪恶熔炉",
    category="onetime",
    options=(
        EventOption("锻造（升级 1 张牌）", _blacksmith_forge),
        EventOption("翻查（怪钳遗物 + 随机诅咒）", _blacksmith_rummage),
        EventOption("离开", lambda s, r, c: _leave("邪恶熔炉：离开")),
    ),
)

BONFIRE_ELEMENTALS = EventDef(
    eid="Bonfire Elementals",
    zh="篝火精灵",
    category="onetime",
    options=(EventOption("献上 1 张牌（按稀有度给奖励）", lambda s, r, c: _out("篝火精灵：献祭", card_choice=CardChoice("bonfire_sacrifice", 1))),),
)

_FACES = (RelicId.CULTIST_MASK, RelicId.FACE_OF_CLERIC, RelicId.GREMLIN_MASK, RelicId.NLOTHS_MASK, RelicId.SSSERPENT_HEAD)


def _face_touch(s: RunState, r: OverworldRngStreams, c: EventContext) -> EventOutcome:
    s.add_gold(75)  # A15：50（java:33-34）
    s.lose_hp(max(1, s.max_hp // 10))
    return _out(f"换脸商：+75 金，损 {max(1, s.max_hp // 10)} HP")


def _face_trade(s: RunState, r: OverworldRngStreams, c: EventContext) -> EventOutcome:
    unowned = [m for m in _FACES if m not in s.relics]
    if not unowned:
        relic = c.gain_relic(RelicId.CIRCLET)  # 全持有 → Circlet（java:91-112）
        return _out(f"换脸商：{relic.name}")
    mask = unowned[r.misc.int_inclusive(0, len(unowned) - 1)]
    c.gain_relic(mask)
    return _out(f"换脸商：{mask.name}")


FACE_TRADER = EventDef(
    eid="FaceTrader",
    zh="换脸商",
    category="onetime",
    options=(
        EventOption("触碰（得 75 金，损 最大生命/10）", _face_touch),
        EventOption("交易（得随机面具遗物）", _face_trade),
        EventOption("离开", lambda s, r, c: _leave("换脸商：离开")),
    ),
)


def _fountain_drink(s: RunState, r: OverworldRngStreams, c: EventContext) -> EventOutcome:
    from sts.content.cards.curses import ASCENDERS_BANE, CURSE_OF_THE_BELL, NECRONOMICURSE, PRIDE

    keep = {c2.name for c2 in (ASCENDERS_BANE, CURSE_OF_THE_BELL, NECRONOMICURSE, PRIDE)}
    n = 0
    for i in range(len(s.deck) - 1, -1, -1):
        if getattr(s.deck[i].card, "ctype", "") == "Curse" and s.deck[i].card.name not in keep:
            s.deck.pop(i)
            n += 1
    return _out(f"神圣泉水：移除 {n} 张诅咒")


FOUNTAIN_OF_CLEANSing = EventDef(
    eid="Fountain of Cleansing",
    zh="神圣泉水",
    category="onetime",
    pool_available=lambda s: s.has_curse(),  # 仅当卡组有诅咒（java:1868-1872）
    options=(EventOption("喝水（移除所有诅咒）", _fountain_drink), EventOption("离开", lambda s, r, c: _leave("神圣泉水：离开"))),
)


def _lab_search(s: RunState, r: OverworldRngStreams, c: EventContext) -> EventOutcome:
    gained = sum(1 for _ in range(3) if c.gain_random_potion() is not None)  # A15：2 瓶
    return _out(f"实验室：得 {gained} 瓶药水（满槽弃 {3 - gained}）")


LAB = EventDef(
    eid="Lab",
    zh="实验室",
    category="onetime",
    options=(EventOption("搜索（得 3 瓶随机药水）", _lab_search),),
)


def _meet_give_potion(s: RunState, r: OverworldRngStreams, c: EventContext) -> EventOutcome:
    slots = [i for i, p in enumerate(s.potions) if p is not None]
    i = slots[r.misc.int_inclusive(0, len(slots) - 1)]
    s.potions[i] = None
    relic = c.gain_random_relic()
    return _out(f"我们又见面了：给药水，得 {relic.name}")


def _meet_give_gold(s: RunState, r: OverworldRngStreams, c: EventContext) -> EventOutcome:
    g = min(r.misc.int_inclusive(50, min(150, s.gold)), s.gold)  # java:72-80
    s.spend_gold(g)
    relic = c.gain_random_relic()
    return _out(f"我们又见面了：给 {g} 金，得 {relic.name}")


def _giftable_indices(s: RunState) -> list[int]:
    """非基础非诅咒牌（java:59-69）。"""
    return [i for i, dc in enumerate(s.deck) if card_wiki_rarity(dc.card) not in ("basic", "curse", "")]


def _meet_give_card(s: RunState, r: OverworldRngStreams, c: EventContext) -> EventOutcome:
    idxs = _giftable_indices(s)
    i = idxs[r.misc.int_inclusive(0, len(idxs) - 1)]
    name = s.deck[i].card.zh
    s.remove_card(i)
    relic = c.gain_random_relic()
    return _out(f"我们又见面了：给 {name}，得 {relic.name}")


WE_MEET_AGAIN = EventDef(
    eid="WeMeetAgain",
    zh="我们又见面了！",
    category="onetime",
    options=(
        EventOption("给他一瓶药水（得随机遗物）", _meet_give_potion, lambda s: any(p is not None for p in s.potions)),
        EventOption("给他金币（得随机遗物）", _meet_give_gold, lambda s: s.gold >= 50),
        EventOption("给他一张牌（得随机遗物）", _meet_give_card, lambda s: bool(_giftable_indices(s))),
        EventOption("攻击（无事）", lambda s, r, c: _leave("我们又见面了：攻击")),
    ),
)


def _woman_buy(n: int, cost: int) -> Callable:
    def _buy(s: RunState, r: OverworldRngStreams, c: EventContext) -> EventOutcome:
        s.spend_gold(cost)
        gained = sum(1 for _ in range(n) if c.gain_random_potion() is not None)
        return _out(f"蓝衣女子：花 {cost} 金得 {gained} 瓶药水")

    return _buy


WOMAN_IN_BLUE = EventDef(
    eid="The Woman in Blue",
    zh="蓝衣女子",
    category="onetime",
    pool_available=lambda s: s.gold >= 50,  # java:1903-1907
    options=(
        EventOption("买 1 瓶（20 金）", _woman_buy(1, 20), lambda s: s.gold >= 20),
        EventOption("买 2 瓶（30 金）", _woman_buy(2, 30), lambda s: s.gold >= 30),
        EventOption("买 3 瓶（40 金）", _woman_buy(3, 40), lambda s: s.gold >= 40),
        EventOption("离开", lambda s, r, c: _leave("蓝衣女子：离开")),
    ),
)


# ---- 注册表 ----


def _reg(defs: tuple[EventDef, ...]) -> dict[str, EventDef]:
    return {e.eid: e for e in defs}


ACT1_EVENTS: dict[str, EventDef] = _reg(
    (
        BIG_FISH, THE_CLERIC, DEAD_ADVENTURER, GOLDEN_IDOL, GOLDEN_WING,
        WORLD_OF_GOOP, LIARS_GAME, LIVING_WALL, MUSHROOMS, SCRAP_OOZE, SHINING_LIGHT,
    )
)
ACT1_SHRINES: dict[str, EventDef] = _reg(
    (MATCH_AND_KEEP, GOLDEN_SHRINE, TRANSMOGRIFIER, PURIFIER, UPGRADE_SHRINE, WHEEL_OF_CHANGE)
)
ACT1_ONETIMES: dict[str, EventDef] = _reg(
    (
        ACCURSED_BLACKSMITH, BONFIRE_ELEMENTALS, FACE_TRADER, FOUNTAIN_OF_CLEANSing,
        LAB, WE_MEET_AGAIN, WOMAN_IN_BLUE,
    )
)

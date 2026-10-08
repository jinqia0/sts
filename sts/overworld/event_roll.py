"""？房房型 roll 与事件选择（Phase 3a，2026-10-08）。

对齐本体：
- 房型 roll（EventHelper.java:94-181）：eventRng 一个 float → 100 格；
  格子按 [MONSTER] [SHOP] [TREASURE] [EVENT…] 顺序填充——即
  cell < monster×100 → MONSTER；< (m+s)×100 → SHOP；< (m+s+t)×100 →
  TREASURE；否则 EVENT。斜坡：非命中 +0.1/+0.03/+0.02，命中重置。
  Juzu 把 MONSTER 强转 EVENT（斜坡仍重置）；TinyChest 第 4 个 ？房
  强制 TREASURE（计数在每个 ？房 roll 时 +1，第 4 次归零重计）。
- 事件选择（AbstractDungeon.generateEvent :1844-1860）：eventRng
  < 0.25 → shrine 分支（shrineList + 合格 one-time 合并均匀抽），
  否则 eventList（池空互相回退）；抽中即从池移除（本 Act 不重复）。
- 池过滤条件在 EventDef.pool_available（getEvent :1924-1969 /
  getShrine :1862-1922 的按名 switch）。

分布级：本体事件选择用 eventRng counter 克隆不回写（EventRoom.java:25-26
怪癖）——本实现直接顺序消费 event 流（不去对齐 counter 步进）。
"""

from __future__ import annotations

from sts.combat.relics import RelicId
from sts.content.events import ACT1_EVENTS, ACT1_ONETIMES, ACT1_SHRINES, EventDef
from sts.overworld.rng import OverworldRngStreams
from sts.overworld.state import RunState

SHRINE_CHANCE = 0.25  # AbstractDungeon.java:2695

_MONSTER_RAMP = 0.1
_SHOP_RAMP = 0.03
_TREASURE_RAMP = 0.02
_MONSTER_RESET = 0.1
_SHOP_RESET = 0.03
_TREASURE_RESET = 0.02
_TINY_CHEST_INTERVAL = 4


def roll_unknown_room(state: RunState, rngs: OverworldRngStreams) -> str:
    """进 ？房先 roll 房型。返回 event / monster / shop / treasure。

    注意：monster 结果可被 Juzu 强转 event（斜坡重置照常发生）；
    tiny chest 在此计数（每 4 个 ？房强制 treasure）。
    """
    # Tiny Chest 计数（EventHelper.java:99-107）
    force_chest = False
    if state.has(RelicId.TINY_CHEST):
        counter = state.counter(RelicId.TINY_CHEST) + 1
        if counter == _TINY_CHEST_INTERVAL:
            counter = 0
            force_chest = True
        state.set_counter(RelicId.TINY_CHEST, counter)

    cell = rngs.event.int_inclusive(0, 99)  # floor(roll×100) 的整数等价

    monster_size = int(state.monster_slope * 100)
    shop_size = int(state.shop_slope * 100)
    treasure_size = int(state.treasure_slope * 100)
    if cell < monster_size:
        choice = "monster"
    elif cell < monster_size + shop_size:
        choice = "shop"
    elif cell < monster_size + shop_size + treasure_size:
        choice = "treasure"
    else:
        choice = "event"
    if force_chest:
        choice = "treasure"

    # Juzu：MONSTER → EVENT（转换发生在斜坡更新前，重置照常，java:150-153,158-160）
    if choice == "monster" and state.has(RelicId.JUZU_BRACELET):
        choice = "event"

    # 斜坡更新
    state.monster_slope = _MONSTER_RESET if choice == "monster" else state.monster_slope + _MONSTER_RAMP
    state.shop_slope = _SHOP_RESET if choice == "shop" else state.shop_slope + _SHOP_RAMP
    state.treasure_slope = _TREASURE_RESET if choice == "treasure" else state.treasure_slope + _TREASURE_RAMP
    return choice


def _shrine_pool(state: RunState) -> list[EventDef]:
    out = [e for e in ACT1_SHRINES.values() if e.eid in state.shrine_pool and (e.pool_available is None or e.pool_available(state))]
    for e in ACT1_ONETIMES.values():
        if e.eid not in state.onetime_pool:
            continue  # 已在本 Act 用过
        if e.pool_available is None or e.pool_available(state):
            out.append(e)
    return out


def _event_pool(state: RunState) -> list[EventDef]:
    return [e for e in ACT1_EVENTS.values() if e.eid in state.event_pool and (e.pool_available is None or e.pool_available(state))]


def pick_event(state: RunState, rngs: OverworldRngStreams) -> EventDef | None:
    """事件分流：0.25 shrine / 0.75 event（池空互相回退），抽后移除。"""
    go_shrine = rngs.event.int_inclusive(0, 99) < int(SHRINE_CHANCE * 100)
    pools = (_shrine_pool(state), _event_pool(state)) if go_shrine else (_event_pool(state), _shrine_pool(state))
    primary, fallback = pools
    pool = primary or fallback
    if not pool:
        return None  # 池全空（25 事件耗尽——Act 1 内不可达，防御性返回）
    event = pool[rngs.event.int_inclusive(0, len(pool) - 1)]
    # 抽后移除（shrine 分支同时从 shrineList 与 one-time 池移除）
    state.event_pool = [e for e in state.event_pool if e != event.eid]
    state.shrine_pool = [e for e in state.shrine_pool if e != event.eid]
    state.onetime_pool = [e for e in state.onetime_pool if e != event.eid]
    return event


def initialize_event_pools(state: RunState) -> None:
    """run 开始时装池（顺序无关——抽取为池内均匀，无需洗牌）。"""
    state.event_pool = list(ACT1_EVENTS)
    state.shrine_pool = list(ACT1_SHRINES)
    state.onetime_pool = list(ACT1_ONETIMES)


def shuffle_event_pools(state: RunState, rngs: OverworldRngStreams) -> None:
    rngs.event.shuffle(state.event_pool)
    rngs.event.shuffle(state.shrine_pool)
    rngs.event.shuffle(state.onetime_pool)

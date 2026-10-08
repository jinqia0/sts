"""局外策略接口（Phase 3a，2026-10-08）——DESIGN.md §8.3 七决策点。

RunPolicy 只做局外决策；战斗内行为由 battle_policy（sts/baselines.py 的
``policy(env) -> int`` 签名）承担——层级分离在策略层同样成立。

RandomPolicy：合法选项均匀随机（自测与统计基线）。
SimpleHeuristicPolicy：贪心级启发式（3a 自测对照用，不追求强度——
正式基线是 3a 的"启发式 + oracle"）。
"""

from __future__ import annotations

from sts.combat.relics import RelicId
from sts.content.cards import CardDef
from sts.content.events import EventDef, EventOption
from sts.content.potions import PotionDef
from sts.overworld.shop import ShopStock
from sts.overworld.state import RunState
from sts.rng import Rng

# 商店动作类型：("card", i) / ("relic", i) / ("potion", i) /
# ("purge", deck_index) / None（离开）
ShopAction = tuple[str, int] | None


class RunPolicy:
    """局外决策点接口（子类覆盖；未覆盖项用保守默认）。"""

    def __init__(self, seed: int | None = None):
        self.rng = Rng(seed)

    # ---- 路线 ----

    def choose_start_node(self, state: RunState, starts: list[tuple[int, int]]) -> int:
        return 0

    def choose_path(self, state: RunState, candidates: list[tuple[int, int]]) -> int:
        return 0

    # ---- 卡牌奖励（None = 跳过）----

    def choose_card_reward(self, state: RunState, cards: list[CardDef]) -> int | None:
        return cards and 0 or None

    def choose_colorless_gain(self, state: RunState, cards: list[CardDef]) -> int | None:
        return cards and 0 or None

    # ---- 事件（valid = 可用选项下标）----

    def choose_event_option(self, state: RunState, event: EventDef, options: list[EventOption], valid: list[int]) -> int:
        return valid[0]

    # ---- 火堆（options：rest / smith / lift / dig / smoke）----

    def choose_campfire(self, state: RunState, options: list[str]) -> int:
        return 0

    # ---- 卡组选择（candidates = 卡组下标；kind 见 events.CardChoice）----

    def choose_card_indices(self, state: RunState, kind: str, candidates: list[int], n: int) -> list[int]:
        return candidates[:n]

    # ---- 商店（逐件决策：返回一个购买动作或 None 离开）----

    def shop_action(self, state: RunState, stock: ShopStock) -> ShopAction:
        return None

    # ---- 药水满槽（弃哪一瓶：槽位号；-1 = 弃新掉落的）----

    def choose_potion_discard(self, state: RunState, incoming: PotionDef) -> int:
        return -1

    # ---- Boss 宝箱（None = 跳过）----

    def choose_boss_relic(self, state: RunState, relics: list[RelicId]) -> int | None:
        return relics and 0 or None


class RandomPolicy(RunPolicy):
    """合法选项均匀随机。"""

    def _idx(self, n: int) -> int:
        return self.rng.int_inclusive(0, n - 1)

    def choose_start_node(self, state: RunState, starts: list[tuple[int, int]]) -> int:
        return self._idx(len(starts))

    def choose_path(self, state: RunState, candidates: list[tuple[int, int]]) -> int:
        return self._idx(len(candidates))

    def choose_card_reward(self, state: RunState, cards: list[CardDef]) -> int | None:
        # 3 张 + 跳过（四选一均匀；无牌必跳）
        return self._idx(len(cards) + 1) if cards else None

    def choose_colorless_gain(self, state: RunState, cards: list[CardDef]) -> int | None:
        return self.choose_card_reward(state, cards)

    def choose_event_option(self, state: RunState, event: EventDef, options: list[EventOption], valid: list[int]) -> int:
        return valid[self._idx(len(valid))]

    def choose_campfire(self, state: RunState, options: list[str]) -> int:
        return self._idx(len(options))

    def choose_card_indices(self, state: RunState, kind: str, candidates: list[int], n: int) -> list[int]:
        picked = list(candidates)
        self.rng.shuffle(picked)
        return picked[:n]

    def shop_action(self, state: RunState, stock: ShopStock) -> ShopAction:
        affordable: list[tuple[str, int, int]] = []
        for i, sc in enumerate(stock.cards):
            if sc.price <= state.gold:
                affordable.append(("card", i, sc.price))
        for i, sr in enumerate(stock.relics):
            if sr.price <= state.gold:
                affordable.append(("relic", i, sr.price))
        for i, sp in enumerate(stock.potions):
            if sp.price <= state.gold:
                affordable.append(("potion", i, sp.price))
        if state.gold >= stock.purge_cost(state) and state.purgable_indices():
            affordable.append(("purge", 0, stock.purge_cost(state)))
        if not affordable:
            return None
        kind, idx, _ = affordable[self._idx(len(affordable))]
        return (kind, idx)

    def choose_potion_discard(self, state: RunState, incoming: PotionDef) -> int:
        return self.rng.int_inclusive(-1, len(state.potions) - 1)

    def choose_boss_relic(self, state: RunState, relics: list[RelicId]) -> int | None:
        return self._idx(len(relics) + 1) if relics else None  # 含跳过


class SimpleHeuristicPolicy(RunPolicy):
    """贪心级启发式（3a 自测对照）：

    - 路线/起点：第一个候选
    - 卡牌奖励：总拿第一张（牌组 < 30）；牌组大了开始跳过
    - 事件：首个可用选项
    - 火堆：血量 < 60% 休息，否则有可升级牌就锻造（升级位取最左），
      否则休息
    - 卡组选择：最左 n 张（remove 取第一张非核心牌的近似——直接最左）
    - 商店：金币 > 200 时买最便宜的卡，否则离开
    - 药水满槽：弃新掉落
    - Boss 遗物：第一个
    """

    def choose_card_reward(self, state: RunState, cards: list[CardDef]) -> int | None:
        if len(state.deck) < 30 and cards:
            return 0
        return None

    def choose_campfire(self, state: RunState, options: list[str]) -> int:
        if "rest" in options and state.hp < state.max_hp * 6 // 10:
            return options.index("rest")
        if "smith" in options and state.upgradable_indices():
            return options.index("smith")
        if "rest" in options:
            return options.index("rest")
        return 0

    def choose_card_indices(self, state: RunState, kind: str, candidates: list[int], n: int) -> list[int]:
        return candidates[:n]

    def shop_action(self, state: RunState, stock: ShopStock) -> ShopAction:
        if state.gold <= 200:
            return None
        affordable = [(sc.price, i) for i, sc in enumerate(stock.cards) if sc.price <= state.gold]
        if affordable:
            _, i = min(affordable)
            return ("card", i)
        return None

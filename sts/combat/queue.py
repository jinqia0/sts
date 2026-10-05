"""动作队列与卡牌队列：一切结算的载体（sts_lightspeed 核心架构）。

设计（对齐 lightspeed ActionQueue.h / CardQueue.h）：
- 动作 = 一个吃 BattleContext 的闭包，无返回值。出牌/敌方行动都不
  直接结算，而是把原子动作压入队列，由 BattleContext.execute_actions
  统一弹出执行。复杂交互（结算中再触发）天然由队列顺序表达。
- addToTop（插队，先执行）/ addToBot（排队，后执行）两个压入端。
- clear_on_victory：战斗胜利时，队列中携带此标志的动作（如本会
  打空的攻击）被清空——对齐 lightspeed Action.clearOnCombatVictory。
"""

from __future__ import annotations

from collections import deque
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Callable

if TYPE_CHECKING:  # 仅类型标注，避免循环导入
    from sts.combat.battle import BattleContext
    from sts.combat.card_manager import CardInstance


@dataclass
class Action:
    fn: Callable[[BattleContext], None]
    clear_on_victory: bool = True


class ActionQueue:
    """双端队列。front 为弹出端；addToTop = pushFront，addToBot = pushBack。"""

    def __init__(self) -> None:
        self._q: deque[Action] = deque()

    def push_front(self, a: Action) -> None:
        self._q.appendleft(a)

    def push_back(self, a: Action) -> None:
        self._q.append(a)

    def pop_front(self) -> Action:
        return self._q.popleft()

    def is_empty(self) -> bool:
        return not self._q

    def __len__(self) -> int:
        return len(self._q)

    def clear(self) -> None:
        self._q.clear()

    def clear_post_combat(self) -> None:
        """胜利结算：清掉 clear_on_victory 的动作，保留其余（对齐 lightspeed）。"""
        self._q = deque(a for a in self._q if not a.clear_on_victory)


@dataclass
class CardQueueItem:
    """卡牌队列项（对齐 lightspeed CardQueueItem，字段裁剪到当前场景）。

    普通出牌：card + target；结束回合：is_end_turn=True 的哨兵项。
    trigger_on_use=False 的项是诅咒/状态卡的自动结算（如 Burn），
    走 useNoTriggerCard 路径——本场景暂无，保留字段供扩展。
    """

    card: CardInstance | None = None
    target: int = -1
    is_end_turn: bool = False
    purge_on_use: bool = False
    exhaust_on_use: bool = False
    trigger_on_use: bool = True
    random_target: bool = False
    autoplay: bool = False

    @staticmethod
    def end_turn_item() -> CardQueueItem:
        return CardQueueItem(is_end_turn=True)


class CardQueue:
    """卡牌队列：FIFO。一次通常只有一项在处理（连打除外）。"""

    def __init__(self) -> None:
        self._q: deque[CardQueueItem] = deque()

    def push_back(self, item: CardQueueItem) -> None:
        self._q.append(item)

    def pop_front(self) -> CardQueueItem:
        return self._q.popleft()

    def is_empty(self) -> bool:
        return not self._q

    def clear(self) -> None:
        self._q.clear()

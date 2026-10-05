"""卡牌实例与卡堆管理（对齐 lightspeed CardInstance.h / CardManager.h）。

Card（内容层定义，不可变模板）与 CardInstance（战斗内实例，带
unique_id 与本回合费用状态）分离：同一张牌的两份拷贝、临时生成牌、
升级标志都挂在实例上。临时牌（Anger/Wild Strike）以战斗内普通
实例的最小形态支持（不做战斗结束回收）。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from sts.content.cards import CardDef

MAX_HAND_SIZE = 10


@dataclass
class CardInstance:
    card: CardDef
    upgraded: bool = False
    unique_id: int = -1
    cost_for_turn: int = -1  # -1 表示未设置（用 card.cost）
    misc_data: int = 0  # 实例计数槽（对齐 lightspeed specialData：Rampage 叠伤/Searing Blow 升级数/Blood for Blood 减费）

    @property
    def cost(self) -> int:
        # 临时改费（如 Madness/Corruption）优先；升级改费（如 Body Slam+）再次；
        # 否则回退模板费用
        if self.cost_for_turn >= 0:
            return self.cost_for_turn
        if self.upgraded and self.card.upgraded_cost is not None:
            return self.card.upgraded_cost
        return self.card.cost

    def __repr__(self) -> str:
        u = "+" if self.upgraded else ""
        return f"{self.card.name}{u}(#{self.unique_id})"


class CardManager:
    """手牌 + 抽/弃/消耗堆 + 实例 id 分配（对齐 lightspeed CardManager）。

    主牌组（Deck）在 GameContext/内容层，战斗开始时把主牌组实例化
    进抽牌堆。next_unique_id 分配的 id 同时用于将来区分同名实例。
    """

    def __init__(self) -> None:
        self.next_unique_card_id = 0
        self.hand: list[CardInstance] = []
        self.draw_pile: list[CardInstance] = []
        self.discard_pile: list[CardInstance] = []
        self.exhaust_pile: list[CardInstance] = []

    # ---- 实例化与移动 ----
    def instantiate(self, card: CardDef) -> CardInstance:
        inst = CardInstance(card=card, unique_id=self.next_unique_card_id)
        self.next_unique_card_id += 1
        return inst

    def create_deck_card_in_draw_pile(self, card: CardDef) -> None:
        self.draw_pile.append(self.instantiate(card))

    def pop_from_draw_pile(self) -> CardInstance:
        return self.draw_pile.pop()

    def remove_from_hand_at_idx(self, idx: int) -> CardInstance:
        return self.hand.pop(idx)

    def move_to_hand(self, c: CardInstance) -> None:
        self.hand.append(c)

    def move_to_discard_pile(self, c: CardInstance) -> None:
        self.discard_pile.append(c)

    def move_to_exhaust_pile(self, c: CardInstance) -> None:
        self.exhaust_pile.append(c)

    def move_discard_pile_into_draw_pile(self) -> None:
        self.draw_pile.extend(self.discard_pile)
        self.discard_pile.clear()

    # ---- 临时牌（对齐 createTempCardInDiscard / InDrawPile / InHand）----
    def create_temp_card_in_discard(self, card: CardDef, upgraded: bool = False) -> None:
        """临时牌进弃牌堆（Anger 副本）。战斗内与普通弃牌无异；
        本项目仅模拟战斗内，不做战斗结束回收。"""
        inst = self.instantiate(card)
        inst.upgraded = upgraded
        self.discard_pile.append(inst)

    def create_temp_card_in_draw_pile(self, card: CardDef, idx: int, upgraded: bool = False) -> None:
        """临时牌插入抽牌堆指定位置（Wild Strike 的伤口，随机位由调用方抽样）。"""
        inst = self.instantiate(card)
        inst.upgraded = upgraded
        self.draw_pile.insert(idx, inst)

    def create_temp_card_in_hand(self, card: CardDef, upgraded: bool = False) -> None:
        """临时牌入手（Power Through 的伤口 / Infernal Blade 的随机攻击）。"""
        if len(self.hand) >= MAX_HAND_SIZE:
            return  # 手牌满：生成牌直接消失（对齐本体手牌上限）
        inst = self.instantiate(card)
        inst.upgraded = upgraded
        self.hand.append(inst)

    def append_to_draw_top(self, inst: CardInstance) -> None:
        """把实例放到抽牌堆顶（Headbutt/Warcry 的置顶效果）。

        抽牌从列表尾弹出，堆顶 = 列表尾。来源堆的移除由调用方负责。
        """
        self.draw_pile.append(inst)

    def move_innate_to_top(self) -> None:
        """战斗开始洗牌后：把固有（Innate）牌按原相对顺序放到抽牌堆顶
        （对齐 lightspeed CardManager::init 的 innate 处理）。"""
        innate = [c for c in self.draw_pile if c.card.innate]
        if not innate:
            return
        rest = [c for c in self.draw_pile if not c.card.innate]
        self.draw_pile[:] = rest + innate  # 堆顶 = 尾部，多张固有按原顺序被抽到

    def reset_attributes_at_end_of_turn(self) -> None:
        """回合结束时清空卡牌的临时属性（本回合费用等）。"""
        for c in self.hand + self.draw_pile + self.discard_pile:
            c.cost_for_turn = -1

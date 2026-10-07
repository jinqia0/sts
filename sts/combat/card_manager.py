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
    cost_override: int | None = None  # 永久改费（Blood for Blood 受击 -1；对齐 C++ 的 cost 字段可变性）
    misc_data: int = 0  # 实例计数槽（对齐 lightspeed specialData：Rampage 叠伤/Searing Blow 升级数/Blood for Blood 减费）
    retain: bool = False  # 本回合保留（回合末进 limbo；Well-Laid Plans/Nightmare 置位，回合开始清除）

    @property
    def is_retained(self) -> bool:
        """回合末保留判定：实例 retain 位或卡牌自带 Retain（对齐 C++
        hasSelfRetain() || retain）。"""
        if self.card is None:
            return self.retain
        if self.card.self_retain or (self.upgraded and getattr(self.card, "retain_when_upgraded", False)):
            return True
        return self.retain

    @property
    def is_ethereal(self) -> bool:
        """虚无判定：模板 ethereal 位；升级后不再虚无（Apparition+，
        isEthereal=false 于 upgrade()）。"""
        if self.card is None:
            return False
        return self.card.ethereal and not (
            self.upgraded and getattr(self.card, "loses_ethereal_on_upgrade", False)
        )

    @property
    def cost(self) -> int:
        # 临时改费（如 Madness/Corruption）→ 永久改费（Blood for Blood）→
        # 升级改费（如 Body Slam+）→ 模板费用
        if self.cost_for_turn >= 0:
            return self.cost_for_turn
        if self.cost_override is not None:
            return self.cost_override
        if self.upgraded and self.card.upgraded_cost is not None:
            return self.card.upgraded_cost
        return self.card.cost

    def update_cost(self, delta: int) -> None:
        """永久改费（对齐 CardInstance::updateCost）：基于当前生效费用增减，下限 0。"""
        base = self.cost
        self.cost_override = max(0, base + delta)

    def upgrade(self) -> bool:
        """升级本实例（对齐 Armaments/打造类路径）：置 upgraded=True 并推进
        实例计数（Searing Blow 类用 misc_data 记升级次数）。已升级则 no-op
        返回 False（Searing Blow 是唯一可反复升级的卡，由其内容层处理计数）。"""
        if self.upgraded:
            return False
        self.upgraded = True
        if self.card.multiple_upgrades:
            self.misc_data += 1
        return True

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
        self.limbo: list[CardInstance] = []  # 回合末保留牌的暂存区（对齐 C++ limbo）

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
        """临时牌入手（Power Through 的伤口 / Infernal Blade 的随机攻击）。

        满手进弃牌堆（对齐 moveToHandHelper else 分支，BattleContext.cpp:2531-2539）。
        """
        inst = self.instantiate(card)
        inst.upgraded = upgraded
        if len(self.hand) < MAX_HAND_SIZE:
            self.hand.append(inst)
        else:
            self.discard_pile.append(inst)

    def append_to_draw_top(self, inst: CardInstance) -> None:
        """把实例放到抽牌堆顶（Headbutt/Warcry 的置顶效果）。

        抽牌从列表尾弹出，堆顶 = 列表尾。来源堆的移除由调用方负责。
        """
        self.draw_pile.append(inst)

    def move_innate_to_top(self) -> None:
        """战斗开始洗牌后：把固有（Innate）牌按原相对顺序放到抽牌堆顶
        （对齐 lightspeed CardManager::init 的 innate 处理）。

        innate_when_upgraded：仅升级版固有（Brutality+）。
        """

        def _is_innate(c: CardInstance) -> bool:
            return c.card.innate or (c.upgraded and getattr(c.card, "innate_when_upgraded", False))

        innate = [c for c in self.draw_pile if _is_innate(c)]
        if not innate:
            return
        rest = [c for c in self.draw_pile if not _is_innate(c)]
        self.draw_pile[:] = rest + innate  # 堆顶 = 尾部，多张固有按原顺序被抽到

    def move_bottled_to_top(self, names: list[str]) -> None:
        """瓶装遗物（Bottled Flame/Lightning/Tornado）选定的卡置抽牌堆顶
        （CardGroup.initializeDeck L921-935：inBottle* 与 innate 同走
        placeOnTop——瓶装牌在固有牌之上被最后抽到…实际 add 序：placeOnTop
        逐张 addToTop（append），故后 add 者更顶；固定序为 innate 先、
        bottle 后，即瓶装牌位于堆最顶）。

        names 为卡名列表（场景/测试表达拾取时的选卡，多张同名全置顶）。
        """
        bottled = [c for c in self.draw_pile if c.card.name in names]
        if not bottled:
            return
        rest = [c for c in self.draw_pile if c.card.name not in names]
        self.draw_pile[:] = rest + bottled

    def reset_attributes_at_end_of_turn(self) -> None:
        """回合结束时清空卡牌的临时属性（本回合费用等）。

        cost_override 不清（Blood for Blood 的永久减费跨回合保留）。
        """
        for c in self.hand + self.draw_pile + self.discard_pile:
            c.cost_for_turn = -1

    def on_player_damaged(self) -> None:
        """玩家每次失去 HP 时（对齐 CardManager::onTookDamage →
        CardInstance::tookDamage）：带 cost_delta_on_damage 的实例
        永久改费（Blood for Blood -1）。三堆全查（对齐 C++ 全堆遍历）。"""
        for c in self.hand + self.draw_pile + self.discard_pile:
            d = c.card.cost_delta_on_damage
            if d:
                c.update_cost(d)

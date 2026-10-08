"""Run 状态（Phase 3a，2026-10-08）。

DESIGN.md §8.6-1 run 状态规格的首块拼图：字段全集（A0 铁甲 Act 1）。
搜索友好：``clone()`` 浅拷贝一切可变容器（CardDef/PotionDef 单例不可变、
遗物为 IntEnum），恢复即替换——快照/回滚的最小实现，够 expectimax 用。

卡组条目带升级位（DeckCard）——战斗引擎 deck 覆盖接受
``CardDef | tuple[CardDef, bool]``（card_manager.create_deck_card_in_draw_pile）。

遗物效果不进战斗钩子链（sts/combat/relics.py 只管战斗面）：局外效果
（拾取/加牌/休息/商店/掉落修正）集中在 sts/overworld/relic_effects.py，
由本模块与 run 循环在操作位调用。
"""

from __future__ import annotations

from dataclasses import dataclass

from sts.combat.relics import RelicId
from sts.content.cards import CardDef
from sts.content.cards.ironclad import BASH, DEFEND, STRIKE
from sts.content.potions import PotionDef

# ---- 初始值（A0，本体 AbstractPlayer：99 金 / 80 HP / 3 药水槽）----
STARTING_GOLD = 99
STARTING_HP = 80
STARTING_POTION_SLOTS = 3

# 铁甲初始牌组：5 打击 / 4 防御 / 1 痛击
INITIAL_DECK_CARDS: list[CardDef] = [STRIKE] * 5 + [DEFEND] * 4 + [BASH]


@dataclass(frozen=True)
class DeckCard:
    """卡组条目：模板 + 升级位（CardDef 是不可变单例，升级是实例状态）。"""

    card: CardDef
    upgraded: bool = False

    @property
    def key(self) -> str:
        return f"{self.card.name}{'+' if self.upgraded else ''}"


class RunState:
    """一局 Act 1 的全部可变状态（地图对象挂载在 run 循环，不入此类）。"""

    def __init__(self) -> None:
        self.hp = STARTING_HP
        self.max_hp = STARTING_HP
        self.gold = STARTING_GOLD
        self.deck: list[DeckCard] = [DeckCard(c) for c in INITIAL_DECK_CARDS]
        self.relics: list[RelicId] = [RelicId.BURNING_BLOOD]
        self.relic_counters: dict[RelicId, int] = {}
        self.potions: list[PotionDef | None] = [None] * STARTING_POTION_SLOTS
        self.floor = 0  # 楼层号（0 = 未进第 1 层；row y → floor y+1）
        # ---- 掉落/奖励计数器 ----
        self.card_pity = 5  # cardBlizzRandomizer：初始 5（AbstractDungeon.java:2753-2755）
        self.potion_blizzard = 0  # 掉率补偿 ±10
        self.purge_uses = 0  # 删牌已用次数（每次 +25）
        # ---- ？房型斜坡（EventHelper.java:71-86，命中重置）----
        self.monster_slope = 0.1
        self.shop_slope = 0.03
        self.treasure_slope = 0.02
        self.seen_unknown_rooms = 0  # TinyChest 每 4 个 ？房计数
        # ---- 池状态（生成于 run 开始，逐场消费）----
        self.event_pool: list[str] = []
        self.shrine_pool: list[str] = []
        self.onetime_pool: list[str] = []
        self.monster_list: list[str] = []  # FIFO：普通房遭遇
        self.elite_list: list[str] = []  # FIFO：精英房遭遇
        self.boss: str = ""
        # ---- 事件多步内部状态（event_id → dict）----
        self.event_scratch: dict[str, dict] = {}
        # ---- 终局 ----
        self.run_over = False
        self.run_won = False

    # ---- 遗物查询 ----

    def has(self, relic: RelicId) -> bool:
        return relic in self.relics

    def counter(self, relic: RelicId) -> int:
        return self.relic_counters.get(relic, 0)

    def set_counter(self, relic: RelicId, value: int) -> None:
        self.relic_counters[relic] = value

    # ---- HP / 金币 ----

    def heal(self, amount: int) -> int:
        """回复（clamp 到上限），返回实际回复量。"""
        before = self.hp
        self.hp = min(self.max_hp, self.hp + amount)
        return self.hp - before

    def lose_hp(self, amount: int) -> None:
        self.hp = max(0, self.hp - amount)

    def gain_max_hp(self, amount: int, heal_too: bool = True) -> None:
        """提升上限（本体 increaseMaxHp(newMax, heal=true 同步回血））。"""
        self.max_hp += amount
        if heal_too:
            self.hp += amount

    def add_gold(self, amount: int) -> None:
        self.gold += amount

    def spend_gold(self, amount: int, in_shop: bool = False) -> None:
        self.gold = max(0, self.gold - amount)
        if in_shop and self.has(RelicId.MAW_BANK):
            # 巨口储蓄罐：在商店花金币即失效（MawBank.java:53）
            self.relic_counters[RelicId.MAW_BANK] = -2

    # ---- 卡组操作（遗物钩子经 relic_effects 注入，避免循环导入）----

    def add_card(self, card: CardDef, upgraded: bool = False) -> None:
        """加入卡组（蛋类自动升级 + 陶瓷小鱼 +9 金，本体 onObtainCard 钩子）。"""
        from sts.overworld.relic_effects import egg_upgraded, on_add_card

        if not upgraded and egg_upgraded(self, card):
            upgraded = True
        self.deck.append(DeckCard(card, upgraded))
        on_add_card(self, card, upgraded)

    def remove_card(self, index: int) -> DeckCard:
        return self.deck.pop(index)

    def upgrade_card(self, index: int) -> bool:
        dc = self.deck[index]
        if dc.upgraded:
            return False
        self.deck[index] = DeckCard(dc.card, True)
        return True

    def upgradable_indices(self) -> list[int]:
        return [i for i, dc in enumerate(self.deck) if not dc.upgraded]

    def purgable_indices(self) -> list[int]:
        """可净化（删除）牌：排除不可移除类（AscendersBane 等特殊诅咒本范围无）。"""
        return list(range(len(self.deck)))

    def has_curse(self) -> bool:
        return any(getattr(dc.card, "ctype", "") == "Curse" for dc in self.deck)

    # ---- 药水 ----

    def free_potion_slot(self) -> int | None:
        for i, p in enumerate(self.potions):
            if p is None:
                return i
        return None

    def obtain_potion(self, potion: PotionDef) -> int | None:
        """放入空槽；满槽返回 None（弃瓶决策由 run 循环的策略做）。"""
        slot = self.free_potion_slot()
        if slot is None:
            return None
        self.potions[slot] = potion
        return slot

    # ---- 快照/回滚（DESIGN.md §8.5：搜索的最低需求）----

    def clone(self) -> RunState:
        other = RunState.__new__(RunState)
        other.__dict__.update(self.__dict__)
        other.deck = list(self.deck)
        other.relics = list(self.relics)
        other.relic_counters = dict(self.relic_counters)
        other.potions = list(self.potions)
        other.event_pool = list(self.event_pool)
        other.shrine_pool = list(self.shrine_pool)
        other.onetime_pool = list(self.onetime_pool)
        other.monster_list = list(self.monster_list)
        other.elite_list = list(self.elite_list)
        other.event_scratch = {k: dict(v) for k, v in self.event_scratch.items()}
        return other

    def restore(self, other: RunState) -> None:
        self.__dict__.update(other.__dict__)

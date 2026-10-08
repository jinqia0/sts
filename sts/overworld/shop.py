"""商店库存与购买（Phase 3a，2026-10-08）。

对齐本体 Merchant.java / ShopScreen.java：
- 彩色卡 5 张：2 攻击 + 2 技能 + 1 能力（稀有度 shop 阈值 roll + 类型过滤；
  第 2 张攻击/技能与第 1 张不同 cardID）；无色 2 张（uncommon + rare）
- 价格：卡 base（common 50 / uncommon 75 / rare 150）× merchantRng
  uniform(0.9, 1.1)；无色槽再 ×1.2；5 张彩色卡中 1 张（merchantRng(0,4)）
  半价
- 遗物 3 槽：槽 0-1 tier roll（merchantRng <48 common / >82 rare，其间
  uncommon），槽 2 恒 shop 池；**尾取**（returnEndRandomRelic）；价格
  base（150/250/300）× uniform(0.95, 1.05)
- 药水 3 瓶（potionRng 稀有度 65/25/10 拒绝采样）；价格（50/75/100）×
  uniform(0.95, 1.05)
- 删牌：75 + 25×已用次数；SmilingMask 恒 50；Courier/Membership 折扣
  乘算（round）
- 折扣（购买时乘算，round）：MembershipCard ×0.5、DiscerningMonocle ×0.8、
  TheCourier ×0.8（叠乘）
- Courier 补货：卡/遗物/药水卖出后补新随机项、重 roll 价格（分布级近似：
  新价 = base × uniform(0.95, 1.05)）

A16 全场 ×1.1 不实现（A0）。
"""

from __future__ import annotations

from dataclasses import dataclass

from sts.combat.relics import RelicId
from sts.content.cards import CardDef
from sts.content.potions import PotionDef
from sts.overworld.card_rewards import roll_colorless_card, roll_shop_card
from sts.overworld.relic_effects import purge_price, shop_price_multiplier, shop_restocks
from sts.overworld.relic_pools import RelicPools
from sts.overworld.rng import OverworldRngStreams
from sts.overworld.state import RunState

CARD_BASE_PRICE = {"common": 50, "uncommon": 75, "rare": 150}  # AbstractCard.java:1900-1922
RELIC_BASE_PRICE = {"common": 150, "uncommon": 250, "rare": 300, "shop": 150}  # AbstractRelic.java:161-187
POTION_BASE_PRICE = {"common": 50, "uncommon": 75, "rare": 100}  # AbstractPotion.java:372-385
COLORLESS_MARKUP = 1.2
_SHOP_TIER_COMMON = 48  # merchantRng roll < 48 common（ShopScreen.java:403-413）
_SHOP_TIER_RARE = 82  # > 82 rare


def _card_price_base(card: CardDef) -> int:
    from sts.content.events import card_wiki_rarity

    return CARD_BASE_PRICE.get(card_wiki_rarity(card), 75)


@dataclass
class ShopCard:
    card: CardDef
    price: int
    on_sale: bool = False
    colorless: bool = False


@dataclass
class ShopRelic:
    relic: RelicId
    price: int


@dataclass
class ShopPotion:
    potion: PotionDef
    price: int


@dataclass
class ShopStock:
    cards: list[ShopCard]
    relics: list[ShopRelic]
    potions: list[ShopPotion]

    def purge_cost(self, state: RunState) -> int:
        return purge_price(state)


def _roll_price(rngs: OverworldRngStreams, base: float, lo: float, hi: float) -> int:
    return int(round(base * rngs.merchant.gen.uniform(lo, hi)))


def generate_stock(state: RunState, rngs: OverworldRngStreams, pools: RelicPools) -> ShopStock:
    # ---- 彩色卡 5 + 无色 2（Merchant.java:52-92）----
    colored: list[CardDef] = []
    for ctype, slot2_dedup in (("Attack", False), ("Attack", True), ("Skill", False), ("Skill", True), ("Power", False)):
        exclude = {colored[-1].name} if (slot2_dedup and colored) else None
        card = roll_shop_card(rngs, state, ctype, exclude=exclude)
        assert card is not None, f"商店卡槽生成失败：{ctype}"
        colored.append(card)
    colorless = [roll_colorless_card(rngs, "uncommon"), roll_colorless_card(rngs, "rare")]

    cards: list[ShopCard] = [
        ShopCard(card=c, price=_roll_price(rngs, _card_price_base(c), 0.9, 1.1)) for c in colored
    ] + [
        ShopCard(card=c, price=_roll_price(rngs, _card_price_base(c) * COLORLESS_MARKUP, 0.9, 1.1), colorless=True)
        for c in colorless
    ]
    # 打折卡：5 张彩色中 1 张半价（merchantRng(0,4)，ShopScreen.java:258）
    sale_idx = rngs.merchant.int_inclusive(0, 4)
    cards[sale_idx].price //= 2
    cards[sale_idx].on_sale = True

    # ---- 遗物 3 槽（ShopScreen.java:345-357；尾取）----
    relics: list[ShopRelic] = []
    for slot in range(3):
        if slot == 2:
            tier = "shop"
        else:
            roll = rngs.merchant.int_inclusive(0, 99)
            tier = "common" if roll < _SHOP_TIER_COMMON else ("rare" if roll > _SHOP_TIER_RARE else "uncommon")
        relic = pools.take_shop(tier, state)
        base = RELIC_BASE_PRICE.get(tier if slot == 2 else tier, 150)
        relics.append(ShopRelic(relic=relic, price=_roll_price(rngs, base, 0.95, 1.05)))

    # ---- 药水 3 瓶（稀有度 65/25/10 拒绝采样，potion 流）----
    from sts.overworld.drops import random_potion_by_rarity

    potions = [
        ShopPotion(potion=random_potion_by_rarity(rngs), price=0) for _ in range(3)
    ]
    for sp in potions:
        sp.price = _roll_price(rngs, POTION_BASE_PRICE.get(sp.potion.rarity, 50), 0.95, 1.05)

    return ShopStock(cards=cards, relics=relics, potions=potions)


def discounted(price: int, state: RunState) -> int:
    """遗物折扣乘算（round；卡/遗物/药水购买价）。"""
    return int(round(price * shop_price_multiplier(state)))


def restock(state: RunState, rngs: OverworldRngStreams, pools: RelicPools, stock: ShopStock, kind: str, index: int) -> None:
    """Courier 补货：卖出位补新随机项（分布级：新价重 roll）。"""
    if not shop_restocks(state):
        return
    if kind == "card":
        slot = stock.cards[index]
        if slot.colorless:
            rarity = "uncommon" if index == 5 else "rare"
            new_card = roll_colorless_card(rngs, rarity)
        else:
            ctype = ("Attack", "Attack", "Skill", "Skill", "Power")[index]
            new_card = roll_shop_card(rngs, state, ctype)
        slot.card = new_card
        slot.price = _roll_price(rngs, _card_price_base(new_card) * (COLORLESS_MARKUP if slot.colorless else 1.0), 0.95, 1.05)
        slot.on_sale = False
    elif kind == "relic":
        slot = stock.relics[index]
        roll = rngs.merchant.int_inclusive(0, 99)
        tier = "shop" if index == 2 else ("common" if roll < _SHOP_TIER_COMMON else ("rare" if roll > _SHOP_TIER_RARE else "uncommon"))
        slot.relic = pools.take_shop(tier, state)
        slot.price = _roll_price(rngs, RELIC_BASE_PRICE.get(tier, 150), 0.95, 1.05)
    elif kind == "potion":
        from sts.overworld.drops import random_potion_by_rarity

        slot = stock.potions[index]
        slot.potion = random_potion_by_rarity(rngs)
        slot.price = _roll_price(rngs, POTION_BASE_PRICE.get(slot.potion.rarity, 50), 0.95, 1.05)

"""遗物池（Phase 3a，2026-10-08）——铁甲 A0 五池 + 头/尾取 + 降级链。

池构成 = shared + 红（RelicLibrary.populateRelicPool java:624-659，红桶注册
RelicLibrary.java:380-389；tier 取自遗物构造器 RelicTier.*）。铁甲池
排除其他职业桶（绿/蓝/紫）与 dev 遗物（Test*/Waffle）。

取物语义（AbstractDungeon.java，两个入口的怪癖照抄）：
- 头取（returnRandomRelicKey :737-788）——战斗/宝箱/Boss 宝箱掉落；
  降级链 COMMON→UNCOMMON→RARE→Circlet，SHOP→UNCOMMON，BOSS→RedCirclet
- 尾取（returnEndRandomRelicKey :684-735）——商店槽 0-2 与非篝火过滤；
  COMMON/UNCOMMON/RARE/SHOP 从池尾取，BOSS 仍从头取
- canSpawn 失败重试：本体递归 bug（重试走到尾取）——分布级近似为
  「跳过该项继续取」（Act 1 内 canSpawn 几乎恒真，仅商店槽排除与
  瓶装三件套卡组条件实际生效）

池构建时按本体用 relic 流洗 5 次（每次一个 randomLong 派生）——
分布级保真，不做调用对齐。掉落即出池（天然去重）。
"""

from __future__ import annotations

from sts.combat.relics import RelicId
from sts.overworld.relic_effects import CAMPFIRE_RELICS
from sts.overworld.state import RunState
from sts.rng import Rng

# ---- 铁甲（shared + 红）五池，tier 自构造器提取 ----

COMMON_POOL: list[RelicId] = [
    RelicId.AKABEKO, RelicId.ANCHOR, RelicId.ANCIENT_TEA_SET, RelicId.ART_OF_WAR,
    RelicId.BAG_OF_MARBLES, RelicId.BAG_OF_PREPARATION, RelicId.BLOOD_VIAL,
    RelicId.THE_BOOT, RelicId.BRONZE_SCALES, RelicId.CENTENNIAL_PUZZLE,
    RelicId.CERAMIC_FISH, RelicId.DREAM_CATCHER, RelicId.HAPPY_FLOWER,
    RelicId.JUZU_BRACELET, RelicId.LANTERN, RelicId.MAW_BANK, RelicId.MEAL_TICKET,
    RelicId.NUNCHAKU, RelicId.ODDLY_SMOOTH_STONE, RelicId.OMAMORI,
    RelicId.ORICHALCUM, RelicId.PEN_NIB, RelicId.POTION_BELT,
    RelicId.PRESERVED_INSECT, RelicId.RED_SKULL, RelicId.REGAL_PILLOW,
    RelicId.SMILING_MASK, RelicId.STRAWBERRY, RelicId.TINY_CHEST,
    RelicId.TOY_ORNITHOPTER, RelicId.VAJRA, RelicId.WAR_PAINT, RelicId.WHETSTONE,
]

UNCOMMON_POOL: list[RelicId] = [
    RelicId.BLUE_CANDLE, RelicId.BOTTLED_FLAME, RelicId.BOTTLED_LIGHTNING,
    RelicId.BOTTLED_TORNADO, RelicId.DARKSTONE_PERIAPT, RelicId.DISCERNING_MONOCLE,
    RelicId.ETERNAL_FEATHER, RelicId.FROZEN_EGG, RelicId.GREMLIN_HORN,
    RelicId.HORN_CLEAT, RelicId.INK_BOTTLE, RelicId.KUNAI, RelicId.LETTER_OPENER,
    RelicId.MATRYOSHKA, RelicId.MEAT_ON_THE_BONE, RelicId.MERCURY_HOURGLASS,
    RelicId.MOLTEN_EGG, RelicId.MUMMIFIED_HAND, RelicId.ORNAMENTAL_FAN,
    RelicId.PANTOGRAPH, RelicId.PAPER_FROG, RelicId.PEAR, RelicId.QUESTION_CARD,
    RelicId.SELF_FORMING_CLAY, RelicId.SHURIKEN, RelicId.SINGING_BOWL,
    RelicId.STRIKE_DUMMY, RelicId.SUNDIAL, RelicId.THE_COURIER,
    RelicId.TOXIC_EGG, RelicId.WHITE_BEAST_STATUE,
]

RARE_POOL: list[RelicId] = [
    RelicId.BIRD_FACED_URN, RelicId.CALIPERS, RelicId.CAPTAINS_WHEEL,
    RelicId.CHAMPION_BELT, RelicId.CHARONS_ASHES, RelicId.DEAD_BRANCH,
    RelicId.DU_VU_DOLL, RelicId.FOSSILIZED_HELIX, RelicId.GAMBLING_CHIP,
    RelicId.GINGER, RelicId.GIRYA, RelicId.ICE_CREAM, RelicId.INCENSE_BURNER,
    RelicId.LIZARD_TAIL, RelicId.MAGIC_FLOWER, RelicId.MANGO, RelicId.OLD_COIN,
    RelicId.PEACE_PIPE, RelicId.POCKETWATCH, RelicId.PRAYER_WHEEL,
    RelicId.SHOVEL, RelicId.STONE_CALENDAR, RelicId.THREAD_AND_NEEDLE,
    RelicId.TORII, RelicId.TUNGSTEN_ROD, RelicId.TURNIP, RelicId.UNCEASING_TOP,
    RelicId.WINGED_GREAVES,
]

SHOP_POOL: list[RelicId] = [
    RelicId.BRIMSTONE, RelicId.CAULDRON, RelicId.CHEMICAL_X,
    RelicId.CLOCKWORK_SOUVENIR, RelicId.DOLLYS_MIRROR, RelicId.FROZEN_EYE,
    RelicId.HAND_DRILL, RelicId.MEDICAL_KIT, RelicId.MEMBERSHIP_CARD,
    RelicId.ORRERY, RelicId.PRISMATIC_SHARD, RelicId.SLING_OF_COURAGE,
    RelicId.STRANGE_SPOON, RelicId.THE_ABACUS, RelicId.TOOLBOX,
]

BOSS_POOL: list[RelicId] = [
    RelicId.ASTROLABE, RelicId.BLACK_BLOOD, RelicId.BLACK_STAR,
    RelicId.BUSTED_CROWN, RelicId.CALLING_BELL, RelicId.COFFEE_DRIPPER,
    RelicId.CURSED_KEY, RelicId.ECTOPLASM, RelicId.EMPTY_CAGE,
    RelicId.FUSION_HAMMER, RelicId.MARK_OF_PAIN, RelicId.PANDORAS_BOX,
    RelicId.PHILOSOPHERS_STONE, RelicId.RUNIC_CUBE, RelicId.RUNIC_DOME,
    RelicId.RUNIC_PYRAMID, RelicId.SACRED_BARK, RelicId.SLAVERS_COLLAR,
    RelicId.SNECKO_EYE, RelicId.SOZU, RelicId.TINY_HOUSE, RelicId.VELVET_CHOKER,
]

# canSpawn 楼层上限（本体各遗物 canSpawn；Act 1 floor ≤ 16 均不触发，保留语义）
_FLOOR_CAPS: dict[RelicId, int] = {
    RelicId.PRESERVED_INSECT: 52,
    RelicId.MATRYOSHKA: 40,
    RelicId.WINGED_GREAVES: 40,
    RelicId.TINY_CHEST: 35,
    RelicId.GIRYA: 47,
    RelicId.SHOVEL: 47,
    RelicId.PEACE_PIPE: 47,
    RelicId.ANCIENT_TEA_SET: 48,
    RelicId.CERAMIC_FISH: 48,
    RelicId.DARKSTONE_PERIAPT: 48,
    RelicId.DREAM_CATCHER: 48,
    RelicId.FROZEN_EGG: 48,
    RelicId.JUZU_BRACELET: 48,
    RelicId.MEAL_TICKET: 48,
    RelicId.MAW_BANK: 48,
    RelicId.MEAT_ON_THE_BONE: 48,
    RelicId.MOLTEN_EGG: 48,
    RelicId.OMAMORI: 48,
    RelicId.POTION_BELT: 48,
    RelicId.PRAYER_WHEEL: 48,
    RelicId.QUESTION_CARD: 48,
    RelicId.REGAL_PILLOW: 48,
    RelicId.SINGING_BOWL: 48,
    RelicId.TOXIC_EGG: 48,
    RelicId.ECTOPLASM: 999,  # actNum ≤ 1（Act 1 恒真）
}

# canSpawn 商店房排除（不会出现在商店槽）：Courier / MawBank / OldCoin / SmilingMask
_SHOP_EXCLUDED = {
    RelicId.THE_COURIER,
    RelicId.MAW_BANK,
    RelicId.OLD_COIN,
    RelicId.SMILING_MASK,
}


def can_spawn(relic: RelicId, state: RunState, in_shop: bool = False) -> bool:
    """canSpawn 过滤（Act 1 内实际生效的只有商店排除/瓶装三件套/铲子营地计数）。"""
    cap = _FLOOR_CAPS.get(relic)
    if cap is not None and state.floor > cap:
        return False
    if in_shop and relic in _SHOP_EXCLUDED:
        return False
    if relic in (RelicId.BOTTLED_FLAME, RelicId.BOTTLED_LIGHTNING, RelicId.BOTTLED_TORNADO):
        ctype = {"BOTTLED_FLAME": "Attack", "BOTTLED_LIGHTNING": "Skill", "BOTTLED_TORNADO": "Power"}[relic.name]
        return any(getattr(dc.card, "ctype", "") == ctype for dc in state.deck)
    if relic == RelicId.SHOVEL:
        return sum(1 for r in CAMPFIRE_RELICS if state.has(r)) < 2
    return True


# 降级链（returnRandomRelicKey :737-788）
_DEGRADE = {
    "common": ("common", "uncommon", "rare"),
    "uncommon": ("uncommon", "rare"),
    "rare": ("rare",),
    "shop": ("shop", "uncommon"),
    "boss": ("boss",),
}


class RelicPools:
    """一局的五个可变遗物池（掉落即出池）。"""

    def __init__(self, rng: Rng):
        self.pools: dict[str, list[RelicId]] = {
            "common": list(COMMON_POOL),
            "uncommon": list(UNCOMMON_POOL),
            "rare": list(RARE_POOL),
            "shop": list(SHOP_POOL),
            "boss": list(BOSS_POOL),
        }
        # 本体：每池 new Random(relicRng.randomLong()) 洗牌（initializeRelicList）
        for pool in self.pools.values():
            rng.shuffle(pool)

    # ---- 取物 ----

    def take_drop(self, tier: str, state: RunState) -> RelicId:
        """头取（战斗/宝箱/Boss 宝箱掉落路径）。池空沿降级链，全空给兜底头环。"""
        for t in _DEGRADE[tier]:
            pool = self.pools[t]
            while pool:
                relic = pool.pop(0)  # 头取
                if can_spawn(relic, state):
                    return relic
        return RelicId.RED_CIRCLET if tier == "boss" else RelicId.CIRCLET

    def take_shop(self, tier: str, state: RunState) -> RelicId:
        """尾取（商店槽；本体 returnEndRandomRelicKey：BOSS 仍头取）。"""
        for t in _DEGRADE[tier]:
            pool = self.pools[t]
            while pool:
                relic = pool.pop() if t != "boss" else pool.pop(0)
                if can_spawn(relic, state, in_shop=True):
                    return relic
        return RelicId.CIRCLET

    def take_non_campfire(self, state: RunState) -> RelicId:
        """Black Star 第二遗物（排除 Peace Pipe / Shovel / Girya，头取随机 tier）。"""
        for pool_name in ("common", "uncommon", "rare"):
            pool = self.pools[pool_name]
            for i, relic in enumerate(pool):
                if relic not in CAMPFIRE_RELICS and can_spawn(relic, state):
                    pool.pop(i)
                    return relic
        return RelicId.CIRCLET

    def take_boss_chest(self, state: RunState) -> list[RelicId]:
        """Boss 宝箱三选一（头取 ×3，未选两件丢弃——本体即如此）。"""
        return [self.take_drop("boss", state) for _ in range(3)]

    def remove(self, relic: RelicId) -> None:
        for pool in self.pools.values():
            if relic in pool:
                pool.remove(relic)


def roll_tier(rng: Rng) -> str:
    """tier roll：<50 common / >82 rare / 其余 uncommon（各 Act 全 50/33/17）。"""
    roll = rng.int_inclusive(0, 99)
    if roll < 50:
        return "common"
    if roll > 82:
        return "rare"
    return "uncommon"

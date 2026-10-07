"""全量内容词表：观测编码的稳定 ID 层（批次 5a，2026-10-07 生成）。

由 scripts/gen_vocab.py 从内容层枚举生成，**手写改动无效**（会被
tests/test_vocab.py 锁测试与再生成覆盖）。内容层改动后重跑生成脚本。

- 卡牌：id = "模块:常量名"。CardDef.name 跨职业重名（4 个 Strike）且
  frozen dataclass 值相等（不同职业的同名 Strike 是值全同的不同对象），
  反查表按对象身份（id()）键。枚举序：中立模块（status/curses/colorless）
  在前——职业模块 re-export 的状态卡（BURN/DAZED/WOUND/VOID）归属定义
  模块；同一对象跨模块只计一次。共 368 个唯一定义 × 2 = 736 维
  （基础版 = 2k、升级版 = 2k+1——升级是性能不同的牌，四堆计数必须
  分维，DESIGN.md §5.2）。
- 怪物：display name 唯一键，68 种，词表 72 留追加余量。
- 药水：pid 唯一键，42 种，词表 48 留追加余量。
- 遗物：RelicId 本身是稳定 IntEnum（0..128），直接用 value，无需词表。
- 职业：CHARACTERS + CHARACTER_MAX_HP（引擎 Player(80) 固定，非铁甲职业
  构造后修正——与 webapp 同款近似）。
"""

from __future__ import annotations

from sts.content.cards import CardDef
from sts.content.potions import PotionDef
from sts.content.cards import colorless as cards_colorless
from sts.content.cards import curses as cards_curses
from sts.content.cards import defect as cards_defect
from sts.content.cards import ironclad as cards_ironclad
from sts.content.cards import silent as cards_silent
from sts.content.cards import status as cards_status
from sts.content.cards import watcher as cards_watcher

# ---- 卡牌 ----
CARD_MODULES = [
    ("status", cards_status),
    ("curses", cards_curses),
    ("colorless", cards_colorless),
    ("ironclad", cards_ironclad),
    ("silent", cards_silent),
    ("defect", cards_defect),
    ("watcher", cards_watcher),
]
CARD_MODULE_ORDER = ('status', 'curses', 'colorless', 'ironclad', 'silent', 'defect', 'watcher')

CARD_VOCAB: list[str] = [
    "status:WOUND", "status:SLIMED", "status:DAZED", "status:BURN",
    "status:VOID", "curses:REGRET", "curses:INJURY", "curses:SHAME",
    "curses:PARASITE", "curses:NORMALITY", "curses:DOUBT", "curses:WRITHE",
    "curses:PAIN", "curses:DECAY", "curses:CLUMSY", "curses:PRIDE",
    "curses:ASCENDERS_BANE", "curses:CURSE_OF_THE_BELL", "curses:NECRONOMICURSE", "colorless:BANDAGE_UP",
    "colorless:BLIND", "colorless:DARK_SHACKLES", "colorless:DEEP_BREATH", "colorless:DISCOVERY",
    "colorless:DRAMATIC_ENTRANCE", "colorless:ENLIGHTENMENT", "colorless:FINESSE", "colorless:FLASH_OF_STEEL",
    "colorless:FORETHOUGHT", "colorless:GOOD_INSTINCTS", "colorless:IMPATIENCE", "colorless:JACK_OF_ALL_TRADES",
    "colorless:MADNESS", "colorless:MIND_BLAST", "colorless:PANACEA", "colorless:PANIC_BUTTON",
    "colorless:PURITY", "colorless:SWIFT_STRIKE", "colorless:TRIP", "colorless:APOTHEOSIS",
    "colorless:CHRYSALIS", "colorless:MAGNETISM", "colorless:MASTER_OF_STRATEGY", "colorless:MAYHEM",
    "colorless:METAMORPHOSIS", "colorless:PANACHE", "colorless:SADISTIC_NATURE", "colorless:SECRET_TECHNIQUE",
    "colorless:SECRET_WEAPON", "colorless:THE_BOMB", "colorless:THINKING_AHEAD", "colorless:TRANSMUTATION",
    "colorless:VIOLENCE", "colorless:HAND_OF_GREED", "colorless:APPARITION", "colorless:BITE",
    "colorless:JAX", "colorless:RITUAL_DAGGER", "ironclad:STRIKE", "ironclad:DEFEND",
    "ironclad:BASH", "ironclad:ANGER", "ironclad:ARMAMENTS", "ironclad:BODY_SLAM",
    "ironclad:CLASH", "ironclad:CLEAVE", "ironclad:CLOTHESLINE", "ironclad:FLEX",
    "ironclad:HAVOC", "ironclad:HEADBUTT", "ironclad:HEAVY_BLADE", "ironclad:IRON_WAVE",
    "ironclad:PERFECTED_STRIKE", "ironclad:POMMEL_STRIKE", "ironclad:SHRUG_IT_OFF", "ironclad:SWORD_BOOMERANG",
    "ironclad:THUNDERCLAP", "ironclad:TRUE_GRIT", "ironclad:TWIN_STRIKE", "ironclad:WARCRY",
    "ironclad:WILD_STRIKE", "ironclad:BATTLE_TRANCE", "ironclad:BLOOD_FOR_BLOOD", "ironclad:BLOODLETTING",
    "ironclad:BURNING_PACT", "ironclad:CARNAGE", "ironclad:COMBUST", "ironclad:DARK_EMBRACE",
    "ironclad:DISARM", "ironclad:DROPKICK", "ironclad:DUAL_WIELD", "ironclad:ENTRENCH",
    "ironclad:EVOLVE", "ironclad:FEEL_NO_PAIN", "ironclad:FIRE_BREATHING", "ironclad:FLAME_BARRIER",
    "ironclad:GHOSTLY_ARMOR", "ironclad:HEMOKINESIS", "ironclad:INFERNAL_BLADE", "ironclad:INFLAME",
    "ironclad:INTIMIDATE", "ironclad:METALLICIZE", "ironclad:POWER_THROUGH", "ironclad:PUMMEL",
    "ironclad:RAMPAGE", "ironclad:RECKLESS_CHARGE", "ironclad:RUPTURE", "ironclad:SEARING_BLOW",
    "ironclad:SECOND_WIND", "ironclad:SEEING_RED", "ironclad:SENTINEL", "ironclad:SEVER_SOUL",
    "ironclad:SHOCKWAVE", "ironclad:SPOT_WEAKNESS", "ironclad:UPPERCUT", "ironclad:WHIRLWIND",
    "ironclad:BARRICADE", "ironclad:BERSERK", "ironclad:BLUDGEON", "ironclad:BRUTALITY",
    "ironclad:CORRUPTION", "ironclad:DEMON_FORM", "ironclad:DOUBLE_TAP", "ironclad:EXHUME",
    "ironclad:FEED", "ironclad:FIEND_FIRE", "ironclad:IMMOLATE", "ironclad:IMPERVIOUS",
    "ironclad:JUGGERNAUT", "ironclad:LIMIT_BREAK", "ironclad:OFFERING", "ironclad:REAPER",
    "ironclad:RAGE", "silent:STRIKE_S", "silent:DEFEND_S", "silent:NEUTRALIZE",
    "silent:SURVIVOR", "silent:SHIV", "silent:ACROBATICS", "silent:BACKFLIP",
    "silent:BANE", "silent:BLADE_DANCE", "silent:CLOAK_AND_DAGGER", "silent:DAGGER_SPRAY",
    "silent:DAGGER_THROW", "silent:DEADLY_POISON", "silent:DEFLECT", "silent:DODGE_AND_ROLL",
    "silent:FLYING_KNEE", "silent:OUTMANEUVER", "silent:PIERCING_WAIL", "silent:POISONED_STAB",
    "silent:PREPARED", "silent:QUICK_SLASH", "silent:SLICE", "silent:SNEAKY_STRIKE",
    "silent:SUCKER_PUNCH", "silent:ACCURACY", "silent:ALL_OUT_ATTACK", "silent:BACKSTAB",
    "silent:BLUR", "silent:BOUNCING_FLASK", "silent:CALCULATED_GAMBLE", "silent:CALTROPS",
    "silent:CATALYST", "silent:CHOKE", "silent:CONCENTRATE", "silent:CRIPPLING_CLOUD",
    "silent:DASH", "silent:DISTRACTION", "silent:ENDLESS_AGONY", "silent:ESCAPE_PLAN",
    "silent:EVISCERATE", "silent:EXPERTISE", "silent:FINISHER", "silent:FLECHETTES",
    "silent:FOOTWORK", "silent:HEEL_HOOK", "silent:INFINITE_BLADES", "silent:LEG_SWEEP",
    "silent:MASTERFUL_STAB", "silent:NOXIOUS_FUMES", "silent:PREDATOR", "silent:REFLEX",
    "silent:RIDDLE_WITH_HOLES", "silent:SETUP", "silent:SKEWER", "silent:TACTICIAN",
    "silent:TERROR", "silent:WELL_LAID_PLANS", "silent:A_THOUSAND_CUTS", "silent:ADRENALINE",
    "silent:AFTER_IMAGE", "silent:BULLET_TIME", "silent:BURST", "silent:CORPSE_EXPLOSION",
    "silent:DIE_DIE_DIE", "silent:DOPPELGANGER", "silent:ENVENOM", "silent:GLASS_KNIFE",
    "silent:GRAND_FINALE", "silent:MALAISE", "silent:NIGHTMARE", "silent:PHANTASMAL_KILLER",
    "silent:STORM_OF_STEEL", "silent:TOOLS_OF_THE_TRADE", "silent:UNLOAD", "silent:WRAITH_FORM",
    "silent:VENOLOGY", "defect:STRIKE_D", "defect:DEFEND_D", "defect:ZAP",
    "defect:DUALCAST", "defect:BALL_LIGHTNING", "defect:BARRAGE", "defect:BEAM_CELL",
    "defect:CHARGE_BATTERY", "defect:CLAW", "defect:COLD_SNAP", "defect:COMPILE_DRIVER",
    "defect:COOLHEADED", "defect:GO_FOR_THE_EYES", "defect:HOLOGRAM", "defect:LEAP",
    "defect:REBOUND", "defect:RECURSION", "defect:STACK", "defect:STEAM_BARRIER",
    "defect:STREAMLINE", "defect:SWEEPING_BEAM", "defect:TURBO", "defect:AGGREGATE",
    "defect:AUTO_SHIELDS", "defect:BLIZZARD", "defect:BOOT_SEQUENCE", "defect:BULLSEYE",
    "defect:CAPACITOR", "defect:CHAOS", "defect:CHILL", "defect:CONSUME",
    "defect:DARKNESS", "defect:DEFRAGMENT", "defect:DOOM_AND_GLOOM", "defect:DOUBLE_ENERGY",
    "defect:EQUILIBRIUM", "defect:FTL", "defect:FORCE_FIELD", "defect:FUSION",
    "defect:GENETIC_ALGORITHM", "defect:GLACIER", "defect:HEATSINKS", "defect:HELLO_WORLD",
    "defect:LOOP", "defect:MELTER", "defect:OVERCLOCK", "defect:RECYCLE",
    "defect:REINFORCED_BODY", "defect:REPROGRAM", "defect:RIP_AND_TEAR", "defect:SCRAPE",
    "defect:SELF_REPAIR", "defect:SKIM", "defect:STATIC_DISCHARGE", "defect:STORM",
    "defect:SUNDER", "defect:TEMPEST", "defect:WHITE_NOISE", "defect:ALL_FOR_ONE",
    "defect:AMPLIFY", "defect:BIASED_COGNITION", "defect:BUFFER", "defect:CORE_SURGE",
    "defect:CREATIVE_AI", "defect:ECHO_FORM", "defect:ELECTRODYNAMICS", "defect:FISSION",
    "defect:HYPERBEAM", "defect:MACHINE_LEARNING", "defect:METEOR_STRIKE", "defect:MULTI_CAST",
    "defect:RAINBOW", "defect:REBOOT", "defect:SEEK", "defect:THUNDER_STRIKE",
    "watcher:STRIKE_W", "watcher:DEFEND_W", "watcher:ERUPTION", "watcher:VIGILANCE",
    "watcher:MIRACLE", "watcher:INSIGHT", "watcher:SAFETY", "watcher:SMITE",
    "watcher:THROUGH_VIOLENCE", "watcher:BETA", "watcher:OMEGA", "watcher:EXPUNGER",
    "watcher:BOWLING_BASH", "watcher:CONSECRATE", "watcher:CRESCENDO", "watcher:CRUSH_JOINTS",
    "watcher:CUT_THROUGH_FATE", "watcher:EMPTY_BODY", "watcher:EMPTY_FIST", "watcher:EVALUATE",
    "watcher:FLURRY_OF_BLOWS", "watcher:FLYING_SLEEVES", "watcher:FOLLOW_UP", "watcher:HALT",
    "watcher:JUST_LUCKY", "watcher:PRESSURE_POINTS", "watcher:PROSTRATE", "watcher:PROTECT",
    "watcher:SASH_WHIP", "watcher:THIRD_EYE", "watcher:TRANQUILITY", "watcher:BATTLE_HYMN",
    "watcher:CARVE_REALITY", "watcher:COLLECT", "watcher:CONCLUDE", "watcher:DECEIVE_REALITY",
    "watcher:EMPTY_MIND", "watcher:FASTING", "watcher:FEAR_NO_EVIL", "watcher:FOREIGN_INFLUENCE",
    "watcher:FORESIGHT", "watcher:INDIGNATION", "watcher:INNER_PEACE", "watcher:LIKE_WATER",
    "watcher:MEDITATE", "watcher:MENTAL_FORTRESS", "watcher:NIRVANA", "watcher:PERSEVERANCE",
    "watcher:PRAY", "watcher:REACH_HEAVEN", "watcher:RUSHDOWN", "watcher:SANCTITY",
    "watcher:SANDS_OF_TIME", "watcher:SIGNATURE_MOVE", "watcher:SIMMERING_FURY", "watcher:STUDY",
    "watcher:SWIVEL", "watcher:TALK_TO_THE_HAND", "watcher:TANTRUM", "watcher:WALLOP",
    "watcher:WAVE_OF_THE_HAND", "watcher:WEAVE", "watcher:WHEEL_KICK", "watcher:WINDMILL_STRIKE",
    "watcher:WORSHIP", "watcher:WREATH_OF_FLAME", "watcher:ALPHA", "watcher:BLASPHEMY",
    "watcher:BRILLIANCE", "watcher:CONJURE_BLADE", "watcher:DEUS_EX_MACHINA", "watcher:DEVA_FORM",
    "watcher:DEVOTION", "watcher:ESTABLISHMENT", "watcher:JUDGMENT", "watcher:LESSON_LEARNED",
    "watcher:MASTER_REALITY", "watcher:OMNISCIENCE", "watcher:RAGNAROK", "watcher:SCRAWL",
    "watcher:SPIRIT_SHIELD", "watcher:VAULT", "watcher:WISH", "watcher:UNRAVELING",
]
CARD_VOCAB_SIZE = 736  # (定义, 升级) 各占一位
# id → 基础版词表位（升级版 = 基础位 + 1）
CARD_INDEX: dict[str, int] = {cid: 2 * i for i, cid in enumerate(CARD_VOCAB)}

# CardDef 对象身份（id()）→ 卡牌 id。不能按值键：不同职业的同名 Strike
# 是值全同的不同对象（值哈希会撞）；模块级单例身份在进程内稳定
_CARD_ID_BY_DEF: dict[int, str] = {}

# ---- 怪物 ----
MONSTER_VOCAB_SIZE = 72
MONSTER_INDEX: dict[str, int] = {
    "Cultist": 0, "Jaw Worm": 1, "Louse": 2,
    "Red Louse": 3, "Green Louse": 4, "Acid Slime (S)": 5,
    "Spike Slime (S)": 6, "Fungi Beast": 7, "Acid Slime (M)": 8,
    "Spike Slime (M)": 9, "Blue Slaver": 10, "Red Slaver": 11,
    "Sneaky Gremlin": 12, "Fat Gremlin": 13, "Shield Gremlin": 14,
    "Gremlin Wizard": 15, "Sentry": 16, "Mad Gremlin": 17,
    "Gremlin Nob": 18, "Lagavulin": 19, "The Guardian": 20,
    "Hexaghost": 21, "Taskmaster": 22, "Acid Slime (L)": 23,
    "Spike Slime (L)": 24, "Slime Boss": 25, "Looter": 26,
    "Mugger": 27, "Slot Placeholder": 28, "Spheric Guardian": 29,
    "Chosen": 30, "Shelled Parasite": 31, "Byrd": 32,
    "Snake Plant": 33, "Snecko": 34, "Centurion": 35,
    "Mystic": 36, "Gremlin Leader": 37, "Book of Stabbing": 38,
    "Bronze Automaton": 39, "Bronze Orb": 40, "The Collector": 41,
    "Torch Head": 42, "The Champ": 43, "Darkling": 44,
    "Orb Walker": 45, "Repulsor": 46, "Exploder": 47,
    "Spiker": 48, "Spire Growth": 49, "Transient": 50,
    "The Maw": 51, "Writhing Mass": 52, "Giant Head": 53,
    "Nemesis": 54, "Reptomancer": 55, "Dagger": 56,
    "Awakened One": 57, "Time Eater": 58, "Deca": 59,
    "Donu": 60, "Spire Shield": 61, "Spire Spear": 62,
    "Corrupt Heart": 63, "Pointy": 64, "Romeo": 65,
    "Bear": 66, "Apology Slime": 67,
}

# ---- 药水 ----
POTION_VOCAB_SIZE = 48
POTION_INDEX: dict[str, int] = {
    "Block Potion": 0, "Dexterity Potion": 1, "Energy Potion": 2,
    "Explosive Potion": 3, "Fire Potion": 4, "Strength Potion": 5,
    "Swift Potion": 6, "Weak Potion": 7, "FearPotion": 8,
    "AttackPotion": 9, "SkillPotion": 10, "PowerPotion": 11,
    "ColorlessPotion": 12, "SteroidPotion": 13, "SpeedPotion": 14,
    "BlessingOfTheForge": 15, "Regen Potion": 16, "Ancient Potion": 17,
    "LiquidBronze": 18, "GamblersBrew": 19, "EssenceOfSteel": 20,
    "DuplicationPotion": 21, "DistilledChaos": 22, "LiquidMemories": 23,
    "CultistPotion": 24, "Fruit Juice": 25, "SneckoOil": 26,
    "FairyPotion": 27, "SmokeBomb": 28, "EntropicBrew": 29,
    "BloodPotion": 30, "ElixirPotion": 31, "HeartOfIron": 32,
    "Poison Potion": 33, "CunningPotion": 34, "GhostInAJar": 35,
    "FocusPotion": 36, "PotionOfCapacity": 37, "EssenceOfDarkness": 38,
    "BottledMiracle": 39, "StancePotion": 40, "Ambrosia": 41,
}

# ---- 职业 ----
CHARACTERS = ("ironclad", "silent", "defect", "watcher")
CHARACTER_MAX_HP = {"ironclad": 80, "silent": 70, "defect": 75, "watcher": 72}


def card_vocab_index(card) -> int | None:
    """CardDef → 基础版词表位；未收录返回 None（该维恒 0，不崩）。"""
    cid = _CARD_ID_BY_DEF.get(id(card))
    return None if cid is None else CARD_INDEX[cid]


def _build() -> None:
    """建立 CardDef 对象身份 → id 反查表（导入期执行一次，身份去重）。"""
    seen: set[int] = set()
    for modkey, mod in CARD_MODULES:
        for varname, obj in vars(mod).items():
            if varname.startswith("_") or not isinstance(obj, CardDef):
                continue
            if id(obj) in seen:
                continue
            seen.add(id(obj))
            _CARD_ID_BY_DEF[id(obj)] = f"{modkey}:{varname}"


_build()

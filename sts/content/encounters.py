"""遭遇装配：把牌组与敌人实例化进 BattleContext。

引擎层 BattleContext._init_content 调用本模块的 setup_encounter(bc)。
扩遭遇 = 注册新的 encounter 名 + 装配函数（多敌人战斗在此生成怪物组，
怪物按加入顺序 = 索引 = 行动顺序，HP 依次从 monster_hp 流抽样）。

已注册遭遇（A0）：
    cultist      邪教徒 ×1
    jaw_worm     颚虫 ×1
    louses       红虱 ×1 + 绿虱 ×1
    slimes_s     酸液史莱姆（小）×1 + 尖刺史莱姆（小）×1
    fungi_beast  真菌兽 ×1
    two_fungi_beasts   真菌兽 ×2
    three_louse        虱子 ×3（红绿按 misc 流逐只抽样）
    small_slimes       小史莱姆：1×S + 1×M（尖 S+酸 M / 酸 S+尖 M 二选一）
    exordium_wildlife  荒野生物：Fungi/Jaw Worm + 虱/M 史莱姆（misc 流组合）
    gremlin_gang       小鬼帮：从 8 槽 Gremlin 池无放回抽 4（批次 2 起）
    slavers            蓝奴役者 + 监工 + 红奴役者（批次 2 补中间位监工）
    three_sentries     哨卫 ×3（首招按 idx 奇偶分 Bolt/Beam）
    gremlin_nob        小鬼巨汉 ×1（精英）
    lagavulin          拉格维林 ×1（精英）
    guardian           守卫者 ×1（Boss）
    hexaghost          六火幽灵 ×1（Boss）
    large_slime        大史莱姆：酸 L / 尖 L 单怪（misc 布尔抽，批次 3）
    looter             窃贼 ×1（批次 3）
    exordium_thugs     荒野暴徒：弱野生动物 + 强人形（批次 3）
    lots_of_slimes     史莱姆群：尖 S×3 + 酸 S×2 随机排列（批次 3）

Act 2（批次 B，对照 MonsterEncounters.h 的 ACT2 池 + MonsterGroup.cpp
的生成组合，共 19 个——slavers 复用 Act 1 已注册的遭遇）：
    spheric_guardian   球形守卫 ×1（普通弱）
    chosen             被选者 ×1（普通弱）
    shell_parasite     甲壳寄生虫 ×1（普通弱）
    three_byrds        伯德鸟 ×3（普通弱）
    two_thieves        窃贼 + 抢劫犯（普通弱）
    chosen_and_byrds   伯德鸟 + 被选者（普通强）
    sentry_and_sphere  哨卫 + 球形守卫（普通强）
    cultist_and_chosen 邪教徒 + 被选者（普通强）
    three_cultist      邪教徒 ×3（普通强）
    shelled_parasite_and_fungi  甲壳寄生虫 + 真菌兽（普通强）
    snecko             蛇颈龙 ×1（普通强）
    snake_plant        蛇藤 ×1（普通强）
    centurion_and_healer  百夫长 + 秘术师（普通强）
    gremlin_leader     小鬼头目（精英；槽 1/2 随机小鬼 + 槽 3 首领）
    slavers            （Act 2 精英池成员，Act 1 批次 2 已注册）
    book_of_stabbing   刺击之书（精英）
    automaton          青铜自律机（Boss；槽 0/2 预留给青铜球）
    collector          收藏家（Boss；槽 0/1 预留给火把头）
    champ              勇士（Boss）

Act 3（批次 D，对照 MonsterEncounters.h 的 Act 3 池 + MonsterGroup.cpp
组合表；普通 10 + 精英 3 + Boss 3 = 16 个遭遇名）：
    three_darklings    暗裔幼体 ×3（普通弱；half_dead 组）
    orb_walker         奥术行走者 ×1（普通弱）
    three_shapes       尖刺体/排斥者/爆爆虫 池无放回抽 3（普通弱）
    spire_growth       尖塔生长体 ×1（普通强）
    transient          瞬变体 ×1（普通强）
    four_shapes        同 shapes 池抽 4（普通强）
    maw                巨口 ×1（普通强）
    sphere_and_two_shapes  尖刺体/排斥者 池随机 2 + 球形守卫（普通强）
    jaw_worm_horde     颚虫 ×3（力量 +3/格挡 +5 起步，跳过首回合特例）
    writhing_mass      扭结团块 ×1（普通强）
    giant_head         巨人头（精英）
    nemesis            复仇者（精英）
    reptomancer        爬行者法师（精英；槽 1/4 匕首 + 槽 0/3 占位）
    awakened_one       觉醒者（Boss；邪教徒 ×2 + 觉醒者，half_dead 组）
    time_eater         时间吞噬者（Boss）
    donu_and_deca      德卡 + 多努（Boss）

Act 4（批次 D）：
    shield_and_spear   尖塔之盾 + 尖塔之矛
    the_heart          腐化之心（最终 Boss）

组合抽样统一走 misc 流（对齐 lightspeed 的 miscRng 用途划分；
DESIGN.md §3 不做轨迹对齐，分布级等价即可）。
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from sts.combat.types import MonsterStatus
from sts.content.cards import starting_deck
from sts.content.monsters import (
    _HalfDeadMonsterGroup,
    _HORDE_PLACEHOLDER,
    ApologySlime,
    AcidSlimeL,
    AcidSlimeM,
    AcidSlimeS,
    Bear,
    AwakenedOne,
    BlueSlaver,
    BookOfStabbing,
    BronzeAutomaton,
    Byrd,
    Centurion,
    Chosen,
    CorruptHeart,
    Cultist,
    Dagger,
    Darkling,
    Deca,
    Donu,
    Exploder,
    FatGremlin,
    FungiBeast,
    GiantHead,
    GremlinLeader,
    GremlinNob,
    GREMLIN_POOL,
    GreenLouse,
    GremlinWizard,
    Hexaghost,
    JawWorm,
    Pointy,
    Romeo,
    Lagavulin,
    Looter,
    MadGremlin,
    Mugger,
    Mystic,
    Nemesis,
    OrbWalker,
    RedLouse,
    RedSlaver,
    Reptomancer,
    Repulsor,
    Sentry,
    ShelledParasite,
    ShieldGremlin,
    SlimeBoss,
    SneakyGremlin,
    Snecko,
    SnakePlant,
    Spiker,
    SpikeSlimeL,
    SpikeSlimeM,
    SpikeSlimeS,
    SpireGrowth,
    SpireShield,
    SpireSpear,
    SphericGuardian,
    Taskmaster,
    TheChamp,
    TheCollector,
    TheGuardian,
    TheMaw,
    TimeEater,
    Transient,
    WrithingMass,
    _SlotPlaceholder,
)

if TYPE_CHECKING:
    from sts.combat.battle import BattleContext
    from sts.combat.entities import Monster


def _add_starting_deck(bc: BattleContext) -> None:
    for card in starting_deck():
        bc.cards.create_deck_card_in_draw_pile(card)


def _spawn(bc: BattleContext, *monster_classes: type[Monster]) -> None:
    """按顺序生成怪物组（idx = 行动顺序），再装入玩家牌组。"""
    for idx, cls in enumerate(monster_classes):
        bc.monsters.add(cls.create(bc, idx))
    _add_starting_deck(bc)


def _setup_cultist(bc: BattleContext) -> None:
    _spawn(bc, Cultist)


def _setup_jaw_worm(bc: BattleContext) -> None:
    _spawn(bc, JawWorm)


def _setup_louses(bc: BattleContext) -> None:
    _spawn(bc, RedLouse, GreenLouse)


def _setup_slimes_s(bc: BattleContext) -> None:
    _spawn(bc, AcidSlimeS, SpikeSlimeS)


def _setup_fungi_beast(bc: BattleContext) -> None:
    _spawn(bc, FungiBeast)


# ---- 批次 1：含组合抽样的遭遇（misc 流，对齐 lightspeed MonsterGroup.cpp）----


def _misc_boolean(bc: BattleContext) -> bool:
    """misc 流 50/50 布尔（对齐 lightspeed miscRng.randomBoolean()）。"""
    return bc.rngs.misc.int_inclusive(0, 1) == 1


def _sample_without_replacement(bc: BattleContext, pool: list, n: int) -> list:
    """无放回抽 n 个（对齐 lightspeed 的 lastIdx 前移删法，misc 流）。

    C++ 逐个抽 pool[miscRng.random(lastIdx)] 后把尾部前移压缩；等价于
    抽中即删。gremlin_gang 自批次 2（Mad Gremlin 入池）起走此路径。
    """
    pool = list(pool)
    picked = []
    last = len(pool) - 1
    for _ in range(n):
        i = bc.rngs.misc.int_inclusive(0, last)
        picked.append(pool[i])
        del pool[i]
        last -= 1
    return picked


def _get_louse(bc: BattleContext) -> type[Monster]:
    """对齐 MonsterGroup::getLouse：misc 布尔选红/绿虱。"""
    return RedLouse if _misc_boolean(bc) else GreenLouse


def _setup_two_fungi_beasts(bc: BattleContext) -> None:
    _spawn(bc, FungiBeast, FungiBeast)


def _setup_three_louse(bc: BattleContext) -> None:
    _spawn(bc, _get_louse(bc), _get_louse(bc), _get_louse(bc))


def _setup_small_slimes(bc: BattleContext) -> None:
    # 对齐 MonsterGroup SMALL_SLIMES：二选一配对（尖 S+酸 M / 酸 S+尖 M）
    if _misc_boolean(bc):
        _spawn(bc, SpikeSlimeS, AcidSlimeM)
    else:
        _spawn(bc, AcidSlimeS, SpikeSlimeM)


def _setup_exordium_wildlife(bc: BattleContext) -> None:
    # 对齐 EXORDIUM_WILDLIFE = createStrongWildlife + createWeakWildlife。
    # 虚构候选怪的 HP roll 消耗（C++ temp 数组）不做——无轨迹对齐诉求。
    strong = [FungiBeast, JawWorm][bc.rngs.misc.int_inclusive(0, 1)]
    weak = [_get_louse(bc), SpikeSlimeM, AcidSlimeM][bc.rngs.misc.int_inclusive(0, 2)]
    _spawn(bc, strong, weak)


# Gremlin 池（对齐 C++ 8 槽：Mad×2、Sneaky×2、Fat×2、Shield、Wizard）。
# 批次 2 起 Mad Gremlin 入池，走 misc 无放回抽样；批次 B 起与
# gremlin_leader 遭遇及 Rally 召唤共用 monsters.GREMLIN_POOL。
_GREMLIN_POOL: list = GREMLIN_POOL


def _setup_gremlin_gang(bc: BattleContext) -> None:
    classes = _sample_without_replacement(bc, _GREMLIN_POOL, 4)
    _spawn(bc, *classes)


def _setup_slavers(bc: BattleContext) -> None:
    # 对齐 C++ SLAVERS 槽位顺序：Blue Slaver + Taskmaster + Red Slaver
    _spawn(bc, BlueSlaver, Taskmaster, RedSlaver)


# ---- 批次 2：精英 / Boss 遭遇（单怪）----


def _setup_gremlin_nob(bc: BattleContext) -> None:
    _spawn(bc, GremlinNob)


def _setup_lagavulin(bc: BattleContext) -> None:
    _spawn(bc, Lagavulin)


def _setup_guardian(bc: BattleContext) -> None:
    _spawn(bc, TheGuardian)


def _setup_hexaghost(bc: BattleContext) -> None:
    _spawn(bc, Hexaghost)


def _setup_three_sentries(bc: BattleContext) -> None:
    _spawn(bc, Sentry, Sentry, Sentry)


# ---- 批次 3：困难档遭遇（对齐 lightspeed MonsterGroup.cpp 组合表）----


def _get_slaver(bc: BattleContext) -> type[Monster]:
    """对齐 MonsterGroup::getSlaver：misc 布尔选红/蓝奴役者。"""
    return RedSlaver if _misc_boolean(bc) else BlueSlaver


def _setup_large_slime(bc: BattleContext) -> None:
    # 对齐 LARGE_SLIME：misc 布尔选酸/尖（大），单怪
    big = AcidSlimeL if _misc_boolean(bc) else SpikeSlimeL
    _spawn(bc, big)


def _setup_slime_boss(bc: BattleContext) -> None:
    _spawn(bc, SlimeBoss)


def _setup_looter(bc: BattleContext) -> None:
    _spawn(bc, Looter)


def _setup_blue_slaver(bc: BattleContext) -> None:
    # 对齐 BLUE_SLAVER（Act 1 强怪池：单只蓝奴役者，Exordium.java:120）
    _spawn(bc, BlueSlaver)


def _setup_red_slaver(bc: BattleContext) -> None:
    # 对齐 RED_SLAVER（Act 1 强怪池：单只红奴役者，Exordium.java:129）
    _spawn(bc, RedSlaver)


def _setup_exordium_thugs(bc: BattleContext) -> None:
    # 对齐 EXORDIUM_THUGS = createWeakWildlife + createStrongHumanoid：
    # 弱位三选一（虱（红绿 misc 布尔）/ 尖 M / 酸 M），
    # 强位三选一（邪教徒 / 红 or 蓝奴役者 / 窃贼）。
    # C++ 对 3 个候选 temp 各 consume 一次 HP roll——无轨迹对齐诉求，不复制。
    weak = [_get_louse(bc), SpikeSlimeM, AcidSlimeM][bc.rngs.misc.int_inclusive(0, 2)]
    strong = [Cultist, _get_slaver(bc), Looter][bc.rngs.misc.int_inclusive(0, 2)]
    _spawn(bc, weak, strong)


def _setup_lots_of_slimes(bc: BattleContext) -> None:
    # 对齐 LOTS_OF_SLIMES：{尖 S×3, 酸 S×2} 无放回全抽（随机排列，misc 流）
    pool = [SpikeSlimeS, SpikeSlimeS, SpikeSlimeS, AcidSlimeS, AcidSlimeS]
    _spawn(bc, *_sample_without_replacement(bc, pool, 5))


# ---- 批次 B：Act 2 遭遇（对照 MonsterEncounters.h ACT2 池 + MonsterGroup.cpp）----


def _setup_with_group(bc: BattleContext, monsters_list: list, alive_count: int) -> None:
    """直接装填怪物组（槽位含死亡占位的布局怪用）：跳过 add() 的存活数自增。"""
    group = bc.monsters
    group.monsters = monsters_list
    group.alive_count = alive_count
    _add_starting_deck(bc)


def _get_gremlin(bc: BattleContext) -> type[Monster]:
    """对齐 MonsterGroup::getGremlin：misc 流 8 槽抽 1。"""
    return GREMLIN_POOL[bc.rngs.misc.int_inclusive(0, 7)]


def _setup_spheric_guardian(bc: BattleContext) -> None:
    _spawn(bc, SphericGuardian)


def _setup_chosen(bc: BattleContext) -> None:
    _spawn(bc, Chosen)


def _setup_shell_parasite(bc: BattleContext) -> None:
    _spawn(bc, ShelledParasite)


def _setup_three_byrds(bc: BattleContext) -> None:
    _spawn(bc, Byrd, Byrd, Byrd)


def _setup_two_thieves(bc: BattleContext) -> None:
    # 对齐 TWO_THIEVES：Looter + Mugger（Act 2 数值版窃贼组合）
    _spawn(bc, Looter, Mugger)


def _setup_chosen_and_byrds(bc: BattleContext) -> None:
    _spawn(bc, Byrd, Chosen)


def _setup_sentry_and_sphere(bc: BattleContext) -> None:
    _spawn(bc, Sentry, SphericGuardian)


def _setup_cultist_and_chosen(bc: BattleContext) -> None:
    _spawn(bc, Cultist, Chosen)


def _setup_three_cultist(bc: BattleContext) -> None:
    _spawn(bc, Cultist, Cultist, Cultist)


def _setup_shelled_parasite_and_fungi(bc: BattleContext) -> None:
    _spawn(bc, ShelledParasite, FungiBeast)


def _setup_snecko(bc: BattleContext) -> None:
    _spawn(bc, Snecko)


def _setup_snake_plant(bc: BattleContext) -> None:
    _spawn(bc, SnakePlant)


def _setup_centurion_and_healer(bc: BattleContext) -> None:
    # 对齐 CENTURION_AND_HEALER：百夫长（槽 0）+ 秘术师（槽 1）
    _spawn(bc, Centurion, Mystic)


def _setup_gremlin_leader(bc: BattleContext) -> None:
    # 对齐 C++ GREMLIN_LEADER：槽 1/2 = getGremlin 随机小鬼（带 MINION），
    # 槽 3 = 首领（create 内加 MINION_LEADER），槽 0 死亡占位（Rally 召唤
    # 的目标槽）。HP roll 顺序同 C++：小鬼 ×2 → 首领。
    gremlins = []
    for slot in (1, 2):
        m = _get_gremlin(bc).create(bc, slot)
        m.statuses.add(MonsterStatus.MINION, 1)
        gremlins.append(m)
    leader = GremlinLeader.create(bc, 3)
    _setup_with_group(bc, [_SlotPlaceholder(0), gremlins[0], gremlins[1], leader], 3)


def _setup_book_of_stabbing(bc: BattleContext) -> None:
    _spawn(bc, BookOfStabbing)


def _setup_automaton(bc: BattleContext) -> None:
    # 对齐 C++ AUTOMATON：自律机在槽 1，槽 0/2 死亡占位
    #（首回合 Spawn Orbs 原位覆写生成青铜球）
    automaton = BronzeAutomaton.create(bc, 1)
    _setup_with_group(bc, [_SlotPlaceholder(0), automaton, _SlotPlaceholder(2)], 1)


def _setup_collector(bc: BattleContext) -> None:
    # 对齐 C++ COLLECTOR：收藏家在槽 2，槽 0/1 死亡占位
    #（首回合 Spawn 补满两只火把头）
    collector = TheCollector.create(bc, 2)
    _setup_with_group(bc, [_SlotPlaceholder(0), _SlotPlaceholder(1), collector], 1)


def _setup_champ(bc: BattleContext) -> None:
    _spawn(bc, TheChamp)


# ---- 批次 D：Act 3 / Act 4 遭遇（对照 MonsterEncounters.h + MonsterGroup.cpp）----


# shapes 池（对齐 MonsterGroup::createShapes：Repulsor×2、Exploder×2、
# Spiker×2，无放回抽样）
_SHAPE_POOL: list = [Repulsor, Repulsor, Exploder, Exploder, Spiker, Spiker]


def _get_ancient_shape(bc: BattleContext) -> type[Monster]:
    """对齐 MonsterGroup::getAncientShape：{Spiker, Repulsor, Exploder} 抽 1。"""
    return [Spiker, Repulsor, Exploder][bc.rngs.misc.int_inclusive(0, 2)]


def _setup_with_half_dead_group(bc: BattleContext, *monster_classes: type[Monster]) -> None:
    """half_dead 怪参与回合的组（Darkling/Awakened One）：替换 bc.monsters
    为 _HalfDeadMonsterGroup（do_monster_turn 对 half_dead 也调 take_turn，
    对齐 MonsterGroup.cpp:571-589），再按序生成。"""
    bc.monsters = _HalfDeadMonsterGroup()
    for idx, cls in enumerate(monster_classes):
        bc.monsters.add(cls.create(bc, idx))
    _add_starting_deck(bc)


def _setup_three_darklings(bc: BattleContext) -> None:
    # 对齐 THREE_DARKLINGS：暗裔幼体 ×3（C++ 顺序构造，HP 依序 roll）
    _setup_with_half_dead_group(bc, Darkling, Darkling, Darkling)


def _setup_orb_walker(bc: BattleContext) -> None:
    _spawn(bc, OrbWalker)


def _setup_three_shapes(bc: BattleContext) -> None:
    _spawn(bc, *_sample_without_replacement(bc, _SHAPE_POOL, 3))


def _setup_four_shapes(bc: BattleContext) -> None:
    _spawn(bc, *_sample_without_replacement(bc, _SHAPE_POOL, 4))


def _setup_spire_growth(bc: BattleContext) -> None:
    _spawn(bc, SpireGrowth)


def _setup_transient(bc: BattleContext) -> None:
    _spawn(bc, Transient)


def _setup_maw(bc: BattleContext) -> None:
    _spawn(bc, TheMaw)


def _setup_sphere_and_two_shapes(bc: BattleContext) -> None:
    # 对齐 SPHERE_AND_TWO_SHAPES：古老形状 ×2（各自独立抽样）+ 球形守卫
    _spawn(bc, _get_ancient_shape(bc), _get_ancient_shape(bc), SphericGuardian)


def _setup_jaw_worm_horde(bc: BattleContext) -> None:
    # 对齐 JAW_WORM_HORDE：颚虫 ×3 + 力量/格挡加成 + 非 INVALID 占位
    # 意图（跳过"首回合固定 Chomp"，此后走 roll 分段）
    _spawn(bc, JawWorm, JawWorm, JawWorm)
    # 本体 JawWorm.java 硬化变体 preBattle：力量 = bellowStr（3/4/5），
    # 格挡 = bellowBlock（6，A17 起 9——A0 与 A2 均为 6；lightspeed 误译
    # 三档 5/6/9，wiki 记 Block 6 (A17:9)，已修）
    str_buff = 5 if bc.ascension >= 17 else 4 if bc.ascension >= 2 else 3
    block_buff = 9 if bc.ascension >= 17 else 6
    for m in bc.monsters.monsters:
        m.statuses.add(MonsterStatus.STRENGTH, str_buff)
        m.block += block_buff
        m.set_move(_HORDE_PLACEHOLDER)


def _setup_writhing_mass(bc: BattleContext) -> None:
    _spawn(bc, WrithingMass)


def _setup_giant_head(bc: BattleContext) -> None:
    _spawn(bc, GiantHead)


def _setup_nemesis(bc: BattleContext) -> None:
    _spawn(bc, Nemesis)


def _setup_reptomancer(bc: BattleContext) -> None:
    # 对齐 C++ REPTOMANCER 布局：槽 1/4 各 1 只匕首、槽 2 首领、
    # 槽 0/3 死亡占位（召唤目标槽）。HP roll 顺序：匕首 → 首领 → 匕首。
    d1 = Dagger.create(bc, 1)
    repto = Reptomancer.create(bc, 2)
    d2 = Dagger.create(bc, 4)
    _setup_with_group(bc, [_SlotPlaceholder(0), d1, repto, _SlotPlaceholder(3), d2], 3)


def _setup_awakened_one(bc: BattleContext) -> None:
    # 对齐 AWAKENED_ONE：邪教徒 ×2 + 觉醒者（槽 2；half_dead 组）
    _setup_with_half_dead_group(bc, Cultist, Cultist, AwakenedOne)


def _setup_time_eater(bc: BattleContext) -> None:
    _spawn(bc, TimeEater)


def _setup_donu_and_deca(bc: BattleContext) -> None:
    # 对齐 DONU_AND_DECA：德卡（槽 0）+ 多努（槽 1）
    _spawn(bc, Deca, Donu)


def _setup_shield_and_spear(bc: BattleContext) -> None:
    # 对齐 SHIELD_AND_SPEAR：尖塔之盾（槽 0）+ 尖塔之矛（槽 1）
    _spawn(bc, SpireShield, SpireSpear)


def _setup_the_heart(bc: BattleContext) -> None:
    _spawn(bc, CorruptHeart)


# ---- 事件战斗遭遇（档 1：事件审计报告——战斗组件已齐备的事件形态；
# 事件后奖励（金币/遗物/卡）属局外层，单战框架不模拟）----


def _setup_mushrooms_event(bc: BattleContext) -> None:
    """Mushrooms 事件：3×真菌兽（事件审计档 1）。"""
    _spawn(bc, FungiBeast, FungiBeast, FungiBeast)


def _setup_dead_adventurer(bc: BattleContext) -> None:
    """Dead Adventurer 事件：三选一精英战（拉格维林/小鬼巨汉/三哨卫）。

    拉格维林为事件变体（本体 getMonster() 返回 "Lagavulin Event" →
    new Lagavulin(false)）：不沉睡、无金属化，开局直接汲取灵魂。
    """
    roll = bc.rngs.misc.int_inclusive(0, 2)
    if roll == 0:
        bc.monsters.add(Lagavulin.create_event(bc, 0))
        _add_starting_deck(bc)
    elif roll == 1:
        _spawn(bc, GremlinNob)
    else:
        _spawn(bc, Sentry, Sentry, Sentry)


def _setup_colosseum_slavers(bc: BattleContext) -> None:
    """Colosseum 事件第一战：蓝+红奴役者（原版两连战，单战框架拆开注册）。"""
    _spawn(bc, BlueSlaver, RedSlaver)


def _setup_colosseum_nobs(bc: BattleContext) -> None:
    """Colosseum 事件第二战：监工+小鬼巨汉（COLOSSEUM_EVENT_NOBS）。"""
    _spawn(bc, Taskmaster, GremlinNob)


def _setup_mysterious_sphere(bc: BattleContext) -> None:
    """Mysterious Sphere 事件：2×奥术行走者。"""
    _spawn(bc, OrbWalker, OrbWalker)


def _setup_masked_bandits(bc: BattleContext) -> None:
    """Masked Bandits 事件：红面具帮（尖刺+罗密欧+大熊）。"""
    _spawn(bc, Pointy, Romeo, Bear)

def _setup_apology_slime(bc: BattleContext) -> None:
    """兜底怪遭遇（本体 MonsterHelper default 分支）：正常遭遇表不引用，
    仅供覆盖测试/调试。"""
    _spawn(bc, ApologySlime)


def _setup_mindbloom_boss(bc: BattleContext) -> None:
    """Mindbloom 事件：随机 Act 1 Boss（本体 shuffle 三选一）。"""
    roll = bc.rngs.misc.int_inclusive(0, 2)
    if roll == 0:
        _spawn(bc, TheGuardian)
    elif roll == 1:
        _spawn(bc, Hexaghost)
    else:
        _spawn(bc, SlimeBoss)


ENCOUNTERS = {
    "cultist": _setup_cultist,
    "jaw_worm": _setup_jaw_worm,
    "louses": _setup_louses,
    "slimes_s": _setup_slimes_s,
    "fungi_beast": _setup_fungi_beast,
    "two_fungi_beasts": _setup_two_fungi_beasts,
    "three_louse": _setup_three_louse,
    "small_slimes": _setup_small_slimes,
    "exordium_wildlife": _setup_exordium_wildlife,
    "gremlin_gang": _setup_gremlin_gang,
    "slavers": _setup_slavers,
    "three_sentries": _setup_three_sentries,
    "gremlin_nob": _setup_gremlin_nob,
    "lagavulin": _setup_lagavulin,
    "guardian": _setup_guardian,
    "hexaghost": _setup_hexaghost,
    "large_slime": _setup_large_slime,
    "slime_boss": _setup_slime_boss,
    "looter": _setup_looter,
    "blue_slaver": _setup_blue_slaver,
    "red_slaver": _setup_red_slaver,
    "exordium_thugs": _setup_exordium_thugs,
    "lots_of_slimes": _setup_lots_of_slimes,
    # ---- Act 2（批次 B）----
    "spheric_guardian": _setup_spheric_guardian,
    "chosen": _setup_chosen,
    "shell_parasite": _setup_shell_parasite,
    "three_byrds": _setup_three_byrds,
    "two_thieves": _setup_two_thieves,
    "chosen_and_byrds": _setup_chosen_and_byrds,
    "sentry_and_sphere": _setup_sentry_and_sphere,
    "cultist_and_chosen": _setup_cultist_and_chosen,
    "three_cultist": _setup_three_cultist,
    "shelled_parasite_and_fungi": _setup_shelled_parasite_and_fungi,
    "snecko": _setup_snecko,
    "snake_plant": _setup_snake_plant,
    "centurion_and_healer": _setup_centurion_and_healer,
    "gremlin_leader": _setup_gremlin_leader,
    "book_of_stabbing": _setup_book_of_stabbing,
    "automaton": _setup_automaton,
    "collector": _setup_collector,
    "champ": _setup_champ,
    # ---- Act 3（批次 D）----
    "three_darklings": _setup_three_darklings,
    "orb_walker": _setup_orb_walker,
    "three_shapes": _setup_three_shapes,
    "spire_growth": _setup_spire_growth,
    "transient": _setup_transient,
    "four_shapes": _setup_four_shapes,
    "maw": _setup_maw,
    "sphere_and_two_shapes": _setup_sphere_and_two_shapes,
    "jaw_worm_horde": _setup_jaw_worm_horde,
    "writhing_mass": _setup_writhing_mass,
    "giant_head": _setup_giant_head,
    "nemesis": _setup_nemesis,
    "reptomancer": _setup_reptomancer,
    "awakened_one": _setup_awakened_one,
    "time_eater": _setup_time_eater,
    "donu_and_deca": _setup_donu_and_deca,
    # ---- Act 4（批次 D）----
    "shield_and_spear": _setup_shield_and_spear,
    "the_heart": _setup_the_heart,    "mushrooms_event": _setup_mushrooms_event,
    "dead_adventurer": _setup_dead_adventurer,
    "colosseum_slavers": _setup_colosseum_slavers,
    "colosseum_nobs": _setup_colosseum_nobs,
    "mysterious_sphere": _setup_mysterious_sphere,
    "masked_bandits": _setup_masked_bandits,
    "apology_slime": _setup_apology_slime,
    "mindbloom_boss": _setup_mindbloom_boss,

}


def setup_encounter(bc: BattleContext) -> None:
    if bc.encounter not in ENCOUNTERS:
        raise ValueError(f"未知遭遇：{bc.encounter}（可选：{sorted(ENCOUNTERS)}）")
    ENCOUNTERS[bc.encounter](bc)

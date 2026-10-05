"""遗物容器与战斗内钩子（对齐 lightspeed RelicContainer + BattleContext::initRelics）。

设计（对齐 lightspeed，Python 化）：
- RelicContainer = 保序 id 列表 + frozenset（O(1) has）+ 计数 dict
  （对齐 vector<RelicInstance> + relicBits 位图 + relic.data 计数器）。
- **没有通用钩子分发机制**：所有遗物效果是各钩子方法内的固定顺序
  if 查询（对齐 lightspeed 硬编码顺序——同 hook 多遗物按固定序结算，
  非获取顺序）。
- 战斗开始分三桶（对齐 initRelics）：即时效果（获取顺序）→ 抽牌前
  桶（影响抽牌数）→ 抽牌后桶（Bag of Marbles 等）。
- 需要 RNG 的遗物用 misc 流（DESIGN.md §3 不做轨迹对齐）。

本文件所有效果均标注 C++ 依据（文件:行号，sts_lightspeed/src/combat/ 下）。
批次 1（2026-10-05）已逐一核对：BattleContext.cpp initRelics(L80-458)/
exitBattle(L459-592)/onUseAttackCard(L1607)/onUseSkillCard(L1733)/
onUsePowerCard(L1821)/onUseStatusOrCurseCard(L1884)/onAfterUseCard(L1937)/
callEndTurnActions(L2032)/afterMonsterTurns(L2152)/isCardPlayAllowed(L709)/
onShuffle(L2795)/triggerAndMoveToExhaustPile(L2814)/calculateCardDamage(L2671)、
Player.cpp applyStartOfTurnRelics(L490)/applyStartOfTurnPostDrawRelics(L661)/
applyEndOfTurnPowers(L349)/hpWasLost(L276)/heal(L156)/attacked(L210)、
Monster.cpp die(L293-325)/attacked(L407)/damage(L466)。

回合数换算（lightspeed bc.turn 与本项目 bc.turn 差 1）：
lightspeed 战斗开始 turn=0（BattleContext.h:87），++turn 只发生在
afterMonsterTurns（BattleContext.cpp:2158）——第 N 个玩家回合期间
lightspeed turn == N-1；本项目 _start_player_turn 先 ++turn，第 N 个
玩家回合期间 turn == N。故 C++ `turn == k` → 本文件 `bc.turn == k+1`。

批次 3（RNG/卡池遗物）已核对：initRelics 的 ENCHIRIDION（L140-146）、
TOOLBOX（注册 L98 / 执行 L382 / Actions.cpp:988-998 ToolboxAction /
chooseDiscoveryCard L2995-3010）、WARPED_TONGS（注册 L118 / 首回合入队
L446-449 + Player.cpp:669-671 / Actions.cpp:940-960
UpgradeRandomCardAction）、MUMMIFIED_HAND（L1874-1876 →
mummifiedHandOnUsePower L2847-2873）、DEAD_BRANCH（L2823-2826）、
STRANGE_SPOON（L1985-1990，批次 1 已实现，批次 3 复核一致）；
卡池范围见 CardPools.h（CombatCardPool L177-187 / CombatTypeCardPool
L150-175 / CombatColorlessCardPool L189-198）与 Game.cpp:209-243、
canUpgrade（CardInstance.cpp:55-59）、moveToHandHelper（BattleContext.cpp:2531-2537）。
"""

from __future__ import annotations

from enum import IntEnum
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from sts.combat.battle import BattleContext
    from sts.combat.card_manager import CardInstance
    from sts.combat.entities import Monster

from sts.combat.actions import Actions
from sts.combat.card_manager import MAX_HAND_SIZE
from sts.combat.queue import Action, CardQueueItem
from sts.combat.types import MonsterStatus, PlayerStatus
from sts.content import cards as _content_cards
from sts.content.cards import _STRIKE_CARD_NAMES as _STRIKE_NAMES  # 打击牌族（isStrikeCard）
from sts.content.cards import CardDef, HAND_OF_GREED

# ---------------------------------------------------------------------------
# 房间类型注册（批次 1）：PRESERVED_INSECT / SLING_OF_COURAGE / PANTOGRAPH 等
# "精英/Boss 房生效"遗物需要房间信息。C++ 从 GameContext.curRoom 判定
#（BattleContext.cpp:311 room==Room::BOSS / :317 Room::ELITE / :341 Room::ELITE）；
# 本项目单场模拟无房间概念，按遭遇名注册：ELITE_ENCOUNTERS / BOSS_ENCOUNTERS。
# 当前五大遭遇（encounters.py）均为普通房，集合为空；场景层/测试按需注册。
ELITE_ENCOUNTERS: set[str] = set()
BOSS_ENCOUNTERS: set[str] = set()

# ---------------------------------------------------------------------------
# 随机卡池（批次 3）：ENCHIRIDION / TOOLBOX / DEAD_BRANCH 的抽样范围。
# 对齐 CardPools.h：CombatCardPool（L177-187，铁甲色 70 张，不含无色/
# 状态/诅咒）、CombatTypeCardPool（L150-175，按类型，Power 14 张）、
# CombatColorlessCardPool（L189-198，无色 34 张）。
# ---------------------------------------------------------------------------

# 无色牌集合。CardDef 无 color 字段（内容层裁剪），无法从模块扫描自动
# 识别，显式列举：目前内容层仅 Hand of Greed 一张无色卡（C++ 池 34 张）。
# 批次 4 扩无色池时把新卡加入此集合（DEAD_BRANCH 的铁甲色池据此排除）。
_COLORLESS_CARDS: frozenset[CardDef] = frozenset({HAND_OF_GREED})


def _combat_card_pool(ctype: str | None = None) -> list[CardDef]:
    """铁甲色随机卡池（对齐 getTrulyRandomCardInCombat，Game.cpp:215-219 /
    221-224：CombatCardPool / CombatTypeCardPool）。

    动态扫描 content.cards 模块级 CardDef：批次 4 新增卡自动入池。
    排除无色（_COLORLESS_CARDS，C++ CombatCardPool 不含无色）与
    状态/诅咒（池仅 Attack/Skill/Power）。按 name 排序保证抽样映射
    确定（DESIGN.md §3：不做轨迹对齐，池序不向 C++ blob 看齐）。
    """
    pool = [
        g
        for g in vars(_content_cards).values()
        if isinstance(g, CardDef)
        and g.ctype in ("Attack", "Skill", "Power")
        and g not in _COLORLESS_CARDS
        and (ctype is None or g.ctype == ctype)
    ]
    return sorted(pool, key=lambda c: c.name)


def _colorless_card_pool() -> list[CardDef]:
    """无色随机卡池（对齐 getTrulyRandomColorlessCardInCombat，Game.cpp:209-213：
    CombatColorlessCardPool）。当前仅 Hand of Greed（诚实实现，见
    _COLORLESS_CARDS 注释）。"""
    return sorted(_COLORLESS_CARDS, key=lambda c: c.name)


def _temp_card_into_hand(bc: BattleContext, card: CardDef, upgraded: bool = False,
                         cost_for_turn: int | None = None) -> None:
    """临时牌入手（对齐 MakeTempCardInHand → moveToHandHelper，
    BattleContext.cpp:2531-2537）：满手（≥10）进弃牌堆而非消失。

    card_manager.create_temp_card_in_hand 的满手分支是"直接消失"，与
    C++ moveToHandHelper 的进弃牌堆不符且该文件本批次不可改，故此处
    直接组合 card_manager 公开 API（instantiate + move_to_hand /
    create_temp_card_in_discard）实现 C++ 语义。
    """
    if len(bc.cards.hand) >= MAX_HAND_SIZE:
        bc.cards.create_temp_card_in_discard(card, upgraded)
        return
    inst = bc.cards.instantiate(card)
    inst.upgraded = upgraded
    if cost_for_turn is not None:
        inst.cost_for_turn = cost_for_turn
    bc.cards.move_to_hand(inst)


class RelicId(IntEnum):
    """战斗内生效遗物（Act 1 迁移范围 ~55 个；局外遗物不收录）。"""

    # ---- 战斗开始-即时效果 ----
    BURNING_BLOOD = 0  # 铁甲开局：战斗胜利回复 6 HP（exitBattle L569-573）
    AKABEKO = 1  # lightspeed 实现为开局一次性 VIGOR 8（initRelics L122-124，非原版每回合首次攻击 +8）
    ANCHOR = 2  # 战斗开始 +10 格挡（L226-228，直接 block+=10 不走 gainBlock）
    BLOOD_VIAL = 3  # 战斗开始回复 2 HP（L236-238）
    GIRYA = 4  # 战斗开始 +data 力量（L280-282；计数器为局外举重次数）
    VAJRA = 5  # 战斗开始 +1 力量（L358-360）
    LANTERN = 6  # 首回合 +1 能量（L284-286 gainEnergy 直加）
    BRONZE_SCALES = 7  # 战斗开始获得 3 层 THORNS（L240-242）
    ODDLY_SMOOTH_STONE = 8  # 战斗开始 +1 敏捷（L306-308）
    DU_VU_DOLL = 9  # 每有一个诅咒 +1 力量（L268-270 用局外计数；本项目开局数牌堆）
    THREAD_AND_NEEDLE = 10  # 战斗开始获得 4 层 PLATED_ARMOR（L354-356）
    MUTAGENIC_STRENGTH = 11  # 战斗开始 +3 力量 / 首回合末 -3（L288-291；LOSE_STRENGTH 回合末结算）
    SLING_OF_COURAGE = 12  # 精英房战斗开始 +2 力量（L340-343）
    PRESERVED_INSECT = 13  # 精英房敌人 HP 减 25%（L316-323）
    PANTOGRAPH = 14  # Boss 房战斗开始回复 25 HP（L310-313）
    NEOWS_LAMENT = 15  # 跨战斗语义（跳过，批次 3+）
    FOSSILIZED_HELIX = 16  # BUFFER 状态未迁移（跳过）
    DATA_DISK = 17  # 战斗开始 +1 专长 FOCUS（L264-265；无充能球体系，状态惰性）
    ECTOPLASM = 18  # 能量 +1，无法获得金币（战斗内无经济，仅能量；L136-138）
    SOZU = 19  # 能量 +1，无法使用药水（药水未迁移，仅能量；L214-216）
    BUSTED_CROWN = 20  # 能量 +1（L244-246；奖励卡惩罚为局外）
    COFFEE_DRIPPER = 21  # 能量 +1（L248-250）
    CURSED_KEY = 22  # 能量 +1（L256-258）
    FUSION_HAMMER = 23  # 能量 +1（L276-278）
    RUNIC_DOME = 24  # 能量 +1，看不到意图（L206-208；观测侧批次 5）
    VELVET_CHOKER = 25  # 能量 +1；每回合至多打 6 张牌（L222-224 + isCardPlayAllowed L709-712）
    PHILOSOPHERS_STONE = 26  # 能量 +1，怪物 +1 力量（L198-204）
    MARK_OF_PAIN = 27  # 能量 +1，战斗开始 2 张 Wound 洗入抽牌堆（L112-115 + L411-413）
    SNECKO_EYE = 28  # 抽牌 +2（init L63-65）；自弃 CONFUSED 未迁移（L210-212 TODO）
    HAPPY_FLOWER = 29  # 每 3 回合 +1 能量（L148-154 + Player.cpp:522-527）
    INCENSE_BURNER = 30  # 每 6 回合获得 1 层 INTANGIBLE（L156-162 + Player.cpp:535-539）
    INK_BOTTLE = 31  # 每打出 10 张牌抽 1 张（L164-166 + onUseXxxCard 四处计数）
    INSERTER = 32  # Retain 未实现（跳过）
    NUNCHAKU = 33  # 每打出 10 张攻击牌 +1 能量（L181-183 + BattleContext.cpp:1709-1714，跨回合累计）
    PEN_NIB = 34  # 打出第 10 张攻击牌后，下一张攻击伤害翻倍（L189-196 + L1697-1703）
    SUNDIAL = 35  # 每洗 3 次牌 +2 能量（L218-220 + onShuffle L2804-2811）
    OMAMORI = 36  # 装载 2 充能；抵消诅咒逻辑待"获得诅咒"事件源（L185-187；TODO，本框架战斗内无诅咒获得来源）
    LIZARD_TAIL = 37  # 需要免死引擎位（跳过）
    MERCURY_HOURGLASS = 38  # 每回合开始对所有敌人 3 伤（L432-434 + Player.cpp:551-553）
    RED_SKULL = 39  # HP ≤50% 时持有 3 力量（进出半血线 ±3，Player.cpp:169-171/311-313 + L436-438）
    # ---- 战斗开始-抽牌前桶 ----
    TOOLBOX = 40  # 战斗开始：随机 1 张无色牌本回合 0 费入手（注册 L98 / 执行 L382；Actions.cpp:988-998）
    # ---- 战斗开始-抽牌后桶 ----
    BAG_OF_MARBLES = 41  # 战斗开始对所有敌人 1 层易伤（L395-397）
    BAG_OF_PREPARATION = 42  # 首回合额外抽 2 张（L399-400）
    CLOCKWORK_SOUVENIR = 43  # 战斗开始获得 1 层 ARTIFACT（L403-405）
    GREMLIN_VISAGE = 44  # 战斗开始自身 1 层虚弱（L407-409）
    RED_MASK = 45  # 战斗开始对所有敌人 1 层虚弱（L415-417）
    TWISTED_FUNNEL = 46  # 战斗开始对所有敌人 4 层中毒（L423-425）
    # ---- 回合开始（固定序）----
    ART_OF_WAR = 47  # 上回合未打出攻击牌 → +1 能量（Player.cpp:492-496）
    HORN_CLEAT = 48  # 第 2 回合开始 +14 格挡（Player.cpp:529-533，lightspeed turn==1）
    DAMARU = 49  # 每回合 +1 MANTRA（Player.cpp:513-516；无姿态体系，状态惰性）
    CAPTAINS_WHEEL = 50  # 第 3 回合开始 +18 格挡（Player.cpp:507-511，lightspeed turn==2）
    EMOTION_CHIP = 51  # lightspeed 未实现（Player.cpp:299/518 两处 TODO），效果待核实
    POCKETWATCH = 52  # 上回合打出 ≤3 张牌 → 抽 3 张（Player.cpp:663-667）
    ICE_CREAM = 53  # 能量回合结束不清空（Player.cpp:715-720 rechargeEnergy）
    WARPED_TONGS = 54  # 每回合开始（含首回合）：随机升级 1 张手牌（Player.cpp:669-671 + Actions.cpp:940-960）
    # ---- 出牌类 ----
    KUNAI = 55  # 每回合每打出 3 张攻击牌 +1 敏捷（BattleContext.cpp:1671-1673）
    ORNAMENTAL_FAN = 56  # 每回合每打出 3 张攻击牌获得 4 格挡（L1683-1685）
    SHURIKEN = 57  # 每回合每打出 3 张攻击牌 +1 力量（L1687-1689）
    NECRONOMICON = 58  # 每回合首张 ≥2 费攻击牌（或 X 费 ≥2 能量）额外结算一次（L1691-1695 + Player.cpp:555-557）
    DUALITY = 59  # TODO（Defect 奥义，批次 3+）
    LETTER_OPENER = 60  # 每回合每打出 3 张技能牌对所有敌人 5 伤（L1796-1800）
    BIRD_FACED_URN = 61  # 每打出能力牌回复 2 HP（L1854-1856）
    MUMMIFIED_HAND = 62  # 打出 Power 后：随机 1 张费用>0 的手牌本回合 0 费（L1874-1876 + L2847-2873）
    # ---- 伤害计算 ----
    STRIKE_DUMMY = 63  # 打击牌 +3 伤（L2677-2679）
    WRIST_BLADE = 64  # 0 费牌 +4 伤（L2681-2683）
    PAPER_PHROG = 65  # 易伤倍率 1.5 → 1.75（L2721-2727）
    # ---- 回合结束 ----
    CLOAK_CLASP = 66  # 回合末按手牌数获得格挡（L2036-2038）
    NILRYS_CODEX = 67  # 选卡 + 卡池（批次 3+）
    ORICHALCUM = 68  # 回合末若无格挡 +6 格挡（L2050-2054）
    STONE_CALENDAR = 69  # 第 7 回合末对所有敌人 52 伤（L2056-2060，lightspeed turn==6）
    RUNIC_PYRAMID = 70  # 回合末不弃手牌
    # ---- 受击/HP 类 ----
    TUNGSTEN_ROD = 71  # 每次受到 HP 损失 -1（Player.cpp:201-203/239-241/266-271）
    TORII = 72  # ≤5 点（未被格挡的）攻击伤害降为 1（Player.cpp:235-237）
    CENTENNIAL_PUZZLE = 73  # 每场首次失去 HP 抽 3 张牌（Player.cpp:294-297）
    SELF_FORMING_CLAY = 74  # 每次失去 HP 下回合 +3 格挡，可叠加（Player.cpp:303-305，NEXT_TURN_BLOCK）
    MAGIC_FLOWER = 75  # 战斗内治疗 ×1.5（Player.cpp:161-163）
    RUNIC_CUBE = 76  # 每次失去 HP 抽 1 张牌（Player.cpp:307-309）
    MEAT_ON_THE_BONE = 77  # 胜利时若 HP ≤50% 回复 12（exitBattle L581-585）
    # ---- 洗牌/消耗/死亡 ----
    THE_ABACUS = 78  # 每次洗牌 +6 格挡（onShuffle L2796-2798）
    CHARONS_ASHES = 79  # 每消耗 1 张牌对所有敌人 3 伤（L2819-2821）
    DEAD_BRANCH = 80  # 任意牌被消耗：随机 1 张铁甲色牌入手（L2823-2826）
    STRANGE_SPOON = 81  # RNG：打出会消耗的牌 50% 不消耗（L1985-1990）
    GREMLIN_HORN = 82  # 怪物死亡 +1 能量 +1 抽（Monster.cpp:317-320）
    THE_SPECIMEN = 83  # 怪物死亡时其中毒层数转移给另一敌人（Monster.cpp:322-324）
    HAND_DRILL = 84  # 攻击打空怪物格挡 → 2 层易伤（Monster.cpp:433-435/488-490）
    THE_BOOT = 85  # <5 的未格挡攻击伤害提到 5（Monster.cpp:340-342）
    # ---- 出牌资格/手牌 ----
    UNCEASING_TOP = 86  # 手牌打空抽 1 张（BattleContext.cpp:809-819）
    # ---- 格挡衰减 ----
    CALIPERS = 87  # 回合开始失去 15 格挡而非全清（L2183-2184）
    # ---- RNG/生成类 ----
    ENCHIRIDION = 88  # 战斗开始：随机 1 张 Power 牌本回合 0 费入手（L140-146）
    # ---- 批次 A 新增（弃牌遗物；lightspeed 未实现效果，按 wiki 补）----
    TINGSHA = 89  # 每弃 1 张牌：随机敌人 3 伤
    TOUGH_BANDAGES = 90  # 每弃 1 张牌：得 3 格挡


class RelicContainer:
    """保序遗物列表 + O(1) 集合查询 + 计数器。

    计数器语义（对齐 lightspeed relic.data / player 计数器）：
    - 跨回合持久：GIRYA 力量、NUNCHAKU/INK_BOTTLE 出牌计数、
      SUNDIAL/PEN_NIB 洗牌与攻击计数、HAPPY_FLOWER/INCENSE_BURNER 回合计数
      （对齐 updateRelicsOnExit L521-561 回写 relic.data）。
    - 每回合计数：KUNAI/SHURIKEN/ORNAMENTAL_FAN/LETTER_OPENER
      （对齐 attacksPlayedThisTurn/skillsPlayedThisTurn 每回合清零，
      BattleContext.cpp:2210-2211）与 NECRONOMICON 每回合一次标志
      （Player.cpp:555-557）。
    - 每场一次：CENTENNIAL_PUZZLE（Player.cpp:295 setHasRelic(false)）。
    """

    def __init__(self, relic_ids: list[RelicId] | None = None):
        self.relics: list[RelicId] = list(relic_ids or [])  # 获取顺序
        self._set = frozenset(self.relics)
        self.counters: dict[RelicId, int] = {r: 0 for r in self.relics}

    def has(self, rid: RelicId) -> bool:
        return rid in self._set

    def counter(self, rid: RelicId) -> int:
        return self.counters.get(rid, 0)

    def set_counter(self, rid: RelicId, v: int) -> None:
        if rid in self.counters:
            self.counters[rid] = v

    def bump(self, rid: RelicId) -> int:
        """计数器 +1 并返回新值（不存在时为 no-op 返回 -1）。"""
        if rid in self.counters:
            self.counters[rid] += 1
            return self.counters[rid]
        return -1

    # ============================================================
    # 治疗辅助（MAGIC_FLOWER 放大与 RED_SKULL 回升扣力量在 Player.heal 内）
    # ============================================================
    def _heal(self, bc: BattleContext, amount: int) -> None:
        """治疗入口（放大逻辑已移入 Player.heal，此处仅转发）。"""
        bc.player.heal(amount, bc)

    def modify_heal(self, bc: BattleContext, amount: int) -> int:
        """MAGIC_FLOWER：治疗量 ×3//2（Player.cpp:161-163，整数截断）。"""
        if self.has(RelicId.MAGIC_FLOWER):
            amount = amount * 3 // 2
        return amount

    def on_after_heal(self, bc: BattleContext, was_bloodied: bool) -> None:
        """治疗收尾：RED_SKULL 从半血以下回复过线 → -3 力量（Player.cpp:169-171）。"""
        p = bc.player
        if was_bloodied and p.hp * 2 > p.max_hp and self.has(RelicId.RED_SKULL):
            p.statuses.add(PlayerStatus.STRENGTH, -3)

    # ============================================================
    # 战斗开始（对齐 initRelics；即时桶按获取顺序，C++ 同为获取序 switch）
    # ============================================================
    def on_battle_start_immediate(self, bc: BattleContext) -> None:
        """即时效果：获取顺序生效，发生在首回合格挡清零之后、抽牌之前。"""
        p = bc.player
        for rid in self.relics:
            if rid == RelicId.VAJRA:
                # BattleContext.cpp:358-360
                p.statuses.add(PlayerStatus.STRENGTH, 1)
            elif rid == RelicId.ANCHOR:
                # L226-228：直接 block += 10（不走 gainBlock，
                # 不触发 JUGGERNAUT、不受 NO_BLOCK 拦截）
                p.block += 10
            elif rid == RelicId.BLOOD_VIAL:
                # L236-238（Player.heal → MAGIC_FLOWER 放大，Player.cpp:161-163）
                self._heal(bc, 2)
            elif rid == RelicId.AKABEKO:
                # L122-124：lightspeed 实现为开局一次性 VIGOR 8（非原版每回合
                # 首次攻击 +8），分布级差异已记录，按 lightspeed 移植。
                # VIGOR 在打出攻击牌后移除（见 on_use_attack_card）。
                p.statuses.add(PlayerStatus.VIGOR, 8)
            elif rid == RelicId.GIRYA:
                # L280-282：+data 力量（计数器 = 局外举重次数，本场景恒 0）
                p.statuses.add(PlayerStatus.STRENGTH, self.counter(RelicId.GIRYA))
            elif rid == RelicId.BRONZE_SCALES:
                # L240-242：3 层 THORNS（批次 1 核对修正：1 → 3）
                p.statuses.add(PlayerStatus.THORNS, 3)
            elif rid == RelicId.ODDLY_SMOOTH_STONE:
                # L306-308
                p.statuses.add(PlayerStatus.DEXTERITY, 1)
            elif rid == RelicId.MUTAGENIC_STRENGTH:
                # L288-291：+3 力量 + 3 层 LOSE_STRENGTH（批次 1 修正：1→3）。
                # LOSE_STRENGTH 于首回合末结算 -3 力量并移除
                #（Player.cpp:399-401 applyEndOfTurnPowers）。
                p.statuses.add(PlayerStatus.STRENGTH, 3)
                p.statuses.add(PlayerStatus.LOSE_STRENGTH, 3)
            elif rid == RelicId.PHILOSOPHERS_STONE:
                # L198-204：已有怪物全体 +1 力量（含不可选中者）；新生怪见
                # on_monster_spawned
                for m in bc.monsters.monsters:
                    m.statuses.add(MonsterStatus.STRENGTH, 1)
            elif rid == RelicId.LANTERN:
                # L284-286：gainEnergy 直加（仅首回合，此后不再触发）
                p.energy += 1
            elif rid == RelicId.HAPPY_FLOWER:
                # L148-154：开局计数 = data+1；满 3 → +1 能量（直加）并清零。
                # 此后每回合开始计数（Player.cpp:522-527）→ 第 3 回合首触发。
                if self.bump(RelicId.HAPPY_FLOWER) == 3:
                    self.set_counter(RelicId.HAPPY_FLOWER, 0)
                    p.energy += 1
            elif rid == RelicId.INCENSE_BURNER:
                # L156-162：开局计数 = data，+1 后满 6 → 1 层 INTANGIBLE。
                # 此后每回合开始计数（Player.cpp:535-539）→ 第 6 回合起每 6 回合。
                if self.bump(RelicId.INCENSE_BURNER) == 6:
                    self.set_counter(RelicId.INCENSE_BURNER, 0)
                    p.statuses.add(PlayerStatus.INTANGIBLE, 1)
            elif rid == RelicId.RED_SKULL:
                # L436-438：开局已在半血线（hp ≤ max/2）→ +3 力量。
                # 失 HP 跌破半血线的 +3 见 on_player_hp_was_lost；
                # 治疗回到半血线以上的 -3（Player.cpp:169-171）因 Player.heal
                # 无遗物钩子（entities.py 本批次不可改）暂缺，TODO。
                if p.hp * 2 <= p.max_hp:
                    p.statuses.add(PlayerStatus.STRENGTH, 3)
            elif rid == RelicId.DU_VU_DOLL:
                # L268-270：C++ 用局外计数 r.data（获得诅咒时维护）。
                # 本项目无局外层，战斗开始按牌堆实数统计 Curse 实例
                #（抽/弃/手/消耗四堆，对齐"牌组中每有一个诅咒"语义）。
                cards = bc.cards
                n = sum(
                    1
                    for pile in (cards.draw_pile, cards.discard_pile, cards.hand, cards.exhaust_pile)
                    for c in pile
                    if c.card.ctype == "Curse"
                )
                if n:
                    p.statuses.add(PlayerStatus.STRENGTH, n)
            elif rid == RelicId.THREAD_AND_NEEDLE:
                # L354-356：4 层 PLATED_ARMOR（结算见 entities.Player：
                # 回合末按层数格挡、未格挡攻击伤害 -1 层）
                p.statuses.add(PlayerStatus.PLATED_ARMOR, 4)
            elif rid == RelicId.SLING_OF_COURAGE:
                # L340-343：精英房 +2 力量
                if bc.encounter in ELITE_ENCOUNTERS:
                    p.statuses.add(PlayerStatus.STRENGTH, 2)
            elif rid == RelicId.PRESERVED_INSECT:
                # L316-323：精英房敌人 HP = maxHp×0.75（截断）。
                # 批次 1 核对修正：原实现的"非 Boss 最高血怪 9 层易伤"与
                # lightspeed 不符（原版游戏文本为"精英房敌人 HP -25%"）。
                if bc.encounter in ELITE_ENCOUNTERS:
                    for m in bc.monsters.monsters:
                        m.hp = int(m.max_hp * 0.75)
            elif rid == RelicId.PANTOGRAPH:
                # L310-313：Boss 房回复 25 HP（治疗受 MAGIC_FLOWER 放大）
                if bc.encounter in BOSS_ENCOUNTERS:
                    self._heal(bc, 25)
            elif rid == RelicId.DATA_DISK:
                # L264-265：+1 FOCUS（无充能球体系，状态惰性装载）
                p.statuses.add(PlayerStatus.FOCUS, 1)
            elif rid == RelicId.DAMARU:
                # L260-262：开局 MANTRA +1（每回合开始的 +1 见 on_turn_start）
                p.statuses.add(PlayerStatus.MANTRA, 1)
            elif rid == RelicId.OMAMORI:
                # L185-187：装载充能计数（setHasRelic(r.data)，原版 2 充能）。
                # 抵消逻辑需要"获得诅咒"事件钩子（C++ 在生成诅咒的各效果处
                # 内联判定），本框架战斗内无任何获得诅咒的来源（内容层无诅咒
                # 生成效果、Act 1 怪物无施加诅咒）——批次 3 已核实，保持 TODO
                # 不硬凑，待诅咒来源（局外事件/更高幕怪物）迁移时再补钩子；
                # 消耗充能的局外事件见 exitBattle L463-469。
                self.set_counter(RelicId.OMAMORI, 2)
            elif rid == RelicId.MARK_OF_PAIN:
                # 能量 +1 属每回合同加成（见 extra_energy_per_turn）；
                # 伤口洗入在抽牌后桶（L411-413，见 on_battle_start_post_draw）
                pass
            elif rid == RelicId.ENCHIRIDION:
                # L140-146：随机 1 张 Power 牌（CombatTypeCardPool，14 张）入手，
                # 未升级，setCostForTurn(0)——本回合 0 费（C++ 口径；回合末
                # reset_attributes_at_end_of_turn 还原）。C++ addToBot 排在
                # 首抽之前 → 净顺序为"先入手再抽首手"，本钩子恰在首抽前，
                # 同步入手等价（此时手牌为空，无满手分支）。misc 流抽样。
                pool = _combat_card_pool("Power")
                card = pool[bc.rngs.misc.int_inclusive(0, len(pool) - 1)]
                _temp_card_into_hand(bc, card, cost_for_turn=0)
            elif rid == RelicId.TOOLBOX:
                # 注册 L98（atBattleStartPreDraw）/ 执行 L382：抽牌前桶。
                # C++ ToolboxAction（Actions.cpp:988-998）为 3 选 1 Discovery
                # 选卡，所选牌经 chooseDiscoveryCard（L2995-3010）setCostForTurn(0)
                # 入手（满手进弃牌堆）；原版游戏为"随机 1 张无色牌直接入手"。
                # 本项目战斗内无选卡环境接线，按任务口径实现为随机 1 张无色牌
                # 本回合 0 费直接入手（池见 _COLORLESS_CARDS 注释）。
                # 与 ENCHIRIDION 同在首抽前入手（C++ 桶序差异：两者都往空手
                # 各加 1 张，可交换，分布级等价）。misc 流抽样。
                pool = _colorless_card_pool()
                card = pool[bc.rngs.misc.int_inclusive(0, len(pool) - 1)]
                _temp_card_into_hand(bc, card, cost_for_turn=0)
            else:
                # 明确跳过（跨战斗/引擎位缺失，见类注释）：
                # NEOWS_LAMENT / FOSSILIZED_HELIX / LIZARD_TAIL / INSERTER /
                # SNECKO_EYE 自弃 CONFUSED 等
                pass

    def on_battle_start_extra_draw(self, bc: BattleContext) -> int:
        """抽牌前桶：影响首回合抽牌数。"""
        extra = 0
        if self.has(RelicId.BAG_OF_PREPARATION):
            # C++ 在抽牌后桶入队 DrawCards(2)（L399-400）；本项目并入首抽
            # 张数，净手牌等价，仅与桶内其他效果的先后有分布级差异
            extra += 2
        if self.has(RelicId.SNECKO_EYE):
            # init L63-65 cardDrawPerTurn += 2；CONFUSED 自弃未迁移（TODO）
            extra += 2
        return extra

    def on_battle_start_post_draw(self, bc: BattleContext) -> None:
        """抽牌后桶（atBattleStart，C++ 按获取序；此处固定序近似）+ 桶后固定项。"""
        # C++ 桶内顺序为获取顺序（L393-430）；Python 用固定序，单遗物/常见
        # 组合下等价，组合顺序差异为已知近似。
        if self.has(RelicId.BAG_OF_MARBLES):
            # L395-397
            bc.add_to_bot(Actions.debuff_all_enemy(MonsterStatus.VULNERABLE, 1, False))
        if self.has(RelicId.MARK_OF_PAIN):
            # L411-413：2 张 Wound 洗入抽牌堆（抽牌后入堆，不入首手）
            from sts.content.cards import WOUND

            bc.add_to_bot(Actions.make_temp_card_in_draw_pile(WOUND, False, shuffle_into=True))
            bc.add_to_bot(Actions.make_temp_card_in_draw_pile(WOUND, False, shuffle_into=True))
        if self.has(RelicId.GREMLIN_VISAGE):
            # L407-409：p.debuff<PS::WEAK>(1)，默认 isSourceMonster=true →
            # justApplied 置位、首个回合末不递减（对齐 C++ 默认参数）
            bc.add_to_bot(Actions.debuff_player(PlayerStatus.WEAK, 1, True))
        if self.has(RelicId.RED_MASK):
            # L415-417：DebuffAllEnemy<MS::WEAK>(1)，默认 isSourceMonster=true
            # → justApplied 置位（对齐 C++ 默认参数，Player.h:42 / Monster.h:318-321）
            bc.add_to_bot(Actions.debuff_all_enemy(MonsterStatus.WEAK, 1, True))
        if self.has(RelicId.TWISTED_FUNNEL):
            # L423-425
            bc.add_to_bot(Actions.debuff_all_enemy(MonsterStatus.POISON, 4, False))
        if self.has(RelicId.CLOCKWORK_SOUVENIR):
            # L403-405：BuffPlayer ARTIFACT 1（即时落地等价入队）
            bc.player.statuses.add(PlayerStatus.ARTIFACT, 1)
        if self.has(RelicId.MERCURY_HOURGLASS):
            # L432-434：桶后固定项（所有桶效果之后）
            bc.add_to_bot(Actions.damage_all_enemy(3))
        # WARPED_TONGS：initRelics L446-449——首回合同样经
        # atTurnStartPostDraw 桶入队（battle.py 首回合不调
        # on_turn_start_post_draw，故在此桶尾接线，顺序对齐 C++：
        # 小时glass → tongs）。
        if self.has(RelicId.WARPED_TONGS):
            self._queue_warped_tongs(bc)

    # ============================================================
    # 回合开始（Player.cpp applyStartOfTurnRelics L490-563，固定序）
    # ============================================================
    def on_turn_start(self, bc: BattleContext) -> None:
        p = bc.player
        # 每回合计数器重置：连击类对齐 attacks/skillsPlayedThisTurn
        # 每回合清零（BattleContext.cpp:2210-2211）；NECRONOMICON 每回合
        # 一次标志对齐 haveUsedNecronomiconThisTurn（Player.cpp:555-557）。
        # NUNCHAKU/INK_BOTTLE 为跨回合累计计数，不在此重置。
        for rid in (RelicId.KUNAI, RelicId.SHURIKEN, RelicId.ORNAMENTAL_FAN,
                    RelicId.LETTER_OPENER, RelicId.NECRONOMICON):
            if rid in self.counters:
                self.counters[rid] = 0
        # Player.cpp:492-496（此时尚未重置，计数即上回合值）
        if self.has(RelicId.ART_OF_WAR):
            if p.attacks_played_last_turn == 0:
                bc.add_to_bot(Actions.gain_energy(1))
        # Player.cpp:507-511：lightspeed turn==2 = 本项目第 3 回合，一次性
        if self.has(RelicId.CAPTAINS_WHEEL):
            if bc.turn == 3:
                bc.add_to_bot(Actions.gain_block(18))
        # Player.cpp:513-516：MANTRA +1（无姿态体系，惰性；批次 1 修正：
        # 原实现 +1 敏捷与 C++ 不符）
        if self.has(RelicId.DAMARU):
            p.statuses.add(PlayerStatus.MANTRA, 1)
        # Player.cpp:522-527
        if self.has(RelicId.HAPPY_FLOWER):
            if self.bump(RelicId.HAPPY_FLOWER) == 3:
                self.set_counter(RelicId.HAPPY_FLOWER, 0)
                bc.add_to_bot(Actions.gain_energy(1))
        # Player.cpp:529-533：lightspeed turn==1 = 本项目第 2 回合，一次性
        #（批次 1 修正：原实现"每 5 回合 +14"与 C++ 不符）
        if self.has(RelicId.HORN_CLEAT):
            if bc.turn == 2:
                bc.add_to_bot(Actions.gain_block(14))
        # Player.cpp:535-539：每 6 回合 1 层 INTANGIBLE
        #（批次 1 修正：原实现"每 2 回合 1 层 ARTIFACT"与 C++ 不符）
        if self.has(RelicId.INCENSE_BURNER):
            if self.bump(RelicId.INCENSE_BURNER) == 6:
                self.set_counter(RelicId.INCENSE_BURNER, 0)
                bc.add_to_bot(Actions.buff_player(PlayerStatus.INTANGIBLE, 1))
        # Player.cpp:551-553
        if self.has(RelicId.MERCURY_HOURGLASS):
            bc.add_to_bot(Actions.damage_all_enemy(3))
        # EMOTION_CHIP：Player.cpp:518-520 lightspeed 未实现（两处 TODO），
        # 效果无法从 C++ 核实，暂不硬凑（报告说明）

    def on_turn_start_post_draw(self, bc: BattleContext) -> None:
        """抽牌后回合开始桶（Player.cpp:661-672）。"""
        p = bc.player
        # Player.cpp:663-667：上回合打出 ≤3 张牌 → 抽 3 张
        #（批次 1 修正：原实现"上回合 0 张 → 回 6 HP"与 C++ 不符）
        if self.has(RelicId.POCKETWATCH):
            if p.cards_played_last_turn <= 3:
                bc.add_to_bot(Actions.draw_cards(3))
        if self.has(RelicId.WARPED_TONGS):
            # Player.cpp:669-671：入队随机升级动作（排在 POCKETWATCH 抽牌
            # 之后弹出，顺序对齐 applyStartOfTurnPostDrawRelics）
            self._queue_warped_tongs(bc)

    def _queue_warped_tongs(self, bc: BattleContext) -> None:
        """WARPED_TONGS：每回合开始随机升级 1 张手牌（入队，对齐
        addToBot(UpgradeRandomCardAction)，Actions.cpp:940-960）。

        - **无条件触发**（C++ 无 50% 判定；UpgradeRandomCardAction 直接
          升级），无可升级手牌时 no-op。
        - 升级资格对齐 canUpgrade（CardInstance.cpp:55-59）：未升级
          （multiple_upgrades 类可反复）且非状态/诅咒。
        - 选牌用 misc 流（C++ 经 shuffleRng 洗牌取首张，分布等价）。
        - 入队而非直接结算：动作在本回合抽牌之后弹出（对齐 C++
          UpgradeRandomCardAction 排在 DrawCards 之后，升级作用于
          抽牌后的手牌）。
        """

        def run(bc2: BattleContext) -> None:
            upgradeable = [
                c for c in bc2.cards.hand
                if (not c.upgraded or c.card.multiple_upgrades)
                and c.card.ctype not in ("Curse", "Status")
            ]
            if not upgradeable:
                return
            inst = upgradeable[bc2.rngs.misc.int_inclusive(0, len(upgradeable) - 1)]
            inst.upgrade()

        bc.add_to_bot(Action(run))

    # ============================================================
    # 能量/格挡衰减
    # ============================================================
    def extra_energy_per_turn(self, bc: BattleContext) -> int:
        """能量类遗物的每回合额外能量（initRelics energyPerTurn++）。"""
        extra = 0
        if self.has(RelicId.ECTOPLASM):  # L136-138
            extra += 1
        if self.has(RelicId.SOZU):  # L214-216
            extra += 1
        if self.has(RelicId.COFFEE_DRIPPER):  # L248-250
            extra += 1
        if self.has(RelicId.CURSED_KEY):  # L256-258
            extra += 1
        if self.has(RelicId.VELVET_CHOKER):  # L222-224
            extra += 1
        if self.has(RelicId.RUNIC_DOME):  # L206-208
            extra += 1
        if self.has(RelicId.PHILOSOPHERS_STONE):  # L203
            extra += 1
        if self.has(RelicId.FUSION_HAMMER):  # L276-278（批次 1 修正：+1，非 +2）
            extra += 1
        if self.has(RelicId.BUSTED_CROWN):  # L244-246（批次 1 修正：+1，非 +2）
            extra += 1
        if self.has(RelicId.MARK_OF_PAIN):  # L112-115
            extra += 1
        return extra

    def keeps_leftover_energy(self, bc: BattleContext) -> bool:
        # Player.cpp:715-720 rechargeEnergy
        return self.has(RelicId.ICE_CREAM)

    def on_block_decay(self, bc: BattleContext) -> int:
        """回合开始格挡保留量（battle.py 以 min(block, 返回值) 落地）。

        CALIPERS：C++ 为 block = max(0, block-15)（BattleContext.cpp:
        2183-2184，"失去 15"而非"保留 15"）；返回失去 15 后的剩余量与
        battle.py 的 min 合成同一结果。
        """
        if self.has(RelicId.CALIPERS):
            return max(0, bc.player.block - 15)
        return 0

    # ============================================================
    # 出牌类（对齐 onUseAttackCard L1660-1714 / onUseSkillCard L1777-1804 /
    # onUsePowerCard L1852-1876 / onUseStatusOrCurseCard L1927-1933 的遗物段）
    # ============================================================
    def on_use_attack_card(self, bc: BattleContext) -> None:
        p = bc.player
        item = bc.cur_card_queue_item
        inst = item.card if item is not None else None
        # VIGOR 出伤后移除（BattleContext.cpp:1647-1649，onUseAttackCard 的
        # Powers 段）。状态结算暂挂遗物钩子位首行（battle.py 不可改），调用
        # 点相对顺序与 C++ 一致（遗物段之前）——AKABEKO 的 +8 只吃首张攻击。
        if p.statuses.has(PlayerStatus.VIGOR):
            p.statuses.remove(PlayerStatus.VIGOR)
        # INK_BOTTLE：BattleContext.cpp:1663-1669，跨回合计数，满 10 抽 1
        #（批次 1 修正：原实现"每回合计数、满 10 +1 力量"与 C++ 不符——
        # C++ 效果为抽 1 张牌）
        if self.has(RelicId.INK_BOTTLE):
            if self.bump(RelicId.INK_BOTTLE) == 10:
                self.set_counter(RelicId.INK_BOTTLE, 0)
                bc.add_to_bot(Actions.draw_cards(1))
        # KUNAI：L1671-1673（attacksPlayedThisTurn % 3 == 0 ≡ 每回合计数满 3）
        if self.has(RelicId.KUNAI):
            if self.bump(RelicId.KUNAI) == 3:
                self.set_counter(RelicId.KUNAI, 0)
                p.statuses.add(PlayerStatus.DEXTERITY, 1)
        # ORNAMENTAL_FAN：L1683-1685
        if self.has(RelicId.ORNAMENTAL_FAN):
            if self.bump(RelicId.ORNAMENTAL_FAN) == 3:
                self.set_counter(RelicId.ORNAMENTAL_FAN, 0)
                bc.add_to_bot(Actions.gain_block(4))
        # SHURIKEN：L1687-1689
        if self.has(RelicId.SHURIKEN):
            if self.bump(RelicId.SHURIKEN) == 3:
                self.set_counter(RelicId.SHURIKEN, 0)
                p.statuses.add(PlayerStatus.STRENGTH, 1)
        # NECRONOMICON：L1691-1695——每回合首张（costForTurn ≥2 或 X 费消耗
        # ≥2 能量）攻击牌额外结算一次。重放项 purgeOnUse（不再入堆、不再触发
        # 本遗物）+ autoplay；C++ 置 cardQueue 队首，本项目等效入队尾
        #（单张出牌期间队列通常为空）。freeToPlay 字段本项目无来源，未对齐。
        if (
            self.has(RelicId.NECRONOMICON)
            and item is not None
            and inst is not None
            and self.counter(RelicId.NECRONOMICON) == 0
            and not item.autoplay
            and not item.purge_on_use
            and (inst.cost >= 2 or (inst.card.x_cost and item.energy_on_use >= 2))
        ):
            self.set_counter(RelicId.NECRONOMICON, 1)
            bc.add_to_bot_card(
                CardQueueItem(
                    card=inst, target=item.target, purge_on_use=True,
                    autoplay=True, energy_on_use=item.energy_on_use,
                )
            )
        # PEN_NIB：L1697-1703，计数到 9（第 9 张攻击后）→ 置翻倍状态、
        # 计数 = -1；第 10 张攻击翻倍并归零（见 modify_card_damage）
        if self.has(RelicId.PEN_NIB):
            if self.bump(RelicId.PEN_NIB) == 9:
                p.statuses.set(PlayerStatus.PEN_NIB, 1)
                self.set_counter(RelicId.PEN_NIB, -1)  # 翻倍中
        # NUNCHAKU：L1709-1714，跨回合计数（batch1 修正：不按回合清零）
        if self.has(RelicId.NUNCHAKU):
            if self.bump(RelicId.NUNCHAKU) >= 10:
                self.set_counter(RelicId.NUNCHAKU, 0)
                bc.add_to_bot(Actions.gain_energy(1))

    def on_use_skill_card(self, bc: BattleContext) -> None:
        # INK_BOTTLE：L1780-1786
        if self.has(RelicId.INK_BOTTLE):
            if self.bump(RelicId.INK_BOTTLE) == 10:
                self.set_counter(RelicId.INK_BOTTLE, 0)
                bc.add_to_bot(Actions.draw_cards(1))
        # LETTER_OPENER：L1796-1800（skillsPlayedThisTurn % 3 == 0；
        # 批次 1 修正：4 伤 → 5 伤）
        if self.has(RelicId.LETTER_OPENER):
            if self.bump(RelicId.LETTER_OPENER) == 3:
                self.set_counter(RelicId.LETTER_OPENER, 0)
                bc.add_to_bot(Actions.damage_all_enemy(5))
        # MUMMIFIED_HAND：onUseSkillCard L1802-1804 为 lightspeed 的 `// todo`
        # 死代码（技能侧不触发，仅能力牌触发，见 on_use_power_card）——
        # 批次 3 已核对，正确跳过

    def on_use_power_card(self, bc: BattleContext) -> None:
        # BIRD_FACED_URN：L1854-1856（Player.heal → MAGIC_FLOWER 放大）
        if self.has(RelicId.BIRD_FACED_URN):
            self._heal(bc, 2)
        # INK_BOTTLE：L1858-1864
        if self.has(RelicId.INK_BOTTLE):
            if self.bump(RelicId.INK_BOTTLE) == 10:
                self.set_counter(RelicId.INK_BOTTLE, 0)
                bc.add_to_bot(Actions.draw_cards(1))
        # MUMMIFIED_HAND：L1874-1876 → mummifiedHandOnUsePower（L2847-2873）。
        # 直接结算（C++ 同为钩子内直调）：打出 Power 后，随机 1 张费用 >0
        # 的手牌 setCostForTurn(0)。此时刚打出的 Power 已移出手牌
        # （play_card 先 pop），不在候选内。
        # C++ 资格：cost>0 && costForTurn>0 && !freeToPlayOnce，并排除已在
        # 卡牌队列中的实例。本项目 cost 属性已折叠 cost_for_turn
        # （-1=未设置），inst.cost>0 覆盖前两条；freeToPlayOnce 无来源、
        # 队列中实例必已移出手牌，均无需额外过滤。misc 流抽样
        # （C++ 用 cardRandomRng）。
        if self.has(RelicId.MUMMIFIED_HAND):
            eligible = [c for c in bc.cards.hand if c.cost > 0]
            if eligible:
                chosen = eligible[bc.rngs.misc.int_inclusive(0, len(eligible) - 1)]
                chosen.cost_for_turn = 0

    def on_use_status_or_curse_card(self, bc: BattleContext) -> None:
        # INK_BOTTLE：L1927-1933（第四处计数点；本项目状态/诅咒卡多为
        # 自动结算路径不经过此钩子，可打出时（BLUE_CANDLE/MEDICAL_KIT）对齐）
        if self.has(RelicId.INK_BOTTLE):
            if self.bump(RelicId.INK_BOTTLE) == 10:
                self.set_counter(RelicId.INK_BOTTLE, 0)
                bc.add_to_bot(Actions.draw_cards(1))
        # TODO 批次 2+：BLUE_CANDLE/MEDICAL_KIT（依赖卡池迁移）

    def on_would_exhaust(self, bc: BattleContext, inst: CardInstance) -> bool:
        """onAfterUseCard 的消耗路由（L1985-1990）：返回 False 表示改走弃牌堆
        （STRANGE_SPOON 50% 不消耗；C++ 用 cardRandom 流，本项目 misc 流）。"""
        if self.has(RelicId.STRANGE_SPOON):
            return bc.rngs.misc.int_inclusive(0, 9999) >= 5000
        return True

    def check_play_allowed(self, bc: BattleContext, inst: CardInstance) -> bool:
        """出牌资格（isCardPlayAllowed L709-712：VELVET_CHOKER 每回合
        至多打 6 张牌——按本回合已打出数，非手牌数；批次 1 修正）。"""
        if self.has(RelicId.VELVET_CHOKER):
            if bc.player.cards_played_this_turn >= 6:
                return False
        return True

    # ============================================================
    # 伤害计算（calculateCardDamage L2671-2742 的查询点）
    # ============================================================
    def modify_card_damage(self, bc: BattleContext, item: CardQueueItem,
                           target_idx: int, base_damage: float) -> float:
        """出伤管线的遗物修正（STRIKE_DUMMY/WRIST_BLADE/PEN_NIB）。

        C++ 中 STRIKE_DUMMY/WRIST_BLADE 位于力量之前（L2675-2683）、
        PEN_NIB 位于力量之后虚弱之前（L2698-2700）；加法项可交换，
        本项目统一在力量之后调用，分布级等价。
        """
        assert item.card is not None
        d = base_damage
        if self.has(RelicId.STRIKE_DUMMY) and item.card.card.name in _STRIKE_NAMES:
            # L2677-2679：isStrikeCard（打击牌族，对齐 content.cards._STRIKE_CARD_NAMES）
            d += 3
        if self.has(RelicId.WRIST_BLADE) and item.card.cost == 0:
            # L2681-2683：costForTurn == 0（calculateCardDamage 仅攻击牌
            # 走入，等价于"0 费攻击牌 +4 伤"）
            d += 4
        if self.has(RelicId.PEN_NIB) and bc.player.statuses.get(PlayerStatus.PEN_NIB) > 0:
            # L2698-2700：×2；状态与计数在当张结算后清除（计数经
            # on_use_attack_card 的 -1→0 递增路径归零）
            d *= 2
            bc.player.statuses.set(PlayerStatus.PEN_NIB, 0)
            if RelicId.PEN_NIB in self.counters and self.counters[RelicId.PEN_NIB] < 0:
                self.counters[RelicId.PEN_NIB] = 0
        return d

    def vulnerable_multiplier(self, bc: BattleContext) -> float:
        """易伤乘算倍率（L2721-2727：PAPER_PHROG 1.5 → 1.75）。"""
        return 1.75 if self.has(RelicId.PAPER_PHROG) else 1.5

    # ============================================================
    # 受击/HP 类（Player.attacked / hpWasLost 调用）
    # ============================================================
    def on_incoming_attack_damage(self, bc: BattleContext, damage: int) -> int:
        """TORII（≤5→1）→ TUNGSTEN_ROD（-1），顺序对齐 Player.cpp:235-241。
        由 entities.Player.attacked 在格挡吸收**之后**按漏格挡余量调用。
        """
        if self.has(RelicId.TORII) and 0 < damage <= 5:
            damage = 1
        if self.has(RelicId.TUNGSTEN_ROD) and damage > 0:
            damage = max(0, damage - 1)
        return damage

    def on_hp_loss_reduce(self, bc: BattleContext, damage: int) -> int:
        """TUNGSTEN_ROD 对非攻击 HP 损失的 -1（damage() :201-203 /
        loseHp() :266-271 两条路径共用）。"""
        if self.has(RelicId.TUNGSTEN_ROD) and damage > 0:
            damage -= 1
        return damage

    def on_player_hp_was_lost(self, bc: BattleContext, amount: int, was_bloodied: bool = False) -> None:
        """hpWasLost 遗物段（Player.cpp:276-321，序：CENTENNIAL →
        EMOTION_CHIP → SELF_FORMING_CLAY → RUNIC_CUBE → RED_SKULL）。
        was_bloodied 为扣血前的半血线快照（由 Player._hp_was_lost 传入）。"""
        if amount <= 0:
            return
        p = bc.player
        # Player.cpp:294-297：每场一次，addToTop 抽 3
        if self.has(RelicId.CENTENNIAL_PUZZLE) and self.counter(RelicId.CENTENNIAL_PUZZLE) == 0:
            self.set_counter(RelicId.CENTENNIAL_PUZZLE, 1)
            bc.add_to_top(Actions.draw_cards(3))
        # EMOTION_CHIP：Player.cpp:299-301 lightspeed TODO，效果待核实，不硬凑
        # Player.cpp:303-305：NEXT_TURN_BLOCK +3（下回合开始转化格挡，可叠加）
        if self.has(RelicId.SELF_FORMING_CLAY):
            p.statuses.add(PlayerStatus.NEXT_TURN_BLOCK, 3)
        # Player.cpp:307-309：每次失去 HP 抽 1（addToTop）
        if self.has(RelicId.RUNIC_CUBE):
            bc.add_to_top(Actions.draw_cards(1))
        # Player.cpp:311-313：跌破半血线（扣血前 >50%、扣血后 ≤50%）→ +3 力量。
        # 回升过线的 -3 见 on_after_heal。
        if self.has(RelicId.RED_SKULL):
            if not was_bloodied and p.hp * 2 <= p.max_hp:
                p.statuses.add(PlayerStatus.STRENGTH, 3)

    # ============================================================
    # 怪物侧触发
    # ============================================================
    def on_monster_death(self, bc: BattleContext, m: Monster) -> None:
        """Monster::die（L317-324，序：GREMLIN_HORN → THE_SPECIMEN；
        全灭时不进此钩子——die L293-297 先判胜返回）。"""
        if self.has(RelicId.GREMLIN_HORN):
            # L317-320
            bc.add_to_bot(Actions.gain_energy(1))
            bc.add_to_bot(Actions.draw_cards(1))
        if self.has(RelicId.THE_SPECIMEN):
            # L322-324：C++ 入队"选择敌人承接中毒"界面；die() 不清状态，
            # 层数可读。单候选直接转移，多候选挂 CARD_SELECT 等外部选择。
            n = m.statuses.get(MonsterStatus.POISON)
            if n > 0:
                others = [o for o in bc.monsters.monsters if o.is_targetable() and o is not m]
                if others:

                    def _apply(bc2: BattleContext, chosen: list) -> None:
                        if chosen:
                            chosen[0].statuses.add(MonsterStatus.POISON, n)
                            m.statuses.remove(MonsterStatus.POISON)

                    bc.open_card_select(
                        others, _apply, prompt="标本：选择承接中毒层数的敌人"
                    )

    def on_monster_spawned(self, bc: BattleContext, m: Monster) -> None:
        if self.has(RelicId.PHILOSOPHERS_STONE):
            # 新生怪物 +1 力量（initSpawnedMonster；与开局全体加成同源）
            m.statuses.add(MonsterStatus.STRENGTH, 1)

    def on_monster_unblocked_attack_damage(self, bc: BattleContext, damage: int) -> int:
        # THE_BOOT：Monster.cpp:340-342（attackedUnblockedHelper）
        if self.has(RelicId.THE_BOOT) and 0 < damage < 5:
            return 5
        return damage

    def on_monster_block_broken(self, bc: BattleContext, m: Monster) -> None:
        """HAND_DRILL：攻击把怪格挡打空（hadBlock && block==0）→ 2 层易伤
        （Monster.cpp:433-435，isSourceMonster=false）。

        已知近似（entities.py 本批次不可改，报告记录）：C++ 的 damage()
        非攻击路径打空格挡同样触发（L488-490）；本项目钩子仅挂在攻击路径。
        """
        if self.has(RelicId.HAND_DRILL):
            bc.add_to_bot(Actions.debuff_enemy(m.idx, MonsterStatus.VULNERABLE, 2, False))

    # ============================================================
    # 洗牌/消耗/抽牌/手牌
    # ============================================================
    def on_shuffle(self, bc: BattleContext) -> None:
        # THE_ABACUS：onShuffle L2796-2798
        if self.has(RelicId.THE_ABACUS):
            bc.add_to_bot(Actions.gain_block(6))
        # SUNDIAL：L2804-2811（计数 ==2 时 +2 能量并清零，即每 3 次）
        if self.has(RelicId.SUNDIAL):
            if self.bump(RelicId.SUNDIAL) == 3:
                self.set_counter(RelicId.SUNDIAL, 0)
                bc.add_to_bot(Actions.gain_energy(2))
        # MELANGE：SCRY 未迁移（批次 3+）

    def on_manual_discard(self, bc: BattleContext, inst: CardInstance) -> None:
        """弃牌触发遗物（批次 A：Silent 弃牌族用）。TingSha/Tough Bandages
        在 lightspeed 未实现（仅枚举），按 wiki 补：随机敌人 3 伤 / 得 3 格挡。"""
        if self.has(RelicId.TINGSHA):
            bc.add_to_bot(Actions.damage_random_enemy(3))
        if self.has(RelicId.TOUGH_BANDAGES):
            bc.add_to_bot(Actions.gain_block(3))

    def on_card_exhausted(self, bc: BattleContext, inst: CardInstance) -> None:
        # CHARONS_ASHES：L2819-2821——3 伤 + addToTop（批次 1 修正：
        # 原实现 2 伤 + addToBot 与 C++ 不符）
        if self.has(RelicId.CHARONS_ASHES):
            bc.add_to_top(Actions.damage_all_enemy(3))
        if self.has(RelicId.DEAD_BRANCH):
            # L2823-2826（triggerAndMoveToExhaustPile）：任意牌被消耗
            # （本钩子是一切消耗来源的统一入口：打出即消耗/Second Wind/
            # Fiend Fire/虚无等）→ 随机 1 张铁甲色牌（CombatCardPool，
            # CardPools.h:177-187，不含无色/状态/诅咒）addToBot 入手，
            # 未升级、原费用。抽样在钩子时点（对齐 C++ 在 trigger 内抽、
            # 动作只做入手），满手进弃牌堆（见 _temp_card_into_hand）。
            # misc 流抽样（C++ 用 cardRandomRng）。
            pool = _combat_card_pool()
            card = pool[bc.rngs.misc.int_inclusive(0, len(pool) - 1)]
            bc.add_to_bot(Action(lambda bc2, c=card: _temp_card_into_hand(bc2, c)))

    def on_hand_empty(self, bc: BattleContext) -> None:
        # UNCEASING_TOP：BattleContext.cpp:809-819（主循环手牌空 → 抽 1）
        if self.has(RelicId.UNCEASING_TOP):
            bc.add_to_bot(Actions.draw_cards(1))

    def keeps_hand_at_end_of_turn(self, bc: BattleContext) -> bool:
        """RUNIC_PYRAMID：回合末不弃手牌。"""
        return self.has(RelicId.RUNIC_PYRAMID)

    # ============================================================
    # 回合结束（callEndOfTurnActions L2032-2060，固定序）
    # ============================================================
    def on_end_turn(self, bc: BattleContext) -> None:
        # CLOAK_CLASP：L2036-2038（按手牌数获得格挡）
        if self.has(RelicId.CLOAK_CLASP):
            n = len(bc.cards.hand)
            if n > 0:
                bc.add_to_bot(Actions.gain_block(n))
        # ORICHALCUM：L2050-2054（block ≤ 0 时 addToTop +6）
        if self.has(RelicId.ORICHALCUM):
            if bc.player.block <= 0:
                bc.add_to_top(Actions.gain_block(6))
        # STONE_CALENDAR：L2056-2060——lightspeed turn==6 = 本项目第 7 回合，
        # 仅一次（批次 1 修正：原实现 turn>=7 每回合触发与 C++ 不符）
        if self.has(RelicId.STONE_CALENDAR) and bc.turn == 7:
            bc.add_to_bot(Actions.damage_all_enemy(52))
        # NILRYS_CODEX：L2046-2048（选卡 + 卡池，批次 3+）

    # ============================================================
    # 战斗结束（exitBattle L521-592：局外结算，治疗不经过战斗内
    # MAGIC_FLOWER 放大——g.playerHeal 直加）
    # ============================================================
    def on_victory(self, bc: BattleContext) -> None:
        p = bc.player
        # BURNING_BLOOD：L569-573
        if self.has(RelicId.BURNING_BLOOD):
            p.heal(6)
        # MEAT_ON_THE_BONE：L581-585（curHp ≤ maxHp/2，整数除法等价 hp*2 ≤ max）
        if self.has(RelicId.MEAT_ON_THE_BONE):
            if p.hp * 2 <= p.max_hp:
                p.heal(12)

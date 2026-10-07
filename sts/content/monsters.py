"""Act 1 怪物定义（对齐 lightspeed src/combat/MonsterSpecific.cpp）。

每个怪 = Monster 子类：
- hp_range：HP 均匀抽样区间（monster_hp 流；A0 基准）
- create(bc, idx)：构造（HP roll + 构造期 roll，如虱子的 Bite 伤害/Curl Up）
- get_move_for_roll：意图选择（ai 流 0..99 roll 分段 + 部分怪的内层布尔抽样，
  分段区间与内层概率逐行对齐 C++ getMoveForRoll）
- take_turn：按当前意图把动作入队 + 回合末 roll_move 生成下回合意图

意图可见性遵守 DESIGN.md §4.2：意图在怪物回合结束时才生成，
观测中物理上不存在未来值。

已移植：Cultist、Jaw Worm、Red/Green Louse、Acid/Spike Slime (S)、Fungi Beast、
Acid/Spike Slime (M)、Blue/Red Slaver、Sneaky/Fat/Shield Gremlin、Gremlin Wizard、
Sentry（批次 1）；Mad Gremlin、Gremlin Nob、Lagavulin、The Guardian、Hexaghost、
Taskmaster（批次 2）；Acid/Spike Slime (L)、Slime Boss、Looter、Mugger（批次 3）；
Act 2 全部新怪 15 种：Spheric Guardian、Chosen、Shelled Parasite、Byrd、
Snake Plant、Snecko、Centurion、Mystic、Gremlin Leader、Book of Stabbing、
Bronze Automaton、Bronze Orb、The Collector、Torch Head、The Champ（批次 B）。
A0 数值直取（`ascN ? x : y` 的 y），但伤害/状态量的进阶分支保留
（读 bc.ascension，A0 时自动落回非进阶值）。2026-10 全量审计补齐了
批次 1 漏移植的进阶档：A7 高位 HP（Cultist/Jaw Worm/虱子/小史莱姆/
真菌兽）、A2 伤害档（Chomp/Tackle、虱子 Bite 6-8）与 hallwayIdx 三档
能力值（Ritual/Grow/Bellow 力量、Curl Up A7/A17 档、Louse A17 出招约束、
Acid Slime S A17 固定 Lick），逐项与 wiki/反编译本体核对。

源码与任务描述/wiki 的出入（以 C++ 为准）：
- Red Louse 的副招是 Grow（力量+3），不是 Spit Web；Green Louse 才是
  Spit Web，且施加 2 层虚弱（DebuffPlayer<PS::WEAK>(2)）而非 3 层。
- Acid Slime (S) 的招式是 Lick（1 层虚弱）/ Tackle（3 伤）交替，
  没有 Corrosive Spit（那是 M/L 型的招式），因此不需要 Slimed 临时卡。
- Spike Slime (S) 只有 Tackle（5 伤），确定性出招（无 Lick）。
- Jaw Worm Thrash 为 7 伤 + 5 格挡（非 8 伤 + 3 格挡）。
- Spike Slime (M) 的 Lick 施加 FRAIL（脆弱）1 层而非 WEAK（C++ 源码
  DebuffPlayer<PS::FRAIL>(1)，默认 isSourceMonster=true）。
- Gremlin Wizard 充能无伤害（C++ CHARGING 只 ++miscInfo），充能计数
  挂 misc_info：开局 roll 时置 1，第 3 点切终极冲击；A0 冲击后清零重充
  （首轮充 2 回合，此后充 3 回合），A17 起不再重充（无限连发）。
- Red Slaver 的 usedEntangle（misc_info）：本体/wiki 为"整场一次"，
  但 lightspeed 从不置位（疑似漏写，会导致重复缠绕）——此处按本体
  语义在 Entangle 落地时置 1。
- Gremlin 帮逃跑（批次 3 定案：不实现）。lightspeed 的 doesEscapeNext
  从不置位（死代码，仅 Fat/Mad/Sneaky 的 takeTurn 残留分支，Shield/Wizard
  连分支都没有）；本体 wiki（Gremlins / Act 1 页）记载各小鬼招式无限循环、
  全站无任何小鬼逃跑条目，更新史仅剩"Weekly Patch 6：死掉的小鬼不再
  喊逃跑台词"一条 flavor 修正——StS1 小鬼帮没有逃跑机制。
  "3 回合后逃跑"的印象应源自 StS2（Gremlin Merc / Thieving Hopper 的
  Escape Artist 力量）。

批次 2 与本体/wiki 的出入（2026-10 全量审计后，以 wiki+反编译本体
（aeubanks/sts）为最终裁决，lightspeed 误译处已按本体修正）：
- Gremlin Nob A18：本体分支为 !lastMove(SKULL_BASH) && !lastMoveBefore
  (SKULL_BASH) → Skull Bash；lightspeed 误译成 lastTwoMoves(SKULL_BASH)
  （Skull Bash 不可达、恒 Rush），已按本体修正为 SB-R-R 循环。
- Lagavulin 自然醒：本体 changeState("OPEN") 两条醒来路径（打醒/自然醒）
  都会 ReducePowerAction(Metallicize, 8)；lightspeed 的 SLEEP 分支只
  setMove（ASLEEP/METALLICIZE 均残留），已按本体补移除。
- Hexaghost 的 Inferno 不塞 3 张升级灼伤、不升级已有灼伤（本体有此
  效果，lightspeed 未实现）；Sear 伤害恒 6、无进阶加成（同 lightspeed）。
- 回合计数映射：C++ bc.turn 0 基（首回合=0），本项目 1 基（首回合=1），
  涉及回合计数的条件统一 +1（Lagavulin 自然醒 2→3、灼伤升级 8→9）。

批次 3 与本体/wiki 的出入（数值一律以 C++ 为准，行为差异择本体/wiki
语义并逐处注明）：
- 大史莱姆/Slime Boss 分裂体的 max_hp = 父体**当前** HP（C++
  initSpawnedMonster 同时写 curHp/maxHp；wiki 只说"继承当前 HP"）。
  分布级后果：分裂体自身的半血再分裂阈值 = 父体当前 HP 的一半。
- Slime Boss 的 Preparing 无任何效果（C++ 该分支只 setMove(Slam)，
  无格挡/自 buff）；Goop Spray 的塞牌走 actFunc 立即结算（非入队）。
- Looter/Mugger 的逃跑链后 MUG 不再回归（C++ setMove 链），
  Looter 第 1 回合、Mugger 前 2 回合固定打劫；C++ 各分支为对话消息
  额外消耗的 aiRng roll（randomBoolean(0.6)/random(2)）不移植
  （RNG 轨迹对齐超出本项目范围，不影响分布）。
- C++ largeSlimeSplit 的 monsterCount 封顶 min(count+1, 4) 与
  "槽位覆写"语义：分裂第二体落在 idx+1 时覆写该槽（可达内容中仅
  Boss 分裂后的死亡占位槽），不后移存活怪——见 _large_slime_split。

批次 B（Act 2 怪物）与本体/wiki/C++ 的出入（数值一律以 C++ 为准）：
- 引擎无 MS::BARRICADE 枚举（types.py 禁改）：Spheric Guardian 的
  "格挡回合开始不清零"以子类覆盖 apply_start_of_turn_powers 实现
  （战斗前后语义与 C++ hasStatus<BARRICADE> 分支一致）。
- C++ 怪物侧回合钩子里的 FLIGHT 重置（Byrd 每回合开始若仍在飞回满
  3/4 层）与 MALLEABLE 重置（Snake Plant 回合末回满 3 层）引擎未做
  （entities.py 禁改），以子类覆盖对应钩子实现，语义一致。
- 静滞偷牌的稀有度偏好（C++ stasisHelper：RARE > UNCOMMON > COMMON
  组内随机，全 BASIC 才均匀）：CardDef 无 rarity 字段，改为整堆均匀
  随机（misc 流）。对起手牌组（全 BASIC）与 C++ 分布完全一致。
- Chosen 的 HEX：本体为"每打出一张非攻击牌，洗 X 张眩晕进抽牌堆"
  （HexPower.onUseCard 的 card.type != ATTACK 判定）；引擎 use_card 对
  任意牌触发（battle.py 禁改）——攻击牌也被计为巫咒触发，需引擎接线
  （见审计报告）。
- Bronze Orb 偷到的牌：本体死亡时回到手中，引擎 die() 归还进弃牌堆
  （引擎既有语义）。
- Book of Stabbing A18：本体 ++stabCount 真实可达（选 Single Stab 也
  +1）；lightspeed 误译到 return 之后成死代码，已按本体补回。
- wiki 记载与 lightspeed 冲突处的裁决（反编译本体为准）：Spheric
  Guardian Activate 格挡 A17 起 35（wiki 同）；Gremlin Leader Encourage
  格挡 A18 起 10（lightspeed 误 asc3，已修）；Automaton Boost 格挡 A9 起
  12（wiki 同）；Bronze Orb / Torch Head 高位 HP 从 A9 起（wiki 同）；
  The Champ Gloat 力量 {2,3,4}@A4/A19（lightspeed 误 {3,4,5}，已修）；
  Collector Mega Debuff A19 起 5 层（lightspeed 误恒 3，已修）。

批次 D（Act 3 全部新怪 17 种 + Act 4 3 种）与本体/wiki/C++/引擎的出入
（数值一律以 C++ 为准；引擎缺口以内容层钩子对齐，见各类 docstring）：
- Darkling Nip 伤害的 A2 加成被 lightspeed 双重施加（construct 已按
  A2 roll 9-13，take_turn 又 +2 → 11-15，源码自留 todo 注释）；本体/
  wiki 为 9-13，此处按 construct 档 roll、不加 take_turn 的 +2。
- Darkling REGROW 的全灭判定：C++ die() 先扣存活数，归零即判胜——
  最后一只死不走 REGROW（同时全灭 = 直接胜利）；非最后死亡则假死、
  两个自身回合后以 maxHp//2 复活并重挂 REGROW（可反复）。引擎通用
  REGROW 分支（die() 满血复活、不减存活数）与 C++ 不同，内容层以
  die() 覆盖对齐；half_dead 怪的回合参与（C++ doMonsterTurn 对
  halfDead 也调 takeTurn）由 _HalfDeadMonsterGroup 提供，遭遇装配方
  安装（同 Awakened One）。
- TIME_WARP / SLOW 的 0 层起点（C++ setHasStatus(true)+setStatus(0)）：
  引擎 Statuses.has 以层数 >0 判定会漏计，_ZeroBasedStatuses 覆盖
  has() 使 Time Eater 第 12 张牌触发、Giant Head 首张牌起 +10%，
  且触发后归零继续计数（引擎 set(...,0) 后 has 为假的问题同修）。
- Giant Head 的 SLOW 乘区在 C++ calculateCardDamage（玩家出伤管线，
  引擎未接线）：以 attacked() 覆盖近似——×(1+0.1×(层-1))（C++ 出牌
  时快照、引擎动作执行时计数已含当前牌，故 -1），floor 时点差异
  见类注释。
- Nemesis 的 INTANGIBLE 回合末衰减（Monster.cpp:55-57）引擎未做，
  apply_end_of_turn_triggers 覆盖补。
- Writhing Mass 的 REACTIVE 仅首次受击重掷意图（Monster.cpp:375-381），
  引擎 attacked() 每击都重掷——以 attacked() 覆盖对齐；Implant 不塞
  Parasite（内容层无此诅咒卡，C++ 亦未建模，仅 OMAMORI/DARKSTONE
  残码不移植）。
- Spire Growth 的 CONSTRICTED 玩家状态（回合末掉血）引擎无枚举无结算：
  以 player.special["constricted"] 计数 + 怪物回合开始时结算掉血近似
  （时序对齐：本体在玩家回合末、怪物攻击前；怪死后不再结算，本体为
  常驻 debuff）——需引擎接线，见批次报告。
- Spire Shield 的 SURROUNDED：状态已施加，但"攻击非面向者 ×1.5"
  伤害引擎无 lastTargetedMonster 追踪未接线——见批次报告。
- Corrupt Heart 的 INVINCIBLE：引擎分支语义（cap=20+misc_info，溢出
  按 //10 记账）与 C++ 池语义（单次钳剩余池、池随伤害扣减、回合开始
  回满）不同——内容层以 unique_power0 存池 + apply_start_of_turn/
  on_hp_lost 回写 misc_info 对齐；非攻击 HP 损失（毒）引擎仍漏钳，
  见类注释。
- Awakened One A9+ 一阶段 HP 恒 320（本体 setHp(320)；lightspeed 误为
  300-320 区间抽样，已修）；二阶段 REBIRTH 固定 300/320 满血。阶段 1
  死亡不判胜（C++ 分支先于判胜检查，即使场上只剩 Boss）。
- Time Eater Head Slam 塞 2 张 Slimed 恒为 A19 分支（wiki 同）；Haste
  为"设为半血"而非"回复到半血"（C++ curHp = maxHp/2；本体 HealAction
  (maxHp/2 - curHp) 仅在半血以下触发，两者等价）。
- Darkling Chomp 为两段攻击（本体两次 DamageAction；lightspeed 单发，
  已修）；Nemesis 第二击 A18 起塞 5 张灼伤（lightspeed 误 asc3，已修）；
  Writhing Mass 连枷的格挡 = 基础连枷伤害 15/16@A2（本体；lightspeed
  误 16/18，已修）；Byrd Flying 飞行中受攻击伤害减半（本体 FlightPower
  atDamageFinalReceive；引擎未接线该乘区，以 attacked 覆盖补）；Centurion
  Protect 在秘术师死亡后给自身格挡（本体 GainBlockRandomMonsterAction）。
- Exploder / Dagger 的自爆 = C++ SuicideAction(triggerRelics=true)：
  对自身施加全额非攻击伤害走 die() 结算；Transient 走引擎 FADING
  回合末逃跑（C++ 于自己回合内 suicideAction，时机等价：均在第 5/6
  次攻击后离场）。
- Reptomancer 召唤的新匕首本回合不行动（C++ skipTurn 位图）：
  以 monster_turn_idx 前跳等效跳过（同批次 B 青铜球先例）。
- Jaw Worm Horde：C++ 给 3 只颚虫塞非 INVALID 占位意图使其跳过
  "首回合固定 Chomp"——JawWorm 的 firstTurn 判定由 turns_taken==0
  改为 not move_history（C++ firstTurn() 语义，普通遭遇行为不变），
  遭遇装配塞 _HORDE_PLACEHOLDER。
- Pointy / Romeo / Bear（红面具帮与角斗场事件怪）不在 Act 3 常规
  池内，未移植；Reptomancer 的随从是 Dagger（匕首），与 Pointy 无关。
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import TYPE_CHECKING

from sts.combat.actions import Actions
from sts.combat.entities import Monster, MonsterGroup
from sts.combat.queue import Action
from sts.combat.types import MonsterStatus, Outcome, PlayerStatus, Statuses
from sts.content.cards import BURN, DAZED, SLIMED, VOID, WOUND

if TYPE_CHECKING:
    from sts.combat.battle import BattleContext


@dataclass(frozen=True)
class MoveDef:
    name: str
    zh: str
    kind: str  # "attack" | "buff" | "debuff" | "defend" | "unknown"
    base_damage: int | None = None  # attack 招式的基础伤害（意图展示与结算共用）
    intent_text: str = ""  # 非攻击招式的意图展示文本


# ---- 出招历史辅助（对齐 lightspeed lastMove / lastTwoMoves）----
# roll 时机（take_turn 尾部的 roll_move）：move_history[0] 是刚执行的招式，
# [1] 是上一回合的——与 C++ moveHistory 双槽语义一致。


def _last(m: Monster, name: str) -> bool:
    return bool(m.move_history) and m.move_history[0].name == name


def _last_two(m: Monster, name: str) -> bool:
    return len(m.move_history) >= 2 and all(x.name == name for x in m.move_history[:2])


def _last_before(m: Monster, name: str) -> bool:
    """上上回合招式（对齐 C++ lastMoveBefore：moveHistory[1]）。

    move_history 长度 < 2 时 C++ 双槽中 [1] 仍为 INVALID——调用处以
    `len < 2` 表达 lastMoveBefore(INVALID)。
    """
    return len(m.move_history) >= 2 and m.move_history[1].name == name


def _ai_boolean(bc: BattleContext, chance: float) -> bool:
    """内层布尔抽样（对齐 lightspeed aiRng.randomBoolean(chance) 的分布）。

    DESIGN.md §3 不做轨迹对齐，用万分位整数抽样近似连续 uniform：
    0.5625/0.357/0.416/0.5 均可被 10000 精确整除，分布完全一致。
    """
    return bc.rngs.ai.int_inclusive(0, 9999) < round(chance * 10000)


class Cultist(Monster):
    """邪教徒（Act 1 普通怪单怪遭遇）。

    数据来源 slaythespire.wiki.gg/wiki/Cultist：
      HP 48-54（A7 起 50-56）；第 1 回合咒语（3 层仪式，A2 起 4、A17 起
      5——wiki/Cultist.java/三档数组 {3,4,5}[hallwayIdx]），此后每回合
      黑暗打击 6 伤。出招完全确定。黑暗打击序列 6, 9, 12, …（Ritual
      回合末 +3，施加当轮 skipFirst 跳过——见 combat/entities.py 的衰减逻辑）。
    """

    name = "Cultist"
    zh = "邪教徒"
    hp_range = (48, 54)
    hp_range_high = (50, 56)

    INCANTATION = MoveDef("Incantation", "念咒", "buff", intent_text="获得 3 层仪式")
    DARK_STRIKE = MoveDef("Dark Strike", "黑暗打击", "attack", base_damage=6)

    def __init__(self, idx: int, hp: int, max_hp: int):
        super().__init__(idx, hp, max_hp, "邪教徒(Cultist)")

    @classmethod
    def create(cls, bc: BattleContext, idx: int) -> "Cultist":
        hp = _roll_hp(bc, cls)
        return cls(idx, hp, hp)

    def get_move_for_roll(self, bc: BattleContext, roll: int) -> MoveDef:
        # 出招完全确定：首回合咒语，之后每回合黑暗打击
        if self.turns_taken == 0:
            return self.INCANTATION
        return self.DARK_STRIKE

    def take_turn(self, bc: BattleContext) -> None:
        move = self.move_history[0]
        match move.name:
            case "Incantation":
                # buff<RITUAL> 自带 justApplied（skipFirst）：见 entities.Monster.buff
                ritual = 5 if bc.ascension >= 17 else 4 if bc.ascension >= 2 else 3
                self.buff(MonsterStatus.RITUAL, ritual)
                bc.log.append(f"{self.display_name} 使用 念咒(Incantation)，获得 {ritual} 层仪式。")
            case "Dark Strike":
                dmg = bc.calculate_monster_damage(self, 6)
                bc.log.append(f"{self.display_name} 使用 黑暗打击(Dark Strike)。")
                bc.add_to_bot(Actions.attack_player(self.idx, dmg))
            case _:
                raise AssertionError(f"未知招式 {move}")
        # 回合末生成下回合意图（对齐 lightspeed takeTurn 尾部的 RollMove）
        bc.add_to_bot(Actions.roll_move(self.idx))
        self.turns_taken += 1


class JawWorm(Monster):
    """颚虫（Act 1 单怪遭遇，也可能是首个精英后的普通遭遇）。

    wiki/C++ A0：HP 40-44（A7 起 42-46）。首回合固定 Chomp（11 伤，A2 起
    12）；之后 roll 分段：
      roll < 25：上回合 Chomp → 内层 56.25% Bellow / 否则 Thrash；
                 否则 Chomp
      roll < 55：上上两回合都是 Thrash → 内层 35.7% Chomp / 否则 Bellow；
                 否则 Thrash
      roll ≥ 55：上回合 Bellow → 内层 41.6% Chomp / 否则 Thrash；
                 否则 Bellow
    招式数值：Chomp 11 伤（A2 起 12）；Thrash 7 伤 + 5 格挡；Bellow
    力量 +3（A2 起 4、A17 起 5——wiki/JawWorm.java 三档数组）+ 6 格挡
    （A17 起 9）。
    """

    name = "Jaw Worm"
    zh = "大颚虫"
    hp_range = (40, 44)
    hp_range_high = (42, 46)

    CHOMP = MoveDef("Chomp", "重咬", "attack", base_damage=11)
    THRASH = MoveDef("Thrash", "抽打", "attack", base_damage=7)  # 另获 5 格挡
    BELLOW = MoveDef("Bellow", "咆哮", "buff", intent_text="力量+3，格挡+6")

    def __init__(self, idx: int, hp: int, max_hp: int):
        super().__init__(idx, hp, max_hp, "大颚虫(Jaw Worm)")

    @classmethod
    def create(cls, bc: BattleContext, idx: int) -> "JawWorm":
        hp = _roll_hp(bc, cls)
        return cls(idx, hp, hp)

    def get_move_for_roll(self, bc: BattleContext, roll: int) -> MoveDef:
        # firstTurn()（moveHistory[0] == INVALID）：首回合固定 Chomp。
        # 批次 D 起由 turns_taken==0 改判 move_history（C++ firstTurn 语义，
        # 普通遭遇等价；Jaw Worm Horde 借占位意图跳过此特例）。
        if not self.move_history:
            return self.CHOMP
        if roll < 25:
            if _last(self, "Chomp"):
                return self.BELLOW if _ai_boolean(bc, 0.5625) else self.THRASH
            return self.CHOMP
        if roll < 55:
            if _last_two(self, "Thrash"):
                return self.CHOMP if _ai_boolean(bc, 0.357) else self.BELLOW
            return self.THRASH
        if _last(self, "Bellow"):
            return self.CHOMP if _ai_boolean(bc, 0.416) else self.THRASH
        return self.BELLOW

    def take_turn(self, bc: BattleContext) -> None:
        move = self.move_history[0]
        match move.name:
            case "Chomp":
                dmg = bc.calculate_monster_damage(self, 12 if bc.ascension >= 2 else 11)
                bc.log.append(f"{self.display_name} 使用 重咬(Chomp)。")
                bc.add_to_bot(Actions.attack_player(self.idx, dmg))
            case "Thrash":
                dmg = bc.calculate_monster_damage(self, 7)
                bc.log.append(f"{self.display_name} 使用 抽打(Thrash)。")
                bc.add_to_bot(Actions.attack_player(self.idx, dmg))
                bc.add_to_bot(Actions.monster_gain_block(self.idx, 5))
            case "Bellow":
                # 力量立即结算（对齐 C++ buff<MS::STRENGTH>，不入队）；格挡入队
                str_gain = 5 if bc.ascension >= 17 else 4 if bc.ascension >= 2 else 3
                self.statuses.add(MonsterStatus.STRENGTH, str_gain)
                bc.log.append(f"{self.display_name} 使用 咆哮(Bellow)，力量+{str_gain}。")
                bc.add_to_bot(Actions.monster_gain_block(self.idx, 9 if bc.ascension >= 17 else 6))
            case _:
                raise AssertionError(f"未知招式 {move}")
        bc.add_to_bot(Actions.roll_move(self.idx))
        self.turns_taken += 1


class Louse(Monster):
    """虱子公共基类（红虱/绿虱共享的构造与 Bite）。

    构造期 roll（对齐 C++ construct + preBattleAction 与本体 LouseNormal.java，
    均走 monsterHpRng）：
      1. HP（红虱 10-15 / 绿虱 11-17；A7 起红虱 11-16 / 绿虱 12-18）
      2. Bite 伤害 5-7（A2 起 6-8；construct 的 miscInfo，战斗开始定死）
      3. Curl Up 3-7（A7 起 4-8、A17 起 9-12；preBattleAction；首次受击
         获得等量格挡，结算钩子在 entities.Monster.attacked 的 CURL_UP 分支）
    出招约束：25% 副招 / 75% Bite，同一招不连续三回合（roll<25 时若副招
    已连续两回合（A17 起上回合出过副招即算）则改出 Bite；roll≥25 时若
    Bite 已连续两回合则出副招）。
    """

    name = "Louse"
    zh = "虱虫"
    hp_range = (10, 15)  # 子类覆盖

    def __init__(self, idx: int, hp: int, max_hp: int, display_name: str, bite_dmg: int, curl_up: int):
        super().__init__(idx, hp, max_hp, display_name)
        self.bite_dmg = bite_dmg
        # Bite 伤害逐实例不同：MoveDef 挂在实例上（意图展示用同一份数值）
        self.BITE = MoveDef("Bite", "啃咬", "attack", base_damage=bite_dmg)
        self.statuses.add(MonsterStatus.CURL_UP, curl_up)

    @classmethod
    def create(cls, bc: BattleContext, idx: int) -> "Louse":
        hp = _roll_hp(bc, cls)
        bite = bc.rngs.monster_hp.int_inclusive(6, 8) if bc.ascension >= 2 \
            else bc.rngs.monster_hp.int_inclusive(5, 7)
        if bc.ascension >= 17:
            curl = bc.rngs.monster_hp.int_inclusive(9, 12)
        elif bc.ascension >= 7:
            curl = bc.rngs.monster_hp.int_inclusive(4, 8)
        else:
            curl = bc.rngs.monster_hp.int_inclusive(3, 7)
        return cls(idx, hp, hp, f"{cls.zh}({cls.name})", bite, curl)

    def _bite_turn(self, bc: BattleContext) -> None:
        dmg = bc.calculate_monster_damage(self, self.bite_dmg)
        bc.log.append(f"{self.display_name} 使用 啃咬(Bite)。")
        bc.add_to_bot(Actions.attack_player(self.idx, dmg))

    def _second_move_turn(self, bc: BattleContext) -> None:
        raise NotImplementedError

    def get_move_for_roll(self, bc: BattleContext, roll: int) -> MoveDef:
        second = self._second_move()
        if roll < 25:
            # 对齐 C++/LouseNormal.java：lastMove(副招) 且（A17 或副招已连续
            # 两回合）→ 改出 Bite（wiki：A17 起副招不连续两回合）
            if _last(self, second.name) and (bc.ascension >= 17 or _last_two(self, second.name)):
                return self.BITE
            return second
        if _last_two(self, "Bite"):
            return second
        return self.BITE

    def _second_move(self) -> MoveDef:
        raise NotImplementedError

    def take_turn(self, bc: BattleContext) -> None:
        move = self.move_history[0]
        match move.name:
            case "Bite":
                self._bite_turn(bc)
            case _:
                self._second_move_turn(bc)
        bc.add_to_bot(Actions.roll_move(self.idx))
        self.turns_taken += 1


class RedLouse(Louse):
    """红虱：Bite 5-7 伤（A2 起 6-8）/ Grow 力量+3（A17 起为 +4）。
    HP 10-15（A7 起 11-16）。"""

    name = "Red Louse"
    zh = "虱虫"
    hp_range = (10, 15)
    hp_range_high = (11, 16)

    GROW = MoveDef("Grow", "成长", "buff", intent_text="力量+3")

    def _second_move(self) -> MoveDef:
        return self.GROW

    def _second_move_turn(self, bc: BattleContext) -> None:
        amt = 4 if bc.ascension >= 17 else 3
        self.statuses.add(MonsterStatus.STRENGTH, amt)
        bc.log.append(f"{self.display_name} 使用 成长(Grow)，力量+{amt}。")


class GreenLouse(Louse):
    """绿虱：Bite 5-7 伤（A2 起 6-8）/ Spit Web 施加 2 层虚弱。
    HP 11-17（A7 起 12-18）。

    虚弱为怪物施加（isSourceMonster=True）：justApplied 跳过首个回合末衰减
    （对齐 C++ DebuffPlayer<PS::WEAK>(2) 的默认参数）。
    """

    name = "Green Louse"
    zh = "虱虫"
    hp_range = (11, 17)
    hp_range_high = (12, 18)

    SPIT_WEB = MoveDef("Spit Web", "吐网", "debuff", intent_text="施加 2 层虚弱")

    def _second_move(self) -> MoveDef:
        return self.SPIT_WEB

    def _second_move_turn(self, bc: BattleContext) -> None:
        bc.log.append(f"{self.display_name} 使用 吐网(Spit Web)。")
        bc.add_to_bot(Actions.debuff_player(PlayerStatus.WEAK, 2, True))


class AcidSlimeS(Monster):
    """酸液史莱姆（小）：Lick 1 层虚弱 / Tackle 3 伤。

    wiki/C++ A0：HP 8-12（A7 起 9-13）。首回合 50/50 抽 Lick 或 Tackle
    （内层 aiRng randomBoolean，roll 参数本身不用；A17 起固定 Lick——
    AcidSlime_S.java 的 getMove A17 分支），此后两招严格交替——take_turn
    直接 set_move 切换、不再消耗 ai 流（对齐 C++ ACID_SLIME_S 分支无 RollMove）。
    """

    name = "Acid Slime (S)"
    zh = "酸液史莱姆（小）"
    hp_range = (8, 12)
    hp_range_high = (9, 13)

    LICK = MoveDef("Lick", "舔舐", "debuff", intent_text="施加 1 层虚弱")
    TACKLE = MoveDef("Tackle", "冲撞", "attack", base_damage=3)

    def __init__(self, idx: int, hp: int, max_hp: int):
        super().__init__(idx, hp, max_hp, "酸液史莱姆（小）(Acid Slime (S))")

    @classmethod
    def create(cls, bc: BattleContext, idx: int) -> "AcidSlimeS":
        hp = _roll_hp(bc, cls)
        return cls(idx, hp, hp)

    def get_move_for_roll(self, bc: BattleContext, roll: int) -> MoveDef:
        # A17 起固定 Lick；A0 为 50/50。roll 参数不参与（对齐 C++）
        if bc.ascension >= 17:
            return self.LICK
        return self.TACKLE if _ai_boolean(bc, 0.5) else self.LICK

    def take_turn(self, bc: BattleContext) -> None:
        move = self.move_history[0]
        match move.name:
            case "Lick":
                bc.log.append(f"{self.display_name} 使用 舔舐(Lick)。")
                bc.add_to_bot(Actions.debuff_player(PlayerStatus.WEAK, 1, True))
                self.set_move(self.TACKLE)  # 严格交替：下回合固定为另一招
            case "Tackle":
                dmg = bc.calculate_monster_damage(self, 4 if bc.ascension >= 2 else 3)
                bc.log.append(f"{self.display_name} 使用 冲撞(Tackle)。")
                bc.add_to_bot(Actions.attack_player(self.idx, dmg))
                self.set_move(self.LICK)
            case _:
                raise AssertionError(f"未知招式 {move}")
        self.turns_taken += 1


class SpikeSlimeS(Monster):
    """尖刺史莱姆（小）：只有 Tackle 5 伤，确定性出招。

    wiki/C++ A0：HP 10-14（A7 起 11-15）。getMoveForRoll 无条件返回 TACKLE
    （任务描述中的 Lick 属于 M/L 型，小尖刺没有）。take_turn 不切招、不
    roll，仅入队 NoOpRollMove 占位（对齐 lightspeed 的 RNG 消耗语义）。
    Tackle 5 伤（A2 起 6）。
    """

    name = "Spike Slime (S)"
    zh = "尖刺史莱姆（小）"
    hp_range = (10, 14)
    hp_range_high = (11, 15)

    TACKLE = MoveDef("Tackle", "冲撞", "attack", base_damage=5)

    def __init__(self, idx: int, hp: int, max_hp: int):
        super().__init__(idx, hp, max_hp, "尖刺史莱姆（小）(Spike Slime (S))")

    @classmethod
    def create(cls, bc: BattleContext, idx: int) -> "SpikeSlimeS":
        hp = _roll_hp(bc, cls)
        return cls(idx, hp, hp)

    def get_move_for_roll(self, bc: BattleContext, roll: int) -> MoveDef:
        return self.TACKLE

    def take_turn(self, bc: BattleContext) -> None:
        dmg = bc.calculate_monster_damage(self, 6 if bc.ascension >= 2 else 5)
        bc.log.append(f"{self.display_name} 使用 冲撞(Tackle)。")
        bc.add_to_bot(Actions.attack_player(self.idx, dmg))
        bc.add_to_bot(Actions.no_op_roll_move())
        self.turns_taken += 1


class FungiBeast(Monster):
    """真菌兽：Bite 6 伤 / Grow 力量+3；死亡时孢子云（2 层易伤）。

    wiki/C++ A0：HP 22-28（A7 起 24-28）。roll 分段：
      roll < 60：Bite 已连续两回合 → Grow，否则 Bite
      roll ≥ 60：上回合 Grow → Bite，否则 Grow
    Grow 力量 +3（A2 起 4、A17 起 5——wiki/FungiBeast.java 三档数组）。
    孢子云（对齐 C++ preBattleAction 的 buff<SPORE_CLOUD>(2) 与 die 的
    SPORE_CLOUD 分支）：死亡时给玩家 2 层易伤，结算钩子在
    entities.Monster.die；最后一只死亡时战斗已结束，不再施加。
    """

    name = "Fungi Beast"
    zh = "真菌兽"
    hp_range = (22, 28)
    hp_range_high = (24, 28)

    BITE = MoveDef("Bite", "撕咬", "attack", base_damage=6)
    GROW = MoveDef("Grow", "生长", "buff", intent_text="力量+3")

    def __init__(self, idx: int, hp: int, max_hp: int):
        super().__init__(idx, hp, max_hp, "真菌兽(Fungi Beast)")
        # 对齐 C++ preBattleAction：SporeCloudPower 恒为 2
        self.statuses.add(MonsterStatus.SPORE_CLOUD, 2)

    @classmethod
    def create(cls, bc: BattleContext, idx: int) -> "FungiBeast":
        hp = _roll_hp(bc, cls)
        return cls(idx, hp, hp)

    def get_move_for_roll(self, bc: BattleContext, roll: int) -> MoveDef:
        if roll < 60:
            if _last_two(self, "Bite"):
                return self.GROW
            return self.BITE
        if _last(self, "Grow"):
            return self.BITE
        return self.GROW

    def take_turn(self, bc: BattleContext) -> None:
        move = self.move_history[0]
        match move.name:
            case "Bite":
                dmg = bc.calculate_monster_damage(self, 6)
                bc.log.append(f"{self.display_name} 使用 撕咬(Bite)。")
                bc.add_to_bot(Actions.attack_player(self.idx, dmg))
            case "Grow":
                str_gain = 5 if bc.ascension >= 17 else 4 if bc.ascension >= 2 else 3
                self.statuses.add(MonsterStatus.STRENGTH, str_gain)
                bc.log.append(f"{self.display_name} 使用 生长(Grow)，力量+{str_gain}。")
            case _:
                raise AssertionError(f"未知招式 {move}")
        bc.add_to_bot(Actions.roll_move(self.idx))
        self.turns_taken += 1


# ====================================================================
# 批次 1：简单档 Act 1 怪物（Acid/Spike Slime M、Blue/Red Slaver、
# Gremlin ×4、Sentry）。数值/分段逐行对齐 MonsterSpecific.cpp，wiki 交叉校验。
# ====================================================================


def _roll_hp(bc: BattleContext, cls: type[Monster]) -> int:
    """HP 抽样（对齐 C++ initHp/setRandomHp：进阶 7 起用高位区间，Sentry 为 8）。"""
    if bc.ascension >= getattr(cls, "hp_high_asc", 7):
        return bc.rngs.monster_hp.int_inclusive(*cls.hp_range_high)
    return bc.rngs.monster_hp.int_inclusive(*cls.hp_range)


class AcidSlimeM(Monster):
    """酸液史莱姆（中）：Corrosive Spit 7 伤 + 塞 1 张黏液 / Lick 1 层虚弱 / Tackle 10 伤。

    wiki/C++ A0：HP 28-32（A7 起 29-34）。roll 分段（A0）：
      roll < 30：Corrosive Spit 已连续两回合 → 内层 50% Tackle / 50% Lick；
                 否则 Corrosive Spit
      roll < 70：上回合 Tackle → 内层 40% Corrosive Spit / 否则 Lick；
                 否则 Tackle
      roll ≥ 70：Lick 已连续两回合 → 内层 40% Corrosive Spit / 否则 Tackle；
                 否则 Lick
    A17 起分段改为 40/80 + lastMove(Lick)（对齐 C++ START ASCENSION 17 段）。
    """

    name = "Acid Slime (M)"
    zh = "酸液史莱姆（中）"
    hp_range = (28, 32)
    hp_range_high = (29, 34)

    CORROSIVE_SPIT = MoveDef("Corrosive Spit", "腐蚀喷吐", "attack", base_damage=7)
    LICK = MoveDef("Lick", "舔舔", "debuff", intent_text="施加 1 层虚弱")
    TACKLE = MoveDef("Tackle", "冲撞", "attack", base_damage=10)

    def __init__(self, idx: int, hp: int, max_hp: int):
        super().__init__(idx, hp, max_hp, "酸液史莱姆（中）(Acid Slime (M))")

    @classmethod
    def create(cls, bc: BattleContext, idx: int) -> "AcidSlimeM":
        hp = _roll_hp(bc, cls)
        return cls(idx, hp, hp)

    def get_move_for_roll(self, bc: BattleContext, roll: int) -> MoveDef:
        if bc.ascension >= 17:
            # A17：40/80 分段，末段判 lastMove(Lick)
            if roll < 40:
                if _last_two(self, "Corrosive Spit"):
                    return self.TACKLE if _ai_boolean(bc, 0.5) else self.LICK
                return self.CORROSIVE_SPIT
            if roll < 80:
                if _last_two(self, "Tackle"):
                    return self.CORROSIVE_SPIT if _ai_boolean(bc, 0.5) else self.LICK
                return self.TACKLE
            if _last(self, "Lick"):
                return self.CORROSIVE_SPIT if _ai_boolean(bc, 0.4) else self.TACKLE
            return self.LICK
        if roll < 30:
            if _last_two(self, "Corrosive Spit"):
                return self.TACKLE if _ai_boolean(bc, 0.5) else self.LICK
            return self.CORROSIVE_SPIT
        if roll < 70:
            if _last(self, "Tackle"):
                return self.CORROSIVE_SPIT if _ai_boolean(bc, 0.4) else self.LICK
            return self.TACKLE
        if _last_two(self, "Lick"):
            return self.CORROSIVE_SPIT if _ai_boolean(bc, 0.4) else self.TACKLE
        return self.LICK

    def take_turn(self, bc: BattleContext) -> None:
        move = self.move_history[0]
        match move.name:
            case "Corrosive Spit":
                dmg = bc.calculate_monster_damage(self, 8 if bc.ascension >= 2 else 7)
                bc.log.append(f"{self.display_name} 使用 腐蚀喷吐(Corrosive Spit)。")
                bc.add_to_bot(Actions.attack_player(self.idx, dmg))
                bc.add_to_bot(Actions.make_temp_card_in_discard(SLIMED))
            case "Lick":
                bc.log.append(f"{self.display_name} 使用 舔舔(Lick)。")
                bc.add_to_bot(Actions.debuff_player(PlayerStatus.WEAK, 1, True))
            case "Tackle":
                dmg = bc.calculate_monster_damage(self, 12 if bc.ascension >= 2 else 10)
                bc.log.append(f"{self.display_name} 使用 冲撞(Tackle)。")
                bc.add_to_bot(Actions.attack_player(self.idx, dmg))
            case _:
                raise AssertionError(f"未知招式 {move}")
        bc.add_to_bot(Actions.roll_move(self.idx))
        self.turns_taken += 1


class SpikeSlimeM(Monster):
    """尖刺史莱姆（中）：Lick 1 层脆弱 / Flame Tackle 8 伤 + 塞 1 张黏液。

    wiki/C++ A0：HP 28-32（A7 起 29-34）。注意 Lick 施加的是 FRAIL
    （C++ DebuffPlayer<PS::FRAIL>(1)，默认 isSourceMonster=true），
    不是 WEAK。roll 分段（A0）：
      roll < 30：Flame Tackle 已连续两回合 → Lick；否则 Flame Tackle
      roll ≥ 30：Lick 已连续两回合（A17 起上回合即算）→ Flame Tackle；
                 否则 Lick
    """

    name = "Spike Slime (M)"
    zh = "尖刺史莱姆（中）"
    hp_range = (28, 32)
    hp_range_high = (29, 34)

    LICK = MoveDef("Lick", "舔舔", "debuff", intent_text="施加 1 层脆弱")
    FLAME_TACKLE = MoveDef("Flame Tackle", "烈焰冲撞", "attack", base_damage=8)

    def __init__(self, idx: int, hp: int, max_hp: int):
        super().__init__(idx, hp, max_hp, "尖刺史莱姆（中）(Spike Slime (M))")

    @classmethod
    def create(cls, bc: BattleContext, idx: int) -> "SpikeSlimeM":
        hp = _roll_hp(bc, cls)
        return cls(idx, hp, hp)

    def get_move_for_roll(self, bc: BattleContext, roll: int) -> MoveDef:
        if roll < 30:
            if _last_two(self, "Flame Tackle"):
                return self.LICK
            return self.FLAME_TACKLE
        if _last_two(self, "Lick") or (bc.ascension >= 17 and _last(self, "Lick")):
            return self.FLAME_TACKLE
        return self.LICK

    def take_turn(self, bc: BattleContext) -> None:
        move = self.move_history[0]
        match move.name:
            case "Lick":
                bc.log.append(f"{self.display_name} 使用 舔舔(Lick)。")
                bc.add_to_bot(Actions.debuff_player(PlayerStatus.FRAIL, 1, True))
            case "Flame Tackle":
                dmg = bc.calculate_monster_damage(self, 10 if bc.ascension >= 2 else 8)
                bc.log.append(f"{self.display_name} 使用 烈焰冲撞(Flame Tackle)。")
                bc.add_to_bot(Actions.attack_player(self.idx, dmg))
                bc.add_to_bot(Actions.make_temp_card_in_discard(SLIMED))
            case _:
                raise AssertionError(f"未知招式 {move}")
        bc.add_to_bot(Actions.roll_move(self.idx))
        self.turns_taken += 1


class BlueSlaver(Monster):
    """蓝奴役者：Stab 12 伤 / Rake 7 伤 + 1 层虚弱（A17 起 2 层）。

    wiki/C++ A0：HP 46-50（A7 起 48-52）。roll 分段（无首回合特例）：
      roll ≥ 40 且 Stab 未连续两回合 → Stab
      否则 Rake 未连续两回合（A17 起上回合出过 Rake 即算）→ Rake
      否则 Stab
    """

    name = "Blue Slaver"
    zh = "奴隶贩子"
    hp_range = (46, 50)
    hp_range_high = (48, 52)

    STAB = MoveDef("Stab", "刺击", "attack", base_damage=12)
    RAKE = MoveDef("Rake", "耙伤", "attack", base_damage=7)  # 另施加 1 层虚弱

    def __init__(self, idx: int, hp: int, max_hp: int):
        super().__init__(idx, hp, max_hp, "奴隶贩子(Blue Slaver)")

    @classmethod
    def create(cls, bc: BattleContext, idx: int) -> "BlueSlaver":
        hp = _roll_hp(bc, cls)
        return cls(idx, hp, hp)

    def get_move_for_roll(self, bc: BattleContext, roll: int) -> MoveDef:
        if roll >= 40 and not _last_two(self, "Stab"):
            return self.STAB
        if not _last_two(self, "Rake") or (bc.ascension >= 17 and not _last(self, "Rake")):
            return self.RAKE
        return self.STAB

    def take_turn(self, bc: BattleContext) -> None:
        move = self.move_history[0]
        match move.name:
            case "Stab":
                dmg = bc.calculate_monster_damage(self, 13 if bc.ascension >= 2 else 12)
                bc.log.append(f"{self.display_name} 使用 刺击(Stab)。")
                bc.add_to_bot(Actions.attack_player(self.idx, dmg))
            case "Rake":
                dmg = bc.calculate_monster_damage(self, 8 if bc.ascension >= 2 else 7)
                bc.log.append(f"{self.display_name} 使用 耙伤(Rake)。")
                bc.add_to_bot(Actions.attack_player(self.idx, dmg))
                bc.add_to_bot(Actions.debuff_player(PlayerStatus.WEAK, 2 if bc.ascension >= 17 else 1, True))
            case _:
                raise AssertionError(f"未知招式 {move}")
        bc.add_to_bot(Actions.roll_move(self.idx))
        self.turns_taken += 1


class RedSlaver(Monster):
    """红奴役者：Stab 13 伤 / Scrape 8 伤 + 1 层易伤 / Entangle 缠绕。

    wiki/C++ A0：HP 46-50（A7 起 48-52）。首招固定 Stab（lastMove(INVALID)）。
    roll 分段：
      roll ≥ 75 且未用过 Entangle → Entangle（misc_info 记录，整场一次）
      roll ≥ 50 且已用过 Entangle 且 Stab 未连续两回合 → Stab
      Scrape 未连续两回合（A17 起上回合出过即算）→ Scrape
      否则 Stab
    注：lightspeed 从不置位 usedEntangle（可重复缠绕，疑漏写）；
    此处按本体"整场一次"语义在 Entangle 落地时置 misc_info=1。
    """

    name = "Red Slaver"
    zh = "奴隶贩子"
    hp_range = (46, 50)
    hp_range_high = (48, 52)

    STAB = MoveDef("Stab", "刺击", "attack", base_damage=13)
    ENTANGLE = MoveDef("Entangle", "丢网", "debuff", intent_text="施加 1 层缠绕")
    SCRAPE = MoveDef("Scrape", "刮伤", "attack", base_damage=8)  # 另施加 1 层易伤

    def __init__(self, idx: int, hp: int, max_hp: int):
        super().__init__(idx, hp, max_hp, "奴隶贩子(Red Slaver)")

    @classmethod
    def create(cls, bc: BattleContext, idx: int) -> "RedSlaver":
        hp = _roll_hp(bc, cls)
        return cls(idx, hp, hp)

    def get_move_for_roll(self, bc: BattleContext, roll: int) -> MoveDef:
        used_entangle = self.misc_info == 1
        if not self.move_history:  # lastMove(INVALID)：首招固定 Stab
            return self.STAB
        if roll >= 75 and not used_entangle:
            return self.ENTANGLE
        if roll >= 50 and used_entangle and not _last_two(self, "Stab"):
            return self.STAB
        if not _last_two(self, "Scrape") or (bc.ascension >= 17 and not _last(self, "Scrape")):
            return self.SCRAPE
        return self.STAB

    def take_turn(self, bc: BattleContext) -> None:
        move = self.move_history[0]
        match move.name:
            case "Stab":
                dmg = bc.calculate_monster_damage(self, 14 if bc.ascension >= 2 else 13)
                bc.log.append(f"{self.display_name} 使用 刺击(Stab)。")
                bc.add_to_bot(Actions.attack_player(self.idx, dmg))
            case "Entangle":
                bc.log.append(f"{self.display_name} 使用 丢网(Entangle)。")
                bc.add_to_bot(Actions.debuff_player(PlayerStatus.ENTANGLED, 1, True))
                self.misc_info = 1  # 已用过（本体语义；lightspeed 漏写，见类注释）
            case "Scrape":
                dmg = bc.calculate_monster_damage(self, 9 if bc.ascension >= 2 else 8)
                bc.log.append(f"{self.display_name} 使用 刮伤(Scrape)。")
                bc.add_to_bot(Actions.attack_player(self.idx, dmg))
                bc.add_to_bot(Actions.debuff_player(PlayerStatus.VULNERABLE, 2 if bc.ascension >= 17 else 1, True))
            case _:
                raise AssertionError(f"未知招式 {move}")
        bc.add_to_bot(Actions.roll_move(self.idx))
        self.turns_taken += 1


class SneakyGremlin(Monster):
    """狡诈小鬼：固定 Puncture 9 伤，无 roll（getMoveForRoll 无条件返回）。

    wiki/C++ A0：HP 10-14（A7 起 11-15）。take_turn 尾部无 RollMove/
    NoOpRollMove（逃跑分支死代码外无入队），意图恒为 Puncture。
    """

    name = "Sneaky Gremlin"
    zh = "卑鄙地精"
    hp_range = (10, 14)
    hp_range_high = (11, 15)

    PUNCTURE = MoveDef("Puncture", "穿刺", "attack", base_damage=9)

    def __init__(self, idx: int, hp: int, max_hp: int):
        super().__init__(idx, hp, max_hp, "卑鄙地精(Sneaky Gremlin)")

    @classmethod
    def create(cls, bc: BattleContext, idx: int) -> "SneakyGremlin":
        hp = _roll_hp(bc, cls)
        return cls(idx, hp, hp)

    def get_move_for_roll(self, bc: BattleContext, roll: int) -> MoveDef:
        return self.PUNCTURE

    def take_turn(self, bc: BattleContext) -> None:
        dmg = bc.calculate_monster_damage(self, 10 if bc.ascension >= 2 else 9)
        bc.log.append(f"{self.display_name} 使用 穿刺(Puncture)。")
        bc.add_to_bot(Actions.attack_player(self.idx, dmg))
        # 对齐 C++：无 RollMove 入队（第 3 回合逃跑分支为死代码，不实现），
        # 意图保持 Puncture 不变
        self.turns_taken += 1


class FatGremlin(Monster):
    """肥硕小鬼：固定 Smash 4 伤 + 1 层虚弱（A17 起另加 1 层脆弱）。

    wiki/C++ A0：HP 13-17（A7 起 14-18）。take_turn 尾部 NoOpRollMove
    （逃跑分支死代码走 else），意图恒为 Smash。
    """

    name = "Fat Gremlin"
    zh = "胖地精"
    hp_range = (13, 17)
    hp_range_high = (14, 18)

    SMASH = MoveDef("Smash", "粉碎", "attack", base_damage=4)  # 另施加 1 层虚弱

    def __init__(self, idx: int, hp: int, max_hp: int):
        super().__init__(idx, hp, max_hp, "胖地精(Fat Gremlin)")

    @classmethod
    def create(cls, bc: BattleContext, idx: int) -> "FatGremlin":
        hp = _roll_hp(bc, cls)
        return cls(idx, hp, hp)

    def get_move_for_roll(self, bc: BattleContext, roll: int) -> MoveDef:
        return self.SMASH

    def take_turn(self, bc: BattleContext) -> None:
        dmg = bc.calculate_monster_damage(self, 5 if bc.ascension >= 2 else 4)
        bc.log.append(f"{self.display_name} 使用 粉碎(Smash)。")
        bc.add_to_bot(Actions.attack_player(self.idx, dmg))
        bc.add_to_bot(Actions.debuff_player(PlayerStatus.WEAK, 1, True))
        if bc.ascension >= 17:
            bc.add_to_bot(Actions.debuff_player(PlayerStatus.FRAIL, 1, True))
        # 对齐 C++：逃跑分支死代码 → NoOpRollMove 占位，意图保持 Smash
        bc.add_to_bot(Actions.no_op_roll_move())
        self.turns_taken += 1


class ShieldGremlin(Monster):
    """盾牌小鬼：Protect 为随机存活友军 +7 格挡（A7 起 8 / A17 起 11）。

    wiki/C++ A0：HP 12-15（A7 起 13-17）。getMoveForRoll 恒返回 PROTECT。
    take_turn：入队给随机友军的格挡动作后，若存活数 ≤ 1 则切换
    Shield Bash（6 伤，A2 起 8），此后不再切回（无 roll 入队）。
    随机目标：C++ GainBlockRandomEnemy 用 aiRng 且只排除已死怪；
    本项目按惯例用 misc 流、排除已死/已逃跑（分布级等价，见 DESIGN.md §3）。
    """

    name = "Shield Gremlin"
    zh = "持盾地精"
    hp_range = (12, 15)
    hp_range_high = (13, 17)

    PROTECT = MoveDef("Protect", "保护", "defend", intent_text="为随机存活友军提供格挡")
    SHIELD_BASH = MoveDef("Shield Bash", "盾击", "attack", base_damage=6)

    def __init__(self, idx: int, hp: int, max_hp: int):
        super().__init__(idx, hp, max_hp, "持盾地精(Shield Gremlin)")

    @classmethod
    def create(cls, bc: BattleContext, idx: int) -> "ShieldGremlin":
        hp = _roll_hp(bc, cls)
        return cls(idx, hp, hp)

    @staticmethod
    def _protect_amount(bc: BattleContext) -> int:
        # 对齐 C++ blockAmounts[getTriIdx(asc, 7, 17)]
        if bc.ascension >= 17:
            return 11
        if bc.ascension >= 7:
            return 8
        return 7

    def _gain_block_random_ally(self, amount: int) -> Action:
        def run(bcb: BattleContext) -> None:
            allies = [
                m.idx
                for m in bcb.monsters.monsters
                if m.idx != self.idx and not m.is_dead_or_escaped()
            ]
            target = allies[bcb.rngs.misc.int_inclusive(0, len(allies) - 1)] if allies else self.idx
            Actions.monster_gain_block(target, amount).fn(bcb)

        return Action(run)

    def get_move_for_roll(self, bc: BattleContext, roll: int) -> MoveDef:
        return self.PROTECT

    def take_turn(self, bc: BattleContext) -> None:
        move = self.move_history[0]
        match move.name:
            case "Protect":
                bc.log.append(f"{self.display_name} 使用 保护(Protect)。")
                bc.add_to_bot(self._gain_block_random_ally(self._protect_amount(bc)))
                if bc.monsters.alive_count <= 1:
                    self.set_move(self.SHIELD_BASH)
            case "Shield Bash":
                dmg = bc.calculate_monster_damage(self, 8 if bc.ascension >= 2 else 6)
                bc.log.append(f"{self.display_name} 使用 盾击(Shield Bash)。")
                bc.add_to_bot(Actions.attack_player(self.idx, dmg))
            case _:
                raise AssertionError(f"未知招式 {move}")
        # 对齐 C++：两分支均无 RollMove 入队，意图不经 roll 更新
        self.turns_taken += 1


class GremlinWizard(Monster):
    """小鬼法师：充能（计数挂 misc_info）→ 终极冲击 25 伤，循环。

    wiki/C++ A0：HP 21-25（A7 起 22-26）。开局 roll 时 misc_info 置 1
    （C++ getMoveForRoll 的 monsterData = 1）；每次充能回合 +1，到 3 切
    终极冲击。A0 冲击后清零重充（首轮充 2 回合，此后每轮充 3 回合）；
    A17 起不重充（此后每回合都是终极冲击）。全程无 RollMove 入队。
    充能回合无任何动作（C++ CHARGING 分支只 ++miscInfo）。
    """

    name = "Gremlin Wizard"
    zh = "地精法师"
    hp_range = (21, 25)
    hp_range_high = (22, 26)

    CHARGING = MoveDef("Charging", "蓄能", "unknown", intent_text="正在充能（无动作）")
    ULTIMATE_BLAST = MoveDef("Ultimate Blast", "终极大爆炸", "attack", base_damage=25)

    def __init__(self, idx: int, hp: int, max_hp: int):
        super().__init__(idx, hp, max_hp, "地精法师(Gremlin Wizard)")

    @classmethod
    def create(cls, bc: BattleContext, idx: int) -> "GremlinWizard":
        hp = _roll_hp(bc, cls)
        return cls(idx, hp, hp)

    def get_move_for_roll(self, bc: BattleContext, roll: int) -> MoveDef:
        self.misc_info = 1  # 对齐 C++ monsterData = 1（充能计数起点）
        return self.CHARGING

    def take_turn(self, bc: BattleContext) -> None:
        move = self.move_history[0]
        match move.name:
            case "Charging":
                self.misc_info += 1
                bc.log.append(f"{self.display_name} 正在充能……")
                if self.misc_info == 3:
                    self.set_move(self.ULTIMATE_BLAST)
            case "Ultimate Blast":
                dmg = bc.calculate_monster_damage(self, 30 if bc.ascension >= 2 else 25)
                bc.log.append(f"{self.display_name} 使用 终极大爆炸(Ultimate Blast)！")
                bc.add_to_bot(Actions.attack_player(self.idx, dmg))
                if bc.ascension < 17:
                    self.misc_info = 0
                    self.set_move(self.CHARGING)
            case _:
                raise AssertionError(f"未知招式 {move}")
        self.turns_taken += 1


class Sentry(Monster):
    """哨卫：Beam 9 伤 / Bolt 塞 2 张眩晕进弃牌堆，严格交替；开局 1 层人工制品。

    wiki/C++ A0：HP 38-42（A8 起 39-45）。首招由奇偶槽位决定：
    firstTurn 时 idx%2==0 先 Bolt、否则先 Beam；此后 take_turn 用
    set_move 交替（无 roll，NoOpRollMove 占位）。Bolt 塞 2 张 DAZED
    （A18 起 3 张）进弃牌堆；Beam 9 伤（A3 起 10）。
    人工制品（ARTIFACT 1）在构造期置位，对齐 C++ preBattleAction。
    """

    name = "Sentry"
    zh = "哨卫"
    hp_range = (38, 42)
    hp_range_high = (39, 45)
    hp_high_asc = 8  # 对齐 C++ initHp：Sentry 的高位 HP 区间从 A8 起

    BEAM = MoveDef("Beam", "光束", "attack", base_damage=9)
    BOLT = MoveDef("Bolt", "闪击", "debuff", intent_text="塞 2 张眩晕进弃牌堆")

    def __init__(self, idx: int, hp: int, max_hp: int):
        super().__init__(idx, hp, max_hp, "哨卫(Sentry)")
        # 对齐 C++ preBattleAction：开局 1 层人工制品
        self.statuses.add(MonsterStatus.ARTIFACT, 1)

    @classmethod
    def create(cls, bc: BattleContext, idx: int) -> "Sentry":
        hp = _roll_hp(bc, cls)
        return cls(idx, hp, hp)

    def get_move_for_roll(self, bc: BattleContext, roll: int) -> MoveDef:
        # 对齐 C++ firstTurn()（moveHistory[0] == INVALID）+ idx 奇偶分支
        if not self.move_history:
            return self.BOLT if self.idx % 2 == 0 else self.BEAM
        # 首回合后不经 roll（take_turn 用 set_move 交替），此处仅兜底
        return self.move_history[0]

    def take_turn(self, bc: BattleContext) -> None:
        move = self.move_history[0]
        match move.name:
            case "Beam":
                dmg = bc.calculate_monster_damage(self, 10 if bc.ascension >= 3 else 9)
                bc.log.append(f"{self.display_name} 使用 光束(Beam)。")
                bc.add_to_bot(Actions.attack_player(self.idx, dmg))
                self.set_move(self.BOLT)
                bc.add_to_bot(Actions.no_op_roll_move())
            case "Bolt":
                n = 3 if bc.ascension >= 18 else 2
                bc.log.append(f"{self.display_name} 使用 闪击(Bolt)，塞 {n} 张眩晕进弃牌堆。")
                for _ in range(n):
                    bc.add_to_bot(Actions.make_temp_card_in_discard(DAZED))
                self.set_move(self.BEAM)
                bc.add_to_bot(Actions.no_op_roll_move())
            case _:
                raise AssertionError(f"未知招式 {move}")
        self.turns_taken += 1


# ====================================================================
# 批次 2：中等档 Act 1 怪物（Mad Gremlin、Gremlin Nob、Lagavulin、
# The Guardian、Hexaghost、Taskmaster）。数值/分段逐行对齐
# MonsterSpecific.cpp，wiki 交叉校验（差异见模块头注释与各类 docstring）。
# ====================================================================


class MadGremlin(Monster):
    """狂怒小鬼：固定 Scratch 4 伤（A2 起 5），开局 1 层愤怒（A17 起 2）。

    wiki/C++ A0：HP 20-24（A7 起 21-25）。preBattleAction buff<ANGRY>
    （A17 起为 2）——受击自动 +STR×ANGRY 层，钩子在
    entities.Monster.attacked。出招恒 Scratch（getMoveForRoll 无条件
    返回，对齐 C++ MAD_GREMLIN 分支），take_turn 尾部 NoOpRollMove
    占位（逃跑分支死代码，同 Sneaky/Fat Gremlin）。
    """

    name = "Mad Gremlin"
    zh = "火大地精"
    hp_range = (20, 24)
    hp_range_high = (21, 25)

    SCRATCH = MoveDef("Scratch", "抓挠", "attack", base_damage=4)

    def __init__(self, idx: int, hp: int, max_hp: int):
        super().__init__(idx, hp, max_hp, "火大地精(Mad Gremlin)")

    @classmethod
    def create(cls, bc: BattleContext, idx: int) -> "MadGremlin":
        hp = _roll_hp(bc, cls)
        m = cls(idx, hp, hp)
        # 对齐 C++ preBattleAction：buff<ANGRY>(asc17 ? 2 : 1)
        m.statuses.add(MonsterStatus.ANGRY, 2 if bc.ascension >= 17 else 1)
        return m

    def get_move_for_roll(self, bc: BattleContext, roll: int) -> MoveDef:
        return self.SCRATCH

    def take_turn(self, bc: BattleContext) -> None:
        dmg = bc.calculate_monster_damage(self, 5 if bc.ascension >= 2 else 4)
        bc.log.append(f"{self.display_name} 使用 抓挠(Scratch)。")
        bc.add_to_bot(Actions.attack_player(self.idx, dmg))
        bc.add_to_bot(Actions.no_op_roll_move())
        self.turns_taken += 1


class GremlinNob(Monster):
    """小鬼巨汉（精英）：首回合怒吼（激怒 2/3），此后 Rush / 颅骨猛击。

    wiki/C++ A0：HP 82-86（A8 起 85-90）。roll 分段：
      首回合（lastMove INVALID）固定 BELLOW（ENRAGE 2，A18 起 3，
      无格挡——玩家每打出技能牌 +ENRAGE 层力量，钩子在
      battle.on_use_skill_card）；
      A18 起（本体 GremlinNob.java）：近两回合均非 Skull Bash →
      SKULL_BASH；否则 Rush 已连续两回合 → SKULL_BASH，否则 RUSH。
      净效果 = 颅骨猛击、冲锋、冲锋 循环（wiki：A18 第 2 回合出
      Skull Bash、此后连续两次 Bull Rush 再循环）。lightspeed 把
      `!lastMove(SKULL_BASH) && !lastMoveBefore(SKULL_BASH)` 误译为
      `!lastTwoMoves(SKULL_BASH)`，使 Skull Bash 不可达（恒 Rush）——
      按 wiki/本体修正；
      A0：roll < 33 或 Rush 已连续两回合 → SKULL_BASH，否则 RUSH。
    数值：Rush 14 伤（A3 起 16）；Skull Bash 6 伤 + 2 层易伤
    （A3 起 8 伤；易伤恒 2，isSourceMonster → justApplied）。
    """

    name = "Gremlin Nob"
    zh = "地精大块头"
    hp_range = (82, 86)
    hp_range_high = (85, 90)
    hp_high_asc = 8

    BELLOW = MoveDef("Bellow", "怒吼", "buff", intent_text="获得 2 层激怒（玩家打出技能牌时 +2 力量）")
    RUSH = MoveDef("Rush", "冲锋", "attack", base_damage=14)
    SKULL_BASH = MoveDef("Skull Bash", "颅骨重击", "attack", base_damage=6)  # 另施加 2 层易伤

    def __init__(self, idx: int, hp: int, max_hp: int):
        super().__init__(idx, hp, max_hp, "地精大块头(Gremlin Nob)")

    @classmethod
    def create(cls, bc: BattleContext, idx: int) -> "GremlinNob":
        hp = _roll_hp(bc, cls)
        return cls(idx, hp, hp)

    def get_move_for_roll(self, bc: BattleContext, roll: int) -> MoveDef:
        # 对齐 C++ lastMove(INVALID)：首回合固定 BELLOW
        if not self.move_history:
            return self.BELLOW
        if bc.ascension >= 18:
            # A18（本体 GremlinNob.java getMove）：近两回合均非 Skull Bash
            # → Skull Bash；否则 Rush×2 → Skull Bash，否则 Rush。
            # lightspeed 误译（lastTwoMoves(SKULL_BASH) 使 Skull Bash 不可达），
            # 按 wiki"SB,R,R 循环"修正，见类注释。
            if not _last(self, "Skull Bash") and not _last_before(self, "Skull Bash"):
                return self.SKULL_BASH
            if _last_two(self, "Rush"):
                return self.SKULL_BASH
            return self.RUSH
        if roll < 33 or _last_two(self, "Rush"):
            return self.SKULL_BASH
        return self.RUSH

    def take_turn(self, bc: BattleContext) -> None:
        move = self.move_history[0]
        match move.name:
            case "Bellow":
                # buff<ENRAGE>：玩家打出技能牌时 +层 力量（引擎 on_use_skill_card）
                self.buff(MonsterStatus.ENRAGE, 3 if bc.ascension >= 18 else 2)
                bc.log.append(f"{self.display_name} 使用 怒吼(Bellow)，获得 {3 if bc.ascension >= 18 else 2} 层激怒！")
            case "Rush":
                dmg = bc.calculate_monster_damage(self, 16 if bc.ascension >= 3 else 14)
                bc.log.append(f"{self.display_name} 使用 冲锋(Rush)。")
                bc.add_to_bot(Actions.attack_player(self.idx, dmg))
            case "Skull Bash":
                dmg = bc.calculate_monster_damage(self, 8 if bc.ascension >= 3 else 6)
                bc.log.append(f"{self.display_name} 使用 颅骨重击(Skull Bash)。")
                bc.add_to_bot(Actions.attack_player(self.idx, dmg))
                bc.add_to_bot(Actions.debuff_player(PlayerStatus.VULNERABLE, 2, True))
            case _:
                raise AssertionError(f"未知招式 {move}")
        bc.add_to_bot(Actions.roll_move(self.idx))
        self.turns_taken += 1


class Lagavulin(Monster):
    """拉格维林（精英）：沉睡 3 回合（金属化 8 + 8 格挡），醒后攻-攻-汲取灵魂循环。

    wiki/C++ A0：HP 109-111（A8 起 112-115）。开局 ASLEEP 1 + METALLICIZE 8
    + 8 格挡（对齐 MonsterGroup LAGAVULIN 置 ASLEEP + preBattleAction）。
    受到漏格挡伤害即醒并移除金属化——引擎 entities._apply_damage 已做
    （对齐 Monster.cpp:412-414）；本类只管自然醒计时：
      C++ LAGAVULIN_SLEEP 分支 `bc.turn == 2 || !hasStatus<ASLEEP>()`
      （0 基回合计数，即第 3 回合末醒、第 4 回合攻击）。本项目回合从 1
      起，条件映射为 bc.turn == 3。打醒的回合 SLEEP 意图照常空转一回合
      （本体"stunned for one turn"），下一回合才攻击。
    自然醒按本体语义补移除 ASLEEP 并同减 8 层金属化（本体 Lagavulin.java
    changeState("OPEN") 的 ReducePowerAction(Metallicize, 8)——打醒与自然
    醒两条路都走该分支，金属化在任一醒来方式后都被移除；lightspeed 的
    LAGAVULIN_SLEEP 分支只 setMove，漏掉金属化移除，见模块头注释）。
    醒后序列（对齐 C++ setMove 链）：攻-攻-汲取灵魂循环；攻击 18 伤
    （A3 起 20），汲取灵魂玩家力量与敏捷 -1（A18 起 -2，立即结算）。
    get_move_for_roll 仅首回合调用一次：睡 → SLEEP / 已醒 → SIPHON_SOUL。
    """

    name = "Lagavulin"
    zh = "乐加维林"
    hp_range = (109, 111)
    hp_range_high = (112, 115)
    hp_high_asc = 8

    SLEEP = MoveDef("Sleep", "沉睡", "unknown", intent_text="沉睡中（不受击则 3 回合后自然醒来）")
    ATTACK = MoveDef("Attack", "攻击", "attack", base_damage=18)
    SIPHON_SOUL = MoveDef("Siphon Soul", "灵魂吸取", "debuff", intent_text="力量与敏捷 -1")

    def __init__(self, idx: int, hp: int, max_hp: int):
        super().__init__(idx, hp, max_hp, "乐加维林(Lagavulin)")

    @classmethod
    def create(cls, bc: BattleContext, idx: int) -> "Lagavulin":
        hp = _roll_hp(bc, cls)
        m = cls(idx, hp, hp)
        # 对齐 C++：遭遇装配置 ASLEEP，preBattleAction 上 METALLICIZE 8 + 8 格挡
        m.statuses.add(MonsterStatus.ASLEEP, 1)
        m.statuses.add(MonsterStatus.METALLICIZE, 8)
        m.block += 8
        return m

    @classmethod
    def create_event(cls, bc: BattleContext, idx: int) -> "Lagavulin":
        """事件变体（Dead Adventurer 的 "Lagavulin Event"，MonsterHelper:440
        → new Lagavulin(false)）：不沉睡、无金属化与开局格挡，
        preBattleAction 直接 setMove(STRONG_DEBUFF)——get_move_for_roll
        读到无 ASLEEP 自然返回 SIPHON_SOUL，与本体一致。"""
        hp = _roll_hp(bc, cls)
        return cls(idx, hp, hp)

    def get_move_for_roll(self, bc: BattleContext, roll: int) -> MoveDef:
        # C++ 仅首回合 roll 一次；此后 take_turn 全 set_move（无 roll）
        return self.SLEEP if self.statuses.has(MonsterStatus.ASLEEP) else self.SIPHON_SOUL

    def take_turn(self, bc: BattleContext) -> None:
        move = self.move_history[0]
        match move.name:
            case "Attack":
                dmg = bc.calculate_monster_damage(self, 20 if bc.ascension >= 3 else 18)
                bc.log.append(f"{self.display_name} 使用 攻击(Attack)。")
                bc.add_to_bot(Actions.attack_player(self.idx, dmg))
                # lastTwoMoves(ATTACK)：本回合与上回合都是攻击 → 汲取灵魂
                if _last_two(self, "Attack"):
                    self.set_move(self.SIPHON_SOUL)
                else:
                    self.set_move(self.ATTACK)
            case "Siphon Soul":
                n = 2 if bc.ascension >= 18 else 1
                bc.log.append(f"{self.display_name} 使用 灵魂吸取(Siphon Soul)，你的力量与敏捷 -{n}。")
                # 对齐 C++ DebuffPlayer<...>(±n).actFunc：立即结算，不入队
                Actions.debuff_player(PlayerStatus.DEXTERITY, -n, True).fn(bc)
                Actions.debuff_player(PlayerStatus.STRENGTH, -n, True).fn(bc)
                self.set_move(self.ATTACK)
            case "Sleep":
                # 自然醒计时（bc.turn 映射见类注释）；被打醒（引擎已移除
                # ASLEEP 并减 8 金属化）同样切攻击。自然醒按本体 OPEN 分支
                # 补移除 ASLEEP 与 8 层金属化（打醒路径引擎已处理，此处
                # decrement 已归零的状态无害）。
                if bc.turn == 3 or not self.statuses.has(MonsterStatus.ASLEEP):
                    self.statuses.remove(MonsterStatus.ASLEEP)
                    self.statuses.decrement(MonsterStatus.METALLICIZE, 8)
                    self.set_move(self.ATTACK)
                    bc.log.append(f"{self.display_name} 醒了！")
                else:
                    self.set_move(self.SLEEP)
                    bc.log.append(f"{self.display_name} 沉睡中……")
            case _:
                raise AssertionError(f"未知招式 {move}")
        bc.add_to_bot(Actions.no_op_roll_move())
        self.turns_taken += 1


class TheGuardian(Monster):
    """守卫者（Boss）：模式切换状态机——攻击循环 ↔ 防御模式（利爪隐蔽反伤）。

    wiki/C++ A0：HP 240（A9 起 250）。开局 misc_info = 阈值 30（A9 35、
    A19 40），MODE_SHIFT 状态同值计数（对齐 preBattleAction）。
    漏格挡伤害累积扣减 MODE_SHIFT 计数（on_hp_lost 覆盖，attacked 与
    非攻击 HP 损失两路径共用），归零（含恰好归零）→ 移除计数、强改
    意图为防御模式、+20 格挡入队（对齐 Monster.cpp:520-536）。
    攻击模式序列（对齐 C++ setMove 链，全 set_move 无 roll）：
      蓄能（+9 格挡）→ 猛烈重击（32/36）→ 排放蒸汽（2 易伤 + 2 虚弱）
      → 旋风（5×4）→ 蓄能 ……
    防御模式：防御模式（利爪隐蔽 3/4，玩家打出攻击牌即反伤 层，
    钩子在 battle.on_use_attack_card）→ 滚动攻击（9/10）→ 双重猛击
    （8×2；移除利爪隐蔽、阈值 +10、MODE_SHIFT 重设为新阈值、回旋风）。
    """

    name = "The Guardian"
    zh = "守护者"
    hp_range = (240, 240)
    hp_range_high = (250, 250)
    hp_high_asc = 9

    CHARGING_UP = MoveDef("Charging Up", "蓄能", "defend", intent_text="获得 9 点格挡")
    FIERCE_BASH = MoveDef("Fierce Bash", "猛烈痛击", "attack", base_damage=32)
    VENT_STEAM = MoveDef("Vent Steam", "蒸汽喷射", "debuff", intent_text="施加 2 层易伤与 2 层虚弱")
    WHIRLWIND = MoveDef("Whirlwind", "旋风", "attack", base_damage=5)  # ×4 段
    DEFENSIVE_MODE = MoveDef("Defensive Mode", "防御模式", "buff", intent_text="获得 3 层利爪隐蔽（打出攻击牌即受反伤）")
    ROLL_ATTACK = MoveDef("Roll Attack", "滚动攻击", "attack", base_damage=9)
    TWIN_SLAM = MoveDef("Twin Slam", "双斩", "attack", base_damage=8)  # ×2 段

    def __init__(self, idx: int, hp: int, max_hp: int):
        super().__init__(idx, hp, max_hp, "守护者(The Guardian)")

    @classmethod
    def create(cls, bc: BattleContext, idx: int) -> "TheGuardian":
        hp = _roll_hp(bc, cls)
        m = cls(idx, hp, hp)
        # 对齐 C++ preBattleAction：miscInfo 与 MODE_SHIFT 同置阈值
        d = 40 if bc.ascension >= 19 else 35 if bc.ascension >= 9 else 30
        m.misc_info = d
        m.statuses.add(MonsterStatus.MODE_SHIFT, d)
        return m

    def get_move_for_roll(self, bc: BattleContext, roll: int) -> MoveDef:
        # C++ 无条件返回 CHARGING_UP（此后 take_turn 全 set_move，不再 roll）
        return self.CHARGING_UP

    def on_hp_lost(self, bc: BattleContext, amount: int) -> None:
        # 对齐 Monster.cpp onHpLost THE_GUARDIAN 分支：漏格挡伤害扣减
        # MODE_SHIFT 计数，归零切换防御模式（强改意图 + 20 格挡入队）。
        # 防御模式期间（双重猛击重设前）无 MODE_SHIFT → 伤害不再累积。
        if self.statuses.has(MonsterStatus.MODE_SHIFT):
            new_amount = self.statuses.get(MonsterStatus.MODE_SHIFT) - amount
            if new_amount <= 0:
                self.statuses.remove(MonsterStatus.MODE_SHIFT)
                self.set_move(self.DEFENSIVE_MODE)
                bc.add_to_bot(Actions.monster_gain_block(self.idx, 20))
            else:
                self.statuses.set(MonsterStatus.MODE_SHIFT, new_amount)

    def take_turn(self, bc: BattleContext) -> None:
        move = self.move_history[0]
        match move.name:
            case "Charging Up":
                self.block += 9  # 对齐 C++ addBlock：立即结算，不入队
                bc.log.append(f"{self.display_name} 使用 蓄能(Charging Up)，获得 9 点格挡。")
                self.set_move(self.FIERCE_BASH)
            case "Fierce Bash":
                dmg = bc.calculate_monster_damage(self, 36 if bc.ascension >= 4 else 32)
                bc.log.append(f"{self.display_name} 使用 猛烈痛击(Fierce Bash)。")
                bc.add_to_bot(Actions.attack_player(self.idx, dmg))
                self.set_move(self.VENT_STEAM)
            case "Vent Steam":
                bc.log.append(f"{self.display_name} 使用 蒸汽喷射(Vent Steam)。")
                bc.add_to_bot(Actions.debuff_player(PlayerStatus.VULNERABLE, 2, True))
                bc.add_to_bot(Actions.debuff_player(PlayerStatus.WEAK, 2, True))
                self.set_move(self.WHIRLWIND)
            case "Whirlwind":
                dmg = bc.calculate_monster_damage(self, 5)
                bc.log.append(f"{self.display_name} 使用 旋风(Whirlwind)，5 点伤害 ×4。")
                for _ in range(4):
                    bc.add_to_bot(Actions.attack_player(self.idx, dmg))
                self.set_move(self.CHARGING_UP)
            case "Defensive Mode":
                n = 4 if bc.ascension >= 19 else 3
                self.buff(MonsterStatus.SHARP_HIDE, n)
                bc.log.append(f"{self.display_name} 进入 防御模式(Defensive Mode)，获得 {n} 层利爪隐蔽。")
                self.set_move(self.ROLL_ATTACK)
            case "Roll Attack":
                dmg = bc.calculate_monster_damage(self, 10 if bc.ascension >= 4 else 9)
                bc.log.append(f"{self.display_name} 使用 滚动攻击(Roll Attack)。")
                bc.add_to_bot(Actions.attack_player(self.idx, dmg))
                self.set_move(self.TWIN_SLAM)
            case "Twin Slam":
                dmg = bc.calculate_monster_damage(self, 8)
                bc.log.append(f"{self.display_name} 使用 双斩(Twin Slam)，8 点伤害 ×2！")
                for _ in range(2):
                    bc.add_to_bot(Actions.attack_player(self.idx, dmg))
                self.statuses.remove(MonsterStatus.SHARP_HIDE)
                self.misc_info += 10  # 阈值递增（对齐 C++ miscInfo += 10）
                self.set_move(self.WHIRLWIND)
                bc.add_to_bot(Actions.buff_enemy(self.idx, MonsterStatus.MODE_SHIFT, self.misc_info))
            case _:
                raise AssertionError(f"未知招式 {move}")
        # 对齐 C++：THE_GUARDIAN 各分支均无 RollMove / NoOpRollMove 入队
        self.turns_taken += 1


class Hexaghost(Monster):
    """六火幽灵（Boss）：激活锁定分割伤害，此后 灼烧-冲撞-灼烧-燃焰-冲撞-灼烧-炼狱 循环。

    wiki/C++ A0：HP 250（A9 起 264）。首回合固定 ACTIVATE（C++ assert
    firstTurn）：misc_info = 玩家当前 HP // 12 + 1，作为 DIVIDER 的
    单段伤害（×6 段）。此后按 unique_power0（火球计数）set_move 轮转：
      SEAR（6 伤 + 塞 1 张灼伤进弃牌堆，A19 起 2 张；C++ `bc.turn > 8`
      起为升级版——0 基计数映射到本项目 1 基为 `bc.turn > 9`）：计数
      0→冲撞、2→燃焰、否则→炼狱，随后计数 +1；
      TACKLE（5×2，A4 起 6×2）→ 灼烧，随后计数 +1；
      INFLAME（+12 格挡、力量 +2（A19 起 +3），计数 +1）→ 冲撞；
      INFERNO（2×6，A4 起 3×6；计数清零）→ 灼烧。
    注：lightspeed 的 INFERNO 不塞 3 张升级灼伤、不升级已有灼伤
    （本体有，此处从 C++——见模块头注释）；SEAR 伤害恒 6 无进阶加成。
    """

    name = "Hexaghost"
    zh = "六火亡魂"
    hp_range = (250, 250)
    hp_range_high = (264, 264)
    hp_high_asc = 9

    ACTIVATE = MoveDef("Activate", "激活", "unknown", intent_text="分割伤害锁定为 玩家HP÷12+1")
    DIVIDER = MoveDef("Divider", "分割", "attack", base_damage=7)  # ×6 段（单段=激活时锁定值）
    SEAR = MoveDef("Sear", "灼烧", "attack", base_damage=6)  # 另塞灼伤进弃牌堆
    TACKLE = MoveDef("Tackle", "冲撞", "attack", base_damage=5)  # ×2 段
    INFLAME = MoveDef("Inflame", "高热", "buff", intent_text="获得 12 点格挡，力量 +2")
    INFERNO = MoveDef("Inferno", "地狱火", "attack", base_damage=2)  # ×6 段

    def __init__(self, idx: int, hp: int, max_hp: int):
        super().__init__(idx, hp, max_hp, "六火亡魂(Hexaghost)")

    @classmethod
    def create(cls, bc: BattleContext, idx: int) -> "Hexaghost":
        hp = _roll_hp(bc, cls)
        return cls(idx, hp, hp)

    def get_move_for_roll(self, bc: BattleContext, roll: int) -> MoveDef:
        # C++ 仅首回合 roll（assert firstTurn）→ ACTIVATE；此后全 set_move
        return self.ACTIVATE

    def take_turn(self, bc: BattleContext) -> None:
        move = self.move_history[0]
        match move.name:
            case "Activate":
                self.misc_info = bc.player.hp // 12 + 1  # 对齐 C++ curHp / 12 + 1
                bc.log.append(f"{self.display_name} 使用 激活(Activate)，锁定分割伤害为 {self.misc_info}×6。")
                self.set_move(self.DIVIDER)
            case "Divider":
                dmg = bc.calculate_monster_damage(self, self.misc_info)
                bc.log.append(f"{self.display_name} 使用 分割(Divider)，{self.misc_info} 点伤害 ×6！")
                for _ in range(6):
                    bc.add_to_bot(Actions.attack_player(self.idx, dmg))
                self.unique_power0 = 0
                self.set_move(self.SEAR)
            case "Sear":
                dmg = bc.calculate_monster_damage(self, 6)
                bc.log.append(f"{self.display_name} 使用 灼烧(Sear)。")
                bc.add_to_bot(Actions.attack_player(self.idx, dmg))
                n = 2 if bc.ascension >= 19 else 1
                # C++ CardInstance(BURN, bc.turn > 8)：0 基回合 → 本项目 1 基 +1
                upgraded = bc.turn > 9
                for _ in range(n):
                    bc.add_to_bot(Actions.make_temp_card_in_discard(BURN, upgraded))
                if self.unique_power0 == 0:
                    self.set_move(self.TACKLE)
                elif self.unique_power0 == 2:
                    self.set_move(self.INFLAME)
                else:
                    self.set_move(self.INFERNO)
                self.unique_power0 += 1
            case "Tackle":
                dmg = bc.calculate_monster_damage(self, 6 if bc.ascension >= 4 else 5)
                bc.log.append(f"{self.display_name} 使用 冲撞(Tackle)。")
                for _ in range(2):
                    bc.add_to_bot(Actions.attack_player(self.idx, dmg))
                self.set_move(self.SEAR)
                self.unique_power0 += 1
            case "Inflame":
                self.block += 12  # 对齐 C++ addBlock：立即结算
                self.statuses.add(MonsterStatus.STRENGTH, 3 if bc.ascension >= 19 else 2)
                bc.log.append(f"{self.display_name} 使用 高热(Inflame)，格挡 +12、力量 +2。")
                self.unique_power0 += 1
                self.set_move(self.TACKLE)
            case "Inferno":
                dmg = bc.calculate_monster_damage(self, 3 if bc.ascension >= 4 else 2)
                bc.log.append(f"{self.display_name} 使用 地狱火(Inferno)，{3 if bc.ascension >= 4 else 2} 点伤害 ×6！")
                for _ in range(6):
                    bc.add_to_bot(Actions.attack_player(self.idx, dmg))
                self.unique_power0 = 0
                self.set_move(self.SEAR)
            case _:
                raise AssertionError(f"未知招式 {move}")
        # 各分支尾部 NoOpRollMove / noOpRollMove（立即/入队在纯空转下等价）
        bc.add_to_bot(Actions.no_op_roll_move())
        self.turns_taken += 1


class Taskmaster(Monster):
    """监工（slavers 遭遇中间位）：固定鞭挞——7 伤 + 塞伤口进弃牌堆。

    wiki/C++ A0：HP 54-60（A8 起 57-64；C++ initHp 先空耗一次
    hpRng.random(54,60) 再 roll 区间——本项目不做轨迹对齐，仅 roll 区间）。
    出招恒 Scouring Whip（getMoveForRoll 无条件返回）；伤害恒 7
    （无 A2 加成，wiki 同）：
      A18 起：自身力量 +1（入队）+ 塞 3 张伤口；
      A3 起：塞 2 张伤口；A0：塞 1 张。
    """

    name = "Taskmaster"
    zh = "奴隶头子"
    hp_range = (54, 60)
    hp_range_high = (57, 64)
    hp_high_asc = 8

    SCOURING_WHIP = MoveDef("Scouring Whip", "鞭挞", "attack", base_damage=7)  # 另塞伤口进弃牌堆

    def __init__(self, idx: int, hp: int, max_hp: int):
        super().__init__(idx, hp, max_hp, "奴隶头子(Taskmaster)")

    @classmethod
    def create(cls, bc: BattleContext, idx: int) -> "Taskmaster":
        hp = _roll_hp(bc, cls)
        return cls(idx, hp, hp)

    def get_move_for_roll(self, bc: BattleContext, roll: int) -> MoveDef:
        return self.SCOURING_WHIP

    def take_turn(self, bc: BattleContext) -> None:
        dmg = bc.calculate_monster_damage(self, 7)
        bc.log.append(f"{self.display_name} 使用 鞭挞(Scouring Whip)。")
        bc.add_to_bot(Actions.attack_player(self.idx, dmg))
        if bc.ascension >= 18:
            bc.add_to_bot(Actions.buff_enemy(self.idx, MonsterStatus.STRENGTH, 1))
            n_wounds = 3
        elif bc.ascension >= 3:
            n_wounds = 2
        else:
            n_wounds = 1
        for _ in range(n_wounds):
            bc.add_to_bot(Actions.make_temp_card_in_discard(WOUND))
        bc.add_to_bot(Actions.no_op_roll_move())
        self.turns_taken += 1


# ====================================================================
# 批次 3：困难档 Act 1 怪物（Acid/Spike Slime L、Slime Boss、Looter、
# Mugger）。数值/分段逐行对齐 MonsterSpecific.cpp，wiki 交叉校验
# （差异见模块头注释）。
# ====================================================================


def _large_slime_split(bc: BattleContext, slime: "Monster", medium_cls: type[Monster]) -> None:
    """大史莱姆分裂（对齐 Monster.cpp largeSlimeSplit，MonsterSpecific.cpp:3342-3367）。

    自身槽 + 下一槽各生成 1 只 M 级史莱姆，两者 curHp=maxHp=大史莱姆当前
    HP（initSpawnedMonster 双字段同写，见模块头注释）。生成怪立即 roll
    意图（initSpawnedMonster 的 rollMove；本引擎走 roll_spawned_move）。
    monster_turn_idx 额外 +1：配合 do_monster_turn 尾部的 +1，合计跳过
    新落在 idx+1 槽位的分裂体本回合的行动（对齐 C++ split 内
    bc.monsterTurnIdx++ + doMonsterTurn 的 ++；extraRollMoveOnTurn 槽位
    标记只是下回合的 aiRng 空转——RNG 轨迹对齐，不移植）。

    槽位语义对齐 C++ arr[idx+1] = 覆写：下一槽若已有占位（可达内容中
    仅 Slime Boss 分裂后槽 1 的死亡占位），原位覆写不后移；否则等价追加。
    存活数用 spawn 钩子的 +1/+1 再对本体的 -1 凑出 C++ 的净 +1
    （C++ 直接 monstersAlive++，隐式移除父体）。
    """
    group = bc.monsters
    hp = slime.hp
    m1 = medium_cls(slime.idx, hp, hp)
    m2 = medium_cls(slime.idx + 1, hp, hp)
    group.spawn_replace(bc, slime.idx, m1)
    if slime.idx + 1 < group.monster_count:
        placeholder = group.monsters[slime.idx + 1]
        assert placeholder.is_dead_or_escaped(), "分裂覆写槽必须是死亡占位（C++ 覆写语义）"
        group.spawn_replace(bc, slime.idx + 1, m2)
    else:
        group.spawn_insert(bc, slime.idx + 1, m2)
    slime.hp = 0  # 本体退场：不走 die()（无死亡触发），存活数下方 -1 对齐 C++ 隐式移除
    group.alive_count -= 1
    m1.roll_spawned_move(bc)
    m2.roll_spawned_move(bc)
    bc.monster_turn_idx += 1
    bc.log.append(f"{slime.display_name} 分裂了！")


class AcidSlimeL(Monster):
    """酸液史莱姆（大）：腐蚀唾液 / 舔舐（2 层虚弱）/ 冲撞；半血强改分裂。

    wiki/C++ A0：HP 65-69（A7 起 68-72）。HP 掉到 ≤maxHp/2 时 onHpLost
    强改当前意图为 SPLIT（Monster.cpp:497-518 的 ACID_SLIME_L 分支，
    每次漏格挡掉血都重判）；SPLIT 执行时原槽 + 下一槽生成 2 只 M 级
    （继承当前 HP，见 _large_slime_split）。roll 分段（A0）：
      roll < 30：腐蚀唾液已连续两回合 → 内层 50% 冲撞 / 50% 舔舐；
                 否则腐蚀唾液
      roll < 70：上回合冲撞 → 内层 40% 腐蚀唾液 / 60% 舔舐；否则冲撞
      roll ≥ 70：舔舐已连续两回合 → 内层 40% 腐蚀唾液 / 60% 冲撞；
                 否则舔舐
    A17 起分段 40/70，第二段改判冲撞连续两回合、第三段只判上回合舔舐
    （对齐 C++ START ASCENSION 17 段）。数值：腐蚀唾液 11 伤 + 塞
    2 张黏液（A2 起 12 伤）；舔舐 2 层虚弱；冲撞 16 伤（A2 起 18）。
    """

    name = "Acid Slime (L)"
    zh = "酸液史莱姆（大）"
    hp_range = (65, 69)
    hp_range_high = (68, 72)

    CORROSIVE_SPIT = MoveDef("Corrosive Spit", "腐蚀喷吐", "attack", base_damage=11)  # 另塞 2 张黏液
    LICK = MoveDef("Lick", "舔舔", "debuff", intent_text="施加 2 层虚弱")
    TACKLE = MoveDef("Tackle", "冲撞", "attack", base_damage=16)
    SPLIT = MoveDef("Split", "分裂", "unknown", intent_text="分裂为两只酸液史莱姆（中）")

    def __init__(self, idx: int, hp: int, max_hp: int):
        super().__init__(idx, hp, max_hp, "酸液史莱姆（大）(Acid Slime (L))")

    @classmethod
    def create(cls, bc: BattleContext, idx: int) -> "AcidSlimeL":
        hp = _roll_hp(bc, cls)
        return cls(idx, hp, hp)

    def on_hp_lost(self, bc: BattleContext, amount: int) -> None:
        # 对齐 Monster.cpp onHpLost：HP ≤ maxHp/2 强改意图为 SPLIT
        if self.hp <= self.max_hp // 2:
            self.set_move(self.SPLIT)

    def get_move_for_roll(self, bc: BattleContext, roll: int) -> MoveDef:
        if bc.ascension >= 17:
            if roll < 40:
                if _last_two(self, "Corrosive Spit"):
                    return self.TACKLE if _ai_boolean(bc, 0.6) else self.LICK
                return self.CORROSIVE_SPIT
            if roll < 70:
                if _last_two(self, "Tackle"):
                    return self.CORROSIVE_SPIT if _ai_boolean(bc, 0.6) else self.LICK
                return self.TACKLE
            if _last(self, "Lick"):
                return self.CORROSIVE_SPIT if _ai_boolean(bc, 0.4) else self.TACKLE
            return self.LICK
        if roll < 30:
            if _last_two(self, "Corrosive Spit"):
                return self.TACKLE if _ai_boolean(bc, 0.5) else self.LICK
            return self.CORROSIVE_SPIT
        if roll < 70:
            if _last(self, "Tackle"):
                return self.CORROSIVE_SPIT if _ai_boolean(bc, 0.4) else self.LICK
            return self.TACKLE
        if _last_two(self, "Lick"):
            return self.CORROSIVE_SPIT if _ai_boolean(bc, 0.4) else self.TACKLE
        return self.LICK

    def take_turn(self, bc: BattleContext) -> None:
        move = self.move_history[0]
        match move.name:
            case "Corrosive Spit":
                dmg = bc.calculate_monster_damage(self, 12 if bc.ascension >= 2 else 11)
                bc.log.append(f"{self.display_name} 使用 腐蚀喷吐(Corrosive Spit)。")
                bc.add_to_bot(Actions.attack_player(self.idx, dmg))
                for _ in range(2):
                    bc.add_to_bot(Actions.make_temp_card_in_discard(SLIMED))
                bc.add_to_bot(Actions.roll_move(self.idx))
            case "Lick":
                bc.log.append(f"{self.display_name} 使用 舔舔(Lick)。")
                bc.add_to_bot(Actions.debuff_player(PlayerStatus.WEAK, 2, True))
                bc.add_to_bot(Actions.roll_move(self.idx))
            case "Tackle":
                dmg = bc.calculate_monster_damage(self, 18 if bc.ascension >= 2 else 16)
                bc.log.append(f"{self.display_name} 使用 冲撞(Tackle)。")
                bc.add_to_bot(Actions.attack_player(self.idx, dmg))
                bc.add_to_bot(Actions.roll_move(self.idx))
            case "Split":
                _large_slime_split(bc, self, AcidSlimeM)
            case _:
                raise AssertionError(f"未知招式 {move}")
        self.turns_taken += 1


class SpikeSlimeL(Monster):
    """尖刺史莱姆（大）：烈焰冲撞 / 舔舐（2 层脆弱）；半血强改分裂。

    wiki/C++ A0：HP 64-70（A7 起 67-73）。onHpLost 半血强改 SPLIT 同
    酸史（大）。roll 分段（对齐 C++ SPIKE_SLIME_L）：
      roll < 30：烈焰冲撞已连续两回合 → 舔舐；否则烈焰冲撞
      roll ≥ 30：舔舐已连续两回合（A17 起上回合出过即算）→ 烈焰冲撞；
                  否则舔舐
    数值：烈焰冲撞 16 伤 + 塞 2 张黏液（A2 起 18 伤）；舔舐 2 层脆弱
    （A17 起 3 层，isSourceMonster → justApplied）。
    """

    name = "Spike Slime (L)"
    zh = "尖刺史莱姆（大）"
    hp_range = (64, 70)
    hp_range_high = (67, 73)

    FLAME_TACKLE = MoveDef("Flame Tackle", "烈焰冲撞", "attack", base_damage=16)  # 另塞 2 张黏液
    LICK = MoveDef("Lick", "舔舔", "debuff", intent_text="施加 2 层脆弱")
    SPLIT = MoveDef("Split", "分裂", "unknown", intent_text="分裂为两只尖刺史莱姆（中）")

    def __init__(self, idx: int, hp: int, max_hp: int):
        super().__init__(idx, hp, max_hp, "尖刺史莱姆（大）(Spike Slime (L))")

    @classmethod
    def create(cls, bc: BattleContext, idx: int) -> "SpikeSlimeL":
        hp = _roll_hp(bc, cls)
        return cls(idx, hp, hp)

    def on_hp_lost(self, bc: BattleContext, amount: int) -> None:
        # 对齐 Monster.cpp onHpLost：HP ≤ maxHp/2 强改意图为 SPLIT
        if self.hp <= self.max_hp // 2:
            self.set_move(self.SPLIT)

    def get_move_for_roll(self, bc: BattleContext, roll: int) -> MoveDef:
        if roll < 30:
            if _last_two(self, "Flame Tackle"):
                return self.LICK
            return self.FLAME_TACKLE
        if _last_two(self, "Lick") or (bc.ascension >= 17 and _last(self, "Lick")):
            return self.FLAME_TACKLE
        return self.LICK

    def take_turn(self, bc: BattleContext) -> None:
        move = self.move_history[0]
        match move.name:
            case "Flame Tackle":
                dmg = bc.calculate_monster_damage(self, 18 if bc.ascension >= 2 else 16)
                bc.log.append(f"{self.display_name} 使用 烈焰冲撞(Flame Tackle)。")
                bc.add_to_bot(Actions.attack_player(self.idx, dmg))
                for _ in range(2):
                    bc.add_to_bot(Actions.make_temp_card_in_discard(SLIMED))
                bc.add_to_bot(Actions.roll_move(self.idx))
            case "Lick":
                bc.log.append(f"{self.display_name} 使用 舔舔(Lick)。")
                bc.add_to_bot(Actions.debuff_player(PlayerStatus.FRAIL, 3 if bc.ascension >= 17 else 2, True))
                bc.add_to_bot(Actions.roll_move(self.idx))
            case "Split":
                _large_slime_split(bc, self, SpikeSlimeM)
            case _:
                raise AssertionError(f"未知招式 {move}")
        self.turns_taken += 1


def _slime_boss_split(bc: BattleContext, boss: "SlimeBoss") -> None:
    """Slime Boss 分裂（对齐 Monster.cpp slimeBossSplit，MonsterSpecific.cpp:3369-3391）。

    整组替换：槽 0 = 尖刺史莱姆（大）、槽 2 = 酸液史莱姆（大），两 L 的
    curHp=maxHp=Boss 当前 HP；槽 1 为死亡占位（C++ arr[1] 是默认构造的
    INVALID 怪且 monsterCount=3 使回合循环跳过它——此处用 Boss 本体
    hp=0 作等价占位，不走 die()，无遗物死亡触发）。分裂后
    monster_turn_idx=3（do_monster_turn 再 +1 即 ≥ monsterCount），
    本回合敌方阶段立即收束；两 L 下回合起按槽 0/2 行动。两只 L 的
    半血阈值 = 继承 HP 的一半，之后仍可各自再分裂成 M 级
    （第二体的槽位覆写语义见 _large_slime_split）。
    """
    hp = boss.hp
    spike = SpikeSlimeL(0, hp, hp)
    acid = AcidSlimeL(2, hp, hp)
    group = bc.monsters
    boss.hp = 0  # 本体退场，留作槽 1 死亡占位
    group.monsters = [spike, boss, acid]
    group.alive_count = 2
    spike.roll_spawned_move(bc)
    acid.roll_spawned_move(bc)
    bc.relics.on_monster_spawned(bc, spike)
    bc.relics.on_monster_spawned(bc, acid)
    bc.monster_turn_idx = 3
    bc.log.append(f"{boss.display_name} 分裂了！")


class SlimeBoss(Monster):
    """史莱姆老大（Boss）：黏液喷射 → 蓄势 → 猛击 循环；半血强改分裂。

    wiki/C++ A0：HP 140（A9 起 150）。序列（对齐 C++ setMove 链，全
    set_move 无 roll；rollMove 仅首回合调用一次）：
      黏液喷射：塞 3 张黏液进弃牌堆（A19 起 5 张；actFunc 立即结算）；
      蓄势：无任何效果（无格挡/自 buff，对齐 C++ 空分支）；
      猛击：35 伤（A4 起 38）→ 回黏液喷射。
    HP ≤ maxHp/2 时 onHpLost 强改 SPLIT（Monster.cpp:507-512）：槽 0
    生成尖刺史莱姆（大）、槽 2 生成酸液史莱姆（大），两 L 继承 Boss
    当前 HP（curHp=maxHp），整组替换、槽 1 死亡占位（见
    _slime_boss_split）。注意猛击分支先入队攻击再 set_move(黏液喷射)
    ——若玩家反伤把 Boss 打到半血，结算期的 onHpLost 会覆盖刚设的下
    回合意图为 SPLIT（C++ 注释 "the attack is executed after, which
    is critical"）。
    """

    name = "Slime Boss"
    zh = "史莱姆老大"
    hp_range = (140, 140)
    hp_range_high = (150, 150)
    hp_high_asc = 9

    GOOP_SPRAY = MoveDef("Goop Spray", "黏液喷射", "debuff", intent_text="塞 3 张黏液进弃牌堆")
    PREPARING = MoveDef("Preparing", "准备", "unknown", intent_text="（无动作）")
    SLAM = MoveDef("Slam", "猛撞", "attack", base_damage=35)
    SPLIT = MoveDef("Split", "分裂", "unknown", intent_text="分裂为尖刺史莱姆（大）与酸液史莱姆（大）")

    def __init__(self, idx: int, hp: int, max_hp: int):
        super().__init__(idx, hp, max_hp, "史莱姆老大(Slime Boss)")

    @classmethod
    def create(cls, bc: BattleContext, idx: int) -> "SlimeBoss":
        hp = _roll_hp(bc, cls)
        return cls(idx, hp, hp)

    def on_hp_lost(self, bc: BattleContext, amount: int) -> None:
        # 对齐 Monster.cpp onHpLost：HP ≤ maxHp/2 强改意图为 SPLIT
        if self.hp <= self.max_hp // 2:
            self.set_move(self.SPLIT)

    def get_move_for_roll(self, bc: BattleContext, roll: int) -> MoveDef:
        # C++ firstTurn() 固定黏液喷射；此后 take_turn 全 set_move 不再 roll，
        # 此处兜底返回当前意图（对齐 C++ rollMove 仅开局调用一次）
        if not self.move_history:
            return self.GOOP_SPRAY
        return self.move_history[0]

    def take_turn(self, bc: BattleContext) -> None:
        move = self.move_history[0]
        match move.name:
            case "Goop Spray":
                n = 5 if bc.ascension >= 19 else 3
                bc.log.append(f"{self.display_name} 使用 黏液喷射(Goop Spray)，塞 {n} 张黏液进弃牌堆。")
                # 对齐 C++ actFunc(bc)：立即结算，不入队
                for _ in range(n):
                    Actions.make_temp_card_in_discard(SLIMED).fn(bc)
                self.set_move(self.PREPARING)
            case "Preparing":
                bc.log.append(f"{self.display_name} 使用 准备(Preparing)。")
                self.set_move(self.SLAM)
            case "Slam":
                dmg = bc.calculate_monster_damage(self, 38 if bc.ascension >= 4 else 35)
                bc.log.append(f"{self.display_name} 使用 猛撞(Slam)。")
                # 先入队攻击再设下回合意图：反伤触发的 onHpLost 可覆盖为 SPLIT
                bc.add_to_bot(Actions.attack_player(self.idx, dmg))
                self.set_move(self.GOOP_SPRAY)
            case "Split":
                _slime_boss_split(bc, self)
            case _:
                raise AssertionError(f"未知招式 {move}")
        self.turns_taken += 1


class Looter(Monster):
    """窃贼：打劫（偷金 + 伤害）→ 突进/烟雾弹 → 逃跑。

    wiki/C++ A0：HP 44-48（A7 起 46-50）。开局偷金上限 15（A17 起 20，
    preBattleAction 的 THIEVERY 层数即单次偷取量；本引擎 misc_info 存
    累计偷金、THIEVERY 状态作死亡返还标记）。序列（对齐 C++ setMove
    链，rollMove 仅首回合调用）：
      第 1 回合 打劫（偷 15 + 10 伤（A2 起 11））→ 意图仍为打劫；
      第 2 回合 打劫（再偷 15）→ 50/50 切 突进 / 烟雾弹；
      突进：偷 15 + 12 伤（A2 起 14）→ 烟雾弹；
      烟雾弹：+6 格挡（立即结算）→ 逃跑；
      逃跑：逃离战斗（全员死亡/逃跑判胜；逃跑怪不可被指定）。
    打劫后 MUG 不再回归。死亡返还偷金（引擎 Monster.die 的 THIEVERY
    分支）。C++ 为对话消息额外消耗的 aiRng roll（randomBoolean(0.6)）
    不移植（无分布影响）。
    """

    name = "Looter"
    zh = "抢劫的"
    hp_range = (44, 48)
    hp_range_high = (46, 50)

    MUG = MoveDef("Mug", "打劫", "attack", base_damage=10)  # 另偷 15 金（A17 起 20）
    LUNGE = MoveDef("Lunge", "突进", "attack", base_damage=12)  # 另偷 15 金
    SMOKE_BOMB = MoveDef("Smoke Bomb", "烟雾弹", "defend", intent_text="获得 6 点格挡")
    ESCAPE = MoveDef("Escape", "逃跑", "unknown", intent_text="逃离战斗")

    def __init__(self, idx: int, hp: int, max_hp: int):
        super().__init__(idx, hp, max_hp, "抢劫的(Looter)")

    @classmethod
    def create(cls, bc: BattleContext, idx: int) -> "Looter":
        hp = _roll_hp(bc, cls)
        return cls(idx, hp, hp)

    def _steal_amount(self, bc: BattleContext) -> int:
        return 20 if bc.ascension >= 17 else 15

    def get_move_for_roll(self, bc: BattleContext, roll: int) -> MoveDef:
        # C++ 注释 called first turn only；此后 take_turn 全 set_move
        return self.MUG

    def take_turn(self, bc: BattleContext) -> None:
        move = self.move_history[0]
        match move.name:
            case "Mug":
                bc.log.append(f"{self.display_name} 使用 打劫(Mug)。")
                bc.add_to_bot(Actions.steal_gold(self.idx, self._steal_amount(bc)))
                dmg = bc.calculate_monster_damage(self, 11 if bc.ascension >= 2 else 10)
                bc.add_to_bot(Actions.attack_player(self.idx, dmg))
                if bc.turn == 1:
                    self.set_move(self.MUG)  # 首回合后再打劫一次
                else:
                    self.set_move(self.SMOKE_BOMB if _ai_boolean(bc, 0.5) else self.LUNGE)
            case "Lunge":
                bc.log.append(f"{self.display_name} 使用 突进(Lunge)。")
                bc.add_to_bot(Actions.steal_gold(self.idx, self._steal_amount(bc)))
                dmg = bc.calculate_monster_damage(self, 14 if bc.ascension >= 2 else 12)
                bc.add_to_bot(Actions.attack_player(self.idx, dmg))
                self.set_move(self.SMOKE_BOMB)
            case "Smoke Bomb":
                self.block += 6  # 对齐 C++ addBlock：立即结算，不入队
                bc.log.append(f"{self.display_name} 使用 烟雾弹(Smoke Bomb)，获得 6 点格挡。")
                self.set_move(self.ESCAPE)
            case "Escape":
                bc.log.append(f"{self.display_name} 逃跑了！")
                self.escape(bc)
            case _:
                raise AssertionError(f"未知招式 {move}")
        self.turns_taken += 1


class Mugger(Monster):
    """抢劫犯（Act 2 TWO_THIEVES 的窃贼搭档；数值与 Looter 不同）：
    打劫 ×2 回合 → 突进/烟雾弹 → 逃跑。

    wiki/C++ A0：HP 48-52（A7 起 50-54）。与 Looter 同构不同值（对齐
    C++ MUGGER_* 分支）：
      第 1-2 回合 打劫（偷 15 + 10 伤（A2 起 11））；第 2 回合的打劫后
      50/50 切 突进 / 烟雾弹；
      突进：偷 15 + 16 伤（A2 起 18）→ 烟雾弹；
      烟雾弹：+11 格挡（A17 起 17）→ 逃跑。
    偷金 15（A17 起 20）与 Looter 相同；死亡返还偷金同 Looter。
    """

    name = "Mugger"
    zh = "打劫的"
    hp_range = (48, 52)
    hp_range_high = (50, 54)

    MUG = MoveDef("Mug", "打劫", "attack", base_damage=10)  # 另偷 15 金（A17 起 20）
    LUNGE = MoveDef("Lunge", "突进", "attack", base_damage=16)  # 另偷 15 金
    SMOKE_BOMB = MoveDef("Smoke Bomb", "烟雾弹", "defend", intent_text="获得 11 点格挡")
    ESCAPE = MoveDef("Escape", "逃跑", "unknown", intent_text="逃离战斗")

    def __init__(self, idx: int, hp: int, max_hp: int):
        super().__init__(idx, hp, max_hp, "打劫的(Mugger)")

    @classmethod
    def create(cls, bc: BattleContext, idx: int) -> "Mugger":
        hp = _roll_hp(bc, cls)
        return cls(idx, hp, hp)

    def _steal_amount(self, bc: BattleContext) -> int:
        return 20 if bc.ascension >= 17 else 15

    def get_move_for_roll(self, bc: BattleContext, roll: int) -> MoveDef:
        # 同 Looter：仅首回合调用
        return self.MUG

    def take_turn(self, bc: BattleContext) -> None:
        move = self.move_history[0]
        match move.name:
            case "Mug":
                bc.log.append(f"{self.display_name} 使用 打劫(Mug)。")
                bc.add_to_bot(Actions.steal_gold(self.idx, self._steal_amount(bc)))
                dmg = bc.calculate_monster_damage(self, 11 if bc.ascension >= 2 else 10)
                bc.add_to_bot(Actions.attack_player(self.idx, dmg))
                if bc.turn == 2:
                    self.set_move(self.SMOKE_BOMB if _ai_boolean(bc, 0.5) else self.LUNGE)
                else:
                    self.set_move(self.MUG)
            case "Lunge":
                bc.log.append(f"{self.display_name} 使用 突进(Lunge)。")
                bc.add_to_bot(Actions.steal_gold(self.idx, self._steal_amount(bc)))
                dmg = bc.calculate_monster_damage(self, 18 if bc.ascension >= 2 else 16)
                bc.add_to_bot(Actions.attack_player(self.idx, dmg))
                self.set_move(self.SMOKE_BOMB)
            case "Smoke Bomb":
                self.block += 17 if bc.ascension >= 17 else 11  # 对齐 C++ addBlock：立即结算
                bc.log.append(f"{self.display_name} 使用 烟雾弹(Smoke Bomb)，获得 {17 if bc.ascension >= 17 else 11} 点格挡。")
                self.set_move(self.ESCAPE)
            case "Escape":
                bc.log.append(f"{self.display_name} 逃跑了！")
                self.escape(bc)
            case _:
                raise AssertionError(f"未知招式 {move}")
        self.turns_taken += 1


# ====================================================================
# 批次 B：Act 2 全部新怪物（15 种）。数值/分段逐行对齐
# MonsterSpecific.cpp，wiki 交叉校验（差异见模块头注释）。
# ====================================================================


class _SlotPlaceholder(Monster):
    """死亡占位槽（对齐 C++ MonsterGroup 的默认构造 INVALID 槽）。

    Gremlin Leader / Automaton / Collector 遭遇的空槽在 C++ 中是
    monsterCount 覆盖范围内的默认构造 Monster（idx 有效但 isDeadOrEscaped，
    init 的 rollMove/preBattleAction 按 idx != -1 跳过）；本项目用 hp=0
    占位实例等价表达——do_monster_turn / apply_pre_turn_logic 均按死亡
    跳过，战斗中生成怪（Rally/Spawn Orbs/Spawn Torch Heads）走
    spawn_replace 原位覆写本槽。
    """

    name = "Slot Placeholder"
    zh = "占位槽"

    def __init__(self, idx: int):
        super().__init__(idx, 0, 0, "占位槽")
        # 意图占位（观测层读 current_move 不炸；C++ INVALID 槽不进观测）
        self.move_history = [MoveDef("Invalid", "无效", "unknown", intent_text="（死亡占位槽）")]

    def roll_move(self, bc: BattleContext) -> None:
        return  # 死槽无意图（对齐 C++ init 对 idx == -1 槽跳过 rollMove）

    def get_move_for_roll(self, bc: BattleContext, roll: int) -> MoveDef:
        raise AssertionError("占位槽不应被询问意图")

    def take_turn(self, bc: BattleContext) -> None:
        raise AssertionError("占位槽不应行动")


# 小鬼召唤池（对齐 MonsterGroup::getGremlin 的 8 槽表；encounters 的
# gremlin_gang / gremlin_leader 与本文件 Rally 召唤共用同一池）。
GREMLIN_POOL: list = [
    MadGremlin,
    MadGremlin,
    SneakyGremlin,
    SneakyGremlin,
    FatGremlin,
    FatGremlin,
    ShieldGremlin,
    GremlinWizard,
]


def _random_gremlin(bc: BattleContext) -> type[Monster]:
    return GREMLIN_POOL[bc.rngs.misc.int_inclusive(0, 7)]


class SphericGuardian(Monster):
    """球形守卫（Act 2 普通怪）：壁垒 + 开局 40 格挡 + 人工制品 3。

    C++ initHp 特例：HP 恒 20（不抽样、无进阶加成）。preBattleAction：
    ARTIFACT 3 + BARRICADE + 40 格挡（BARRICADE 无引擎枚举，以
    apply_start_of_turn_powers 覆盖实现"回合开始不清格挡"）。
    意图链（全 set_move，rollMove 仅首回合一次）：
      激活（+25 格挡，A17 起 35）→ 削弱攻击（10 伤（A2 起 11）+ 5 脆弱）
      → 猛击（10×2）→ 硬化（+15 格挡 + 10 伤）→ 猛击 → 硬化 ……
    """

    name = "Spheric Guardian"
    zh = "圆球守护者"
    hp_range = (20, 20)
    hp_range_high = (20, 20)

    ACTIVATE = MoveDef("Activate", "激活", "defend", intent_text="获得 25 点格挡")
    ATTACK_DEBUFF = MoveDef("Attack Debuff", "削弱攻击", "attack", base_damage=10)  # 另施加 5 层脆弱
    HARDEN = MoveDef("Harden", "硬化", "attack", base_damage=10)  # 另获 15 点格挡
    SLAM = MoveDef("Slam", "猛击", "attack", base_damage=10)  # ×2 段

    def __init__(self, idx: int, hp: int, max_hp: int):
        super().__init__(idx, hp, max_hp, "圆球守护者(Spheric Guardian)")
        # 对齐 C++ preBattleAction：ARTIFACT 3 + BARRICADE + 40 格挡
        self.statuses.add(MonsterStatus.ARTIFACT, 3)
        self.block += 40

    @classmethod
    def create(cls, bc: BattleContext, idx: int) -> "SphericGuardian":
        # C++ initHp 特例：curHp = 区间下界（恒 20），不走 hp 流
        return cls(idx, cls.hp_range[0], cls.hp_range[0])

    def apply_start_of_turn_powers(self, bc: BattleContext) -> None:
        # BARRICADE（引擎无 MS::BARRICADE 枚举，覆盖钩子实现）：
        # 对齐 Monster.cpp:19-21 —— 有壁垒时格挡不清零。
        saved = self.block
        super().apply_start_of_turn_powers(bc)
        self.block += saved  # 基类已把 block 清零并重加金属化/重甲类增益

    def get_move_for_roll(self, bc: BattleContext, roll: int) -> MoveDef:
        # C++ 注释 called first turn only；此后 take_turn 全 set_move
        return self.ACTIVATE

    def take_turn(self, bc: BattleContext) -> None:
        move = self.move_history[0]
        match move.name:
            case "Activate":
                self.block += 35 if bc.ascension >= 17 else 25  # 对齐 C++ addBlock
                bc.log.append(f"{self.display_name} 使用 激活(Activate)。")
                self.set_move(self.ATTACK_DEBUFF)
            case "Attack Debuff":
                dmg = bc.calculate_monster_damage(self, 11 if bc.ascension >= 2 else 10)
                bc.log.append(f"{self.display_name} 使用 削弱攻击(Attack Debuff)。")
                bc.add_to_bot(Actions.attack_player(self.idx, dmg))
                bc.add_to_bot(Actions.debuff_player(PlayerStatus.FRAIL, 5, True))
                self.set_move(self.SLAM)
            case "Harden":
                bc.add_to_bot(Actions.monster_gain_block(self.idx, 15))
                dmg = bc.calculate_monster_damage(self, 11 if bc.ascension >= 2 else 10)
                bc.log.append(f"{self.display_name} 使用 硬化(Harden)。")
                bc.add_to_bot(Actions.attack_player(self.idx, dmg))
                self.set_move(self.SLAM)
            case "Slam":
                dmg = bc.calculate_monster_damage(self, 11 if bc.ascension >= 2 else 10)
                bc.log.append(f"{self.display_name} 使用 猛击(Slam)，{dmg} 点伤害 ×2。")
                for _ in range(2):
                    bc.add_to_bot(Actions.attack_player(self.idx, dmg))
                self.set_move(self.HARDEN)
            case _:
                raise AssertionError(f"未知招式 {move}")
        bc.add_to_bot(Actions.no_op_roll_move())
        self.turns_taken += 1


class Chosen(Monster):
    """被选者（Act 2 普通怪）：Poke → Hex → 削弱/汲取 ↔ 电击/Poke 循环。

    wiki/C++ A0：HP 95-99（A7 起 98-103）。意图链（A0）：
      首回合 Poke（5×2，A2 起 6×2）→ 第二次 roll 出 Hex（施 1 层 HEX）
      → 此后两步循环：Debilitate（10 伤（A2 起 12）+ 2 易伤）/ Drain
      （3 层虚弱 + 自身力量+3）二选一 → Zap（18 伤（A2 起 21））/ Poke
      二选一，再回削弱/汲取。
    A17 起首回合固定 Hex，无 Poke 开局。
    """

    name = "Chosen"
    zh = "被拣选者"
    hp_range = (95, 99)
    hp_range_high = (98, 103)

    ZAP = MoveDef("Zap", "电击", "attack", base_damage=18)
    DRAIN = MoveDef("Drain", "汲取", "debuff", intent_text="施加 3 层虚弱，力量 +3")
    DEBILITATE = MoveDef("Debilitate", "削弱", "attack", base_damage=10)  # 另施加 2 层易伤
    HEX = MoveDef("Hex", "巫咒", "debuff", intent_text="施加 1 层巫咒")
    POKE = MoveDef("Poke", "戳刺", "attack", base_damage=5)  # ×2 段

    def __init__(self, idx: int, hp: int, max_hp: int):
        super().__init__(idx, hp, max_hp, "被拣选者(Chosen)")

    @classmethod
    def create(cls, bc: BattleContext, idx: int) -> "Chosen":
        hp = _roll_hp(bc, cls)
        return cls(idx, hp, hp)

    def get_move_for_roll(self, bc: BattleContext, roll: int) -> MoveDef:
        if bc.ascension >= 17:
            if not self.move_history:
                return self.HEX
        else:
            if not self.move_history:
                return self.POKE
            # 对齐 C++ lastMoveBefore(INVALID)：仅出过一招（首回合 Poke）
            if len(self.move_history) < 2:
                return self.HEX
        if not _last(self, "Debilitate") and not _last(self, "Drain"):
            return self.DEBILITATE if roll < 50 else self.DRAIN
        if roll < 40:
            return self.ZAP
        return self.POKE

    def take_turn(self, bc: BattleContext) -> None:
        move = self.move_history[0]
        match move.name:
            case "Zap":
                dmg = bc.calculate_monster_damage(self, 21 if bc.ascension >= 2 else 18)
                bc.log.append(f"{self.display_name} 使用 电击(Zap)。")
                bc.add_to_bot(Actions.attack_player(self.idx, dmg))
            case "Drain":
                bc.log.append(f"{self.display_name} 使用 汲取(Drain)。")
                bc.add_to_bot(Actions.debuff_player(PlayerStatus.WEAK, 3, True))
                self.statuses.add(MonsterStatus.STRENGTH, 3)
            case "Debilitate":
                dmg = bc.calculate_monster_damage(self, 12 if bc.ascension >= 2 else 10)
                bc.log.append(f"{self.display_name} 使用 削弱(Debilitate)。")
                bc.add_to_bot(Actions.attack_player(self.idx, dmg))
                bc.add_to_bot(Actions.debuff_player(PlayerStatus.VULNERABLE, 2, True))
            case "Hex":
                bc.log.append(f"{self.display_name} 使用 巫咒(Hex)。")
                bc.add_to_bot(Actions.debuff_player(PlayerStatus.HEX, 1, True))
            case "Poke":
                dmg = bc.calculate_monster_damage(self, 6 if bc.ascension >= 2 else 5)
                bc.log.append(f"{self.display_name} 使用 戳刺(Poke)。")
                for _ in range(2):
                    bc.add_to_bot(Actions.attack_player(self.idx, dmg))
            case _:
                raise AssertionError(f"未知招式 {move}")
        bc.add_to_bot(Actions.roll_move(self.idx))
        self.turns_taken += 1


class ShelledParasite(Monster):
    """甲壳寄生虫（Act 2 普通怪）：重甲 14（怪版）+ 开局 14 格挡。

    wiki/C++ A0：HP 68-72（A7 起 70-75）。preBattleAction：PLATED_ARMOR
    （本项目 PLATED_ARMOR_M）14 层 + 14 格挡——受未格挡攻击 -1 层，
    归零眩晕（引擎 _apply_damage 钩子 → on_stunned → STUNNED_MOVE），
    每回合开始按层得格挡（引擎 apply_start_of_turn_powers）。
    意图（A17 起首回合固定 Fell，否则 50/50 Double Strike/Suck）：
      Fell 18 伤（A2 起 21）+ 2 脆弱 / Double Strike 6×2（A2 起 7×2）/
      Suck 吸血攻击 10（A2 起 12，按漏格挡部分回血）/ Stunned 眩晕空转。
    眩晕后下次 roll 的 roll2 内层抽样见 get_move_for_roll（C++ 源码 2671-2694）。
    """

    name = "Shelled Parasite"
    zh = "带壳寄生怪"
    hp_range = (68, 72)
    hp_range_high = (70, 75)

    FELL = MoveDef("Fell", "击倒", "attack", base_damage=18)  # 另施加 2 层脆弱
    DOUBLE_STRIKE = MoveDef("Double Strike", "双重打击", "attack", base_damage=6)  # ×2 段
    SUCK = MoveDef("Suck", "吸取", "attack", base_damage=10)  # 吸血：按漏格挡伤害回血
    STUNNED_MOVE = MoveDef("Stunned", "眩晕", "unknown", intent_text="（无动作）")

    def __init__(self, idx: int, hp: int, max_hp: int):
        super().__init__(idx, hp, max_hp, "带壳寄生怪(Shelled Parasite)")
        # 对齐 C++ preBattleAction：PLATED_ARMOR 14 + 14 格挡
        self.statuses.add(MonsterStatus.PLATED_ARMOR_M, 14)
        self.block += 14

    @classmethod
    def create(cls, bc: BattleContext, idx: int) -> "ShelledParasite":
        hp = _roll_hp(bc, cls)
        return cls(idx, hp, hp)

    def get_move_for_roll(self, bc: BattleContext, roll: int) -> MoveDef:
        if not self.move_history:
            if bc.ascension >= 17:
                return self.FELL
            return self.DOUBLE_STRIKE if _ai_boolean(bc, 0.5) else self.SUCK
        roll2 = 100
        if roll < 20:
            if not _last(self, "Fell"):
                return self.FELL
            roll2 = bc.rngs.ai.int_inclusive(20, 99)
        if roll < 60 or roll2 < 60:
            if not _last_two(self, "Double Strike"):
                return self.DOUBLE_STRIKE
            return self.SUCK
        if not _last_two(self, "Suck"):
            return self.SUCK
        return self.DOUBLE_STRIKE

    def _vampire_attack(self, bc: BattleContext, dmg: int) -> Action:
        """吸血攻击（对齐 Actions::VampireAttack）：命中后按漏格挡量回血。"""

        def run(bcb: BattleContext) -> None:
            saved_block = bcb.player.block
            bcb.player.attacked(bcb, self.idx, dmg)
            if not self.is_dying:
                heal = min(dmg, max(0, dmg - saved_block))
                self.hp = min(self.max_hp, self.hp + heal)

        return Action(run)

    def take_turn(self, bc: BattleContext) -> None:
        move = self.move_history[0]
        match move.name:
            case "Fell":
                dmg = bc.calculate_monster_damage(self, 21 if bc.ascension >= 2 else 18)
                bc.log.append(f"{self.display_name} 使用 击倒(Fell)。")
                bc.add_to_bot(Actions.attack_player(self.idx, dmg))
                bc.add_to_bot(Actions.debuff_player(PlayerStatus.FRAIL, 2, True))
            case "Double Strike":
                dmg = bc.calculate_monster_damage(self, 7 if bc.ascension >= 2 else 6)
                bc.log.append(f"{self.display_name} 使用 双重打击(Double Strike)，{dmg} 点伤害 ×2。")
                for _ in range(2):
                    bc.add_to_bot(Actions.attack_player(self.idx, dmg))
            case "Suck":
                dmg = bc.calculate_monster_damage(self, 12 if bc.ascension >= 2 else 10)
                bc.log.append(f"{self.display_name} 使用 吸取(Suck)。")
                bc.add_to_bot(self._vampire_attack(bc, dmg))
            case "Stunned":
                # 对齐 C++：setMove(FELL) 后 rollMove（眩晕空转一回合）
                bc.log.append(f"{self.display_name} 眩晕了！")
                self.set_move(self.FELL)
                bc.add_to_bot(Actions.roll_move(self.idx))
            case _:
                raise AssertionError(f"未知招式 {move}")
        if move.name != "Stunned":
            bc.add_to_bot(Actions.roll_move(self.idx))
        self.turns_taken += 1


class Byrd(Monster):
    """伯德鸟（Act 2 普通怪）：飞行 3（A17 起 4），落地眩晕链。

    wiki/C++ A0：HP 25-31（A7 起 26-33）。preBattleAction：FLIGHT 3。
    每回合开始若仍在飞，FLIGHT 回满 3/4（C++ applyStartOfTurnPowers，
    引擎未做——子类覆盖钩子实现）；受未格挡攻击 -1 层，归零落地眩晕
    （引擎 _apply_damage）→ Stunned（空转）→ Headbutt（3 伤）→ Fly
    （重新起飞）。
    意图 roll 分段（首回合 37.5% Caw / 62.5% Peck；之后）：
      roll < 50：Peck 已连续两回合 → 内层 40% Swoop / 60% Caw；否则 Peck
      roll < 70：上回合 Swoop → 内层 37.5% Caw / 62.5% Peck；否则 Swoop
      roll ≥ 70：上回合 Caw → 内层 28.57% Swoop / 71.43% Peck；否则 Caw
    数值：Peck 1 伤 ×5 段（A2 起 ×6 段）；Swoop 12 伤（A2 起 14）；
      Caw 力量 +1。
    """

    name = "Byrd"
    zh = "异鸟"
    hp_range = (25, 31)
    hp_range_high = (26, 33)

    PECK = MoveDef("Peck", "啄击", "attack", base_damage=1)  # ×5 段（A2 起 ×6）
    SWOOP = MoveDef("Swoop", "俯冲", "attack", base_damage=12)
    CAW = MoveDef("Caw", "鸣叫", "buff", intent_text="力量 +1")
    FLY = MoveDef("Fly", "起飞", "buff", intent_text="获得 3 层飞行")
    HEADBUTT = MoveDef("Headbutt", "头槌", "attack", base_damage=3)
    STUNNED_MOVE = MoveDef("Stunned", "眩晕", "unknown", intent_text="（无动作）")

    def __init__(self, idx: int, hp: int, max_hp: int):
        super().__init__(idx, hp, max_hp, "异鸟(Byrd)")
        # 对齐 C++ preBattleAction：FLIGHT 3（A17 起 4，由 create 覆盖）
        self.statuses.add(MonsterStatus.FLIGHT, 3)

    @classmethod
    def create(cls, bc: BattleContext, idx: int) -> "Byrd":
        hp = _roll_hp(bc, cls)
        m = cls(idx, hp, hp)
        if bc.ascension >= 17:
            m.statuses.set(MonsterStatus.FLIGHT, 4)
        return m

    def apply_start_of_turn_powers(self, bc: BattleContext) -> None:
        # 对齐 C++ applyStartOfTurnPowers：仍在飞则 FLIGHT 回满 3/4
        #（落地后 hasStatus 为假，不再自动起飞——须靠 Fly 招式）
        super().apply_start_of_turn_powers(bc)
        if self.statuses.has(MonsterStatus.FLIGHT):
            self.statuses.set(MonsterStatus.FLIGHT, 4 if bc.ascension >= 17 else 3)

    def attacked(self, bc: BattleContext, damage: int) -> None:
        # Flying 的伤害减半（本体 FlightPower.atDamageFinalReceive /
        # lightspeed BattleContext.cpp:2733 的 ×0.5 乘区）：引擎
        # calculate_card_damage 未接线该乘区，以 attacked 覆盖在格挡
        # 吸收前折半等效（非攻击 HP 损失不吃减半——damage() 路径不覆盖）。
        if damage > 0 and self.statuses.has(MonsterStatus.FLIGHT):
            damage = damage // 2
        super().attacked(bc, damage)

    def get_move_for_roll(self, bc: BattleContext, roll: int) -> MoveDef:
        if not self.move_history:
            return self.CAW if _ai_boolean(bc, 0.375) else self.PECK
        if roll < 50:
            if _last_two(self, "Peck"):
                return self.SWOOP if _ai_boolean(bc, 0.4) else self.CAW
            return self.PECK
        if roll < 70:
            if _last(self, "Swoop"):
                return self.CAW if _ai_boolean(bc, 0.375) else self.PECK
            return self.SWOOP
        if _last(self, "Caw"):
            return self.SWOOP if _ai_boolean(bc, 0.2857) else self.PECK
        return self.CAW

    def take_turn(self, bc: BattleContext) -> None:
        move = self.move_history[0]
        match move.name:
            case "Caw":
                self.statuses.add(MonsterStatus.STRENGTH, 1)
                bc.log.append(f"{self.display_name} 使用 鸣叫(Caw)，力量 +1。")
            case "Fly":
                self.statuses.add(MonsterStatus.FLIGHT, 4 if bc.ascension >= 17 else 3)
                bc.log.append(f"{self.display_name} 使用 起飞(Fly)。")
            case "Headbutt":
                dmg = bc.calculate_monster_damage(self, 3)
                bc.log.append(f"{self.display_name} 使用 头槌(Headbutt)。")
                bc.add_to_bot(Actions.attack_player(self.idx, dmg))
                self.set_move(self.FLY)
                self.turns_taken += 1
                return  # 对齐 C++：Headbutt 分支无 RollMove 入队
            case "Peck":
                # 对齐 C++ attackPlayerHelper(bc, 1, asc2 ? 6 : 5)：1 伤，A2 起段数 5→6
                dmg = bc.calculate_monster_damage(self, 1)
                hits = 6 if bc.ascension >= 2 else 5
                bc.log.append(f"{self.display_name} 使用 啄击(Peck)，{dmg} 点伤害 ×{hits}。")
                for _ in range(hits):
                    bc.add_to_bot(Actions.attack_player(self.idx, dmg))
            case "Swoop":
                dmg = bc.calculate_monster_damage(self, 14 if bc.ascension >= 2 else 12)
                bc.log.append(f"{self.display_name} 使用 俯冲(Swoop)。")
                bc.add_to_bot(Actions.attack_player(self.idx, dmg))
            case "Stunned":
                bc.log.append(f"{self.display_name} 眩晕了！")
                bc.add_to_bot(Actions.no_op_roll_move())
                self.set_move(self.HEADBUTT)
                self.turns_taken += 1
                return  # 对齐 C++：noOpRollMove + setMove(HEADBUTT)，无 RollMove
            case _:
                raise AssertionError(f"未知招式 {move}")
        bc.add_to_bot(Actions.roll_move(self.idx))
        self.turns_taken += 1


class SnakePlant(Monster):
    """蛇藤（Act 2 普通怪）：可塑 3——受击得层格挡且层+1，回合末回满 3。

    wiki/C++ A0：HP 75-79（A7 起 78-82）。preBattleAction：MALLEABLE 3
    （受未格挡攻击获得当前层格挡且 +1 层，引擎 _apply_damage；回合末
    重置回 3，C++ applyEndOfTurnTriggers——子类覆盖钩子实现）。
    意图 roll 分段：
      A0：roll < 65：Chomp 已连续两回合 → 孢子，否则 Chomp（7×3，
      A2 起 8×3）；否则 上回合孢子 → Chomp，否则 Enfeebling Spores
      （2 层脆弱 + 2 层虚弱）。
      A17：第三段改判 孢子未连续两回合 → 孢子。
    """

    name = "Snake Plant"
    zh = "蛇花"
    hp_range = (75, 79)
    hp_range_high = (78, 82)

    CHOMP = MoveDef("Chomp", "咬啃", "attack", base_damage=7)  # ×3 段
    ENFEEBLING_SPORES = MoveDef("Enfeebling Spores", "虚弱孢子", "debuff", intent_text="施加 2 层脆弱与 2 层虚弱")

    def __init__(self, idx: int, hp: int, max_hp: int):
        super().__init__(idx, hp, max_hp, "蛇花(Snake Plant)")
        self.statuses.add(MonsterStatus.MALLEABLE, 3)

    @classmethod
    def create(cls, bc: BattleContext, idx: int) -> "SnakePlant":
        hp = _roll_hp(bc, cls)
        return cls(idx, hp, hp)

    def apply_end_of_turn_triggers(self, bc: BattleContext) -> None:
        # 对齐 C++ applyEndOfTurnTriggers：MALLEABLE 回满 3
        super().apply_end_of_turn_triggers(bc)
        if self.statuses.has(MonsterStatus.MALLEABLE):
            self.statuses.set(MonsterStatus.MALLEABLE, 3)

    def get_move_for_roll(self, bc: BattleContext, roll: int) -> MoveDef:
        if roll < 65:
            return self.ENFEEBLING_SPORES if _last_two(self, "Chomp") else self.CHOMP
        if bc.ascension >= 17:
            return self.CHOMP if _last_two(self, "Enfeebling Spores") else self.ENFEEBLING_SPORES
        return self.CHOMP if _last(self, "Enfeebling Spores") else self.ENFEEBLING_SPORES

    def take_turn(self, bc: BattleContext) -> None:
        move = self.move_history[0]
        match move.name:
            case "Chomp":
                dmg = bc.calculate_monster_damage(self, 8 if bc.ascension >= 2 else 7)
                bc.log.append(f"{self.display_name} 使用 咬啃(Chomp)，{dmg} 点伤害 ×3。")
                for _ in range(3):
                    bc.add_to_bot(Actions.attack_player(self.idx, dmg))
            case "Enfeebling Spores":
                bc.log.append(f"{self.display_name} 使用 虚弱孢子(Enfeebling Spores)。")
                bc.add_to_bot(Actions.debuff_player(PlayerStatus.FRAIL, 2, True))
                bc.add_to_bot(Actions.debuff_player(PlayerStatus.WEAK, 2, True))
            case _:
                raise AssertionError(f"未知招式 {move}")
        bc.add_to_bot(Actions.roll_move(self.idx))
        self.turns_taken += 1


class Snecko(Monster):
    """蛇颈龙（Act 2 普通怪，单怪遭遇）：首回合迷惑视线施加 1 层混乱。

    wiki/C++ A0：HP 114-120（A7 起 120-125）。首回合固定 Perplexing Glare
    （CONFUSED 1——此后每次抽牌费用随机 0~3，引擎 on_card_drawn），
    之后 roll 分段：roll < 40 或 Bite 已连续两回合 → Tail Whip（8 伤
    （A2 起 10）+ 2 易伤，A17 起另加 2 虚弱）；否则 Bite（15 伤，
    A2 起 18）。C++ 只在首回合施一次混乱，并非每回合。
    """

    name = "Snecko"
    zh = "异蛇"
    hp_range = (114, 120)
    hp_range_high = (120, 125)

    PERPLEXING_GLARE = MoveDef("Perplexing Glare", "困惑瞪视", "debuff", intent_text="施加 1 层混乱")
    BITE = MoveDef("Bite", "噬咬", "attack", base_damage=15)
    TAIL_WHIP = MoveDef("Tail Whip", "扫尾", "attack", base_damage=8)  # 另施加 2 层易伤

    def __init__(self, idx: int, hp: int, max_hp: int):
        super().__init__(idx, hp, max_hp, "异蛇(Snecko)")

    @classmethod
    def create(cls, bc: BattleContext, idx: int) -> "Snecko":
        hp = _roll_hp(bc, cls)
        return cls(idx, hp, hp)

    def get_move_for_roll(self, bc: BattleContext, roll: int) -> MoveDef:
        if not self.move_history:
            return self.PERPLEXING_GLARE
        if roll < 40 or _last_two(self, "Bite"):
            return self.TAIL_WHIP
        return self.BITE

    def take_turn(self, bc: BattleContext) -> None:
        move = self.move_history[0]
        match move.name:
            case "Perplexing Glare":
                bc.log.append(f"{self.display_name} 使用 困惑瞪视(Perplexing Glare)，你被混乱了！")
                bc.add_to_bot(Actions.debuff_player(PlayerStatus.CONFUSED, 1, True))
            case "Bite":
                dmg = bc.calculate_monster_damage(self, 18 if bc.ascension >= 2 else 15)
                bc.log.append(f"{self.display_name} 使用 噬咬(Bite)。")
                bc.add_to_bot(Actions.attack_player(self.idx, dmg))
            case "Tail Whip":
                dmg = bc.calculate_monster_damage(self, 10 if bc.ascension >= 2 else 8)
                bc.log.append(f"{self.display_name} 使用 扫尾(Tail Whip)。")
                bc.add_to_bot(Actions.attack_player(self.idx, dmg))
                bc.add_to_bot(Actions.debuff_player(PlayerStatus.VULNERABLE, 2, True))
                if bc.ascension >= 17:
                    bc.add_to_bot(Actions.debuff_player(PlayerStatus.WEAK, 2, True))
            case _:
                raise AssertionError(f"未知招式 {move}")
        bc.add_to_bot(Actions.roll_move(self.idx))
        self.turns_taken += 1


class Centurion(Monster):
    """百夫长（Act 2 centurion_and_healer 遭遇首位）：斩击/防御/狂怒。

    wiki/C++ A0：HP 76-80（A7 起 76-83）。roll 分段（mysticAlive =
    存活数 > 1，即秘术师在场）：
      roll ≥ 65 且 防御/狂怒均未连续两回合 → 防御（秘术师在场）/ 狂怒
      斩击未连续两回合 → 斩击
      否则 → 防御/狂怒（按 mysticAlive）
    数值：斩击 12 伤（A2 起 14）；防御给秘术师 15 格挡（A17 起 20，
    立即结算）；狂怒 6×3（A2 起 7×3）。
    """

    name = "Centurion"
    zh = "百夫长"
    hp_range = (76, 80)
    hp_range_high = (76, 83)

    SLASH = MoveDef("Slash", "斩击", "attack", base_damage=12)
    DEFEND = MoveDef("Defend", "防御", "defend", intent_text="为秘术师提供 15 点格挡")
    FURY = MoveDef("Fury", "狂怒", "attack", base_damage=6)  # ×3 段

    def __init__(self, idx: int, hp: int, max_hp: int):
        super().__init__(idx, hp, max_hp, "百夫长(Centurion)")

    @classmethod
    def create(cls, bc: BattleContext, idx: int) -> "Centurion":
        hp = _roll_hp(bc, cls)
        return cls(idx, hp, hp)

    def get_move_for_roll(self, bc: BattleContext, roll: int) -> MoveDef:
        mystic_alive = bc.monsters.alive_count > 1
        if roll >= 65 and not _last_two(self, "Defend") and not _last_two(self, "Fury"):
            return self.DEFEND if mystic_alive else self.FURY
        if not _last_two(self, "Slash"):
            return self.SLASH
        return self.DEFEND if mystic_alive else self.FURY

    def take_turn(self, bc: BattleContext) -> None:
        move = self.move_history[0]
        match move.name:
            case "Slash":
                dmg = bc.calculate_monster_damage(self, 14 if bc.ascension >= 2 else 12)
                bc.log.append(f"{self.display_name} 使用 斩击(Slash)。")
                bc.add_to_bot(Actions.attack_player(self.idx, dmg))
            case "Defend":
                bc.log.append(f"{self.display_name} 使用 防御(Defend)。")
                amount = 20 if bc.ascension >= 17 else 15
                mystic = bc.monsters.monsters[1] if bc.monsters.monster_count > 1 else None
                if mystic is not None and not mystic.is_dead_or_escaped():
                    mystic.block += amount  # C++ addBlock 立即结算
                else:
                    # 本体 Centurion.java：Protect 走 GainBlockRandomMonsterAction
                    # （排除自身的随机存活怪，无其余存活怪时给自身）——秘术师
                    # 已死时百夫长给自己格挡；lightspeed 固定 arr[1] 死亡即不加。
                    self.block += amount
            case "Fury":
                dmg = bc.calculate_monster_damage(self, 7 if bc.ascension >= 2 else 6)
                bc.log.append(f"{self.display_name} 使用 狂怒(Fury)，{dmg} 点伤害 ×3。")
                for _ in range(3):
                    bc.add_to_bot(Actions.attack_player(self.idx, dmg))
            case _:
                raise AssertionError(f"未知招式 {move}")
        bc.add_to_bot(Actions.roll_move(self.idx))
        self.turns_taken += 1


class Mystic(Monster):
    """秘术师（Act 2 centurion_and_healer 遭遇次位）：治疗/增益/削弱攻击。

    wiki/C++ A0：HP 48-56（A7 起 50-58）。roll 分段：
      自身或百夫长（arr[0]）缺血 ≥ 16（A17 起 21）→ 治疗（回复 16
      （A17 起 20），先百夫长后自身，立即结算）；
      roll ≥ 40 且 削弱攻击未连续两回合（A17 起上回合出过即算）→
      削弱攻击（8 伤（A2 起 9）+ 2 脆弱）；
      增益未连续两回合 → 增益（百夫长（若在场）与自身 力量 +2
      （A2 起 +3、A17 起 +4））；否则削弱攻击。
    """

    name = "Mystic"
    zh = "神秘术士"
    hp_range = (48, 56)
    hp_range_high = (50, 58)

    ATTACK_DEBUFF = MoveDef("Attack Debuff", "削弱攻击", "attack", base_damage=8)  # 另施加 2 层脆弱
    BUFF = MoveDef("Buff", "增益", "buff", intent_text="百夫长与自身力量 +2")
    HEAL = MoveDef("Heal", "治疗", "buff", intent_text="治疗自身与百夫长 16 点 HP")

    def __init__(self, idx: int, hp: int, max_hp: int):
        super().__init__(idx, hp, max_hp, "神秘术士(Mystic)")

    @classmethod
    def create(cls, bc: BattleContext, idx: int) -> "Mystic":
        hp = _roll_hp(bc, cls)
        return cls(idx, hp, hp)

    def get_move_for_roll(self, bc: BattleContext, roll: int) -> MoveDef:
        heal_need = 21 if bc.ascension >= 17 else 16
        knight = bc.monsters.monsters[0]
        if self.max_hp - self.hp >= heal_need or (knight.hp > 0 and knight.max_hp - knight.hp >= heal_need):
            return self.HEAL
        not_repeat = not _last(self, "Attack Debuff") if bc.ascension >= 17 else not _last_two(self, "Attack Debuff")
        if roll >= 40 and not_repeat:
            return self.ATTACK_DEBUFF
        if not _last_two(self, "Buff"):
            return self.BUFF
        return self.ATTACK_DEBUFF

    def take_turn(self, bc: BattleContext) -> None:
        move = self.move_history[0]
        match move.name:
            case "Attack Debuff":
                dmg = bc.calculate_monster_damage(self, 9 if bc.ascension >= 2 else 8)
                bc.log.append(f"{self.display_name} 使用 削弱攻击(Attack Debuff)。")
                bc.add_to_bot(Actions.attack_player(self.idx, dmg))
                bc.add_to_bot(Actions.debuff_player(PlayerStatus.FRAIL, 2, True))
            case "Buff":
                amt = 4 if bc.ascension >= 17 else 3 if bc.ascension >= 2 else 2
                bc.log.append(f"{self.display_name} 使用 增益(Buff)，力量 +{amt}。")
                if bc.monsters.alive_count > 1:
                    knight = bc.monsters.monsters[0]
                    knight.statuses.add(MonsterStatus.STRENGTH, amt)
                self.statuses.add(MonsterStatus.STRENGTH, amt)
            case "Heal":
                amt = 20 if bc.ascension >= 17 else 16
                bc.log.append(f"{self.display_name} 使用 治疗(Heal)，回复 {amt} 点 HP。")
                if bc.monsters.alive_count > 1:
                    knight = bc.monsters.monsters[0]
                    knight.hp = min(knight.max_hp, knight.hp + amt)
                self.hp = min(self.max_hp, self.hp + amt)
            case _:
                raise AssertionError(f"未知招式 {move}")
        bc.add_to_bot(Actions.roll_move(self.idx))
        self.turns_taken += 1


def _alive_gremlin_count(bc: BattleContext) -> int:
    """存活小鬼数（对齐 C++ getAliveGremlinCount：只数槽 0-2，首领在槽 3）。"""
    group = bc.monsters
    n = 0
    for i in range(3):
        if i < group.monster_count and not group.monsters[i].is_dead_or_escaped():
            n += 1
    return n


def _summon_gremlins_action() -> Action:
    """召唤 2 只随机小鬼（对齐 Actions::SummonGremlins）。

    按 1、2、0 的顺序找空槽（死亡/逃跑占位），原位覆写生成；
    池 = 8 槽小鬼池（misc 流抽样，对齐 C++ getGremlin 的用途划分）；
    新小鬼带 MINION 并立即 roll 一次意图。C++ 硬断言恰有 2 空槽
    （Rally 只在存活 ≤1 时被选）——此处防御性取 min(2, 空槽数)。
    """

    def run(bcb: BattleContext) -> None:
        group = bcb.monsters
        open_slots = [i for i in (1, 2, 0) if group.monsters[i].is_dead_or_escaped()]
        for slot in open_slots[:2]:
            m = _random_gremlin(bcb).create(bcb, slot)
            group.spawn_replace(bcb, slot, m)
            m.statuses.add(MonsterStatus.MINION, 1)
            m.roll_spawned_move(bcb)
            bcb.log.append(f"{m.display_name} 被召唤进场！")

    return Action(run)


class GremlinLeader(Monster):
    """小鬼头目（Act 2 精英，gremlin_leader 遭遇）：主死即胜 + 召唤小鬼。

    wiki/C++ A0：HP 140-148（A8 起 145-155）。遭遇布局（encounters）：
    槽 1/2 = 随机小鬼（MINION）、槽 3 = 首领、槽 0 = 死亡占位；
    preBattleAction：MINION_LEADER（死亡即判胜，引擎 die()）。
    roll 分段按存活小鬼数（numAliveGremlins = 槽 0-2 存活数）：
      0 只：roll < 75：上回合 Rally → Stab，否则 Rally；
           roll ≥ 75：上回合 Stab → Rally，否则 Stab。
      1 只：roll < 50：上回合 Rally → 内层 roll2∈[50,99]：<80 Encourage /
           ≥80 Stab；否则 Rally；
           50 ≤ roll < 80：上回合 Encourage → Stab，否则 Encourage；
           roll ≥ 80：上回合 Stab → 内层 roll2∈[0,80]：<50 Rally /
           ≥50 Encourage；否则 Stab。
      ≥2 只：roll < 66：上回合 Encourage → Stab，否则 Encourage；
             roll ≥ 66：上回合 Stab → Encourage，否则 Stab。
    招式：Encourage——存活小鬼（槽 0-2）力量 +3（A3 起 +4、A18 起 +5）
    且格挡 +6（A18 起 +10，立即结算），自身力量同 +；Rally——召唤 2 只
    随机小鬼进空槽；Stab——6 伤 ×3。
    """

    name = "Gremlin Leader"
    zh = "地精首领"
    hp_range = (140, 148)
    hp_range_high = (145, 155)
    hp_high_asc = 8

    ENCOURAGE = MoveDef("Encourage", "鼓动", "buff", intent_text="小鬼们力量 +3、格挡 +6，自身力量 +3")
    RALLY = MoveDef("Rally", "集合！", "unknown", intent_text="召唤 2 只随机小鬼")
    STAB = MoveDef("Stab", "刺击", "attack", base_damage=6)  # ×3 段

    def __init__(self, idx: int, hp: int, max_hp: int):
        super().__init__(idx, hp, max_hp, "地精首领(Gremlin Leader)")
        # 对齐 C++ preBattleAction：MINION_LEADER
        self.statuses.add(MonsterStatus.MINION_LEADER, 1)

    @classmethod
    def create(cls, bc: BattleContext, idx: int) -> "GremlinLeader":
        hp = _roll_hp(bc, cls)
        return cls(idx, hp, hp)

    def get_move_for_roll(self, bc: BattleContext, roll: int) -> MoveDef:
        n = _alive_gremlin_count(bc)
        if n == 0:
            if roll < 75:
                return self.STAB if _last(self, "Rally") else self.RALLY
            return self.RALLY if _last(self, "Stab") else self.STAB
        if n == 1:
            if roll < 50:
                if _last(self, "Rally"):
                    roll2 = bc.rngs.ai.int_inclusive(50, 99)
                    return self.ENCOURAGE if roll2 < 80 else self.STAB
                return self.RALLY
            if roll < 80:
                return self.STAB if _last(self, "Encourage") else self.ENCOURAGE
            if _last(self, "Stab"):
                roll2 = bc.rngs.ai.int_inclusive(0, 80)
                return self.RALLY if roll2 < 50 else self.ENCOURAGE
            return self.STAB
        # n >= 2
        if roll < 66:
            return self.STAB if _last(self, "Encourage") else self.ENCOURAGE
        return self.ENCOURAGE if _last(self, "Stab") else self.STAB

    def take_turn(self, bc: BattleContext) -> None:
        move = self.move_history[0]
        match move.name:
            case "Encourage":
                str_gain = 5 if bc.ascension >= 18 else 4 if bc.ascension >= 3 else 3
                # 格挡 6、A18 起 10（本体 GremlinLeader.java：A_18_BLOCK_AMT=10，
                # 力量三档走 A3/A18 两档与格挡不同步；lightspeed 误用 asc3，
                # wiki 记 A18 为准）
                block_gain = 10 if bc.ascension >= 18 else 6
                bc.log.append(f"{self.display_name} 使用 鼓动(Encourage)，小鬼们力量 +{str_gain}、格挡 +{block_gain}！")
                for i in range(min(3, bc.monsters.monster_count)):
                    minion = bc.monsters.monsters[i]
                    if not minion.is_dead_or_escaped():
                        minion.statuses.add(MonsterStatus.STRENGTH, str_gain)
                        minion.block += block_gain  # C++ addBlock 立即结算
                self.statuses.add(MonsterStatus.STRENGTH, str_gain)
            case "Rally":
                bc.log.append(f"{self.display_name} 使用 集合！(Rally)！")
                bc.add_to_bot(_summon_gremlins_action())
            case "Stab":
                dmg = bc.calculate_monster_damage(self, 6)
                bc.log.append(f"{self.display_name} 使用 刺击(Stab)，{dmg} 点伤害 ×3。")
                for _ in range(3):
                    bc.add_to_bot(Actions.attack_player(self.idx, dmg))
            case _:
                raise AssertionError(f"未知招式 {move}")
        bc.add_to_bot(Actions.roll_move(self.idx))
        self.turns_taken += 1


class BookOfStabbing(Monster):
    """刺击之书（Act 2 精英）：痛苦刺击 + 单刺/多段刺循环。

    wiki/C++ A0：HP 160-164（A8 起 168-172）。preBattleAction：
    PAINFUL_STABS 1（玩家每打出攻击牌受 1 伤，引擎 on_use_attack_card）
    + miscInfo 置 1（多段刺段数计数）。roll 分段：
      roll < 15：上回合 Single Stab → 计数 +1 出 Multi Stab；
                 否则 Single Stab（A18 起计数也 +1）；
      上两回合均 Multi Stab → Single Stab（A18 起计数也 +1）；
      否则 → 计数 +1 出 Multi Stab。
    （本体 BookOfStabbing.java 的 A18 ++stabCount 真实可达——lightspeed
    误译到 return 之后成死代码，此处按本体补回：A18 起每回合选择 Single
    Stab 也 +1 计数，净效果同 wiki"段数随回合递增"。）
    数值：Single Stab 21 伤（A3 起 24）；Multi Stab 6 伤（A3 起 7）
    × 当前计数（首段从 2 起，之后每次选用 Multi Stab 计数 +1）。
    """

    name = "Book of Stabbing"
    zh = "扎人的书"
    hp_range = (160, 164)
    hp_range_high = (168, 172)
    hp_high_asc = 8

    MULTI_STAB = MoveDef("Multi Stab", "多段刺", "attack", base_damage=6)  # ×计数 段
    SINGLE_STAB = MoveDef("Single Stab", "单刺", "attack", base_damage=21)

    def __init__(self, idx: int, hp: int, max_hp: int):
        super().__init__(idx, hp, max_hp, "扎人的书(Book of Stabbing)")
        # 对齐 C++ preBattleAction：PAINFUL_STABS + 计数起点 1
        self.statuses.add(MonsterStatus.PAINFUL_STABS, 1)
        self.misc_info = 1

    @classmethod
    def create(cls, bc: BattleContext, idx: int) -> "BookOfStabbing":
        hp = _roll_hp(bc, cls)
        return cls(idx, hp, hp)

    def get_move_for_roll(self, bc: BattleContext, roll: int) -> MoveDef:
        if roll < 15:
            if _last(self, "Single Stab"):
                self.misc_info += 1
                return self.MULTI_STAB
            # A18：选 Single Stab 时计数也 +1（本体可达分支，lightspeed 死代码）
            if bc.ascension >= 18:
                self.misc_info += 1
            return self.SINGLE_STAB
        if _last_two(self, "Multi Stab"):
            if bc.ascension >= 18:
                self.misc_info += 1
            return self.SINGLE_STAB
        self.misc_info += 1
        return self.MULTI_STAB

    def take_turn(self, bc: BattleContext) -> None:
        move = self.move_history[0]
        match move.name:
            case "Multi Stab":
                dmg = bc.calculate_monster_damage(self, 7 if bc.ascension >= 3 else 6)
                bc.log.append(f"{self.display_name} 使用 多段刺(Multi Stab)，{dmg} 点伤害 ×{self.misc_info}！")
                for _ in range(self.misc_info):
                    bc.add_to_bot(Actions.attack_player(self.idx, dmg))
            case "Single Stab":
                dmg = bc.calculate_monster_damage(self, 24 if bc.ascension >= 3 else 21)
                bc.log.append(f"{self.display_name} 使用 单刺(Single Stab)。")
                bc.add_to_bot(Actions.attack_player(self.idx, dmg))
            case _:
                raise AssertionError(f"未知招式 {move}")
        bc.add_to_bot(Actions.roll_move(self.idx))
        self.turns_taken += 1


def _spawn_bronze_orbs(bc: BattleContext, automaton: "BronzeAutomaton") -> None:
    """生成 2 只青铜球（对齐 Monster::spawnBronzeOrbs，MonsterSpecific.cpp:3393-3410）。

    槽 0/2 原位覆写（automaton 在槽 1），各带 MINION 并立即 roll 意图
    （spawn_replace 的遗物钩子即 C++ 的 PHILOSOPHERS_STONE +1 力量）。
    monster_turn_idx 额外 +1：配合 do_monster_turn 尾部的 +1，合计跳过
    槽 2 青铜球本回合的行动（槽 0 已被回合指针越过，两只都不动）。
    """
    group = bc.monsters
    orb1 = BronzeOrb.create(bc, 0)
    orb2 = BronzeOrb.create(bc, 2)
    group.spawn_replace(bc, 0, orb1)
    group.spawn_replace(bc, 2, orb2)
    for orb in (orb1, orb2):
        orb.statuses.add(MonsterStatus.MINION, 1)
        orb.roll_spawned_move(bc)
    bc.monster_turn_idx += 1
    bc.log.append(f"{automaton.display_name} 召唤了 2 只青铜球！")


class BronzeAutomaton(Monster):
    """青铜自律机（Act 2 Boss，automaton 遭遇，槽 1）：召唤青铜球后循环。

    wiki/C++ A0：HP 300（A9 起 320）。preBattleAction：MINION_LEADER +
    ARTIFACT 3。遭遇布局：槽 0/2 为死亡占位（开局 Spawn Orbs 填充）。
    意图链（rollMove 仅首回合一次，此后 set_move + noOpRollMove）：
      Spawn Orbs（生成 2 球，本回合两球均不行动）→ Flail（7×2（A4 起
      8×2））→ Boost（力量 +3（A4 起 +4）、格挡 +9（A9 起 +12），misc
      记录上次 Boost 后是否 Flail）→ Flail → Boost → Hyper Beam
      （45 伤（A4 起 50））→ Stunned（空转；A19 起改为 Boost）→
      Flail → Boost → Hyper Beam → ……
    """

    name = "Bronze Automaton"
    zh = "铜制机械人偶"
    hp_range = (300, 300)
    hp_range_high = (320, 320)
    hp_high_asc = 9

    FLAIL = MoveDef("Flail", "连枷", "attack", base_damage=7)  # ×2 段
    BOOST = MoveDef("Boost", "充能", "buff", intent_text="力量 +3，格挡 +9")
    HYPER_BEAM = MoveDef("Hyper Beam", "超能光束", "attack", base_damage=45)
    SPAWN_ORBS = MoveDef("Spawn Orbs", "召球", "unknown", intent_text="召唤 2 只青铜球")
    STUNNED = MoveDef("Stunned", "眩晕", "unknown", intent_text="（无动作）")

    def __init__(self, idx: int, hp: int, max_hp: int):
        super().__init__(idx, hp, max_hp, "铜制机械人偶(Bronze Automaton)")
        # 对齐 C++ preBattleAction：MINION_LEADER + ARTIFACT 3
        self.statuses.add(MonsterStatus.MINION_LEADER, 1)
        self.statuses.add(MonsterStatus.ARTIFACT, 3)

    @classmethod
    def create(cls, bc: BattleContext, idx: int) -> "BronzeAutomaton":
        hp = _roll_hp(bc, cls)
        return cls(idx, hp, hp)

    def get_move_for_roll(self, bc: BattleContext, roll: int) -> MoveDef:
        # C++ 注释 called first turn only；此后 take_turn 全 set_move
        return self.SPAWN_ORBS

    def take_turn(self, bc: BattleContext) -> None:
        move = self.move_history[0]
        match move.name:
            case "Flail":
                dmg = bc.calculate_monster_damage(self, 8 if bc.ascension >= 4 else 7)
                bc.log.append(f"{self.display_name} 使用 连枷(Flail)，{dmg} 点伤害 ×2。")
                for _ in range(2):
                    bc.add_to_bot(Actions.attack_player(self.idx, dmg))
                self.set_move(self.BOOST)
            case "Boost":
                self.statuses.add(MonsterStatus.STRENGTH, 4 if bc.ascension >= 4 else 3)
                self.block += 12 if bc.ascension >= 9 else 9  # C++ addBlock 立即结算
                bc.log.append(f"{self.display_name} 使用 充能(Boost)。")
                # misc_info = 上次 Boost 后是否经过 Flail（对齐 C++ lastBoostWasFlail）
                if self.misc_info:
                    self.set_move(self.HYPER_BEAM)
                    self.misc_info = 0
                else:
                    self.set_move(self.FLAIL)
                    self.misc_info = 1
            case "Hyper Beam":
                dmg = bc.calculate_monster_damage(self, 50 if bc.ascension >= 4 else 45)
                bc.log.append(f"{self.display_name} 使用 超能光束(Hyper Beam)！")
                bc.add_to_bot(Actions.attack_player(self.idx, dmg))
                self.set_move(self.BOOST if bc.ascension >= 19 else self.STUNNED)
            case "Spawn Orbs":
                bc.log.append(f"{self.display_name} 使用 召球(Spawn Orbs)。")
                _spawn_bronze_orbs(bc, self)
                self.set_move(self.FLAIL)
            case "Stunned":
                bc.log.append(f"{self.display_name} 眩晕了！")
                self.set_move(self.FLAIL)
            case _:
                raise AssertionError(f"未知招式 {move}")
        bc.add_to_bot(Actions.no_op_roll_move())
        self.turns_taken += 1


def _stasis_steal(bc: BattleContext, orb: "BronzeOrb") -> None:
    """静滞偷牌（对齐 Monster::stasisAction）：从抽牌堆（空则弃牌堆）
    随机抽 1 张挂到实例 stasis_cards 并从原堆移除；死亡时引擎 die()
    归还弃牌堆。C++ stasisHelper 的稀有度偏好（RARE>UNCOMMON>COMMON）
    需要 rarity 字段——CardDef 无此字段，改为整堆均匀随机（misc 流；
    对全 BASIC/COMMON 的起手牌组分布与 C++ 完全一致）。
    """
    cards = bc.cards
    if not cards.draw_pile and not cards.discard_pile:
        return  # 两堆皆空：什么都不做
    if cards.draw_pile:
        pile = cards.draw_pile
    else:
        pile = cards.discard_pile
    inst = pile[bc.rngs.misc.int_inclusive(0, len(pile) - 1)]
    pile.remove(inst)
    orb.stasis_cards.append(inst)
    orb.statuses.add(MonsterStatus.STASIS, 1)
    bc.log.append(f"{orb.display_name} 静滞了你的 {inst.card.zh}({inst.card.name})！")


class BronzeOrb(Monster):
    """青铜球（Act 2 automaton 遭遇随从，槽 0/2）：静滞偷牌（每场一次）。

    wiki/C++ A0：HP 52-58（A9 起 54-60——C++ initHp 在 setRandomHp 前
    空耗一次 hp 流，本项目不做轨迹对齐，仅 roll 区间）。MINION（由
    生成处加）。roll 分段（misc_info 记已用 Stasis）：
      未用 Stasis 且 roll ≥ 25 → Stasis（偷 1 张，misc_info 置 1）；
      roll ≥ 70 且 Support Beam 未连续两回合 → Support Beam（给槽 1
      自律机 +12 格挡，立即结算）；
      Beam 未连续两回合 → Beam（8 伤）；否则 Support Beam。
    """

    name = "Bronze Orb"
    zh = "铜球"
    hp_range = (52, 58)
    hp_range_high = (54, 60)
    hp_high_asc = 9

    BEAM = MoveDef("Beam", "光束", "attack", base_damage=8)
    STASIS = MoveDef("Stasis", "静滞", "debuff", intent_text="偷走你的一张牌")
    SUPPORT_BEAM = MoveDef("Support Beam", "支援光束", "defend", intent_text="为青铜自律机提供 12 点格挡")

    def __init__(self, idx: int, hp: int, max_hp: int):
        super().__init__(idx, hp, max_hp, "铜球(Bronze Orb)")
        self.stasis_cards: list = []  # 偷到的卡（引擎 die() 归还弃牌堆）

    @classmethod
    def create(cls, bc: BattleContext, idx: int) -> "BronzeOrb":
        hp = _roll_hp(bc, cls)
        return cls(idx, hp, hp)

    def get_move_for_roll(self, bc: BattleContext, roll: int) -> MoveDef:
        if self.misc_info == 0 and roll >= 25:
            return self.STASIS
        if roll >= 70 and not _last_two(self, "Support Beam"):
            return self.SUPPORT_BEAM
        if not _last_two(self, "Beam"):
            return self.BEAM
        return self.SUPPORT_BEAM

    def take_turn(self, bc: BattleContext) -> None:
        move = self.move_history[0]
        match move.name:
            case "Beam":
                dmg = bc.calculate_monster_damage(self, 8)
                bc.log.append(f"{self.display_name} 使用 光束(Beam)。")
                bc.add_to_bot(Actions.attack_player(self.idx, dmg))
            case "Stasis":
                bc.log.append(f"{self.display_name} 使用 静滞(Stasis)。")
                _stasis_steal(bc, self)
                self.misc_info = 1
            case "Support Beam":
                bc.log.append(f"{self.display_name} 使用 支援光束(Support Beam)。")
                # C++ 硬编码 arr[1]（自律机固定槽位；单怪隔离战斗时跳过）
                if bc.monsters.monster_count > 1:
                    automaton = bc.monsters.monsters[1]
                    if not automaton.is_dead_or_escaped():
                        automaton.block += 12  # C++ addBlock 立即结算
            case _:
                raise AssertionError(f"未知招式 {move}")
        bc.add_to_bot(Actions.roll_move(self.idx))
        self.turns_taken += 1


def _spawn_torch_heads_action() -> Action:
    """补满火把头（对齐 Actions::SpawnTorchHeads）：spawnCount = 3 - 存活数，
    首只落在槽 1（若槽 1 已死）否则槽 0，第二只恒槽 0。火把头 HP 走
    hp 流 roll（A9 起高位区间），意图固定 Tackle（setMove，不 roll）。"""

    def run(bcb: BattleContext) -> None:
        group = bcb.monsters
        spawn_count = 3 - group.alive_count
        if spawn_count <= 0:
            return
        idxs = (1 if group.monsters[1].is_dead_or_escaped() else 0, 0)
        for i in range(spawn_count):
            idx = idxs[i]
            torch = TorchHead.create(bcb, idx)
            group.spawn_replace(bcb, idx, torch)
            torch.set_move(TorchHead.TACKLE)
            bcb.log.append(f"{torch.display_name} 被召唤进场！")

    return Action(run)


class TheCollector(Monster):
    """收藏家（Act 2 Boss，collector 遭遇，槽 2）：主死即胜 + 召唤火把头。

    wiki/C++ A0：HP 282（A9 起 300）。preBattleAction：MINION_LEADER。
    遭遇布局：槽 0/1 死亡占位（Spawn 补满两只火把头）。
    roll 分段（rollMove 每回合走队列；回合数映射 our_turn == C++
    getMonsterTurnNumber()）：
      首回合固定 Spawn；第 3 回合的 roll 恒出 Mega Debuff（即第 4 回合
      执行——wiki"always uses Mega Debuff on turn 4"）；
      存活数 < 3 且上回合非 Spawn 且 roll ≤ 25 → Spawn（补满）；
      roll ≤ 70 且火球未连续两回合 → Fireball（18 伤，A4 起 21）；
      上回合非 Buff → Buff；否则 Fireball。
    Buff：存活火把头（槽 0-1）与自身力量 +3（A4 起 +4、A19 起 +5），
    自身格挡 +15（A9 起 +18、A19 起 +23，立即结算）。
    Mega Debuff：3 层虚弱/易伤/脆弱（A19 起 5 层——本体 TheCollector.java
    megaDebuffAmt 三档 {3,3,5}@A4/A19；lightspeed 恒 3 系漏译，wiki 为准）。
    """

    name = "The Collector"
    zh = "收藏家"
    hp_range = (282, 282)
    hp_range_high = (300, 300)
    hp_high_asc = 9

    SPAWN = MoveDef("Spawn", "召唤", "unknown", intent_text="召唤火把头补满")
    FIREBALL = MoveDef("Fireball", "火球", "attack", base_damage=18)
    BUFF = MoveDef("Buff", "增益", "buff", intent_text="火把头与自身力量 +3，自身格挡 +15")
    MEGA_DEBUFF = MoveDef("Mega Debuff", "超级削弱", "debuff", intent_text="施加 3 层虚弱、易伤与脆弱")

    def __init__(self, idx: int, hp: int, max_hp: int):
        super().__init__(idx, hp, max_hp, "收藏家(The Collector)")
        self.statuses.add(MonsterStatus.MINION_LEADER, 1)

    @classmethod
    def create(cls, bc: BattleContext, idx: int) -> "TheCollector":
        hp = _roll_hp(bc, cls)
        return cls(idx, hp, hp)

    def get_move_for_roll(self, bc: BattleContext, roll: int) -> MoveDef:
        if not self.move_history:
            return self.SPAWN
        if bc.turn == 3:  # getMonsterTurnNumber() == 3 → 第 4 回合的意图
            return self.MEGA_DEBUFF
        can_spawn = bc.monsters.alive_count < 3 and not _last(self, "Spawn")
        if roll <= 25 and can_spawn:
            return self.SPAWN
        if roll <= 70 and not _last_two(self, "Fireball"):
            return self.FIREBALL
        if not _last(self, "Buff"):
            return self.BUFF
        return self.FIREBALL

    def take_turn(self, bc: BattleContext) -> None:
        move = self.move_history[0]
        match move.name:
            case "Spawn":
                bc.log.append(f"{self.display_name} 使用 召唤(Spawn)。")
                bc.add_to_bot(_spawn_torch_heads_action())
            case "Fireball":
                dmg = bc.calculate_monster_damage(self, 21 if bc.ascension >= 4 else 18)
                bc.log.append(f"{self.display_name} 使用 火球(Fireball)。")
                bc.add_to_bot(Actions.attack_player(self.idx, dmg))
            case "Buff":
                str_gain = 5 if bc.ascension >= 19 else 4 if bc.ascension >= 4 else 3
                block_gain = 23 if bc.ascension >= 19 else 18 if bc.ascension >= 9 else 15
                bc.log.append(f"{self.display_name} 使用 增益(Buff)，力量 +{str_gain}、格挡 +{block_gain}。")
                for i in range(min(2, bc.monsters.monster_count)):
                    torch = bc.monsters.monsters[i]
                    if not torch.is_dead_or_escaped():
                        torch.statuses.add(MonsterStatus.STRENGTH, str_gain)
                self.statuses.add(MonsterStatus.STRENGTH, str_gain)
                self.block += block_gain  # C++ addBlock 立即结算
            case "Mega Debuff":
                n = 5 if bc.ascension >= 19 else 3
                bc.log.append(f"{self.display_name} 使用 超级削弱(Mega Debuff)！")
                bc.add_to_bot(Actions.debuff_player(PlayerStatus.WEAK, n, True))
                bc.add_to_bot(Actions.debuff_player(PlayerStatus.VULNERABLE, n, True))
                bc.add_to_bot(Actions.debuff_player(PlayerStatus.FRAIL, n, True))
            case _:
                raise AssertionError(f"未知招式 {move}")
        bc.add_to_bot(Actions.roll_move(self.idx))
        self.turns_taken += 1


class TorchHead(Monster):
    """火把头（Act 2 collector 遭遇随从）：固定冲撞 7 伤。

    wiki/C++ A0：HP 38-40（A9 起 40-45）。MINION（create 时加）。意图
    由 Spawn 动作直接 set_move(Tackle)，从不出 roll；take_turn 也不入队
    RollMove（C++ TORCH_HEAD_TACKLE 分支只有攻击），意图恒为冲撞。
    """

    name = "Torch Head"
    zh = "火炬头"
    hp_range = (38, 40)
    hp_range_high = (40, 45)
    hp_high_asc = 9

    TACKLE = MoveDef("Tackle", "冲撞", "attack", base_damage=7)

    def __init__(self, idx: int, hp: int, max_hp: int):
        super().__init__(idx, hp, max_hp, "火炬头(Torch Head)")
        self.statuses.add(MonsterStatus.MINION, 1)

    @classmethod
    def create(cls, bc: BattleContext, idx: int) -> "TorchHead":
        hp = _roll_hp(bc, cls)
        return cls(idx, hp, hp)

    def get_move_for_roll(self, bc: BattleContext, roll: int) -> MoveDef:
        # C++ TORCH_HEAD 走到 default assert（从不被 roll）；防御性返回固定招
        return self.TACKLE

    def take_turn(self, bc: BattleContext) -> None:
        dmg = bc.calculate_monster_damage(self, 7)
        bc.log.append(f"{self.display_name} 使用 冲撞(Tackle)。")
        bc.add_to_bot(Actions.attack_player(self.idx, dmg))
        # 对齐 C++：无 RollMove / NoOpRollMove 入队，意图保持冲撞
        self.turns_taken += 1


class TheChamp(Monster):
    """勇士（Act 2 Boss）：阶段化状态机（misc 位域存阶段与防御姿态计数）。

    wiki/C++ A0：HP 420（A9 起 440）。misc_info 位域（对齐 C++ monsterData）：
    低 2 位 = 防御姿态已用次数（上限 2）；0x4 = 二阶段标记。
    roll 分段（rollMove 每回合走队列；回合数映射 our_turn == C++
    getMonsterTurnNumber()）：
      二阶段：Execute 未出现在最近两招 → Execute；否则落入通用段；
      一阶段：HP < maxHp//2 → 置二阶段位、出 Anger（移除自身削弱 +
        力量 +6（A4 起 +9、A19 起 +12））；
        (turn+1) % 4 == 0 → Taunt（2 层虚弱 + 2 层易伤，立即结算）；
      通用段：roll ≤ 15（A19 起 30）且上回合非 防御姿态 且已用 < 2 →
        防御姿态（格挡 +15、金属化 +5（A9 起 18/6、A19 起 20/7），
        立即结算），计数 +1；
        roll ≤ 30 且上回合非 嘲讽/防御姿态 → 嘲讽（力量 +2（A4 起 +3、
        A19 起 +4）——本体 Champ.java strAmt 三档 {2,3,4}；lightspeed 误为
        {3,4,5}（bossDiffIdx），wiki 为准）；
        roll ≤ 55 且上回合非 掌掴 → 掌掴（12 伤（A4 起 14）+ 2 脆弱 +
        2 易伤）；上回合非 重斩 → 重斩（16 伤（A4 起 18））；否则 掌掴。
    Execute：10 伤 ×2（无进阶加成）。
    """

    name = "The Champ"
    zh = "第一勇士"
    hp_range = (420, 420)
    hp_range_high = (440, 440)
    hp_high_asc = 9

    HEAVY_SLASH = MoveDef("Heavy Slash", "重斩", "attack", base_damage=16)
    DEFENSIVE_STANCE = MoveDef("Defensive Stance", "防御态势", "defend", intent_text="获得 15 点格挡与 5 层金属化")
    EXECUTE = MoveDef("Execute", "处决", "attack", base_damage=10)  # ×2 段
    FACE_SLAP = MoveDef("Face Slap", "打脸", "attack", base_damage=12)  # 另施加 2 层脆弱与 2 层易伤
    GLOAT = MoveDef("Gloat", "得意", "buff", intent_text="力量 +3")
    TAUNT = MoveDef("Taunt", "嘲讽", "debuff", intent_text="施加 2 层虚弱与 2 层易伤")
    ANGER = MoveDef("Anger", "愤怒", "buff", intent_text="移除自身削弱，力量 +6")

    def __init__(self, idx: int, hp: int, max_hp: int):
        super().__init__(idx, hp, max_hp, "第一勇士(The Champ)")

    @classmethod
    def create(cls, bc: BattleContext, idx: int) -> "TheChamp":
        hp = _roll_hp(bc, cls)
        return cls(idx, hp, hp)

    def get_move_for_roll(self, bc: BattleContext, roll: int) -> MoveDef:
        if self.misc_info & 0x4:  # 二阶段
            if not _last(self, "Execute") and not _last_before(self, "Execute"):
                return self.EXECUTE
        else:
            if self.hp < self.max_hp // 2:
                self.misc_info |= 0x4
                return self.ANGER
            if (bc.turn + 1) % 4 == 0:  # getMonsterTurnNumber()+1 ≡ our_turn+1
                return self.TAUNT
        # 通用段（一阶段常规 / 二阶段 Execute 刚用过的间隙）
        defensive_uses = self.misc_info & 0x3
        threshold = 30 if bc.ascension >= 19 else 15
        if roll <= threshold and not _last(self, "Defensive Stance") and defensive_uses < 2:
            self.misc_info += 1
            return self.DEFENSIVE_STANCE
        if roll <= 30 and not _last(self, "Gloat") and not _last(self, "Defensive Stance"):
            return self.GLOAT
        if roll <= 55 and not _last(self, "Face Slap"):
            return self.FACE_SLAP
        if not _last(self, "Heavy Slash"):
            return self.HEAVY_SLASH
        return self.FACE_SLAP

    def take_turn(self, bc: BattleContext) -> None:
        move = self.move_history[0]
        match move.name:
            case "Heavy Slash":
                dmg = bc.calculate_monster_damage(self, 18 if bc.ascension >= 4 else 16)
                bc.log.append(f"{self.display_name} 使用 重斩(Heavy Slash)。")
                bc.add_to_bot(Actions.attack_player(self.idx, dmg))
            case "Defensive Stance":
                block_amt = 20 if bc.ascension >= 19 else 18 if bc.ascension >= 9 else 15
                metal = 7 if bc.ascension >= 19 else 6 if bc.ascension >= 9 else 5
                self.block += block_amt  # C++ addBlock 立即结算
                self.statuses.add(MonsterStatus.METALLICIZE, metal)
                bc.log.append(f"{self.display_name} 使用 防御态势(Defensive Stance)，格挡 +{block_amt}、金属化 +{metal}。")
            case "Execute":
                dmg = bc.calculate_monster_damage(self, 10)
                bc.log.append(f"{self.display_name} 使用 处决(Execute)，{dmg} 点伤害 ×2！")
                for _ in range(2):
                    bc.add_to_bot(Actions.attack_player(self.idx, dmg))
            case "Face Slap":
                dmg = bc.calculate_monster_damage(self, 14 if bc.ascension >= 4 else 12)
                bc.log.append(f"{self.display_name} 使用 打脸(Face Slap)。")
                bc.add_to_bot(Actions.attack_player(self.idx, dmg))
                bc.add_to_bot(Actions.debuff_player(PlayerStatus.FRAIL, 2, True))
                bc.add_to_bot(Actions.debuff_player(PlayerStatus.VULNERABLE, 2, True))
            case "Gloat":
                # 本体 Champ.java：strAmt 三档 {2,3,4}@A4/A19（Anger 用其 ×3）；
                # lightspeed 误译为 {3,4,5}，wiki 为准
                amt = 4 if bc.ascension >= 19 else 3 if bc.ascension >= 4 else 2
                self.statuses.add(MonsterStatus.STRENGTH, amt)
                bc.log.append(f"{self.display_name} 使用 得意(Gloat)，力量 +{amt}。")
            case "Taunt":
                bc.log.append(f"{self.display_name} 使用 嘲讽(Taunt)。")
                # 对齐 C++ bc.player.debuff：立即结算，不入队
                Actions.debuff_player(PlayerStatus.WEAK, 2, True).fn(bc)
                Actions.debuff_player(PlayerStatus.VULNERABLE, 2, True).fn(bc)
            case "Anger":
                # 对齐 C++ removeDebuffs + 力量增益
                if self.statuses.get(MonsterStatus.STRENGTH) < 0:
                    self.statuses.set(MonsterStatus.STRENGTH, 0)
                for s in (MonsterStatus.VULNERABLE, MonsterStatus.WEAK,
                          MonsterStatus.POISON, MonsterStatus.SHACKLED, MonsterStatus.LOCK_ON):
                    self.statuses.remove(s)
                amt = 12 if bc.ascension >= 19 else 9 if bc.ascension >= 4 else 6
                self.statuses.add(MonsterStatus.STRENGTH, amt)
                bc.log.append(f"{self.display_name} 使用 愤怒(Anger)，移除自身削弱，力量 +{amt}！")
            case _:
                raise AssertionError(f"未知招式 {move}")
        bc.add_to_bot(Actions.roll_move(self.idx))
        self.turns_taken += 1


# ====================================================================
# 批次 D：Act 3 全部新怪物（17 种）+ Act 4 怪物（3 种）。数值/分段逐行
# 对齐 MonsterSpecific.cpp / MonsterGroup.cpp，wiki 交叉校验（差异见
# 模块头注释与各类 docstring）。
# ====================================================================


def _remove_debuffs(m: Monster) -> None:
    """移除怪物全部 debuff（对齐 Monster.cpp:538-552 removeDebuffs）：
    负力量归零 + BLOCK_RETURN/CHOKED/CORPSE_EXPLOSION/LOCK_ON/MARK/
    POISON/SHACKLED/VULNERABLE/WEAK。"""
    if m.statuses.get(MonsterStatus.STRENGTH) < 0:
        m.statuses.set(MonsterStatus.STRENGTH, 0)
    for s in (MonsterStatus.BLOCK_RETURN, MonsterStatus.CHOKED,
              MonsterStatus.CORPSE_EXPLOSION, MonsterStatus.LOCK_ON,
              MonsterStatus.MARK, MonsterStatus.POISON,
              MonsterStatus.SHACKLED, MonsterStatus.VULNERABLE,
              MonsterStatus.WEAK):
        m.statuses.remove(s)


class _ZeroBasedStatuses(Statuses):
    """0 层起点的常驻状态（对齐 C++ setHasStatus(true)+setStatus(0)）。

    引擎 Statuses.has 以层数>0 判定：TIME_WARP/SLOW 初始 0 层会被
    use_card 的计数钩子漏掉（Time Eater 第 1 张牌、Giant Head 首张牌
    加成），且触发后 set(...,0) 会让计数永远停摆。此子类让指定状态
    恒视为"已挂"，计数/清零仍由引擎按 get/set 语义照常进行——
    Time Eater 恰在第 12 张牌触发并循环、Giant Head 每张牌 +10%。
    """

    def __init__(self, always_present) -> None:
        super().__init__()
        self._always_present = frozenset(always_present)

    def has(self, s) -> bool:
        if s in self._always_present:
            return True
        return super().has(s)


class _HalfDeadMonsterGroup(MonsterGroup):
    """half_dead 怪也参与回合（对齐 MonsterGroup.cpp:571-589 doMonsterTurn
    的 `!isDeadOrEscaped() || isHalfDead()`）——Darkling/Awakened One 的
    假死体在自己回合执行 Regrow→Reincarnate / Rebirth。由遭遇装配方
    （encounters）安装到 bc.monsters。"""

    def do_monster_turn(self, bc: BattleContext) -> None:
        m = self.monsters[bc.monster_turn_idx]
        if (not m.is_dead_or_escaped()) or m.half_dead:
            m.take_turn(bc)
        bc.monster_turn_idx += 1


def _suicide_by_damage(idx: int) -> Action:
    """自爆（对齐 Actions::SuicideAction(idx, true)：对自身施加全额
    非攻击伤害，正常走 die() 结算——Exploder/Dagger 的 EXPLODE）。"""

    def run(bcb: BattleContext) -> None:
        m = bcb.monsters.monsters[idx]
        if not m.is_dead_or_escaped():
            m.damage(bcb, m.hp)

    return Action(run)


_HORDE_PLACEHOLDER = MoveDef(
    "Horde Placeholder", "占位", "unknown",
    intent_text="（Jaw Worm Horde 占位意图：跳过首回合特例，MonsterGroup.cpp:285-288）")


# ---- Act 3 普通怪 ----


class Darkling(Monster):
    """暗裔幼体（Act 3，三只出没）：REGROW 假死复活链。

    wiki/C++ A0：HP 48-56（A7 起 50-59）。构造期 roll：Nip 伤害 7-11
    （A2 起 9-13，misc_info 存值，死后复活保留）。preBattle：REGROW。
    出招（对齐 C++ DARKLING）：
      首回合 50/50：硬化（+12 格挡，A17 起另 +2 力量）/ 啃咬；
      假死中：Regrow（空转一回合）→ 下回合 Reincarnate（复活）；
      roll < 40：非上回合 Chomp 且 idx≠1（中位永不 Chomp）→ Chomp
      （8/9 伤 ×2——本体 Darkling.java 每个 Chomp 入队两次 DamageAction；
      lightspeed 单发，wiki 记 ×2，按本体修正），否则重抽 40-99；
      roll < 70：上回合非硬化 → 硬化，否则啃咬；
      啃咬未连续两回合 → 啃咬，否则整段重抽。
    死亡（die 覆盖，对齐 Monster.cpp:283-325）：存活数先 -1，归零即
    判胜（最后一只死不复活，全灭=胜利）；否则清空全部状态（含
    REGROW——Reincarnate 时重挂，可无限循环）、置意图 Regrow、
    half_dead 假死。复活：hp = maxHp//2、存活数 +1、重挂 REGROW
    （哲学之石 +1 力量走 on_monster_spawned 钩子）。
    """

    name = "Darkling"
    zh = "小黑"
    hp_range = (48, 56)
    hp_range_high = (50, 59)

    CHOMP = MoveDef("Chomp", "撕咬", "attack", base_damage=8)  # ×2 段（本体 Darkling.java 两次 DamageAction）
    HARDEN = MoveDef("Harden", "硬化", "defend", intent_text="获得 12 点格挡")
    NIP = MoveDef("Nip", "啃咬", "attack", base_damage=9)  # 基础值逐实例 roll，见 __init__
    REGROW = MoveDef("Regrow", "重生蓄力", "unknown", intent_text="（假死蓄力，下回合复活）")
    REINCARNATE = MoveDef("Reincarnate", "转生", "buff", intent_text="以 50% 最大生命复活")

    def __init__(self, idx: int, hp: int, max_hp: int, nip_dmg: int):
        super().__init__(idx, hp, max_hp, "小黑(Darkling)")
        self.misc_info = nip_dmg  # 对齐 C++ construct：Nip 伤害挂 miscInfo
        self.NIP = MoveDef("Nip", "啃咬", "attack", base_damage=nip_dmg)

    @classmethod
    def create(cls, bc: BattleContext, idx: int) -> "Darkling":
        hp = _roll_hp(bc, cls)
        nip = bc.rngs.monster_hp.int_inclusive(9, 13) if bc.ascension >= 2 \
            else bc.rngs.monster_hp.int_inclusive(7, 11)
        m = cls(idx, hp, hp, nip)
        m.statuses.add(MonsterStatus.REGROW, 1)
        return m

    def die(self, bc: BattleContext) -> None:
        # 对齐 C++ die()：先扣存活数；REGROW 分支后于全灭判胜——最后
        # 一只死亡直接判胜不复活。覆盖引擎通用 REGROW 分支（满血复活
        # 且不扣存活数，语义与 C++ 不符，见模块头注释）。
        if self.half_dead:
            return
        self.is_dying = True
        group = bc.monsters
        group.alive_count -= 1
        if group.alive_count <= 0:
            bc.outcome = Outcome.PLAYER_VICTORY
            bc.check_combat()
            return
        if self.statuses.has(MonsterStatus.REGROW):
            # resetAllStatusEffects（Monster.cpp:554-558）：清空全部状态
            #（含 REGROW 与力量）与格挡；Reincarnate 时重挂 REGROW
            self.statuses = Statuses()
            self.block = 0
            self.set_move(self.REGROW)
            self.half_dead = True
        # C++ 继续走 GREMLIN_HORN/THE_SPECIMEN 遗物死亡触发（REGROW
        # 分支不 return）——孢子云已被清空、毒已清空，按引擎钩子保留
        bc.relics.on_monster_death(bc, self)
        bc.check_combat()

    def get_move_for_roll(self, bc: BattleContext, roll: int) -> MoveDef:
        if not self.move_history:  # firstTurn：50/50 硬化/啃咬
            return self.HARDEN if roll < 50 else self.NIP
        if self.half_dead:
            return self.REINCARNATE
        my_roll = roll
        if my_roll < 40:
            # 中位（idx 1）永不 Chomp（C++ `idx != 1`）
            if not _last(self, "Chomp") and self.idx != 1:
                return self.CHOMP
            my_roll = bc.rngs.ai.int_inclusive(40, 99)
        if my_roll < 70:
            return self.HARDEN if not _last(self, "Harden") else self.NIP
        if not _last_two(self, "Nip"):
            return self.NIP
        # 对齐 C++：整段递归重抽
        return self.get_move_for_roll(bc, bc.rngs.ai.int_inclusive(0, 99))

    def take_turn(self, bc: BattleContext) -> None:
        move = self.move_history[0]
        match move.name:
            case "Chomp":
                # 本体 Darkling.java：Chomp 入队两次 DamageAction（wiki"8×2 伤"）
                dmg = bc.calculate_monster_damage(self, 9 if bc.ascension >= 2 else 8)
                bc.log.append(f"{self.display_name} 使用 撕咬(Chomp)，{dmg} 点伤害 ×2。")
                for _ in range(2):
                    bc.add_to_bot(Actions.attack_player(self.idx, dmg))
                bc.add_to_bot(Actions.roll_move(self.idx))
            case "Harden":
                self.block += 12  # 对齐 C++ addBlock：立即结算
                if bc.ascension >= 17:
                    self.statuses.add(MonsterStatus.STRENGTH, 2)
                bc.log.append(f"{self.display_name} 使用 硬化(Harden)，获得 12 点格挡。")
                self.roll_move(bc)
            case "Nip":
                # C++ `miscInfo + (asc2 ? 2 : 0)` 为双重 A2 加成（construct
                # 已按 A2 roll 9-13），按 wiki/本体 9-13，不加 +2（模块头注释）
                dmg = bc.calculate_monster_damage(self, self.misc_info)
                bc.log.append(f"{self.display_name} 使用 啃咬(Nip)。")
                bc.add_to_bot(Actions.attack_player(self.idx, dmg))
                bc.add_to_bot(Actions.roll_move(self.idx))
            case "Regrow":
                # 假死空转一回合（对齐 C++ "do nothing; rollMove"）
                bc.log.append(f"{self.display_name} 正在蓄力重生……")
                self.roll_move(bc)
            case "Reincarnate":
                # 对齐 C++：curHp = maxHp/2、清假死、存活数 +1、重挂 REGROW
                self.hp = self.max_hp // 2
                self.half_dead = False
                self.is_dying = False
                bc.monsters.alive_count += 1
                self.statuses.add(MonsterStatus.REGROW, 1)
                bc.relics.on_monster_spawned(bc, self)  # 哲学之石 +1 力量
                bc.log.append(f"{self.display_name} 转生(Reincarnate)了！")
                self.roll_move(bc)
            case _:
                raise AssertionError(f"未知招式 {move}")
        self.turns_taken += 1


class OrbWalker(Monster):
    """奥术行走者（Act 3 普通怪）：激光 / 爪击。

    wiki/C++ A0：HP 90-96（A7 起 92-102）。preBattle：GENERIC_STRENGTH_UP
    3（A17 起 5）——每回合末 +层 力量（引擎 apply_end_of_round_powers）。
    roll 分段：roll < 40：爪击未连续两回合 → 爪击（15 伤，A2 起 16），
    否则激光；roll ≥ 40：激光未连续两回合 → 激光（10 伤，A2 起 11，
    另洗 1 张灼伤进抽牌堆 + 塞 1 张灼伤进弃牌堆），否则爪击。
    """

    name = "Orb Walker"
    zh = "圆球行者"
    hp_range = (90, 96)
    hp_range_high = (92, 102)
    hp_high_asc = 7

    LASER = MoveDef("Laser", "激光", "attack", base_damage=10)  # 另塞/洗灼伤
    CLAW = MoveDef("Claw", "爪击", "attack", base_damage=15)

    def __init__(self, idx: int, hp: int, max_hp: int):
        super().__init__(idx, hp, max_hp, "圆球行者(Orb Walker)")

    @classmethod
    def create(cls, bc: BattleContext, idx: int) -> "OrbWalker":
        hp = _roll_hp(bc, cls)
        m = cls(idx, hp, hp)
        m.statuses.add(MonsterStatus.GENERIC_STRENGTH_UP, 5 if bc.ascension >= 17 else 3)
        return m

    def get_move_for_roll(self, bc: BattleContext, roll: int) -> MoveDef:
        if roll < 40:
            return self.CLAW if not _last_two(self, "Claw") else self.LASER
        return self.LASER if not _last_two(self, "Laser") else self.CLAW

    def take_turn(self, bc: BattleContext) -> None:
        move = self.move_history[0]
        match move.name:
            case "Laser":
                dmg = bc.calculate_monster_damage(self, 11 if bc.ascension >= 2 else 10)
                bc.log.append(f"{self.display_name} 使用 激光(Laser)。")
                bc.add_to_bot(Actions.attack_player(self.idx, dmg))
                # ShuffleTempCardIntoDrawPile(BURN,1) + MakeTempCardInDiscard(BURN)
                bc.add_to_bot(Actions.make_temp_card_in_draw_pile(BURN, False, True))
                bc.add_to_bot(Actions.make_temp_card_in_discard(BURN))
                bc.add_to_bot(Actions.roll_move(self.idx))
            case "Claw":
                dmg = bc.calculate_monster_damage(self, 16 if bc.ascension >= 2 else 15)
                bc.log.append(f"{self.display_name} 使用 爪击(Claw)。")
                bc.add_to_bot(Actions.attack_player(self.idx, dmg))
                bc.add_to_bot(Actions.roll_move(self.idx))
            case _:
                raise AssertionError(f"未知招式 {move}")
        self.turns_taken += 1


class Repulsor(Monster):
    """排斥者（Act 3 普通怪，shapes 遭遇成员）：猛击 / 排斥。

    wiki/C++ A0：HP 29-35（A7 起 31-38）。roll 分段：roll < 20 且上回合
    非猛击 → 猛击（11 伤，A2 起 13）；否则排斥（洗 2 张眩晕进抽牌堆，
    立即结算）。
    """

    name = "Repulsor"
    zh = "反冲机"
    hp_range = (29, 35)
    hp_range_high = (31, 38)

    BASH = MoveDef("Bash", "猛击", "attack", base_damage=11)
    REPULSE = MoveDef("Repulse", "排斥", "debuff", intent_text="洗 2 张眩晕进抽牌堆")

    def __init__(self, idx: int, hp: int, max_hp: int):
        super().__init__(idx, hp, max_hp, "反冲机(Repulsor)")

    @classmethod
    def create(cls, bc: BattleContext, idx: int) -> "Repulsor":
        hp = _roll_hp(bc, cls)
        return cls(idx, hp, hp)

    def get_move_for_roll(self, bc: BattleContext, roll: int) -> MoveDef:
        if roll < 20 and not _last(self, "Bash"):
            return self.BASH
        return self.REPULSE

    def take_turn(self, bc: BattleContext) -> None:
        move = self.move_history[0]
        match move.name:
            case "Bash":
                dmg = bc.calculate_monster_damage(self, 13 if bc.ascension >= 2 else 11)
                bc.log.append(f"{self.display_name} 使用 猛击(Bash)。")
                bc.add_to_bot(Actions.attack_player(self.idx, dmg))
                bc.add_to_bot(Actions.roll_move(self.idx))
            case "Repulse":
                bc.log.append(f"{self.display_name} 使用 排斥(Repulse)，洗 2 张眩晕进抽牌堆。")
                # 对齐 C++ actFunc：立即结算；rollMove 直调
                for _ in range(2):
                    Actions.make_temp_card_in_draw_pile(DAZED, False, True).fn(bc)
                self.roll_move(bc)
            case _:
                raise AssertionError(f"未知招式 {move}")
        self.turns_taken += 1


class Exploder(Monster):
    """爆爆虫（Act 3 普通怪，shapes 遭遇成员）：重击两次后自爆。

    wiki/C++ A0：HP 30（A7 起 30-35）。出招恒重击（rollMove 仅首回合），
    重击连续两回合后切自爆。重击 9 伤（A2 起 11）；自爆：30 点非攻击
    HP 损失（吃玩家格挡）后对自身全额伤害自杀（走 die() 结算）。
    """

    name = "Exploder"
    zh = "爆炸机"
    hp_range = (30, 30)
    hp_range_high = (30, 35)
    hp_high_asc = 7

    SLAM = MoveDef("Slam", "重击", "attack", base_damage=9)
    EXPLODE = MoveDef("Explode", "自爆", "attack", base_damage=30)  # 非攻击 HP 损失

    def __init__(self, idx: int, hp: int, max_hp: int):
        super().__init__(idx, hp, max_hp, "爆炸机(Exploder)")

    @classmethod
    def create(cls, bc: BattleContext, idx: int) -> "Exploder":
        hp = _roll_hp(bc, cls)
        return cls(idx, hp, hp)

    def get_move_for_roll(self, bc: BattleContext, roll: int) -> MoveDef:
        return self.SLAM

    def take_turn(self, bc: BattleContext) -> None:
        move = self.move_history[0]
        match move.name:
            case "Slam":
                dmg = bc.calculate_monster_damage(self, 11 if bc.ascension >= 2 else 9)
                bc.log.append(f"{self.display_name} 使用 重击(Slam)。")
                bc.add_to_bot(Actions.attack_player(self.idx, dmg))
                # lastTwoMoves(SLAM)（当前 + 上回合均为重击）→ 自爆
                self.set_move(self.EXPLODE if _last_two(self, "Slam") else self.SLAM)
                bc.add_to_bot(Actions.no_op_roll_move())
            case "Explode":
                bc.log.append(f"{self.display_name} 自爆(Explode)了！")
                bc.add_to_bot(Actions.damage_player(30))
                bc.add_to_bot(_suicide_by_damage(self.idx))
                bc.add_to_bot(Actions.no_op_roll_move())
            case _:
                raise AssertionError(f"未知招式 {move}")
        self.turns_taken += 1


class Spiker(Monster):
    """尖刺体（Act 3 普通怪，shapes 遭遇成员）：荆棘反伤 + 切割/尖刺。

    wiki/C++ A0：HP 42-56（A7 起 44-60）。preBattle：THORNS 3（A2 起 4、
    A17 起 7）。roll 分段：misc（尖刺使用次数）> 5 或（roll < 50 且上回
    合非切割）→ 切割（7 伤，A2 起 9）；否则尖刺（THORNS +2，计数 +1）。
    荆棘反伤（引擎 _apply_damage 无 THORNS 分支，attacked 覆盖补）：
    受到未被格挡吸收的攻击伤害时，按层数对玩家反弹非攻击 HP 损失
    （addToTop，致命一击也反伤，对齐 Monster.cpp:385-386）。
    """

    name = "Spiker"
    zh = "钉刺机"
    hp_range = (42, 56)
    hp_range_high = (44, 60)

    CUT = MoveDef("Cut", "切割", "attack", base_damage=7)
    SPIKE = MoveDef("Spike", "尖刺", "buff", intent_text="荆棘 +2")

    def __init__(self, idx: int, hp: int, max_hp: int):
        super().__init__(idx, hp, max_hp, "钉刺机(Spiker)")

    @classmethod
    def create(cls, bc: BattleContext, idx: int) -> "Spiker":
        hp = _roll_hp(bc, cls)
        m = cls(idx, hp, hp)
        thorns = 7 if bc.ascension >= 17 else 4 if bc.ascension >= 2 else 3
        m.statuses.add(MonsterStatus.THORNS, thorns)
        return m

    def attacked(self, bc: BattleContext, damage: int) -> None:
        # 覆盖：基类无 THORNS 反伤分支。以 HP 实际损失量判定"未被格挡
        # 吸收"（致命一击同样反伤，反伤先于死亡结算后入队 top）。
        hp_before = self.hp
        super().attacked(bc, damage)
        taken = hp_before - self.hp
        if taken > 0 and self.statuses.has(MonsterStatus.THORNS):
            bc.add_to_top(Actions.damage_player(self.statuses.get(MonsterStatus.THORNS)))

    def get_move_for_roll(self, bc: BattleContext, roll: int) -> MoveDef:
        if self.misc_info > 5 or (roll < 50 and not _last(self, "Cut")):
            return self.CUT
        return self.SPIKE

    def take_turn(self, bc: BattleContext) -> None:
        move = self.move_history[0]
        match move.name:
            case "Cut":
                dmg = bc.calculate_monster_damage(self, 9 if bc.ascension >= 2 else 7)
                bc.log.append(f"{self.display_name} 使用 切割(Cut)。")
                bc.add_to_bot(Actions.attack_player(self.idx, dmg))
                bc.add_to_bot(Actions.roll_move(self.idx))
            case "Spike":
                self.misc_info += 1  # 尖刺使用计数（对齐 C++ ++miscInfo）
                self.statuses.add(MonsterStatus.THORNS, 2)
                bc.log.append(f"{self.display_name} 使用 尖刺(Spike)，荆棘 +2。")
                self.roll_move(bc)
            case _:
                raise AssertionError(f"未知招式 {move}")
        self.turns_taken += 1


class SpireGrowth(Monster):
    """尖塔生长体（Act 3 普通怪）：快击 / 粉碎 / 紧勒。

    wiki/C++ A0：HP 170（A7 起 190）。roll 分段：
      玩家无 CONSTRICTED 且上回合非紧勒且（A17 或 roll ≥ 50）→ 紧勒
      （CONSTRICTED 10 层，A17 起 12）；
      roll < 50 且快击未连续两回合 → 快击（16 伤，A2 起 18）；
      粉碎未连续两回合 → 粉碎（22 伤，A2 起 25）；否则快击。
    CONSTRICTED（被紧勒：玩家回合末受等同层数的非攻击 HP 损失）引擎
    无 PlayerStatus 枚举与结算——以 player.special["constricted"] 计数、
    本怪 apply_start_of_turn_powers（怪物回合开始、先于怪物攻击，与
    本体"玩家回合末"相对玩家同一时位）结算掉血近似；怪死后不再结算
    （本体为常驻 debuff），见模块头注释。
    """

    name = "Spire Growth"
    zh = "塔内增生组织"
    hp_range = (170, 170)
    hp_range_high = (190, 190)

    QUICK_TACKLE = MoveDef("Quick Tackle", "快击", "attack", base_damage=16)
    SMASH = MoveDef("Smash", "粉碎", "attack", base_damage=22)
    CONSTRICT = MoveDef("Constrict", "紧勒", "debuff", intent_text="施加 10 层紧勒（回合末掉血）")

    def __init__(self, idx: int, hp: int, max_hp: int):
        super().__init__(idx, hp, max_hp, "塔内增生组织(Spire Growth)")

    @classmethod
    def create(cls, bc: BattleContext, idx: int) -> "SpireGrowth":
        hp = _roll_hp(bc, cls)
        return cls(idx, hp, hp)

    def apply_start_of_turn_powers(self, bc: BattleContext) -> None:
        super().apply_start_of_turn_powers(bc)
        # CONSTRICTED 结算（近似，见类注释）：怪物回合开始掉血
        n = bc.player.special.get("constricted", 0)
        if n > 0:
            bc.add_to_bot(Actions.damage_player(n))

    def get_move_for_roll(self, bc: BattleContext, roll: int) -> MoveDef:
        use_constrict = (
            bc.player.special.get("constricted", 0) <= 0
            and not _last(self, "Constrict")
            and (bc.ascension >= 17 or roll >= 50)
        )
        if use_constrict:
            return self.CONSTRICT
        if roll < 50 and not _last_two(self, "Quick Tackle"):
            return self.QUICK_TACKLE
        return self.SMASH if not _last_two(self, "Smash") else self.QUICK_TACKLE

    def take_turn(self, bc: BattleContext) -> None:
        move = self.move_history[0]
        match move.name:
            case "Quick Tackle":
                dmg = bc.calculate_monster_damage(self, 18 if bc.ascension >= 2 else 16)
                bc.log.append(f"{self.display_name} 使用 快击(Quick Tackle)。")
                bc.add_to_bot(Actions.attack_player(self.idx, dmg))
                bc.add_to_bot(Actions.roll_move(self.idx))
            case "Smash":
                dmg = bc.calculate_monster_damage(self, 25 if bc.ascension >= 2 else 22)
                bc.log.append(f"{self.display_name} 使用 粉碎(Smash)。")
                bc.add_to_bot(Actions.attack_player(self.idx, dmg))
                bc.add_to_bot(Actions.roll_move(self.idx))
            case "Constrict":
                n = 12 if bc.ascension >= 17 else 10
                # 对齐 C++ bc.player.debuff<CONSTRICTED>(n)：立即结算；
                # 引擎无枚举 → special 计数（可叠加，本体 debuff 同叠层）
                bc.player.special["constricted"] = bc.player.special.get("constricted", 0) + n
                bc.log.append(f"{self.display_name} 使用 紧勒(Constrict)，被紧勒 {n} 层！")
                bc.add_to_bot(Actions.roll_move(self.idx))
            case _:
                raise AssertionError(f"未知招式 {move}")
        self.turns_taken += 1


class Transient(Monster):
    """瞬变体（Act 3 普通怪）：SHIFTING + FADING，伤害逐回合递增后逃跑。

    wiki/C++ A0：HP 恒 999（initHp 特例，不抽样、无进阶）。preBattle：
    SHIFTING（受击 -全额伤害 力量并挂 SHACKLED 回合末回补，引擎
    _apply_damage）+ FADING 5（A17 起 6；引擎 apply_end_of_round_powers
    倒数，归零逃跑——第 5/6 次攻击后离场）。出招恒攻击：
    伤害 = 30（A2 起 40）+ 10×(回合-1)；受击降力量使其后续攻击变弱。
    """

    name = "Transient"
    zh = "倏忽魔"
    hp_range = (999, 999)

    ATTACK = MoveDef("Attack", "攻击", "attack", base_damage=30)

    def __init__(self, idx: int, hp: int, max_hp: int):
        super().__init__(idx, hp, max_hp, "倏忽魔(Transient)")

    @classmethod
    def create(cls, bc: BattleContext, idx: int) -> "Transient":
        # C++ initHp 特例：curHp = 区间下界（恒 999）
        m = cls(idx, 999, 999)
        m.statuses.add(MonsterStatus.SHIFTING, 1)
        m.statuses.add(MonsterStatus.FADING, 6 if bc.ascension >= 17 else 5)
        return m

    def get_move_for_roll(self, bc: BattleContext, roll: int) -> MoveDef:
        return self.ATTACK

    def take_turn(self, bc: BattleContext) -> None:
        # 伤害 = (asc2?40:30) + 10×(getMonsterTurnNumber()-1)；bc.turn 与
        # C++ getMonsterTurnNumber() 同为 1 基。FADING 倒数/离场由引擎
        # apply_end_of_round_powers 处理（C++ 在本分支内 decrement +
        # FADING==1 时 suicideAction，时机等价，不入队）
        dmg = bc.calculate_monster_damage(
            self, (40 if bc.ascension >= 2 else 30) + 10 * (bc.turn - 1))
        bc.log.append(f"{self.display_name} 使用 攻击(Attack)。")
        bc.add_to_bot(Actions.attack_player(self.idx, dmg))
        bc.add_to_bot(Actions.no_op_roll_move())
        self.turns_taken += 1


class TheMaw(Monster):
    """巨口（Act 3 普通怪，单怪遭遇）：咆哮开局，吞噬段数随回合增长。

    wiki/C++ A0：HP 恒 300（initHp 特例，无进阶变化）。首回合固定咆哮
    （3 层虚弱 + 3 层脆弱，A17 起 5/5，立即结算）。此后 roll：
      roll < 50 且上回合非吞噬 → 吞噬（5 伤 ×(回合+1)//2 段）；
      上回合非粉碎 → 粉碎（25 伤，A2 起 30）；否则流涎（力量 +3，
      A17 起 +5）。吞噬后下回合固定流涎（setMove 链）。
    """

    name = "The Maw"
    zh = "巨口"
    hp_range = (300, 300)

    DROOL = MoveDef("Drool", "流涎", "buff", intent_text="力量 +3")
    NOM = MoveDef("Nom Nom", "吞噬", "attack", base_damage=5)  # ×(回合+1)//2 段
    ROAR = MoveDef("Roar", "咆哮", "debuff", intent_text="施加 3 层虚弱与 3 层脆弱")
    SLAM = MoveDef("Slam", "粉碎", "attack", base_damage=25)

    def __init__(self, idx: int, hp: int, max_hp: int):
        super().__init__(idx, hp, max_hp, "巨口(The Maw)")

    @classmethod
    def create(cls, bc: BattleContext, idx: int) -> "TheMaw":
        # C++ initHp 特例：curHp = 区间下界（恒 300）
        return cls(idx, 300, 300)

    def get_move_for_roll(self, bc: BattleContext, roll: int) -> MoveDef:
        if not self.move_history:  # firstTurn：固定咆哮
            return self.ROAR
        if roll < 50 and not _last(self, "Nom Nom"):
            return self.NOM
        return self.SLAM if not _last(self, "Slam") else self.DROOL

    def take_turn(self, bc: BattleContext) -> None:
        move = self.move_history[0]
        match move.name:
            case "Drool":
                self.statuses.add(MonsterStatus.STRENGTH, 5 if bc.ascension >= 17 else 3)
                bc.log.append(f"{self.display_name} 使用 流涎(Drool)，力量提升。")
                self.roll_move(bc)
            case "Nom Nom":
                # 段数 = (getMonsterTurnNumber()+1)/2 = (bc.turn+1)//2
                hits = (bc.turn + 1) // 2
                dmg = bc.calculate_monster_damage(self, 5)
                bc.log.append(f"{self.display_name} 使用 吞噬(Nom Nom)，{dmg} 点伤害 ×{hits}！")
                for _ in range(hits):
                    bc.add_to_bot(Actions.attack_player(self.idx, dmg))
                self.set_move(self.DROOL)
                bc.add_to_bot(Actions.no_op_roll_move())
            case "Roar":
                n = 5 if bc.ascension >= 17 else 3
                bc.log.append(f"{self.display_name} 使用 咆哮(Roar)，施加 {n} 层虚弱与 {n} 层脆弱！")
                # 对齐 C++ bc.player.debuff：立即结算
                Actions.debuff_player(PlayerStatus.WEAK, n, True).fn(bc)
                Actions.debuff_player(PlayerStatus.FRAIL, n, True).fn(bc)
                self.roll_move(bc)
            case "Slam":
                dmg = bc.calculate_monster_damage(self, 30 if bc.ascension >= 2 else 25)
                bc.log.append(f"{self.display_name} 使用 粉碎(Slam)。")
                bc.add_to_bot(Actions.attack_player(self.idx, dmg))
                bc.add_to_bot(Actions.roll_move(self.idx))
            case _:
                raise AssertionError(f"未知招式 {move}")
        self.turns_taken += 1


class WrithingMass(Monster):
    """扭结团块（Act 3 普通怪，单怪遭遇）：应激（受击重掷）+ 可塑 3。

    wiki/C++ A0：HP 160（A7 起 175）。preBattle：REACTIVE（首次受未被
    格挡攻击重掷意图——引擎 attacked() 每击都重掷，此处覆盖对齐 C++
    仅首次）+ MALLEABLE 3（受击得层格挡且层+1，回合末回满 3——
    覆盖 apply_end_of_turn_triggers，同 Snake Plant）。
    首回合 roll < 33 多重打击（7×3，A2 起 9×3）/ < 66 连枷（15 伤 +
    16 格挡，A2 起 16/18）/ 否则枯萎（10 伤 + 2 虚弱 + 2 易伤，A2 起
    12）。此后 while 循环分段（逐行对齐 C++ WRITHING_MASS）：
      < 10：上回合非强力攻击 → 强力攻击（32，A2 起 38），否则重抽 10-99；
      < 20：未用过植入且上回合非植入 → 植入（一次性标记）；否则 10%
      强力攻击；不中则重抽 20-99；
      < 40：上回合非枯萎 → 枯萎；否则 40% 内层再抽 0-19（<10 强力
      攻击，否则植入/10% 强力/重抽），未中重抽 40-99；
      < 70：上回合非多重打击 → 多重打击；否则 30% 连枷，不中重抽 0-39；
      否则上回合非连枷 → 连枷；否则枯萎。
    植入不塞 2 张 Parasite（内容层无此诅咒卡；C++ 的 OMAMORI/
    DARKSTONE_PERIAPT 分支为残码，不移植——见模块头注释）。
    """

    name = "Writhing Mass"
    zh = "扭曲团块"
    hp_range = (160, 160)
    hp_range_high = (175, 175)

    FLAIL = MoveDef("Flail", "连枷", "attack", base_damage=15)  # 另获等同基础伤害的格挡（15/16@A2）
    IMPLANT = MoveDef("Implant", "植入", "debuff", intent_text="（一次性；本体另塞 2 张寄生物，未移植）")
    MULTI_STRIKE = MoveDef("Multi Strike", "多重打击", "attack", base_damage=7)  # ×3 段
    STRONG_STRIKE = MoveDef("Strong Strike", "强力攻击", "attack", base_damage=32)
    WITHER = MoveDef("Wither", "枯萎", "attack", base_damage=10)  # 另施加 2 虚弱与 2 易伤

    def __init__(self, idx: int, hp: int, max_hp: int):
        super().__init__(idx, hp, max_hp, "扭曲团块(Writhing Mass)")

    @classmethod
    def create(cls, bc: BattleContext, idx: int) -> "WrithingMass":
        hp = _roll_hp(bc, cls)
        m = cls(idx, hp, hp)
        # REACTIVE 初始 1：引擎 has() 需 >0；attacked 覆盖按"首次（值 1）
        # 重掷、此后只计数"对齐 C++ 的 0 起点首掷语义
        m.statuses.add(MonsterStatus.REACTIVE, 1)
        m.statuses.add(MonsterStatus.MALLEABLE, 3)
        return m

    def apply_end_of_turn_triggers(self, bc: BattleContext) -> None:
        # 对齐 C++ applyEndOfRoundPowers：MALLEABLE 回满 3（Monster.cpp:47-49）
        super().apply_end_of_turn_triggers(bc)
        if self.statuses.has(MonsterStatus.MALLEABLE):
            self.statuses.set(MonsterStatus.MALLEABLE, 3)

    def attacked(self, bc: BattleContext, damage: int) -> None:
        # 覆盖基类 REACTIVE 段（引擎每击重掷 ≠ C++ 仅首次，Monster.cpp:375-381）：
        # 复刻基类管线（死亡/负伤钳制/INTANGIBLE/ANGRY/_apply_damage），
        # REACTIVE 值为 1（首击）时重掷意图，此后仅计数。
        if self.is_dead_or_escaped():
            return
        if damage < 0:
            damage = 0
        if self.statuses.has(MonsterStatus.INTANGIBLE):
            damage = min(damage, 1)
        if self.statuses.has(MonsterStatus.ANGRY):
            self.statuses.add(MonsterStatus.STRENGTH, self.statuses.get(MonsterStatus.ANGRY))
        self._apply_damage(bc, damage, from_attack=True)
        if not self.is_dying and self.statuses.has(MonsterStatus.REACTIVE):
            if self.statuses.get(MonsterStatus.REACTIVE) == 1:
                self.roll_move(bc)
            self.statuses.add(MonsterStatus.REACTIVE, 1)

    def get_move_for_roll(self, bc: BattleContext, roll: int) -> MoveDef:
        if not self.move_history:  # firstTurn 三段
            if roll < 33:
                return self.MULTI_STRIKE
            if roll < 66:
                return self.FLAIL
            return self.WITHER
        have_used_implant = self.misc_info == 1
        my_roll = roll
        while True:
            if my_roll < 10:
                if not _last(self, "Strong Strike"):
                    return self.STRONG_STRIKE
                my_roll = bc.rngs.ai.int_inclusive(10, 99)
            if my_roll < 20:
                if not have_used_implant and not _last(self, "Implant"):
                    return self.IMPLANT
                if _ai_boolean(bc, 0.1):
                    return self.STRONG_STRIKE
                my_roll = bc.rngs.ai.int_inclusive(20, 99)
            if my_roll < 40:
                if not _last(self, "Wither"):
                    return self.WITHER
                if _ai_boolean(bc, 0.4):
                    my_roll = bc.rngs.ai.int_inclusive(0, 19)
                    if my_roll < 10:
                        return self.STRONG_STRIKE
                    if not have_used_implant:
                        return self.IMPLANT
                    if _ai_boolean(bc, 0.1):
                        return self.STRONG_STRIKE
                    my_roll = bc.rngs.ai.int_inclusive(20, 99)
                    continue
                my_roll = bc.rngs.ai.int_inclusive(40, 99)
            if my_roll < 70:
                if not _last(self, "Multi Strike"):
                    return self.MULTI_STRIKE
                if _ai_boolean(bc, 0.3):
                    return self.FLAIL
                my_roll = bc.rngs.ai.int_inclusive(0, 39)
                continue
            return self.FLAIL if not _last(self, "Flail") else self.WITHER

    def take_turn(self, bc: BattleContext) -> None:
        move = self.move_history[0]
        match move.name:
            case "Flail":
                # 本体 WrithingMass.java：格挡 = 基础连枷伤害（damage.get(2).base，
                # 15/16@A2，不含力量）；lightspeed 误为 16/18，wiki 记 16 系只看 A2
                base = 16 if bc.ascension >= 2 else 15
                dmg = bc.calculate_monster_damage(self, base)
                bc.log.append(f"{self.display_name} 使用 连枷(Flail)。")
                bc.add_to_bot(Actions.attack_player(self.idx, dmg))
                bc.add_to_bot(Actions.monster_gain_block(self.idx, base))
                bc.add_to_bot(Actions.roll_move(self.idx))
            case "Implant":
                self.misc_info = 1  # 一次性标记（对齐 C++ miscInfo = true）
                bc.log.append(f"{self.display_name} 使用 植入(Implant)。")
                self.roll_move(bc)
            case "Multi Strike":
                dmg = bc.calculate_monster_damage(self, 9 if bc.ascension >= 2 else 7)
                bc.log.append(f"{self.display_name} 使用 多重打击(Multi Strike)，{dmg} 点伤害 ×3。")
                for _ in range(3):
                    bc.add_to_bot(Actions.attack_player(self.idx, dmg))
                bc.add_to_bot(Actions.roll_move(self.idx))
            case "Strong Strike":
                dmg = bc.calculate_monster_damage(self, 38 if bc.ascension >= 2 else 32)
                bc.log.append(f"{self.display_name} 使用 强力攻击(Strong Strike)。")
                bc.add_to_bot(Actions.attack_player(self.idx, dmg))
                bc.add_to_bot(Actions.roll_move(self.idx))
            case "Wither":
                dmg = bc.calculate_monster_damage(self, 12 if bc.ascension >= 2 else 10)
                bc.log.append(f"{self.display_name} 使用 枯萎(Wither)。")
                bc.add_to_bot(Actions.attack_player(self.idx, dmg))
                bc.add_to_bot(Actions.debuff_player(PlayerStatus.WEAK, 2, True))
                bc.add_to_bot(Actions.debuff_player(PlayerStatus.VULNERABLE, 2, True))
                bc.add_to_bot(Actions.roll_move(self.idx))
            case _:
                raise AssertionError(f"未知招式 {move}")
        self.turns_taken += 1


class GiantHead(Monster):
    """巨人头（Act 3 精英）：迟缓 + 时机已到。

    wiki/C++ A0：HP 500（A8 起 520）。preBattle：SLOW 0 层（玩家每打出
    一张牌 +1；其受到的攻击伤害 ×(1+0.1×层)——C++ 乘区在
    calculateCardDamage，引擎未接线，attacked() 覆盖近似，见下）。
    出招（回合数 = bc.turn，与 C++ getMonsterTurnNumber() 同 1 基）：
      第 4 回合的 roll 起（即第 5 回合起）恒为时机已到：伤害 =
      30（A3 起 40）+ 5×min(回合-5, 6)——首用 30/40，每用一次 +5，
      封顶 60/70；
      此前 50/50：瞪视（1 层虚弱，立即结算）/ 计数（13 伤），同招
      不连续三回合。
    SLOW 乘区近似（attacked 覆盖）：C++ 在玩家出牌时快照（先算伤害
    后 +1 层），引擎动作执行时计数已含当前牌，故用 (层-1)；floor
    时点差异——引擎先 floor 再乘，偶有 ±1（分布级可忽略，见模块头）。
    """

    name = "Giant Head"
    zh = "大脑袋"
    hp_range = (500, 500)
    hp_range_high = (520, 520)
    hp_high_asc = 8

    COUNT = MoveDef("Count", "计数", "attack", base_damage=13)
    GLARE = MoveDef("Glare", "瞪视", "debuff", intent_text="施加 1 层虚弱")
    IT_IS_TIME = MoveDef("It Is Time", "时机已到", "attack", base_damage=30)

    def __init__(self, idx: int, hp: int, max_hp: int):
        super().__init__(idx, hp, max_hp, "大脑袋(Giant Head)")
        # SLOW 0 层起点：_ZeroBasedStatuses 使 has() 恒真（计数/清零照常）
        self.statuses = _ZeroBasedStatuses((MonsterStatus.SLOW,))

    @classmethod
    def create(cls, bc: BattleContext, idx: int) -> "GiantHead":
        hp = _roll_hp(bc, cls)
        return cls(idx, hp, hp)

    # SLOW 乘区已接引擎 calculate_card_damage（BattleContext.cpp:2717 段），
    # attacked 覆盖近似已移除

    def get_move_for_roll(self, bc: BattleContext, roll: int) -> MoveDef:
        # 回合 ≥ 4 时的 roll（为下一回合生成意图）→ 恒时机已到
        if bc.turn >= 4:
            return self.IT_IS_TIME
        if roll < 50:
            return self.GLARE if not _last_two(self, "Glare") else self.COUNT
        return self.COUNT if not _last_two(self, "Count") else self.GLARE

    def take_turn(self, bc: BattleContext) -> None:
        move = self.move_history[0]
        match move.name:
            case "Count":
                dmg = bc.calculate_monster_damage(self, 13)
                bc.log.append(f"{self.display_name} 使用 计数(Count)。")
                bc.add_to_bot(Actions.attack_player(self.idx, dmg))
                bc.add_to_bot(Actions.roll_move(self.idx))
            case "Glare":
                bc.log.append(f"{self.display_name} 使用 瞪视(Glare)。")
                # 对齐 C++ bc.player.debuff：立即结算
                Actions.debuff_player(PlayerStatus.WEAK, 1, True).fn(bc)
                self.roll_move(bc)
            case "It Is Time":
                t = min(bc.turn - 5, 6) * 5
                dmg = bc.calculate_monster_damage(self, (40 if bc.ascension >= 3 else 30) + t)
                bc.log.append(f"{self.display_name} 使用 时机已到(It Is Time)！")
                bc.add_to_bot(Actions.attack_player(self.idx, dmg))
                bc.add_to_bot(Actions.no_op_roll_move())
            case _:
                raise AssertionError(f"未知招式 {move}")
        self.turns_taken += 1


def _either_last_two(m: Monster, name: str) -> bool:
    """对齐 C++ eitherLastTwo：moveHistory[0] 或 [1] 为该招。"""
    return _last(m, name) or _last_before(m, name)


class Nemesis(Monster):
    """复仇者（Act 3 精英）：无实体交替 + 镰刀重击。

    wiki/C++ A0：HP 185（A8 起 200）。意图后缀规则（对齐 C++ NEMESIS
    三个 takeTurn 分支）：本回合无 INTANGIBLE 时，行动结束后获得 2 层
    无实体（攻击/镰刀入队加、第二击立即加）；INTANGIBLE 回合末 -1
    （引擎缺，apply_end_of_turn_triggers 覆盖补）——净效果为"隔回合
    无实体，覆盖 2 回合内的所有攻击"。
    首回合 50/50：攻击（6×3，A3 起 7×3）/ 第二击（塞 3 张灼伤进弃牌
    堆，A18 起 5 张——本体 Nemesis.java 的 A18 分支（lightspeed 误译为
    asc3），立即结算）。此后 roll 分段（逐行对齐 C++）：
      < 30：近两回合无镰刀 → 镰刀（45）；否则 50/50：攻击未连续两回
      合 → 攻击，否则第二击；非上回合第二击 → 第二击，否则攻击；
      < 65：攻击未连续两回合 → 攻击；否则（50% 且近两回合无镰刀）→
      镰刀，不然第二击；
      否则：上回合非第二击 → 第二击；（50% 且近两回合无镰刀）→ 镰刀；
      否则攻击。
    """

    name = "Nemesis"
    zh = "天罚"
    hp_range = (185, 185)
    hp_range_high = (200, 200)
    hp_high_asc = 8

    ATTACK = MoveDef("Attack", "攻击", "attack", base_damage=6)  # ×3 段
    SCYTHE = MoveDef("Scythe", "镰刀", "attack", base_damage=45)
    SECOND_STRIKE = MoveDef("Second Strike", "第二击", "debuff", intent_text="塞 3 张灼伤进弃牌堆")

    def __init__(self, idx: int, hp: int, max_hp: int):
        super().__init__(idx, hp, max_hp, "天罚(Nemesis)")

    @classmethod
    def create(cls, bc: BattleContext, idx: int) -> "Nemesis":
        hp = _roll_hp(bc, cls)
        return cls(idx, hp, hp)

    def apply_end_of_turn_triggers(self, bc: BattleContext) -> None:
        # 对齐 Monster.cpp:55-57：INTANGIBLE 回合末 -1（引擎未做，覆盖补）
        super().apply_end_of_turn_triggers(bc)
        if self.statuses.has(MonsterStatus.INTANGIBLE):
            self.statuses.decrement(MonsterStatus.INTANGIBLE)

    def get_move_for_roll(self, bc: BattleContext, roll: int) -> MoveDef:
        if not self.move_history:  # firstTurn：50/50 攻击/第二击
            return self.ATTACK if roll < 50 else self.SECOND_STRIKE
        if roll < 30:
            if not _either_last_two(self, "Scythe"):
                return self.SCYTHE
            if _ai_boolean(bc, 0.5):
                return self.ATTACK if not _last_two(self, "Attack") else self.SECOND_STRIKE
            return self.SECOND_STRIKE if not _last(self, "Second Strike") else self.ATTACK
        if roll < 65:
            if not _last_two(self, "Attack"):
                return self.ATTACK
            if not _ai_boolean(bc, 0.5) or _either_last_two(self, "Scythe"):
                return self.SECOND_STRIKE
            return self.SCYTHE
        if not _last(self, "Second Strike"):
            return self.SECOND_STRIKE
        if _ai_boolean(bc, 0.5) and not _either_last_two(self, "Scythe"):
            return self.SCYTHE
        return self.ATTACK

    def take_turn(self, bc: BattleContext) -> None:
        move = self.move_history[0]
        match move.name:
            case "Attack":
                dmg = bc.calculate_monster_damage(self, 7 if bc.ascension >= 3 else 6)
                bc.log.append(f"{self.display_name} 使用 攻击(Attack)，{dmg} 点伤害 ×3。")
                for _ in range(3):
                    bc.add_to_bot(Actions.attack_player(self.idx, dmg))
                bc.add_to_bot(Actions.roll_move(self.idx))
                if not self.statuses.has(MonsterStatus.INTANGIBLE):
                    bc.add_to_bot(Actions.buff_enemy(self.idx, MonsterStatus.INTANGIBLE, 2))
            case "Scythe":
                dmg = bc.calculate_monster_damage(self, 45)
                bc.log.append(f"{self.display_name} 使用 镰刀(Scythe)！")
                bc.add_to_bot(Actions.attack_player(self.idx, dmg))
                bc.add_to_bot(Actions.roll_move(self.idx))
                if not self.statuses.has(MonsterStatus.INTANGIBLE):
                    bc.add_to_bot(Actions.buff_enemy(self.idx, MonsterStatus.INTANGIBLE, 2))
            case "Second Strike":
                # 本体 Nemesis.java：A18 起塞 5 张（lightspeed 误译为 asc3）
                n = 5 if bc.ascension >= 18 else 3
                bc.log.append(f"{self.display_name} 使用 第二击(Second Strike)，塞 {n} 张灼伤进弃牌堆。")
                # 对齐 C++ actFunc：立即结算；rollMove 直调；无实体立即自加
                for _ in range(n):
                    Actions.make_temp_card_in_discard(BURN).fn(bc)
                self.roll_move(bc)
                if not self.statuses.has(MonsterStatus.INTANGIBLE):
                    self.statuses.add(MonsterStatus.INTANGIBLE, 2)
            case _:
                raise AssertionError(f"未知招式 {move}")
        self.turns_taken += 1


def _reptomancer_summon(bc: BattleContext, dagger_count: int) -> None:
    """召唤匕首（对齐 Monster::reptomancerSummon + reptoSummonHelper）：
    按 4,1,3,0 的顺序找空槽（死亡/逃跑占位），原位覆写生成匕首
    （MINION、意图固定 Stab）；C++ skipTurn 位图（新匕首本回合不行动）
    以 monster_turn_idx 前跳等效——落在当前回合指针之后的槽位各 +1
    （do_monster_turn 尾部的 +1 使指针恰好越过该槽）。"""
    group = bc.monsters
    open_slots = [i for i in (4, 1, 3, 0) if group.monsters[i].is_dead_or_escaped()]
    for slot in open_slots[:dagger_count]:
        dagger = Dagger.create(bc, slot)
        group.spawn_replace(bc, slot, dagger)
        dagger.statuses.add(MonsterStatus.MINION, 1)
        dagger.set_move(Dagger.STAB)
        if slot > bc.monster_turn_idx:
            bc.monster_turn_idx += 1
        bc.log.append(f"{dagger.display_name} 被召唤进场！")


class Reptomancer(Monster):
    """爬行者法师（Act 3 精英，reptomancer 遭遇槽 2）：主死即胜 + 召唤匕首。

    wiki/C++ A0：HP 180-190（A8 起 190-200）。preBattle：MINION_LEADER。
    遭遇布局（encounters）：槽 1/4 各 1 只匕首、槽 0/3 死亡占位。
    首回合固定召唤（补 1 只匕首，A18 起 2 只；canSpawn = 存活 < 4）；
    此后 while 循环分段（逐行对齐 C++ REPTOMANCER）：
      < 33：上回合非蛇击 → 蛇击（13×2 + 1 虚弱，A3 起 16×2）；否则
      重抽 33-99；
      < 66：召唤未连续两回合且可召 → 召唤，否则蛇击；
      否则：上回合非重咬 → 重咬（30，A3 起 34）；否则重抽 0-65。
    匕首（Dagger）见其类。
    """

    name = "Reptomancer"
    zh = "拜蛇术士"
    hp_range = (180, 190)
    hp_range_high = (190, 200)
    hp_high_asc = 8

    BIG_BITE = MoveDef("Big Bite", "重咬", "attack", base_damage=30)
    SNAKE_STRIKE = MoveDef("Snake Strike", "蛇击", "attack", base_damage=13)  # ×2 段，另施加 1 层虚弱
    SUMMON = MoveDef("Summon", "召唤", "unknown", intent_text="召唤匕首")

    def __init__(self, idx: int, hp: int, max_hp: int):
        super().__init__(idx, hp, max_hp, "拜蛇术士(Reptomancer)")
        self.statuses.add(MonsterStatus.MINION_LEADER, 1)

    @classmethod
    def create(cls, bc: BattleContext, idx: int) -> "Reptomancer":
        hp = _roll_hp(bc, cls)
        return cls(idx, hp, hp)

    def get_move_for_roll(self, bc: BattleContext, roll: int) -> MoveDef:
        if not self.move_history:  # firstTurn：固定召唤
            return self.SUMMON
        can_spawn = bc.monsters.alive_count < 4
        my_roll = roll
        while True:
            if my_roll < 33:
                if not _last(self, "Snake Strike"):
                    return self.SNAKE_STRIKE
                my_roll = bc.rngs.ai.int_inclusive(33, 99)
            if my_roll < 66:
                if not _last_two(self, "Summon") and can_spawn:
                    return self.SUMMON
                return self.SNAKE_STRIKE
            if not _last(self, "Big Bite"):
                return self.BIG_BITE
            my_roll = bc.rngs.ai.int_inclusive(0, 65)

    def take_turn(self, bc: BattleContext) -> None:
        move = self.move_history[0]
        match move.name:
            case "Big Bite":
                dmg = bc.calculate_monster_damage(self, 34 if bc.ascension >= 3 else 30)
                bc.log.append(f"{self.display_name} 使用 重咬(Big Bite)。")
                bc.add_to_bot(Actions.attack_player(self.idx, dmg))
                bc.add_to_bot(Actions.roll_move(self.idx))
            case "Snake Strike":
                dmg = bc.calculate_monster_damage(self, 16 if bc.ascension >= 3 else 13)
                bc.log.append(f"{self.display_name} 使用 蛇击(Snake Strike)，{dmg} 点伤害 ×2。")
                for _ in range(2):
                    bc.add_to_bot(Actions.attack_player(self.idx, dmg))
                bc.add_to_bot(Actions.debuff_player(PlayerStatus.WEAK, 1, True))
                bc.add_to_bot(Actions.roll_move(self.idx))
            case "Summon":
                bc.log.append(f"{self.display_name} 使用 召唤(Summon)！")
                _reptomancer_summon(bc, 2 if bc.ascension >= 18 else 1)
                self.roll_move(bc)
            case _:
                raise AssertionError(f"未知招式 {move}")
        self.turns_taken += 1


class Dagger(Monster):
    """匕首（reptomancer 遭遇随从）：戳刺一次后自爆。

    wiki/C++ A0：HP 20-25（A8+ 同区间）。preBattle：MINION。意图链
    （rollMove 仅在被召唤时走 setMove(Stab)，此后 set_move 切换）：
      戳刺：9 伤 + 塞 1 张伤口进弃牌堆 → 下回合固定自爆；
      自爆：25 伤 + 对自身全额伤害自杀（SuicideAction(triggerRelics=true)
      走 die() 结算）。
    """

    name = "Dagger"
    zh = "匕首"
    hp_range = (20, 25)
    hp_range_high = (20, 25)
    hp_high_asc = 8  # 对齐 C++ initHp 分组（两档区间相同，无实际影响）

    STAB = MoveDef("Stab", "戳刺", "attack", base_damage=9)  # 另塞 1 张伤口
    EXPLODE = MoveDef("Explode", "自爆", "attack", base_damage=25)

    def __init__(self, idx: int, hp: int, max_hp: int):
        super().__init__(idx, hp, max_hp, "匕首(Dagger)")
        self.statuses.add(MonsterStatus.MINION, 1)

    @classmethod
    def create(cls, bc: BattleContext, idx: int) -> "Dagger":
        hp = _roll_hp(bc, cls)
        return cls(idx, hp, hp)

    def get_move_for_roll(self, bc: BattleContext, roll: int) -> MoveDef:
        # 对齐 C++：恒 Stab（召唤处直接 set_move(Stab)，本方法仅兜底）
        return self.STAB

    def take_turn(self, bc: BattleContext) -> None:
        move = self.move_history[0]
        match move.name:
            case "Stab":
                dmg = bc.calculate_monster_damage(self, 9)
                bc.log.append(f"{self.display_name} 使用 戳刺(Stab)。")
                bc.add_to_bot(Actions.attack_player(self.idx, dmg))
                bc.add_to_bot(Actions.make_temp_card_in_discard(WOUND))
                self.set_move(self.EXPLODE)
                bc.add_to_bot(Actions.no_op_roll_move())
            case "Explode":
                dmg = bc.calculate_monster_damage(self, 25)
                bc.log.append(f"{self.display_name} 自爆(Explode)了！")
                bc.add_to_bot(Actions.attack_player(self.idx, dmg))
                bc.add_to_bot(_suicide_by_damage(self.idx))
                bc.add_to_bot(Actions.no_op_roll_move())
            case _:
                raise AssertionError(f"未知招式 {move}")
        self.turns_taken += 1


# ---- Act 3 Boss ----


class AwakenedOne(Monster):
    """觉醒者（Act 3 Boss，awakened_one 遭遇槽 2，槽 0/1 为两只邪教徒）：
    half_dead 二阶段。

    wiki/C++ A0：HP 300（A9 起 320——本体 AwakenedOne.java setHp(320)
    恒定值；lightspeed 误为区间 300-320 抽样，wiki 为准）；二阶段
    REBIRTH 固定 maxHp = 320（A9）/300 满血。
    preBattle：A4 起力量 +2；CURIOSITY 1（A19 起 2；玩家每打出能力牌
    +层 力量，引擎 on_use_power_card）；REGEN 10（A19 起 15，回合末
    回血减层）。
    一阶段 roll：首回合固定挥砍（20 伤）；roll < 25：上回合灵魂斩击 →
    挥砍，否则灵魂斩击（6×4）；否则挥砍未连续两回合 → 挥砍，否则
    灵魂斩击。
    阶段 1 死亡（die 覆盖，对齐 Monster.cpp:286-292）：hp 归零时不断
    胜（该分支先于判胜检查，即使场上只剩 Boss）——存活数 -1、清
    debuff、移除 CURIOSITY、置意图 Rebirth、清卡牌队列、half_dead
    假死；下一次自身回合执行 Rebirth：满血复活、misc 标记二阶段、
    负力量归零、存活数 +1、挂 MINION_LEADER（二阶段死亡立即判胜，
    即使邪教徒仍在场）、下回合意图黑暗回响（40 伤）。
    二阶段 roll：roll < 50：污泥未连续两回合 → 污泥（18 伤 + 洗 1 张
    虚空进抽牌堆），否则冲撞（10×3）；否则冲撞未连续两回合 → 冲撞，
    否则污泥。
    """

    name = "Awakened One"
    zh = "觉醒者"
    hp_range = (300, 300)
    hp_range_high = (320, 320)  # 本体 setHp(320) 恒定（lightspeed 误为 300-320 区间）
    hp_high_asc = 9

    SLASH = MoveDef("Slash", "挥砍", "attack", base_damage=20)
    SOUL_STRIKE = MoveDef("Soul Strike", "灵魂攻击", "attack", base_damage=6)  # ×4 段
    REBIRTH = MoveDef("Rebirth", "重生", "buff", intent_text="满血复活，进入第二形态")
    DARK_ECHO = MoveDef("Dark Echo", "黑暗回音", "attack", base_damage=40)
    SLUDGE = MoveDef("Sludge", "污泥", "attack", base_damage=18)  # 另洗 1 张虚空
    TACKLE = MoveDef("Tackle", "冲撞", "attack", base_damage=10)  # ×3 段

    def __init__(self, idx: int, hp: int, max_hp: int):
        super().__init__(idx, hp, max_hp, "觉醒者(Awakened One)")

    @classmethod
    def create(cls, bc: BattleContext, idx: int) -> "AwakenedOne":
        hp = _roll_hp(bc, cls)
        m = cls(idx, hp, hp)
        if bc.ascension >= 4:
            m.statuses.add(MonsterStatus.STRENGTH, 2)
        m.statuses.add(MonsterStatus.CURIOSITY, 2 if bc.ascension >= 19 else 1)
        m.statuses.add(MonsterStatus.REGEN, 15 if bc.ascension >= 19 else 10)
        return m

    def die(self, bc: BattleContext) -> None:
        # 对齐 C++ die() 的 AWAKENED_ONE 分支（先于判胜检查）：一阶段
        # 死亡不判胜，假死待 Rebirth；二阶段（misc_info=1）走正常 die()
        #（MINION_LEADER → 主死即胜）。覆盖引擎 half_dead 早退兜底。
        if self.half_dead:
            return
        if self.misc_info == 0:
            self.is_dying = True
            self.half_dead = True  # 对齐 C++ halfDead = true（假死待 Rebirth）
            bc.monsters.alive_count -= 1
            _remove_debuffs(self)
            self.statuses.remove(MonsterStatus.CURIOSITY)
            self.set_move(self.REBIRTH)
            bc.card_queue.clear()
            return
        super().die(bc)

    def get_move_for_roll(self, bc: BattleContext, roll: int) -> MoveDef:
        if self.half_dead:
            return self.REBIRTH
        if self.misc_info == 0:  # 一阶段
            if not self.move_history:  # firstTurn：固定挥砍
                return self.SLASH
            if roll < 25:
                return self.SLASH if _last(self, "Soul Strike") else self.SOUL_STRIKE
            return self.SLASH if not _last_two(self, "Slash") else self.SOUL_STRIKE
        # 二阶段
        if roll < 50:
            return self.SLUDGE if not _last_two(self, "Sludge") else self.TACKLE
        return self.TACKLE if not _last_two(self, "Tackle") else self.SLUDGE

    def take_turn(self, bc: BattleContext) -> None:
        move = self.move_history[0]
        match move.name:
            case "Slash":
                dmg = bc.calculate_monster_damage(self, 20)
                bc.log.append(f"{self.display_name} 使用 挥砍(Slash)。")
                bc.add_to_bot(Actions.attack_player(self.idx, dmg))
                bc.add_to_bot(Actions.roll_move(self.idx))
            case "Soul Strike":
                dmg = bc.calculate_monster_damage(self, 6)
                bc.log.append(f"{self.display_name} 使用 灵魂攻击(Soul Strike)，{dmg} 点伤害 ×4！")
                for _ in range(4):
                    bc.add_to_bot(Actions.attack_player(self.idx, dmg))
                bc.add_to_bot(Actions.roll_move(self.idx))
            case "Rebirth":
                # 对齐 C++ REBIRTH：满血复活 + 二阶段标记 + MINION_LEADER
                self.max_hp = 320 if bc.ascension >= 9 else 300
                self.hp = self.max_hp
                self.half_dead = False
                self.is_dying = False
                self.misc_info = 1  # 二阶段标记（对齐 C++ miscInfo = true）
                if self.statuses.get(MonsterStatus.STRENGTH) < 0:
                    self.statuses.set(MonsterStatus.STRENGTH, 0)
                bc.monsters.alive_count += 1
                self.statuses.add(MonsterStatus.MINION_LEADER, 1)
                self.set_move(self.DARK_ECHO)
                bc.log.append(f"{self.display_name} 重生(Rebirth)了！进入第二形态。")
                bc.add_to_bot(Actions.no_op_roll_move())
            case "Dark Echo":
                dmg = bc.calculate_monster_damage(self, 40)
                bc.log.append(f"{self.display_name} 使用 黑暗回音(Dark Echo)。")
                bc.add_to_bot(Actions.attack_player(self.idx, dmg))
                bc.add_to_bot(Actions.roll_move(self.idx))
            case "Sludge":
                dmg = bc.calculate_monster_damage(self, 18)
                bc.log.append(f"{self.display_name} 使用 污泥(Sludge)。")
                bc.add_to_bot(Actions.attack_player(self.idx, dmg))
                bc.add_to_bot(Actions.make_temp_card_in_draw_pile(VOID, False, True))
                bc.add_to_bot(Actions.roll_move(self.idx))
            case "Tackle":
                dmg = bc.calculate_monster_damage(self, 10)
                bc.log.append(f"{self.display_name} 使用 冲撞(Tackle)，{dmg} 点伤害 ×3。")
                for _ in range(3):
                    bc.add_to_bot(Actions.attack_player(self.idx, dmg))
                bc.add_to_bot(Actions.roll_move(self.idx))
            case _:
                raise AssertionError(f"未知招式 {move}")
        self.turns_taken += 1


class TimeEater(Monster):
    """时间吞噬者（Act 3 Boss，单怪遭遇）：TIME_WARP 提前结束回合链。

    wiki/C++ A0：HP 456（A9 起 480）。preBattle：TIME_WARP 0 层
    （_ZeroBasedStatuses 使 0 层即被引擎计数钩子识别：玩家每出一张牌
    +1，第 12 张触发——重置、力量 +2、立即结束玩家回合；此后从 0
    继续计数）。roll 分段（misc_info 记已用急速）：
      未用急速且 hp < maxHp//2 → 急速（hp 设为 maxHp//2、移除自身
      debuff、A19 另 +32 格挡；整场一次）；
      < 45：回响未连续两回合 → 回响（7×3，A4 起 8×3），否则重抽 50-99；
      < 80：上回合非头撞 → 头撞（26 伤 + 1 层抽牌减少，A4 起 32 伤、
      A19 另塞 2 张黏液），否则 66% 回响 / 否则涟漪；
      否则：上回合涟漪 → 重抽 0-73（<45 回响，否则头撞）；否则涟漪。
    涟漪：+20 格挡（立即），玩家 1 层虚弱 + 1 层易伤（立即，A19 另
    1 层脆弱）。
    """

    name = "Time Eater"
    zh = "时间吞噬者"
    hp_range = (456, 456)
    hp_range_high = (480, 480)
    hp_high_asc = 9

    REVERBERATE = MoveDef("Reverberate", "回响", "attack", base_damage=7)  # ×3 段
    RIPPLE = MoveDef("Ripple", "涟漪", "defend", intent_text="获得 20 点格挡，施加虚弱与易伤")
    HEAD_SLAM = MoveDef("Head Slam", "头撞", "attack", base_damage=26)  # 另施加 1 层抽牌减少
    HASTE = MoveDef("Haste", "急速", "buff", intent_text="移除自身削弱，HP 设为 50%")

    def __init__(self, idx: int, hp: int, max_hp: int):
        super().__init__(idx, hp, max_hp, "时间吞噬者(Time Eater)")
        # TIME_WARP 0 层起点（对齐 buff<MS::TIME_WARP>(0)）：has 恒真使
        # 引擎 use_card 计数从 0 生效、触发后归零继续（见 _ZeroBasedStatuses）
        self.statuses = _ZeroBasedStatuses((MonsterStatus.TIME_WARP,))

    @classmethod
    def create(cls, bc: BattleContext, idx: int) -> "TimeEater":
        hp = _roll_hp(bc, cls)
        return cls(idx, hp, hp)

    def get_move_for_roll(self, bc: BattleContext, roll: int) -> MoveDef:
        used_haste = self.misc_info == 1
        under_half = self.hp < self.max_hp // 2
        if not used_haste and under_half:
            return self.HASTE
        my_roll = roll
        if my_roll < 45:
            if not _last_two(self, "Reverberate"):
                return self.REVERBERATE
            my_roll = bc.rngs.ai.int_inclusive(50, 99)
        if my_roll < 80:
            if not _last(self, "Head Slam"):
                return self.HEAD_SLAM
            if _ai_boolean(bc, 0.66):
                return self.REVERBERATE
            return self.RIPPLE
        if _last(self, "Ripple"):
            my_roll = bc.rngs.ai.int_inclusive(0, 73)
            return self.REVERBERATE if my_roll < 45 else self.HEAD_SLAM
        return self.RIPPLE

    def take_turn(self, bc: BattleContext) -> None:
        move = self.move_history[0]
        match move.name:
            case "Haste":
                self.misc_info = 1  # 已用急速（对齐 C++ miscInfo = true）
                self.hp = self.max_hp // 2  # C++ curHp = maxHp/2：设为而非回复
                if bc.ascension >= 19:
                    self.block += 32  # 对齐 C++ addBlock：立即结算
                _remove_debuffs(self)  # 对齐 C++ removeDebuffs（含 SHACKLED）
                bc.log.append(f"{self.display_name} 使用 急速(Haste)，移除了自身的削弱！")
                self.roll_move(bc)
            case "Head Slam":
                dmg = bc.calculate_monster_damage(self, 32 if bc.ascension >= 4 else 26)
                bc.log.append(f"{self.display_name} 使用 头撞(Head Slam)。")
                bc.add_to_bot(Actions.attack_player(self.idx, dmg))
                bc.add_to_bot(Actions.debuff_player(PlayerStatus.DRAW_REDUCTION, 1, True))
                if bc.ascension >= 19:
                    for _ in range(2):
                        bc.add_to_bot(Actions.make_temp_card_in_discard(SLIMED))
                bc.add_to_bot(Actions.roll_move(self.idx))
            case "Reverberate":
                dmg = bc.calculate_monster_damage(self, 8 if bc.ascension >= 4 else 7)
                bc.log.append(f"{self.display_name} 使用 回响(Reverberate)，{dmg} 点伤害 ×3。")
                for _ in range(3):
                    bc.add_to_bot(Actions.attack_player(self.idx, dmg))
                bc.add_to_bot(Actions.roll_move(self.idx))
            case "Ripple":
                self.block += 20  # 对齐 C++ addBlock：立即结算
                bc.log.append(f"{self.display_name} 使用 涟漪(Ripple)。")
                # 对齐 C++ bc.player.debuff：立即结算
                Actions.debuff_player(PlayerStatus.WEAK, 1, True).fn(bc)
                Actions.debuff_player(PlayerStatus.VULNERABLE, 1, True).fn(bc)
                if bc.ascension >= 19:
                    Actions.debuff_player(PlayerStatus.FRAIL, 1, True).fn(bc)
                self.roll_move(bc)
            case _:
                raise AssertionError(f"未知招式 {move}")
        self.turns_taken += 1


class Deca(Monster):
    """德卡（Act 3 双 Boss，donu_and_deca 遭遇槽 0）：光束 / 守护方阵。

    wiki/C++ A0：HP 250（A9 起 265）。preBattle：ARTIFACT 2（A19 起 3）。
    意图链（全 set_move，rollMove 仅首回合一次）：光束（10×2（A4 起
    12×2）+ 塞 2 张眩晕进弃牌堆）↔ 守护方阵（德卡与多努（槽 1）各
    +16 格挡（立即结算）；A19 起另各 +3 层重甲）交替。
    """

    name = "Deca"
    zh = "八体"
    hp_range = (250, 250)
    hp_range_high = (265, 265)
    hp_high_asc = 9

    BEAM = MoveDef("Beam", "光束", "attack", base_damage=10)  # ×2 段，另塞 2 张眩晕
    SQUARE_OF_PROTECTION = MoveDef("Square of Protection", "守护方阵", "defend",
                                   intent_text="德卡与多努各获得 16 点格挡")

    def __init__(self, idx: int, hp: int, max_hp: int):
        super().__init__(idx, hp, max_hp, "八体(Deca)")

    @classmethod
    def create(cls, bc: BattleContext, idx: int) -> "Deca":
        hp = _roll_hp(bc, cls)
        m = cls(idx, hp, hp)
        m.statuses.add(MonsterStatus.ARTIFACT, 3 if bc.ascension >= 19 else 2)
        return m

    def get_move_for_roll(self, bc: BattleContext, roll: int) -> MoveDef:
        # 对齐 C++：恒光束（此后 take_turn 全 set_move）
        return self.BEAM

    def take_turn(self, bc: BattleContext) -> None:
        move = self.move_history[0]
        match move.name:
            case "Beam":
                dmg = bc.calculate_monster_damage(self, 12 if bc.ascension >= 4 else 10)
                bc.log.append(f"{self.display_name} 使用 光束(Beam)，{dmg} 点伤害 ×2。")
                for _ in range(2):
                    bc.add_to_bot(Actions.attack_player(self.idx, dmg))
                for _ in range(2):
                    bc.add_to_bot(Actions.make_temp_card_in_discard(DAZED))
                self.set_move(self.SQUARE_OF_PROTECTION)
            case "Square of Protection":
                bc.log.append(f"{self.display_name} 使用 守护方阵(Square of Protection)。")
                self.block += 16  # 对齐 C++ addBlock：立即结算
                if bc.monsters.monster_count > 1:
                    donu = bc.monsters.monsters[1]  # C++ 硬编码 arr[1]（死亡亦加，无害）
                    donu.block += 16
                    if bc.ascension >= 19:
                        donu.statuses.add(MonsterStatus.PLATED_ARMOR_M, 3)
                if bc.ascension >= 19:
                    self.statuses.add(MonsterStatus.PLATED_ARMOR_M, 3)
                self.set_move(self.BEAM)
            case _:
                raise AssertionError(f"未知招式 {move}")
        bc.add_to_bot(Actions.no_op_roll_move())
        self.turns_taken += 1


class Donu(Monster):
    """多努（Act 3 双 Boss，donu_and_deca 遭遇槽 1）：光束 / 力量圆环。

    wiki/C++ A0：HP 250（A9 起 265）。preBattle：ARTIFACT 2（A19 起 3）。
    意图链（全 set_move）：光束（10×2（A4 起 12×2））↔ 力量圆环（德卡
    （槽 0）与多努各 力量 +3——C++ 注释"德卡死了也照样加"，死亡加成
    无害，按字面保留）交替。
    """

    name = "Donu"
    zh = "甜圈"
    hp_range = (250, 250)
    hp_range_high = (265, 265)
    hp_high_asc = 9

    BEAM = MoveDef("Beam", "光束", "attack", base_damage=10)  # ×2 段
    CIRCLE_OF_POWER = MoveDef("Circle of Power", "力量之环", "buff",
                              intent_text="德卡与多努各力量 +3")

    def __init__(self, idx: int, hp: int, max_hp: int):
        super().__init__(idx, hp, max_hp, "甜圈(Donu)")

    @classmethod
    def create(cls, bc: BattleContext, idx: int) -> "Donu":
        hp = _roll_hp(bc, cls)
        m = cls(idx, hp, hp)
        m.statuses.add(MonsterStatus.ARTIFACT, 3 if bc.ascension >= 19 else 2)
        return m

    def get_move_for_roll(self, bc: BattleContext, roll: int) -> MoveDef:
        # 对齐 C++：恒力量圆环（此后 take_turn 全 set_move）
        return self.CIRCLE_OF_POWER

    def take_turn(self, bc: BattleContext) -> None:
        move = self.move_history[0]
        match move.name:
            case "Beam":
                dmg = bc.calculate_monster_damage(self, 12 if bc.ascension >= 4 else 10)
                bc.log.append(f"{self.display_name} 使用 光束(Beam)，{dmg} 点伤害 ×2。")
                for _ in range(2):
                    bc.add_to_bot(Actions.attack_player(self.idx, dmg))
                self.set_move(self.CIRCLE_OF_POWER)
            case "Circle of Power":
                bc.log.append(f"{self.display_name} 使用 力量之环(Circle of Power)，德卡与多努各力量 +3。")
                deca = bc.monsters.monsters[0]  # C++ 硬编码 arr[0]（死亡亦加，无害）
                deca.statuses.add(MonsterStatus.STRENGTH, 3)
                self.statuses.add(MonsterStatus.STRENGTH, 3)
                self.set_move(self.BEAM)
            case _:
                raise AssertionError(f"未知招式 {move}")
        bc.add_to_bot(Actions.no_op_roll_move())
        self.turns_taken += 1


# ---- Act 4 ----


class SpireShield(Monster):
    """尖塔之盾（Act 4，shield_and_spear 遭遇槽 0）：猛击 / 坚守 / 粉碎。

    wiki/C++ A0：HP 110（A8 起 125）。preBattle：玩家 SURROUNDED 1
    （被包围：攻击非面向的怪时其伤害 ×1.5——引擎无 lastTargetedMonster
    追踪，乘区未接线，见模块头注释）+ 自身 ARTIFACT 1（A18 起 2）。
    意图链（首意图 50/50 猛击/坚守，rollMove 仅粉碎后入队）：
      猛击：12 伤（A3 起 14）+ 玩家力量 -1（立即）；上上回合为粉碎或
      无记录 → 坚守，否则粉碎；
      坚守：自身与尖塔之矛（槽 1）各 +30 格挡（立即）；上上回合为
      粉碎或无记录 → 猛击，否则粉碎；
      粉碎：34 伤（A3 起 38）+ 获得等同伤害的格挡（A18 起 99）。
    """

    name = "Spire Shield"
    zh = "高塔之盾"
    hp_range = (110, 110)
    hp_range_high = (125, 125)
    hp_high_asc = 8

    BASH = MoveDef("Bash", "猛击", "attack", base_damage=12)  # 另使玩家力量 -1
    FORTIFY = MoveDef("Fortify", "坚守", "defend", intent_text="自身与尖塔之矛各获得 30 点格挡")
    SMASH = MoveDef("Smash", "粉碎", "attack", base_damage=34)  # 另获得等同伤害的格挡

    def __init__(self, idx: int, hp: int, max_hp: int):
        super().__init__(idx, hp, max_hp, "高塔之盾(Spire Shield)")

    @classmethod
    def create(cls, bc: BattleContext, idx: int) -> "SpireShield":
        hp = _roll_hp(bc, cls)
        m = cls(idx, hp, hp)
        m.statuses.add(MonsterStatus.ARTIFACT, 2 if bc.ascension >= 18 else 1)
        # 对齐 C++ preBattle：bc.player.buff<PS::SURROUNDED>()
        bc.player.statuses.add(PlayerStatus.SURROUNDED, 1)
        return m

    def get_move_for_roll(self, bc: BattleContext, roll: int) -> MoveDef:
        return self.FORTIFY if _ai_boolean(bc, 0.5) else self.BASH

    def take_turn(self, bc: BattleContext) -> None:
        move = self.move_history[0]
        match move.name:
            case "Bash":
                dmg = bc.calculate_monster_damage(self, 14 if bc.ascension >= 3 else 12)
                bc.log.append(f"{self.display_name} 使用 猛击(Bash)。")
                bc.add_to_bot(Actions.attack_player(self.idx, dmg))
                # 对齐 C++ bc.player.debuff<PS::STRENGTH>(-1)：立即结算
                Actions.debuff_player(PlayerStatus.STRENGTH, -1, True).fn(bc)
                if len(self.move_history) < 2 or self.move_history[1].name == "Smash":
                    self.set_move(self.FORTIFY)
                else:
                    self.set_move(self.SMASH)
                bc.add_to_bot(Actions.no_op_roll_move())
            case "Fortify":
                bc.log.append(f"{self.display_name} 使用 坚守(Fortify)。")
                self.block += 30  # 对齐 C++ addBlock：立即结算
                if bc.monsters.monster_count > 1:
                    spear = bc.monsters.monsters[1]  # C++ 硬编码 arr[1]
                    spear.block += 30
                if len(self.move_history) < 2 or self.move_history[1].name == "Smash":
                    self.set_move(self.BASH)
                else:
                    self.set_move(self.SMASH)
                bc.add_to_bot(Actions.no_op_roll_move())
            case "Smash":
                dmg = bc.calculate_monster_damage(self, 38 if bc.ascension >= 3 else 34)
                bc.log.append(f"{self.display_name} 使用 粉碎(Smash)。")
                bc.add_to_bot(Actions.attack_player(self.idx, dmg))
                bc.add_to_bot(Actions.monster_gain_block(self.idx, 99 if bc.ascension >= 18 else dmg))
                bc.add_to_bot(Actions.roll_move(self.idx))
            case _:
                raise AssertionError(f"未知招式 {move}")
        self.turns_taken += 1


class SpireSpear(Monster):
    """尖塔之矛（Act 4，shield_and_spear 遭遇槽 1）：灼烧打击 / 穿刺 / 串刺。

    wiki/C++ A0：HP 160（A8 起 180）。preBattle：ARTIFACT 1（A18 起 2）。
    意图链（首意图固定灼烧打击；串刺后 rollMove 50/50 灼烧/穿刺）：
      灼烧打击：5×2（A3 起 6×2）+ 塞 2 张灼伤进弃牌堆（A18 起改为
      2 张灼伤进抽牌堆顶）；上上回合为串刺 → 穿刺，否则串刺；
      穿刺：自身与尖塔之盾（槽 0）各力量 +2（立即）；上上回合为串刺
      → 灼烧打击，否则串刺；
      串刺：10 伤 ×3（A3 起 ×4）。
    """

    name = "Spire Spear"
    zh = "高塔之矛"
    hp_range = (160, 160)
    hp_range_high = (180, 180)
    hp_high_asc = 8

    BURN_STRIKE = MoveDef("Burn Strike", "灼烧打击", "attack", base_damage=5)  # ×2 段，另塞 2 张灼伤
    PIERCER = MoveDef("Piercer", "穿刺", "buff", intent_text="自身与尖塔之盾各力量 +2")
    SKEWER = MoveDef("Skewer", "串刺", "attack", base_damage=10)  # ×3 段（A3 起 ×4）

    def __init__(self, idx: int, hp: int, max_hp: int):
        super().__init__(idx, hp, max_hp, "高塔之矛(Spire Spear)")

    @classmethod
    def create(cls, bc: BattleContext, idx: int) -> "SpireSpear":
        hp = _roll_hp(bc, cls)
        m = cls(idx, hp, hp)
        m.statuses.add(MonsterStatus.ARTIFACT, 2 if bc.ascension >= 18 else 1)
        return m

    def get_move_for_roll(self, bc: BattleContext, roll: int) -> MoveDef:
        if not self.move_history:  # firstTurn：固定灼烧打击
            return self.BURN_STRIKE
        return self.PIERCER if _ai_boolean(bc, 0.5) else self.BURN_STRIKE

    def _next_move(self, after_piercer: bool) -> None:
        # 对齐 C++ lastMoveBefore(SKEWER)：上上回合为串刺 → 穿刺后接
        # 灼烧打击 / 灼烧打击后接穿刺；否则串刺
        if len(self.move_history) >= 2 and self.move_history[1].name == "Skewer":
            self.set_move(self.BURN_STRIKE if after_piercer else self.PIERCER)
        else:
            self.set_move(self.SKEWER)

    def take_turn(self, bc: BattleContext) -> None:
        move = self.move_history[0]
        match move.name:
            case "Burn Strike":
                dmg = bc.calculate_monster_damage(self, 6 if bc.ascension >= 3 else 5)
                bc.log.append(f"{self.display_name} 使用 灼烧打击(Burn Strike)，{dmg} 点伤害 ×2。")
                for _ in range(2):
                    bc.add_to_bot(Actions.attack_player(self.idx, dmg))
                if bc.ascension >= 18:
                    # A18：2 张灼伤进抽牌堆顶（不洗入）
                    for _ in range(2):
                        bc.add_to_bot(Actions.make_temp_card_in_draw_pile(BURN, False, False))
                else:
                    for _ in range(2):
                        bc.add_to_bot(Actions.make_temp_card_in_discard(BURN))
                self._next_move(after_piercer=False)
                bc.add_to_bot(Actions.no_op_roll_move())
            case "Piercer":
                bc.log.append(f"{self.display_name} 使用 穿刺(Piercer)，自身与尖塔之盾各力量 +2。")
                self.statuses.add(MonsterStatus.STRENGTH, 2)
                shield = bc.monsters.monsters[0]  # C++ 硬编码 arr[0]（死亡亦加，无害）
                shield.statuses.add(MonsterStatus.STRENGTH, 2)
                self._next_move(after_piercer=True)
                bc.add_to_bot(Actions.no_op_roll_move())
            case "Skewer":
                dmg = bc.calculate_monster_damage(self, 10)
                hits = 4 if bc.ascension >= 3 else 3
                bc.log.append(f"{self.display_name} 使用 串刺(Skewer)，{dmg} 点伤害 ×{hits}。")
                for _ in range(hits):
                    bc.add_to_bot(Actions.attack_player(self.idx, dmg))
                bc.add_to_bot(Actions.roll_move(self.idx))
            case _:
                raise AssertionError(f"未知招式 {move}")
        self.turns_taken += 1


class CorruptHeart(Monster):
    """腐化之心（Act 4 最终 Boss，单怪遭遇）：死亡节拍 + 无敌 + 轮转增強。

    wiki/C++ A0：HP 750（A9 起 800）。preBattle：BEAT_OF_DEATH 1
    （A19 起 2；玩家每出一张牌受层伤，引擎 use_card）+ INVINCIBLE
    池 300（A19 起 200）。
    意图链：首回合固定削弱（2 层易伤/虚弱/脆弱 + 各洗 1 张眩晕/黏液/
    伤口/灼伤/虚空进抽牌堆）；此后 50/50 血针（2×12（A4 起 2×15））/
    回声（40（A4 起 45））交替——回合数为 3 的倍数时，下回合为增强
    （实际第 4、7、10……回合）：负力量归零后 +2，并按第 N 次增强
    （回合//3）：1→人工制品 2 / 2→死亡节拍 +1 / 3→痛苦刺击 / 4→力量
    +10 / 5+→力量 +50。
    INVINCIBLE（引擎分支语义与 C++ 池语义不同，见模块头注释）：本类
    以 unique_power0 存剩余池、apply_start_of_turn_powers 回满（对齐
    C++ 每回合重置）、on_hp_lost 按实伤扣池并回写 misc_info——引擎
    的钳制分支读 cap = 20 + misc_info，回写后即等效 C++ 的
    "单次伤害钳剩余池"。毒等非攻击 HP 损失仍会漏钳（引擎分支仅
    from_attack）——已知偏差。
    """

    name = "Corrupt Heart"
    zh = "腐化之心"
    hp_range = (750, 750)
    hp_range_high = (800, 800)
    hp_high_asc = 9

    BLOOD_SHOTS = MoveDef("Blood Shots", "血针", "attack", base_damage=2)  # ×12 段（A4 起 ×15）
    ECHO = MoveDef("Echo", "回声", "attack", base_damage=40)
    DEBILITATE = MoveDef("Debilitate", "削弱", "debuff",
                         intent_text="施加 2 层易伤/虚弱/脆弱，并各洗 1 张状态牌进抽牌堆")
    BUFF = MoveDef("Buff", "增强", "buff", intent_text="力量 +2 与递增的增益")

    def __init__(self, idx: int, hp: int, max_hp: int):
        super().__init__(idx, hp, max_hp, "腐化之心(Corrupt Heart)")

    @classmethod
    def create(cls, bc: BattleContext, idx: int) -> "CorruptHeart":
        hp = _roll_hp(bc, cls)
        m = cls(idx, hp, hp)
        m.statuses.add(MonsterStatus.BEAT_OF_DEATH, 2 if bc.ascension >= 19 else 1)
        pool = 200 if bc.ascension >= 19 else 300
        m.statuses.add(MonsterStatus.INVINCIBLE, 1)
        m.unique_power0 = pool  # 剩余池（本类源真值）
        m.misc_info = pool - 20  # 引擎钳制分支的 cap 编码（cap = 20 + misc）
        return m

    def apply_start_of_turn_powers(self, bc: BattleContext) -> None:
        # 对齐 C++ applyStartOfTurnPowers：INVINCIBLE 池每回合回满
        pool = 200 if bc.ascension >= 19 else 300
        self.unique_power0 = pool
        self.misc_info = pool - 20
        super().apply_start_of_turn_powers(bc)

    def on_hp_lost(self, bc: BattleContext, amount: int) -> None:
        # 按实伤扣池并回写 misc_info（覆盖引擎钳制分支对该槽的临时改动）
        self.unique_power0 = max(0, self.unique_power0 - amount)
        self.misc_info = self.unique_power0 - 20

    def get_move_for_roll(self, bc: BattleContext, roll: int) -> MoveDef:
        if not self.move_history:  # firstTurn：固定削弱
            return self.DEBILITATE
        return self.BLOOD_SHOTS if _ai_boolean(bc, 0.5) else self.ECHO

    def take_turn(self, bc: BattleContext) -> None:
        move = self.move_history[0]
        match move.name:
            case "Blood Shots":
                dmg = bc.calculate_monster_damage(self, 2)
                hits = 15 if bc.ascension >= 4 else 12
                bc.log.append(f"{self.display_name} 使用 血针(Blood Shots)，{dmg} 点伤害 ×{hits}！")
                for _ in range(hits):
                    bc.add_to_bot(Actions.attack_player(self.idx, dmg))
                self.set_move(self.BUFF if bc.turn % 3 == 0 else self.ECHO)
                bc.add_to_bot(Actions.no_op_roll_move())
            case "Echo":
                dmg = bc.calculate_monster_damage(self, 45 if bc.ascension >= 4 else 40)
                bc.log.append(f"{self.display_name} 使用 回声(Echo)。")
                bc.add_to_bot(Actions.attack_player(self.idx, dmg))
                self.set_move(self.BUFF if bc.turn % 3 == 0 else self.BLOOD_SHOTS)
                bc.add_to_bot(Actions.no_op_roll_move())
            case "Debilitate":
                bc.log.append(f"{self.display_name} 使用 削弱(Debilitate)！")
                # 对齐 C++ bc.player.debuff + actFunc：立即结算
                Actions.debuff_player(PlayerStatus.VULNERABLE, 2, True).fn(bc)
                Actions.debuff_player(PlayerStatus.WEAK, 2, True).fn(bc)
                Actions.debuff_player(PlayerStatus.FRAIL, 2, True).fn(bc)
                for card in (DAZED, SLIMED, WOUND, BURN, VOID):
                    Actions.make_temp_card_in_draw_pile(card, False, True).fn(bc)
                self.roll_move(bc)
            case "Buff":
                # 对齐 C++：负力量归零后 +2；buffCount = getMonsterTurnNumber()/3
                if self.statuses.get(MonsterStatus.STRENGTH) < 0:
                    self.statuses.set(MonsterStatus.STRENGTH, 0)
                self.statuses.add(MonsterStatus.STRENGTH, 2)
                buff_count = bc.turn // 3
                if buff_count == 1:
                    self.statuses.add(MonsterStatus.ARTIFACT, 2)
                elif buff_count == 2:
                    self.statuses.add(MonsterStatus.BEAT_OF_DEATH, 1)
                elif buff_count == 3:
                    self.statuses.add(MonsterStatus.PAINFUL_STABS, 1)
                elif buff_count == 4:
                    self.statuses.add(MonsterStatus.STRENGTH, 10)
                else:
                    self.statuses.add(MonsterStatus.STRENGTH, 50)
                bc.log.append(f"{self.display_name} 使用 增强(Buff)（第 {buff_count} 次）！")
                self.roll_move(bc)
            case _:
                raise AssertionError(f"未知招式 {move}")
        self.turns_taken += 1


# ---- 红面具帮（Masked Bandits 事件专属，MonsterSpecific.cpp:405-437/2946-2958）----


class Pointy(Monster):
    """尖刺（红面具帮三当家的）：固定 5×2 段攻击（A2 起 6×2），无 roll。

    lightspeed MonsterIds.h monsterHpRange：30 固定（A7+ 34）。
    """

    name = "Pointy"
    zh = "尖尖"
    hp_range = (30, 30)

    ATTACK = MoveDef("Attack", "戳刺", "attack", base_damage=5)  # ×2 段

    def __init__(self, idx: int, hp: int, max_hp: int):
        super().__init__(idx, hp, max_hp, "尖尖(Pointy)")
        if hp > 30:  # A7+ 段伤害提升
            self.ATTACK = MoveDef("Attack", "戳刺", "attack", base_damage=6)

    @classmethod
    def create(cls, bc: BattleContext, idx: int) -> "Pointy":
        asc = bc.ascension
        hp = 34 if asc >= 7 else 30
        return cls(idx, hp, hp)

    def get_move_for_roll(self, bc: BattleContext, roll: int) -> MoveDef:
        return self.ATTACK

    def take_turn(self, bc: BattleContext) -> None:
        dmg = bc.calculate_monster_damage(self, 6 if bc.ascension >= 2 else 5)
        bc.log.append(f"{self.display_name} 使用 戳刺(Attack)。")
        for _ in range(2):
            bc.add_to_bot(Actions.attack_player(self.idx, dmg))
        bc.add_to_bot(Actions.no_op_roll_move())
        self.turns_taken += 1


class Romeo(Monster):
    """罗密欧（红面具帮二当家的）：首回合嘲讽（无效果），此后痛苦斩与
    十字斩交替。HP 35-39（A7+ 37-41）。

    痛苦斩 10 伤 + 2 层虚弱（A17: 3）；十字斩 15 伤（A2: 17）。
    """

    name = "Romeo"
    zh = "罗密欧"
    hp_range = (35, 39)

    MOCK = MoveDef("Mock", "嘲讽", "unknown", intent_text="（无效果）")
    AGONIZING_SLASH = MoveDef("Agonizing Slash", "痛苦斩", "attack", base_damage=10)
    CROSS_SLASH = MoveDef("Cross Slash", "十字斩", "attack", base_damage=15)

    def __init__(self, idx: int, hp: int, max_hp: int):
        super().__init__(idx, hp, max_hp, "罗密欧(Romeo)")

    @classmethod
    def create(cls, bc: BattleContext, idx: int) -> "Romeo":
        hp = bc.rngs.monster_hp.int_inclusive(*(37, 41) if bc.ascension >= 7 else (35, 39))
        return cls(idx, hp, hp)

    def get_move_for_roll(self, bc: BattleContext, roll: int) -> MoveDef:
        if self.turns_taken == 0:
            return self.MOCK
        return self.AGONIZING_SLASH

    def take_turn(self, bc: BattleContext) -> None:
        asc = bc.ascension
        move = self.move_history[0]
        match move.name:
            case "Mock":
                bc.log.append(f"{self.display_name} 使用 嘲讽(Mock)。")
                self.set_move(self.AGONIZING_SLASH)
            case "Agonizing Slash":
                dmg = bc.calculate_monster_damage(self, 10)
                weak = 3 if asc >= 17 else 2
                bc.log.append(f"{self.display_name} 使用 痛苦斩(Agonizing Slash)。")
                bc.add_to_bot(Actions.attack_player(self.idx, dmg))
                bc.add_to_bot(Actions.debuff_player(PlayerStatus.WEAK, weak, True))
                self.set_move(self.CROSS_SLASH)
            case "Cross Slash":
                dmg = bc.calculate_monster_damage(self, 17 if asc >= 2 else 15)
                bc.log.append(f"{self.display_name} 使用 十字斩(Cross Slash)。")
                bc.add_to_bot(Actions.attack_player(self.idx, dmg))
                self.set_move(self.AGONIZING_SLASH)
            case _:
                raise AssertionError(f"未知招式 {move}")
        bc.add_to_bot(Actions.no_op_roll_move())
        self.turns_taken += 1


class Bear(Monster):
    """大熊（红面具帮大当家的）：熊抱（敏捷 -2/A17 -4）→ 突袭（9 伤+9 格挡，
    A2: 10）→ 撕裂（18 伤，A2: 20）→ 突袭↔撕裂循环。HP 38-52（A7+ 40-44）。
    """

    name = "Bear"
    zh = "熊"
    # wiki：38-42（lightspeed 表 {{38,52}} 系其笔误——wiki/官方数据 38-42，wiki 比照修正）
    hp_range = (38, 42)

    BEAR_HUG = MoveDef("Bear Hug", "熊抱", "debuff", intent_text="敏捷 -2")
    LUNGE = MoveDef("Lunge", "突袭", "attack", base_damage=9)
    MAUL = MoveDef("Maul", "撕裂", "attack", base_damage=18)

    def __init__(self, idx: int, hp: int, max_hp: int):
        super().__init__(idx, hp, max_hp, "熊(Bear)")

    @classmethod
    def create(cls, bc: BattleContext, idx: int) -> "Bear":
        hp = bc.rngs.monster_hp.int_inclusive(*(40, 44) if bc.ascension >= 7 else (38, 42))
        return cls(idx, hp, hp)

    def get_move_for_roll(self, bc: BattleContext, roll: int) -> MoveDef:
        if self.turns_taken == 0:
            return self.BEAR_HUG
        return self.LUNGE

    def take_turn(self, bc: BattleContext) -> None:
        asc = bc.ascension
        move = self.move_history[0]
        match move.name:
            case "Bear Hug":
                dex_loss = 4 if asc >= 17 else 2
                bc.log.append(f"{self.display_name} 使用 熊抱(Bear Hug)，敏捷 -{dex_loss}。")
                bc.add_to_bot(Actions.debuff_player(PlayerStatus.DEXTERITY, -dex_loss, True))
                self.set_move(self.LUNGE)
            case "Lunge":
                dmg = bc.calculate_monster_damage(self, 10 if asc >= 2 else 9)
                bc.log.append(f"{self.display_name} 使用 突袭(Lunge)。")
                bc.add_to_bot(Actions.attack_player(self.idx, dmg))
                bc.add_to_bot(Actions.monster_gain_block(self.idx, 9))
                self.set_move(self.MAUL)
            case "Maul":
                dmg = bc.calculate_monster_damage(self, 20 if asc >= 2 else 18)
                bc.log.append(f"{self.display_name} 使用 撕裂(Maul)。")
                bc.add_to_bot(Actions.attack_player(self.idx, dmg))
                self.set_move(self.LUNGE)
            case _:
                raise AssertionError(f"未知招式 {move}")
        bc.add_to_bot(Actions.no_op_roll_move())
        self.turns_taken += 1


class ApologySlime(Monster):
    """道歉史莱姆：本体的遭遇加载失败兜底怪（MonsterHelper.getEncounter
    default 分支；开场台词 "Aw, something went wrong... please let the
    devs know!" 即其身份注释）。

    ApologySlime.java：HP 8-12（无进阶分支），Tackle 3 伤（无 A2 加伤），
    Lick 无——debuff 招为 1 层虚弱（WeakPower(1, true)）。getMove 用
    aiRng.randomBoolean() 50/50 定首招，roll 参数不用；此后 take_turn
    setMove 严格交替（TACKLE→DEBUFF→TACKLE，无 RollMoveAction）。
    为覆盖完整性移植；正常遭遇表不引用（模拟器对未知遭遇直接抛
    ValueError，对应本体"不该走到这里"的语义）。
    """

    name = "Apology Slime"
    zh = "抱歉史莱姆"
    hp_range = (8, 12)

    TACKLE = MoveDef("Tackle", "冲撞", "attack", base_damage=3)
    DEBUFF = MoveDef("Debuff", "道歉虚弱", "debuff", intent_text="施加 1 层虚弱")

    def __init__(self, idx: int, hp: int, max_hp: int):
        super().__init__(idx, hp, max_hp, "抱歉史莱姆(Apology Slime)")

    @classmethod
    def create(cls, bc: BattleContext, idx: int) -> "ApologySlime":
        hp = _roll_hp(bc, cls)
        return cls(idx, hp, hp)

    def get_move_for_roll(self, bc: BattleContext, roll: int) -> MoveDef:
        # 50/50 抽首招（对齐 getMove 的 randomBoolean；roll 参数不参与）
        return self.TACKLE if _ai_boolean(bc, 0.5) else self.DEBUFF

    def take_turn(self, bc: BattleContext) -> None:
        move = self.move_history[0]
        match move.name:
            case "Tackle":
                dmg = bc.calculate_monster_damage(self, 3)
                bc.log.append(f"{self.display_name} 使用 冲撞(Tackle)。")
                bc.add_to_bot(Actions.attack_player(self.idx, dmg))
                self.set_move(self.DEBUFF)
            case "Debuff":
                bc.log.append(f"{self.display_name} 使用 道歉虚弱(Debuff)。")
                bc.add_to_bot(Actions.debuff_player(PlayerStatus.WEAK, 1, True))
                self.set_move(self.TACKLE)
            case _:
                raise AssertionError(f"未知招式 {move}")
        self.turns_taken += 1

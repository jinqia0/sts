"""Defect（故障）职业全卡移植：wiki 口径 75 张（4 基础 + 18 普通 + 36 非普通
+ 17 稀有），无生成卡（Void 状态卡已在 status.py，Burn 亦然）。

权威源（lightspeed 的 C++ switch 未实现任何 Defect 卡效果——BattleContext.cpp
全卡 switch 无一个 Defect case，仅 GENETIC_ALGORITHM 有被注释的残留）：
- 数值/结算文本/费用/升级：slaythespire.wiki.gg 逐卡页（A0 基准，wiki 口径）
- 数据位交叉校验：sts_lightspeed Cards.h（doesCardExhaust / isCardInnate /
  isXCost / doesCardSelfRetain / cardRarities）。注意三处 Cards.h 数据错误
  以 wiki 为准：① cardColors 把 BRILLIANCE/COLLECT/STACK 标 BLUE、BUFFER 标
  PURPLE（数组错位）；② getEnergyCost 对未列名 Defect 卡一律回落 1（Blizzard/
  Hyperbeam/Meteor Strike 等均与 wiki 不符）；③ getUpgradedCost 无独立表。
  Cards.h 与 wiki 吻合的数据位：BOOT_SEQUENCE 固有+消耗 / CHILL·HELLO_WORLD·
  STORM·MACHINE_LEARNING 升级后固有 / BOOT_SEQUENCE·CHILL·DOUBLE_ENERGY·
  GENETIC_ALGORITHM·TEMPEST·WHITE_NOISE·CORE_SURGE·FISSION·REBOOT·SEEK 消耗 /
  HOLOGRAM·RAINBOW 仅基础版消耗 / TEMPEST·MULTI_CAST·REINFORCED_BODY X 费 /
  ECHO_FORM 仅基础版虚无。
- 状态结算语义参照：lightspeed 的 REBOUND（BattleContext.cpp:1975-1985 +
  Player.cpp:416-417 回合末移除）与 BIAS（Player.cpp:577-578 回合开始
  FOCUS -层数）有实现可对齐；其余按 wiki。

引擎接线状态（本模块 play 落状态/槽位即可全流程生效）：
- 已接可用：充能球全套（channel/evoke/passive/槽位/FOCUS/ELECTRO/STATIC_
  DISCHARGE 基础版/LOOP-FROST）、EQUILIBRIUM（回合末保留手牌）、special
  ["next_turn_energy"]（Charge Battery）、DRAW_REDUCTION 负层 = 每回合多抽
  （Machine Learning，引擎 draw_cards 的 count -= 层语义天然支持负值）、
  CARD_SELECT（Seek/Recycle/Hologram）、X 费能量快照、ARTIFACT。
- 槽位落地 + 引擎接线需求（逐项见迁移报告）：
  * special["chan_lightning"]/["chan_frost"]：本场累计引导计数（Blizzard/
    Thunder Strike 读）。内容层 _channel 助手已计数，但引擎驱动路径
    （STATIC_DISCHARGE 受击引导、遗物 Cracked Core 等）不经助手 → 少计，
    引擎应在 Player.channel_orb 内统一计数。
  * REBOUND 状态：触发段需引擎接 use_card 收尾（对齐 C++ onAfterUseCard
    的 REBOUND 分支：==1 时该牌置抽牌堆顶并移除状态；>1 时减到 1）+ 回合末
    移除（Player.cpp:416-417）。本模块按异步时序置 1（play 入队落状态时
    Rebound 自身已落弃牌堆，不会被自身回弹）。
  * LOCK_ON（Bullseye）：受球伤害 ×1.5 的乘区缺（引擎 evoke/passive 的
    damage_enemy 路径无 LOCK_ON 判定；衰减已有 Monster.cpp:83-84 对应物）。
  * special["bias_focus"]（Biased Cognition）：每回合开始 FOCUS -1×层
    （C++ BIAS 状态的对应物，新状态枚举待引擎加）。
  * special["hello_world"]/["creative_ai"]：回合开始随机生成牌入手。
  * special["storm"]/["heatsinks"]：打出能力牌时引导闪电/抽牌（on_use_
    power_card 无内容钩子）。
  * special["amplify"]：本回合下 N 张能力牌双发。
  * special["echo_form"]：每回合首张牌双发（C++ echoFormCardsDoubled 位）。
  * special["buffer"]：抵挡 N 次 HP 损失（新 BUFFER 状态待引擎加）。
  * special["self_repair"]：战斗结束回血（战斗结束无内容钩子）。
- 引擎已知偏差（wiki vs 现实现，迁移报告）：
  * STATIC_DISCHARGE：引擎每次受击恒引导 1 个（不读层数，升级版 2 层少计）；
    且在格挡完全吸收时也触发（wiki：仅未格挡攻击伤害触发）。
  * LOOP：引擎回合开始仅对 orbs[0] 为 FROST 的额外 passive 生效（LIGHTNING
    伤/DARK 存层缺）。
  * Consume 移除球位时最老球直接移除不唤起（wiki 口径已按此实现，无偏差）。

与包结构的关系：本文件为 Defect 卡唯一正式定义，经包 __init__
eager re-export 暴露；CardDef 取自 _base.py，BURN/VOID/_strike_play/
_defend_play 复用自 ironclad.py。STRIKE_D/DEFEND_D 沿用卡名
"Strike"/"Defend"（CARD_INDEX 按名去重，观测层无冲突）。
"""

from __future__ import annotations

import re
import sys
from typing import TYPE_CHECKING

from sts.combat.actions import Actions
from sts.combat.card_manager import MAX_HAND_SIZE
from sts.combat.queue import Action
from sts.combat.types import MonsterStatus, Orb, Outcome, PlayerStatus

from sts.content.cards._base import CardDef, _defend_play, _strike_play
from sts.content.cards.status import BURN, VOID

if TYPE_CHECKING:
    from sts.combat.battle import BattleContext
    from sts.combat.card_manager import CardInstance
    from sts.combat.queue import CardQueueItem


# ============================================================
# 公共设施
# ============================================================


def _channel(orb: Orb) -> Action:
    """引导充能球（内容层统一入口）：引擎 channel_orb 结算 + 本场累计引导计数
    （Blizzard 读 chan_frost、Thunder Strike 读 chan_lightning）。

    引擎驱动的引导（STATIC_DISCHARGE 受击、Cracked Core 类遗物）不经本入口
    → 计数少计，引擎接线需求见模块注释。满槽唤起最老的球由引擎自理。"""

    def run(bc: BattleContext) -> None:
        key = f"chan_{orb.name.lower()}"
        bc.player.special[key] = bc.player.special.get(key, 0) + 1
        bc.player.channel_orb(bc, orb)

    return Action(run)


def _add_to_hand(bc: BattleContext, inst: CardInstance) -> None:
    """加牌入手；手满落弃牌堆（对齐 moveToHandHelper，上限 10）。"""
    if len(bc.cards.hand) < MAX_HAND_SIZE:
        bc.cards.hand.append(inst)
    else:
        bc.cards.move_to_discard_pile(inst)


_CTYPE_CACHE: dict[str, str] | None = None


def _ctype_by_name() -> dict[str, str]:
    """卡名 → 类型（全内容模块扫描，惰性缓存；同名跨职业卡类型一致）。"""
    global _CTYPE_CACHE
    if _CTYPE_CACHE is None:
        import sts.content.cards.ironclad as _c
        import sts.content.cards.colorless as _cl
        import sts.content.cards.curses as _cu
        import sts.content.cards.silent as _s
        import sts.content.cards.watcher as _w

        cache: dict[str, str] = {}
        for mod in (_c, _cu, _cl, _s, _w, sys.modules[__name__]):
            for g in vars(mod).values():
                if isinstance(g, CardDef):
                    cache.setdefault(g.name, g.ctype)
        _CTYPE_CACHE = cache
    return _CTYPE_CACHE


_PLAYED_PAT = re.compile(r"^你打出 .+\(([^()]+)\)。$")


def _powers_played_count(bc: BattleContext) -> int:
    """本场已打出的能力牌数（Force Field 动态费用读）。

    引擎无 powers_played_this_combat 计数位——按战斗日志解析近似（use_card
    对每次打出（含 Double Tap 重放/Mayhem 自动播放）都先记日志，语义完备；
    Watcher 批次"上一张打出的牌"同款手法）。"""
    ctypes = _ctype_by_name()
    return sum(1 for line in bc.log
               if (m := _PLAYED_PAT.match(line)) and ctypes.get(m.group(1)) == "Power")


def _random_orb(bc: BattleContext) -> Orb:
    """随机球种（Chaos；misc 流，DESIGN.md §3 分布级等价）。"""
    return Orb(bc.rngs.misc.int_inclusive(0, len(Orb) - 1))


def _defect_pool(ctype: str, exclude: tuple = ()) -> list:
    """本职业卡池扫描（White Noise 的随机能力 / Hello World 的随机普通牌 /
    Creative AI 的随机能力）：排除不可生成卡（Self Repair 治疗，wiki
    Neutral 节）。后续新增卡自动入池。"""
    return [g for g in vars(sys.modules[__name__]).values()
            if isinstance(g, CardDef) and g.ctype == ctype and g not in exclude]


def _add_special(key: str, n: int) -> Action:
    """special 槽位累加（接线需求见模块注释）。"""
    return Action(lambda bc: bc.player.special.update(
        **{key: bc.player.special.get(key, 0) + n}))


def _evoke_times(n: int) -> Action:
    """唤起最老的充能球 n 次（Dualcast 2 次 / Multi-Cast X 次；无球空转）。"""
    return Action(lambda bc: [bc.player.evoke_orb(bc) for _ in range(n)])


# ============================================================
# 基础 4 张
# ============================================================

STRIKE_D = CardDef("Strike", "打击", 1, "Attack", "造成 6 点伤害。（升级 9 点）",
                   True, False, _strike_play)
DEFEND_D = CardDef("Defend", "防御", 1, "Skill", "获得 5 点格挡。（升级 8 点）",
                   False, False, _defend_play)


def _zap_play(bc: BattleContext, item: CardQueueItem) -> None:
    # wiki：引导 1 个闪电球（升级费用 1→0）
    bc.add_to_bot(_channel(Orb.LIGHTNING))


def _dualcast_play(bc: BattleContext, item: CardQueueItem) -> None:
    # wiki：唤起下一个球 2 次（升级费用 1→0）。第二次唤起的是（可能的）新最老球
    bc.add_to_bot(_evoke_times(2))


ZAP = CardDef("Zap", "电击", 1, "Skill", "引导 1 个闪电球。（升级费用 0）",
              False, False, _zap_play, upgraded_cost=0)
DUALCAST = CardDef("Dualcast", "双重施法", 1, "Skill", "唤起你的下一个球 2 次。（升级费用 0）",
                   False, False, _dualcast_play, upgraded_cost=0)


# ============================================================
# 普通 18 张
# ============================================================


def _ball_lightning_play(bc: BattleContext, item: CardQueueItem) -> None:
    # wiki：造成 7（10）伤，引导 1 闪电
    dmg = bc.calculate_card_damage(item, item.target, 10 if item.card.upgraded else 7)
    bc.add_to_bot(Actions.attack_enemy(item.target, dmg))
    bc.add_to_bot(_channel(Orb.LIGHTNING))


def _barrage_play(bc: BattleContext, item: CardQueueItem) -> None:
    # wiki：每有 1 个已引导的球造成 4（6）伤——单段攻击，基准 = 4×球数
    #（力量计入一次，wiki Neutral：one large hit）
    per = 6 if item.card.upgraded else 4
    dmg = bc.calculate_card_damage(item, item.target, per * len(bc.player.orbs))
    bc.add_to_bot(Actions.attack_enemy(item.target, dmg))


def _beam_cell_play(bc: BattleContext, item: CardQueueItem) -> None:
    # wiki：造成 3（4）伤，施加 1（2）层易伤
    up = item.card.upgraded
    dmg = bc.calculate_card_damage(item, item.target, 4 if up else 3)
    bc.add_to_bot(Actions.attack_enemy(item.target, dmg))
    bc.add_to_bot(Actions.debuff_enemy(item.target, MonsterStatus.VULNERABLE, 2 if up else 1, False))


def _charge_battery_play(bc: BattleContext, item: CardQueueItem) -> None:
    # wiki：获得 7（10）格挡，下回合获得 1 点能量——next_turn_energy 槽引擎
    # 已接（_recharge_energy 读后清零）
    bc.add_to_bot(Actions.gain_block(bc.calculate_card_block(10 if item.card.upgraded else 7)))
    bc.add_to_bot(_add_special("next_turn_energy", 1))


def _claw_play(bc: BattleContext, item: CardQueueItem) -> None:
    # wiki：造成 3（5）伤，本场战斗所有爪击卡伤害 +2——全局共享计数（与
    # Rampage 的单实例 misc_data 不同，Claw 是"ALL Claw cards"）
    bonus = bc.player.special.get("claw_bonus", 0)
    dmg = bc.calculate_card_damage(item, item.target, (5 if item.card.upgraded else 3) + bonus)
    bc.add_to_bot(Actions.attack_enemy(item.target, dmg))
    bc.add_to_bot(_add_special("claw_bonus", 2))


def _cold_snap_play(bc: BattleContext, item: CardQueueItem) -> None:
    # wiki：造成 6（9）伤，引导 1 冰球
    dmg = bc.calculate_card_damage(item, item.target, 9 if item.card.upgraded else 6)
    bc.add_to_bot(Actions.attack_enemy(item.target, dmg))
    bc.add_to_bot(_channel(Orb.FROST))


def _compile_driver_play(bc: BattleContext, item: CardQueueItem) -> None:
    # wiki：造成 7（10）伤，每有 1 种不同类型的球抽 1 张
    dmg = bc.calculate_card_damage(item, item.target, 10 if item.card.upgraded else 7)
    bc.add_to_bot(Actions.attack_enemy(item.target, dmg))
    bc.add_to_bot(Actions.draw_cards(len(set(bc.player.orbs))))


def _coolheaded_play(bc: BattleContext, item: CardQueueItem) -> None:
    # wiki：引导 1 冰球，抽 1（2）张
    bc.add_to_bot(_channel(Orb.FROST))
    bc.add_to_bot(Actions.draw_cards(2 if item.card.upgraded else 1))


def _go_for_the_eyes_play(bc: BattleContext, item: CardQueueItem) -> None:
    # wiki：造成 3（4）伤，若该敌人意图为攻击施加 1（2）层虚弱（执行时读
    # 意图，Spot Weakness 先例）
    up = item.card.upgraded
    dmg = bc.calculate_card_damage(item, item.target, 4 if up else 3)
    bc.add_to_bot(Actions.attack_enemy(item.target, dmg))
    t = item.target

    def run(bc2: BattleContext) -> None:
        m = bc2.monsters.monsters[t]
        if not m.is_dead_or_escaped() and m.current_move.kind == "attack":
            bc2.add_to_bot(Actions.debuff_enemy(t, MonsterStatus.WEAK, 2 if up else 1, False))

    bc.add_to_bot(Action(run))


def _hologram_play(bc: BattleContext, item: CardQueueItem) -> None:
    # wiki：获得 3（5）格挡，从弃牌堆选 1 张牌到手牌。基础版消耗（升级版不再
    # 消耗——静态位表达不了按升级分支，Limit Break 先例：play 内置
    # exhaust_on_use 覆盖）。执行时 Hologram 自身已落堆：基础版在消耗堆天然
    # 不可选；升级版在弃牌堆，按实例身份排除（本体打出的牌落堆晚于自身效果）
    up = item.card.upgraded
    bc.add_to_bot(Actions.gain_block(bc.calculate_card_block(5 if up else 3)))
    if not up:
        item.exhaust_on_use = True

    def run(bc2: BattleContext) -> None:
        cands = [c for c in list(bc2.cards.discard_pile) if c is not item.card]

        def on_choose(bc3: BattleContext, chosen: list) -> None:
            for inst in chosen:
                bc3.cards.discard_pile.remove(inst)
                _add_to_hand(bc3, inst)

        bc2.open_card_select(cands, on_choose, can_pick_zero=True,
                             prompt="全息影像：选择 1 张弃牌回到手牌")

    bc.add_to_bot(Action(run))


def _leap_play(bc: BattleContext, item: CardQueueItem) -> None:
    # wiki：获得 9（12）格挡
    bc.add_to_bot(Actions.gain_block(bc.calculate_card_block(12 if item.card.upgraded else 9)))


def _rebound_play(bc: BattleContext, item: CardQueueItem) -> None:
    # wiki：造成 9（12）伤。本回合下一张打出的牌置于抽牌堆顶。REBOUND 状态
    # 触发段需引擎接线（use_card 收尾对齐 C++ BattleContext.cpp:1975-1985 +
    # 回合末移除）；本引擎出牌时序下 play 入队落状态时 Rebound 自身已落
    # 弃牌堆（on_after_use_card 同步先行），置 1 即"下一张"生效，不会被
    # 自身回弹
    dmg = bc.calculate_card_damage(item, item.target, 12 if item.card.upgraded else 9)
    bc.add_to_bot(Actions.attack_enemy(item.target, dmg))
    bc.add_to_bot(Actions.buff_player(PlayerStatus.REBOUND, 1))


def _recursion_play(bc: BattleContext, item: CardQueueItem) -> None:
    # wiki：唤起下一个球，引导一个刚被唤起的球（副本携带积累——暗球存层随
    # 副本保留；引擎 dark_stacks 为全局池，唤起清零后按快照回填近似）
    def run(bc2: BattleContext) -> None:
        p = bc2.player
        if not p.orbs:
            return
        orb = p.orbs[0]
        saved = p.dark_stacks
        p.evoke_orb(bc2)
        bc2.add_to_bot(_channel(orb))
        if orb == Orb.DARK:
            bc2.add_to_bot(Action(lambda bc3: setattr(bc3.player, "dark_stacks", saved)))

    bc.add_to_bot(Action(run))


def _stack_play(bc: BattleContext, item: CardQueueItem) -> None:
    # wiki：获得等同弃牌堆卡数的格挡（升级 +3）。出牌时读数——此时 Stack
    # 自身尚未落弃牌堆（on_after_use_card 在动作出队前同步执行，若在动作内
    # 读会把自身计入，wiki Order 节明确不计自身），故在 play() 同步计数
    n = len(bc.cards.discard_pile) + (3 if item.card.upgraded else 0)
    bc.add_to_bot(Actions.gain_block(bc.calculate_card_block(n)))


def _steam_barrier_play(bc: BattleContext, item: CardQueueItem) -> None:
    # wiki：获得 6（8）格挡，本场战斗此牌格挡 -1（每实例独立计数，misc_data
    # 记已打次数）
    base = 8 if item.card.upgraded else 6
    n = max(0, base - item.card.misc_data)
    bc.add_to_bot(Actions.gain_block(bc.calculate_card_block(n)))
    item.card.misc_data += 1


def _streamline_play(bc: BattleContext, item: CardQueueItem) -> None:
    # wiki：造成 15（20）伤，此牌本场费用 -1（update_cost 永久改费，Blood
    # for Blood 同款 cost_override 路径）
    dmg = bc.calculate_card_damage(item, item.target, 20 if item.card.upgraded else 15)
    bc.add_to_bot(Actions.attack_enemy(item.target, dmg))
    item.card.update_cost(-1)


def _sweeping_beam_play(bc: BattleContext, item: CardQueueItem) -> None:
    # wiki：对所有敌人造成 6（9）伤，抽 1 张
    bc.add_to_bot(Actions.attack_all_enemy(9 if item.card.upgraded else 6))
    bc.add_to_bot(Actions.draw_cards(1))


def _turbo_play(bc: BattleContext, item: CardQueueItem) -> None:
    # wiki（卡名全大写 TURBO）：获得 2（3）点能量，1 张虚空加入弃牌堆
    bc.add_to_bot(Actions.gain_energy(3 if item.card.upgraded else 2))
    bc.add_to_bot(Actions.make_temp_card_in_discard(VOID))


BALL_LIGHTNING = CardDef("Ball Lightning", "球状闪电", 1, "Attack",
                          "造成 7 点伤害。引导 1 个闪电球。（升级 10 伤）", True, False,
                          _ball_lightning_play)
BARRAGE = CardDef("Barrage", "弹幕", 1, "Attack",
                  "每有 1 个已引导的球，造成 4 点伤害。（升级 6 点）", True, False,
                  _barrage_play)
BEAM_CELL = CardDef("Beam Cell", "光束牢笼", 0, "Attack",
                    "造成 3 点伤害。施加 1 层易伤。（升级 4 伤 2 层）", True, False,
                    _beam_cell_play)
CHARGE_BATTERY = CardDef("Charge Battery", "充电", 1, "Skill",
                          "获得 7 点格挡。下回合获得 1 点能量。（升级 10 格挡）", False, False,
                          _charge_battery_play)
CLAW = CardDef("Claw", "爪击", 0, "Attack",
               "造成 3 点伤害。本场战斗所有爪击卡伤害 +2。（升级 5 伤）", True, False,
               _claw_play)
COLD_SNAP = CardDef("Cold Snap", "寒流", 1, "Attack",
                    "造成 6 点伤害。引导 1 个冰球。（升级 9 伤）", True, False,
                    _cold_snap_play)
COMPILE_DRIVER = CardDef("Compile Driver", "编译驱动", 1, "Attack",
                         "造成 7 点伤害。每有 1 种不同类型的球，抽 1 张牌。（升级 10 伤）",
                         True, False, _compile_driver_play)
COOLHEADED = CardDef("Coolheaded", "冷静", 1, "Skill",
                     "引导 1 个冰球。抽 1 张牌。（升级抽 2 张）", False, False,
                     _coolheaded_play)
GO_FOR_THE_EYES = CardDef("Go for the Eyes", "直击要害", 0, "Attack",
                          "造成 3 点伤害。若该敌人意图为攻击，施加 1 层虚弱。（升级 4 伤 2 层）",
                          True, False, _go_for_the_eyes_play)
HOLOGRAM = CardDef("Hologram", "全息影像", 1, "Skill",
                   "获得 3 点格挡。从弃牌堆选 1 张牌回到手牌。消耗。（升级 5 格挡、不再消耗）",
                   False, False, _hologram_play)
LEAP = CardDef("Leap", "跃迁", 1, "Skill", "获得 9 点格挡。（升级 12 格挡）", False, False,
               _leap_play)
REBOUND = CardDef("Rebound", "回弹", 1, "Attack",
                  "造成 9 点伤害。本回合下一张打出的牌置于抽牌堆顶。（升级 12 伤）",
                  True, False, _rebound_play)
RECURSION = CardDef("Recursion", "递归", 1, "Skill",
                    "唤起你的下一个球。引导一个刚被唤起的球。（升级费用 0）", False, False,
                    _recursion_play, upgraded_cost=0)
STACK = CardDef("Stack", "堆栈", 1, "Skill",
                "获得等同弃牌堆卡数的格挡。（升级额外 +3）", False, False, _stack_play)
STEAM_BARRIER = CardDef("Steam Barrier", "蒸汽屏障", 0, "Skill",
                        "获得 6 点格挡。本场战斗此牌格挡 -1。（升级 8 格挡）", False, False,
                        _steam_barrier_play)
STREAMLINE = CardDef("Streamline", "流线化", 2, "Attack",
                     "造成 15 点伤害。此牌本场战斗费用 -1。（升级 20 伤）", True, False,
                     _streamline_play)
SWEEPING_BEAM = CardDef("Sweeping Beam", "扫射光束", 1, "Attack",
                        "对所有敌人造成 6 点伤害。抽 1 张牌。（升级 9 伤）", False, False,
                        _sweeping_beam_play)
TURBO = CardDef("TURBO", "涡轮", 0, "Skill",
                "获得 2 点能量。1 张虚空加入弃牌堆。（升级 3 点能量）", False, False,
                _turbo_play)


# ============================================================
# 非普通 36 张
# ============================================================


def _aggregate_play(bc: BattleContext, item: CardQueueItem) -> None:
    # wiki：每有 4（3）张抽牌堆的牌获得 1 点能量（向下取整）
    per = 3 if item.card.upgraded else 4
    n = len(bc.cards.draw_pile) // per
    if n > 0:
        bc.add_to_bot(Actions.gain_energy(n))


def _auto_shields_play(bc: BattleContext, item: CardQueueItem) -> None:
    # wiki：若没有格挡，获得 11（15）格挡（执行时读当前格挡）
    n = 15 if item.card.upgraded else 11

    def run(bc2: BattleContext) -> None:
        if bc2.player.block == 0:
            bc2.add_to_bot(Actions.gain_block(bc2.calculate_card_block(n)))

    bc.add_to_bot(Action(run))


def _blizzard_play(bc: BattleContext, item: CardQueueItem) -> None:
    # wiki：对所有敌人造成 2（3）倍本场引导冰球数的伤害——单段大攻击
    #（力量计入一次）
    mult = 3 if item.card.upgraded else 2
    base = mult * bc.player.special.get("chan_frost", 0)
    bc.add_to_bot(Actions.attack_all_enemy(base))


def _boot_sequence_play(bc: BattleContext, item: CardQueueItem) -> None:
    # wiki：固有。获得 10（13）格挡。消耗
    bc.add_to_bot(Actions.gain_block(bc.calculate_card_block(13 if item.card.upgraded else 10)))


def _bullseye_play(bc: BattleContext, item: CardQueueItem) -> None:
    # wiki：造成 8（11）伤，施加 2（3）层锁定。锁定乘区（受球伤害 ×1.5）
    # 引擎未接，见模块注释
    up = item.card.upgraded
    dmg = bc.calculate_card_damage(item, item.target, 11 if up else 8)
    bc.add_to_bot(Actions.attack_enemy(item.target, dmg))
    bc.add_to_bot(Actions.debuff_enemy(item.target, MonsterStatus.LOCK_ON, 3 if up else 2, False))


def _capacitor_play(bc: BattleContext, item: CardQueueItem) -> None:
    # wiki：获得 2（3）个球位（可叠、可负后抵消 Consume）
    bc.add_to_bot(Actions.modify_orb_slots(3 if item.card.upgraded else 2))


def _chaos_play(bc: BattleContext, item: CardQueueItem) -> None:
    # wiki：引导 1（2）个随机球
    for _ in range(2 if item.card.upgraded else 1):
        bc.add_to_bot(Action(lambda bc2: bc2.add_to_bot(_channel(_random_orb(bc2)))))


def _chill_play(bc: BattleContext, item: CardQueueItem) -> None:
    # wiki：每有 1 个战斗中的敌人引导 1 个冰球（打出时计数存活敌）。
    # 消耗；升级后固有
    n = sum(1 for m in bc.monsters.monsters if not m.is_dead_or_escaped())
    for _ in range(n):
        bc.add_to_bot(_channel(Orb.FROST))


def _consume_play(bc: BattleContext, item: CardQueueItem) -> None:
    # wiki：获得 2（3）专长，失去 1 个球位。若被移除的球位有球，该球直接
    # 移除（不唤起、最老位，wiki Neutral 节）
    def run(bc2: BattleContext) -> None:
        p = bc2.player
        new_slots = max(0, p.orb_slots - 1)
        if len(p.orbs) > new_slots:
            p.orbs.pop(0)
        p.orb_slots = new_slots
        p.statuses.add(PlayerStatus.FOCUS, 3 if item.card.upgraded else 2)

    bc.add_to_bot(Action(run))


def _darkness_play(bc: BattleContext, item: CardQueueItem) -> None:
    # wiki：引导 1 个暗球。升级：额外触发所有暗球的被动（各 +6 存层）
    bc.add_to_bot(_channel(Orb.DARK))
    if item.card.upgraded:

        def run(bc2: BattleContext) -> None:
            bc2.player.dark_stacks += 6 * sum(1 for o in bc2.player.orbs if o == Orb.DARK)

        bc.add_to_bot(Action(run))


def _defragment_play(bc: BattleContext, item: CardQueueItem) -> None:
    # wiki：获得 1（2）专长
    bc.add_to_bot(Actions.buff_player(PlayerStatus.FOCUS, 2 if item.card.upgraded else 1))


def _doom_and_gloom_play(bc: BattleContext, item: CardQueueItem) -> None:
    # wiki：对所有敌人造成 10（14）伤，引导 1 个暗球
    bc.add_to_bot(Actions.attack_all_enemy(14 if item.card.upgraded else 10))
    bc.add_to_bot(_channel(Orb.DARK))


def _double_energy_play(bc: BattleContext, item: CardQueueItem) -> None:
    # wiki：能量翻倍（含本次已支付的；wiki Order 例：3 能量付 1 → 2 → 4）。
    # 消耗（两版均消耗）
    bc.add_to_bot(Action(lambda bc2: setattr(
        bc2.player, "energy", bc2.player.energy * 2)))


def _equilibrium_play(bc: BattleContext, item: CardQueueItem) -> None:
    # wiki：获得 13（16）格挡，本回合保留手牌——EQUILIBRIUM 状态引擎已接
    #（回合末整手保留，回合末统一段衰减）
    bc.add_to_bot(Actions.gain_block(bc.calculate_card_block(16 if item.card.upgraded else 13)))
    bc.add_to_bot(Actions.buff_player(PlayerStatus.EQUILIBRIUM, 1))


def _ftl_play(bc: BattleContext, item: CardQueueItem) -> None:
    # wiki 卡面：造成 5（6）伤。若本回合打出的牌少于 3（4）张，抽 1 张。
    # "打出的牌"按结算 FTL 之前已打出的计（不含自身）：FTL 是本回合第 1~3
    #（升级 4）张时抽牌。cards_played_this_turn 在 use_card 内先自增（含
    # FTL 自身），故条件为 ≤ 3/4。注意 wiki Interactions 引言句（"a maximum
    # of 3 (4) cards were played before this one"）口径再宽一张（第 4/5 张
    # 仍抽），与卡面文本矛盾，按卡面文本实现，偏差记录在迁移报告
    dmg = bc.calculate_card_damage(item, item.target, 6 if item.card.upgraded else 5)
    bc.add_to_bot(Actions.attack_enemy(item.target, dmg))
    if bc.player.cards_played_this_turn <= (4 if item.card.upgraded else 3):
        bc.add_to_bot(Actions.draw_cards(1))


def _force_field_cost(bc: BattleContext, inst: CardInstance) -> int:
    # wiki：本场每打出 1 张能力牌费用 -1（4 费起步，下限 0）。计数按战斗
    # 日志解析（引擎无 powers_played_this_combat 位，见 _powers_played_count）
    return max(0, 4 - _powers_played_count(bc))


def _force_field_play(bc: BattleContext, item: CardQueueItem) -> None:
    # wiki：获得 12（16）格挡
    bc.add_to_bot(Actions.gain_block(bc.calculate_card_block(16 if item.card.upgraded else 12)))


def _fusion_play(bc: BattleContext, item: CardQueueItem) -> None:
    # wiki：引导 1 个等离子球（升级费用 2→1）
    bc.add_to_bot(_channel(Orb.PLASMA))


def _genetic_algorithm_play(bc: BattleContext, item: CardQueueItem) -> None:
    # wiki：获得 1 点格挡，永久增加此牌格挡 2（3）。消耗。战斗中永久计数走
    # 实例 misc_data（Rampage 同款；Double Tap 重放共享本实例 → 重放读首次
    # 增量后的值，wiki/Echo Form 节确认此为本体行为）
    n = item.card.misc_data
    bc.add_to_bot(Actions.gain_block(bc.calculate_card_block(1 + n)))
    item.card.misc_data += 3 if item.card.upgraded else 2


def _glacier_play(bc: BattleContext, item: CardQueueItem) -> None:
    # wiki：获得 7（10）格挡，引导 2 个冰球
    bc.add_to_bot(Actions.gain_block(bc.calculate_card_block(10 if item.card.upgraded else 7)))
    bc.add_to_bot(_channel(Orb.FROST))
    bc.add_to_bot(_channel(Orb.FROST))


def _heatsinks_play(bc: BattleContext, item: CardQueueItem) -> None:
    # wiki：每打出 1 张能力牌抽 1（2）张——on_use_power_card 无内容钩子，
    # special["heatsinks"] 落槽，接线需求见模块注释
    bc.add_to_bot(_add_special("heatsinks", 2 if item.card.upgraded else 1))


def _hello_world_play(bc: BattleContext, item: CardQueueItem) -> None:
    # wiki：每回合开始加 1 张随机普通牌到手牌（升级后固有）——回合开始生成
    # 无内容钩子，special["hello_world"] 落槽（层数 × 张数），接线需求见模块注释
    bc.add_to_bot(_add_special("hello_world", 1))


def _loop_play(bc: BattleContext, item: CardQueueItem) -> None:
    # wiki：回合开始时下一个球的被动额外触发 1（2）次——LOOP 状态引擎已接
    #（当前仅 FROST 分支，LIGHTNING/DARK 缺，见模块注释）
    bc.add_to_bot(Actions.buff_player(PlayerStatus.LOOP, 2 if item.card.upgraded else 1))


def _melter_play(bc: BattleContext, item: CardQueueItem) -> None:
    # wiki：移除敌人全部格挡，造成 10（14）伤（先移除后结算）
    t = item.target
    dmg = bc.calculate_card_damage(item, t, 14 if item.card.upgraded else 10)

    def run(bc2: BattleContext) -> None:
        m = bc2.monsters.monsters[t]
        if not m.is_dead_or_escaped():
            m.block = 0
            m.attacked(bc2, dmg)
            bc2.check_combat()

    bc.add_to_bot(Action(run))


def _overclock_play(bc: BattleContext, item: CardQueueItem) -> None:
    # wiki：抽 2（3）张牌，1 张灼伤加入弃牌堆（先抽后洗入——wiki Order 节）
    bc.add_to_bot(Actions.draw_cards(3 if item.card.upgraded else 2))
    bc.add_to_bot(Actions.make_temp_card_in_discard(BURN))


def _recycle_play(bc: BattleContext, item: CardQueueItem) -> None:
    # wiki：消耗 1 张手牌，获得等同其费用的能量（升级费用 1→0）。选卡消耗走
    # 内容层统一路径（触发 FNP/Dark Embrace/Sentinel）
    def run(bc2: BattleContext) -> None:
        cands = list(bc2.cards.hand)

        def on_choose(bc3: BattleContext, chosen: list) -> None:
            for inst in chosen:
                bc3.add_to_bot(Actions.gain_energy(inst.cost))
                bc3.add_to_bot(Actions.exhaust_hand_card(inst))

        bc2.open_card_select(cands, on_choose,
                             prompt="回收：选择 1 张手牌消耗并获得等同费用的能量")

    bc.add_to_bot(Action(run))


def _reinforced_body_play(bc: BattleContext, item: CardQueueItem) -> None:
    # wiki X 费：获得 7（9）格挡 X 次（每次独立走 gain_block：NO_BLOCK 拦截 +
    # JUGGERNAUT 触发；敏捷经 calculate_card_block 计入一次 × X 次 = 受益 X 次）
    per = bc.calculate_card_block(9 if item.card.upgraded else 7)
    times = max(item.energy_on_use, 0)

    def run(bc2: BattleContext) -> None:
        for _ in range(times):
            bc2.player.gain_block(bc2, per)

    bc.add_to_bot(Action(run))


def _reprogram_play(bc: BattleContext, item: CardQueueItem) -> None:
    # wiki：失去 1（2）专长，获得 1（2）力量与 1（2）敏捷
    n = 2 if item.card.upgraded else 1
    bc.add_to_bot(Actions.debuff_player(PlayerStatus.FOCUS, -n, False))
    bc.add_to_bot(Actions.buff_player(PlayerStatus.STRENGTH, n))
    bc.add_to_bot(Actions.buff_player(PlayerStatus.DEXTERITY, n))


def _rip_and_tear_play(bc: BattleContext, item: CardQueueItem) -> None:
    # wiki：对随机敌人造成 7（9）伤 2 次（每段独立随机目标 + 独立走攻击管线）
    bc.add_to_bot(Actions.attack_random_enemy(9 if item.card.upgraded else 7, 2))


def _scrape_play(bc: BattleContext, item: CardQueueItem) -> None:
    # wiki：造成 7（10）伤，抽 4（5）张，弃置其中所有非 0 费牌（"costs 0
    # upon being drawn"按抽到时的当前费用判定；X 费（-1）与无具体费用的
    # 状态/诅咒牌一律弃——wiki Neutral 节，按类型排除本引擎 0 费的 VOID/BURN）
    up = item.card.upgraded
    dmg = bc.calculate_card_damage(item, item.target, 10 if up else 7)
    bc.add_to_bot(Actions.attack_enemy(item.target, dmg))

    def run(bc2: BattleContext) -> None:
        pre = {id(c) for c in bc2.cards.hand}
        bc2.draw_cards(5 if up else 4)
        drawn = [c for c in list(bc2.cards.hand) if id(c) not in pre]
        for inst in drawn:
            if inst.cost != 0 or inst.card.ctype in ("Status", "Curse"):
                bc2.manual_discard(inst)

    bc.add_to_bot(Action(run))


def _self_repair_play(bc: BattleContext, item: CardQueueItem) -> None:
    # wiki：战斗结束时回复 7（10）HP——战斗结束无内容钩子，
    # special["self_repair"] 落槽（可叠），接线需求见模块注释
    bc.add_to_bot(_add_special("self_repair", 10 if item.card.upgraded else 7))


def _skim_play(bc: BattleContext, item: CardQueueItem) -> None:
    # wiki：抽 3（4）张牌（无弃牌段）
    bc.add_to_bot(Actions.draw_cards(4 if item.card.upgraded else 3))


def _static_discharge_play(bc: BattleContext, item: CardQueueItem) -> None:
    # wiki：每次受到未格挡的攻击伤害时引导 1（2）个闪电球——引擎已接
    # STATIC_DISCHARGE（受击引导），已知偏差：恒引导 1 个不读层数、格挡
    # 吸收时也触发，见模块注释
    bc.add_to_bot(Actions.buff_player(PlayerStatus.STATIC_DISCHARGE, 2 if item.card.upgraded else 1))


def _storm_play(bc: BattleContext, item: CardQueueItem) -> None:
    # wiki：每打出 1 张能力牌引导 1 个闪电球（升级后固有）——on_use_power_card
    # 无内容钩子，special["storm"] 落槽，接线需求见模块注释
    bc.add_to_bot(_add_special("storm", 1))


def _sunder_play(bc: BattleContext, item: CardQueueItem) -> None:
    # wiki：造成 24（32）伤，若击杀敌人获得 3 点能量
    t = item.target
    dmg = bc.calculate_card_damage(item, t, 32 if item.card.upgraded else 24)

    def run(bc2: BattleContext) -> None:
        m = bc2.monsters.monsters[t]
        if m.is_dead_or_escaped():
            return
        m.attacked(bc2, dmg)
        bc2.check_combat()
        if not m.alive and bc2.outcome == Outcome.UNDECIDED:
            bc2.add_to_bot(Actions.gain_energy(3))

    bc.add_to_bot(Action(run))


def _tempest_play(bc: BattleContext, item: CardQueueItem) -> None:
    # wiki X 费：引导 X（X+1）个闪电球。消耗
    times = max(item.energy_on_use, 0) + (1 if item.card.upgraded else 0)
    for _ in range(times):
        bc.add_to_bot(_channel(Orb.LIGHTNING))


def _white_noise_play(bc: BattleContext, item: CardQueueItem) -> None:
    # wiki：加 1 张随机能力牌到手牌，本回合费用 0。消耗（升级费用 1→0）。
    # 池 = 本职业技能牌，排除 Self Repair（治疗卡不可生成，wiki Neutral 节）

    def run(bc2: BattleContext) -> None:
        pool = _defect_pool("Power", exclude=(SELF_REPAIR,))
        card = pool[bc2.rngs.misc.int_inclusive(0, len(pool) - 1)]
        inst = bc2.cards.instantiate(card)
        inst.cost_for_turn = 0
        _add_to_hand(bc2, inst)

    bc.add_to_bot(Action(run))


AGGREGATE = CardDef("Aggregate", "聚合", 1, "Skill",
                    "每有 4 张抽牌堆的牌，获得 1 点能量。（升级每 3 张）", False, False,
                    _aggregate_play)
AUTO_SHIELDS = CardDef("Auto-Shields", "自动护盾", 1, "Skill",
                       "若没有格挡，获得 11 点格挡。（升级 15 格挡）", False, False,
                       _auto_shields_play)
BLIZZARD = CardDef("Blizzard", "暴风雪", 1, "Attack",
                   "对所有敌人造成 2 倍本场引导冰球数的伤害。（升级 3 倍）", False, False,
                   _blizzard_play)
BOOT_SEQUENCE = CardDef("Boot Sequence", "启动序列", 0, "Skill",
                        "固有。获得 10 点格挡。消耗。（升级 13 格挡）", False, True,
                        _boot_sequence_play, innate=True)
BULLSEYE = CardDef("Bullseye", "正中靶心", 1, "Attack",
                   "造成 8 点伤害。施加 2 层锁定。（升级 11 伤 3 层）", True, False,
                   _bullseye_play)
CAPACITOR = CardDef("Capacitor", "电容器", 1, "Power",
                    "获得 2 个球位。（升级 3 个）", False, False, _capacitor_play)
CHAOS = CardDef("Chaos", "混沌", 1, "Skill",
                "引导 1 个随机球。（升级 2 个）", False, False, _chaos_play)
CHILL = CardDef("Chill", "寒意", 0, "Skill",
                "每有 1 个战斗中的敌人，引导 1 个冰球。消耗。（升级后固有）", False, True,
                _chill_play, innate_when_upgraded=True)
CONSUME = CardDef("Consume", "消耗", 2, "Skill",
                  "获得 2 点专长。失去 1 个球位。（升级 3 点专长）", False, False,
                  _consume_play)
DARKNESS = CardDef("Darkness", "黑暗", 1, "Skill",
                   "引导 1 个暗球。（升级：额外触发所有暗球的被动）", False, False,
                   _darkness_play)
DEFRAGMENT = CardDef("Defragment", "碎片整理", 1, "Power",
                     "获得 1 点专长。（升级 2 点）", False, False, _defragment_play)
DOOM_AND_GLOOM = CardDef("Doom and Gloom", "阴郁末日", 2, "Attack",
                         "对所有敌人造成 10 点伤害。引导 1 个暗球。（升级 14 伤）",
                         False, False, _doom_and_gloom_play)
DOUBLE_ENERGY = CardDef("Double Energy", "能量倍增", 1, "Skill",
                        "能量翻倍。消耗。（升级费用 0）", False, True, _double_energy_play,
                        upgraded_cost=0)
EQUILIBRIUM = CardDef("Equilibrium", "平衡", 2, "Skill",
                      "获得 13 点格挡。本回合保留手牌。（升级 16 格挡）", False, False,
                      _equilibrium_play)
FTL = CardDef("FTL", "超光速", 0, "Attack",
              "造成 5 点伤害。若本回合打出的牌少于 3 张，抽 1 张。（升级 6 伤、4 张）",
              True, False, _ftl_play)
FORCE_FIELD = CardDef("Force Field", "力场", 4, "Skill",
                      "本场每打出 1 张能力牌，费用 -1。获得 12 点格挡。（升级 16 格挡）",
                      False, False, _force_field_play, dynamic_cost=_force_field_cost)
FUSION = CardDef("Fusion", "聚变", 2, "Skill",
                 "引导 1 个等离子球。（升级费用 1）", False, False, _fusion_play,
                 upgraded_cost=1)
GENETIC_ALGORITHM = CardDef("Genetic Algorithm", "遗传算法", 1, "Skill",
                            "获得 1 点格挡。永久增加此牌格挡 2 点。消耗。（升级 +3）",
                            False, True, _genetic_algorithm_play)
GLACIER = CardDef("Glacier", "冰川", 2, "Skill",
                  "获得 7 点格挡。引导 2 个冰球。（升级 10 格挡）", False, False,
                  _glacier_play)
HEATSINKS = CardDef("Heatsinks", "散热器", 1, "Power",
                    "每打出 1 张能力牌，抽 1 张牌。（升级 2 张；special 槽位，接线见报告）",
                    False, False, _heatsinks_play)
HELLO_WORLD = CardDef("Hello World", "你好世界", 1, "Power",
                      "每回合开始加 1 张随机普通牌到手牌。（升级后固有；"
                      "special 槽位，接线见报告）", False, False, _hello_world_play,
                      innate_when_upgraded=True)
LOOP = CardDef("Loop", "循环", 1, "Power",
               "回合开始时，下一个球的被动额外触发 1 次。（升级 2 次）", False, False,
               _loop_play)
MELTER = CardDef("Melter", "熔毁", 1, "Attack",
                 "移除敌人全部格挡，造成 10 点伤害。（升级 14 伤）", True, False,
                 _melter_play)
OVERCLOCK = CardDef("Overclock", "超频", 0, "Skill",
                    "抽 2 张牌。1 张灼伤加入弃牌堆。（升级抽 3 张）", False, False,
                    _overclock_play)
RECYCLE = CardDef("Recycle", "回收", 1, "Skill",
                  "消耗 1 张手牌，获得等同其费用的能量。（升级费用 0）", False, False,
                  _recycle_play, upgraded_cost=0)
REINFORCED_BODY = CardDef("Reinforced Body", "强化机体", -1, "Skill",
                          "X 费：获得 7 点格挡 X 次。（升级 9 点）", False, False,
                          _reinforced_body_play, x_cost=True)
REPROGRAM = CardDef("Reprogram", "重编程序", 1, "Skill",
                    "失去 1 点专长。获得 1 点力量和 1 点敏捷。（升级各 2 点）",
                    False, False, _reprogram_play)
RIP_AND_TEAR = CardDef("Rip and Tear", "撕裂", 1, "Attack",
                       "对随机敌人造成 7 点伤害 2 次。（升级 9 伤）", False, False,
                       _rip_and_tear_play)
SCRAPE = CardDef("Scrape", "刮削", 1, "Attack",
                 "造成 7 点伤害。抽 4 张牌，弃置其中所有非 0 费牌。（升级 10 伤、抽 5 张）",
                 True, False, _scrape_play)
SELF_REPAIR = CardDef("Self Repair", "自我修复", 1, "Power",
                      "战斗结束时回复 7 点 HP。（升级 10 点；special 槽位，接线见报告）",
                      False, False, _self_repair_play)
SKIM = CardDef("Skim", "略读", 1, "Skill", "抽 3 张牌。（升级 4 张）", False, False,
               _skim_play)
STATIC_DISCHARGE = CardDef("Static Discharge", "静电释放", 1, "Power",
                           "每次受到未格挡的攻击伤害时，引导 1 个闪电球。（升级 2 个）",
                           False, False, _static_discharge_play)
STORM = CardDef("Storm", "风暴", 1, "Power",
                "每打出 1 张能力牌，引导 1 个闪电球。（升级后固有；"
                "special 槽位，接线见报告）", False, False, _storm_play,
                innate_when_upgraded=True)
SUNDER = CardDef("Sunder", "撕裂打击", 3, "Attack",
                 "造成 24 点伤害。若击杀敌人，获得 3 点能量。（升级 32 伤）", True,
                 False, _sunder_play)
TEMPEST = CardDef("Tempest", "雷暴", -1, "Skill",
                  "X 费：引导 X 个闪电球。消耗。（升级 X+1 个）", False, True,
                  _tempest_play, x_cost=True)
WHITE_NOISE = CardDef("White Noise", "白噪声", 1, "Skill",
                      "加 1 张随机能力牌到手牌，本回合费用 0。消耗。（升级费用 0）",
                      False, True, _white_noise_play, upgraded_cost=0)


# ============================================================
# 稀有 17 张
# ============================================================


def _all_for_one_play(bc: BattleContext, item: CardQueueItem) -> None:
    # wiki：造成 10（14）伤，把弃牌堆所有 0 费牌放回手牌（按堆序取到手满
    # 为止，溢出留弃牌堆；"costs 0 while in the discard pile"按当前生效费用
    # ——升级改费/永久改费都算；X 费（-1）与无具体费用的状态/诅咒牌永不
    # 回收（wiki Neutral 节——本引擎 VOID/BURN 模板费 0，按类型排除））
    dmg = bc.calculate_card_damage(item, item.target, 14 if item.card.upgraded else 10)
    bc.add_to_bot(Actions.attack_enemy(item.target, dmg))

    def run(bc2: BattleContext) -> None:
        cards = bc2.cards
        movers = [c for c in list(cards.discard_pile)
                  if c.cost == 0 and c.card.ctype not in ("Status", "Curse")]
        for inst in movers:
            if len(cards.hand) >= MAX_HAND_SIZE:
                break
            cards.discard_pile.remove(inst)
            cards.hand.append(inst)

    bc.add_to_bot(Action(run))


def _amplify_play(bc: BattleContext, item: CardQueueItem) -> None:
    # wiki：本回合下一张（升级：下 2 张）能力牌结算两次——能力牌双发无引擎
    # 钩子（DOUBLE_TAP 的 Power 版触发段缺），special["amplify"] 落槽，
    # 接线需求见模块注释
    bc.add_to_bot(_add_special("amplify", 2 if item.card.upgraded else 1))


def _biased_cognition_play(bc: BattleContext, item: CardQueueItem) -> None:
    # wiki：获得 4（5）专长，每回合开始失去 1 点专长（Bias 状态：持续不衰减，
    # 可叠——多层每回合 -层数）。BIAS 状态枚举引擎未建，
    # special["bias_focus"] 近似（C++ Player.cpp:577-578 语义），接线需求见模块注释
    bc.add_to_bot(Actions.buff_player(PlayerStatus.FOCUS, 5 if item.card.upgraded else 4))
    bc.add_to_bot(_add_special("bias_focus", 1))


def _buffer_play(bc: BattleContext, item: CardQueueItem) -> None:
    # wiki：抵挡接下来 1（2）次 HP 损失——BUFFER 状态引擎未建，
    # special["buffer"] 落槽（可叠），接线需求见模块注释
    bc.add_to_bot(_add_special("buffer", 2 if item.card.upgraded else 1))


def _core_surge_play(bc: BattleContext, item: CardQueueItem) -> None:
    # wiki：造成 11（15）伤，获得 1 层人工制品。消耗
    dmg = bc.calculate_card_damage(item, item.target, 15 if item.card.upgraded else 11)
    bc.add_to_bot(Actions.attack_enemy(item.target, dmg))
    bc.add_to_bot(Actions.buff_player(PlayerStatus.ARTIFACT, 1))


def _creative_ai_play(bc: BattleContext, item: CardQueueItem) -> None:
    # wiki：每回合开始加 1 张随机能力牌到手牌（升级费用 3→2）——回合开始生成
    # 无内容钩子，special["creative_ai"] 落槽，接线需求见模块注释
    bc.add_to_bot(_add_special("creative_ai", 1))


def _echo_form_play(bc: BattleContext, item: CardQueueItem) -> None:
    # wiki：虚无（升级后不再虚无——静态位表达不了，升级版误消散为已知缺口）。
    # 每回合首张打出的牌结算两次——无引擎钩子，special["echo_form"] 落槽
    #（C++ echoFormCardsDoubled 对应物），接线需求见模块注释
    bc.add_to_bot(_add_special("echo_form", 1))


def _electrodynamics_play(bc: BattleContext, item: CardQueueItem) -> None:
    # wiki：闪电球改为命中所有敌人，引导 2（3）个闪电球——ELECTRO 状态引擎已接
    bc.add_to_bot(Actions.buff_player(PlayerStatus.ELECTRO, 1))
    for _ in range(3 if item.card.upgraded else 2):
        bc.add_to_bot(_channel(Orb.LIGHTNING))


def _fission_play(bc: BattleContext, item: CardQueueItem) -> None:
    # wiki：移除（升级：唤起）所有球，每有 1 个球获得 1 点能量并抽 1 张。
    # 消耗。基础版"移除"不触发唤起效果（暗球存层随之作废）
    up = item.card.upgraded

    def run(bc2: BattleContext) -> None:
        p = bc2.player
        n = len(p.orbs)
        if up:
            while p.orbs:
                p.evoke_orb(bc2)
        else:
            p.orbs.clear()
            p.dark_stacks = 0
        if n > 0:
            bc2.add_to_bot(Actions.gain_energy(n))
            bc2.add_to_bot(Actions.draw_cards(n))

    bc.add_to_bot(Action(run))


def _hyperbeam_play(bc: BattleContext, item: CardQueueItem) -> None:
    # wiki：对所有敌人造成 26（34）伤，失去 3 点专长（可为负直达）
    bc.add_to_bot(Actions.attack_all_enemy(34 if item.card.upgraded else 26))
    bc.add_to_bot(Actions.debuff_player(PlayerStatus.FOCUS, -3, False))


def _machine_learning_play(bc: BattleContext, item: CardQueueItem) -> None:
    # wiki：每回合开始多抽 1 张牌（升级后固有）——DRAW_REDUCTION 负层实现
    # 全流程生效（draw_cards 的 count -= 层：-1 层 = +1 张，无自动衰减、可叠）
    bc.add_to_bot(Actions.debuff_player(PlayerStatus.DRAW_REDUCTION, -1, False))


def _meteor_strike_play(bc: BattleContext, item: CardQueueItem) -> None:
    # wiki：造成 24（30）伤，引导 3 个等离子球
    dmg = bc.calculate_card_damage(item, item.target, 30 if item.card.upgraded else 24)
    bc.add_to_bot(Actions.attack_enemy(item.target, dmg))
    for _ in range(3):
        bc.add_to_bot(_channel(Orb.PLASMA))


def _multi_cast_play(bc: BattleContext, item: CardQueueItem) -> None:
    # wiki X 费：唤起下一个球 X（X+1）次
    times = max(item.energy_on_use, 0) + (1 if item.card.upgraded else 0)
    bc.add_to_bot(_evoke_times(times))


def _rainbow_play(bc: BattleContext, item: CardQueueItem) -> None:
    # wiki：引导闪电/冰/暗各 1 个。基础版消耗（升级版不再消耗——play 内覆盖）
    if not item.card.upgraded:
        item.exhaust_on_use = True
    bc.add_to_bot(_channel(Orb.LIGHTNING))
    bc.add_to_bot(_channel(Orb.FROST))
    bc.add_to_bot(_channel(Orb.DARK))


def _reboot_play(bc: BattleContext, item: CardQueueItem) -> None:
    # wiki：手牌与弃牌堆洗入抽牌堆，抽 4（6）张。消耗。Reboot 自身执行时已在
    # 消耗堆（on_after_use_card 同步先行），天然不参与洗回。弃牌堆洗回走引擎
    # on_shuffle（洗牌遗物触发一次，对齐 Patch V1.1 修复后行为），手牌并入后
    # 一并洗匀
    n = 6 if item.card.upgraded else 4

    def run(bc2: BattleContext) -> None:
        cards = bc2.cards
        for inst in list(cards.hand):
            cards.hand.remove(inst)
            cards.draw_pile.append(inst)
        if cards.discard_pile:
            bc2.on_shuffle()
        else:
            bc2.rngs.shuffle.shuffle(cards.draw_pile)
        bc2.draw_cards(n)

    bc.add_to_bot(Action(run))


def _seek_play(bc: BattleContext, item: CardQueueItem) -> None:
    # wiki：从抽牌堆选 1（2）张牌到手牌。消耗。手满时后续选中的牌落弃牌堆
    #（wiki Neutral 节）；抽牌堆为空时空过。Seek 自身执行时已在消耗堆
    n = 2 if item.card.upgraded else 1

    def run(bc2: BattleContext) -> None:
        cands = list(bc2.cards.draw_pile)

        def on_choose(bc3: BattleContext, chosen: list) -> None:
            for inst in chosen:
                bc3.cards.draw_pile.remove(inst)
                if len(bc3.cards.hand) < MAX_HAND_SIZE:
                    bc3.cards.hand.append(inst)
                else:
                    bc3.cards.move_to_discard_pile(inst)

        bc2.open_card_select(cands, on_choose, pick_count=n, can_pick_zero=True,
                             prompt=f"检索：选择 {n} 张抽牌堆的牌到手牌")

    bc.add_to_bot(Action(run))


def _thunder_strike_play(bc: BattleContext, item: CardQueueItem) -> None:
    # wiki：每引导 1 个本场引导过的闪电球，对随机敌人造成 7（9）伤（每段独立
    # 随机目标 + 独立攻击管线；不受 ELECTRO 影响，wiki Neutral 节）
    hits = bc.player.special.get("chan_lightning", 0)
    if hits > 0:
        bc.add_to_bot(Actions.attack_random_enemy(9 if item.card.upgraded else 7, hits))


ALL_FOR_ONE = CardDef("All for One", "合众为一", 2, "Attack",
                      "造成 10 点伤害。把弃牌堆所有 0 费牌放回手牌。（升级 14 伤）",
                      True, False, _all_for_one_play)
AMPLIFY = CardDef("Amplify", "增幅", 1, "Skill",
                  "本回合下一张能力牌结算两次。（升级 2 张；special 槽位，接线见报告）",
                  False, False, _amplify_play)
BIASED_COGNITION = CardDef("Biased Cognition", "偏执认知", 1, "Power",
                           "获得 4 点专长。每回合开始失去 1 点专长。（升级 5 点；"
                           "special 槽位近似 Bias，接线见报告）", False, False,
                           _biased_cognition_play)
BUFFER = CardDef("Buffer", "缓冲", 2, "Power",
                 "抵挡下一次 HP 损失。（升级 2 次；special 槽位，接线见报告）",
                 False, False, _buffer_play)
CORE_SURGE = CardDef("Core Surge", "核心涌动", 1, "Attack",
                     "造成 11 点伤害。获得 1 层人工制品。消耗。（升级 15 伤）", True, True,
                     _core_surge_play)
CREATIVE_AI = CardDef("Creative AI", "创造型 AI", 3, "Power",
                      "每回合开始加 1 张随机能力牌到手牌。（升级费用 2；"
                      "special 槽位，接线见报告）", False, False, _creative_ai_play,
                      upgraded_cost=2)
ECHO_FORM = CardDef("Echo Form", "回声形态", 3, "Power",
                    "虚无。每回合首张打出的牌结算两次。（升级不再虚无；"
                    "special 槽位，接线见报告）", False, False, _echo_form_play,
                    ethereal=True)
ELECTRODYNAMICS = CardDef("Electrodynamics", "电动力学", 2, "Power",
                          "闪电球命中所有敌人。引导 2 个闪电球。（升级 3 个）",
                          False, False, _electrodynamics_play)
FISSION = CardDef("Fission", "裂变", 0, "Skill",
                  "移除所有球，每有 1 个球获得 1 点能量并抽 1 张。消耗。（升级改为唤起）",
                  False, True, _fission_play)
HYPERBEAM = CardDef("Hyperbeam", "巨型光束", 2, "Attack",
                    "对所有敌人造成 26 点伤害。失去 3 点专长。（升级 34 伤）",
                    False, False, _hyperbeam_play)
MACHINE_LEARNING = CardDef("Machine Learning", "机器学习", 1, "Power",
                           "每回合开始多抽 1 张牌。（升级后固有）", False, False,
                           _machine_learning_play, innate_when_upgraded=True)
METEOR_STRIKE = CardDef("Meteor Strike", "陨石打击", 5, "Attack",
                        "造成 24 点伤害。引导 3 个等离子球。（升级 30 伤）", True, False,
                        _meteor_strike_play)
MULTI_CAST = CardDef("Multi-Cast", "多重施法", -1, "Skill",
                     "X 费：唤起下一个球 X 次。（升级 X+1 次）", False, False,
                     _multi_cast_play, x_cost=True)
RAINBOW = CardDef("Rainbow", "彩虹", 2, "Skill",
                  "引导闪电、冰、暗球各 1 个。消耗。（升级不再消耗）", False, False,
                  _rainbow_play)
REBOOT = CardDef("Reboot", "重启", 0, "Skill",
                 "手牌与弃牌堆洗入抽牌堆。抽 4 张牌。消耗。（升级抽 6 张）", False, True,
                 _reboot_play)
SEEK = CardDef("Seek", "检索", 0, "Skill",
               "从抽牌堆选 1 张牌到手牌。消耗。（升级 2 张）", False, True, _seek_play)
THUNDER_STRIKE = CardDef("Thunder Strike", "雷霆打击", 3, "Attack",
                         "每引导过 1 个本场引导的闪电球，对随机敌人造成 7 点伤害。（升级 9 伤）",
                         False, False, _thunder_strike_play)


__all__ = [
    # 基础
    "DEFEND_D", "DUALCAST", "STRIKE_D", "ZAP",
    # 普通
    "BALL_LIGHTNING", "BARRAGE", "BEAM_CELL", "CHARGE_BATTERY", "CLAW",
    "COLD_SNAP", "COMPILE_DRIVER", "COOLHEADED", "GO_FOR_THE_EYES", "HOLOGRAM",
    "LEAP", "REBOUND", "RECURSION", "STACK", "STEAM_BARRIER", "STREAMLINE",
    "SWEEPING_BEAM", "TURBO",
    # 非普通
    "AGGREGATE", "AUTO_SHIELDS", "BLIZZARD", "BOOT_SEQUENCE", "BULLSEYE",
    "CAPACITOR", "CHAOS", "CHILL", "CONSUME", "DARKNESS", "DEFRAGMENT",
    "DOOM_AND_GLOOM", "DOUBLE_ENERGY", "EQUILIBRIUM", "FTL", "FORCE_FIELD",
    "FUSION", "GENETIC_ALGORITHM", "GLACIER", "HEATSINKS", "HELLO_WORLD",
    "LOOP", "MELTER", "OVERCLOCK", "RECYCLE", "REINFORCED_BODY", "REPROGRAM",
    "RIP_AND_TEAR", "SCRAPE", "SELF_REPAIR", "SKIM", "STATIC_DISCHARGE",
    "STORM", "SUNDER", "TEMPEST", "WHITE_NOISE",
    # 稀有
    "ALL_FOR_ONE", "AMPLIFY", "BIASED_COGNITION", "BUFFER", "CORE_SURGE",
    "CREATIVE_AI", "ECHO_FORM", "ELECTRODYNAMICS", "FISSION", "HYPERBEAM",
    "MACHINE_LEARNING", "METEOR_STRIKE", "MULTI_CAST", "RAINBOW", "REBOOT",
    "SEEK", "THUNDER_STRIKE",
]


def random_power_card():
    """随机能力牌（Hello World/Creative AI 生成用；Java 口径：随机 1 张
    Defect 能力牌。排除 Hello World/Creative AI/Self Repair 防自我循环
    与战斗外语义）。"""
    import random as _random

    pool = [CAPACITOR, DEFRAGMENT, HEATSINKS, LOOP, STATIC_DISCHARGE, STORM,
            BIASED_COGNITION, BUFFER, ECHO_FORM, ELECTRODYNAMICS, MACHINE_LEARNING]
    return _random.choice(pool)

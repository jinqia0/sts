"""Watcher（观者）职业全卡移植：75 张池内卡（4 基础 + 19 普通 + 35 非普通
+ 17 稀有，wiki Watcher 卡池页口径——含任务清单未列、但池页在列的
Sands of Time / Windmill Strike / Conclude / Study / Third Eye / Signature
Move / Wreath of Flame / Spirit Shield / Reach Heaven / BrilLiance 族）+ 8 张
生成卡（Miracle / Insight / Safety / Smite / Through Violence / Beta /
Omega / Expunger——Expunger 为 Conjure Blade 的生成物，任务清单未列，
wiki Conjure Blade 卡页在列），共 83 个 CardDef。

权威源（lightspeed 的 C++ switch 未实现任何 Watcher 卡效果，仅 Cards.h
有数据位）：
- 数值/结算文本/费用：slaythespire.wiki.gg（A0 基准，wiki 口径，逐卡注明）
- 数据位交叉校验：Cards.h doesCardExhaust / doesCardSelfRetain /
  isCardInnate / isXCost——观测者卡几乎全部吻合（唯一例外：getEnergyCost
  对未列名的 Watcher 卡一律回落 1（Eruption/Vigilance/Omega 等均与 wiki
  不符），以 wiki 为准。

姿态（Keywords#Stance，wiki 口径；引擎侧已实现的部分见 combat/entities）：
- Calm：**退出平静时 +2 能量**——引擎 change_stance 未实现，本模块对
  内容层驱动的姿态切换做了仿真（_change_stance 助手）；引擎驱动路径
  （Devotion 真言满 10、WRATH_NEXT_TURN、回合开始 Divinity→Neutral）
  不经仿真，已列入迁移报告的引擎接线需求。
- Divinity：**进入时 +3 能量**、攻击 ×3（乘区引擎已接）、下回合开始回
  Neutral（引擎已接）。+3 能量同样走 _change_stance / _gain_mantra 仿真。
- Wrath：攻击 ×2（引擎已接）；**受到的攻击伤害 ×2** 引擎未实现
  （calculate_monster_damage 无姿态乘区）——迁移报告。

引擎接线状态（本模块 play 落状态/槽位即可，逐项见迁移报告）：
- 已接可用：MANTRA（满 10 进 Divinity）/ DEVOTION（回合开始 +层真言）/
  RUSHDOWN（进愤怒抽 2×层）/ MENTAL_FORTRESS（进任意姿态 3×层 格挡——
  wiki 为 4/6，引擎常量 3，偏差报告）/ LIKE_WATER（平静回合末 3×层 格挡
  ——wiki 为 5/7，同偏差）/ WRATH_NEXT_TURN / Scry（open_scry→choose_scry）/
  Retain / VIGOR（下一张攻击 +N 后移除，relics.on_use_attack_card——
  Wreath of Flame 全功能可用）/ PLATED_ARMOR / NEXT_TURN_BLOCK /
  special["next_turn_draw"] / energy_per_turn_bonus（Fasting）。
- 内容层仿真（覆盖内容驱动的路径，引擎驱动路径有缺口，报告）：
  Calm 退出 +2 能量 / Divinity 进入 +3 能量 / Flurry of Blows 姿态切换
  回手（_change_stance 内扫描弃牌堆）/ 真言获取改走 _gain_mantra（便于
  计入 Brilliance 的"本场战斗获得真言"计数 + Divinity 能量）。
- 槽位落地 + 引擎接线需求（只断言槽位落地）：special["foresight"]（回合
  开始 Scry）/ ["battle_hymn"]（回合开始加 Smite）/ ["study"]（回合末洗
  入 Insight）/ ["deva_form"]（回合开始能量爬坡）/ ["omega"]（回合末全体
  伤害）/ ["collect_miracles"]（每回合一张 Miracle+）/ ["master_reality"]
  （生成牌升级——观者内容层生成路径已读此位，引擎侧生成如 Shiv/伤口仍缺）/
  ["establishment"]（保留牌 -1 费）/ ["blasphemy_die"]（下回合开始死亡）/
  ["nirvana"]（每次 Scry 得格挡）/ ["wave_of_the_hand"]（本回合每次得
  格挡全体虚弱）/ ["swivel"]（下一张攻击 0 费）/ ["weave_recall"]（每次
  Scry 从弃牌堆回手）。
- 无槽位、纯报告：Retain 时点触发器（Perseverance +格挡 / Windmill
  Strike +伤害 / Sands of Time -费用，实例 misc_data 已就绪但增量时机缺）
  / "上一张打出的牌"类型追踪（本模块以日志解析近似，建议引擎加
  last_card_played 位）/ Talk to the Hand 的 BLOCK_RETURN 触发段
  （MonsterStatus.BLOCK_RETURN 枚举已在，触发缺）。

与包结构的关系：本文件为 Watcher 卡唯一正式定义，经包 __init__
eager re-export 暴露；CardDef 取自 _base.py，_strike_play 复用自
ironclad.py。STRIKE_W/DEFEND_W 沿用卡名 "Strike"/"Defend"
（观测词表按 "模块:常量名" 身份区分，sts/vocab.py）。
"""

from __future__ import annotations

import re
from typing import TYPE_CHECKING

from sts.combat.actions import Actions
from sts.combat.card_manager import MAX_HAND_SIZE
from sts.combat.queue import Action, CardQueueItem
from sts.combat.types import MonsterStatus, Outcome, PlayerStatus, Stance

from sts.content.cards._base import CardDef, _strike_play

if TYPE_CHECKING:
    from sts.combat.battle import BattleContext
    from sts.combat.card_manager import CardInstance
    from sts.combat.queue import CardQueueItem


# ============================================================
# 公共设施
# ============================================================


def _unplayable_noop(bc: BattleContext, item: CardQueueItem) -> None:
    """不可打出牌（Deus Ex Machina）的 play 占位：正常出牌被 play_card
    的 unplayable 位拦截；Havoc/Mayhem 等强制入队结算时无效果。"""
    pass


def _add_to_hand(bc: BattleContext, inst: CardInstance) -> None:
    """加牌入手；手满落弃牌堆（对齐 moveToHandHelper，上限 10）。"""
    if len(bc.cards.hand) < MAX_HAND_SIZE:
        bc.cards.hand.append(inst)
    else:
        bc.cards.move_to_discard_pile(inst)


def _mr(bc: BattleContext, base_upgraded: bool = False) -> bool:
    """Master Reality（现实大师）：战斗中生成的牌升级。内容层生成路径
    （本模块全部生成牌）读此位即时生效；引擎侧生成（Shiv/伤口等）的
    升级钩子缺，列入迁移报告。"""
    return bool(base_upgraded or bc.player.special.get("master_reality"))


def _scry(n: int) -> Action:
    """检视抽牌堆顶 n 张（引擎 InputState.SCRY：open_scry 挂起 → 外部
    choose_scry 保留/弃置 → 主循环继续）。抽牌堆为空时 open_scry 自行
    空跳过。"""
    return Action(lambda bc: bc.open_scry(n))


def _change_stance(new: Stance) -> Action:
    """姿态切换（内容层薄封装）：能量（退 Calm +2 / 进 Divinity +3）已在
    引擎 change_stance 统一结算，此处仅保留 Flurry of Blows 的姿态切换
    回手（wiki：姿态改变时从弃牌堆回手，引擎未接，内容层处理）。"""

    def run(bc: BattleContext) -> None:
        p = bc.player
        prev = p.stance
        p.change_stance(bc, new)
        if p.stance == prev:
            return  # 同姿态 no-op（引擎行为，无任何触发）
        for inst in [c for c in list(bc.cards.discard_pile)
                     if c.card is FLURRY_OF_BLOWS]:
            if len(bc.cards.hand) >= MAX_HAND_SIZE:
                break
            bc.cards.discard_pile.remove(inst)
            _add_to_hand(bc, inst)

    return Action(run)


def _gain_mantra(n: int) -> Action:
    """真言 +N（内容层计数增强）：真言累计/满 10 进 Divinity 已在引擎
    gain_mantra 统一结算（含 Divinity +3 能量），此处补
    special["mantra_gained"]（Brilliance 的"本场战斗获得的真言"计数）。"""

    def run(bc: BattleContext) -> None:
        p = bc.player
        p.special["mantra_gained"] = p.special.get("mantra_gained", 0) + n
        p.gain_mantra(bc, n)

    return Action(run)




# ============================================================
# "上一张打出的牌"类型（Crush Joints / Follow-Up / Sash Whip / Sanctity）
# ============================================================


def _played_card_names(bc: BattleContext) -> list[str]:
    """从战斗日志提取"打出"序列（use_card 在 play 之前逐张记录；Double
    Tap/Burst 重放与 Havoc/Mayhem 自动播放同样经 use_card 记录，语义与
    wiki"the last card played this combat"一致）。

    引擎无 last_card_played 追踪位——本函数为内容层近似（迁移报告建议
    引擎补位）。play() 被调用时最后一条必是当前牌自身，取倒数第二条。
    """
    pat = re.compile(r"^你打出 .+\(([^()]+)\)。$")
    names: list[str] = []
    for line in bc.log:
        m = pat.match(line)
        if m:
            names.append(m.group(1))
    return names


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
        for mod in (_c, _cu, _cl, _s, _w):
            for g in vars(mod).values():
                if isinstance(g, CardDef):
                    cache.setdefault(g.name, g.ctype)
        _CTYPE_CACHE = cache
    return _CTYPE_CACHE


def _prev_played_ctype(bc: BattleContext) -> str | None:
    """上一张打出的牌的类型（当前牌已在日志、取其前一张）。"""
    names = _played_card_names(bc)
    if len(names) < 2:
        return None
    return _ctype_by_name().get(names[-2])


# ============================================================
# 回合结束 / 牌堆操作
# ============================================================


def _end_turn_from_play(bc: BattleContext) -> None:
    """出牌效果内结束本回合（Conclude/Meditate/Vault）：压入结束回合哨兵
    （对齐引擎 end_turn 的队列路径，不要求 PLAYER_NORMAL 状态）。"""
    bc.add_to_bot_card(CardQueueItem.end_turn_item())
    bc.end_turn_queued = True


def _shuffle_created_into_draw(card: "CardDef", upgraded: bool = False) -> Action:
    """生成牌洗入抽牌堆（随机位，misc 流；Master Reality 感知升级）。"""

    def run(bc: BattleContext) -> None:
        up = _mr(bc, upgraded)
        bc.add_to_bot(Actions.make_temp_card_in_draw_pile(card, up, shuffle_into=True))

    return Action(run)


# ============================================================
# 基础 4 张（wiki：Eruption+ 为 1 费 9 伤——升级只改费，不改伤害）
# ============================================================


def _defend_w_play(bc: BattleContext, item: CardQueueItem) -> None:
    # wiki：获得 5 格挡（+：8）
    bc.add_to_bot(Actions.gain_block(bc.calculate_card_block(8 if item.card.upgraded else 5)))


def _eruption_play(bc: BattleContext, item: CardQueueItem) -> None:
    # wiki：造成 9 伤害，进入愤怒。伤害先结算（wiki Order 节：自身伤害
    # 不吃尚未进入的愤怒 ×2），再切姿态（自平静退出 +2 能量见 _change_stance）
    dmg = bc.calculate_card_damage(item, item.target, 9)
    bc.add_to_bot(Actions.attack_enemy(item.target, dmg))
    bc.add_to_bot(_change_stance(Stance.WRATH))


def _vigilance_play(bc: BattleContext, item: CardQueueItem) -> None:
    # wiki：获得 8 格挡（+：12），进入平静。费用恒 2（升级不改费）
    bc.add_to_bot(Actions.gain_block(bc.calculate_card_block(12 if item.card.upgraded else 8)))
    bc.add_to_bot(_change_stance(Stance.CALM))


STRIKE_W = CardDef("Strike", "打击", 1, "Attack", "造成 6 点伤害。", True, False,
                   _strike_play)
DEFEND_W = CardDef("Defend", "防御", 1, "Skill", "获得 5 点格挡。", False, False,
                   _defend_w_play)
ERUPTION = CardDef("Eruption", "暴怒", 2, "Attack", "造成 9 点伤害。\n进入愤怒。",
                   True, False, _eruption_play, upgraded_cost=1)
VIGILANCE = CardDef("Vigilance", "警惕", 2, "Skill", "获得 8 点格挡。\n进入平静。",
                    False, False, _vigilance_play)


# ============================================================
# 生成牌 8 张（Colorless Special；Retain/Exhaust 对齐 Cards.h）
# ============================================================


def _miracle_play(bc: BattleContext, item: CardQueueItem) -> None:
    # wiki：保留。获得 1 点能量（+：2 点）。消耗
    bc.add_to_bot(Actions.gain_energy(2 if item.card.upgraded else 1))


def _insight_play(bc: BattleContext, item: CardQueueItem) -> None:
    # wiki：保留。抽 2 张牌（+：3 张）。消耗
    bc.add_to_bot(Actions.draw_cards(3 if item.card.upgraded else 2))


def _safety_play(bc: BattleContext, item: CardQueueItem) -> None:
    # wiki：保留。获得 12 点格挡（+：16）。消耗
    bc.add_to_bot(Actions.gain_block(bc.calculate_card_block(16 if item.card.upgraded else 12)))


def _smite_play(bc: BattleContext, item: CardQueueItem) -> None:
    # wiki：保留。造成 12 点伤害（+：16）。消耗
    dmg = bc.calculate_card_damage(item, item.target, 16 if item.card.upgraded else 12)
    bc.add_to_bot(Actions.attack_enemy(item.target, dmg))


def _through_violence_play(bc: BattleContext, item: CardQueueItem) -> None:
    # wiki：保留。造成 20 点伤害（+：30）。消耗
    dmg = bc.calculate_card_damage(item, item.target, 30 if item.card.upgraded else 20)
    bc.add_to_bot(Actions.attack_enemy(item.target, dmg))


def _beta_play(bc: BattleContext, item: CardQueueItem) -> None:
    # wiki：洗入 1 张 Omega（+：费用 2→1）。消耗。Alpha→Beta→Omega 链
    bc.add_to_bot(_shuffle_created_into_draw(OMEGA))


def _omega_play(bc: BattleContext, item: CardQueueItem) -> None:
    # wiki：回合结束时对所有敌人造成 50 点伤害（+：60）。能力牌，打出即
    # 离场；"回合末全体伤害"无引擎钩子——special["omega"] 存伤害量，接线
    # 需求见迁移报告
    bc.add_to_bot(Action(lambda bc2: bc2.player.special.update(
        omega=bc2.player.special.get("omega", 0) + (60 if item.card.upgraded else 50))))


def _expunger_play(bc: BattleContext, item: CardQueueItem) -> None:
    # wiki（Conjure Blade 页内）：造成 9 点伤害（+：15）X 次——X 为 Conjure
    # Blade 打出时消耗的能量（存实例 misc_data，生成时写入）
    times = max(item.card.misc_data, 0)
    dmg = bc.calculate_card_damage(item, item.target, 15 if item.card.upgraded else 9)
    for _ in range(times):
        bc.add_to_bot(Actions.attack_enemy(item.target, dmg))


MIRACLE = CardDef("Miracle", "奇迹", 0, "Skill", "保留。\n获得 1 点能量。\n消耗。",
                  False, True, _miracle_play, self_retain=True)
INSIGHT = CardDef("Insight", "洞见", 0, "Skill", "保留。\n抽 2 张牌。\n消耗。",
                  False, True, _insight_play, self_retain=True)
SAFETY = CardDef("Safety", "平安", 1, "Skill", "保留。\n获得 12 点格挡。\n消耗。",
                 False, True, _safety_play, self_retain=True)
SMITE = CardDef("Smite", "惩恶", 1, "Attack", "保留。\n造成 12 点伤害。\n消耗。",
                True, True, _smite_play, self_retain=True)
THROUGH_VIOLENCE = CardDef("Through Violence", "以暴易暴", 0, "Attack",
                           "保留。\n造成 20 点伤害。\n消耗。", True, True,
                           _through_violence_play, self_retain=True)
BETA = CardDef("Beta", "贝塔", 2, "Skill", "将一张欧米伽放入你的抽牌堆中。\n消耗。",
               False, True, _beta_play, upgraded_cost=1)
OMEGA = CardDef("Omega", "欧米伽", 3, "Power", "在你的回合结束时，对所有敌人造成 50 点伤害。",
                False, False, _omega_play)
EXPUNGER = CardDef("Expunger", "灭除之刃", 1, "Attack", "造成 9 点伤害 X 次。", True, False, _expunger_play)


# ============================================================
# 普通 19 张
# ============================================================


def _bowling_bash_play(bc: BattleContext, item: CardQueueItem) -> None:
    # wiki：对单个目标造成 7 伤（+：10）× 存活敌人数（含命中增益每段吃
    # 力量——多段共用出牌时算好的伤害即可）。只计存活敌人
    alive = sum(1 for m in bc.monsters.monsters if m.is_targetable())
    dmg = bc.calculate_card_damage(item, item.target, 10 if item.card.upgraded else 7)
    for _ in range(max(alive, 0)):
        bc.add_to_bot(Actions.attack_enemy(item.target, dmg))


def _consecrate_play(bc: BattleContext, item: CardQueueItem) -> None:
    # wiki：对所有敌人造成 5 伤（+：8）。0 费
    bc.add_to_bot(Actions.attack_all_enemy(8 if item.card.upgraded else 5))


def _crescendo_play(bc: BattleContext, item: CardQueueItem) -> None:
    # wiki：保留。进入愤怒。消耗（+：费用 1→0）
    bc.add_to_bot(_change_stance(Stance.WRATH))


def _crush_joints_play(bc: BattleContext, item: CardQueueItem) -> None:
    # wiki：造成 8 伤（+：10）。若本场战斗上一张打出的牌是技能牌，施加
    # 1 层（+：2 层）易伤。"上一张打出"以日志解析近似（引擎缺追踪位）
    up = item.card.upgraded
    dmg = bc.calculate_card_damage(item, item.target, 10 if up else 8)
    bc.add_to_bot(Actions.attack_enemy(item.target, dmg))
    if _prev_played_ctype(bc) == "Skill":
        bc.add_to_bot(Actions.debuff_enemy(item.target, MonsterStatus.VULNERABLE, 2 if up else 1, False))


def _cut_through_fate_play(bc: BattleContext, item: CardQueueItem) -> None:
    # wiki：造成 7 伤（+：9）。检视 2（+：3）。抽 1 张牌（升级抽牌量不变）
    dmg = bc.calculate_card_damage(item, item.target, 9 if item.card.upgraded else 7)
    bc.add_to_bot(Actions.attack_enemy(item.target, dmg))
    bc.add_to_bot(_scry(3 if item.card.upgraded else 2))
    bc.add_to_bot(Actions.draw_cards(1))


def _exit_stance() -> Action:
    """退出姿态（Empty Body/Fist/Mind）：回中性——自平静退出同样触发
    +2 能量（wiki 口径）。已在中性则 no-op。"""
    return _change_stance(Stance.NEUTRAL)


def _empty_body_play(bc: BattleContext, item: CardQueueItem) -> None:
    # wiki：获得 7 格挡（+：10）。退出姿态
    bc.add_to_bot(Actions.gain_block(bc.calculate_card_block(10 if item.card.upgraded else 7)))
    bc.add_to_bot(_exit_stance())


def _empty_fist_play(bc: BattleContext, item: CardQueueItem) -> None:
    # wiki：造成 9 伤（+：14）。退出姿态
    dmg = bc.calculate_card_damage(item, item.target, 14 if item.card.upgraded else 9)
    bc.add_to_bot(Actions.attack_enemy(item.target, dmg))
    bc.add_to_bot(_exit_stance())


def _evaluate_play(bc: BattleContext, item: CardQueueItem) -> None:
    # wiki：获得 6 格挡（+：10）。洗入 1 张洞见（Master Reality 感知升级）
    bc.add_to_bot(Actions.gain_block(bc.calculate_card_block(10 if item.card.upgraded else 6)))
    bc.add_to_bot(_shuffle_created_into_draw(INSIGHT))


def _flurry_of_blows_play(bc: BattleContext, item: CardQueueItem) -> None:
    # wiki：造成 4 伤（+：6）。每当你切换姿态，从弃牌堆回到手牌——回手在
    # _change_stance 内对内容驱动路径仿真；引擎驱动路径（Devotion 满真言
    # 等）不触发，列入迁移报告
    dmg = bc.calculate_card_damage(item, item.target, 6 if item.card.upgraded else 4)
    bc.add_to_bot(Actions.attack_enemy(item.target, dmg))


def _flying_sleeves_play(bc: BattleContext, item: CardQueueItem) -> None:
    # wiki：保留。造成 4 伤（+：6）2 次。两段共用出牌时算好的伤害
    dmg = bc.calculate_card_damage(item, item.target, 6 if item.card.upgraded else 4)
    bc.add_to_bot(Actions.attack_enemy(item.target, dmg))
    bc.add_to_bot(Actions.attack_enemy(item.target, dmg))


def _follow_up_play(bc: BattleContext, item: CardQueueItem) -> None:
    # wiki：造成 7 伤（+：11）。若上一张打出的牌是攻击牌，获得 1 点能量
    #（升级版能量同样为 1——wiki Interactions 节确认两版均 1 点）
    dmg = bc.calculate_card_damage(item, item.target, 11 if item.card.upgraded else 7)
    bc.add_to_bot(Actions.attack_enemy(item.target, dmg))
    if _prev_played_ctype(bc) == "Attack":
        bc.add_to_bot(Actions.gain_energy(1))


def _halt_play(bc: BattleContext, item: CardQueueItem) -> None:
    # wiki：获得 3 格挡（+：4）。若处于愤怒，额外获得 9（+：14）格挡
    up = item.card.upgraded
    bc.add_to_bot(Actions.gain_block(bc.calculate_card_block(4 if up else 3)))
    if bc.player.stance == Stance.WRATH:
        bc.add_to_bot(Actions.gain_block(bc.calculate_card_block(14 if up else 9)))


def _just_lucky_play(bc: BattleContext, item: CardQueueItem) -> None:
    # wiki：检视 1（+：2）。获得 2 格挡（+：3）。造成 3 伤（+：4）
    up = item.card.upgraded
    bc.add_to_bot(_scry(2 if up else 1))
    bc.add_to_bot(Actions.gain_block(bc.calculate_card_block(3 if up else 2)))
    dmg = bc.calculate_card_damage(item, item.target, 4 if up else 3)
    bc.add_to_bot(Actions.attack_enemy(item.target, dmg))


def _pressure_points_play(bc: BattleContext, item: CardQueueItem) -> None:
    # wiki：对所有敌人施加 8 层（+：11）标记（MARK 为 debuff，吃 ARTIFACT）；
    # 所有敌人失去等同其标记层数的 HP——"失去 HP"不吃格挡（直伤），
    # 存活敌人逐个结算、死亡走 die()。MARK 枚举引擎预留已用上
    n = 11 if item.card.upgraded else 8
    bc.add_to_bot(Actions.debuff_all_enemy(MonsterStatus.MARK, n, False))

    def run(bc2: BattleContext) -> None:
        for m in bc2.monsters.monsters:
            if m.is_dead_or_escaped():
                continue
            mark = m.statuses.get(MonsterStatus.MARK)
            if mark <= 0:
                continue
            m.hp = max(0, m.hp - mark)
            if m.hp == 0:
                m.die(bc2)
            bc2.check_combat()

    bc.add_to_bot(Action(run))


def _prostrate_play(bc: BattleContext, item: CardQueueItem) -> None:
    # wiki：获得 2 层（+：3）真言。获得 4 格挡（升级格挡不变）
    bc.add_to_bot(_gain_mantra(3 if item.card.upgraded else 2))
    bc.add_to_bot(Actions.gain_block(bc.calculate_card_block(4)))


def _protect_play(bc: BattleContext, item: CardQueueItem) -> None:
    # wiki：保留。获得 12 格挡（+：16）
    bc.add_to_bot(Actions.gain_block(bc.calculate_card_block(16 if item.card.upgraded else 12)))


def _sash_whip_play(bc: BattleContext, item: CardQueueItem) -> None:
    # wiki：造成 8 伤（+：10）。若上一张打出的牌是攻击牌，施加 1 层
    #（+：2 层）虚弱
    up = item.card.upgraded
    dmg = bc.calculate_card_damage(item, item.target, 10 if up else 8)
    bc.add_to_bot(Actions.attack_enemy(item.target, dmg))
    if _prev_played_ctype(bc) == "Attack":
        bc.add_to_bot(Actions.debuff_enemy(item.target, MonsterStatus.WEAK, 2 if up else 1, False))


def _third_eye_play(bc: BattleContext, item: CardQueueItem) -> None:
    # wiki：获得 7 格挡（+：9）。检视 3（+：5）
    bc.add_to_bot(Actions.gain_block(bc.calculate_card_block(9 if item.card.upgraded else 7)))
    bc.add_to_bot(_scry(5 if item.card.upgraded else 3))


def _tranquility_play(bc: BattleContext, item: CardQueueItem) -> None:
    # wiki：保留。进入平静。消耗（+：费用 1→0）
    bc.add_to_bot(_change_stance(Stance.CALM))


BOWLING_BASH = CardDef("Bowling Bash", "碰撞连击", 1, "Attack",
                       "当前每有一名敌人，造成 7 点伤害。",
                       True, False, _bowling_bash_play)
CONSECRATE = CardDef("Consecrate", "供奉", 0, "Attack", "对所有敌人造成 5 点伤害。",
                     False, False, _consecrate_play)
CRESCENDO = CardDef("Crescendo", "渐强", 1, "Skill", "保留。\n进入愤怒。\n消耗。",
                    False, True, _crescendo_play, upgraded_cost=0, self_retain=True)
CRUSH_JOINTS = CardDef("Crush Joints", "粉碎关节", 1, "Attack",
                       "造成 8 点伤害。\n如果本场战斗中打出的上一张牌是技能牌，给予 1 层易伤。",
                       True, False, _crush_joints_play)
CUT_THROUGH_FATE = CardDef("Cut Through Fate", "斩破命运", 1, "Attack",
                           "造成 7 点伤害。\n预见 2。\n抽 1 张牌。",
                           True, False, _cut_through_fate_play)
EMPTY_BODY = CardDef("Empty Body", "化体为空", 1, "Skill",
                     "获得 7 点格挡。\n退出当前姿态。", False, False, _empty_body_play)
EMPTY_FIST = CardDef("Empty Fist", "化拳为空", 1, "Attack",
                     "造成 9 点伤害。\n退出当前姿态。", True, False, _empty_fist_play)
EVALUATE = CardDef("Evaluate", "评估", 1, "Skill",
                   "获得 6 点格挡。\n在你的抽牌堆中加入一张洞见。", False, False, _evaluate_play)
FLURRY_OF_BLOWS = CardDef("Flurry of Blows", "疾风连击", 0, "Attack",
                           "造成 4 点伤害。\n你每次转换姿态时，将这张牌从弃牌堆放回你的手牌。",
                           True, False, _flurry_of_blows_play)
FLYING_SLEEVES = CardDef("Flying Sleeves", "流云飞袖", 1, "Attack",
                         "保留。\n造成 4 点伤害两次。", True, False,
                         _flying_sleeves_play, self_retain=True)
FOLLOW_UP = CardDef("Follow-Up", "追击", 1, "Attack",
                    "造成 7 点伤害。\n如果本场战斗中打出的上一张牌是攻击牌，获得 1 点能量。",
                    True, False, _follow_up_play)
HALT = CardDef("Halt", "停顿", 0, "Skill",
               "获得 3 点格挡。\n愤怒：获得 9 点额外格挡。",
               False, False, _halt_play)
JUST_LUCKY = CardDef("Just Lucky", "幸运一击", 0, "Attack",
                     "预见 1。\n获得 2 点格挡。\n造成 3 点伤害。",
                     True, False, _just_lucky_play)
PRESSURE_POINTS = CardDef("Pressure Points", "点穴", 1, "Skill",
                          "给予 8 层印记。\n所有拥有印记的敌人，失去与层数相等的生命。",
                          False, False, _pressure_points_play)
PROSTRATE = CardDef("Prostrate", "五体投地", 0, "Skill",
                    "获得 2 层真言。\n获得 4 点格挡。", False, False, _prostrate_play)
PROTECT = CardDef("Protect", "护身", 2, "Skill", "保留。\n获得 12 点格挡。",
                  False, False, _protect_play, self_retain=True)
SASH_WHIP = CardDef("Sash Whip", "腰带抽打", 1, "Attack",
                    "造成 8 点伤害。\n如果本场战斗中打出的上一张牌是攻击牌，给予 1 层虚弱。",
                    True, False, _sash_whip_play)
THIRD_EYE = CardDef("Third Eye", "天眼", 1, "Skill",
                    "获得 7 点格挡。\n预见 3。", False, False, _third_eye_play)
TRANQUILITY = CardDef("Tranquility", "安宁", 1, "Skill",
                      "保留。进入平静。\n消耗。", False, True, _tranquility_play,
                      upgraded_cost=0, self_retain=True)


# ============================================================
# 非普通 35 张
# ============================================================


def _battle_hymn_play(bc: BattleContext, item: CardQueueItem) -> None:
    # wiki：每回合开始时加 1 张天罚到手牌（+：固有）。回合开始生成无内容
    # 钩子——special["battle_hymn"] 存层数（多次施放每层 1 张），接线
    # 需求见迁移报告
    bc.add_to_bot(Action(lambda bc2: bc2.player.special.update(
        battle_hymn=bc2.player.special.get("battle_hymn", 0) + 1)))


def _carve_reality_play(bc: BattleContext, item: CardQueueItem) -> None:
    # wiki：造成 6 伤（+：10）。加 1 张天罚到手牌
    dmg = bc.calculate_card_damage(item, item.target, 10 if item.card.upgraded else 6)
    bc.add_to_bot(Actions.attack_enemy(item.target, dmg))
    bc.add_to_bot(Action(lambda bc2: bc2.cards.create_temp_card_in_hand(SMITE, _mr(bc2))))


def _collect_play(bc: BattleContext, item: CardQueueItem) -> None:
    # wiki：X 费：在接下来 X（+：X+1）回合的每回合开始，加 1 张奇迹+到手
    # 中。消耗。"每回合一张"跨多回合，引擎 next_turn_cards 槽只支持单次
    # 爆发——special["collect_miracles"] 存剩余回合数，接线需求见迁移报告
    turns = max(item.energy_on_use, 0) + (1 if item.card.upgraded else 0)
    bc.add_to_bot(Action(lambda bc2: bc2.player.special.update(
        collect_miracles=bc2.player.special.get("collect_miracles", 0) + turns)))


def _conclude_play(bc: BattleContext, item: CardQueueItem) -> None:
    # wiki：对所有敌人造成 12 伤（+：16）。结束你的回合（出牌内结束回合
    # 走结束回合哨兵，见 _end_turn_from_play）
    bc.add_to_bot(Actions.attack_all_enemy(16 if item.card.upgraded else 12))
    bc.add_to_bot(Action(lambda bc2: _end_turn_from_play(bc2)))


def _deceive_reality_play(bc: BattleContext, item: CardQueueItem) -> None:
    # wiki：获得 4 格挡（+：7）。加 1 张安全庇护到手牌
    bc.add_to_bot(Actions.gain_block(bc.calculate_card_block(7 if item.card.upgraded else 4)))
    bc.add_to_bot(Action(lambda bc2: bc2.cards.create_temp_card_in_hand(SAFETY, _mr(bc2))))


def _empty_mind_play(bc: BattleContext, item: CardQueueItem) -> None:
    # wiki：退出姿态。抽 2（+：3）张牌
    bc.add_to_bot(_exit_stance())
    bc.add_to_bot(Actions.draw_cards(3 if item.card.upgraded else 2))


def _fasting_play(bc: BattleContext, item: CardQueueItem) -> None:
    # wiki：获得 3 点力量与 3 点敏捷（+：各 4）。每回合开始少获得 1 点能量
    #（多次施放各 -1）——引擎 _recharge_energy 读 energy_per_turn_bonus，
    # 内容层直接递减即全流程生效
    n = 4 if item.card.upgraded else 3
    bc.add_to_bot(Actions.buff_player(PlayerStatus.STRENGTH, n))
    bc.add_to_bot(Actions.buff_player(PlayerStatus.DEXTERITY, n))
    bc.player.energy_per_turn_bonus -= 1


def _fear_no_evil_play(bc: BattleContext, item: CardQueueItem) -> None:
    # wiki：造成 8 伤（+：11）。若该敌人意图为攻击，进入平静
    dmg = bc.calculate_card_damage(item, item.target, 11 if item.card.upgraded else 8)
    bc.add_to_bot(Actions.attack_enemy(item.target, dmg))
    t = item.target

    def run(bc2: BattleContext) -> None:
        m = bc2.monsters.monsters[t]
        if not m.is_dead_or_escaped() and m.current_move.kind == "attack":
            bc2.add_to_bot(_change_stance(Stance.CALM))

    bc.add_to_bot(Action(run))


def _foreign_influence_pool() -> list:
    """随机攻击池（Foreign Influence："任意职业卡池、可在卡牌奖励中出现"
    ——近似为全内容模块的攻击卡，按 wiki 排除带局外永久效果/仅生成来源的
    卡与基础打击/防御；X 费攻击保留——升级版置 0 费仅本回合，X 费照旧
    消耗全部能量）。"""
    import sts.content.cards.ironclad as _c
    import sts.content.cards.colorless as _cl
    import sts.content.cards.silent as _s
    import sts.content.cards.watcher as _w

    excluded = {"Feed", "Reaper", "Lesson Learned", "Bite", "Ritual Dagger",
                "Shiv", "Smite", "Through Violence", "Expunger", "Strike", "Defend"}
    pool = []
    for mod in (_c, _cl, _s, _w):
        for g in vars(mod).values():
            if isinstance(g, CardDef) and g.ctype == "Attack" and g.name not in excluded:
                pool.append(g)
    return pool


def _foreign_influence_play(bc: BattleContext, item: CardQueueItem) -> None:
    # wiki：3 张随机攻击牌选 1 加入手牌（+：该牌本回合 0 费）。消耗。
    # 采样无放回（3 张互不相同）；空池/候选全弃均可空选
    up = item.card.upgraded

    def run(bc2: BattleContext) -> None:
        pool = _foreign_influence_pool()
        cands: list[CardDef] = []
        for _ in range(min(3, len(pool))):
            i = bc2.rngs.misc.int_inclusive(0, len(pool) - 1)
            cands.append(pool.pop(i))

        def on_choose(bc3: BattleContext, chosen: list) -> None:
            for card in chosen:
                inst = bc3.cards.instantiate(card)
                inst.upgraded = _mr(bc3)
                if up:
                    inst.cost_for_turn = 0
                _add_to_hand(bc3, inst)

        bc2.open_card_select(cands, on_choose, can_pick_zero=True,
                             prompt="异域影响：选择 1 张攻击牌加入手牌")

    bc.add_to_bot(Action(run))


def _foresight_play(bc: BattleContext, item: CardQueueItem) -> None:
    # wiki：每回合开始时检视 3（+：4）。回合开始无内容钩子——
    # special["foresight"] 累加检视量，接线需求见迁移报告
    n = 4 if item.card.upgraded else 3
    bc.add_to_bot(Action(lambda bc2: bc2.player.special.update(
        foresight=bc2.player.special.get("foresight", 0) + n)))


def _indignation_play(bc: BattleContext, item: CardQueueItem) -> None:
    # wiki：若处于愤怒，对所有敌人施加 3 层（+：5）易伤；否则进入愤怒
    if bc.player.stance == Stance.WRATH:
        bc.add_to_bot(Actions.debuff_all_enemy(MonsterStatus.VULNERABLE,
                                                5 if item.card.upgraded else 3, False))
    else:
        bc.add_to_bot(_change_stance(Stance.WRATH))


def _inner_peace_play(bc: BattleContext, item: CardQueueItem) -> None:
    # wiki：若处于平静，抽 3（+：4）张牌；否则进入平静
    if bc.player.stance == Stance.CALM:
        bc.add_to_bot(Actions.draw_cards(4 if item.card.upgraded else 3))
    else:
        bc.add_to_bot(_change_stance(Stance.CALM))


def _like_water_play(bc: BattleContext, item: CardQueueItem) -> None:
    # wiki：回合结束时若处于平静，获得 5 格挡（+：7）。引擎按层直读
    #（已接 5×1 语义——层=格挡数），此处落 5/7 层
    bc.add_to_bot(Actions.buff_player(PlayerStatus.LIKE_WATER, 7 if item.card.upgraded else 5))


def _meditate_play(bc: BattleContext, item: CardQueueItem) -> None:
    # wiki：从弃牌堆选 1（+：2）张牌到手牌并保留它们。进入平静。结束
    # 你的回合
    n = 2 if item.card.upgraded else 1

    def run(bc2: BattleContext) -> None:
        cands = list(bc2.cards.discard_pile)

        def on_choose(bc3: BattleContext, chosen: list) -> None:
            for inst in chosen:
                bc3.cards.discard_pile.remove(inst)
                inst.retain = True
                _add_to_hand(bc3, inst)

        bc2.open_card_select(cands, on_choose, pick_count=n, can_pick_zero=True,
                             prompt=f"冥思：选择至多 {n} 张弃牌回到手牌并保留")

    bc.add_to_bot(Action(run))
    bc.add_to_bot(_change_stance(Stance.CALM))
    bc.add_to_bot(Action(lambda bc2: _end_turn_from_play(bc2)))


def _mental_fortress_play(bc: BattleContext, item: CardQueueItem) -> None:
    # wiki：每切换一次姿态获得 4 格挡（+：6）——引擎 MENTAL_FORTRESS 结算
    # 常量 3×层（wiki 4/6），偏差列入迁移报告；此处按"层数=卡"落位
    bc.add_to_bot(Actions.buff_player(PlayerStatus.MENTAL_FORTRESS, 1))


def _nirvana_play(bc: BattleContext, item: CardQueueItem) -> None:
    # wiki：每当你检视，获得 3 格挡（+：4）——Scry 结算无内容钩子，
    # special["nirvana"] 存每次格挡量，接线需求见迁移报告
    bc.add_to_bot(Action(lambda bc2: bc2.player.special.update(
        nirvana=4 if item.card.upgraded else 3)))


def _perseverance_play(bc: BattleContext, item: CardQueueItem) -> None:
    # wiki：保留。获得 5 格挡（+：7）。此牌被保留时，本场战斗格挡 +2
    #（+：3）——增量在 Retain 时点（回合末），引擎缺保留触发钩子：实例
    # misc_data 即增量累计位，play 读之；增量时机接线需求见迁移报告
    bonus = 3 if item.card.upgraded else 2
    total = (7 if item.card.upgraded else 5) + item.card.misc_data
    bc.add_to_bot(Actions.gain_block(bc.calculate_card_block(total)))


def _pray_play(bc: BattleContext, item: CardQueueItem) -> None:
    # wiki：获得 3 层（+：4）真言。洗入 1 张洞见
    bc.add_to_bot(_gain_mantra(4 if item.card.upgraded else 3))
    bc.add_to_bot(_shuffle_created_into_draw(INSIGHT))


def _reach_heaven_play(bc: BattleContext, item: CardQueueItem) -> None:
    # wiki：造成 10 伤（+：15）。洗入 1 张穿透暴力
    dmg = bc.calculate_card_damage(item, item.target, 15 if item.card.upgraded else 10)
    bc.add_to_bot(Actions.attack_enemy(item.target, dmg))
    bc.add_to_bot(_shuffle_created_into_draw(THROUGH_VIOLENCE))


def _rushdown_play(bc: BattleContext, item: CardQueueItem) -> None:
    # wiki：每当你进入愤怒，抽 2 张牌（升级仅改费 1→0）——引擎 RUSHDOWN
    # 已接（进愤怒抽 2×层）
    bc.add_to_bot(Actions.buff_player(PlayerStatus.RUSHDOWN, 1))


def _sanctity_play(bc: BattleContext, item: CardQueueItem) -> None:
    # wiki：获得 6 格挡（+：9）。若上一张打出的牌是技能牌，抽 2 张牌
    bc.add_to_bot(Actions.gain_block(bc.calculate_card_block(9 if item.card.upgraded else 6)))
    if _prev_played_ctype(bc) == "Skill":
        bc.add_to_bot(Actions.draw_cards(2))


def _sands_of_time_play(bc: BattleContext, item: CardQueueItem) -> None:
    # wiki：保留。造成 20 伤（+：26）。此牌被保留时，本场战斗费用 -1
    #（4 费起步）——费用递减在 Retain 时点，引擎缺保留触发钩子
    #（cost_override 即累计位），接线需求见迁移报告
    dmg = bc.calculate_card_damage(item, item.target, 26 if item.card.upgraded else 20)
    bc.add_to_bot(Actions.attack_enemy(item.target, dmg))


def _signature_move_condition(bc: BattleContext, inst: CardInstance) -> bool:
    # wiki：只有当此牌是手牌中唯一的攻击牌时才能打出（play_card 校验时
    # 此牌仍在手，故条件 = 手中攻击牌恰 1 张）
    return sum(1 for c in bc.cards.hand if c.card.ctype == "Attack") == 1


def _signature_move_play(bc: BattleContext, item: CardQueueItem) -> None:
    # wiki：造成 30 伤（+：40）
    dmg = bc.calculate_card_damage(item, item.target, 40 if item.card.upgraded else 30)
    bc.add_to_bot(Actions.attack_enemy(item.target, dmg))


def _simmering_fury_play(bc: BattleContext, item: CardQueueItem) -> None:
    # wiki：下回合开始时进入愤怒并抽 2（+：3）张牌——WRATH_NEXT_TURN 引擎
    # 已接；额外抽牌走 special["next_turn_draw"]（引擎已接）
    bc.add_to_bot(Actions.buff_player(PlayerStatus.WRATH_NEXT_TURN, 1))
    n = 3 if item.card.upgraded else 2
    bc.add_to_bot(Action(lambda bc2: bc2.player.special.update(
        next_turn_draw=bc2.player.special.get("next_turn_draw", 0) + n)))


def _study_play(bc: BattleContext, item: CardQueueItem) -> None:
    # wiki：每回合结束时洗入 1 张洞见（+：费用 2→1）。回合末无内容钩子
    # ——special["study"] 存层数，接线需求见迁移报告
    bc.add_to_bot(Action(lambda bc2: bc2.player.special.update(
        study=bc2.player.special.get("study", 0) + 1)))


def _swivel_play(bc: BattleContext, item: CardQueueItem) -> None:
    # wiki：获得 8 格挡（+：11）。你的下一张攻击牌费用变为 0——"下一张"
    # 一次性减费无引擎表达位（dynamic_cost 是模板级），special["swivel"]
    # 落槽，接线需求见迁移报告
    bc.add_to_bot(Actions.gain_block(bc.calculate_card_block(11 if item.card.upgraded else 8)))
    bc.add_to_bot(Action(lambda bc2: bc2.player.special.update(swivel=1)))


def _talk_to_the_hand_play(bc: BattleContext, item: CardQueueItem) -> None:
    # wiki：造成 5 伤（+：7）。每当你攻击该敌人，获得 2（+：3）格挡——
    # MonsterStatus.BLOCK_RETURN 枚举引擎已预留、触发段未接：此处落状态
    # 层数，接线需求见迁移报告
    dmg = bc.calculate_card_damage(item, item.target, 7 if item.card.upgraded else 5)
    bc.add_to_bot(Actions.attack_enemy(item.target, dmg))
    bc.add_to_bot(Actions.debuff_enemy(item.target, MonsterStatus.BLOCK_RETURN,
                                        3 if item.card.upgraded else 2, False))


def _tantrum_play(bc: BattleContext, item: CardQueueItem) -> None:
    # wiki：造成 3 伤 3（+：4）次。进入愤怒。将此牌洗入抽牌堆——本体语义
    # 是这张实例本身而非副本：由出牌收尾 on_after_use_card 的
    # shuffle_back_into_draw_pile 分支处理（对齐本体 UseCardAction 的
    # moveToDeck(shuffle) / C++ onAfterUseCard 的 TANTRUM 分支），效果动作
    # 只负责伤害与转姿
    dmg = bc.calculate_card_damage(item, item.target, 3)
    for _ in range(4 if item.card.upgraded else 3):
        bc.add_to_bot(Actions.attack_enemy(item.target, dmg))
    bc.add_to_bot(_change_stance(Stance.WRATH))


def _wallop_play(bc: BattleContext, item: CardQueueItem) -> None:
    # wiki：造成 9 伤（+：12）。获得等同未被格挡吸收伤害的格挡
    base = 12 if item.card.upgraded else 9
    t = item.target

    def run(bc2: BattleContext) -> None:
        m = bc2.monsters.monsters[t]
        if m.is_dead_or_escaped():
            return
        pre_block = m.block
        dmg = bc2.calculate_card_damage(bc2.cur_card_queue_item, t, base)
        m.attacked(bc2, dmg)
        unblocked = dmg - (pre_block - m.block)
        if unblocked > 0 and bc2.outcome == Outcome.UNDECIDED:
            bc2.player.gain_block(bc2, unblocked)

    bc.add_to_bot(Action(run))


def _wave_of_the_hand_play(bc: BattleContext, item: CardQueueItem) -> None:
    # wiki：本回合每当你获得格挡，对所有敌人施加 1 层（+：2）虚弱——
    # 格挡获得触发无内容钩子，special["wave_of_the_hand"] 落槽（引擎
    # 接线时需按回合清零），接线需求见迁移报告
    bc.add_to_bot(Action(lambda bc2: bc2.player.special.update(
        wave_of_the_hand=2 if item.card.upgraded else 1)))


def _weave_play(bc: BattleContext, item: CardQueueItem) -> None:
    # wiki：造成 4 伤（+：6）。每当你检视，此牌从弃牌堆回到手牌——Scry
    # 结算无内容钩子，special["weave_recall"] 落槽，接线需求见迁移报告
    dmg = bc.calculate_card_damage(item, item.target, 6 if item.card.upgraded else 4)
    bc.add_to_bot(Actions.attack_enemy(item.target, dmg))
    bc.add_to_bot(Action(lambda bc2: bc2.player.special.update(weave_recall=1)))


def _wheel_kick_play(bc: BattleContext, item: CardQueueItem) -> None:
    # wiki：造成 15 伤（+：20）。抽 2 张牌
    dmg = bc.calculate_card_damage(item, item.target, 20 if item.card.upgraded else 15)
    bc.add_to_bot(Actions.attack_enemy(item.target, dmg))
    bc.add_to_bot(Actions.draw_cards(2))


def _windmill_strike_play(bc: BattleContext, item: CardQueueItem) -> None:
    # wiki：保留。造成 7 伤（+：10）。此牌被保留时，本场战斗伤害 +4
    #（+：5）——增量在 Retain 时点，引擎缺保留触发钩子（misc_data 为
    # 累计位，play 读之），接线需求见迁移报告
    bonus_per = 5 if item.card.upgraded else 4
    total = (10 if item.card.upgraded else 7) + item.card.misc_data
    dmg = bc.calculate_card_damage(item, item.target, total)
    bc.add_to_bot(Actions.attack_enemy(item.target, dmg))


def _worship_play(bc: BattleContext, item: CardQueueItem) -> None:
    # wiki：获得 5 层真言（+：保留）。5 层不足直接进 Divinity（配合已有
    # 真言累计可以满 10——_gain_mantra 满即进 Divinity 且 +3 能量）
    bc.add_to_bot(_gain_mantra(5))


def _wreath_of_flame_play(bc: BattleContext, item: CardQueueItem) -> None:
    # wiki：你的下一张攻击牌 +5（+：8）伤害——引擎 VIGOR 语义完全吻合
    #（calculate_card_damage 计入 + on_use_attack_card 出伤后整体移除），
    # 全流程可用
    bc.add_to_bot(Actions.buff_player(PlayerStatus.VIGOR, 8 if item.card.upgraded else 5))


BATTLE_HYMN = CardDef("Battle Hymn", "战歌", 1, "Power",
                      "在每回合开始时，将一张惩恶加入你的手牌。", False, False,
                      _battle_hymn_play, innate_when_upgraded=True)
CARVE_REALITY = CardDef("Carve Reality", "改造现实", 1, "Attack",
                        "造成 6 点伤害。\n将一张惩恶加入你的手牌。", True, False,
                        _carve_reality_play)
COLLECT = CardDef("Collect", "收集", -1, "Skill",
                  "在你的下X个回合开始时，增加一张奇迹+ 到你的手牌。\n消耗。",
                  False, True, _collect_play, x_cost=True)
CONCLUDE = CardDef("Conclude", "结末", 1, "Attack",
                   "对所有敌人造成 12 点伤害。\n结束你的回合。",
                   False, False, _conclude_play)
DECEIVE_REALITY = CardDef("Deceive Reality", "欺瞒现实", 1, "Skill",
                          "获得 4 点格挡。\n将一张平安加入你的手牌。",
                          False, False, _deceive_reality_play)
EMPTY_MIND = CardDef("Empty Mind", "化智为空", 1, "Skill",
                     "抽 2 张牌。\n退出当前姿态。", False, False, _empty_mind_play)
FASTING = CardDef("Fasting", "斋戒", 2, "Power",
                  "获得 3 点力量。\n获得 3 敏捷。\n每回合开始时少获得 1 点能量。",
                  False, False, _fasting_play)
FEAR_NO_EVIL = CardDef("Fear No Evil", "不惧妖邪", 1, "Attack",
                       "造成 8 点伤害。\n如果目标敌人的意图是攻击，则进入平静。",
                       True, False, _fear_no_evil_play)
FOREIGN_INFLUENCE = CardDef("Foreign Influence", "他山之石", 0, "Skill",
                            "从 3 张任意颜色的攻击牌中选择 1 张加入你的手牌。\n消耗。",
                            False, True, _foreign_influence_play)
FORESIGHT = CardDef("Foresight", "先见之明", 1, "Power",
                    "在你的回合开始时，预见 3。", False, False, _foresight_play)
INDIGNATION = CardDef("Indignation", "义愤填膺", 1, "Skill",
                      "愤怒：给予所有敌人 3 层易伤。\n否则，进入愤怒。",
                      False, False, _indignation_play)
INNER_PEACE = CardDef("Inner Peace", "内心宁静", 1, "Skill",
                      "平静：抽 3 张牌。\n否则，进入平静。",
                      False, False, _inner_peace_play)
LIKE_WATER = CardDef("Like Water", "如水", 1, "Power",
                     "在你的回合结束时，如果你处于平静，则获得 5 点格挡。", False, False, _like_water_play)
MEDITATE = CardDef("Meditate", "冥想", 1, "Skill",
                   "将弃牌堆中的一张牌放入你的手牌，并将其保留。\n进入平静。\n结束你的回合。",
                   False, False, _meditate_play)
MENTAL_FORTRESS = CardDef("Mental Fortress", "心灵堡垒", 1, "Power",
                          "每当你转换姿态时，获得 4 点格挡。", False, False, _mental_fortress_play)
NIRVANA = CardDef("Nirvana", "涅槃", 1, "Power",
                  "你每次预见时，获得 3 点格挡。", False, False, _nirvana_play)
PERSEVERANCE = CardDef("Perseverance", "坚韧", 1, "Skill",
                       "保留。\n获得 5 点格挡。\n每当这张牌被保留时，将其在本场战斗的格挡增加 2 点。",
                       False, False, _perseverance_play, self_retain=True)
PRAY = CardDef("Pray", "祈祷", 1, "Skill",
               "获得 3 层真言。\n在你的抽牌堆中加入 1 张洞见。", False, False, _pray_play)
REACH_HEAVEN = CardDef("Reach Heaven", "立地升天", 2, "Attack",
                       "造成 10 点伤害。在你的抽牌堆中加入 1 张\n以暴易暴。",
                       True, False, _reach_heaven_play)
RUSHDOWN = CardDef("Rushdown", "猛虎下山", 1, "Power",
                   "每当你进入愤怒时，抽 2 张牌。", False, False,
                   _rushdown_play, upgraded_cost=0)
SANCTITY = CardDef("Sanctity", "圣洁", 1, "Skill",
                   "获得 6 点格挡。\n如果本场战斗中打出的上一张牌是技能牌，抽 2 张牌。",
                   False, False, _sanctity_play)
SANDS_OF_TIME = CardDef("Sands of Time", "时之沙", 4, "Attack",
                        "保留。\n造成 20 点伤害。\n每当这张牌被保留时，将其在本场战斗的耗能减少 1。",
                        True, False, _sands_of_time_play, self_retain=True)
SIGNATURE_MOVE = CardDef("Signature Move", "招牌技", 2, "Attack",
                         "只有当这张牌是你手中唯一的一张攻击牌时才可以被打出。造成 30 点伤害。",
                         True, False, _signature_move_play, play_condition=_signature_move_condition)
SIMMERING_FURY = CardDef("Simmering Fury", "怒火中烧", 1, "Skill",
                         "在你的下个回合开始时，进入愤怒并抽 2 张牌。",
                         False, False, _simmering_fury_play)
STUDY = CardDef("Study", "研习", 2, "Power",
                "在你的回合结束时，在你的抽牌堆中加入一张洞见。", False, False, _study_play, upgraded_cost=1)
SWIVEL = CardDef("Swivel", "旋身", 2, "Skill",
                 "获得 8 点格挡。\n你打出的下一张攻击牌耗能变为 0。", False, False, _swivel_play)
TALK_TO_THE_HAND = CardDef("Talk to the Hand", "以手拒之", 1, "Attack",
                           "造成 5 点伤害。\n每当目标敌人受到攻击时，你获得 2 点格挡。\n消耗。",
                           True, True, _talk_to_the_hand_play)
TANTRUM = CardDef("Tantrum", "发泄", 1, "Attack",
                  "造成 3 点伤害 3 次。\n进入愤怒。\n将这张牌放入你的抽牌堆。",
                  True, False, _tantrum_play,
                  shuffle_back_into_draw_pile=True)
WALLOP = CardDef("Wallop", "当头棒喝", 2, "Attack",
                 "造成 9 点伤害。\n获得与所造成的未被格挡的伤害相等的格挡。",
                 True, False, _wallop_play)
WAVE_OF_THE_HAND = CardDef("Wave of the Hand", "摆手", 1, "Skill",
                           "在本回合，你每次获得格挡时，给予所有敌人 1 层虚弱。", False, False, _wave_of_the_hand_play)
WEAVE = CardDef("Weave", "迂回", 0, "Attack",
                "造成 4 点伤害。\n你每次预见时，将这张牌从弃牌堆放回你的手牌。", True, False, _weave_play)
WHEEL_KICK = CardDef("Wheel Kick", "回环踢", 2, "Attack",
                     "造成 15 点伤害。\n抽 2 张牌。", True, False, _wheel_kick_play)
WINDMILL_STRIKE = CardDef("Windmill Strike", "旋转打击", 2, "Attack",
                          "保留。\n造成 7 点伤害。\n每当这张牌被保留时，将其在本场战斗的伤害增加 4 点。",
                          True, False, _windmill_strike_play, self_retain=True)
WORSHIP = CardDef("Worship", "敬拜", 2, "Skill",
                  "获得 5 层真言。", False, False, _worship_play,
                  retain_when_upgraded=True)
WREATH_OF_FLAME = CardDef("Wreath of Flame", "火焰纹", 1, "Skill",
                          "你的下一张攻击牌造成 5 点额外伤害。",
                          False, False, _wreath_of_flame_play)


# ============================================================
# 稀有 17 张
# ============================================================


def _alpha_play(bc: BattleContext, item: CardQueueItem) -> None:
    # wiki：洗入 1 张贝塔（+：固有）。消耗。Alpha→Beta→Omega 链起点
    bc.add_to_bot(_shuffle_created_into_draw(BETA))


def _blasphemy_play(bc: BattleContext, item: CardQueueItem) -> None:
    # wiki：进入 Divinity（+3 能量、攻击 ×3 至回合结束——乘区引擎已接）。
    # 下回合开始时死亡（Blasphemer 99999 自伤）——special["blasphemy_die"]
    # 落槽，引擎回合开始死亡结算接线需求见迁移报告。消耗（+：保留）
    bc.add_to_bot(_change_stance(Stance.DIVINITY))
    bc.add_to_bot(Action(lambda bc2: bc2.player.special.update(blasphemy_die=1)))


def _brilliance_play(bc: BattleContext, item: CardQueueItem) -> None:
    # wiki：造成 12 伤（+：16），额外伤害 = 本场战斗获得的真言数
    #（special["mantra_gained"] 由 _gain_mantra 维护；Devotion 状态经引擎
    # 结算的真言不计入——缺口见迁移报告）
    bonus = bc.player.special.get("mantra_gained", 0)
    dmg = bc.calculate_card_damage(item, item.target,
                                   (16 if item.card.upgraded else 12) + bonus)
    bc.add_to_bot(Actions.attack_enemy(item.target, dmg))


def _conjure_blade_play(bc: BattleContext, item: CardQueueItem) -> None:
    # wiki：洗入 1 张肃清者，其段数 X = 消耗的能量（+：X+1；可为 0 段）。
    # 肃清者实例的 misc_data 存段数（Master Reality 升级其 9→15 基伤）
    times = max(item.energy_on_use, 0) + (1 if item.card.upgraded else 0)

    def run(bc2: BattleContext) -> None:
        inst = bc2.cards.instantiate(EXPUNGER)
        inst.upgraded = _mr(bc2)
        inst.misc_data = times
        pos = (bc2.rngs.misc.int_inclusive(0, len(bc2.cards.draw_pile))
               if bc2.cards.draw_pile else 0)
        bc2.cards.draw_pile.insert(pos, inst)

    bc.add_to_bot(Action(run))


def _deus_ex_machina_on_drawn(bc: BattleContext, inst: CardInstance) -> None:
    # wiki：不可打出。抽到此牌时，加 2（+：3）张奇迹到手牌并消耗此牌
    #（on_drawn_effect 引擎钩子已接）。手满时奇迹落弃牌堆（引擎
    # create_temp_card_in_hand 兜底）；自身消耗按所在堆检索
    n = 3 if inst.upgraded else 2
    for _ in range(n):
        bc.cards.create_temp_card_in_hand(MIRACLE, _mr(bc))
    for pile in (bc.cards.hand, bc.cards.discard_pile):
        if inst in pile:
            pile.remove(inst)
            break
    bc.cards.move_to_exhaust_pile(inst)
    bc.on_card_exhausted(inst)


def _deva_form_play(bc: BattleContext, item: CardQueueItem) -> None:
    # wiki：虚无（升级后不再虚无——CardDef.ethereal 为静态位，表达不了
    # "仅基础版虚无"，此处置 True、升级版误消散的缺口见迁移报告）。
    # 每回合开始获得 1 点能量且该增益每回合 +1——special["deva_form"] 存
    # 份数（各份独立爬坡），回合开始结算接线需求见迁移报告
    bc.add_to_bot(Action(lambda bc2: bc2.player.special.update(
        deva_form=bc2.player.special.get("deva_form", 0) + 1)))


def _devotion_play(bc: BattleContext, item: CardQueueItem) -> None:
    # wiki：每回合开始时获得 2 层（+：3）真言——引擎 DEVOTION 已接
    #（apply_start_of_turn_post_draw_powers → Actions.gain_mantra）。注意
    # 这份真言走引擎路径：不计入 Brilliance 计数、满 10 的 Divinity 进入
    # 无 +3 能量（缺口见迁移报告）
    bc.add_to_bot(Actions.buff_player(PlayerStatus.DEVOTION, 3 if item.card.upgraded else 2))


def _establishment_play(bc: BattleContext, item: CardQueueItem) -> None:
    # wiki：每当有牌被保留，该牌本场战斗费用 -1（+：固有）——保留时点无
    # 内容钩子，special["establishment"] 落槽，接线需求见迁移报告
    bc.add_to_bot(Action(lambda bc2: bc2.player.special.update(establishment=1)))


def _judgment_play(bc: BattleContext, item: CardQueueItem) -> None:
    # wiki：若该敌人 HP ≤30（+：40），将其 HP 置 0（直杀，走 die() 判胜）
    threshold = 40 if item.card.upgraded else 30
    t = item.target

    def run(bc2: BattleContext) -> None:
        m = bc2.monsters.monsters[t]
        if m.is_dead_or_escaped():
            return
        if m.hp <= threshold:
            m.hp = 0
            m.die(bc2)
            bc2.check_combat()

    bc.add_to_bot(Action(run))


def _lesson_learned_play(bc: BattleContext, item: CardQueueItem) -> None:
    # wiki：造成 10 伤（+：13）。若此伤害致命，永久升级牌组中 1 张随机牌
    #——"永久"是局外语义（战斗结束保留升级），本模拟仅战斗内：升级
    # 抽/手/弃三堆中 1 张随机牌；局外语义列入迁移报告
    dmg = bc.calculate_card_damage(item, item.target, 13 if item.card.upgraded else 10)
    t = item.target

    def run(bc2: BattleContext) -> None:
        m = bc2.monsters.monsters[t]
        if m.is_dead_or_escaped():
            return
        m.attacked(bc2, dmg)
        bc2.check_combat()
        if m.alive:
            return
        # 击杀成立即升级（战斗同时结束也不拦——永久升级在真实语义中跨战斗
        # 生效，此处为战斗内近似）
        pool = [c for c in (bc2.cards.draw_pile + bc2.cards.hand + bc2.cards.discard_pile)
                if not c.upgraded]
        if pool:
            pool[bc2.rngs.misc.int_inclusive(0, len(pool) - 1)].upgrade()

    bc.add_to_bot(Action(run))


def _master_reality_play(bc: BattleContext, item: CardQueueItem) -> None:
    # wiki：战斗中每当有牌被生成，将其升级（+：费用 1→0）。内容层生成
    # 路径（观者全部生成牌/Foreign Influence/Collect 等）经 _mr 即时生效；
    # 引擎侧生成（Shiv/伤口/诅咒等）的升级钩子缺，接线需求见迁移报告
    bc.add_to_bot(Action(lambda bc2: bc2.player.special.update(master_reality=1)))


def _omniscience_play(bc: BattleContext, item: CardQueueItem) -> None:
    # wiki：选择抽牌堆中的 1 张牌。打出该牌两次并消耗它（+：费用 4→3）。
    # 两张队列项共用同一实例：首项 purge（打完即消失）、次项
    # exhaust_on_use（打完落消耗堆）；随机目标（原牌目标语义由引擎
    # random_target 路径覆盖）
    def run(bc2: BattleContext) -> None:
        cands = list(bc2.cards.draw_pile)

        def on_choose(bc3: BattleContext, chosen: list) -> None:
            for inst in chosen:
                bc3.cards.draw_pile.remove(inst)
                bc3.add_to_bot_card(CardQueueItem(
                    card=inst, random_target=True, autoplay=True, purge_on_use=True))
                bc3.add_to_bot_card(CardQueueItem(
                    card=inst, random_target=True, autoplay=True, exhaust_on_use=True))

        bc2.open_card_select(cands, on_choose, can_pick_zero=True,
                             prompt="全知全能：选择抽牌堆 1 张牌，打出两次并消耗")

    bc.add_to_bot(Action(run))


def _ragnarok_play(bc: BattleContext, item: CardQueueItem) -> None:
    # wiki：对随机敌人造成 5 伤（+：6）5（+：6）次——引擎
    # attack_random_enemy 每段独立随机目标 + 独立走攻击管线
    n = 6 if item.card.upgraded else 5
    bc.add_to_bot(Actions.attack_random_enemy(n, n))


def _scrawl_play(bc: BattleContext, item: CardQueueItem) -> None:
    # wiki：抽牌直到手牌满（+：费用 1→0）。消耗
    def run(bc2: BattleContext) -> None:
        need = MAX_HAND_SIZE - len(bc2.cards.hand)
        if need > 0:
            bc2.draw_cards(need)

    bc.add_to_bot(Action(run))


def _spirit_shield_play(bc: BattleContext, item: CardQueueItem) -> None:
    # wiki：每有 1 张手牌获得 3 格挡（+：4）。单次格挡获得（敏捷计入一次）；
    # 结算时读手牌数（自身打出时已离手，不计）
    per = 4 if item.card.upgraded else 3

    def run(bc2: BattleContext) -> None:
        n = len(bc2.cards.hand)
        if n > 0:
            bc2.add_to_bot(Actions.gain_block(bc2.calculate_card_block(per * n)))

    bc.add_to_bot(Action(run))


def _vault_play(bc: BattleContext, item: CardQueueItem) -> None:
    # wiki：在这之后进行一个额外回合。结束你的回合。消耗（+：费用 3→2）。
    # 内容层降级实现（任务口径）：结束本回合且跳过敌方阶段——置
    # skip_monster_turn（引擎回合流转已读此位：敌方不行动、跳过回合末
    # 衰减），回合照常 +1 并重抽重充能，净效果 ≈ 额外回合。与本体差异
    #（跳过回合末状态衰减、无敌方意图推进）见迁移报告
    bc.skip_monster_turn = True
    bc.add_to_bot(Action(lambda bc2: _end_turn_from_play(bc2)))


def _wish_play(bc: BattleContext, item: CardQueueItem) -> None:
    # wiki：三选一（本体为生成并立即打出 Live Forever / Become Almighty /
    # Fame and Fortune 三张子牌；此处以选卡界面 + 直接结算等价表达——
    # 子牌不进手牌不入组，与本体一致）：6（+：8）层重甲 / 3（+：4）力量 /
    # 25（+：30）金币。消耗
    up = item.card.upgraded

    class _WishOption:
        def __init__(self, name: str, zh: str, apply) -> None:
            self.name = name
            self.zh = zh
            self.apply = apply

    pa = 8 if up else 6
    st = 4 if up else 3
    gold = 30 if up else 25

    def run(bc2: BattleContext) -> None:
        opts = [
            _WishOption("Live Forever", "不朽",
                        lambda bc3: bc3.player.statuses.add(PlayerStatus.PLATED_ARMOR, pa)),
            _WishOption("Become Almighty", "化身为神",
                        lambda bc3: bc3.player.statuses.add(PlayerStatus.STRENGTH, st)),
            _WishOption("Fame and Fortune", "名利双收",
                        lambda bc3: setattr(bc3.player, "gold", bc3.player.gold + gold)),
        ]

        def on_choose(bc3: BattleContext, chosen: list) -> None:
            for opt in chosen:
                opt.apply(bc3)

        bc2.open_card_select(opts, on_choose, prompt="祈愿：三选一")

    bc.add_to_bot(Action(run))


ALPHA = CardDef("Alpha", "阿尔法", 1, "Skill",
                "将一张贝塔放入你的抽牌堆中。\n消耗。", False, True, _alpha_play,
                innate_when_upgraded=True)
BLASPHEMY = CardDef("Blasphemy", "渎神", 1, "Skill",
                    "进入神格。\n在下回合死亡。\n消耗。", False, True,
                    _blasphemy_play, retain_when_upgraded=True)
BRILLIANCE = CardDef("Brilliance", "光辉", 1, "Attack",
                     "造成 12 点伤害。\n额外造成本场战斗中获得的真言总层数的伤害。",
                     True, False, _brilliance_play)
CONJURE_BLADE = CardDef("Conjure Blade", "聚能成刃", -1, "Skill",
                        "将一张灭除之刃放入你的抽牌堆中。\n消耗。",
                        False, True, _conjure_blade_play, x_cost=True)
DEUS_EX_MACHINA = CardDef("Deus Ex Machina", "机械降神", -2, "Skill",
                          "不能被打出。\n当你抽到这张牌时，在你的手牌中加入 2 张奇迹，然后消耗。",
                          False, True, _unplayable_noop, unplayable=True,
                          on_drawn_effect=_deus_ex_machina_on_drawn)
DEVA_FORM = CardDef("Deva Form", "天人形态", 3, "Power",
                    "虚无。\n在你的回合开始时获得 1 点能量，每回合增加 1。", False, False, _deva_form_play, ethereal=True)
DEVOTION = CardDef("Devotion", "虔信", 1, "Power",
                   "在你的回合开始时，获得 2 层真言。", False, False, _devotion_play)
ESTABLISHMENT = CardDef("Establishment", "确立基础", 1, "Power",
                        "每当有卡牌被保留时，将其在本场战斗的耗能减少 1。", False, False, _establishment_play,
                        innate_when_upgraded=True)
JUDGMENT = CardDef("Judgment", "审判", 1, "Skill",
                   "如果目标敌人的生命值小于等于 30 点，\n则将其生命值变为 0。", True, False,
                   _judgment_play)
LESSON_LEARNED = CardDef("Lesson Learned", "勤学精进", 2, "Attack",
                         "造成 10 点伤害。\n斩杀时，升级你牌组中的一张随机牌。消耗。",
                         True, True, _lesson_learned_play)
MASTER_REALITY = CardDef("Master Reality", "操控现实", 1, "Power",
                         "所有在战斗中临时增加的牌将被升级。", False, False,
                         _master_reality_play, upgraded_cost=0)
OMNISCIENCE = CardDef("Omniscience", "通晓万物", 4, "Skill",
                      "选择你抽牌堆中的一张牌。将这张牌打出两次然后将其消耗。\n消耗。",
                      False, True, _omniscience_play, upgraded_cost=3)
RAGNAROK = CardDef("Ragnarok", "诸神之黄昏", 3, "Attack",
                   "随机对敌人造成 5 点伤害 5 次。", False, False,
                   _ragnarok_play)
SCRAWL = CardDef("Scrawl", "潦草急就", 1, "Skill",
                 "抽牌直到将手牌抽满。\n消耗。", False, True, _scrawl_play,
                 upgraded_cost=0)
SPIRIT_SHIELD = CardDef("Spirit Shield", "精神护盾", 2, "Skill",
                        "你每有一张手牌，获得 3 点格挡。", False, False,
                        _spirit_shield_play)
VAULT = CardDef("Vault", "腾跃", 3, "Skill",
               "在本回合结束后，额外获得一回合。\n结束你的回合。\n消耗。", False, True, _vault_play, upgraded_cost=2)
WISH = CardDef("Wish", "许愿", 3, "Skill",
               "选择：获得 6 层多层护甲、 3 点力量、或 25 金币。\n消耗。",
               False, True, _wish_play)


def _unraveling_play(bc: BattleContext, item: CardQueueItem) -> None:
    # 2026-10-07 补齐：Unraveling.java（purple rare）→ UnravelingAction：
    # 执行时快照手牌，逐张压入卡牌队列（freeToPlayOnce → 免费播放，
    # needs_target 的随机目标）。autoplay 项不收能量（对齐 Havoc 的
    # 免费播放口径）；手牌移除在入队时统一完成（play_card 的弹手牌在
    # 此路径不存在，on_after_use_card 的 move_to_* 不做手牌移除）。
    def run(bc2: BattleContext) -> None:
        for inst in list(bc2.cards.hand):
            bc2.cards.hand.remove(inst)
            bc2.add_to_bot_card(
                CardQueueItem(card=inst, random_target=True, autoplay=True)
            )

    bc.add_to_bot(Action(run))


UNRAVELING = CardDef("Unraveling", "彻悟", 2, "Skill",
                     "从左至右打出你手牌中的所有牌。需要选择目标的牌将随机选择目标。\n消耗。",
                     False, True, _unraveling_play, upgraded_cost=1)


__all__ = [
    # 基础
    "DEFEND_W", "ERUPTION", "STRIKE_W", "VIGILANCE",
    # 生成牌
    "BETA", "EXPUNGER", "INSIGHT", "MIRACLE", "OMEGA", "SAFETY", "SMITE",
    "THROUGH_VIOLENCE",
    # 普通
    "BOWLING_BASH", "CONSECRATE", "CRESCENDO", "CRUSH_JOINTS", "CUT_THROUGH_FATE",
    "EMPTY_BODY", "EMPTY_FIST", "EVALUATE", "FLURRY_OF_BLOWS", "FLYING_SLEEVES",
    "FOLLOW_UP", "HALT", "JUST_LUCKY", "PRESSURE_POINTS", "PROSTRATE", "PROTECT",
    "SASH_WHIP", "THIRD_EYE", "TRANQUILITY",
    # 非普通
    "BATTLE_HYMN", "CARVE_REALITY", "COLLECT", "CONCLUDE", "DECEIVE_REALITY",
    "EMPTY_MIND", "FASTING", "FEAR_NO_EVIL", "FOREIGN_INFLUENCE", "FORESIGHT",
    "INDIGNATION", "INNER_PEACE", "LIKE_WATER", "MEDITATE", "MENTAL_FORTRESS",
    "NIRVANA", "PERSEVERANCE", "PRAY", "REACH_HEAVEN", "RUSHDOWN", "SANCTITY",
    "SANDS_OF_TIME", "SIGNATURE_MOVE", "SIMMERING_FURY", "STUDY", "SWIVEL",
    "TALK_TO_THE_HAND", "TANTRUM", "WALLOP", "WAVE_OF_THE_HAND", "WEAVE",
    "WHEEL_KICK", "WINDMILL_STRIKE", "WORSHIP", "WREATH_OF_FLAME",
    # 稀有
    "ALPHA", "BLASPHEMY", "BRILLIANCE", "CONJURE_BLADE", "DEUS_EX_MACHINA",
    "DEVA_FORM", "DEVOTION", "ESTABLISHMENT", "JUDGMENT", "LESSON_LEARNED",
    "MASTER_REALITY", "OMNISCIENCE", "RAGNAROK", "SCRAWL", "SPIRIT_SHIELD",
    "UNRAVELING", "VAULT", "WISH",
]

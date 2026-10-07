"""诅咒卡正式定义（对齐 lightspeed curseCardPool 全 10 张 + 特殊诅咒 4 张）。

来源与保真度口径：
- 结算路径以 lightspeed C++ 为准——callEndTurnActions
  （BattleContext.cpp L2082-2102：按手牌顺序把 no-trigger 卡入队，
  regretCardCount = 入队时的完整手牌数）+ useNoTriggerCard（L933-961：
  Burn/Decay 走 DamagePlayer **吃格挡**、Regret 走 PlayerLoseHp **不吃
  格挡**、Doubt/Shame 直接 debuff 且置 justApplied）+ CardPools.h L63
  curseCardPool + BattleContext.cpp L2836-2837（Necronomicurse 的
  triggerOnExhaust 复制入手）。Curse of the Bell 在 C++ 里的同款复制
  系 lightspeed 笔误，wiki 无此效果，2026-10-06 审计已移除（见下方注释）。
- 数值/文本与本体反编译交叉校验：Regret.java（magicNumber=hand.size()
  **含自身**，LoseHPAction 不吃格挡）、Pride.java（cost 1 **可打出**、
  exhaust、isInnate、回合末 MakeTempCardInDrawPile **置顶复制**、原牌随
  弃牌阶段弃置）、Necronomicurse.java（triggerOnExhaust → 复制入手）。
  与 C++ / 本体不一致处在各卡注释记录。

回合末结算协议（引擎 battle.py 批次 0 已接线）：
call_end_turn_actions 按手牌顺序把带 no_trigger_effect 的卡入队 →
use_no_trigger_card 逐张「先移出手牌 → 跑 no_trigger_effect → 进弃牌堆
（no_trigger_exhausts=True 则进消耗堆）」，时机在 on_turn_ending 弃手牌
之前，对齐 C++。

与包结构的关系：本文件为诅咒的唯一正式定义，经包 __init__ eager
re-export 暴露；CardDef 取自 _base.py，mark_no_trigger_processed 供
ironclad.py 的 _burn_effect 调用（无导入期循环）。状态卡
（Wound/Burn/Dazed/Slimed/Void）核对结论见迁移报告：数值与
结算路径均正确，留在 ironclad.py 不动。
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from sts.combat.actions import Actions
from sts.combat.types import PlayerStatus
from sts.content.cards._base import CardDef

if TYPE_CHECKING:
    from sts.combat.battle import BattleContext
    from sts.combat.card_manager import CardInstance
    from sts.combat.queue import CardQueueItem


# ============================================================
# 回合末 no-trigger 结算的公共设施
# ============================================================


def mark_no_trigger_processed(bc: "BattleContext", inst: "CardInstance | None") -> None:
    """标记"本回合末已完成 no-trigger 结算"的实例（Regret 计数用）。

    C++ 在 callEndTurnActions 入队时快照 regretCardCount = cardsInHand
    （结算前完整手牌数，含 Regret 自身与所有尚未结算的卡）；引擎
    use_no_trigger_card 则逐张"先离手再结算"，Regret 效果执行时读到的
    手牌数已不含先结算的卡。本标记把已结算实例与结算时的回合号绑定
    （bc.turn 在整个回合末结算期间不变，回合号即可区分本轮/上轮），
    _end_turn_hand_size 据此重建 C++ 的快照口径。所有 no-trigger 效果
    开头必须调用（ironclad.py 的 _burn_effect 有模块级导入调用）。
    """
    if inst is not None:
        inst._no_trigger_turn = bc.turn


def _end_turn_hand_size(bc: "BattleContext") -> int:
    """重建 C++ regretCardCount 口径：结算前的完整手牌数。

    = 当前手牌（普通手牌 + 尚未结算的 no-trigger 卡）+ 1（Regret 自身，
    引擎效果执行前已移出手牌）+ 本回合末已先行结算离手的 no-trigger 卡
    （弃牌堆/消耗堆中带本回合标记的实例）。跨回合的同类牌（旧回合标记）
    不会被计入。
    """
    processed = sum(
        1
        for pile in (bc.cards.discard_pile, bc.cards.exhaust_pile)
        for inst in pile
        if getattr(inst, "_no_trigger_turn", None) == bc.turn
    )
    return len(bc.cards.hand) + 1 + processed


def _unplayable_noop(bc: "BattleContext", item: "CardQueueItem") -> None:
    """不可打出诅咒的 play 占位：正常出牌被 play_card 的 unplayable 位
    拦截；Havoc/Mayhem 等强制入队结算时无效果（对齐 C++ useCard 的
    CURSE 分支，不进任何 useXxxCard switch）。"""
    pass


# ============================================================
# 诅咒池 10 张（CardPools.h L63 顺序）
# ============================================================


def _regret_effect(bc: "BattleContext", item: "CardQueueItem") -> None:
    # 对齐 C++ PlayerLoseHp(regretCardCount, true)：不吃格挡（LoseHPAction）；
    # self_inflicted=True 对齐 C++ selfDamage 位——lightspeed 口径下会触发
    # RUPTURE（hpWasLost 的 selfDamage 分支）。本体 Regret.java 的
    # magicNumber 在 triggerOnEndOfTurnForPlayingCard 时快照 = hand.size()，
    # 此时 Regret 仍在手 → 含自身。
    mark_no_trigger_processed(bc, item.card)
    bc.add_to_bot(Actions.player_lose_hp(_end_turn_hand_size(bc), self_inflicted=True))


def _shame_effect(bc: "BattleContext", item: "CardQueueItem") -> None:
    # 对齐 C++ player.debuff<FRAIL>(1, true)：isSourceMonster=true 置
    # justApplied——本回合末施加、跳过同回合末衰减，实际作用于下个玩家
    # 回合的格挡（本体 ApplyPowerAction 创建新 Power 时的 justApplied 等价）。
    mark_no_trigger_processed(bc, item.card)
    bc.add_to_bot(Actions.debuff_player(PlayerStatus.FRAIL, 1, True))


def _doubt_effect(bc: "BattleContext", item: "CardQueueItem") -> None:
    # 同 Shame，虚弱 1 层（对齐 C++ player.debuff<WEAK>(1, true)）。
    mark_no_trigger_processed(bc, item.card)
    bc.add_to_bot(Actions.debuff_player(PlayerStatus.WEAK, 1, True))


def _decay_effect(bc: "BattleContext", item: "CardQueueItem") -> None:
    # 对齐 C++ DamagePlayer(2, true)：走 damage 管线**吃格挡**（本体
    # Decay.java 的 DamageAction THORNS 伤害类型同样吃格挡；Regret 才是
    # 不吃格挡的 LoseHPAction 路径）。C++ selfDamage=true 在 lightspeed
    # 口径下会触发 RUPTURE——Actions.damage_player 已补 self_inflicted 位
    # 位，Decay/Burn 的掉血不触发 RUPTURE——已知偏差，见迁移报告。
    mark_no_trigger_processed(bc, item.card)
    bc.add_to_bot(Actions.damage_player(2, self_inflicted=True))


REGRET = CardDef("Regret", "悔恨", 0, "Curse",
                 "不能被打出。\n在你的回合结束时，失去相当于手牌数量的生命。",
                 False, False, _unplayable_noop,
                 unplayable=True, no_trigger_effect=_regret_effect)
INJURY = CardDef("Injury", "受伤", 0, "Curse",
                 "不能被打出。", False, False, _unplayable_noop, unplayable=True)
SHAME = CardDef("Shame", "羞耻", 0, "Curse",
                "不能被打出。\n在你的回合结束时，获得 1 层脆弱。",
                False, False, _unplayable_noop,
                unplayable=True, no_trigger_effect=_shame_effect)
PARASITE = CardDef("Parasite", "寄生", 0, "Curse",
                   "不能被打出。\n如果这张牌在你的牌组中被转化或移除，你失去 3 点最大生命。", False, False, _unplayable_noop, unplayable=True)
NORMALITY = CardDef("Normality", "凡庸", 0, "Curse",
                    "不能被打出。\n在手牌中时，你在此回合无法打出 3 张以上牌。",
                    False, False, _unplayable_noop, unplayable=True)
# Normality 的打出限制未实现（2026-10-07 wiki 复核修正文本）：wiki 规则是
# "While in hand, you cannot play more than 3 cards this turn."（该诅咒
# 不可打出，整回合滞留手中 → 本回合第 4 张起不可出）。lightspeed 的闸门
# （isCardPlayAllowed：handNormalityCount && cardsPlayedThisTurn >= 3，
# BattleContext.cpp L713-716）语义其实与 wiki 一致——此前记录"与本体规则
# 对不上"系误读。真正的阻塞在引擎层：出牌校验需在 battle.py play_card
# 前置（内容层无对应钩子），故本文件仅落地 unplayable 位 + 文本。
DOUBT = CardDef("Doubt", "疑虑", 0, "Curse",
                "不能被打出。\n在你的回合结束时，获得 1 层虚弱。",
                False, False, _unplayable_noop,
                unplayable=True, no_trigger_effect=_doubt_effect)
WRITHE = CardDef("Writhe", "苦恼", 0, "Curse",
                "不能被打出。\n固有。", False, False, _unplayable_noop,
                unplayable=True, innate=True)
PAIN = CardDef("Pain", "疼痛", 0, "Curse",
               "不能被打出。\n当在手牌中时，每打出一张其他牌，失去 1 生命。",
               False, False, _unplayable_noop,
               unplayable=True, on_play_other_lose_hp=1)
# Pain：引擎 use_card 已按手中剩余 Pain 计数结算（battle.py L339-341，
# Actions.player_lose_hp 不吃格挡，对齐 C++ triggerOnOtherCardPlayed 的
# PlayerLoseHp(1)×painCount——不含被打开的那张 Pain 自身）。
DECAY = CardDef("Decay", "腐朽", 0, "Curse",
                "不能被打出。\n在你的回合结束时，受到 2 点伤害。",
                False, False, _unplayable_noop,
                unplayable=True, no_trigger_effect=_decay_effect)
CLUMSY = CardDef("Clumsy", "笨拙", 0, "Curse",
                 "不能被打出。\n虚无。", False, False, _unplayable_noop,
                 unplayable=True, ethereal=True)


# ============================================================
# 特殊诅咒（不在 curseCardPool，仅特定来源进牌组）
# ============================================================


def _pride_effect(bc: "BattleContext", item: "CardQueueItem") -> None:
    # 对齐本体 Pride.java triggerOnEndOfTurnForPlayingCard：
    # MakeTempCardInDrawPileAction(copy, 1, shuffle=false, toTop=true)
    # ——副本置于抽牌堆顶。原牌不消耗，随回合末弃牌阶段正常弃置
    # （no_trigger_exhausts=False）；"Exhaust." 是打出时消耗（exhausts=True）。
    mark_no_trigger_processed(bc, item.card)
    bc.add_to_bot(Actions.make_temp_card_in_draw_pile(PRIDE, shuffle_into=False))


PRIDE = CardDef("Pride", "傲慢", 1, "Curse",
                "固有。消耗。\n你的回合结束时，在抽牌堆顶部加入一张这张牌的复制品。",
                False, True, _unplayable_noop,
                innate=True, no_trigger_effect=_pride_effect)
# Pride 是唯一可用能量打出的诅咒（本体 cost 1 + exhaust + isInnate，
# Pride.java 构造器）。lightspeed 未实现其回合末效果（Endless 专属卡，
# Cards.h 仅收录 doesCardExhaust=true），本实现以本体反编译为准。
# 注意：与任务计划注释（"回合末自动消耗"）不同——"Exhaust." 是打出时
# 消耗的词条，回合末原牌走弃牌，见迁移报告。


ASCENDERS_BANE = CardDef("Ascender's Bane", "进阶之灾", 0, "Curse",
                         "不能被打出。\n虚无。\n不能从牌组中移除。",
                         False, False, _unplayable_noop,
                         unplayable=True, ethereal=True)
# "无法移除"是局外层概念（C++ Card.cpp L84 transformable 排除三位），
# 本项目无移除/变形机制，战斗内仅落地 unplayable + ethereal。


# Curse of the Bell（2026-10-06 wiki 审计修正）：wiki 页为"Unplayable.
# Cannot be removed from your deck."——**无**"被消耗时复制入手"效果；
# 该行为系 lightspeed CardInstance::triggerOnExhaust（L210-211）的笔误，
# 此前按"结算路径以 C++ 为准"误继承，已删除。


CURSE_OF_THE_BELL = CardDef("Curse of the Bell", "铃铛的诅咒", 0, "Curse",
                            "不能被打出。\n不能从牌组中移除。",
                            False, False, _unplayable_noop,
                            unplayable=True)


def _necronomicurse_on_exhaust(bc: "BattleContext", inst: "CardInstance") -> None:
    # 对齐 C++ BattleContext.cpp L2836-2837 与本体 Necronomicurse.java
    # triggerOnExhaust：被消耗时复制一张入手（"无法摆脱"的体现——消耗
    # 堆进一张、手里回来一张）。无守卫也不死循环：复制入手后须再次被
    # 消耗才触发下一次。misc_data 守卫同上防双结算。
    if inst.misc_data:
        return
    inst.misc_data = 1
    bc.add_to_bot(Actions.make_temp_card_in_hand(NECRONOMICURSE))


NECRONOMICURSE = CardDef("Necronomicurse", "死灵诅咒", 0, "Curse",
                         "不能被打出。\n这个诅咒无法逃脱。",
                         False, False, _unplayable_noop,
                         unplayable=True, on_exhaust_effect=_necronomicurse_on_exhaust)

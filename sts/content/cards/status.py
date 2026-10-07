"""状态卡（WOUND/BURN/DAZED/SLIMED/VOID）——不属于任何职业的中立卡。

包化拆分（2026-10-07）前驻留在平铺 cards.py（铁甲文件），现独立成
模块；生成来源为怪物（Acid Slime 的 SLIMED、Sentry 的 DAZED、
Hexaghost 的 BURN）与卡牌效果（Wild Strike 的 WOUND 等），数值与
结算路径经迁移报告核对无偏差。

Burn 的回合末自动结算（no_trigger_effect）依赖 curses.py 的
mark_no_trigger_processed——curses 只从 _base 取 CardDef，无循环。
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from sts.combat.actions import Actions

from sts.content.cards._base import CardDef
from sts.content.cards.curses import mark_no_trigger_processed

if TYPE_CHECKING:
    from sts.combat.battle import BattleContext
    from sts.combat.queue import CardQueueItem


def _unplayable_play(bc: BattleContext, item: CardQueueItem) -> None:
    # 状态/诅咒卡被强制入队结算时无效果——对齐 C++ useCard 的 STATUS/CURSE
    # 分支（不进任何 useXxxCard switch；Havoc/Mayhem 打出抽牌堆顶会走到
    # 此路径，随后按 exhaust_on_use 正常落堆）。正常出牌路径仍被 play_card
    # 的 unplayable 位拦截，不会进入结算。
    pass


WOUND = CardDef("Wound", "伤口", 0, "Status", "不可打出。回合结束时弃置。", False, False, _unplayable_play, unplayable=True)


# ============================================================
# 怪物施加的状态卡（Acid Slime M/L 的 SLIMED、Sentry 的 DAZED、Hexaghost 的 BURN）
# ============================================================


def _slimed_play(bc: BattleContext, item: CardQueueItem) -> None:
    pass  # 打出仅消耗自身（唯一可打出的状态卡，对齐 lightspeed useNoTriggerCard 之外的正常路径）


def _burn_effect(bc: BattleContext, item: CardQueueItem) -> None:
    up = item.card is not None and item.card.upgraded
    # 回合末结算标记：Regret 重建 C++ regretCardCount（入队时完整手牌数）
    # 时需识别本回合末已离手的 no-trigger 卡（curses.py 详述）。
    mark_no_trigger_processed(bc, item.card)
    bc.add_to_bot(Actions.damage_player(4 if up else 2, self_inflicted=True))


SLIMED = CardDef("Slimed", "黏液", 1, "Status", "消耗。（被打出时无其他效果）", False, True, _slimed_play)
DAZED = CardDef("Dazed", "眩晕", 0, "Status", "不可打出。虚无。", False, False, _unplayable_play,
                unplayable=True, ethereal=True)
BURN = CardDef("Burn", "灼伤", 0, "Status", "回合结束时受到 2 点伤害。", False, False, _unplayable_play,
               unplayable=True, no_trigger_effect=_burn_effect)
VOID = CardDef("Void", "虚空", 0, "Status", "不可打出。虚无。被抽到时失去 1 点能量。", False, False, _unplayable_play,
               unplayable=True, ethereal=True, lose_energy_when_drawn=1)

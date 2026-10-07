"""铁甲战士职业全卡移植：74 张（3 基础 + 20 普通 + 35 非普通 + 16 稀有）；
另有无色稀有卡 Hand of Greed 在 colorless.py、状态卡在 status.py。

权威源（对齐 lightspeed useAttackCard/useSkillCard 的逐卡 switch）：
- 数值/结算顺序：lightspeed C++（BattleContext.cpp useAttackCard L958 起 /
  useSkillCard L1203 起 / usePowerCard L1515 起 + Actions.cpp 复合动作 +
  Cards.h doesCardExhaust/isXCost/getEnergyCost/getUpgradedCost）为准对译，
  slaythespire.wiki.gg（A0 基准）交叉校验；与 wiki 不一致处在各卡注释中记录。
- Power 数值口径：C++ 把部分 Power 状态存为"每次触发数值"（如 COMBUST 5/7、
  FEEL_NO_PAIN 3/4），本引擎语义是"层数 × 固定基数"（见 combat/types.py
  注释与 entities.py 结算），基础版一致、升级版有数值差异——逐卡注释记录。
- 历史迁移批次（简单档批次 1 / 中等档批次 2 / 困难档批次 3 / G 补遗，
  2026-10-05~06）：批次 G 为 wiki 全量比对发现迁移清单漏收的补遗
  （Reckless Charge 补齐；Rage 引擎阻塞未实现——battle.py 已按 RAGE 层数
  给格挡，但 entities 缺回合末移除，接线后加卡即可）。

每张卡 = 不可变模板（CardDef，_base.py）+ play()（把效果分解为原子动作
入队）；升级版数值用 self.upgraded 分支，卡牌文本以「（升级 X）」标注。
本文件 2026-10-07 由迁移批次分节重排为稀有度分节（与其他职业卡文件
同构），定义与数值未改动。

与包结构的关系：本文件为铁甲卡唯一正式定义，经包 __init__ eager
re-export 暴露；_strike_play 等共享助手取自 _base.py，BURN/DAZED/WOUND
状态卡取自 status.py。starting_deck 为铁甲初始牌组（5 打击/4 防御/1 痛击）。
"""


from __future__ import annotations


from typing import TYPE_CHECKING


from sts.combat.actions import Actions


from sts.combat.card_manager import MAX_HAND_SIZE


from sts.combat.queue import Action, CardQueueItem


from sts.combat.types import MonsterStatus, Outcome, PlayerStatus


from sts.content.cards._base import (
    CardDef,
    _defend_play,
    _exhaust_from_hand,
    _strike_play,
    _upgrade_in_place,
)


from sts.content.cards.status import BURN, DAZED, WOUND


if TYPE_CHECKING:
    from sts.combat.battle import BattleContext
    from sts.combat.card_manager import CardInstance
    from sts.combat.queue import CardQueueItem


# ============================================================
# 公共设施
# ============================================================


# Perfect Strike 的计数范围（对齐 Cards.h isCardStrikeCard）：战斗内所有
# "打击"牌（抽牌堆+手牌+弃牌堆；消耗堆已被移出战斗，不计——对齐
# moveToExhaustPile 的 notifyRemoveFromCombat）。未定义的打击牌保留名字，
# 定义后自动纳入计数。
_STRIKE_CARD_NAMES = frozenset({
    "Strike", "Twin Strike", "Wild Strike", "Pommel Strike", "Perfected Strike",
    "Swift Strike", "Sneaky Strike", "Meteor Strike", "Thunder Strike", "Windmill Strike",
})


def _count_strikes_in_combat(bc: BattleContext) -> int:
    cards = bc.cards
    return sum(
        1
        for pile in (cards.draw_pile, cards.hand, cards.discard_pile)
        for c in pile
        if c.card.name in _STRIKE_CARD_NAMES
    )


def _exhaust_action(inst: CardInstance) -> Action:
    return Action(lambda bc: _exhaust_from_hand(bc, inst))


def _exhaust_random_from_hand(bc: BattleContext) -> None:
    """随机消耗手中 1 张（True Grit 基础版 / Fiend Fire）。

    对齐 ExhaustRandomCardInHand + getRandomCardIdxInHand（C++ 用
    cardRandom 流，本项目按 DESIGN.md §3 统一 misc 流，分布级等价）。
    """
    if not bc.cards.hand:
        return
    idx = bc.rngs.misc.int_inclusive(0, len(bc.cards.hand) - 1)
    _exhaust_from_hand(bc, bc.cards.hand[idx])


def starting_deck() -> list[CardDef]:
    """铁甲战士初始牌组：5 打击 / 4 防御 / 1 痛击。"""
    return [STRIKE] * 5 + [DEFEND] * 4 + [BASH]


# ============================================================
# 基础 3 张（游戏初始牌组序）
# ============================================================


STRIKE = CardDef("Strike", "打击", 1, "Attack", "造成 6 点伤害。", True, False, _strike_play)


DEFEND = CardDef("Defend", "防御", 1, "Skill", "获得 5 点格挡。", False, False, _defend_play)


def _bash_play(bc: BattleContext, item: CardQueueItem) -> None:
    up = item.card.upgraded
    dmg = bc.calculate_card_damage(item, item.target, 10 if up else 8)
    bc.add_to_bot(Actions.attack_enemy(item.target, dmg))
    # 玩家施加的易伤：is_source_monster=False，当轮回合末即递减
    bc.add_to_bot(Actions.debuff_enemy(item.target, MonsterStatus.VULNERABLE, 3 if up else 2, False))


BASH = CardDef("Bash", "痛击", 2, "Attack", "造成 8 点伤害。\n给予 2 层易伤。", True, False, _bash_play)


# ============================================================
# 普通 20 张
# ============================================================


def _anger_play(bc: BattleContext, item: CardQueueItem) -> None:
    up = item.card.upgraded
    dmg = bc.calculate_card_damage(item, item.target, 8 if up else 6)
    bc.add_to_bot(Actions.attack_enemy(item.target, dmg))
    # 一张副本（保留升级状态）进弃牌堆
    bc.add_to_bot(Actions.make_temp_card_in_discard(ANGER, up))


ANGER = CardDef("Anger", "愤怒", 0, "Attack", "造成 6 点伤害。\n在弃牌堆放入一张此牌的复制品。", True, False, _anger_play)


def _armaments_play(bc: BattleContext, item: CardQueueItem) -> None:
    # 对齐 C++ ARMAMENTS：恒 5 格挡（calculateCardBlock(5)，升级不改，wiki 同）；
    # 升级版 UpgradeAllCardsInHand（已升级 no-op），基础版 ArmamentsAction 选
    # 1 张可升级手牌。canUpgrade（CardInstance.cpp:55）：未升级或可多次升级
    #（Searing Blow），且非状态/诅咒；自身打出时已离手，天然不在候选。
    bc.add_to_bot(Actions.gain_block(bc.calculate_card_block(5)))
    if item.card.upgraded:

        def upgrade_all(bc: BattleContext) -> None:
            for inst in bc.cards.hand:
                _upgrade_in_place(inst)

        bc.add_to_bot(Action(upgrade_all))
        return

    def run(bc: BattleContext) -> None:
        candidates = [
            c for c in bc.cards.hand
            if (not c.upgraded or c.card.multiple_upgrades) and c.card.ctype not in ("Status", "Curse")
        ]

        def on_choose(bc2: BattleContext, chosen: list) -> None:
            for inst in chosen:
                _upgrade_in_place(inst)

        bc.open_card_select(candidates, on_choose, prompt="武装：选择 1 张手牌升级")

    bc.add_to_bot(Action(run))


ARMAMENTS = CardDef("Armaments", "武装", 1, "Skill",
                    "获得 5 点格挡。\n在本场战斗中升级手牌中的一张牌。",
                    False, False, _armaments_play)


def _body_slam_play(bc: BattleContext, item: CardQueueItem) -> None:
    # 伤害 = 出牌结算时的当前格挡（仍走伤害管线：吃力量/虚弱/易伤）
    dmg = bc.calculate_card_damage(item, item.target, bc.player.block)
    bc.add_to_bot(Actions.attack_enemy(item.target, dmg))


BODY_SLAM = CardDef(
    "Body Slam", "全身撞击", 1, "Attack", "造成你当前格挡值的伤害。", True, False, _body_slam_play,
    upgraded_cost=0,  # 升级版仅改费 1→0（伤害不变）
)


def _clash_condition(bc: BattleContext, inst: CardInstance) -> bool:
    """对齐 canUseClash（CardInstance.cpp L260）：手牌（含自身）全部为攻击牌。"""
    return all(c.card.ctype == "Attack" for c in bc.cards.hand)


def _clash_play(bc: BattleContext, item: CardQueueItem) -> None:
    dmg = bc.calculate_card_damage(item, item.target, 18 if item.card.upgraded else 14)
    bc.add_to_bot(Actions.attack_enemy(item.target, dmg))


CLASH = CardDef("Clash", "交锋", 0, "Attack", "只有在手牌每一张牌都是攻击牌时才能被打出。\n造成 14 点伤害。",
                True, False, _clash_play, play_condition=_clash_condition)


def _cleave_play(bc: BattleContext, item: CardQueueItem) -> None:
    up = item.card.upgraded
    # attack_all_enemy 内部逐怪走完整伤害管线（含力量/虚弱/易伤）
    bc.add_to_bot(Actions.attack_all_enemy(11 if up else 8))


CLEAVE = CardDef("Cleave", "顺劈斩", 1, "Attack", "对所有敌人造成 8 点伤害。", False, False, _cleave_play)


def _clothesline_play(bc: BattleContext, item: CardQueueItem) -> None:
    up = item.card.upgraded
    dmg = bc.calculate_card_damage(item, item.target, 14 if up else 12)
    bc.add_to_bot(Actions.attack_enemy(item.target, dmg))
    bc.add_to_bot(Actions.debuff_enemy(item.target, MonsterStatus.WEAK, 3 if up else 2, False))


CLOTHESLINE = CardDef("Clothesline", "金刚臂", 2, "Attack", "造成 12 点伤害。\n给予 2 层虚弱。", True, False, _clothesline_play)


def _flex_play(bc: BattleContext, item: CardQueueItem) -> None:
    up = item.card.upgraded
    n = 4 if up else 2
    # 临时力量：+N 力量 + N 层 LOSE_STRENGTH，回合末在
    # Player.apply_end_of_turn_powers 扣回（对齐 C++ 的 UNIQUE 状态机制）
    bc.add_to_bot(Actions.buff_player(PlayerStatus.STRENGTH, n))
    bc.add_to_bot(Actions.debuff_player(PlayerStatus.LOSE_STRENGTH, n, False))


FLEX = CardDef("Flex", "活动肌肉", 0, "Skill", "获得 2 点力量。\n你的回合结束时，失去 2 点力量。", False, False, _flex_play)


def _havoc_play(bc: BattleContext, item: CardQueueItem) -> None:
    # 对齐 useSkillCard HAVOC（BattleContext.cpp:1337）：随机目标免费打出
    # 抽牌堆顶牌，打完那张牌消耗（PlayTopCard 第二参 true）。wiki 口径：
    # "Play the top card of your draw pile and Exhaust it."——"Exhaust it"
    # 指被 打出的顶牌，Havoc 自身**不**消耗（此前误读 wiki 置了 exhausts=True，
    # 与 lightspeed 不消耗一致，已改回）。
    # 抽牌堆空时 PlayTopCard 自带"洗弃牌堆再重试"（playTopCardInDrawPile，
    # BattleContext.cpp:2515-2522）；此刻刚打出的 Havoc 尚在 limbo（出牌
    # 收尾 on_after_card_used 为入队动作、晚于本效果），不参与洗回，也
    # 不会"打出自己"；两堆皆空则 no-op。
    bc.add_to_bot(Actions.play_top_card(exhaust=True))


HAVOC = CardDef("Havoc", "破灭", 1, "Skill", "打出抽牌堆顶部的牌，将其消耗。", False, False, _havoc_play,
                upgraded_cost=0)  # wiki 口径（2026-10-06 复核）：Exhaust 仅指被打出的顶牌，自身不消耗


def _headbutt_play(bc: BattleContext, item: CardQueueItem) -> None:
    # 对齐 C++ HEADBUTT：先攻击（9/12，出牌时算伤）后 HeadbuttAction 选卡
    # （候选=弃牌堆全部，空堆仅攻击无选卡）；选中 → 置抽牌堆顶 + 移出弃牌堆。
    # 出牌收尾 on_after_card_used 为入队动作、晚于本效果（对齐 C++
    # OnAfterCardUsed）——选卡时刚打出的 Headbutt 尚在 limbo、不在弃牌堆，
    # 候选集天然不含它；堆中先前的 Headbutt 仍可选，与 C++ 一致。
    dmg = bc.calculate_card_damage(item, item.target, 12 if item.card.upgraded else 9)
    bc.add_to_bot(Actions.attack_enemy(item.target, dmg))

    def run(bc: BattleContext) -> None:
        candidates = list(bc.cards.discard_pile)

        def on_choose(bc2: BattleContext, chosen: list) -> None:
            for inst in chosen:
                bc2.cards.discard_pile.remove(inst)
                bc2.cards.append_to_draw_top(inst)

        bc.open_card_select(
            candidates, on_choose, prompt="头槌：选择 1 张弃牌置于抽牌堆顶"
        )

    bc.add_to_bot(Action(run))


HEADBUTT = CardDef("Headbutt", "头槌", 1, "Attack",
                   "造成 9 点伤害。\n将弃牌堆中的一张牌放到抽牌堆的顶部。",
                   True, False, _headbutt_play)


def _heavy_blade_play(bc: BattleContext, item: CardQueueItem) -> None:
    up = item.card.upgraded
    # 对齐 C++ HEAVY_BLADE 分支：base = 14 + (up?4:2)×力量，再走
    # calculateCardDamage（管线内另加 1×力量）→ 力量总倍率 3/5。
    # 升级不改基准伤害（14），与 wiki 一致。
    base = 14 + (4 if up else 2) * bc.player.statuses.get(PlayerStatus.STRENGTH)
    dmg = bc.calculate_card_damage(item, item.target, base)
    bc.add_to_bot(Actions.attack_enemy(item.target, dmg))


HEAVY_BLADE = CardDef("Heavy Blade", "重刃", 2, "Attack", "造成 14 点伤害。\n力量在重刃上发挥 3 倍效果。", True, False, _heavy_blade_play)


def _iron_wave_play(bc: BattleContext, item: CardQueueItem) -> None:
    up = item.card.upgraded
    # C++ 有 calculateCardBlock 嵌套两次的笔误，本体为单次：5 格挡 + 5 伤
    bc.add_to_bot(Actions.gain_block(bc.calculate_card_block(7 if up else 5)))
    dmg = bc.calculate_card_damage(item, item.target, 7 if up else 5)
    bc.add_to_bot(Actions.attack_enemy(item.target, dmg))


IRON_WAVE = CardDef("Iron Wave", "铁斩波", 1, "Attack", "获得 5 点格挡。\n造成 5 点伤害。", True, False, _iron_wave_play)


def _perfected_strike_play(bc: BattleContext, item: CardQueueItem) -> None:
    up = item.card.upgraded
    # C++ 在 useAttackCard 计算时打出牌仍在手（"hack because we calculate
    # strikeCount while non purge cards are still in hand"）→ 计数含自身；
    # 重放体（purge_on_use，如 Double Tap 复制）不在手，不计。
    count = _count_strikes_in_combat(bc) + (0 if item.purge_on_use else 1)
    base = 6 + count * (3 if up else 2)
    dmg = bc.calculate_card_damage(item, item.target, base)
    bc.add_to_bot(Actions.attack_enemy(item.target, dmg))


PERFECTED_STRIKE = CardDef("Perfected Strike", "完美打击", 2, "Attack", "造成 6 点伤害。\n你每有一张名字中有打击的牌，伤害+2。", True, False, _perfected_strike_play)


def _pommel_strike_play(bc: BattleContext, item: CardQueueItem) -> None:
    up = item.card.upgraded
    dmg = bc.calculate_card_damage(item, item.target, 10 if up else 9)
    bc.add_to_bot(Actions.attack_enemy(item.target, dmg))
    bc.add_to_bot(Actions.draw_cards(2 if up else 1))


POMMEL_STRIKE = CardDef("Pommel Strike", "剑柄打击", 1, "Attack", "造成 9 点伤害。\n抽 1 张牌。", True, False, _pommel_strike_play)


def _shrug_it_off_play(bc: BattleContext, item: CardQueueItem) -> None:
    up = item.card.upgraded
    bc.add_to_bot(Actions.gain_block(bc.calculate_card_block(11 if up else 8)))
    bc.add_to_bot(Actions.draw_cards(1))


SHRUG_IT_OFF = CardDef("Shrug It Off", "耸肩无视", 1, "Skill", "获得 8 点格挡。\n抽 1 张牌。", False, False, _shrug_it_off_play)


def _sword_boomerang_play(bc: BattleContext, item: CardQueueItem) -> None:
    # 对齐 C++：3（升级 4）段，每段独立随机目标 + 独立走攻击管线
    bc.add_to_bot(Actions.attack_random_enemy(3, 4 if item.card.upgraded else 3))


SWORD_BOOMERANG = CardDef("Sword Boomerang", "飞剑回旋镖", 1, "Attack", "随机对敌人造成 3 点伤害 3 次。", False, False, _sword_boomerang_play)


def _thunderclap_play(bc: BattleContext, item: CardQueueItem) -> None:
    up = item.card.upgraded
    # 全体 4 伤（升级 7）+ 全体 1 层易伤（升级不变，仅伤害提升）
    bc.add_to_bot(Actions.attack_all_enemy(7 if up else 4))
    bc.add_to_bot(Actions.debuff_all_enemy(MonsterStatus.VULNERABLE, 1, False))


THUNDERCLAP = CardDef("Thunderclap", "闪电霹雳", 1, "Attack", "对所有敌人造成 4 点伤害，给予 1 层易伤。", False, False, _thunderclap_play)


def _true_grit_play(bc: BattleContext, item: CardQueueItem) -> None:
    up = item.card.upgraded
    bc.add_to_bot(Actions.gain_block(bc.calculate_card_block(9 if up else 7)))
    if up:
        # 升级版选卡消耗（对齐 ChooseExhaustOne：canPickZero=false，单候选
        # 直执、空手跳过——open_card_select 已内置同款分支）
        def on_choose(bc2: BattleContext, chosen: list) -> None:
            for inst in chosen:
                _exhaust_from_hand(bc2, inst)

        bc.add_to_bot(Action(lambda bc: bc.open_card_select(
            list(bc.cards.hand), on_choose, prompt="坚毅+：选择 1 张手牌消耗")))
    else:
        # 基础版随机消耗 1 张（执行时抽，misc 流）
        bc.add_to_bot(Action(_exhaust_random_from_hand))


TRUE_GRIT = CardDef("True Grit", "坚毅", 1, "Skill", "获得 7 点格挡。\n消耗一张随机手牌。", False, False, _true_grit_play)


def _twin_strike_play(bc: BattleContext, item: CardQueueItem) -> None:
    up = item.card.upgraded
    # 伤害出队前算好一次（对齐 C++：两段共用同一 dmg，第二段不重新计算）
    dmg = bc.calculate_card_damage(item, item.target, 7 if up else 5)
    bc.add_to_bot(Actions.attack_enemy(item.target, dmg))
    bc.add_to_bot(Actions.attack_enemy(item.target, dmg))


TWIN_STRIKE = CardDef("Twin Strike", "双重打击", 1, "Attack", "造成 5 点伤害两次。", True, False, _twin_strike_play)


def _warcry_play(bc: BattleContext, item: CardQueueItem) -> None:
    # 对齐 C++ WARCRY：先抽 1（升级 2），后 WarcryAction 置顶选卡——候选 =
    # 抽牌后的手牌（自身已离手不在候选；C++ 单候选分支有空转 cardRandom 流，
    # 本项目不做轨迹对齐故省略），选中 → 置抽牌堆顶 + 移出手牌
    bc.add_to_bot(Actions.draw_cards(2 if item.card.upgraded else 1))

    def run(bc: BattleContext) -> None:
        def on_choose(bc2: BattleContext, chosen: list) -> None:
            for inst in chosen:
                bc2.cards.hand.remove(inst)
                bc2.cards.append_to_draw_top(inst)  # 置顶：抽牌从 draw_pile 尾弹出

        bc.open_card_select(
            list(bc.cards.hand), on_choose, prompt="战吼：选择 1 张手牌置于抽牌堆顶"
        )

    bc.add_to_bot(Action(run))


WARCRY = CardDef("Warcry", "战吼", 0, "Skill",
                 "抽 1 张牌。\n将手牌中的一张牌放到你的抽牌堆顶部。\n消耗。",
                 False, True, _warcry_play)


def _wild_strike_play(bc: BattleContext, item: CardQueueItem) -> None:
    up = item.card.upgraded
    dmg = bc.calculate_card_damage(item, item.target, 17 if up else 12)
    bc.add_to_bot(Actions.attack_enemy(item.target, dmg))
    # 1 张伤口洗入抽牌堆（随机位置）
    bc.add_to_bot(Actions.make_temp_card_in_draw_pile(WOUND, False, shuffle_into=True))


WILD_STRIKE = CardDef("Wild Strike", "狂野打击", 1, "Attack", "造成 12 点伤害。\n将一张伤口放入你的抽牌堆中。", True, False, _wild_strike_play)


# ============================================================
# 非普通 35 张
# ============================================================


def _battle_trance_play(bc: BattleContext, item: CardQueueItem) -> None:
    bc.add_to_bot(Actions.draw_cards(4 if item.card.upgraded else 3))
    # 本回合不能再抽牌：回合末由 apply_end_of_turn_powers 解除
    bc.add_to_bot(Actions.debuff_player(PlayerStatus.NO_DRAW, 1, False))


BATTLE_TRANCE = CardDef("Battle Trance", "战斗专注", 0, "Skill", "抽 3 张牌。\n你在这个回合内不能再抽任何牌。", False, False, _battle_trance_play)


def _blood_for_blood_play(bc: BattleContext, item: CardQueueItem) -> None:
    # C++ up?22:18（wiki 同）。受击 -1 费由引擎 cost_delta_on_damage 三堆
    # 遍历实现（onTookDamage→tookDamage→updateCost(-1)，下限 0，无上限
    # 逻辑——CardInstance.cpp:148 的"cost<4"分支是升级路径，不在受击路径）。
    dmg = bc.calculate_card_damage(item, item.target, 22 if item.card.upgraded else 18)
    bc.add_to_bot(Actions.attack_enemy(item.target, dmg))


BLOOD_FOR_BLOOD = CardDef("Blood for Blood", "以血还血", 4, "Attack", "你每在战斗中失去生命一次，这张牌的耗能就减少 1 点能量。\n造成 18 点伤害。",
                          True, False, _blood_for_blood_play, upgraded_cost=3, cost_delta_on_damage=-1)


def _bloodletting_play(bc: BattleContext, item: CardQueueItem) -> None:
    # 对齐 C++ BLOODLETTING：失去 3 HP（wiki 为 1，以 C++ 为准；自伤，
    # 触发 RUPTURE），+2/3 能量
    bc.add_to_bot(Actions.player_lose_hp(3, self_inflicted=True))
    bc.add_to_bot(Actions.gain_energy(3 if item.card.upgraded else 2))


BLOODLETTING = CardDef("Bloodletting", "放血", 0, "Skill", "获得 2 点能量。\n失去 3 点生命。", False, False, _bloodletting_play)


def _burning_pact_play(bc: BattleContext, item: CardQueueItem) -> None:
    # 对齐 C++ BURNING_PACT：ChooseExhaustOne + DrawCards(up?3:2)——基础版
    # 也是选卡消耗（wiki：基础版随机消耗、升级版才可选卡；以 C++ 为准）。
    # 消耗走内容层统一路径 _exhaust_from_hand（触发 FNP/Dark Embrace/Sentinel）。
    def run(bc: BattleContext) -> None:
        def on_choose(bc2: BattleContext, chosen: list) -> None:
            for inst in chosen:
                _exhaust_from_hand(bc2, inst)

        bc.open_card_select(
            list(bc.cards.hand), on_choose, prompt="燃烧契约：选择 1 张手牌消耗"
        )

    bc.add_to_bot(Action(run))
    bc.add_to_bot(Actions.draw_cards(3 if item.card.upgraded else 2))


BURNING_PACT = CardDef("Burning Pact", "燃烧契约", 1, "Skill",
                       "消耗 1 张牌。\n抽 2 张牌。",
                       False, False, _burning_pact_play)


def _carnage_play(bc: BattleContext, item: CardQueueItem) -> None:
    dmg = bc.calculate_card_damage(item, item.target, 28 if item.card.upgraded else 20)
    bc.add_to_bot(Actions.attack_enemy(item.target, dmg))


CARNAGE = CardDef("Carnage", "残杀", 2, "Attack", "虚无。\n造成 20 点伤害。", True, False, _carnage_play, ethereal=True)


def _combust_play(bc: BattleContext, item: CardQueueItem) -> None:
    # wiki 口径：回合末失 1 HP（恒，不随叠加）、全体 5/7 伤（多张伤害累加）。
    # 层恒 1；基数经 special["combust_base"] 写入（entities 已接线）。
    bc.add_to_bot(Actions.buff_player(PlayerStatus.COMBUST, 1))
    bc.add_to_bot(Action(lambda bc2: bc2.player.special.update(
        combust_base=(bc2.player.special.get("combust_base", 0) + (7 if item.card.upgraded else 5)))))


COMBUST = CardDef("Combust", "自燃", 1, "Power", "在你的回合结束时，你失去 1 点生命，对所有敌人造成 5 点伤害。", False, False,
                  _combust_play)


def _dark_embrace_play(bc: BattleContext, item: CardQueueItem) -> None:
    # C++ 无 up 分支：恒 1 层；升级只改费 2→1（wiki 同）
    bc.add_to_bot(Actions.buff_player(PlayerStatus.DARK_EMBRACE, 1))


DARK_EMBRACE = CardDef("Dark Embrace", "黑暗之拥", 2, "Power", "每当有一张牌被消耗时，抽 1 张牌。", False, False,
                       _dark_embrace_play, upgraded_cost=1)


def _disarm_play(bc: BattleContext, item: CardQueueItem) -> None:
    # wiki 口径（Disarm -2/-3 力量；lightspeed 原恒 -2，系其笔误——升级分支
    # 漏写）。DebuffEnemy 语义：吃 ARTIFACT 抵消，负数直达力量（可为负）
    n = -3 if item.card.upgraded else -2
    bc.add_to_bot(Actions.debuff_enemy(item.target, MonsterStatus.STRENGTH, n, False))


DISARM = CardDef("Disarm", "缴械", 1, "Skill", "使敌人失去 2 点力量。\n消耗。", True, True, _disarm_play)


def _dropkick_play(bc: BattleContext, item: CardQueueItem) -> None:
    up = item.card.upgraded
    t = item.target

    def run(bc: BattleContext) -> None:
        # 对齐 DropkickAction：执行时判断目标易伤、计算伤害；攻击先结算，
        # 有易伤则 +1 能量、抽 1（战斗已结束时不再执行——对齐胜利清队列）
        m = bc.monsters.monsters[t]
        if m.is_dead_or_escaped():
            return
        bonus = m.statuses.has(MonsterStatus.VULNERABLE)
        dmg = bc.calculate_card_damage(item, t, 8 if up else 5)
        m.attacked(bc, dmg)
        bc.check_combat()
        if bonus and bc.outcome == Outcome.UNDECIDED:
            bc.player.energy += 1
            bc.draw_cards(1)

    bc.add_to_bot(Action(run))


DROPKICK = CardDef("Dropkick", "飞身踢", 1, "Attack", "造成 5 点伤害。\n如果敌人有易伤状态，\n获得 1 点能量并且\n抽 1 张牌。", True, False, _dropkick_play)


def _copy_instance_to_hand(bc: BattleContext, inst: CardInstance, count: int) -> None:
    """复制实例入手（Dual Wield）：手满则落弃牌堆（对齐 C++ createTempCardInHand /
    createTempCardInDiscard 的手满分支）。保留升级态与实例计数（对齐 C++ 整实例
    拷贝）；引擎 create_temp_card_in_hand 工厂不拷 misc_data，故内容层自建副本。
    """
    for _ in range(count):
        copy = bc.cards.instantiate(inst.card)
        copy.upgraded = inst.upgraded
        copy.misc_data = inst.misc_data
        if len(bc.cards.hand) < MAX_HAND_SIZE:
            bc.cards.hand.append(copy)
        else:
            bc.cards.move_to_discard_pile(copy)


def _dual_wield_play(bc: BattleContext, item: CardQueueItem) -> None:
    # 对齐 C++ DUAL_WIELD：DualWieldAction(up ? 2 : 1)——基础复制 1 份、
    # 升级 2 份（wiki 同；任务口径的 2/3 以 C++ 为准修正）。候选 = 手中
    # 攻击/能力牌（自身已离手）；单候选直执由 open_card_select 内建。
    copy_count = 2 if item.card.upgraded else 1

    def run(bc: BattleContext) -> None:
        candidates = [c for c in bc.cards.hand if c.card.ctype in ("Attack", "Power")]

        def on_choose(bc2: BattleContext, chosen: list) -> None:
            for inst in chosen:
                _copy_instance_to_hand(bc2, inst, copy_count)

        bc.open_card_select(
            candidates, on_choose, prompt="双持：选择 1 张攻击或能力牌复制"
        )

    bc.add_to_bot(Action(run))


DUAL_WIELD = CardDef("Dual Wield", "双持", 1, "Skill",
                     "将你手牌中的一张攻击或能力牌复制一张。",
                     False, False, _dual_wield_play)  # wiki 口径（2026-10-06 复核）：无"消耗"词条，自身不消耗（此前误读）


def _entrench_play(bc: BattleContext, item: CardQueueItem) -> None:
    def run(bc: BattleContext) -> None:
        # 对齐 EntrenchAction：执行时格挡翻倍（走 gain_block：NO_BLOCK 拦截
        # + Juggernaut 触发）
        bc.player.gain_block(bc, bc.player.block)

    bc.add_to_bot(Action(run))


ENTRENCH = CardDef("Entrench", "巩固", 2, "Skill", "将你当前的格挡翻倍。", False, False, _entrench_play,
                   upgraded_cost=1)


def _evolve_play(bc: BattleContext, item: CardQueueItem) -> None:
    # 层数 = 抽到状态牌时的补抽张数（C++ 1/2 直接用值，语义一致）
    bc.add_to_bot(Actions.buff_player(PlayerStatus.EVOLVE, 2 if item.card.upgraded else 1))


EVOLVE = CardDef("Evolve", "进化", 1, "Power", "每当你抽到一张状态牌时，抽 1 张牌。", False, False, _evolve_play)


def _feel_no_pain_play(bc: BattleContext, item: CardQueueItem) -> None:
    # wiki 口径：卡被消耗时 3/4 格挡。层恒 1；基数经 special["fnp_base"]
    # 写入（battle.py on_card_exhausted 已接线）。
    bc.add_to_bot(Actions.buff_player(PlayerStatus.FEEL_NO_PAIN, 1))
    bc.add_to_bot(Action(lambda bc2: bc2.player.special.update(
        fnp_base=4 if item.card.upgraded else 3)))


FEEL_NO_PAIN = CardDef("Feel No Pain", "无惧疼痛", 1, "Power", "每当有一张牌被消耗时，获得 3 点格挡。", False, False,
                       _feel_no_pain_play)


def _fire_breathing_play(bc: BattleContext, item: CardQueueItem) -> None:
    # wiki 口径：抽到状态/诅咒时全体 6/10 伤。层恒 1；基数经 special
    # ["fire_breathing_base"] 写入（battle.py 抽牌钩子已接线）。
    bc.add_to_bot(Actions.buff_player(PlayerStatus.FIRE_BREATHING, 1))
    bc.add_to_bot(Action(lambda bc2: bc2.player.special.update(
        fire_breathing_base=10 if item.card.upgraded else 6)))


FIRE_BREATHING = CardDef("Fire Breathing", "火焰吐息", 1, "Power", "每当你抽到一张状态牌或诅咒牌时，对所有敌人造成 6 点伤害。",
                         False, False, _fire_breathing_play)


def _flame_barrier_play(bc: BattleContext, item: CardQueueItem) -> None:
    up = item.card.upgraded
    bc.add_to_bot(Actions.gain_block(bc.calculate_card_block(16 if up else 12)))
    bc.add_to_bot(Actions.buff_player(PlayerStatus.FLAME_BARRIER, 6 if up else 4))


FLAME_BARRIER = CardDef("Flame Barrier", "火焰屏障", 2, "Skill", "获得 12 点格挡。\n你在这个回合每受到一次攻击，都对攻击者造成 4 点伤害。",
                        False, False, _flame_barrier_play)


def _ghostly_armor_play(bc: BattleContext, item: CardQueueItem) -> None:
    bc.add_to_bot(Actions.gain_block(bc.calculate_card_block(13 if item.card.upgraded else 10)))


GHOSTLY_ARMOR = CardDef("Ghostly Armor", "幽灵铠甲", 1, "Skill", "虚无。\n获得 10 点格挡。", False, False,
                        _ghostly_armor_play, ethereal=True)


def _hemokinesis_play(bc: BattleContext, item: CardQueueItem) -> None:
    up = item.card.upgraded
    # 对齐 C++：先失 2 HP（自伤，触发 RUPTURE）后攻击；伤害在出牌时算好
    #（失去 HP 不会反过来影响本卡伤害）
    bc.add_to_bot(Actions.player_lose_hp(2, self_inflicted=True))
    dmg = bc.calculate_card_damage(item, item.target, 20 if up else 15)
    bc.add_to_bot(Actions.attack_enemy(item.target, dmg))


HEMOKINESIS = CardDef("Hemokinesis", "御血术", 1, "Attack", "失去 2 点生命。\n造成 15 点伤害。", True, False, _hemokinesis_play)


def _infernal_blade_pool() -> list:
    """随机攻击牌池（对齐 getTrulyRandomCardInCombat(ATTACK)：本模块全部攻击卡）。

    动态扫描模块级 CardDef：后续批次新增攻击卡自动入池。
    """
    return [g for g in list(globals().values()) if isinstance(g, CardDef) and g.ctype == "Attack"]


def _infernal_blade_play(bc: BattleContext, item: CardQueueItem) -> None:
    def run(bc: BattleContext) -> None:
        pool = _infernal_blade_pool()
        card = pool[bc.rngs.misc.int_inclusive(0, len(pool) - 1)]
        inst = bc.cards.instantiate(card)
        inst.cost_for_turn = 0  # 本回合 0 费（回合末 reset_attributes 复原；对齐 setCostForTurn(0)）
        if len(bc.cards.hand) < MAX_HAND_SIZE:
            bc.cards.hand.append(inst)
        else:
            bc.cards.move_to_discard_pile(inst)  # 手牌满：生成牌落弃牌堆（对齐 moveToHandHelper）

    bc.add_to_bot(Action(run))


INFERNAL_BLADE = CardDef("Infernal Blade", "地狱之刃", 1, "Skill", "增加一张随机攻击牌到你的手牌。\n这张牌在本回合耗能变为 0。\n消耗。",
                         False, True, _infernal_blade_play, upgraded_cost=0)  # wiki 口径：升级改费 1→0（lightspeed 原不改费，系其笔误）


def _inflame_play(bc: BattleContext, item: CardQueueItem) -> None:
    bc.add_to_bot(Actions.buff_player(PlayerStatus.STRENGTH, 3 if item.card.upgraded else 2))


INFLAME = CardDef("Inflame", "燃烧", 1, "Power", "获得 2 点力量。", False, False, _inflame_play)


def _intimidate_play(bc: BattleContext, item: CardQueueItem) -> None:
    bc.add_to_bot(Actions.debuff_all_enemy(MonsterStatus.WEAK, 2 if item.card.upgraded else 1, False))


INTIMIDATE = CardDef("Intimidate", "威吓", 0, "Skill", "给予所有敌人 1 层虚弱。\n消耗。", False, True, _intimidate_play)


def _metallicize_play(bc: BattleContext, item: CardQueueItem) -> None:
    bc.add_to_bot(Actions.buff_player(PlayerStatus.METALLICIZE, 4 if item.card.upgraded else 3))


METALLICIZE = CardDef("Metallicize", "金属化", 1, "Power", "在你的回合结束时，获得 3 点格挡。", False, False, _metallicize_play)


def _power_through_play(bc: BattleContext, item: CardQueueItem) -> None:
    # 对齐 C++：2 张伤口先入手（手牌满则按上限消失），后格挡
    bc.add_to_bot(Actions.make_temp_card_in_hand(WOUND))
    bc.add_to_bot(Actions.make_temp_card_in_hand(WOUND))
    bc.add_to_bot(Actions.gain_block(bc.calculate_card_block(20 if item.card.upgraded else 15)))


POWER_THROUGH = CardDef("Power Through", "硬撑", 1, "Skill", "增加 2 张伤口到你的手牌。\n获得 15 点格挡。", False, False,
                        _power_through_play)


def _pummel_play(bc: BattleContext, item: CardQueueItem) -> None:
    up = item.card.upgraded
    # 对齐 C++ PUMMEL：升级加第 5 段而非加伤（wiki 同；伤害恒 2，
    # 多段共用同一 dmg）
    dmg = bc.calculate_card_damage(item, item.target, 2)
    for _ in range(5 if up else 4):
        bc.add_to_bot(Actions.attack_enemy(item.target, dmg))


PUMMEL = CardDef("Pummel", "连续拳", 1, "Attack", "造成 2 点伤害 4 次。\n消耗。", True, True, _pummel_play)


def _rampage_play(bc: BattleContext, item: CardQueueItem) -> None:
    up = item.card.upgraded
    # 对齐 C++：伤害按打出时的 misc_data 计（先算后加），打出后永久 +5/8。
    # Double Tap 重放体共享本实例 → 重放伤害含第一次的增量（对齐 C++ todo
    # "doubled card damage is changed by the first" 的实际行为）；C++ 额外的
    # findAndUpgradeSpecialData 只为更新战斗外的牌组副本，战斗内等价。
    dmg = bc.calculate_card_damage(item, item.target, 8 + item.card.misc_data)
    bc.add_to_bot(Actions.attack_enemy(item.target, dmg))
    item.card.misc_data += 8 if up else 5


RAMPAGE = CardDef("Rampage", "暴走", 1, "Attack", "造成 8 点伤害。\n这张牌每被打出一次，在本场战斗中其伤害增加 5。",
                  True, False, _rampage_play)


def _reckless_charge_play(bc: BattleContext, item: CardQueueItem) -> None:
    # wiki 口径："Deal (7;10) damage. Shuffle a Dazed into your draw pile."
    # 伤害 + 1 张眩晕洗入抽牌堆随机位置（同 Wild Strike 的 WOUND 路径）
    up = item.card.upgraded
    dmg = bc.calculate_card_damage(item, item.target, 10 if up else 7)
    bc.add_to_bot(Actions.attack_enemy(item.target, dmg))
    bc.add_to_bot(Actions.make_temp_card_in_draw_pile(DAZED, False, shuffle_into=True))


RECKLESS_CHARGE = CardDef("Reckless Charge", "无谋冲锋", 0, "Attack",
                           "造成 7 点伤害。\n将一张晕眩放入你的抽牌堆中。",
                           True, False, _reckless_charge_play)


def _rupture_play(bc: BattleContext, item: CardQueueItem) -> None:
    # 层数 = 每次自伤失 HP 的力量增量（C++ 1/2，直接一致）
    bc.add_to_bot(Actions.buff_player(PlayerStatus.RUPTURE, 2 if item.card.upgraded else 1))


RUPTURE = CardDef("Rupture", "撕裂", 1, "Power", "每当你从一张牌中失去生命时，获得 1 点力量。", False, False, _rupture_play)


def _searing_blow_play(bc: BattleContext, item: CardQueueItem) -> None:
    # 公式（C++ SEARING_BLOW）：base = n×(n+7)/2 + 12，n = 升级次数。
    # 本引擎无多次升级来源（Armaments 批次 3）——升级位为 True 而
    # misc_data=0 时按 n=1 兜底；手改 misc_data 可表达任意升级数
    #（升级来源接线时应对 Searing Blow 递增 misc_data 而非仅置 upgraded）。
    n = item.card.misc_data
    if n == 0 and item.card.upgraded:
        n = 1
    dmg = bc.calculate_card_damage(item, item.target, n * (n + 7) // 2 + 12)
    bc.add_to_bot(Actions.attack_enemy(item.target, dmg))


SEARING_BLOW = CardDef("Searing Blow", "灼热攻击", 2, "Attack", "造成 12 点伤害。\n能被多次升级。",
                       True, False, _searing_blow_play,
                       multiple_upgrades=True)  # 批次 3 接线：Armaments 升级路径经 upgrade() 推进 misc_data（原批次 2 遗留 TODO）


def _second_wind_play(bc: BattleContext, item: CardQueueItem) -> None:
    # 出牌时按管线算好每张格挡（对齐 calculateCardBlock(up?7:5)）
    block_per_card = bc.calculate_card_block(7 if item.card.upgraded else 5)

    def run(bc: BattleContext) -> None:
        # 对齐 SecondWindAction：执行时读手牌，为每张非攻击牌 top 入队
        # 格挡、再 top 入队对应消耗 → 净结算序 = 全部消耗（逆手牌序）→
        # 全部格挡（自身已在手牌外，不计）
        targets = [c for c in list(bc.cards.hand) if c.card.ctype != "Attack"]
        for _ in targets:
            bc.add_to_top(Actions.gain_block(block_per_card))
        for inst in targets:
            bc.add_to_top(_exhaust_action(inst))

    bc.add_to_bot(Action(run))


SECOND_WIND = CardDef("Second Wind", "重振精神", 1, "Skill", "消耗手牌中所有非攻击牌，每张获得 5 点格挡。", False, False,
                      _second_wind_play)


def _seeing_red_play(bc: BattleContext, item: CardQueueItem) -> None:
    # wiki 口径（"Gain 2 Energy. Exhaust."）：消耗；lightspeed 的 doesCardExhaust
    # 未收录 SEEING_RED → 不消耗，系其笔误。+2 能量、升级改费 1→0。
    bc.add_to_bot(Actions.gain_energy(2))


SEEING_RED = CardDef("Seeing Red", "盛怒", 1, "Skill", "获得 2 点能量。\n消耗。", False, True, _seeing_red_play,
                     upgraded_cost=0)  # wiki 口径置消耗（lightspeed 原不消耗，系其 doesCardExhaust 笔误）


def _sentinel_on_exhaust(bc: BattleContext, inst: CardInstance) -> None:
    # 对齐 triggerAndMoveToExhaustPile 的 SENTINEL 分支：消耗时立即
    # +2/3 能量（C++ 注释"the game adds to bot here"——lightspeed 直接结算，
    # 等价）。misc_data 守卫：效果可能经引擎 on_card_exhausted 钩子与内容层
    # 消耗闭包的显式调用各到达一次，守卫保证只结算一次（消耗堆不可逆出，
    # 每实例至多消耗一次，守卫位不会与正常计数冲突）。
    if inst.misc_data:
        return
    inst.misc_data = 1
    bc.player.energy += 3 if inst.upgraded else 2


def _sentinel_play(bc: BattleContext, item: CardQueueItem) -> None:
    bc.add_to_bot(Actions.gain_block(bc.calculate_card_block(8 if item.card.upgraded else 5)))


SENTINEL = CardDef("Sentinel", "哨卫", 1, "Skill", "获得 5 点格挡。\n如果这张牌被消耗，\n获得 2 点能量。", False, False,
                   _sentinel_play, on_exhaust_effect=_sentinel_on_exhaust)


def _sever_soul_play(bc: BattleContext, item: CardQueueItem) -> None:
    up = item.card.upgraded
    dmg = bc.calculate_card_damage(item, item.target, 22 if up else 16)  # wiki 同：16/22

    def exhaust_run(bc: BattleContext) -> None:
        # 对齐 SeverSoulExhaustAction：逆序为每张非攻击手牌 bot 入队消耗
        # → 落在已入队的攻击之后（净结算：先 16/22 伤，后消耗全部非攻击牌）
        for inst in reversed(list(bc.cards.hand)):
            if inst.card.ctype != "Attack":
                bc.add_to_bot(_exhaust_action(inst))

    bc.add_to_bot(Action(exhaust_run))
    bc.add_to_bot(Actions.attack_enemy(item.target, dmg))


SEVER_SOUL = CardDef("Sever Soul", "断魂斩", 2, "Attack", "消耗手牌中所有非攻击牌。\n造成 16 点伤害。", True, False,
                     _sever_soul_play)


def _shockwave_play(bc: BattleContext, item: CardQueueItem) -> None:
    n = 5 if item.card.upgraded else 3
    bc.add_to_bot(Actions.debuff_all_enemy(MonsterStatus.WEAK, n, False))
    bc.add_to_bot(Actions.debuff_all_enemy(MonsterStatus.VULNERABLE, n, False))


SHOCKWAVE = CardDef("Shockwave", "震荡波", 2, "Skill", "给予所有敌人 3 层虚弱和易伤。\n消耗。", False, True, _shockwave_play)


def _spot_weakness_play(bc: BattleContext, item: CardQueueItem) -> None:
    n = 4 if item.card.upgraded else 3
    t = item.target

    def run(bc: BattleContext) -> None:
        # 对齐 SpotWeaknessAction：执行时读目标意图，为攻击时 +力量
        m = bc.monsters.monsters[t]
        if not m.is_dead_or_escaped() and m.current_move.kind == "attack":
            bc.player.statuses.add(PlayerStatus.STRENGTH, n)

    bc.add_to_bot(Action(run))


SPOT_WEAKNESS = CardDef("Spot Weakness", "观察弱点", 1, "Skill", "如果一名敌人的意图是攻击，你获得 3 点力量。", True, False, _spot_weakness_play)


def _uppercut_play(bc: BattleContext, item: CardQueueItem) -> None:
    up = item.card.upgraded
    # wiki 口径（Uppercut 13/13：升级不加伤，仅虚弱/易伤 1→2；批次 1 曾记录
    # "wiki 为 17" 系当时误读——2026-10-06 复核 wiki 页与 lightspeed 均为 13）
    dmg = bc.calculate_card_damage(item, item.target, 13)
    bc.add_to_bot(Actions.attack_enemy(item.target, dmg))
    n = 2 if up else 1
    bc.add_to_bot(Actions.debuff_enemy(item.target, MonsterStatus.WEAK, n, False))
    bc.add_to_bot(Actions.debuff_enemy(item.target, MonsterStatus.VULNERABLE, n, False))


UPPERCUT = CardDef("Uppercut", "上勾拳", 2, "Attack", "造成 13 点伤害。\n给予 1 层虚弱。\n给予 1 层易伤。", True, False, _uppercut_play)


def _whirlwind_play(bc: BattleContext, item: CardQueueItem) -> None:
    up = item.card.upgraded
    # 对齐 C++ WHIRLWIND 分支：baseDamage = 5/8 + VIGOR。活力必须在出牌时
    # 捕获——on_use_attack_card（VIGOR 出伤后移除）先于动作出队执行；C++ 在
    # 管线内二次加 VIGOR 实为延迟结算下捕获活力的必要 hack（同 Sword
    # Boomerang 注释），净效果 = 计入恰好一次，本实现以出牌时捕获等价表达。
    vigor = bc.player.statuses.get(PlayerStatus.VIGOR)
    base = (8 if up else 5) + vigor

    def run(bc: BattleContext) -> None:
        # 对齐 WhirlwindAction：能量已由 play_card 快照进 energy_on_use 并清零
        #（引擎契约；C++ 在动作内 useEnergy，时机差异无观测点），次数 =
        # max(快照, 0)。C++ 的 CHEMICAL_X +2 次未实现（本引擎遗物集不含）。
        times = max(item.energy_on_use, 0)
        if times <= 0:
            return
        # 一次性算好每怪伤害矩阵（每怪 calculateCardDamage）→ 循环 N 遍用矩阵
        # 值打：力量/易伤在第一遍后的变化不影响后续遍（伤害入队前算死）。
        # C++ 用 AttackAllMonsterRecursive 逐遍 addToTop 入队，本实现合并为
        # 单闭包——净行为等价：CURL_UP 等受击 add_to_bot 的动作同样落在全部
        # 遍数之后（C++ 首遍直执 + 余遍入 top，受击入队永远在递归项之后）；
        # 胜利清队以 outcome 判断替代 clear_post_combat。
        matrix = {
            m.idx: bc.calculate_card_damage(item, m.idx, base)
            for m in bc.monsters.monsters
            if not m.is_dead_or_escaped()
        }
        for _ in range(times):
            for m in bc.monsters.monsters:
                if not m.is_dead_or_escaped():
                    m.attacked(bc, matrix[m.idx])
            bc.check_combat()
            if bc.outcome != Outcome.UNDECIDED:
                return

    bc.add_to_bot(Action(run))


WHIRLWIND = CardDef("Whirlwind", "旋风斩", -1, "Attack",
                    "对所有敌人造成 5 点伤害X次。",
                    False, False, _whirlwind_play, x_cost=True)


# ============================================================
# 稀有 16 张
# ============================================================


def _barricade_play(bc: BattleContext, item: CardQueueItem) -> None:
    # C++ 为立即 setHasStatus；入队结算在时机上不可区分（无中途读取点）
    bc.add_to_bot(Actions.buff_player(PlayerStatus.BARRICADE, 1))


BARRICADE = CardDef("Barricade", "壁垒", 3, "Power", "格挡不再在你的回合开始时消失。", False, False,
                    _barricade_play, upgraded_cost=2)


def _berserk_play(bc: BattleContext, item: CardQueueItem) -> None:
    # 对齐 C++：++energyPerTurn 立即生效；易伤 2 层（升级仅 1 层）入 bot，
    # 玩家自施 → 当轮回合末即递减
    bc.player.energy_per_turn_bonus += 1
    bc.add_to_bot(Actions.debuff_player(PlayerStatus.VULNERABLE, 1 if item.card.upgraded else 2, False))


BERSERK = CardDef("Berserk", "狂暴", 0, "Power", "获得 2 层易伤。\n在每回合开始时获得 1 点能量。", False, False,
                  _berserk_play)  # wiki 口径（2026-10-06 复核）：费用恒 0，升级仅易伤 2→1（此前误记为 1→0）


def _bludgeon_play(bc: BattleContext, item: CardQueueItem) -> None:
    dmg = bc.calculate_card_damage(item, item.target, 42 if item.card.upgraded else 32)
    bc.add_to_bot(Actions.attack_enemy(item.target, dmg))


BLUDGEON = CardDef("Bludgeon", "重锤", 3, "Attack", "造成 32 点伤害。", True, False, _bludgeon_play)


def _brutality_play(bc: BattleContext, item: CardQueueItem) -> None:
    # C++ 恒 1 层；升级差异 = 固有（isCardInnate 的 upgraded 分支，用
    # innate_when_upgraded 位表达，待引擎 move_innate_to_top 接线）；
    # 费用 wiki 口径恒 0（2026-10-06 复核，此前误记 1→0）
    bc.add_to_bot(Actions.buff_player(PlayerStatus.BRUTALITY, 1))


BRUTALITY = CardDef("Brutality", "残暴", 0, "Power", "在你的回合开始时，你失去 1 点生命，抽 1 张牌。", False, False,
                    _brutality_play, innate_when_upgraded=True)  # wiki 口径：费用恒 0，升级仅加"固有"


def _corruption_play(bc: BattleContext, item: CardQueueItem) -> None:
    bc.add_to_bot(Actions.buff_player(PlayerStatus.CORRUPTION, 1))


CORRUPTION = CardDef("Corruption", "腐化", 3, "Power", "所有技能牌耗能变为 0。\n所有技能牌在被打出时被消耗。", False, False,
                     _corruption_play, upgraded_cost=2)


def _demon_form_play(bc: BattleContext, item: CardQueueItem) -> None:
    # 回合开始抽牌后 +层数力量（entities.apply_start_of_turn_post_draw_powers）
    bc.add_to_bot(Actions.buff_player(PlayerStatus.DEMON_FORM, 3 if item.card.upgraded else 2))


DEMON_FORM = CardDef("Demon Form", "恶魔形态", 3, "Power", "在每回合开始时获得\n2 点力量。", False, False, _demon_form_play)


def _double_tap_play(bc: BattleContext, item: CardQueueItem) -> None:
    # C++ up?2:1（升级版下一张与下两张攻击牌各翻倍）。引擎 on_use_attack_card
    # 已按 decrement 结算（battle.py L476 附近），与 wiki "your next (Attack is;
    # 2 Attacks are) played twice" 一致。
    bc.add_to_bot(Actions.buff_player(PlayerStatus.DOUBLE_TAP, 2 if item.card.upgraded else 1))


DOUBLE_TAP = CardDef("Double Tap", "双发", 1, "Skill", "在这个回合，你打出的下一张攻击牌会打出两次。", False, False, _double_tap_play)


def _exhume_play(bc: BattleContext, item: CardQueueItem) -> None:
    def run(bc: BattleContext) -> None:
        # 手牌满：整体跳过（对齐 C++ cardsInHand == MAX_HAND_SIZE 守卫）
        if len(bc.cards.hand) >= MAX_HAND_SIZE:
            return
        # 候选 = 消耗堆中非 Exhume 的牌（对齐 C++ 排除分支——lightspeed 自带
        # todo 标注此为 bug：本体允许选回 Exhume 自身；按"以 C++ 为准"口径
        # 实现排除）。刚打出的 Exhume 尚在 limbo（出牌收尾晚于效果），不在
        # 消耗堆中；排除分支只滤掉堆中先前的 Exhume，两边净候选集一致。
        candidates = [c for c in bc.cards.exhaust_pile if c.card is not EXHUME]

        def on_choose(bc2: BattleContext, chosen: list) -> None:
            for inst in chosen:
                bc2.cards.exhaust_pile.remove(inst)
                bc2.cards.hand.append(inst)  # 回手（对齐 moveToHandHelper；手满守卫已前置）

        bc.open_card_select(
            candidates, on_choose, prompt="发掘：选择 1 张消耗堆的牌回到手牌"
        )

    bc.add_to_bot(Action(run))


EXHUME = CardDef("Exhume", "发掘", 1, "Skill",
                 "选择一张已消耗的牌，将其放入你的手牌。\n消耗。", False, True, _exhume_play,
                 upgraded_cost=0)  # Cards.h getUpgradedCost：EXHUME 升级 1→0（同 Havoc/Seeing Red）


def _feed_play(bc: BattleContext, item: CardQueueItem) -> None:
    up = item.card.upgraded
    dmg = bc.calculate_card_damage(item, item.target, 12 if up else 10)

    def run(bc: BattleContext) -> None:
        # 对齐 FeedAction：走完整攻击管线；目标死于本次攻击（C++ 另要求
        # 非随从/非半死/非重生——本引擎 Act 1 无此类怪，化简为死亡判定）
        # → maxHP +3/4 并回复等量 HP（C++ increaseMaxHp 内含 heal(amount)，
        # 即"击杀回 X 血"成立）。胜利清队不影响本动作（正在执行中）。
        m = bc.monsters.monsters[item.target]
        if m.is_dead_or_escaped():
            return
        m.attacked(bc, dmg)
        bc.check_combat()
        if not m.alive:
            n = 4 if up else 3
            bc.player.max_hp += n
            bc.player.heal(n, bc)

    bc.add_to_bot(Action(run))


FEED = CardDef("Feed", "狂宴", 1, "Attack", "造成 10 点伤害。\n斩杀时，永久获得 3 点最大生命。消耗。",
               True, True, _feed_play)


def _fiend_fire_play(bc: BattleContext, item: CardQueueItem) -> None:
    up = item.card.upgraded
    dmg = bc.calculate_card_damage(item, item.target, 10 if up else 7)

    def run(bc: BattleContext) -> None:
        # 对齐 FiendFireAction：执行时锁定手牌数 n，先 top 入队 n 段攻击、
        # 再 top 入队 n 次随机消耗 → 净结算序 = 随机消耗全部手牌 → n 段
        # 攻击（段数在消耗前锁定，与"消耗的牌数"无关地=原手牌数）
        n = len(bc.cards.hand)
        for _ in range(n):
            bc.add_to_top(Actions.attack_enemy(item.target, dmg))
        for _ in range(n):
            bc.add_to_top(Action(_exhaust_random_from_hand))

    bc.add_to_bot(Action(run))


FIEND_FIRE = CardDef("Fiend Fire", "恶魔之焰", 2, "Attack", "消耗所有手牌。\n每张被消耗的牌造成 7 点伤害。\n消耗。", True, True,
                     _fiend_fire_play)


def _immolate_play(bc: BattleContext, item: CardQueueItem) -> None:
    # C++ up?28:21（wiki 同）；1 张灼伤进弃牌堆
    bc.add_to_bot(Actions.attack_all_enemy(28 if item.card.upgraded else 21))
    bc.add_to_bot(Actions.make_temp_card_in_discard(BURN))


IMMOLATE = CardDef("Immolate", "燔祭", 2, "Attack", "对所有敌人造成 21 点伤害。\n将一张灼伤放入你的弃牌堆中。", False, False,
                   _immolate_play)


def _impervious_play(bc: BattleContext, item: CardQueueItem) -> None:
    bc.add_to_bot(Actions.gain_block(bc.calculate_card_block(40 if item.card.upgraded else 30)))


IMPERVIOUS = CardDef("Impervious", "岿然不动", 2, "Skill", "获得 30 点格挡。\n消耗。", False, True, _impervious_play)


def _juggernaut_play(bc: BattleContext, item: CardQueueItem) -> None:
    # wiki 口径：每次获得格挡对随机敌 5/7 伤。层恒 1（多张打出各自独立结算？
    # 本体多张 Juggernaut 伤害相加——用基数覆盖近似），基数经 special
    # ["juggernaut_base"] 写入（引擎 gain_block 已接线读此槽，审计接线）。
    bc.add_to_bot(Actions.buff_player(PlayerStatus.JUGGERNAUT, 1))
    bc.add_to_bot(Action(lambda bc2: bc2.player.special.update(
        juggernaut_base=7 if item.card.upgraded else 5)))


JUGGERNAUT = CardDef("Juggernaut", "势不可当", 2, "Power", "每当你获得格挡时，\n对随机一名敌人造成\n5 点伤害。", False, False,
                     _juggernaut_play)


def _limit_break_play(bc: BattleContext, item: CardQueueItem) -> None:
    # 对齐 doesCardExhaust：LIMIT_BREAK → !upgraded（仅基础版消耗）。
    # CardDef.exhausts 是模板级静态位，表达不了"按升级分支"，故在 play 里
    # 直接置 item.exhaust_on_use（use_card 在 play 之前已读过 exhausts，
    # 此处覆盖即最终值，on_after_use_card 按它落消耗堆）
    if not item.card.upgraded:
        item.exhaust_on_use = True

    def run(bc: BattleContext) -> None:
        # 对齐 LimitBreakAction：执行时力量翻倍
        n = bc.player.statuses.get(PlayerStatus.STRENGTH)
        bc.player.statuses.add(PlayerStatus.STRENGTH, n)

    bc.add_to_bot(Action(run))


LIMIT_BREAK = CardDef("Limit Break", "突破极限", 1, "Skill", "将你的力量翻倍。\n消耗。", False, False, _limit_break_play)


def _offering_play(bc: BattleContext, item: CardQueueItem) -> None:
    up = item.card.upgraded
    # 对齐 C++ OFFERING：失 6 HP（自伤）→ +2 能量 → 抽 3/5
    bc.add_to_bot(Actions.player_lose_hp(6, self_inflicted=True))
    bc.add_to_bot(Actions.gain_energy(2))
    bc.add_to_bot(Actions.draw_cards(5 if up else 3))


OFFERING = CardDef("Offering", "祭品", 0, "Skill", "失去 6 点生命。\n获得 2 点能量。\n抽 3 张牌。\n消耗。", False, True, _offering_play)


def _reaper_play(bc: BattleContext, item: CardQueueItem) -> None:
    base = 5 if item.card.upgraded else 4

    def run(bc: BattleContext) -> None:
        # 对齐 ReaperAction：按索引序逐怪走完整攻击管线（每怪独立算伤），
        # 吸血量 = 各怪实际掉落的 HP（被格挡吸收的不计）；逐段 attacked
        # （死亡即触发 die/checkCombat），heal 在循环后入 bot——若中途
        # 胜利，clearPostCombat 已先行执行，heal 照常落地（与 C++ 时序一致）
        heal = 0
        for m in bc.monsters.monsters:
            if m.is_dead_or_escaped():
                continue
            pre_hp = m.hp
            m.attacked(bc, bc.calculate_card_damage(item, m.idx, base))
            heal += pre_hp - m.hp
        if heal > 0:
            bc.add_to_bot(Actions.heal_player(heal))

    bc.add_to_bot(Action(run))


REAPER = CardDef("Reaper", "死亡收割", 2, "Attack", "对所有敌人造成 4 点伤害。未被格挡的伤害将回复你的生命。\n消耗。", False, True, _reaper_play)


def _rage_play(bc: BattleContext, item: CardQueueItem) -> None:
    # 2026-10-07 补齐：Rage.java（red uncommon）——ApplyPowerAction(RagePower, 3/5)。
    # 引擎触发段已有（on_use_attack_card 的 RAGE 分支 + 回合末移除）。
    bc.add_to_bot(Actions.buff_player(PlayerStatus.RAGE, 5 if item.card.upgraded else 3))


RAGE = CardDef("Rage", "狂怒", 0, "Skill", "打出此牌后，你在这个回合内每打出一张攻击牌，获得 3 格挡。", False, False, _rage_play)


__all__ = [
    # 基础,
    "STRIKE", "DEFEND", "BASH",
    # 普通,
    "ANGER", "ARMAMENTS", "BODY_SLAM", "CLASH", "CLEAVE", "CLOTHESLINE",
    "FLEX", "HAVOC", "HEADBUTT", "HEAVY_BLADE", "IRON_WAVE",
    "PERFECTED_STRIKE", "POMMEL_STRIKE", "SHRUG_IT_OFF", "SWORD_BOOMERANG",
    "THUNDERCLAP", "TRUE_GRIT", "TWIN_STRIKE", "WARCRY", "WILD_STRIKE",
    # 非普通,
    "BATTLE_TRANCE", "BLOOD_FOR_BLOOD", "BLOODLETTING", "BURNING_PACT",
    "CARNAGE", "COMBUST", "DARK_EMBRACE", "DISARM", "DROPKICK", "DUAL_WIELD",
    "ENTRENCH", "EVOLVE", "FEEL_NO_PAIN", "FIRE_BREATHING", "FLAME_BARRIER",
    "GHOSTLY_ARMOR", "HEMOKINESIS", "INFERNAL_BLADE", "INFLAME", "INTIMIDATE",
    "METALLICIZE", "POWER_THROUGH", "PUMMEL", "RAMPAGE", "RECKLESS_CHARGE",
    "RAGE", "RUPTURE", "SEARING_BLOW", "SECOND_WIND", "SEEING_RED", "SENTINEL",
    "SEVER_SOUL", "SHOCKWAVE", "SPOT_WEAKNESS", "UPPERCUT", "WHIRLWIND",
    # 稀有,
    "BARRICADE", "BERSERK", "BLUDGEON", "BRUTALITY", "CORRUPTION",
    "DEMON_FORM", "DOUBLE_TAP", "EXHUME", "FEED", "FIEND_FIRE", "IMMOLATE",
    "IMPERVIOUS", "JUGGERNAUT", "LIMIT_BREAK", "OFFERING", "REAPER",
    # 公共,
    "starting_deck",
]

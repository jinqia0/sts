"""Silent（静默）职业全卡移植：75 张（4 基础 + 19 普通 + 33 非普通 + 19 稀有）
+ 生成卡 SHIV。Alchemize（无药水系统）跳过，其余 74 张 + SHIV 全部正式定义。

权威源（与铁甲批次不同——lightspeed 的 C++ switch 只实现铁甲卡，Silent
效果全部走 default 未实现分支）：
- 数值/结算文本：slaythespire.wiki.gg（A0 基准，wiki 口径）
- 卡牌数据（费用/类型/消耗/固有）：Cards.h getEnergyCost / doesCardExhaust /
  isCardInnate / isXCost 交叉校验——注意 C++ getEnergyCost 对未列名的 Silent
  卡一律回落 1（如 LEG_SWEEP/PREDATOR/RIDDLE_WITH_HOLES/DASH/BOUNCING_FLASK/
  SNEAKY_STRIK 均与 wiki 不符），以 wiki 为准；doesCardExhaust 缺 TERROR 也
  以 wiki（消耗）为准。
- 状态结算语义：lightspeed Player.cpp/BattleContext.cpp/Monster.cpp 的
  已实现部分（AFTER_IMAGE=每打出一张牌得格挡、PHANTASMAL→DOUBLE_DAMAGE、
  WRAITH_FORM=回合末扣敏捷、CHOKED=回合开始清除等）。

引擎接线状态（前置提交 f0d724f 已接，本模块 play 落状态即可全流程生效）：
- ENVENOM（Monster._apply_damage）/ CORPSE_EXPLOSION（Monster.die）/ POISON
  （回合开始掉血减层）/ 弃牌管线 / Retain（实例 retain 位）——批次 A 起在位。
- AFTER_IMAGE / BURST / A_THOUSAND_CUTS / ACCURACY（按卡名 "Shiv" 识别）/
  PHANTASMAL_KILLER→DOUBLE_DAMAGE / NOXIOUS_FUMES / INFINITE_BLADES /
  next_turn_cards 生成槽 / special["wlp"] 回合末保留 / DRAW_REDUCTION——
  f0d724f 已接。注意三处与 wiki/C++ 的出入（迁移报告详述）：
  ① AFTER_IMAGE 引擎按"出技能生成 Shiv"结算；wiki 与 C++（BattleContext.cpp
     四处 onUseXxxCard 的 GainBlock 分支）均为"每打出一张牌得 1 格挡"。
  ② INFINITE_BLADES 引擎加了"上回合出过攻击牌"条件；wiki 与 C++
     （Player.cpp applyStartOfTurnPowers 无条件 MakeTempCardInHand）均无条件。
  ③ PHANTASMAL_KILLER 引擎落"首攻击后移除"的 DOUBLE_DAMAGE；wiki（"your
     Attacks deal double damage"）与 C++（DOUBLE_DAMAGE 全回合乘 2、回合末
     applyAtEndOfRoundPowers 才衰减）均为下回合全部攻击翻倍。

仍需引擎接线的槽位（本模块 play 只落标记，逐项见迁移报告）：
- special["next_turn_energy"]（Flying Knee/Outmaneuver/Doppelganger）：
  _recharge_energy 读后清零。
- special["next_turn_draw"]（Predator/Doppelganger）：after_monster_turns 抽牌加量。
- special["blur_next_turn"]（Blur）：after_monster_turns 格挡衰减豁免一轮。
- special["tott_draw"]（Tools of the Trade）：回合开始抽 1 弃 1。
- special["wraith_form_dex"]（Wraith Form）：回合末敏捷 -层数（C++ WRAITH_FORM
  状态的 DecrementStatus<DEXTERITY> 对应物）。
- CHOKED（Choke）：use_card 出牌对带 CHOKED 的怪造成层数伤 + 怪回合开始清除
  （Monster.cpp:24-26）；引擎 use_card/on_use_xxx_card 未接。
- Endless Agony 抽到复制（on_card_drawn 无内容层钩子）。
- Eviscerate 动态费用（play 前读 cards_discarded_this_turn 改 cost）：引擎
  play_card 只读静态 cost，本实现以"按名义 3 费支付、结算后退还减费额"近似
  （能量收支与本体一致；能量 <3 时不可打出为已知偏差）。
- Well-Laid Plans 升级版选 2 张：引擎 wlp 分支 pick_count 写死 1。

与包结构的关系：本文件为 Silent 卡唯一正式定义，经包 __init__
eager re-export 暴露；CardDef 取自 _base.py，_strike_play 复用自
ironclad.py。STRIKE_S/DEFEND_S 沿用卡名 "Strike"/"Defend"
（观测词表按 "模块:常量名" 身份区分，sts/vocab.py，同名跨职业不冲突）。
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from sts.combat.actions import Actions
from sts.combat.card_manager import MAX_HAND_SIZE
from sts.combat.queue import Action
from sts.combat.types import MonsterStatus, Outcome, PlayerStatus

from sts.content.cards._base import CardDef, _strike_play

if TYPE_CHECKING:
    from sts.combat.battle import BattleContext
    from sts.combat.card_manager import CardInstance
    from sts.combat.queue import CardQueueItem


# ============================================================
# 公共设施
# ============================================================


def _unplayable_noop(bc: BattleContext, item: CardQueueItem) -> None:
    """不可打出技能（Tactician/Reflex）的 play 占位：正常出牌被 play_card
    的 unplayable 位拦截，Havoc/Mayhem 等强制入队结算时无效果。"""
    pass


def _add_temp_to_hand(bc: BattleContext, inst: CardInstance) -> None:
    """临时牌入手；手满落弃牌堆（对齐 moveToHandHelper，上限 10）。"""
    if len(bc.cards.hand) < MAX_HAND_SIZE:
        bc.cards.hand.append(inst)
    else:
        bc.cards.move_to_discard_pile(inst)


def _add_next_turn_energy(bc: BattleContext, n: int) -> None:
    """下回合能量槽（Flying Knee/Outmaneuver/Doppelganger；引擎接线待接，
    见模块注释）。"""
    bc.player.special["next_turn_energy"] = bc.player.special.get("next_turn_energy", 0) + n


def _add_next_turn_draw(bc: BattleContext, n: int) -> None:
    """下回合额外抽牌槽（Predator/Doppelganger；引擎接线待接，见模块注释）。"""
    bc.player.special["next_turn_draw"] = bc.player.special.get("next_turn_draw", 0) + n


def _silent_skill_pool() -> list:
    """随机技能池（Distraction；对齐 returnTrulyRandomCardInCombat(SKILL) 的
    "职业卡池"口径：Silent 技能 + 无色技能，含不可打出的 Tactician/Reflex——
    本体奖励池同样收录）。"""
    import sys

    import sts.content.cards.colorless as cc

    pool = [g for g in vars(sys.modules[__name__]).values()
            if isinstance(g, CardDef) and g.ctype == "Skill"]
    pool += [g for g in vars(cc).values() if isinstance(g, CardDef) and g.ctype == "Skill"]
    return pool


def _random_alive(bc: BattleContext) -> int:
    """随机存活敌人索引（misc 流，分布级等价 C++ cardRandom 流）。"""
    alive = [m for m in bc.monsters.monsters if m.is_targetable()]
    if not alive:
        return -1
    return alive[bc.rngs.misc.int_inclusive(0, len(alive) - 1)].idx


# ============================================================
# 基础 4 张 + SHIV
# ============================================================


def _neutralize_play(bc: BattleContext, item: CardQueueItem) -> None:
    up = item.card.upgraded
    # wiki：造成 3 伤 + 1 弱（+：4 伤 + 2 弱）
    dmg = bc.calculate_card_damage(item, item.target, 4 if up else 3)
    bc.add_to_bot(Actions.attack_enemy(item.target, dmg))
    bc.add_to_bot(Actions.debuff_enemy(item.target, MonsterStatus.WEAK, 2 if up else 1, False))


def _defend_s_play(bc: BattleContext, item: CardQueueItem) -> None:
    # wiki：获得 5 格挡（+：8）。不复用铁甲 _defend_play——后者不读升级位
    #（铁甲既有口径），静默版按 wiki 满足 Defend+ 8 格挡
    bc.add_to_bot(Actions.gain_block(bc.calculate_card_block(8 if item.card.upgraded else 5)))


def _survivor_play(bc: BattleContext, item: CardQueueItem) -> None:
    # wiki：获得 8 格挡，弃 1 张牌（+：11 格挡）
    bc.add_to_bot(Actions.gain_block(bc.calculate_card_block(11 if item.card.upgraded else 8)))
    bc.add_to_bot(Actions.discard_chosen(1))


def _shiv_play(bc: BattleContext, item: CardQueueItem) -> None:
    # wiki：0 费攻击，造成 4 伤，消耗（Shiv+：6 伤）
    dmg = bc.calculate_card_damage(item, item.target, 6 if item.card.upgraded else 4)
    bc.add_to_bot(Actions.attack_enemy(item.target, dmg))


STRIKE_S = CardDef("Strike", "打击", 1, "Attack", "造成 6 点伤害。", True, False, _strike_play)
DEFEND_S = CardDef("Defend", "防御", 1, "Skill", "获得 5 点格挡。", False, False, _defend_s_play)
NEUTRALIZE = CardDef("Neutralize", "中和", 0, "Attack", "造成 3 点伤害。\n给予 1 层虚弱。",
                     True, False, _neutralize_play)
SURVIVOR = CardDef("Survivor", "生存者", 1, "Skill", "获得 8 点格挡。\n丢弃一张牌。",
                   False, False, _survivor_play)
SHIV = CardDef("Shiv", "小刀", 0, "Attack", "造成 4 点伤害。\n消耗。", True, True, _shiv_play)


# ============================================================
# 普通 19 张
# ============================================================


def _acrobatics_play(bc: BattleContext, item: CardQueueItem) -> None:
    # wiki：抽 3 张牌，弃 1 张（+：抽 4）
    bc.add_to_bot(Actions.draw_cards(4 if item.card.upgraded else 3))
    bc.add_to_bot(Actions.discard_chosen(1))


def _backflip_play(bc: BattleContext, item: CardQueueItem) -> None:
    # wiki：获得 5 格挡，抽 2 张（+：8 格挡）
    bc.add_to_bot(Actions.gain_block(bc.calculate_card_block(8 if item.card.upgraded else 5)))
    bc.add_to_bot(Actions.draw_cards(2))


def _bane_play(bc: BattleContext, item: CardQueueItem) -> None:
    up = item.card.upgraded
    # wiki：造成 7 伤；若敌人有中毒，再造成 7 伤（+：10/10）。两段共用出牌时
    # 算好的伤害；第二段结算时检查目标存活 + 中毒（对齐 BaneAction 时机）
    base = 10 if up else 7
    dmg = bc.calculate_card_damage(item, item.target, base)
    bc.add_to_bot(Actions.attack_enemy(item.target, dmg))

    def run(bc2: BattleContext) -> None:
        m = bc2.monsters.monsters[item.target]
        if not m.is_dead_or_escaped() and m.statuses.has(MonsterStatus.POISON):
            m.attacked(bc2, dmg)
            bc2.check_combat()

    bc.add_to_bot(Action(run))


def _blade_dance_play(bc: BattleContext, item: CardQueueItem) -> None:
    # wiki：加 3 张袖剑到手牌（+：4 张）
    for _ in range(4 if item.card.upgraded else 3):
        bc.add_to_bot(Actions.make_temp_card_in_hand(SHIV))


def _cloak_and_dagger_play(bc: BattleContext, item: CardQueueItem) -> None:
    # wiki：获得 6 格挡，加 1 张袖剑到手牌（+：2 张袖剑，格挡不变）
    bc.add_to_bot(Actions.gain_block(bc.calculate_card_block(6)))
    for _ in range(2 if item.card.upgraded else 1):
        bc.add_to_bot(Actions.make_temp_card_in_hand(SHIV))


def _dagger_spray_play(bc: BattleContext, item: CardQueueItem) -> None:
    # wiki：对所有敌人造成 4 点伤害两次（+：6 点）。attack_all_enemy 内部逐怪
    # 走完整管线，两段各自独立计算（目标状态在两段间可能变化）
    base = 6 if item.card.upgraded else 4
    bc.add_to_bot(Actions.attack_all_enemy(base))
    bc.add_to_bot(Actions.attack_all_enemy(base))


def _dagger_throw_play(bc: BattleContext, item: CardQueueItem) -> None:
    # wiki：造成 9 伤，抽 1 张牌，弃 1 张牌（+：12 伤）
    dmg = bc.calculate_card_damage(item, item.target, 12 if item.card.upgraded else 9)
    bc.add_to_bot(Actions.attack_enemy(item.target, dmg))
    bc.add_to_bot(Actions.draw_cards(1))
    bc.add_to_bot(Actions.discard_chosen(1))


def _deadly_poison_play(bc: BattleContext, item: CardQueueItem) -> None:
    # wiki：施加 5 层中毒（+：7 层）
    bc.add_to_bot(Actions.debuff_enemy(item.target, MonsterStatus.POISON, 7 if item.card.upgraded else 5))


def _deflect_play(bc: BattleContext, item: CardQueueItem) -> None:
    # wiki：获得 4 格挡（+：7）
    bc.add_to_bot(Actions.gain_block(bc.calculate_card_block(7 if item.card.upgraded else 4)))


def _dodge_and_roll_play(bc: BattleContext, item: CardQueueItem) -> None:
    # wiki：获得 4 格挡。下回合再获得 4 格挡（+：6/6）。下回合格挡走
    # NEXT_TURN_BLOCK 状态（引擎回合开始结算：得格挡后移除，可叠加）
    n = 6 if item.card.upgraded else 4
    bc.add_to_bot(Actions.gain_block(bc.calculate_card_block(n)))
    bc.add_to_bot(Actions.buff_player(PlayerStatus.NEXT_TURN_BLOCK, n))


def _flying_knee_play(bc: BattleContext, item: CardQueueItem) -> None:
    # wiki：造成 8 伤。下回合获得 1 能量（+：11 伤）。下回合能量走
    # special["next_turn_energy"] 槽（引擎 _recharge_energy 接线待接）
    dmg = bc.calculate_card_damage(item, item.target, 11 if item.card.upgraded else 8)
    bc.add_to_bot(Actions.attack_enemy(item.target, dmg))
    bc.add_to_bot(Action(lambda bc2: _add_next_turn_energy(bc2, 1)))


def _outmaneuver_play(bc: BattleContext, item: CardQueueItem) -> None:
    # wiki：下回合获得 2 能量（+：3）
    bc.add_to_bot(Action(lambda bc2: _add_next_turn_energy(bc2, 3 if item.card.upgraded else 2)))


def _piercing_wail_play(bc: BattleContext, item: CardQueueItem) -> None:
    # wiki：所有敌人本回合失去 6 点力量。消耗（+：8 点）。"本回合"以
    # SHACKLED 配对状态表达：怪回合末（apply_end_of_turn_triggers）回补，
    # 与 Dark Shackles 同款（wiki 口径力量 -X + SHACKLED X；ARTIFACT 抵消则
    # 两不落地）
    x = 8 if item.card.upgraded else 6

    def run(bc2: BattleContext) -> None:
        for m in bc2.monsters.monsters:
            if m.is_dead_or_escaped():
                continue
            if m.statuses.has(MonsterStatus.ARTIFACT):
                m.statuses.decrement(MonsterStatus.ARTIFACT)
                continue
            m.statuses.add(MonsterStatus.STRENGTH, -x)
            m.statuses.add(MonsterStatus.SHACKLED, x)

    bc.add_to_bot(Action(run))


def _poisoned_stab_play(bc: BattleContext, item: CardQueueItem) -> None:
    up = item.card.upgraded
    # wiki：造成 6 伤，施加 3 层中毒（+：8 伤 4 层）
    dmg = bc.calculate_card_damage(item, item.target, 8 if up else 6)
    bc.add_to_bot(Actions.attack_enemy(item.target, dmg))
    bc.add_to_bot(Actions.debuff_enemy(item.target, MonsterStatus.POISON, 4 if up else 3))


def _prepared_play(bc: BattleContext, item: CardQueueItem) -> None:
    # wiki：抽 1 张牌，弃 1 张牌（+：各 2 张）。先抽后弃——弃牌候选含新抽的牌
    n = 2 if item.card.upgraded else 1
    bc.add_to_bot(Actions.draw_cards(n))
    bc.add_to_bot(Actions.discard_chosen(n))


def _quick_slash_play(bc: BattleContext, item: CardQueueItem) -> None:
    # wiki：造成 8 伤，抽 1 张牌（+：12 伤）
    dmg = bc.calculate_card_damage(item, item.target, 12 if item.card.upgraded else 8)
    bc.add_to_bot(Actions.attack_enemy(item.target, dmg))
    bc.add_to_bot(Actions.draw_cards(1))


def _slice_play(bc: BattleContext, item: CardQueueItem) -> None:
    # wiki：造成 6 伤（+：9）
    dmg = bc.calculate_card_damage(item, item.target, 9 if item.card.upgraded else 6)
    bc.add_to_bot(Actions.attack_enemy(item.target, dmg))


def _sneaky_strike_play(bc: BattleContext, item: CardQueueItem) -> None:
    # wiki：造成 12 伤。若本回合弃过牌，获得 2 能量（+：16 伤）。条件结算
    # 时读取 cards_discarded_this_turn（弃牌管线计数）
    dmg = bc.calculate_card_damage(item, item.target, 16 if item.card.upgraded else 12)
    bc.add_to_bot(Actions.attack_enemy(item.target, dmg))

    def run(bc2: BattleContext) -> None:
        if bc2.player.cards_discarded_this_turn > 0:
            bc2.player.energy += 2

    bc.add_to_bot(Action(run))


def _sucker_punch_play(bc: BattleContext, item: CardQueueItem) -> None:
    up = item.card.upgraded
    # wiki：造成 7 伤，施加 1 层虚弱（+：9 伤 2 层）
    dmg = bc.calculate_card_damage(item, item.target, 9 if up else 7)
    bc.add_to_bot(Actions.attack_enemy(item.target, dmg))
    bc.add_to_bot(Actions.debuff_enemy(item.target, MonsterStatus.WEAK, 2 if up else 1, False))


ACROBATICS = CardDef("Acrobatics", "杂技", 1, "Skill", "抽 3 张牌。\n丢弃 1 张牌。",
                     False, False, _acrobatics_play)
BACKFLIP = CardDef("Backflip", "后空翻", 1, "Skill", "获得 5 点格挡。\n抽 2 张牌。",
                   False, False, _backflip_play)
BANE = CardDef("Bane", "灾祸", 1, "Attack", "造成 7 点伤害。\n如果敌人有中毒状态，则再次造成 7 点伤害。",
               True, False, _bane_play)
BLADE_DANCE = CardDef("Blade Dance", "刀刃之舞", 1, "Skill", "增加 3 张小刀到你的手牌。",
                     False, False, _blade_dance_play)
CLOAK_AND_DAGGER = CardDef("Cloak and Dagger", "斗篷与匕首", 1, "Skill", "获得 6 点格挡。\n增加 1 张小刀到你的手牌。",
                          False, False, _cloak_and_dagger_play)
DAGGER_SPRAY = CardDef("Dagger Spray", "匕首雨", 1, "Attack", "对所有敌人造成 4 点伤害两次。",
                       False, False, _dagger_spray_play)
DAGGER_THROW = CardDef("Dagger Throw", "投掷匕首", 1, "Attack", "造成 9 点伤害。\n抽一张牌。\n丢弃一张牌。",
                       True, False, _dagger_throw_play)
DEADLY_POISON = CardDef("Deadly Poison", "致命毒药", 1, "Skill", "给予 5 层中毒。",
                       True, False, _deadly_poison_play)
DEFLECT = CardDef("Deflect", "偏折", 0, "Skill", "获得 4 点格挡。",
                  False, False, _deflect_play)
DODGE_AND_ROLL = CardDef("Dodge and Roll", "闪躲翻滚", 1, "Skill", "获得 4 点格挡。\n在下一回合获得 4 点格挡。",
                         False, False, _dodge_and_roll_play)
FLYING_KNEE = CardDef("Flying Knee", "飞膝", 1, "Attack", "造成 8 点伤害。\n在下一回合获得 1 点能量。",
                      True, False, _flying_knee_play)
OUTMANEUVER = CardDef("Outmaneuver", "抢占先机", 1, "Skill", "下一回合\n获得 2 点能量。",
                      False, False, _outmaneuver_play)
PIERCING_WAIL = CardDef("Piercing Wail", "尖啸", 1, "Skill", "所有敌人失去 6 力量 1 回合。\n消耗。",
                        False, True, _piercing_wail_play)
POISONED_STAB = CardDef("Poisoned Stab", "带毒刺击", 1, "Attack", "造成 6 点伤害。\n给予 3 层中毒。",
                        True, False, _poisoned_stab_play)
PREPARED = CardDef("Prepared", "早有准备", 0, "Skill", "抽 1 张牌。\n丢弃 1 张牌。",
                   False, False, _prepared_play)
QUICK_SLASH = CardDef("Quick Slash", "快斩", 1, "Attack", "造成 8 点伤害。\n抽 1 张牌。",
                      True, False, _quick_slash_play)
SLICE = CardDef("Slice", "切割", 0, "Attack", "造成 6 点伤害。",
                True, False, _slice_play)
SNEAKY_STRIKE = CardDef("Sneaky Strike", "隐秘打击", 2, "Attack", "造成 12 点伤害。\n如果你在这回合丢弃过牌，获得 2 点能量。",
                        True, False, _sneaky_strike_play)
SUCKER_PUNCH = CardDef("Sucker Punch", "突然一拳", 1, "Attack", "造成 7 点伤害。\n给予 1 层虚弱。",
                       True, False, _sucker_punch_play)


# ============================================================
# 非普通 33 张
# ============================================================


def _accuracy_play(bc: BattleContext, item: CardQueueItem) -> None:
    # wiki：袖剑造成 4 点额外伤害（+：6 点）。状态层=附加伤害（多次施放叠加）
    bc.add_to_bot(Actions.buff_player(PlayerStatus.ACCURACY, 6 if item.card.upgraded else 4))


def _all_out_attack_play(bc: BattleContext, item: CardQueueItem) -> None:
    # wiki：对所有敌人造成 10 伤，随机弃 1 张牌（+：14 伤）
    bc.add_to_bot(Actions.attack_all_enemy(14 if item.card.upgraded else 10))
    bc.add_to_bot(Actions.discard_random_from_hand(1))


def _backstab_play(bc: BattleContext, item: CardQueueItem) -> None:
    # wiki：固有。造成 11 伤。消耗（+：15 伤）。消耗位对齐 Cards.h
    # doesCardExhaust（BACKSTAB 在列）
    dmg = bc.calculate_card_damage(item, item.target, 15 if item.card.upgraded else 11)
    bc.add_to_bot(Actions.attack_enemy(item.target, dmg))


def _blur_play(bc: BattleContext, item: CardQueueItem) -> None:
    # wiki：获得 5 格挡。格挡在下回合开始时不消失（+：8 格挡）。以
    # special["blur_next_turn"] 标记，after_monster_turns 格挡衰减段接线待接
    bc.add_to_bot(Actions.gain_block(bc.calculate_card_block(8 if item.card.upgraded else 5)))
    bc.add_to_bot(Action(lambda bc2: bc2.player.special.update(blur_next_turn=1)))


def _bouncing_flask_play(bc: BattleContext, item: CardQueueItem) -> None:
    # wiki：对随机敌人施加 3 层中毒，共 3 次（+：4 次）。每次独立随机（可
    # 连中同一目标）；死亡中的怪不可再被抽中
    times = 4 if item.card.upgraded else 3

    def run(bc2: BattleContext) -> None:
        for _ in range(times):
            idx = _random_alive(bc2)
            if idx < 0:
                return
            bc2.add_to_bot(Actions.debuff_enemy(idx, MonsterStatus.POISON, 3))

    bc.add_to_bot(Action(run))


def _calculated_gamble_play(bc: BattleContext, item: CardQueueItem) -> None:
    # wiki：弃掉所有手牌，抽等量的牌。消耗（+：不消耗）。张数在结算时锁定
    # （弃牌堆经洗牌回流不影响本张数量）。仅基础版消耗——静态位表达不了
    # "按升级分支"，play 里置 exhaust_on_use（同 Limit Break 模式）
    if not item.card.upgraded:
        item.exhaust_on_use = True

    def run(bc2: BattleContext) -> None:
        n = len(bc2.cards.hand)
        for inst in list(bc2.cards.hand):
            bc2.manual_discard(inst)
        bc2.add_to_bot(Actions.draw_cards(n))

    bc.add_to_bot(Action(run))


def _caltrops_play(bc: BattleContext, item: CardQueueItem) -> None:
    # wiki：受到攻击时对攻击者反弹 3 伤（+：5 伤）。玩家 THORNS 状态
    # （Player.attacked 已接线，无论是否漏格挡都反弹）
    bc.add_to_bot(Actions.buff_player(PlayerStatus.THORNS, 5 if item.card.upgraded else 3))


def _catalyst_play(bc: BattleContext, item: CardQueueItem) -> None:
    # wiki：使敌人的中毒翻倍（+：三倍）。消耗。结算时读当前层数补差
    #（无中毒则无效果）；翻倍不是新施加 debuff，不吃 ARTIFACT
    mult = 3 if item.card.upgraded else 2
    t = item.target

    def run(bc2: BattleContext) -> None:
        m = bc2.monsters.monsters[t]
        if m.is_dead_or_escaped():
            return
        p = m.statuses.get(MonsterStatus.POISON)
        if p > 0:
            m.statuses.add(MonsterStatus.POISON, p * (mult - 1))

    bc.add_to_bot(Action(run))


def _choke_play(bc: BattleContext, item: CardQueueItem) -> None:
    # wiki：造成 12 伤。本回合你每打出一张牌，该敌人失去 3 点 HP（+：12 伤
    # /5 点 HP）。伤害两版均为 12，升级只提升每次掉血。掉血触发段
    # （use_card × CHOKED）与回合开始清除（Monster.cpp:24-26）需引擎接线
    dmg = bc.calculate_card_damage(item, item.target, 12)
    bc.add_to_bot(Actions.attack_enemy(item.target, dmg))
    bc.add_to_bot(Actions.debuff_enemy(item.target, MonsterStatus.CHOKED, 5 if item.card.upgraded else 3))


def _concentrate_play(bc: BattleContext, item: CardQueueItem) -> None:
    # wiki：弃 3 张牌，获得 2 点能量（+：弃 2 张牌）。0 费；能量两版均 2
    # （wiki 图标计数口径）
    bc.add_to_bot(Actions.discard_chosen(2 if item.card.upgraded else 3))
    bc.add_to_bot(Actions.gain_energy(2))


def _crippling_cloud_play(bc: BattleContext, item: CardQueueItem) -> None:
    # wiki：对所有敌人施加 4 层中毒和 2 层虚弱。消耗（+：7 层中毒）。
    # 消耗位对齐 Cards.h doesCardExhaust（CRIPPLING_CLOUD 在列）
    bc.add_to_bot(Actions.debuff_all_enemy(MonsterStatus.POISON, 7 if item.card.upgraded else 4, False))
    bc.add_to_bot(Actions.debuff_all_enemy(MonsterStatus.WEAK, 2, False))


def _dash_play(bc: BattleContext, item: CardQueueItem) -> None:
    # wiki：获得 10 格挡，造成 10 伤（+：13/13）。先格挡后攻击
    n = 13 if item.card.upgraded else 10
    bc.add_to_bot(Actions.gain_block(bc.calculate_card_block(n)))
    dmg = bc.calculate_card_damage(item, item.target, n)
    bc.add_to_bot(Actions.attack_enemy(item.target, dmg))


def _distraction_play(bc: BattleContext, item: CardQueueItem) -> None:
    # wiki：随机 1 张技能牌加入手牌，本回合 0 费。消耗（+：费用 0）。
    # 池 = Silent 技能 + 无色技能（对齐 returnTrulyRandomCardInCombat 单职业
    # 池口径）；升级仅改费 1→0（wiki desc 两版文本相同，费用差异见卡页）
    def run(bc2: BattleContext) -> None:
        pool = _silent_skill_pool()
        card = pool[bc2.rngs.misc.int_inclusive(0, len(pool) - 1)]
        inst = bc2.cards.instantiate(card)
        inst.cost_for_turn = 0
        _add_temp_to_hand(bc2, inst)

    bc.add_to_bot(Action(run))


def _endless_agony_play(bc: BattleContext, item: CardQueueItem) -> None:
    # wiki：抽到这张牌时，将一张它的副本加入手牌。造成 4 伤。消耗
    #（+：6 伤）。无虚无词条（wiki desc 无 Ethereal）。抽到复制需引擎
    # on_card_drawn 钩子（接线待接，见模块注释）
    dmg = bc.calculate_card_damage(item, item.target, 6 if item.card.upgraded else 4)
    bc.add_to_bot(Actions.attack_enemy(item.target, dmg))


def _escape_plan_play(bc: BattleContext, item: CardQueueItem) -> None:
    # wiki：抽 1 张牌。若抽到的是技能牌，获得 3 格挡（+：5 格挡）。
    # 以 unique_id 差集识别新抽的牌（手满溢出落弃牌堆的也在检查范围内）
    n = 5 if item.card.upgraded else 3

    def run(bc2: BattleContext) -> None:
        before = {c.unique_id for c in bc2.cards.hand}
        before_d = {c.unique_id for c in bc2.cards.discard_pile}
        bc2.draw_cards(1)
        drawn = [c for c in bc2.cards.hand if c.unique_id not in before] + [
            c for c in bc2.cards.discard_pile if c.unique_id not in before_d]
        if any(c.card.ctype == "Skill" for c in drawn):
            bc2.add_to_bot(Actions.gain_block(bc2.calculate_card_block(n)))

    bc.add_to_bot(Action(run))


def _eviscerate_play(bc: BattleContext, item: CardQueueItem) -> None:
    # wiki：每弃 1 张牌（本回合）费用 -1。造成 7 伤 3 次（+：9 伤 3 次）。
    # 动态费用走引擎 dynamic_cost 钩子（已接线，见 CardDef 定义处），
    # 原"结算后退还"近似已移除
    dmg = bc.calculate_card_damage(item, item.target, 9 if item.card.upgraded else 7)
    for _ in range(3):
        bc.add_to_bot(Actions.attack_enemy(item.target, dmg))


def _expertise_play(bc: BattleContext, item: CardQueueItem) -> None:
    # wiki：抽牌直到手牌有 6 张（+：7 张）
    target = 7 if item.card.upgraded else 6

    def run(bc2: BattleContext) -> None:
        need = target - len(bc2.cards.hand)
        if need > 0:
            bc2.draw_cards(need)

    bc.add_to_bot(Action(run))


def _finisher_play(bc: BattleContext, item: CardQueueItem) -> None:
    # wiki：本回合每打出过 1 张攻击牌，造成 6 伤（+：8 伤）。计数含自身
    #（on_use_attack_card 先于动作出队执行，结算时 attacks_played_this_turn
    # 已计入 Finisher）。多段共用同一伤害
    base = 8 if item.card.upgraded else 6

    def run(bc2: BattleContext) -> None:
        count = bc2.player.attacks_played_this_turn
        dmg = bc2.calculate_card_damage(bc2.cur_card_queue_item, item.target, base)
        for _ in range(count):
            bc2.add_to_bot(Actions.attack_enemy(item.target, dmg))

    bc.add_to_bot(Action(run))


def _flechettes_play(bc: BattleContext, item: CardQueueItem) -> None:
    # wiki：手中每有 1 张技能牌，造成 4 伤（+：6 伤）。结算时读手牌
    #（自身已离手不计）
    base = 6 if item.card.upgraded else 4

    def run(bc2: BattleContext) -> None:
        count = sum(1 for c in bc2.cards.hand if c.card.ctype == "Skill")
        if count <= 0:
            return
        dmg = bc2.calculate_card_damage(bc2.cur_card_queue_item, item.target, base)
        for _ in range(count):
            bc2.add_to_bot(Actions.attack_enemy(item.target, dmg))

    bc.add_to_bot(Action(run))


def _footwork_play(bc: BattleContext, item: CardQueueItem) -> None:
    # wiki：获得 2 点敏捷（+：3 点）
    bc.add_to_bot(Actions.buff_player(PlayerStatus.DEXTERITY, 3 if item.card.upgraded else 2))


def _heel_hook_play(bc: BattleContext, item: CardQueueItem) -> None:
    # wiki：造成 5 伤。若敌人有虚弱，获得 1 点能量并抽 1 张牌（+：8 伤）。
    # 对齐 Dropkick 模式：结算时检查目标状态，攻击先于奖励
    up = item.card.upgraded
    t = item.target

    def run(bc2: BattleContext) -> None:
        m = bc2.monsters.monsters[t]
        if m.is_dead_or_escaped():
            return
        bonus = m.statuses.has(MonsterStatus.WEAK)
        dmg = bc2.calculate_card_damage(bc2.cur_card_queue_item, t, 8 if up else 5)
        m.attacked(bc2, dmg)
        bc2.check_combat()
        if bonus and bc2.outcome == Outcome.UNDECIDED:
            bc2.player.energy += 1
            bc2.draw_cards(1)

    bc.add_to_bot(Action(run))


def _infinite_blades_play(bc: BattleContext, item: CardQueueItem) -> None:
    # wiki：回合开始时加 1 张袖剑到手牌（+：固有）。无"上回合出过攻击牌"
    # 条件（wiki desc 与 C++ Player.cpp 均无条件；引擎 f0d724f 接线带条件，
    # 出入见迁移报告）。层数×每层张数：多张叠加各生成
    bc.add_to_bot(Actions.buff_player(PlayerStatus.INFINITE_BLADES, 1))


def _leg_sweep_play(bc: BattleContext, item: CardQueueItem) -> None:
    # wiki：施加 2 层虚弱。获得 11 格挡（+：3 层 / 14 格挡）
    up = item.card.upgraded
    bc.add_to_bot(Actions.debuff_enemy(item.target, MonsterStatus.WEAK, 3 if up else 2, False))
    bc.add_to_bot(Actions.gain_block(bc.calculate_card_block(14 if up else 11)))


def _masterful_stab_play(bc: BattleContext, item: CardQueueItem) -> None:
    # wiki：本场战斗你每次失去 HP，此牌费用 +1。造成 12 伤（+：16 伤）。
    # 0 费。费用递增走引擎 cost_delta_on_damage=+1（on_player_damaged 对
    # 手/抽/弃三堆实例 update_cost，"本场战斗"口径一致）
    dmg = bc.calculate_card_damage(item, item.target, 16 if item.card.upgraded else 12)
    bc.add_to_bot(Actions.attack_enemy(item.target, dmg))


def _noxious_fumes_play(bc: BattleContext, item: CardQueueItem) -> None:
    # wiki：回合开始时对所有敌人施加 2 层中毒（+：3 层）。层数=每回合施毒量
    #（多次施放叠加）；结算在引擎 after_monster_turns（f0d724f 已接）
    bc.add_to_bot(Actions.buff_player(PlayerStatus.NOXIOUS_FUMES, 3 if item.card.upgraded else 2))


def _predator_play(bc: BattleContext, item: CardQueueItem) -> None:
    # wiki：造成 15 伤。下回合多抽 2 张牌（+：20 伤，抽牌量不变）。
    # 额外抽牌走 special["next_turn_draw"] 槽（接线待接）
    dmg = bc.calculate_card_damage(item, item.target, 20 if item.card.upgraded else 15)
    bc.add_to_bot(Actions.attack_enemy(item.target, dmg))
    bc.add_to_bot(Action(lambda bc2: _add_next_turn_draw(bc2, 2)))


def _reflex_on_discard(bc: BattleContext, inst: CardInstance) -> None:
    # wiki：不可打出。从手中被弃置时，抽 2 张牌（+：3 张）。引擎弃牌管线
    # （manual_discard → on_manual_discard → on_discard_effect）已接线，
    # 可全流程断言
    bc.add_to_bot(Actions.draw_cards(3 if inst.upgraded else 2))


def _riddle_with_holes_play(bc: BattleContext, item: CardQueueItem) -> None:
    # wiki：造成 3 伤 5 次（+：4 伤 5 次）。多段共用同一伤害
    dmg = bc.calculate_card_damage(item, item.target, 4 if item.card.upgraded else 3)
    for _ in range(5):
        bc.add_to_bot(Actions.attack_enemy(item.target, dmg))


def _setup_play(bc: BattleContext, item: CardQueueItem) -> None:
    # wiki：将 1 张手牌置于抽牌堆顶。它 0 费直到被打出（+：费用 0）。
    # 不消耗（wiki desc 无 Exhaust，Cards.h 亦未收录）。"0 费直到打出"
    # 以 cost_override=0 近似（同 Forethought 口径，与"仅首次免费"的差异
    # 在同名实例再次抽到重打时显现——迁移报告记录）
    def run(bc2: BattleContext) -> None:
        cands = list(bc2.cards.hand)

        def on_choose(bc3: BattleContext, chosen: list) -> None:
            for inst in chosen:
                if inst.cost > 0:
                    inst.cost_override = 0
                bc3.cards.hand.remove(inst)
                bc3.cards.append_to_draw_top(inst)

        bc2.open_card_select(cands, on_choose, can_pick_zero=True,
                             prompt="布置：选择 1 张手牌置于抽牌堆顶")

    bc.add_to_bot(Action(run))


def _skewer_play(bc: BattleContext, item: CardQueueItem) -> None:
    # wiki：X 费：造成 7 伤 X 次（+：10 伤）。能量由引擎 x_cost 路径在出牌时
    # 快照进 energy_on_use 并清零；多段共用同一伤害
    dmg = bc.calculate_card_damage(item, item.target, 10 if item.card.upgraded else 7)
    for _ in range(max(item.energy_on_use, 0)):
        bc.add_to_bot(Actions.attack_enemy(item.target, dmg))


def _tactician_on_discard(bc: BattleContext, inst: CardInstance) -> None:
    # wiki：不可打出。从手中被弃置时，获得 1 点能量（+：2 点）
    #（wiki 图标计数口径：基础 1 枚能量图标、升级 2 枚）
    bc.add_to_bot(Actions.gain_energy(2 if inst.upgraded else 1))


def _terror_play(bc: BattleContext, item: CardQueueItem) -> None:
    # wiki：施加 99 层易伤。消耗（+：费用 0）。Cards.h doesCardExhaust 未收录
    # TERROR（偏差），以 wiki 消耗口径为准
    bc.add_to_bot(Actions.debuff_enemy(item.target, MonsterStatus.VULNERABLE, 99))


def _well_laid_plans_play(bc: BattleContext, item: CardQueueItem) -> None:
    # wiki：回合结束时保留至多 1 张牌（+：2 张）。以 special["wlp"] 槽表达
    #（引擎 call_end_turn_actions 的 wlp 分支 f0d724f 已接：回合末 CARD_SELECT
    # 选 1 张置 retain）。升级版选 2 张的 pick_count 差异列入迁移报告
    bc.player.special["wlp"] = 2 if item.card.upgraded else 1


ACCURACY = CardDef("Accuracy", "精准", 1, "Power", "小刀造成的伤害增加 4。",
                   False, False, _accuracy_play)
ALL_OUT_ATTACK = CardDef("All-Out Attack", "全力攻击", 1, "Attack", "对所有敌人造成 10 点伤害。\n丢弃一张随机手牌。",
                         False, False, _all_out_attack_play)
BACKSTAB = CardDef("Backstab", "背刺", 0, "Attack", "造成 11 点伤害。\n固有。\n消耗。",
                   True, True, _backstab_play, innate=True)
BLUR = CardDef("Blur", "残影", 1, "Skill", "获得 5 点格挡。\n你的下一回合开始时格挡不会消失。",
               False, False, _blur_play)
BOUNCING_FLASK = CardDef("Bouncing Flask", "弹跳药瓶", 2, "Skill", "随机给予敌人 3 层中毒  3 次。",
                         False, False, _bouncing_flask_play)
CALCULATED_GAMBLE = CardDef("Calculated Gamble", "计算下注", 0, "Skill", "丢弃所有手牌。\n然后抽相同数量张牌。\n消耗。",
                            False, False, _calculated_gamble_play)
CALTROPS = CardDef("Caltrops", "铁蒺藜", 1, "Power", "每当你被攻击时，对攻击者造成 3 点伤害。",
                   False, False, _caltrops_play)
CATALYST = CardDef("Catalyst", "催化剂", 1, "Skill", "将一名敌人的中毒层数翻倍。\n消耗。",
                   True, True, _catalyst_play)
CHOKE = CardDef("Choke", "勒脖", 2, "Attack", "造成 12 点伤害。\n你在这个回合内每打出一张牌，该名敌人都会失去 3 点生命。",
                True, False, _choke_play)
CONCENTRATE = CardDef("Concentrate", "全神贯注", 0, "Skill", "丢弃 3 张牌。\n获得 2 点能量。",
                      False, False, _concentrate_play)
CRIPPLING_CLOUD = CardDef("Crippling Cloud", "致残毒云", 2, "Skill", "给予所有敌人 4 层中毒和 2 层虚弱。\n消耗。",
                          False, True, _crippling_cloud_play)
DASH = CardDef("Dash", "冲刺", 2, "Attack", "获得 10 点格挡。\n造成 10 点伤害。",
               True, False, _dash_play)
DISTRACTION = CardDef("Distraction", "声东击西", 1, "Skill", "增加一张随机技能牌到你的手牌。\n这张牌在本回合耗能变为 0。\n消耗。",
                      False, True, _distraction_play, upgraded_cost=0)
def _endless_agony_on_drawn(bc: BattleContext, inst) -> None:
    # 引擎 on_drawn_effect 钩子（已接线）：抽到时复制 1 张入手（保留升级态）
    bc.cards.create_temp_card_in_hand(inst.card, inst.upgraded)


ENDLESS_AGONY = CardDef("Endless Agony", "无尽苦痛", 0, "Attack", "造成 4 点伤害。\n每当你抽到这张牌，都增加一张其复制品到你的手牌。\n消耗。",
                        True, True, _endless_agony_play, on_drawn_effect=_endless_agony_on_drawn)
ESCAPE_PLAN = CardDef("Escape Plan", "逃脱计划", 0, "Skill", "抽 1 张牌。\n如果抽到的是技能牌，获得 3 点格挡。",
                      False, False, _escape_plan_play)
def _eviscerate_cost(bc: BattleContext, inst) -> int:
    return max(0, 3 - bc.player.cards_discarded_this_turn)


EVISCERATE = CardDef("Eviscerate", "内脏切除", 3, "Attack", "你在这个回合内每丢弃一张牌，耗能就减少 1 点能量。\n造成 7 点伤害三次。",
                     True, False, _eviscerate_play, dynamic_cost=_eviscerate_cost)
EXPERTISE = CardDef("Expertise", "独门技术", 1, "Skill", "抽牌直到你的手牌有 6 张牌。",
                    False, False, _expertise_play)
FINISHER = CardDef("Finisher", "终结技", 1, "Attack", "你在这个回合内每打出过一张攻击牌，就造成一次 6 点伤害。",
                   True, False, _finisher_play)
FLECHETTES = CardDef("Flechettes", "飞镖", 1, "Attack", "手牌中每有一张技能牌，造成 4 点伤害。",
                     True, False, _flechettes_play)
FOOTWORK = CardDef("Footwork", "灵动步法", 1, "Power", "获得 2 点敏捷。",
                   False, False, _footwork_play)
HEEL_HOOK = CardDef("Heel Hook", "足跟勾", 1, "Attack", "造成 5 点伤害。\n如果敌人有虚弱状态，\n获得 1 点能量并且\n抽 1 张牌。",
                    True, False, _heel_hook_play)
INFINITE_BLADES = CardDef("Infinite Blades", "无限刀刃", 1, "Power", "在你的回合开始时，增加一张小刀到你的手牌。",
                          False, False, _infinite_blades_play, innate_when_upgraded=True)
LEG_SWEEP = CardDef("Leg Sweep", "扫腿", 2, "Skill", "给予 2 层虚弱 .\n获得 11 点格挡。",
                    True, False, _leg_sweep_play)
MASTERFUL_STAB = CardDef("Masterful Stab", "精巧刺击", 0, "Attack", "造成 12 点伤害。\n你每次受到伤害，这张牌的耗能增加 1。",
                         True, False, _masterful_stab_play, cost_delta_on_damage=1)
NOXIOUS_FUMES = CardDef("Noxious Fumes", "毒雾", 1, "Power", "在你的回合开始时，给予所有敌人 2 层中毒。",
                        False, False, _noxious_fumes_play)
PREDATOR = CardDef("Predator", "猎杀者", 2, "Attack", "造成 15 点伤害。\n在下一回合多抽 2 张牌。",
                   True, False, _predator_play)
REFLEX = CardDef("Reflex", "本能反应", 0, "Skill", "不能被打出。\n如果这张牌从你的手牌中被丢弃，抽 2 张牌。",
                 False, False, _unplayable_noop, unplayable=True, on_discard_effect=_reflex_on_discard)
RIDDLE_WITH_HOLES = CardDef("Riddle with Holes", "千穿百刺", 2, "Attack", "造成 3 点伤害 5 次。",
                           True, False, _riddle_with_holes_play)
SETUP = CardDef("Setup", "部署", 1, "Skill", "将手牌中的一张牌放到抽牌堆的顶部。\n并且在其被打出之前，其耗能变为 0。",
                False, False, _setup_play, upgraded_cost=0)
SKEWER = CardDef("Skewer", "串刺", -1, "Attack", "造成 7 点伤害X次。",
                 True, False, _skewer_play, x_cost=True)
TACTICIAN = CardDef("Tactician", "战术大师", 0, "Skill", "不能被打出。\n如果这张牌从你的手牌中被丢弃，获得 1 点能量。",
                    False, False, _unplayable_noop, unplayable=True, on_discard_effect=_tactician_on_discard)
TERROR = CardDef("Terror", "恐怖", 1, "Skill", "给予 99 层易伤。\n消耗。",
                 True, True, _terror_play, upgraded_cost=0)
WELL_LAID_PLANS = CardDef("Well-Laid Plans", "计划妥当", 1, "Power", "在你的回合结束时，保留最多 1 张牌。",
                          False, False, _well_laid_plans_play)


# ============================================================
# 稀有 19 张（Alchemize 跳过）
# ============================================================


def _thousand_cuts_play(bc: BattleContext, item: CardQueueItem) -> None:
    # wiki：你每打出一张牌，对所有敌人造成 1 伤（+：2 伤）。层数=每次伤害
    #（多张叠加）；结算在引擎 use_card（f0d724f 已接）
    bc.add_to_bot(Actions.buff_player(PlayerStatus.A_THOUSAND_CUTS, 2 if item.card.upgraded else 1))


def _adrenaline_play(bc: BattleContext, item: CardQueueItem) -> None:
    # wiki：获得 1 点能量。抽 2 张牌。消耗（+：获得 2 点能量，抽牌量不变）
    up = item.card.upgraded
    bc.add_to_bot(Actions.gain_energy(2 if up else 1))
    bc.add_to_bot(Actions.draw_cards(2))


def _after_image_play(bc: BattleContext, item: CardQueueItem) -> None:
    # wiki：你每打出一张牌，获得 1 点格挡（+：固有）。注意 wiki/C++ 语义为
    # 每张牌 1 格挡（C++ BattleContext.cpp 四处 onUseXxxCard 的 GainBlock 分支），
    # 引擎 f0d724f 按"出技能生成袖剑"接线——出入列入迁移报告
    bc.add_to_bot(Actions.buff_player(PlayerStatus.AFTER_IMAGE, 1))


def _bullet_time_play(bc: BattleContext, item: CardQueueItem) -> None:
    # wiki：本回合不能再抽牌。手牌费用本轮全部降为 0（+：费用 2）。
    # 禁抽走 NO_DRAW（回合末引擎解除）；降费在结算时置 cost_for_turn=0
    #（回合末 reset_attributes 复原）
    bc.add_to_bot(Actions.debuff_player(PlayerStatus.NO_DRAW, 1, False))

    def run(bc2: BattleContext) -> None:
        for c in bc2.cards.hand:
            c.cost_for_turn = 0

    bc.add_to_bot(Action(run))


def _burst_play(bc: BattleContext, item: CardQueueItem) -> None:
    # wiki：本回合你的下一张技能牌结算两次（+：下 2 张）。结算在引擎
    # on_use_skill_card（f0d724f 已接，递减式支持多层）
    bc.add_to_bot(Actions.buff_player(PlayerStatus.BURST, 2 if item.card.upgraded else 1))


def _corpse_explosion_play(bc: BattleContext, item: CardQueueItem) -> None:
    # wiki：施加 6 层中毒。该敌人死亡时，对所有敌人造成等同其最大 HP 的伤害
    #（+：9 层）。不消耗（wiki desc 无 Exhaust）。尸爆状态（可叠层）与
    # 死亡结算（maxHp×层）引擎已接（Monster.die）
    up = item.card.upgraded
    bc.add_to_bot(Actions.debuff_enemy(item.target, MonsterStatus.POISON, 9 if up else 6))
    bc.add_to_bot(Actions.debuff_enemy(item.target, MonsterStatus.CORPSE_EXPLOSION, 1))


def _die_die_die_play(bc: BattleContext, item: CardQueueItem) -> None:
    # wiki：对所有敌人造成 13 伤。消耗（+：17 伤）
    bc.add_to_bot(Actions.attack_all_enemy(17 if item.card.upgraded else 13))


def _doppelganger_play(bc: BattleContext, item: CardQueueItem) -> None:
    # wiki：X 费：下回合抽 X 张牌并获得 X 点能量。消耗（+：X+1）。
    # 走 next_turn_draw / next_turn_energy 槽（接线待接）
    x = max(item.energy_on_use, 0) + (1 if item.card.upgraded else 0)
    bc.add_to_bot(Action(lambda bc2: _add_next_turn_draw(bc2, x)))
    bc.add_to_bot(Action(lambda bc2: _add_next_turn_energy(bc2, x)))


def _envenom_play(bc: BattleContext, item: CardQueueItem) -> None:
    # wiki：你的攻击造成未被格挡的伤害时，施加 1 层中毒（+：费用 1）。
    # 结算已接（Monster._apply_damage 的 ENVENOM 挂点）
    bc.add_to_bot(Actions.buff_player(PlayerStatus.ENVENOM, 1))


def _glass_knife_play(bc: BattleContext, item: CardQueueItem) -> None:
    # wiki：造成 8 伤 2 次。每次打出，此牌本场伤害 -2（+：12 伤 2 次）。
    # 实例计数（misc_data）表达"本场战斗此牌"的递减——每次打出后 -2，
    # 双段共用递减后伤害
    up = item.card.upgraded
    dmg = bc.calculate_card_damage(item, item.target, (12 if up else 8) - 2 * item.card.misc_data)
    bc.add_to_bot(Actions.attack_enemy(item.target, dmg))
    bc.add_to_bot(Actions.attack_enemy(item.target, dmg))
    item.card.misc_data += 1


def _grand_finale_condition(bc: BattleContext, inst: CardInstance) -> bool:
    # wiki：只有抽牌堆为空时才能打出
    return not bc.cards.draw_pile


def _grand_finale_play(bc: BattleContext, item: CardQueueItem) -> None:
    # wiki：对所有敌人造成 50 伤（+：60 伤）。0 费
    bc.add_to_bot(Actions.attack_all_enemy(60 if item.card.upgraded else 50))


def _malaise_play(bc: BattleContext, item: CardQueueItem) -> None:
    # wiki：X 费：敌人失去 X 点力量，施加 X 层虚弱。消耗（+：X+1）。
    # 力量流失走 DebuffEnemy 负数（同 Disarm：吃 ARTIFACT 抵消，负数直达力量）
    n = max(item.energy_on_use, 0) + (1 if item.card.upgraded else 0)
    if n > 0:
        bc.add_to_bot(Actions.debuff_enemy(item.target, MonsterStatus.STRENGTH, -n))
        bc.add_to_bot(Actions.debuff_enemy(item.target, MonsterStatus.WEAK, n))


def _nightmare_play(bc: BattleContext, item: CardQueueItem) -> None:
    # wiki：选择一张牌。下回合将 3 张它的副本加入手牌。消耗（+：费用 2，
    # 副本数不变）。副本带升级态；经 special["next_turn_cards"] 槽——引擎
    # after_monster_turns（f0d724f 已接）回合开始生成保留副本
    def run(bc2: BattleContext) -> None:
        cands = list(bc2.cards.hand)

        def on_choose(bc3: BattleContext, chosen: list) -> None:
            for inst in chosen:
                bc3.player.special.setdefault("next_turn_cards", []).append(
                    (inst.card, inst.upgraded, 3))

        bc2.open_card_select(cands, on_choose, can_pick_zero=True,
                             prompt="梦魇：选择 1 张手牌，下回合加入 3 张副本")

    bc.add_to_bot(Action(run))


def _phantasmal_killer_play(bc: BattleContext, item: CardQueueItem) -> None:
    # wiki：下回合你的攻击伤害翻倍（+：费用 0）。引擎 f0d724f 语义：回合
    # 开始落 DOUBLE_DAMAGE、首攻击后移除；wiki/C++（全回合乘 2）的出入
    # 列入迁移报告
    bc.add_to_bot(Actions.buff_player(PlayerStatus.PHANTASMAL_KILLER, 1))


def _storm_of_steel_play(bc: BattleContext, item: CardQueueItem) -> None:
    # wiki：弃掉所有手牌。每弃 1 张，加 1 张袖剑到手牌（+：加 Shiv+）。
    # 张数结算时锁定；弃牌走 manual_discard（触发袖剑师的弃牌遗物/反射/谋士）
    up = item.card.upgraded

    def run(bc2: BattleContext) -> None:
        n = len(bc2.cards.hand)
        for inst in list(bc2.cards.hand):
            bc2.manual_discard(inst)
        for _ in range(n):
            inst = bc2.cards.instantiate(SHIV)
            inst.upgraded = up
            _add_temp_to_hand(bc2, inst)

    bc.add_to_bot(Action(run))


def _tools_of_the_trade_play(bc: BattleContext, item: CardQueueItem) -> None:
    # wiki：回合开始时抽 1 张牌并弃 1 张牌（+：费用 0）。C++ 只实现抽牌
    # （Player.cpp TOOLS_OF_THE_TRADE 分支的弃牌为注释掉的 todo），wiki
    # 口径含弃牌——以 special["tott_draw"] 槽接线（抽 1 + 弃 1）
    bc.player.special["tott_draw"] = 1


def _unload_play(bc: BattleContext, item: CardQueueItem) -> None:
    # wiki：造成 14 伤。弃掉手中所有非攻击牌（+：18 伤）。弃牌走
    # manual_discard（触发弃牌管线钩子）
    dmg = bc.calculate_card_damage(item, item.target, 18 if item.card.upgraded else 14)
    bc.add_to_bot(Actions.attack_enemy(item.target, dmg))

    def run(bc2: BattleContext) -> None:
        for inst in list(bc2.cards.hand):
            if inst.card.ctype != "Attack":
                bc2.manual_discard(inst)

    bc.add_to_bot(Action(run))


def _wraith_form_play(bc: BattleContext, item: CardQueueItem) -> None:
    # wiki：获得 2 层无实体。回合结束时失去 1 点敏捷（+：3 层）。每回合
    # 敏捷流失走 special["wraith_form_dex"] 槽（对齐 C++ PS::WRAITH_FORM
    # 状态的回合末 DecrementStatus<DEXTERITY>，接线待接）；可叠层
    bc.add_to_bot(Actions.buff_player(PlayerStatus.INTANGIBLE, 3 if item.card.upgraded else 2))
    bc.add_to_bot(Action(lambda bc2: bc2.player.special.update(
        wraith_form_dex=bc2.player.special.get("wraith_form_dex", 0) + 1)))


A_THOUSAND_CUTS = CardDef("A Thousand Cuts", "凌迟", 2, "Power", "你每打出一张牌，就对所有敌人造成 1 点伤害。",
                          False, False, _thousand_cuts_play)
ADRENALINE = CardDef("Adrenaline", "肾上腺素", 0, "Skill", "获得 1 点能量。\n抽 2 张牌。\n消耗。",
                     False, True, _adrenaline_play)
AFTER_IMAGE = CardDef("After Image", "余像", 1, "Power", "你每打出一张牌，都获得 1 点格挡。",
                      False, False, _after_image_play, innate_when_upgraded=True)
BULLET_TIME = CardDef("Bullet Time", "子弹时间", 3, "Skill", "你在本回合内不能再抽牌。你手牌中的所有牌在本回合的耗能变为 0 点。",
                      False, False, _bullet_time_play, upgraded_cost=2)
BURST = CardDef("Burst", "爆发", 1, "Skill", "在这个回合，你打出的下一张技能牌会打出两次。",
                False, False, _burst_play)
CORPSE_EXPLOSION = CardDef("Corpse Explosion", "尸爆术", 2, "Skill", "给予 6 层中毒。\n当这名敌人死亡时，对所有敌人造成等于其最大生命值的伤害。",
                           True, False, _corpse_explosion_play)
DIE_DIE_DIE = CardDef("Die Die Die", "死吧死吧死吧", 1, "Attack", "对所有敌人造成 13 点伤害。\n消耗。",
                      False, True, _die_die_die_play)
DOPPELGANGER = CardDef("Doppelganger", "双重存在", -1, "Skill", "下一回合，抽X张牌，获得X 1 点能量。\n消耗。",
                       False, True, _doppelganger_play, x_cost=True)
ENVENOM = CardDef("Envenom", "涂毒", 2, "Power", "每有一次攻击造成未被格挡的伤害，就给予 1 层中毒。",
                  False, False, _envenom_play, upgraded_cost=1)
GLASS_KNIFE = CardDef("Glass Knife", "玻璃刀刃", 1, "Attack", "造成 8 点伤害两次。\n这张牌每被打出一次，在本场战斗中其基础伤害减少 2。",
                      True, False, _glass_knife_play)
GRAND_FINALE = CardDef("Grand Finale", "华丽收场", 0, "Attack", "只有当抽牌堆中没有牌时才能打出。\n对所有敌人造成 50 点伤害。",
                       False, False, _grand_finale_play, play_condition=_grand_finale_condition)
MALAISE = CardDef("Malaise", "萎靡", -1, "Skill", "敌人失去X点力量，给予X层虚弱。\n消耗。",
                  True, True, _malaise_play, x_cost=True)
NIGHTMARE = CardDef("Nightmare", "夜魇", 3, "Skill", "选择一张牌，\n在下一回合，将 3 份这张牌的复制品放入你的手牌中。消耗。",
                   False, True, _nightmare_play, upgraded_cost=2)
PHANTASMAL_KILLER = CardDef("Phantasmal Killer", "幻影杀手", 1, "Skill", "在你的下个回合，你所有的攻击伤害翻倍。",
                           False, False, _phantasmal_killer_play, upgraded_cost=0)
STORM_OF_STEEL = CardDef("Storm of Steel", "钢铁风暴", 1, "Skill", "丢弃所有手牌。\n每丢弃一张牌，在你的手牌中增加一张小刀。",
                        False, False, _storm_of_steel_play)
TOOLS_OF_THE_TRADE = CardDef("Tools of the Trade", "必备工具", 1, "Power", "在你的回合开始时，抽 1 张牌，丢弃 1 张牌。",
                             False, False, _tools_of_the_trade_play, upgraded_cost=0)
UNLOAD = CardDef("Unload", "乾坤一掷", 1, "Attack", "造成 14 点伤害。\n丢弃所有非攻击牌。",
                 True, False, _unload_play)
WRAITH_FORM = CardDef("Wraith Form", "幽魂形态", 3, "Power", "获得 2 层无实体。\n在每回合结束时失去 1 点敏捷。",
                     False, False, _wraith_form_play)


def _venomology_play(bc: BattleContext, item: CardQueueItem) -> None:
    # 2026-10-07 补齐（Alchemize.java，ID=Venomology，Silent 稀有）：
    # ObtainPotionAction(returnRandomPotion(true))——全池 42 均匀抽，空槽放置
    def run(bc2: BattleContext) -> None:
        from sts.content.potions import random_potion

        bc2.obtain_potion(random_potion(bc2))

    bc.add_to_bot(Action(run))


VENOLOGY = CardDef("Alchemize", "炼制药水", 1, "Skill",
                   "获得一瓶随机药水。\n消耗。",
                   False, True, _venomology_play, upgraded_cost=0)


__all__ = [
    # 基础
    "DEFEND_S", "NEUTRALIZE", "SHIV", "STRIKE_S", "SURVIVOR",
    # 普通
    "ACROBATICS", "BACKFLIP", "BANE", "BLADE_DANCE", "CLOAK_AND_DAGGER",
    "DAGGER_SPRAY", "DAGGER_THROW", "DEADLY_POISON", "DEFLECT",
    "DODGE_AND_ROLL", "FLYING_KNEE", "OUTMANEUVER", "PIERCING_WAIL",
    "POISONED_STAB", "PREPARED", "QUICK_SLASH", "SLICE", "SNEAKY_STRIKE",
    "SUCKER_PUNCH",
    # 非普通
    "ACCURACY", "ALL_OUT_ATTACK", "BACKSTAB", "BLUR", "BOUNCING_FLASK",
    "CALCULATED_GAMBLE", "CALTROPS", "CATALYST", "CHOKE", "CONCENTRATE",
    "CRIPPLING_CLOUD", "DASH", "DISTRACTION", "ENDLESS_AGONY", "ESCAPE_PLAN",
    "EVISCERATE", "EXPERTISE", "FINISHER", "FLECHETTES", "FOOTWORK",
    "HEEL_HOOK", "INFINITE_BLADES", "LEG_SWEEP", "MASTERFUL_STAB",
    "NOXIOUS_FUMES", "PREDATOR", "REFLEX", "RIDDLE_WITH_HOLES", "SETUP",
    "SKEWER", "TACTICIAN", "TERROR", "WELL_LAID_PLANS",
    # 稀有
    "A_THOUSAND_CUTS", "ADRENALINE", "AFTER_IMAGE", "BULLET_TIME", "BURST",
    "CORPSE_EXPLOSION", "DIE_DIE_DIE", "DOPPELGANGER", "ENVENOM",
    "GLASS_KNIFE", "GRAND_FINALE", "MALAISE", "NIGHTMARE",
    "PHANTASMAL_KILLER", "STORM_OF_STEEL", "TOOLS_OF_THE_TRADE", "UNLOAD",
    "VENOLOGY", "WRAITH_FORM",
]

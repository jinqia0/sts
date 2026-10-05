"""铁甲战士卡牌定义（对齐 lightspeed useAttackCard/useSkillCard 的逐卡 switch）。

每张卡 = 不可变模板（CardDef）+ play()（把效果分解为原子动作入队）。
数值来源 slaythespire.wiki.gg（A0 基准）；升级版数值用 self.upgraded 分支。

拆分（批次 4，2026-10-06）：诅咒卡在 curses_cards.py、全部无色卡在
colorless_cards.py（本文件 Hand of Greed 除外），均经本文件尾部 __getattr__
惰性 re-export，既有 `from sts.content.cards import X` 路径不变。状态卡
（WOUND/BURN/DAZED/SLIMED/VOID）留驻本文件。
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

from sts.combat.actions import Actions
from sts.combat.card_manager import MAX_HAND_SIZE
from sts.combat.queue import Action, CardQueueItem
from sts.combat.types import MonsterStatus, Outcome, PlayerStatus

if TYPE_CHECKING:
    from sts.combat.battle import BattleContext
    from sts.combat.card_manager import CardInstance
    from sts.combat.queue import CardQueueItem


@dataclass(frozen=True)
class CardDef:
    name: str
    zh: str
    cost: int
    ctype: str  # "Attack" | "Skill" | "Power" | "Status" | "Curse"
    text: str
    needs_target: bool
    exhausts: bool
    play: "type(None) | callable"  # (bc, item) -> None，入队原子动作
    unplayable: bool = False  # 状态/诅咒卡不可打出（Wound 等）
    upgraded_cost: int | None = None  # 升级版改费（Body Slam+：1→0），None 表示不变
    # ---- 全量内容迁移新增字段（2026-10-05 批次 0）----
    x_cost: bool = False  # X 费（Whirlwind）：打出消耗所有能量
    ethereal: bool = False  # 虚无（Carnage/Clumsy/Dazed）：回合末在手则消耗
    innate: bool = False  # 固有（Brutality+/Dramatic Entrance）：战斗开始必在手
    no_trigger_effect: "callable | None" = None  # 回合末自动结算（Burn/Regret 等），(bc, item) -> None
    no_trigger_exhausts: bool = False  # 自动结算后进消耗堆而非弃牌堆（Pride）
    on_play_other_lose_hp: int = 0  # 打出其他牌时每张失去的 HP（诅咒 Pain）
    lose_energy_when_drawn: int = 0  # 被抽到时失去的能量（状态卡 Void）
    play_condition: "callable | None" = None  # 打出条件（Clash）：(bc, inst) -> bool，False 则 play_card 拒绝
    cost_delta_on_damage: int = 0  # 玩家每次失去 HP 时该实例的永久费用增减（Blood for Blood：-1）
    multiple_upgrades: bool = False  # 可无限升级（Searing Blow：misc_data 计升级次数）
    on_exhaust_effect: "callable | None" = None  # 被消耗时触发（Sentinel：+2 能量），引擎 on_card_exhausted 已接线
    # ---- Retain 关键词（批次 A：Watcher/Silent/Defect 共用）----
    self_retain: bool = False  # 自带保留：回合末不弃（Crescendo/Protect 等）
    retain_when_upgraded: bool = False  # 仅升级版保留（Worship/Blasphemy）
    on_discard_effect: "callable | None" = None  # 被弃置时触发（Tactician/Reflex），引擎 on_manual_discard 已接线
    on_drawn_effect: "callable | None" = None  # 被抽到时触发（Endless Agony：复制 1 张入手），引擎 on_card_drawn 已接线
    dynamic_cost: "callable | None" = None  # 动态费用回调 (bc, inst) -> int（Eviscerate：3-本回合弃牌数）
    # ---- 中等档迁移新增（批次 2）----
    innate_when_upgraded: bool = False  # 仅升级版固有（Brutality+；引擎 move_innate_to_top 需接线读此位，见批次 2 报告）
    on_exhaust_effect: "callable | None" = None  # 被消耗时触发 (bc, inst) -> None（Sentinel +能量；引擎 on_card_exhausted 已接线读取，内容层 _exhaust_from_hand 的显式调用以效果侧守卫防双重）
    # ---- 无色卡批次新增（批次 4，2026-10-06）----
    colorless: bool = False  # 无色卡标记（生成池筛选：Jack of All Trades/Transmutation/Magnetism 的 CombatColorlessCardPool 对应物）


def _strike_play(bc: BattleContext, item: CardQueueItem) -> None:
    dmg = bc.calculate_card_damage(item, item.target, 6 if not item.card.upgraded else 9)
    bc.add_to_bot(Actions.attack_enemy(item.target, dmg))


def _defend_play(bc: BattleContext, item: CardQueueItem) -> None:
    # Defend+ 为 8 格挡（wiki；批次 C 遗留修正——原恒 5 不读升级位）
    bc.add_to_bot(Actions.gain_block(bc.calculate_card_block(8 if item.card.upgraded else 5)))


def _bash_play(bc: BattleContext, item: CardQueueItem) -> None:
    up = item.card.upgraded
    dmg = bc.calculate_card_damage(item, item.target, 10 if up else 8)
    bc.add_to_bot(Actions.attack_enemy(item.target, dmg))
    # 玩家施加的易伤：is_source_monster=False，当轮回合末即递减
    bc.add_to_bot(Actions.debuff_enemy(item.target, MonsterStatus.VULNERABLE, 3 if up else 2, False))


def _cleave_play(bc: BattleContext, item: CardQueueItem) -> None:
    up = item.card.upgraded
    # attack_all_enemy 内部逐怪走完整伤害管线（含力量/虚弱/易伤）
    bc.add_to_bot(Actions.attack_all_enemy(11 if up else 8))


def _twin_strike_play(bc: BattleContext, item: CardQueueItem) -> None:
    up = item.card.upgraded
    # 伤害出队前算好一次（对齐 C++：两段共用同一 dmg，第二段不重新计算）
    dmg = bc.calculate_card_damage(item, item.target, 7 if up else 5)
    bc.add_to_bot(Actions.attack_enemy(item.target, dmg))
    bc.add_to_bot(Actions.attack_enemy(item.target, dmg))


def _iron_wave_play(bc: BattleContext, item: CardQueueItem) -> None:
    up = item.card.upgraded
    # C++ 有 calculateCardBlock 嵌套两次的笔误，本体为单次：5 格挡 + 5 伤
    bc.add_to_bot(Actions.gain_block(bc.calculate_card_block(7 if up else 5)))
    dmg = bc.calculate_card_damage(item, item.target, 7 if up else 5)
    bc.add_to_bot(Actions.attack_enemy(item.target, dmg))


def _pommel_strike_play(bc: BattleContext, item: CardQueueItem) -> None:
    up = item.card.upgraded
    dmg = bc.calculate_card_damage(item, item.target, 10 if up else 9)
    bc.add_to_bot(Actions.attack_enemy(item.target, dmg))
    bc.add_to_bot(Actions.draw_cards(2 if up else 1))


def _shrug_it_off_play(bc: BattleContext, item: CardQueueItem) -> None:
    up = item.card.upgraded
    bc.add_to_bot(Actions.gain_block(bc.calculate_card_block(11 if up else 8)))
    bc.add_to_bot(Actions.draw_cards(1))


def _clothesline_play(bc: BattleContext, item: CardQueueItem) -> None:
    up = item.card.upgraded
    dmg = bc.calculate_card_damage(item, item.target, 14 if up else 12)
    bc.add_to_bot(Actions.attack_enemy(item.target, dmg))
    bc.add_to_bot(Actions.debuff_enemy(item.target, MonsterStatus.WEAK, 3 if up else 2, False))


def _thunderclap_play(bc: BattleContext, item: CardQueueItem) -> None:
    up = item.card.upgraded
    # 全体 4 伤（升级 7）+ 全体 1 层易伤（升级不变，仅伤害提升）
    bc.add_to_bot(Actions.attack_all_enemy(7 if up else 4))
    bc.add_to_bot(Actions.debuff_all_enemy(MonsterStatus.VULNERABLE, 1, False))


def _flex_play(bc: BattleContext, item: CardQueueItem) -> None:
    up = item.card.upgraded
    n = 4 if up else 2
    # 临时力量：+N 力量 + N 层 LOSE_STRENGTH，回合末在
    # Player.apply_end_of_turn_powers 扣回（对齐 C++ 的 UNIQUE 状态机制）
    bc.add_to_bot(Actions.buff_player(PlayerStatus.STRENGTH, n))
    bc.add_to_bot(Actions.debuff_player(PlayerStatus.LOSE_STRENGTH, n, False))


def _body_slam_play(bc: BattleContext, item: CardQueueItem) -> None:
    # 伤害 = 出牌结算时的当前格挡（仍走伤害管线：吃力量/虚弱/易伤）
    dmg = bc.calculate_card_damage(item, item.target, bc.player.block)
    bc.add_to_bot(Actions.attack_enemy(item.target, dmg))


def _inflame_play(bc: BattleContext, item: CardQueueItem) -> None:
    bc.add_to_bot(Actions.buff_player(PlayerStatus.STRENGTH, 3 if item.card.upgraded else 2))


def _metallicize_play(bc: BattleContext, item: CardQueueItem) -> None:
    bc.add_to_bot(Actions.buff_player(PlayerStatus.METALLICIZE, 4 if item.card.upgraded else 3))


def _battle_trance_play(bc: BattleContext, item: CardQueueItem) -> None:
    bc.add_to_bot(Actions.draw_cards(4 if item.card.upgraded else 3))
    # 本回合不能再抽牌：回合末由 apply_end_of_turn_powers 解除
    bc.add_to_bot(Actions.debuff_player(PlayerStatus.NO_DRAW, 1, False))


def _anger_play(bc: BattleContext, item: CardQueueItem) -> None:
    up = item.card.upgraded
    dmg = bc.calculate_card_damage(item, item.target, 8 if up else 6)
    bc.add_to_bot(Actions.attack_enemy(item.target, dmg))
    # 一张副本（保留升级状态）进弃牌堆
    bc.add_to_bot(Actions.make_temp_card_in_discard(ANGER, up))


def _wild_strike_play(bc: BattleContext, item: CardQueueItem) -> None:
    up = item.card.upgraded
    dmg = bc.calculate_card_damage(item, item.target, 17 if up else 12)
    bc.add_to_bot(Actions.attack_enemy(item.target, dmg))
    # 1 张伤口洗入抽牌堆（随机位置）
    bc.add_to_bot(Actions.make_temp_card_in_draw_pile(WOUND, False, shuffle_into=True))


def _unplayable_play(bc: BattleContext, item: CardQueueItem) -> None:
    # 状态/诅咒卡被强制入队结算时无效果——对齐 C++ useCard 的 STATUS/CURSE
    # 分支（不进任何 useXxxCard switch；Havoc/Mayhem 打出抽牌堆顶会走到
    # 此路径，随后按 exhaust_on_use 正常落堆）。正常出牌路径仍被 play_card
    # 的 unplayable 位拦截，不会进入结算。
    pass


STRIKE = CardDef("Strike", "打击", 1, "Attack", "造成 6 点伤害。", True, False, _strike_play)
DEFEND = CardDef("Defend", "防御", 1, "Skill", "获得 5 点格挡。", False, False, _defend_play)
BASH = CardDef("Bash", "痛击", 2, "Attack", "造成 8 点伤害。施加 2 层易伤。", True, False, _bash_play)

# ---- 铁甲战士 Act 1 常见卡（固定初始牌组训练的可选卡池）----

CLEAVE = CardDef("Cleave", "顺劈斩", 1, "Attack", "对所有敌人造成 8 点伤害。", False, False, _cleave_play)
TWIN_STRIKE = CardDef("Twin Strike", "双斩", 1, "Attack", "造成 2 次 5 点伤害。", True, False, _twin_strike_play)
IRON_WAVE = CardDef("Iron Wave", "铁波", 1, "Attack", "获得 5 点格挡。造成 5 点伤害。", True, False, _iron_wave_play)
POMMEL_STRIKE = CardDef("Pommel Strike", "剑柄打击", 1, "Attack", "造成 9 点伤害。抽 1 张牌。", True, False, _pommel_strike_play)
SHRUG_IT_OFF = CardDef("Shrug It Off", "耸肩", 1, "Skill", "获得 8 点格挡。抽 1 张牌。", False, False, _shrug_it_off_play)
CLOTHESLINE = CardDef("Clothesline", "锁喉", 2, "Attack", "造成 12 点伤害。施加 2 层虚弱。", True, False, _clothesline_play)
THUNDERCLAP = CardDef("Thunderclap", "雷霆骤雨", 1, "Attack", "对所有敌人造成 4 点伤害。施加 1 层易伤。", False, False, _thunderclap_play)
FLEX = CardDef("Flex", "展示肌肉", 0, "Skill", "获得 2 点力量。回合末失去。", False, False, _flex_play)
BODY_SLAM = CardDef(
    "Body Slam", "猛击", 1, "Attack", "造成等同于当前格挡的伤害。", True, False, _body_slam_play,
    upgraded_cost=0,  # 升级版仅改费 1→0（伤害不变）
)
INFLAME = CardDef("Inflame", "燃烧", 1, "Power", "获得 2 点力量。", False, False, _inflame_play)
METALLICIZE = CardDef("Metallicize", "金属化", 1, "Power", "每回合末获得 3 点格挡。", False, False, _metallicize_play)
BATTLE_TRANCE = CardDef("Battle Trance", "战斗恍惚", 0, "Skill", "抽 3 张牌。本回合不能再抽牌。", False, False, _battle_trance_play)
ANGER = CardDef("Anger", "怒火", 0, "Attack", "造成 6 点伤害。一张副本进入弃牌堆。", True, False, _anger_play)
WILD_STRIKE = CardDef("Wild Strike", "狂野打击", 1, "Attack", "造成 12 点伤害。1 张伤口洗入抽牌堆。", True, False, _wild_strike_play)
WOUND = CardDef("Wound", "伤口", 0, "Status", "不可打出。回合结束时弃置。", False, False, _unplayable_play, unplayable=True)


def starting_deck() -> list[CardDef]:
    """铁甲战士初始牌组：5 打击 / 4 防御 / 1 痛击。"""
    return [STRIKE] * 5 + [DEFEND] * 4 + [BASH]


# ---- 怪物施加的状态卡（Acid Slime M/L 的 SLIMED、Sentry 的 DAZED、Hexaghost 的 BURN）----


def _slimed_play(bc: BattleContext, item: CardQueueItem) -> None:
    pass  # 打出仅消耗自身（唯一可打出的状态卡，对齐 lightspeed useNoTriggerCard 之外的正常路径）


def _burn_effect(bc: BattleContext, item: CardQueueItem) -> None:
    up = item.card is not None and item.card.upgraded
    # 回合末结算标记：Regret 重建 C++ regretCardCount（入队时完整手牌数）
    # 时需识别本回合末已离手的 no-trigger 卡（curses_cards.py 详述）。
    # 延迟导入避免 cards→curses 导入期循环。
    from sts.content.curses_cards import mark_no_trigger_processed
    mark_no_trigger_processed(bc, item.card)
    bc.add_to_bot(Actions.damage_player(4 if up else 2, self_inflicted=True))


SLIMED = CardDef("Slimed", "黏液", 1, "Status", "消耗。（被打出时无其他效果）", False, True, _slimed_play)
DAZED = CardDef("Dazed", "眩晕", 0, "Status", "不可打出。虚无。", False, False, _unplayable_play,
                unplayable=True, ethereal=True)
BURN = CardDef("Burn", "灼伤", 0, "Status", "回合结束时受到 2 点伤害。", False, False, _unplayable_play,
               unplayable=True, no_trigger_effect=_burn_effect)
VOID = CardDef("Void", "虚空", 0, "Status", "不可打出。虚无。被抽到时失去 1 点能量。", False, False, _unplayable_play,
               unplayable=True, ethereal=True, lose_energy_when_drawn=1)


# ---- 简单档迁移（批次 1，2026-10-05）：Actions 工厂与现有状态即可覆盖的 20 张 ----
# 数值以 lightspeed C++（BattleContext.cpp useAttackCard L958 起 / useSkillCard
# L1203 起 / Actions.cpp 复合动作）为准对译，wiki 交叉校验；与 wiki 不一致处
# 在各卡注释中记录。


def _clash_condition(bc: BattleContext, inst: CardInstance) -> bool:
    """对齐 canUseClash（CardInstance.cpp L260）：手牌（含自身）全部为攻击牌。"""
    return all(c.card.ctype == "Attack" for c in bc.cards.hand)


def _clash_play(bc: BattleContext, item: CardQueueItem) -> None:
    dmg = bc.calculate_card_damage(item, item.target, 18 if item.card.upgraded else 14)
    bc.add_to_bot(Actions.attack_enemy(item.target, dmg))


def _heavy_blade_play(bc: BattleContext, item: CardQueueItem) -> None:
    up = item.card.upgraded
    # 对齐 C++ HEAVY_BLADE 分支：base = 14 + (up?4:2)×力量，再走
    # calculateCardDamage（管线内另加 1×力量）→ 力量总倍率 3/5。
    # 升级不改基准伤害（14），与 wiki 一致。
    base = 14 + (4 if up else 2) * bc.player.statuses.get(PlayerStatus.STRENGTH)
    dmg = bc.calculate_card_damage(item, item.target, base)
    bc.add_to_bot(Actions.attack_enemy(item.target, dmg))


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


def _perfected_strike_play(bc: BattleContext, item: CardQueueItem) -> None:
    up = item.card.upgraded
    # C++ 在 useAttackCard 计算时打出牌仍在手（"hack because we calculate
    # strikeCount while non purge cards are still in hand"）→ 计数含自身；
    # 重放体（purge_on_use，如 Double Tap 复制）不在手，不计。
    count = _count_strikes_in_combat(bc) + (0 if item.purge_on_use else 1)
    base = 6 + count * (3 if up else 2)
    dmg = bc.calculate_card_damage(item, item.target, base)
    bc.add_to_bot(Actions.attack_enemy(item.target, dmg))


def _uppercut_play(bc: BattleContext, item: CardQueueItem) -> None:
    up = item.card.upgraded
    # C++ 升级版伤害仍为 13（wiki 为 17，以 C++ 为准），升级仅提升虚弱/易伤
    dmg = bc.calculate_card_damage(item, item.target, 13)
    bc.add_to_bot(Actions.attack_enemy(item.target, dmg))
    n = 2 if up else 1
    bc.add_to_bot(Actions.debuff_enemy(item.target, MonsterStatus.WEAK, n, False))
    bc.add_to_bot(Actions.debuff_enemy(item.target, MonsterStatus.VULNERABLE, n, False))


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


def _hemokinesis_play(bc: BattleContext, item: CardQueueItem) -> None:
    up = item.card.upgraded
    # 对齐 C++：先失 2 HP（自伤，触发 RUPTURE）后攻击；伤害在出牌时算好
    #（失去 HP 不会反过来影响本卡伤害）
    bc.add_to_bot(Actions.player_lose_hp(2, self_inflicted=True))
    dmg = bc.calculate_card_damage(item, item.target, 20 if up else 15)
    bc.add_to_bot(Actions.attack_enemy(item.target, dmg))


def _pummel_play(bc: BattleContext, item: CardQueueItem) -> None:
    up = item.card.upgraded
    # 对齐 C++ PUMMEL：升级加第 5 段而非加伤（wiki 同；伤害恒 2，
    # 多段共用同一 dmg）
    dmg = bc.calculate_card_damage(item, item.target, 2)
    for _ in range(5 if up else 4):
        bc.add_to_bot(Actions.attack_enemy(item.target, dmg))


def _intimidate_play(bc: BattleContext, item: CardQueueItem) -> None:
    bc.add_to_bot(Actions.debuff_all_enemy(MonsterStatus.WEAK, 2 if item.card.upgraded else 1, False))


def _shockwave_play(bc: BattleContext, item: CardQueueItem) -> None:
    n = 5 if item.card.upgraded else 3
    bc.add_to_bot(Actions.debuff_all_enemy(MonsterStatus.WEAK, n, False))
    bc.add_to_bot(Actions.debuff_all_enemy(MonsterStatus.VULNERABLE, n, False))


def _disarm_play(bc: BattleContext, item: CardQueueItem) -> None:
    # 对齐 C++ DISARM：恒 -2 力量（wiki 升级版 -3，以 C++ 为准）；
    # DebuffEnemy 语义：吃 ARTIFACT 抵消，负数直达力量（可为负）
    bc.add_to_bot(Actions.debuff_enemy(item.target, MonsterStatus.STRENGTH, -2, False))


def _seeing_red_play(bc: BattleContext, item: CardQueueItem) -> None:
    # 对齐 C++：+2 能量、升级改费 1→0；lightspeed 的 doesCardExhaust 未收录
    # SEEING_RED → 不消耗（wiki 为消耗，以 C++ 为准）
    bc.add_to_bot(Actions.gain_energy(2))


def _bloodletting_play(bc: BattleContext, item: CardQueueItem) -> None:
    # 对齐 C++ BLOODLETTING：失去 3 HP（wiki 为 1，以 C++ 为准；自伤，
    # 触发 RUPTURE），+2/3 能量
    bc.add_to_bot(Actions.player_lose_hp(3, self_inflicted=True))
    bc.add_to_bot(Actions.gain_energy(3 if item.card.upgraded else 2))


def _spot_weakness_play(bc: BattleContext, item: CardQueueItem) -> None:
    n = 4 if item.card.upgraded else 3
    t = item.target

    def run(bc: BattleContext) -> None:
        # 对齐 SpotWeaknessAction：执行时读目标意图，为攻击时 +力量
        m = bc.monsters.monsters[t]
        if not m.is_dead_or_escaped() and m.current_move.kind == "attack":
            bc.player.statuses.add(PlayerStatus.STRENGTH, n)

    bc.add_to_bot(Action(run))


def _entrench_play(bc: BattleContext, item: CardQueueItem) -> None:
    def run(bc: BattleContext) -> None:
        # 对齐 EntrenchAction：执行时格挡翻倍（走 gain_block：NO_BLOCK 拦截
        # + Juggernaut 触发）
        bc.player.gain_block(bc, bc.player.block)

    bc.add_to_bot(Action(run))


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


def _bludgeon_play(bc: BattleContext, item: CardQueueItem) -> None:
    dmg = bc.calculate_card_damage(item, item.target, 42 if item.card.upgraded else 32)
    bc.add_to_bot(Actions.attack_enemy(item.target, dmg))


def _offering_play(bc: BattleContext, item: CardQueueItem) -> None:
    up = item.card.upgraded
    # 对齐 C++ OFFERING：失 6 HP（自伤）→ +2 能量 → 抽 3/5
    bc.add_to_bot(Actions.player_lose_hp(6, self_inflicted=True))
    bc.add_to_bot(Actions.gain_energy(2))
    bc.add_to_bot(Actions.draw_cards(5 if up else 3))


def _impervious_play(bc: BattleContext, item: CardQueueItem) -> None:
    bc.add_to_bot(Actions.gain_block(bc.calculate_card_block(40 if item.card.upgraded else 30)))


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


def _sword_boomerang_play(bc: BattleContext, item: CardQueueItem) -> None:
    # 对齐 C++：3（升级 4）段，每段独立随机目标 + 独立走攻击管线
    bc.add_to_bot(Actions.attack_random_enemy(3, 4 if item.card.upgraded else 3))


CLASH = CardDef("Clash", "冲突", 0, "Attack", "只有在手牌全是攻击牌时才能打出。造成 14 点伤害。",
                True, False, _clash_play, play_condition=_clash_condition)
HEAVY_BLADE = CardDef("Heavy Blade", "重刃", 2, "Attack", "造成 14 点伤害。力量额外计入 2 次。", True, False, _heavy_blade_play)
PERFECTED_STRIKE = CardDef("Perfected Strike", "完美打击", 2, "Attack", "造成 6 点伤害，每有一张“打击”牌额外 +2。", True, False, _perfected_strike_play)
UPPERCUT = CardDef("Uppercut", "上勾拳", 2, "Attack", "造成 13 点伤害。施加 1 层虚弱和 1 层易伤。", True, False, _uppercut_play)
DROPKICK = CardDef("Dropkick", "飞踢", 1, "Attack", "造成 5 点伤害。若目标有易伤，获得 1 点能量并抽 1 张牌。", True, False, _dropkick_play)
HEMOKINESIS = CardDef("Hemokinesis", "血液激发", 1, "Attack", "失去 2 点 HP。造成 15 点伤害。", True, False, _hemokinesis_play)
PUMMEL = CardDef("Pummel", "连续痛击", 1, "Attack", "造成 2 点伤害 4 次。消耗。", True, True, _pummel_play)
INTIMIDATE = CardDef("Intimidate", "威吓", 0, "Skill", "所有敌人获得 1 层虚弱。消耗。", False, True, _intimidate_play)
SHOCKWAVE = CardDef("Shockwave", "震波", 2, "Skill", "所有敌人获得 3 层虚弱和 3 层易伤。消耗。", False, True, _shockwave_play)
DISARM = CardDef("Disarm", "缴械", 1, "Skill", "敌人失去 2 点力量。消耗。", True, True, _disarm_play)
SEEING_RED = CardDef("Seeing Red", "怒目而视", 1, "Skill", "获得 2 点能量。", False, False, _seeing_red_play,
                     upgraded_cost=0)
BLOODLETTING = CardDef("Bloodletting", "放血", 0, "Skill", "失去 3 点 HP。获得 2 点能量。", False, False, _bloodletting_play)
SPOT_WEAKNESS = CardDef("Spot Weakness", "洞察弱点", 1, "Skill", "若敌人意图为攻击，获得 3 点力量。", True, False, _spot_weakness_play)
ENTRENCH = CardDef("Entrench", "堑壕", 2, "Skill", "将当前格挡翻倍。", False, False, _entrench_play,
                   upgraded_cost=1)
LIMIT_BREAK = CardDef("Limit Break", "极限突破", 1, "Skill", "力量翻倍。消耗。（升级后不消耗）", False, False, _limit_break_play)
BLUDGEON = CardDef("Bludgeon", "重击", 3, "Attack", "造成 32 点伤害。", True, False, _bludgeon_play)
OFFERING = CardDef("Offering", "献祭", 0, "Skill", "失去 6 点 HP。获得 2 点能量。抽 3 张牌。消耗。", False, True, _offering_play)
IMPERVIOUS = CardDef("Impervious", "金刚不坏", 2, "Skill", "获得 30 点格挡。消耗。", False, True, _impervious_play)
REAPER = CardDef("Reaper", "收割", 2, "Attack", "对所有敌人造成 4 点伤害。回复等同于未被格挡吸收的伤害的 HP。消耗。", False, True, _reaper_play)
SWORD_BOOMERANG = CardDef("Sword Boomerang", "回旋剑", 1, "Attack", "对随机敌人造成 3 点伤害 3 次。", False, False, _sword_boomerang_play)


# ---- 中等档迁移（批次 2，2026-10-05）：Power 状态族 / 消耗族 / 虚无族 /
# 实例计数族 / 生成与击杀奖励族，共 30 张 ----
# 数值以 lightspeed C++（BattleContext.cpp useAttackCard L958 起 /
# useSkillCard L1203 起 / usePowerCard L1515 起 / Actions.cpp 复合动作）为准
# 对译；C++ 把部分 Power 状态存为"每次触发数值"（如 COMBUST 5/7、
# FEEL_NO_PAIN 3/4），而本引擎同批次的语义是"层数 × 固定基数"（见
# combat/types.py 注释与 entities.py 结算），基础版两者一致、升级版有
# 数值差异——逐卡注释记录，汇总见迁移报告。


def _exhaust_from_hand(bc: BattleContext, inst: CardInstance) -> None:
    """内容层统一消耗路径（True Grit/Second Wind/Sever Soul/Fiend Fire）。

    对齐 C++ triggerAndMoveToExhaustPile：移出手牌（按实例身份，对齐
    exhaustSpecificCardInHand 的 uniqueId 校验）→ 进消耗堆 → 状态/遗物
    钩子（bc.on_card_exhausted：FEEL_NO_PAIN/DARK_EMBRACE/遗物）→
    卡自身的 on_exhaust_effect（Sentinel）。引擎 on_card_exhausted 已
    （工作树 2026-10-05 接线）读取 on_exhaust_effect——效果侧的
    misc_data 守卫保证两处调用只结算一次，兼容接线前后两种引擎状态。
    """
    for i, c in enumerate(bc.cards.hand):
        if c is inst:
            del bc.cards.hand[i]
            break
    else:
        return  # 已不在手牌（防御性：跳过，对齐 C++ 找不到即 return）
    bc.cards.move_to_exhaust_pile(inst)
    bc.on_card_exhausted(inst)
    if inst.card.on_exhaust_effect is not None:
        inst.card.on_exhaust_effect(bc, inst)


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


# ---- Power 状态族 ----


def _barricade_play(bc: BattleContext, item: CardQueueItem) -> None:
    # C++ 为立即 setHasStatus；入队结算在时机上不可区分（无中途读取点）
    bc.add_to_bot(Actions.buff_player(PlayerStatus.BARRICADE, 1))


def _corruption_play(bc: BattleContext, item: CardQueueItem) -> None:
    bc.add_to_bot(Actions.buff_player(PlayerStatus.CORRUPTION, 1))


def _demon_form_play(bc: BattleContext, item: CardQueueItem) -> None:
    # 回合开始抽牌后 +层数力量（entities.apply_start_of_turn_post_draw_powers）
    bc.add_to_bot(Actions.buff_player(PlayerStatus.DEMON_FORM, 3 if item.card.upgraded else 2))


def _berserk_play(bc: BattleContext, item: CardQueueItem) -> None:
    # 对齐 C++：++energyPerTurn 立即生效；易伤 2 层（升级仅 1 层）入 bot，
    # 玩家自施 → 当轮回合末即递减
    bc.player.energy_per_turn_bonus += 1
    bc.add_to_bot(Actions.debuff_player(PlayerStatus.VULNERABLE, 1 if item.card.upgraded else 2, False))


def _brutality_play(bc: BattleContext, item: CardQueueItem) -> None:
    # C++ 恒 1 层；升级差异 = 费用 1→0 + 固有（isCardInnate 的 upgraded 分支，
    # 用 innate_when_upgraded 位表达，待引擎 move_innate_to_top 接线）
    bc.add_to_bot(Actions.buff_player(PlayerStatus.BRUTALITY, 1))


def _juggernaut_play(bc: BattleContext, item: CardQueueItem) -> None:
    # C++ 存每次触发伤害 5/7（gainBlock 直接用值）；本引擎层数语义
    #（gain_block 内 5×层）。基础 1 层 = 5 伤一致；升级 2 层 = 10 伤
    #（C++ 为 7），差异记录于迁移报告。
    bc.add_to_bot(Actions.buff_player(PlayerStatus.JUGGERNAUT, 2 if item.card.upgraded else 1))


def _rupture_play(bc: BattleContext, item: CardQueueItem) -> None:
    # 层数 = 每次自伤失 HP 的力量增量（C++ 1/2，直接一致）
    bc.add_to_bot(Actions.buff_player(PlayerStatus.RUPTURE, 2 if item.card.upgraded else 1))


def _combust_play(bc: BattleContext, item: CardQueueItem) -> None:
    # C++ 存全体伤害值 5/7、HP 损失恒 1（combustHpLoss，C++ 自带 todo
    # "doesn't stack hp loss correctly"）；本引擎层数语义（回合末失 层 HP
    # + 全体 5×层）。基础 1 层 = 失 1/5 伤一致；升级 2 层 = 失 2/10 伤
    #（C++ 失 1/7 伤），差异记录于迁移报告。
    bc.add_to_bot(Actions.buff_player(PlayerStatus.COMBUST, 2 if item.card.upgraded else 1))


def _evolve_play(bc: BattleContext, item: CardQueueItem) -> None:
    # 层数 = 抽到状态牌时的补抽张数（C++ 1/2 直接用值，语义一致）
    bc.add_to_bot(Actions.buff_player(PlayerStatus.EVOLVE, 2 if item.card.upgraded else 1))


def _fire_breathing_play(bc: BattleContext, item: CardQueueItem) -> None:
    # C++ 存全体伤害值 6/10（CardManager::draw 直接用值，wiki 为 4/6）；
    # 本引擎 4×层语义 → 基础 1 层 = 4 伤（与 wiki 一致、与 C++ 6 不同），
    # 升级 2 层 = 8 伤（C++ 为 10），差异记录于迁移报告。
    bc.add_to_bot(Actions.buff_player(PlayerStatus.FIRE_BREATHING, 2 if item.card.upgraded else 1))


def _feel_no_pain_play(bc: BattleContext, item: CardQueueItem) -> None:
    # C++ 存格挡值 3/4（onCardExhausted 直接用值）；本引擎 3×层语义 →
    # 基础 1 层 = 3 一致；升级 2 层 = 6（C++ 为 4），差异记录于迁移报告。
    bc.add_to_bot(Actions.buff_player(PlayerStatus.FEEL_NO_PAIN, 2 if item.card.upgraded else 1))


def _dark_embrace_play(bc: BattleContext, item: CardQueueItem) -> None:
    # C++ 无 up 分支：恒 1 层；升级只改费 2→1（wiki 同）
    bc.add_to_bot(Actions.buff_player(PlayerStatus.DARK_EMBRACE, 1))


def _flame_barrier_play(bc: BattleContext, item: CardQueueItem) -> None:
    up = item.card.upgraded
    bc.add_to_bot(Actions.gain_block(bc.calculate_card_block(16 if up else 12)))
    bc.add_to_bot(Actions.buff_player(PlayerStatus.FLAME_BARRIER, 6 if up else 4))


def _double_tap_play(bc: BattleContext, item: CardQueueItem) -> None:
    # C++ up?2:1（升级版下一张与下两张攻击牌各翻倍）。注意引擎
    # on_use_attack_card 触发后是整状态 remove 而非 decrement——升级版
    # 2 层实际只翻倍第一张攻击牌，需引擎改为 decrement（见迁移报告）。
    bc.add_to_bot(Actions.buff_player(PlayerStatus.DOUBLE_TAP, 2 if item.card.upgraded else 1))


# ---- 消耗族（技能）----


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


def _power_through_play(bc: BattleContext, item: CardQueueItem) -> None:
    # 对齐 C++：2 张伤口先入手（手牌满则按上限消失），后格挡
    bc.add_to_bot(Actions.make_temp_card_in_hand(WOUND))
    bc.add_to_bot(Actions.make_temp_card_in_hand(WOUND))
    bc.add_to_bot(Actions.gain_block(bc.calculate_card_block(20 if item.card.upgraded else 15)))


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


def _play_top_card(exhaust: bool) -> Action:
    """PlayTopCard 转发（引擎工厂已修复 CardQueueItem 运行时导入）。"""
    return Actions.play_top_card(exhaust)


def _havoc_play(bc: BattleContext, item: CardQueueItem) -> None:
    # 对齐 useSkillCard HAVOC（BattleContext.cpp:1337）：随机目标免费打出
    # 抽牌堆顶牌，打完那张牌消耗（PlayTopCard 第二参 true）。Havoc 自身
    # 消耗：wiki 有"消耗。"，lightspeed doesCardExhaust 未收录 HAVOC（偏差，
    # 以 wiki/任务口径为准置 exhausts=True）。
    bc.add_to_bot(_play_top_card(exhaust=True))


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


# ---- 虚无族 ----


def _carnage_play(bc: BattleContext, item: CardQueueItem) -> None:
    dmg = bc.calculate_card_damage(item, item.target, 28 if item.card.upgraded else 20)
    bc.add_to_bot(Actions.attack_enemy(item.target, dmg))


def _ghostly_armor_play(bc: BattleContext, item: CardQueueItem) -> None:
    bc.add_to_bot(Actions.gain_block(bc.calculate_card_block(13 if item.card.upgraded else 10)))


# ---- 实例计数族（misc_data）----


def _rampage_play(bc: BattleContext, item: CardQueueItem) -> None:
    up = item.card.upgraded
    # 对齐 C++：伤害按打出时的 misc_data 计（先算后加），打出后永久 +5/8。
    # Double Tap 重放体共享本实例 → 重放伤害含第一次的增量（对齐 C++ todo
    # "doubled card damage is changed by the first" 的实际行为）；C++ 额外的
    # findAndUpgradeSpecialData 只为更新战斗外的牌组副本，战斗内等价。
    dmg = bc.calculate_card_damage(item, item.target, 8 + item.card.misc_data)
    bc.add_to_bot(Actions.attack_enemy(item.target, dmg))
    item.card.misc_data += 8 if up else 5


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


def _blood_for_blood_play(bc: BattleContext, item: CardQueueItem) -> None:
    # C++ up?22:18（wiki 同）。受击 -1 费由引擎 cost_delta_on_damage 三堆
    # 遍历实现（onTookDamage→tookDamage→updateCost(-1)，下限 0，无上限
    # 逻辑——CardInstance.cpp:148 的"cost<4"分支是升级路径，不在受击路径）。
    dmg = bc.calculate_card_damage(item, item.target, 22 if item.card.upgraded else 18)
    bc.add_to_bot(Actions.attack_enemy(item.target, dmg))


# ---- 生成与击杀奖励族 ----


def _immolate_play(bc: BattleContext, item: CardQueueItem) -> None:
    # C++ up?28:21（wiki 同）；1 张灼伤进弃牌堆
    bc.add_to_bot(Actions.attack_all_enemy(28 if item.card.upgraded else 21))
    bc.add_to_bot(Actions.make_temp_card_in_discard(BURN))


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


def _hand_of_greed_play(bc: BattleContext, item: CardQueueItem) -> None:
    up = item.card.upgraded
    dmg = bc.calculate_card_damage(item, item.target, 25 if up else 20)

    def run(bc: BattleContext) -> None:
        # 对齐 HandOfGreedAction：注意 C++ 用 m.damage（非攻击 HP 损失）
        # 而非 attacked——不吃 CURL_UP/ANGRY/THE_BOOT 等受击触发
        #（lightspeed 特有口径，wiki 为普通攻击；伤害数值仍按攻击管线在
        # 出牌时算好）。击杀 → +20/25 金币。
        m = bc.monsters.monsters[item.target]
        if m.is_dead_or_escaped():
            return
        m.damage(bc, dmg)
        bc.check_combat()
        if not m.alive:
            bc.player.gold += 25 if up else 20

    bc.add_to_bot(Action(run))


BARRICADE = CardDef("Barricade", "壁垒", 3, "Power", "格挡不再在回合开始时消失。", False, False,
                    _barricade_play, upgraded_cost=2)
CORRUPTION = CardDef("Corruption", "腐化", 3, "Power", "技能牌费用变为 0，打出即消耗。", False, False,
                     _corruption_play, upgraded_cost=2)
DEMON_FORM = CardDef("Demon Form", "恶魔形态", 3, "Power", "每回合开始获得 2 点力量。", False, False, _demon_form_play)
BERSERK = CardDef("Berserk", "狂暴", 1, "Power", "获得 2 层易伤。每回合额外获得 1 点能量。", False, False,
                  _berserk_play, upgraded_cost=0)  # lightspeed getEnergyCost 恒 0（偏差），以 wiki 1→0 为准
BRUTALITY = CardDef("Brutality", "残暴", 1, "Power", "每回合开始失去 1 点 HP 并抽 1 张牌。", False, False,
                    _brutality_play, upgraded_cost=0, innate_when_upgraded=True)  # 费用同上偏差口径
JUGGERNAUT = CardDef("Juggernaut", "重装冲锋", 2, "Power", "每次获得格挡时对随机敌人造成 5 点伤害。", False, False,
                     _juggernaut_play)
RUPTURE = CardDef("Rupture", "破裂", 1, "Power", "自伤失去 HP 时获得 1 点力量。", False, False, _rupture_play)
COMBUST = CardDef("Combust", "燃烧", 1, "Power", "回合末失去 1 点 HP，对所有敌人造成 5 点伤害。", False, False,
                  _combust_play)
EVOLVE = CardDef("Evolve", "进化", 1, "Power", "抽到状态牌时抽 1 张牌。", False, False, _evolve_play)
FIRE_BREATHING = CardDef("Fire Breathing", "火焰吐息", 1, "Power", "抽到状态或诅咒牌时对所有敌人造成 4 点伤害。",
                         False, False, _fire_breathing_play)
FEEL_NO_PAIN = CardDef("Feel No Pain", "无痛", 1, "Power", "卡牌被消耗时获得 3 点格挡。", False, False,
                       _feel_no_pain_play)
DARK_EMBRACE = CardDef("Dark Embrace", "黑暗拥抱", 2, "Power", "卡牌被消耗时抽 1 张牌。", False, False,
                       _dark_embrace_play, upgraded_cost=1)
FLAME_BARRIER = CardDef("Flame Barrier", "烈焰屏障", 2, "Skill", "获得 12 点格挡。本回合受到攻击时对攻击者反弹 4 点伤害。",
                        False, False, _flame_barrier_play)
DOUBLE_TAP = CardDef("Double Tap", "双重打击", 1, "Skill", "本回合下一张攻击牌结算两次。", False, False, _double_tap_play)
SECOND_WIND = CardDef("Second Wind", "喘息", 1, "Skill", "消耗手中所有非攻击牌，每张获得 5 点格挡。", False, False,
                      _second_wind_play)
SENTINEL = CardDef("Sentinel", "哨兵", 1, "Skill", "获得 5 点格挡。被消耗时获得 2 点能量。", False, False,
                   _sentinel_play, on_exhaust_effect=_sentinel_on_exhaust)
POWER_THROUGH = CardDef("Power Through", "硬撑", 1, "Skill", "将 2 张伤口加入手牌。获得 15 点格挡。", False, False,
                        _power_through_play)
TRUE_GRIT = CardDef("True Grit", "坚毅", 1, "Skill", "获得 7 点格挡。消耗 1 张随机手牌。", False, False, _true_grit_play)
HAVOC = CardDef("Havoc", "浩劫", 1, "Skill", "打出抽牌堆顶的牌并消耗它。消耗。", False, True, _havoc_play,
                upgraded_cost=0)
INFERNAL_BLADE = CardDef("Infernal Blade", "地狱之刃", 1, "Skill", "随机攻击牌加入手牌，本回合费用为 0。消耗。",
                         False, True, _infernal_blade_play)  # lightspeed 升级不改费（wiki 为 0 费，偏差以 C++ 为准）
CARNAGE = CardDef("Carnage", "杀戮", 2, "Attack", "虚无。造成 20 点伤害。", True, False, _carnage_play, ethereal=True)
GHOSTLY_ARMOR = CardDef("Ghostly Armor", "幽灵护甲", 1, "Skill", "虚无。获得 10 点格挡。", False, False,
                        _ghostly_armor_play, ethereal=True)
RAMPAGE = CardDef("Rampage", "狂暴冲杀", 1, "Attack", "造成 8 点伤害。本次战斗中此牌每次打出永久 +5 伤害。",
                  True, False, _rampage_play)
SEARING_BLOW = CardDef("Searing Blow", "灼热打击", 2, "Attack", "造成 12 点伤害。可以多次升级，每次 +2 伤害递增。",
                       True, False, _searing_blow_play,
                       multiple_upgrades=True)  # 批次 3 接线：Armaments 升级路径经 upgrade() 推进 misc_data（原批次 2 遗留 TODO）
BLOOD_FOR_BLOOD = CardDef("Blood for Blood", "以血还血", 4, "Attack", "造成 18 点伤害。战斗中每次失去 HP，费用 -1。",
                          True, False, _blood_for_blood_play, upgraded_cost=3, cost_delta_on_damage=-1)
SEVER_SOUL = CardDef("Sever Soul", "撕裂灵魂", 2, "Attack", "消耗手中所有非攻击牌。造成 16 点伤害。", True, False,
                     _sever_soul_play)
FIEND_FIRE = CardDef("Fiend Fire", "恶魔之火", 2, "Attack", "消耗手中所有牌，每张造成 7 点伤害。消耗。", True, True,
                     _fiend_fire_play)
IMMOLATE = CardDef("Immolate", "焚化", 2, "Attack", "对所有敌人造成 21 点伤害。1 张灼伤加入弃牌堆。", False, False,
                   _immolate_play)
FEED = CardDef("Feed", "吞噬", 1, "Attack", "造成 10 点伤害。若击杀敌人，最大 HP +3 并回复 3 点 HP。消耗。",
               True, True, _feed_play)
HAND_OF_GREED = CardDef("Hand of Greed", "贪婪之手", 2, "Attack", "造成 20 点伤害。若击杀敌人，获得 20 金币。",
                        True, False, _hand_of_greed_play, colorless=True)  # 无色稀有卡（CardPools srcColorlessCardPool）


# ---- 困难档迁移（批次 3，2026-10-06）：X 费 Whirlwind + 选卡族 6 张 ----
# 数值与结算顺序以 lightspeed C++ 为准（BattleContext.cpp useAttackCard /
# useSkillCard 各分支 + Actions.cpp 复合动作 + BattleContext.cpp 的
# chooseXxx 回调族 + Cards.h doesCardExhaust/isXCost/getUpgradedCost）；
# 与 wiki 不一致处逐卡注释。True Grit+ 的选卡版已在批次 2 实现，本批次
# 核对与 C++ TRUE_GRIT 分支（ChooseExhaustOne / ExhaustRandomCardInHand）
# 一致，不改动。


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


def _upgrade_in_place(inst: CardInstance) -> None:
    """升级手牌实例（Armaments 路径）。引擎 CardInstance.upgrade() 对已升级
    实例 no-op 返回 False，而 C++ upgrade() 的 SEARING_BLOW 分支无条件
    ++specialData（可反复升级，CardInstance.cpp:143-146）——引擎层
    （card_manager）不在本批次可改范围，内容层补齐该分支：可多次升级且
    已升级的实例直接递增 misc_data。
    """
    if inst.card.multiple_upgrades and inst.upgraded:
        inst.misc_data += 1
    else:
        inst.upgrade()


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


def _headbutt_play(bc: BattleContext, item: CardQueueItem) -> None:
    # 对齐 C++ HEADBUTT：先攻击（9/12，出牌时算伤）后 HeadbuttAction 选卡
    # （候选=弃牌堆全部，空堆仅攻击无选卡）；选中 → 置抽牌堆顶 + 移出弃牌堆。
    # C++ 的 OnAfterCardUsed（打出的牌落堆）是入队动作，晚于本卡自身效果
    # （Actions.cpp OnAfterCardUsed）——即 C++ HeadbuttAction 看到的弃牌堆
    # 不含刚打出的 Headbutt；本引擎 on_after_use_card 同步先行，刚打出的
    # Headbutt 已落弃牌堆，故按实例身份排除以对齐 C++ 净候选集（"空堆仅
    # 攻击"的口径也由此成立；堆中先前的 Headbutt 仍可选，与 C++ 一致）。
    dmg = bc.calculate_card_damage(item, item.target, 12 if item.card.upgraded else 9)
    bc.add_to_bot(Actions.attack_enemy(item.target, dmg))

    def run(bc: BattleContext) -> None:
        candidates = [c for c in bc.cards.discard_pile if c is not item.card]

        def on_choose(bc2: BattleContext, chosen: list) -> None:
            for inst in chosen:
                bc2.cards.discard_pile.remove(inst)
                bc2.cards.append_to_draw_top(inst)

        bc.open_card_select(
            candidates, on_choose, prompt="头槌：选择 1 张弃牌置于抽牌堆顶"
        )

    bc.add_to_bot(Action(run))


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


def _exhume_play(bc: BattleContext, item: CardQueueItem) -> None:
    def run(bc: BattleContext) -> None:
        # 手牌满：整体跳过（对齐 C++ cardsInHand == MAX_HAND_SIZE 守卫）
        if len(bc.cards.hand) >= MAX_HAND_SIZE:
            return
        # 候选 = 消耗堆中非 Exhume 的牌（对齐 C++ 排除分支——lightspeed 自带
        # todo 标注此为 bug：本体允许选回 Exhume 自身；按"以 C++ 为准"口径
        # 实现排除）。时序差异说明：C++ 打出的牌落堆晚于自身效果（OnAfterCardUsed
        # 入队），本引擎同步先行——但排除按卡牌身份过滤，两边的净候选集一致
        #（本引擎额外排除的"刚打出的自身"在 C++ 中尚未落堆，同样不可选）。
        candidates = [c for c in bc.cards.exhaust_pile if c.card is not EXHUME]

        def on_choose(bc2: BattleContext, chosen: list) -> None:
            for inst in chosen:
                bc2.cards.exhaust_pile.remove(inst)
                bc2.cards.hand.append(inst)  # 回手（对齐 moveToHandHelper；手满守卫已前置）

        bc.open_card_select(
            candidates, on_choose, prompt="发掘：选择 1 张消耗堆的牌回到手牌"
        )

    bc.add_to_bot(Action(run))


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


WHIRLWIND = CardDef("Whirlwind", "旋风斩", -1, "Attack",
                    "消耗所有能量，对所有敌人造成 5 点伤害，次数等同于能量数。（升级 8 点）",
                    False, False, _whirlwind_play, x_cost=True)
ARMAMENTS = CardDef("Armaments", "武装", 1, "Skill",
                    "获得 5 点格挡。升级 1 张手牌。（升级后：升级所有手牌）",
                    False, False, _armaments_play)
WARCRY = CardDef("Warcry", "战吼", 0, "Skill",
                 "抽 1 张牌。将 1 张手牌置于抽牌堆顶。消耗。（升级抽 2 张）",
                 False, True, _warcry_play)
HEADBUTT = CardDef("Headbutt", "头槌", 1, "Attack",
                   "造成 9 点伤害。将 1 张弃牌堆的牌置于抽牌堆顶。（升级 12 点）",
                   True, False, _headbutt_play)
DUAL_WIELD = CardDef("Dual Wield", "双持", 1, "Skill",
                     "复制 1 张手中的攻击或能力牌加入手牌。（升级后 2 份）消耗。",
                     False, True, _dual_wield_play)  # wiki 口径置消耗；lightspeed doesCardExhaust 未收录 DUAL_WIELD（偏差，同 Havoc 处理）
EXHUME = CardDef("Exhume", "发掘", 1, "Skill",
                 "从消耗堆选 1 张牌回到手牌。消耗。", False, True, _exhume_play,
                 upgraded_cost=0)  # Cards.h getUpgradedCost：EXHUME 升级 1→0（同 Havoc/Seeing Red）
BURNING_PACT = CardDef("Burning Pact", "燃烧契约", 1, "Skill",
                       "消耗 1 张手牌。抽 2 张牌。（升级抽 3 张）",
                       False, False, _burning_pact_play)


# ---- 诅咒卡 / 无色卡 / 静默卡 / 观者卡 / 故障卡 re-export（正式定义在
# curses_cards.py / colorless_cards.py / silent_cards.py / watcher_cards.py /
# defect_cards.py，批次 4 / 批次 C / 批次 E / 批次 F）----
# 惰性 re-export（PEP 562）：各内容子模块均需在模块级导入本文件的 CardDef，
# 顶部 from-import 会构成 cards→子模块→cards 的导入期循环（子模块先导入时
# 本文件尾部拿不到已定义名）；__getattr__ 只在属性缺失时触发，任意导入顺序
# 均安全。from sts.content.cards import REGRET / BANDAGE_UP 等用法保持兼容。


def __getattr__(name: str):
    import sts.content.curses_cards as _curses

    if hasattr(_curses, name):
        return getattr(_curses, name)
    import sts.content.colorless_cards as _colorless

    if hasattr(_colorless, name):
        return getattr(_colorless, name)
    import sts.content.silent_cards as _silent

    if hasattr(_silent, name):
        return getattr(_silent, name)
    import sts.content.watcher_cards as _watcher

    if hasattr(_watcher, name):
        return getattr(_watcher, name)
    import sts.content.defect_cards as _defect

    if hasattr(_defect, name):
        return getattr(_defect, name)
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")

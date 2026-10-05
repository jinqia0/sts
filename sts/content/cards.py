"""铁甲战士卡牌定义（对齐 lightspeed useAttackCard/useSkillCard 的逐卡 switch）。

每张卡 = 不可变模板（CardDef）+ play()（把效果分解为原子动作入队）。
数值来源 slaythespire.wiki.gg（A0 基准）；升级版数值用 self.upgraded 分支。
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

from sts.combat.actions import Actions
from sts.combat.queue import Action
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


def _strike_play(bc: BattleContext, item: CardQueueItem) -> None:
    dmg = bc.calculate_card_damage(item, item.target, 6 if not item.card.upgraded else 9)
    bc.add_to_bot(Actions.attack_enemy(item.target, dmg))


def _defend_play(bc: BattleContext, item: CardQueueItem) -> None:
    bc.add_to_bot(Actions.gain_block(bc.calculate_card_block(5)))


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
    raise RuntimeError("不可打出的卡不应进入结算（play_card 应当拦截）")


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
    bc.add_to_bot(Actions.damage_player(4 if up else 2))


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

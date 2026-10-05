"""铁甲战士卡牌定义（对齐 lightspeed useAttackCard/useSkillCard 的逐卡 switch）。

每张卡 = 不可变模板（CardDef）+ play()（把效果分解为原子动作入队）。
数值来源 slaythespire.wiki.gg（A0 基准）；升级版数值用 self.upgraded 分支。
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

from sts.combat.actions import Actions
from sts.combat.types import MonsterStatus, PlayerStatus

if TYPE_CHECKING:
    from sts.combat.battle import BattleContext
    from sts.combat.queue import CardQueueItem


@dataclass(frozen=True)
class CardDef:
    name: str
    zh: str
    cost: int
    ctype: str  # "Attack" | "Skill" | "Power" | "Status"
    text: str
    needs_target: bool
    exhausts: bool
    play: "type(None) | callable"  # (bc, item) -> None，入队原子动作
    unplayable: bool = False  # 状态/诅咒卡不可打出（Wound 等）
    upgraded_cost: int | None = None  # 升级版改费（Body Slam+：1→0），None 表示不变


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

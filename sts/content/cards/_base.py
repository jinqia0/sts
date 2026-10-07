"""CardDef 模板 + 跨职业共享的私有出牌助手。

原 cards.py（现 ironclad.py）顶层的公共定义，包化拆分（2026-10-07）
后集中于此：各职业子模块从这里取 CardDef 与共享助手，避免「子模块 ←
铁甲文件」的跨模块依赖。字段语义见各字段行内注释，与拆分前逐字一致。

助手依赖注：_strike_play/_defend_play 仅用 Actions 与 TYPE_CHECKING
类型，import 保持轻量；_exhaust_from_hand/_upgrade_in_place 同。
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

from sts.combat.actions import Actions

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
    on_exhaust_effect: "callable | None" = None  # 被消耗时触发 (bc, inst) -> None（Sentinel +能量；引擎 on_card_exhausted 已接线读取，内容层 _exhaust_from_hand 的显式调用以效果侧守卫防双重）
    # ---- Retain 关键词（批次 A：Watcher/Silent/Defect 共用）----
    self_retain: bool = False  # 自带保留：回合末不弃（Crescendo/Protect 等）
    retain_when_upgraded: bool = False  # 仅升级版保留（Worship/Blasphemy）
    on_discard_effect: "callable | None" = None  # 被弃置时触发（Tactician/Reflex），引擎 on_manual_discard 已接线
    on_drawn_effect: "callable | None" = None  # 被抽到时触发（Endless Agony：复制 1 张入手），引擎 on_card_drawn 已接线
    dynamic_cost: "callable | None" = None  # 动态费用回调 (bc, inst) -> int（Eviscerate：3-本回合弃牌数）
    # ---- 中等档迁移新增（批次 2）----
    innate_when_upgraded: bool = False  # 仅升级版固有（Brutality+；引擎 move_innate_to_top 需接线读此位，见批次 2 报告）
    # ---- 无色卡批次新增（批次 4，2026-10-06）----
    colorless: bool = False  # 无色卡标记（生成池筛选：Jack of All Trades/Transmutation/Magnetism 的 CombatColorlessCardPool 对应物）
    # ---- 2026-10-07 补齐批次 ----
    loses_ethereal_on_upgrade: bool = False  # 升级后不再虚无（Apparition+；引擎 CardInstance.is_ethereal 读取）
    shuffle_back_into_draw_pile: bool = False  # 打出后洗回抽牌堆（Tantrum；本体 AbstractCard 同名字段，由出牌收尾 on_after_use_card 处理）


def _strike_play(bc: BattleContext, item: CardQueueItem) -> None:
    dmg = bc.calculate_card_damage(item, item.target, 6 if not item.card.upgraded else 9)
    bc.add_to_bot(Actions.attack_enemy(item.target, dmg))


def _defend_play(bc: BattleContext, item: CardQueueItem) -> None:
    # Defend+ 为 8 格挡（wiki；批次 C 遗留修正——原恒 5 不读升级位）
    bc.add_to_bot(Actions.gain_block(bc.calculate_card_block(8 if item.card.upgraded else 5)))


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

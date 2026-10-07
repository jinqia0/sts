"""CardDef：卡牌不可变模板的公共定义。

原 cards.py 顶层类，包化拆分（2026-10-07）后独立成模块：各职业/类别
子模块（ironclad/silent/defect/watcher/colorless/curses）与本包
__init__ 均从这里取 CardDef，避免「子模块 ← 铁甲文件」的跨模块依赖。
字段语义见各字段行内注释，与拆分前逐字一致。
"""

from __future__ import annotations

from dataclasses import dataclass


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

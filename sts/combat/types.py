"""引擎层公共类型：枚举与 Statuses 容器。

自 sts_lightspeed 移植（include/constants/*StatusEffects.h 的 Python 化）：
状态用 IntEnum + 计数容器表达，而非 Power 对象栈——lightspeed 验证过
的设计是「结算逻辑集中在引擎/实体方法里按固定顺序检查状态」，每加
一个状态只是枚举 + 一处结算代码，不需要订阅系统。

Player 与 Monster 的状态枚举分开（对齐 lightspeed：PS:: / MS::），
因为同名状态在两侧语义不同（如 Ritual 只存在于怪物侧）。
"""

from __future__ import annotations

from enum import Enum, IntEnum


class Outcome(IntEnum):
    UNDECIDED = 0
    PLAYER_VICTORY = 1
    PLAYER_LOSS = 2


class InputState(Enum):
    """战斗推进的输入状态机（对齐 lightspeed InputState.h，范围裁剪到当前场景）。

    EXECUTING_ACTIONS：动作/卡牌队列仍在弹出，环境不接受玩家输入
    PLAYER_NORMAL：队列全空，等待玩家出牌或结束回合
    （CARD_SELECT 等选卡状态在引入对应卡牌时再加）
    """

    EXECUTING_ACTIONS = 0
    PLAYER_NORMAL = 1
    CARD_SELECT = 2


class CardType(Enum):
    ATTACK = "Attack"
    SKILL = "Skill"
    POWER = "Power"
    STATUS = "Status"
    CURSE = "Curse"


class PlayerStatus(IntEnum):
    """玩家侧状态（当前在范围内的子集，加卡时扩枚举）。

    衰减语义分组（结算位置见 entities.Player）：
    - debuff 回合末衰减：VULNERABLE/WEAK/FRAIL/NO_BLOCK/INTANGIBLE
      （just_applied 首轮跳过）
    - 回合末清除/结算：LOSE_STRENGTH/NO_DRAW/ENTANGLED/DOUBLE_TAP/
      METALLICIZE（得格挡）/COMBUST/THE_BOMB（倒数）
    - 回合开始清除：FLAME_BARRIER（仅本回合反伤）
    - Power 永续：METALLICIZE/BARRICADE/CORRUPTION/DEMON_FORM/BRUTALITY/
      JUGGERNAUT/RUPTURE/EVOLVE/FIRE_BREATHING/FEEL_NO_PAIN/DARK_EMBRACE
    """

    STRENGTH = 0
    DEXTERITY = 1
    VULNERABLE = 2
    WEAK = 3
    FRAIL = 4
    METALLICIZE = 5
    RAGE = 6
    ARTIFACT = 7
    # 以下为本场景暂无来源、但管线/结算已预留位置的状态
    ENERGIZED = 8
    VIGOR = 9
    # Flex 的临时力量（回合末扣回）与 Battle Trance 的禁抽（回合末移除）
    LOSE_STRENGTH = 10
    NO_DRAW = 11
    # ---- 全量内容迁移新增（Power 族 + 特殊 debuff，2026-10-05 批次 0）----
    ENTANGLED = 12  # 本回合不能打出卡牌（红奴役者；回合末解除）
    BARRICADE = 13  # 格挡回合开始不清零
    CORRUPTION = 14  # 技能牌 0 费且打出即消耗
    DEMON_FORM = 15  # 回合开始（抽牌后）+层数力量（层数=每回合增量）
    BRUTALITY = 16  # 回合开始（抽牌后）失去 1 HP×层 并抽 1×层
    JUGGERNAUT = 17  # 每次获得格挡 → 随机敌人受 5×层 伤
    RUPTURE = 18  # 自伤失去 HP 时 +层力量
    COMBUST = 19  # 回合末失去 1×层 HP，对所有敌人造成 5×层 伤
    EVOLVE = 20  # 抽到状态牌时抽 1×层
    FIRE_BREATHING = 21  # 抽到状态/诅咒牌时对所有敌人 4×层 伤
    FEEL_NO_PAIN = 22  # 卡牌被消耗时获得 3×层 格挡
    DARK_EMBRACE = 23  # 卡牌被消耗时抽 1×层
    FLAME_BARRIER = 24  # 本回合受攻击时对攻击者反弹 层 伤（回合开始移除）
    DOUBLE_TAP = 25  # 本回合下一张攻击牌结算两次（触发后移除）
    INTANGIBLE = 26  # 受到的伤害降为 1（回合末衰减）
    NO_BLOCK = 27  # 无法获得格挡（回合末衰减）
    THE_BOMB = 28  # 3 回合后对所有敌人造成 special["the_bomb"] 伤（回合末倒数）
    PEN_NIB = 29  # 下一张攻击牌伤害翻倍（PEN_NIB 遗物触发段，一次性）
    THORNS = 30  # 反伤：受到攻击时对攻击者反弹层数伤害（Bronze Scales 等）
    MAYHEM = 31  # 每回合开始自动打出抽牌堆顶牌 ×层（无色卡 Mayhem）
    MAGNETISM = 32  # 每回合开始随机无色牌入手 ×层（无色卡 Magnetism；生成逻辑在内容层闭包）
    SADISTIC = 33  # 敌人被施加 debuff 时受 层 伤（无色卡 Sadistic Nature；lightspeed 未实现触发段，仅状态落地）
    # ---- 遗物批次 1 新增（2026-10-05，尾部追加不改旧值）----
    PLATED_ARMOR = 31  # 重甲：回合末按层数获得格挡；受到未被格挡吸收的攻击伤害时 -1 层（Thread and Needle）
    NEXT_TURN_BLOCK = 32  # 下回合格挡：回合开始按层数获得格挡后移除，可叠加（Self-Forming Clay）
    FOCUS = 33  # 专长（Defect 充能球加成；无充能球体系，预留——Data Disk 装载）
    MANTRA = 34  # 真言（Damaru 每回合 +1；无观者姿态体系，预留）


class MonsterStatus(IntEnum):
    """怪物侧状态（当前在范围内的子集）。"""

    STRENGTH = 0
    VULNERABLE = 1
    WEAK = 2
    RITUAL = 3
    METALLICIZE = 4
    ANGRY = 5
    CURL_UP = 6
    SHACKLED = 7
    ARTIFACT = 8
    # SPORE_CLOUD：死亡时给玩家 2 层易伤（Fungi Beast；结算见 entities.Monster.die）
    SPORE_CLOUD = 9
    # ---- Act 1 全量迁移新增（2026-10-05 批次 0）----
    ENRAGE = 10  # 玩家每打出一张技能牌，+层 力量（Gremlin Nob）
    MODE_SHIFT = 11  # 受到伤害累积计数，归零切换模式（The Guardian，计数存 misc_info）
    SHARP_HIDE = 12  # 玩家每打出攻击牌反伤 局（The Guardian 防御模式）
    THIEVERY = 13  # 偷金（Looter；偷到的金币存 misc_info，死亡时返还）
    ASLEEP = 14  # 沉睡（Lagavulin；受击唤醒，唤醒时移除 METALLICIZE）
    POISON = 15  # 中毒：回合开始失去层数 HP、层数-1（预留，Act 1 无来源）
    THORNS = 16  # 反伤（预留，Act 1 怪无来源）


class Statuses:
    """一个实体的状态计数表：{Status: 层数} + just_applied 集合。

    just_applied（对齐 lightspeed Monster.h addDebuff）：怪物施加的
    WEAK/VULNERABLE 设此标志，首个回合末不递减；玩家施加的不设、
    当轮回合末就递减。攻击/受击结算不读取此集合，仅回合末衰减用。
    """

    def __init__(self) -> None:
        self._counts: dict[IntEnum, int] = {}
        self._just_applied: set[IntEnum] = set()

    def has(self, s: IntEnum) -> bool:
        return self._counts.get(s, 0) > 0

    def get(self, s: IntEnum) -> int:
        return self._counts.get(s, 0)

    def set(self, s: IntEnum, v: int) -> None:
        self._counts[s] = v

    def add(self, s: IntEnum, n: int) -> None:
        self._counts[s] = self._counts.get(s, 0) + n

    def remove(self, s: IntEnum) -> None:
        self._counts.pop(s, None)
        self._just_applied.discard(s)

    def decrement(self, s: IntEnum, n: int = 1) -> None:
        v = self.get(s) - n
        if v <= 0:
            self.remove(s)
        else:
            self._counts[s] = v

    def just_applied(self, s: IntEnum) -> bool:
        return s in self._just_applied

    def set_just_applied(self, s: IntEnum, v: bool) -> None:
        if v:
            self._just_applied.add(s)
        else:
            self._just_applied.discard(s)

    def items(self) -> list[tuple[IntEnum, int]]:
        return sorted(self._counts.items(), key=lambda kv: kv[0].value)

    def __repr__(self) -> str:
        inner = ", ".join(f"{s.name}={n}" for s, n in self.items())
        return f"Statuses({inner})"

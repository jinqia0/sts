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
    """玩家侧状态（当前在范围内的子集，加卡时扩枚举）。"""

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

"""Act 1 怪物定义（对齐 lightspeed src/combat/MonsterSpecific.cpp）。

每个怪 = Monster 子类：
- hp_range：HP 均匀抽样区间（monster_hp 流；A0 基准）
- create(bc, idx)：构造（HP roll + 构造期 roll，如虱子的 Bite 伤害/Curl Up）
- get_move_for_roll：意图选择（ai 流 0..99 roll 分段 + 部分怪的内层布尔抽样，
  分段区间与内层概率逐行对齐 C++ getMoveForRoll）
- take_turn：按当前意图把动作入队 + 回合末 roll_move 生成下回合意图

意图可见性遵守 DESIGN.md §4.2：意图在怪物回合结束时才生成，
观测中物理上不存在未来值。

已移植：Cultist、Jaw Worm、Red/Green Louse、Acid/Spike Slime (S)、Fungi Beast。
数值一律 A0（C++ 源码 `ascN ? x : y` 取 y）。

源码与任务描述/wiki 的出入（以 C++ 为准）：
- Red Louse 的副招是 Grow（力量+3），不是 Spit Web；Green Louse 才是
  Spit Web，且施加 2 层虚弱（DebuffPlayer<PS::WEAK>(2)）而非 3 层。
- Acid Slime (S) 的招式是 Lick（1 层虚弱）/ Tackle（3 伤）交替，
  没有 Corrosive Spit（那是 M/L 型的招式），因此不需要 Slimed 临时卡。
- Spike Slime (S) 只有 Tackle（5 伤），确定性出招（无 Lick）。
- Jaw Worm Thrash 为 7 伤 + 5 格挡（非 8 伤 + 3 格挡）。
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

from sts.combat.actions import Actions
from sts.combat.entities import Monster
from sts.combat.types import MonsterStatus, PlayerStatus

if TYPE_CHECKING:
    from sts.combat.battle import BattleContext


@dataclass(frozen=True)
class MoveDef:
    name: str
    zh: str
    kind: str  # "attack" | "buff" | "debuff" | "defend" | "unknown"
    base_damage: int | None = None  # attack 招式的基础伤害（意图展示与结算共用）
    intent_text: str = ""  # 非攻击招式的意图展示文本


# ---- 出招历史辅助（对齐 lightspeed lastMove / lastTwoMoves）----
# roll 时机（take_turn 尾部的 roll_move）：move_history[0] 是刚执行的招式，
# [1] 是上一回合的——与 C++ moveHistory 双槽语义一致。


def _last(m: Monster, name: str) -> bool:
    return bool(m.move_history) and m.move_history[0].name == name


def _last_two(m: Monster, name: str) -> bool:
    return len(m.move_history) >= 2 and all(x.name == name for x in m.move_history[:2])


def _ai_boolean(bc: BattleContext, chance: float) -> bool:
    """内层布尔抽样（对齐 lightspeed aiRng.randomBoolean(chance) 的分布）。

    DESIGN.md §3 不做轨迹对齐，用万分位整数抽样近似连续 uniform：
    0.5625/0.357/0.416/0.5 均可被 10000 精确整除，分布完全一致。
    """
    return bc.rngs.ai.int_inclusive(0, 9999) < round(chance * 10000)


class Cultist(Monster):
    """邪教徒（Act 1 普通怪单怪遭遇）。

    数据来源 slaythespire.wiki.gg/wiki/Cultist：
      HP 48-54；第 1 回合咒语（3 层仪式），此后每回合黑暗打击 6 伤。
      出招完全确定。黑暗打击序列 6, 9, 12, …（Ritual 回合末 +3，
      施加当轮 skipFirst 跳过——见 combat/entities.py 的衰减逻辑）。
    """

    name = "Cultist"
    zh = "邪教徒"
    hp_range = (48, 54)

    INCANTATION = MoveDef("Incantation", "咒语", "buff", intent_text="获得 3 层仪式")
    DARK_STRIKE = MoveDef("Dark Strike", "黑暗打击", "attack", base_damage=6)

    def __init__(self, idx: int, hp: int, max_hp: int):
        super().__init__(idx, hp, max_hp, f"邪教徒(Cultist)")

    @classmethod
    def create(cls, bc: BattleContext, idx: int) -> "Cultist":
        hp = bc.rngs.monster_hp.int_inclusive(*cls.hp_range)
        return cls(idx, hp, hp)

    def get_move_for_roll(self, bc: BattleContext, roll: int) -> MoveDef:
        # 出招完全确定：首回合咒语，之后每回合黑暗打击
        if self.turns_taken == 0:
            return self.INCANTATION
        return self.DARK_STRIKE

    def take_turn(self, bc: BattleContext) -> None:
        move = self.move_history[0]
        match move.name:
            case "Incantation":
                # buff<RITUAL> 自带 justApplied（skipFirst）：见 entities.Monster.buff
                self.buff(MonsterStatus.RITUAL, 3)
                bc.log.append(f"{self.display_name} 使用 咒语(Incantation)，获得 3 层仪式。")
            case "Dark Strike":
                dmg = bc.calculate_monster_damage(self, 6)
                bc.log.append(f"{self.display_name} 使用 黑暗打击(Dark Strike)。")
                bc.add_to_bot(Actions.attack_player(self.idx, dmg))
            case _:
                raise AssertionError(f"未知招式 {move}")
        # 回合末生成下回合意图（对齐 lightspeed takeTurn 尾部的 RollMove）
        bc.add_to_bot(Actions.roll_move(self.idx))
        self.turns_taken += 1


class JawWorm(Monster):
    """颚虫（Act 1 单怪遭遇，也可能是首个精英后的普通遭遇）。

    wiki/C++ A0：HP 40-44。首回合固定 Chomp（11 伤）；之后 roll 分段：
      roll < 25：上回合 Chomp → 内层 56.25% Bellow / 否则 Thrash；
                 否则 Chomp
      roll < 55：上上两回合都是 Thrash → 内层 35.7% Chomp / 否则 Bellow；
                 否则 Thrash
      roll ≥ 55：上回合 Bellow → 内层 41.6% Chomp / 否则 Thrash；
                 否则 Bellow
    招式数值：Chomp 11 伤；Thrash 7 伤 + 5 格挡；Bellow 力量+3 + 6 格挡。
    """

    name = "Jaw Worm"
    zh = "颚虫"
    hp_range = (40, 44)

    CHOMP = MoveDef("Chomp", "重咬", "attack", base_damage=11)
    THRASH = MoveDef("Thrash", "抽打", "attack", base_damage=7)  # 另获 5 格挡
    BELLOW = MoveDef("Bellow", "咆哮", "buff", intent_text="力量+3，格挡+6")

    def __init__(self, idx: int, hp: int, max_hp: int):
        super().__init__(idx, hp, max_hp, "颚虫(Jaw Worm)")

    @classmethod
    def create(cls, bc: BattleContext, idx: int) -> "JawWorm":
        hp = bc.rngs.monster_hp.int_inclusive(*cls.hp_range)
        return cls(idx, hp, hp)

    def get_move_for_roll(self, bc: BattleContext, roll: int) -> MoveDef:
        if self.turns_taken == 0:  # firstTurn：固定 Chomp
            return self.CHOMP
        if roll < 25:
            if _last(self, "Chomp"):
                return self.BELLOW if _ai_boolean(bc, 0.5625) else self.THRASH
            return self.CHOMP
        if roll < 55:
            if _last_two(self, "Thrash"):
                return self.CHOMP if _ai_boolean(bc, 0.357) else self.BELLOW
            return self.THRASH
        if _last(self, "Bellow"):
            return self.CHOMP if _ai_boolean(bc, 0.416) else self.THRASH
        return self.BELLOW

    def take_turn(self, bc: BattleContext) -> None:
        move = self.move_history[0]
        match move.name:
            case "Chomp":
                dmg = bc.calculate_monster_damage(self, 11)
                bc.log.append(f"{self.display_name} 使用 重咬(Chomp)。")
                bc.add_to_bot(Actions.attack_player(self.idx, dmg))
            case "Thrash":
                dmg = bc.calculate_monster_damage(self, 7)
                bc.log.append(f"{self.display_name} 使用 抽打(Thrash)。")
                bc.add_to_bot(Actions.attack_player(self.idx, dmg))
                bc.add_to_bot(Actions.monster_gain_block(self.idx, 5))
            case "Bellow":
                # 力量立即结算（对齐 C++ buff<MS::STRENGTH>，不入队）；格挡入队
                self.statuses.add(MonsterStatus.STRENGTH, 3)
                bc.log.append(f"{self.display_name} 使用 咆哮(Bellow)，力量+3。")
                bc.add_to_bot(Actions.monster_gain_block(self.idx, 6))
            case _:
                raise AssertionError(f"未知招式 {move}")
        bc.add_to_bot(Actions.roll_move(self.idx))
        self.turns_taken += 1


class Louse(Monster):
    """虱子公共基类（红虱/绿虱共享的构造与 Bite）。

    构造期 roll（对齐 C++ construct + preBattleAction，均走 monsterHpRng）：
      1. HP（红虱 10-15 / 绿虱 11-17）
      2. Bite 伤害 5-7（construct 的 miscInfo，战斗开始定死）
      3. Curl Up 3-7（preBattleAction；首次受击获得等量格挡，
         结算钩子在 entities.Monster.attacked 的 CURL_UP 分支）
    出招约束：25% 副招 / 75% Bite，同一招不连续三回合（roll<25 时若
    副招已连续两回合则改出 Bite；roll≥25 时若 Bite 已连续两回合则出副招）。
    """

    name = "Louse"
    zh = "虱子"
    hp_range = (10, 15)  # 子类覆盖

    def __init__(self, idx: int, hp: int, max_hp: int, display_name: str, bite_dmg: int, curl_up: int):
        super().__init__(idx, hp, max_hp, display_name)
        self.bite_dmg = bite_dmg
        # Bite 伤害逐实例不同：MoveDef 挂在实例上（意图展示用同一份数值）
        self.BITE = MoveDef("Bite", "啃咬", "attack", base_damage=bite_dmg)
        self.statuses.add(MonsterStatus.CURL_UP, curl_up)

    @classmethod
    def create(cls, bc: BattleContext, idx: int) -> "Louse":
        hp = bc.rngs.monster_hp.int_inclusive(*cls.hp_range)
        bite = bc.rngs.monster_hp.int_inclusive(5, 7)
        curl = bc.rngs.monster_hp.int_inclusive(3, 7)
        return cls(idx, hp, hp, f"{cls.zh}({cls.name})", bite, curl)

    def _bite_turn(self, bc: BattleContext) -> None:
        dmg = bc.calculate_monster_damage(self, self.bite_dmg)
        bc.log.append(f"{self.display_name} 使用 啃咬(Bite)。")
        bc.add_to_bot(Actions.attack_player(self.idx, dmg))

    def _second_move_turn(self, bc: BattleContext) -> None:
        raise NotImplementedError

    def get_move_for_roll(self, bc: BattleContext, roll: int) -> MoveDef:
        second = self._second_move()
        if roll < 25:
            if _last_two(self, second.name):
                return self.BITE
            return second
        if _last_two(self, "Bite"):
            return second
        return self.BITE

    def _second_move(self) -> MoveDef:
        raise NotImplementedError

    def take_turn(self, bc: BattleContext) -> None:
        move = self.move_history[0]
        match move.name:
            case "Bite":
                self._bite_turn(bc)
            case _:
                self._second_move_turn(bc)
        bc.add_to_bot(Actions.roll_move(self.idx))
        self.turns_taken += 1


class RedLouse(Louse):
    """红虱：Bite 5-7 伤 / Grow 力量+3（A17 起为 +4）。HP 10-15。"""

    name = "Red Louse"
    zh = "红虱"
    hp_range = (10, 15)

    GROW = MoveDef("Grow", "生长", "buff", intent_text="力量+3")

    def _second_move(self) -> MoveDef:
        return self.GROW

    def _second_move_turn(self, bc: BattleContext) -> None:
        self.statuses.add(MonsterStatus.STRENGTH, 3)
        bc.log.append(f"{self.display_name} 使用 生长(Grow)，力量+3。")


class GreenLouse(Louse):
    """绿虱：Bite 5-7 伤 / Spit Web 施加 2 层虚弱。HP 11-17。

    虚弱为怪物施加（isSourceMonster=True）：justApplied 跳过首个回合末衰减
    （对齐 C++ DebuffPlayer<PS::WEAK>(2) 的默认参数）。
    """

    name = "Green Louse"
    zh = "绿虱"
    hp_range = (11, 17)

    SPIT_WEB = MoveDef("Spit Web", "吐丝", "debuff", intent_text="施加 2 层虚弱")

    def _second_move(self) -> MoveDef:
        return self.SPIT_WEB

    def _second_move_turn(self, bc: BattleContext) -> None:
        bc.log.append(f"{self.display_name} 使用 吐丝(Spit Web)。")
        bc.add_to_bot(Actions.debuff_player(PlayerStatus.WEAK, 2, True))


class AcidSlimeS(Monster):
    """酸液史莱姆（小）：Lick 1 层虚弱 / Tackle 3 伤。

    wiki/C++ A0：HP 8-12。首回合 50/50 抽 Lick 或 Tackle（内层 aiRng
    randomBoolean，roll 参数本身不用），此后两招严格交替——take_turn 直接
    set_move 切换、不再消耗 ai 流（对齐 C++ ACID_SLIME_S 分支无 RollMove）。
    """

    name = "Acid Slime (S)"
    zh = "酸液史莱姆（小）"
    hp_range = (8, 12)

    LICK = MoveDef("Lick", "舔舐", "debuff", intent_text="施加 1 层虚弱")
    TACKLE = MoveDef("Tackle", "冲撞", "attack", base_damage=3)

    def __init__(self, idx: int, hp: int, max_hp: int):
        super().__init__(idx, hp, max_hp, "酸液史莱姆（小）(Acid Slime (S))")

    @classmethod
    def create(cls, bc: BattleContext, idx: int) -> "AcidSlimeS":
        hp = bc.rngs.monster_hp.int_inclusive(*cls.hp_range)
        return cls(idx, hp, hp)

    def get_move_for_roll(self, bc: BattleContext, roll: int) -> MoveDef:
        # A17 起固定 Lick；A0 为 50/50。roll 参数不参与（对齐 C++）
        return self.TACKLE if _ai_boolean(bc, 0.5) else self.LICK

    def take_turn(self, bc: BattleContext) -> None:
        move = self.move_history[0]
        match move.name:
            case "Lick":
                bc.log.append(f"{self.display_name} 使用 舔舐(Lick)。")
                bc.add_to_bot(Actions.debuff_player(PlayerStatus.WEAK, 1, True))
                self.set_move(self.TACKLE)  # 严格交替：下回合固定为另一招
            case "Tackle":
                dmg = bc.calculate_monster_damage(self, 3)
                bc.log.append(f"{self.display_name} 使用 冲撞(Tackle)。")
                bc.add_to_bot(Actions.attack_player(self.idx, dmg))
                self.set_move(self.LICK)
            case _:
                raise AssertionError(f"未知招式 {move}")
        self.turns_taken += 1


class SpikeSlimeS(Monster):
    """尖刺史莱姆（小）：只有 Tackle 5 伤，确定性出招。

    wiki/C++ A0：HP 10-14。getMoveForRoll 无条件返回 TACKLE（任务描述
    中的 Lick 属于 M/L 型，小尖刺没有）。take_turn 不切招、不 roll，
    仅入队 NoOpRollMove 占位（对齐 lightspeed 的 RNG 消耗语义）。
    """

    name = "Spike Slime (S)"
    zh = "尖刺史莱姆（小）"
    hp_range = (10, 14)

    TACKLE = MoveDef("Tackle", "冲撞", "attack", base_damage=5)

    def __init__(self, idx: int, hp: int, max_hp: int):
        super().__init__(idx, hp, max_hp, "尖刺史莱姆（小）(Spike Slime (S))")

    @classmethod
    def create(cls, bc: BattleContext, idx: int) -> "SpikeSlimeS":
        hp = bc.rngs.monster_hp.int_inclusive(*cls.hp_range)
        return cls(idx, hp, hp)

    def get_move_for_roll(self, bc: BattleContext, roll: int) -> MoveDef:
        return self.TACKLE

    def take_turn(self, bc: BattleContext) -> None:
        dmg = bc.calculate_monster_damage(self, 5)
        bc.log.append(f"{self.display_name} 使用 冲撞(Tackle)。")
        bc.add_to_bot(Actions.attack_player(self.idx, dmg))
        bc.add_to_bot(Actions.no_op_roll_move())
        self.turns_taken += 1


class FungiBeast(Monster):
    """真菌兽：Bite 6 伤 / Grow 力量+3；死亡时孢子云（2 层易伤）。

    wiki/C++ A0：HP 22-28。roll 分段：
      roll < 60：Bite 已连续两回合 → Grow，否则 Bite
      roll ≥ 60：上回合 Grow → Bite，否则 Grow
    孢子云（对齐 C++ preBattleAction 的 buff<SPORE_CLOUD>(2) 与 die 的
    SPORE_CLOUD 分支）：死亡时给玩家 2 层易伤，结算钩子在
    entities.Monster.die；最后一只死亡时战斗已结束，不再施加。
    """

    name = "Fungi Beast"
    zh = "真菌兽"
    hp_range = (22, 28)

    BITE = MoveDef("Bite", "撕咬", "attack", base_damage=6)
    GROW = MoveDef("Grow", "生长", "buff", intent_text="力量+3")

    def __init__(self, idx: int, hp: int, max_hp: int):
        super().__init__(idx, hp, max_hp, "真菌兽(Fungi Beast)")
        # 对齐 C++ preBattleAction：SporeCloudPower 恒为 2
        self.statuses.add(MonsterStatus.SPORE_CLOUD, 2)

    @classmethod
    def create(cls, bc: BattleContext, idx: int) -> "FungiBeast":
        hp = bc.rngs.monster_hp.int_inclusive(*cls.hp_range)
        return cls(idx, hp, hp)

    def get_move_for_roll(self, bc: BattleContext, roll: int) -> MoveDef:
        if roll < 60:
            if _last_two(self, "Bite"):
                return self.GROW
            return self.BITE
        if _last(self, "Grow"):
            return self.BITE
        return self.GROW

    def take_turn(self, bc: BattleContext) -> None:
        move = self.move_history[0]
        match move.name:
            case "Bite":
                dmg = bc.calculate_monster_damage(self, 6)
                bc.log.append(f"{self.display_name} 使用 撕咬(Bite)。")
                bc.add_to_bot(Actions.attack_player(self.idx, dmg))
            case "Grow":
                self.statuses.add(MonsterStatus.STRENGTH, 3)
                bc.log.append(f"{self.display_name} 使用 生长(Grow)，力量+3。")
            case _:
                raise AssertionError(f"未知招式 {move}")
        bc.add_to_bot(Actions.roll_move(self.idx))
        self.turns_taken += 1

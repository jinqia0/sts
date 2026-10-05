"""Act 1 怪物定义（对齐 lightspeed src/combat/MonsterSpecific.cpp）。

每个怪 = Monster 子类：
- hp_range：HP 均匀抽样区间（monster_hp 流；A0 基准）
- create(bc, idx)：构造（HP roll + 构造期 roll，如虱子的 Bite 伤害/Curl Up）
- get_move_for_roll：意图选择（ai 流 0..99 roll 分段 + 部分怪的内层布尔抽样，
  分段区间与内层概率逐行对齐 C++ getMoveForRoll）
- take_turn：按当前意图把动作入队 + 回合末 roll_move 生成下回合意图

意图可见性遵守 DESIGN.md §4.2：意图在怪物回合结束时才生成，
观测中物理上不存在未来值。

已移植：Cultist、Jaw Worm、Red/Green Louse、Acid/Spike Slime (S)、Fungi Beast、
Acid/Spike Slime (M)、Blue/Red Slaver、Sneaky/Fat/Shield Gremlin、Gremlin Wizard、
Sentry。A0 数值直取（`ascN ? x : y` 的 y），但伤害/状态量的进阶分支保留
（读 bc.ascension，A0 时自动落回非进阶值）。

源码与任务描述/wiki 的出入（以 C++ 为准）：
- Red Louse 的副招是 Grow（力量+3），不是 Spit Web；Green Louse 才是
  Spit Web，且施加 2 层虚弱（DebuffPlayer<PS::WEAK>(2)）而非 3 层。
- Acid Slime (S) 的招式是 Lick（1 层虚弱）/ Tackle（3 伤）交替，
  没有 Corrosive Spit（那是 M/L 型的招式），因此不需要 Slimed 临时卡。
- Spike Slime (S) 只有 Tackle（5 伤），确定性出招（无 Lick）。
- Jaw Worm Thrash 为 7 伤 + 5 格挡（非 8 伤 + 3 格挡）。
- Spike Slime (M) 的 Lick 施加 FRAIL（脆弱）1 层而非 WEAK（C++ 源码
  DebuffPlayer<PS::FRAIL>(1)，默认 isSourceMonster=true）。
- Gremlin Wizard 充能无伤害（C++ CHARGING 只 ++miscInfo），充能计数
  挂 misc_info：开局 roll 时置 1，第 3 点切终极冲击；A0 冲击后清零重充
  （首轮充 2 回合，此后充 3 回合），A17 起不再重充（无限连发）。
- Red Slaver 的 usedEntangle（misc_info）：本体/wiki 为"整场一次"，
  但 lightspeed 从不置位（疑似漏写，会导致重复缠绕）——此处按本体
  语义在 Entangle 落地时置 1。
- Gremlin 帮第 3 回合逃跑（Fat/Sneaky 等）：lightspeed 的
  doesEscapeNext 为死代码，本批不实现（留批次 3 决策）。
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

from sts.combat.actions import Actions
from sts.combat.entities import Monster
from sts.combat.queue import Action
from sts.combat.types import MonsterStatus, PlayerStatus
from sts.content.cards import DAZED, SLIMED

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


# ====================================================================
# 批次 1：简单档 Act 1 怪物（Acid/Spike Slime M、Blue/Red Slaver、
# Gremlin ×4、Sentry）。数值/分段逐行对齐 MonsterSpecific.cpp，wiki 交叉校验。
# ====================================================================


def _roll_hp(bc: BattleContext, cls: type[Monster]) -> int:
    """HP 抽样（对齐 C++ initHp/setRandomHp：进阶 7 起用高位区间，Sentry 为 8）。"""
    if bc.ascension >= getattr(cls, "hp_high_asc", 7):
        return bc.rngs.monster_hp.int_inclusive(*cls.hp_range_high)
    return bc.rngs.monster_hp.int_inclusive(*cls.hp_range)


class AcidSlimeM(Monster):
    """酸液史莱姆（中）：Corrosive Spit 7 伤 + 塞 1 张黏液 / Lick 1 层虚弱 / Tackle 10 伤。

    wiki/C++ A0：HP 28-32（A7 起 29-34）。roll 分段（A0）：
      roll < 30：Corrosive Spit 已连续两回合 → 内层 50% Tackle / 50% Lick；
                 否则 Corrosive Spit
      roll < 70：上回合 Tackle → 内层 40% Corrosive Spit / 否则 Lick；
                 否则 Tackle
      roll ≥ 70：Lick 已连续两回合 → 内层 40% Corrosive Spit / 否则 Tackle；
                 否则 Lick
    A17 起分段改为 40/80 + lastMove(Lick)（对齐 C++ START ASCENSION 17 段）。
    """

    name = "Acid Slime (M)"
    zh = "酸液史莱姆（中）"
    hp_range = (28, 32)
    hp_range_high = (29, 34)

    CORROSIVE_SPIT = MoveDef("Corrosive Spit", "腐蚀唾液", "attack", base_damage=7)
    LICK = MoveDef("Lick", "舔舐", "debuff", intent_text="施加 1 层虚弱")
    TACKLE = MoveDef("Tackle", "冲撞", "attack", base_damage=10)

    def __init__(self, idx: int, hp: int, max_hp: int):
        super().__init__(idx, hp, max_hp, "酸液史莱姆（中）(Acid Slime (M))")

    @classmethod
    def create(cls, bc: BattleContext, idx: int) -> "AcidSlimeM":
        hp = _roll_hp(bc, cls)
        return cls(idx, hp, hp)

    def get_move_for_roll(self, bc: BattleContext, roll: int) -> MoveDef:
        if bc.ascension >= 17:
            # A17：40/80 分段，末段判 lastMove(Lick)
            if roll < 40:
                if _last_two(self, "Corrosive Spit"):
                    return self.TACKLE if _ai_boolean(bc, 0.5) else self.LICK
                return self.CORROSIVE_SPIT
            if roll < 80:
                if _last_two(self, "Tackle"):
                    return self.CORROSIVE_SPIT if _ai_boolean(bc, 0.5) else self.LICK
                return self.TACKLE
            if _last(self, "Lick"):
                return self.CORROSIVE_SPIT if _ai_boolean(bc, 0.4) else self.TACKLE
            return self.LICK
        if roll < 30:
            if _last_two(self, "Corrosive Spit"):
                return self.TACKLE if _ai_boolean(bc, 0.5) else self.LICK
            return self.CORROSIVE_SPIT
        if roll < 70:
            if _last(self, "Tackle"):
                return self.CORROSIVE_SPIT if _ai_boolean(bc, 0.4) else self.LICK
            return self.TACKLE
        if _last_two(self, "Lick"):
            return self.CORROSIVE_SPIT if _ai_boolean(bc, 0.4) else self.TACKLE
        return self.LICK

    def take_turn(self, bc: BattleContext) -> None:
        move = self.move_history[0]
        match move.name:
            case "Corrosive Spit":
                dmg = bc.calculate_monster_damage(self, 8 if bc.ascension >= 2 else 7)
                bc.log.append(f"{self.display_name} 使用 腐蚀唾液(Corrosive Spit)。")
                bc.add_to_bot(Actions.attack_player(self.idx, dmg))
                bc.add_to_bot(Actions.make_temp_card_in_discard(SLIMED))
            case "Lick":
                bc.log.append(f"{self.display_name} 使用 舔舐(Lick)。")
                bc.add_to_bot(Actions.debuff_player(PlayerStatus.WEAK, 1, True))
            case "Tackle":
                dmg = bc.calculate_monster_damage(self, 12 if bc.ascension >= 2 else 10)
                bc.log.append(f"{self.display_name} 使用 冲撞(Tackle)。")
                bc.add_to_bot(Actions.attack_player(self.idx, dmg))
            case _:
                raise AssertionError(f"未知招式 {move}")
        bc.add_to_bot(Actions.roll_move(self.idx))
        self.turns_taken += 1


class SpikeSlimeM(Monster):
    """尖刺史莱姆（中）：Lick 1 层脆弱 / Flame Tackle 8 伤 + 塞 1 张黏液。

    wiki/C++ A0：HP 28-32（A7 起 29-34）。注意 Lick 施加的是 FRAIL
    （C++ DebuffPlayer<PS::FRAIL>(1)，默认 isSourceMonster=true），
    不是 WEAK。roll 分段（A0）：
      roll < 30：Flame Tackle 已连续两回合 → Lick；否则 Flame Tackle
      roll ≥ 30：Lick 已连续两回合（A17 起上回合即算）→ Flame Tackle；
                 否则 Lick
    """

    name = "Spike Slime (M)"
    zh = "尖刺史莱姆（中）"
    hp_range = (28, 32)
    hp_range_high = (29, 34)

    LICK = MoveDef("Lick", "舔舐", "debuff", intent_text="施加 1 层脆弱")
    FLAME_TACKLE = MoveDef("Flame Tackle", "烈焰冲撞", "attack", base_damage=8)

    def __init__(self, idx: int, hp: int, max_hp: int):
        super().__init__(idx, hp, max_hp, "尖刺史莱姆（中）(Spike Slime (M))")

    @classmethod
    def create(cls, bc: BattleContext, idx: int) -> "SpikeSlimeM":
        hp = _roll_hp(bc, cls)
        return cls(idx, hp, hp)

    def get_move_for_roll(self, bc: BattleContext, roll: int) -> MoveDef:
        if roll < 30:
            if _last_two(self, "Flame Tackle"):
                return self.LICK
            return self.FLAME_TACKLE
        if _last_two(self, "Lick") or (bc.ascension >= 17 and _last(self, "Lick")):
            return self.FLAME_TACKLE
        return self.LICK

    def take_turn(self, bc: BattleContext) -> None:
        move = self.move_history[0]
        match move.name:
            case "Lick":
                bc.log.append(f"{self.display_name} 使用 舔舐(Lick)。")
                bc.add_to_bot(Actions.debuff_player(PlayerStatus.FRAIL, 1, True))
            case "Flame Tackle":
                dmg = bc.calculate_monster_damage(self, 10 if bc.ascension >= 2 else 8)
                bc.log.append(f"{self.display_name} 使用 烈焰冲撞(Flame Tackle)。")
                bc.add_to_bot(Actions.attack_player(self.idx, dmg))
                bc.add_to_bot(Actions.make_temp_card_in_discard(SLIMED))
            case _:
                raise AssertionError(f"未知招式 {move}")
        bc.add_to_bot(Actions.roll_move(self.idx))
        self.turns_taken += 1


class BlueSlaver(Monster):
    """蓝奴役者：Stab 12 伤 / Rake 7 伤 + 1 层虚弱（A17 起 2 层）。

    wiki/C++ A0：HP 46-50（A7 起 48-52）。roll 分段（无首回合特例）：
      roll ≥ 40 且 Stab 未连续两回合 → Stab
      否则 Rake 未连续两回合（A17 起上回合出过 Rake 即算）→ Rake
      否则 Stab
    """

    name = "Blue Slaver"
    zh = "蓝奴役者"
    hp_range = (46, 50)
    hp_range_high = (48, 52)

    STAB = MoveDef("Stab", "刺击", "attack", base_damage=12)
    RAKE = MoveDef("Rake", "耙击", "attack", base_damage=7)  # 另施加 1 层虚弱

    def __init__(self, idx: int, hp: int, max_hp: int):
        super().__init__(idx, hp, max_hp, "蓝奴役者(Blue Slaver)")

    @classmethod
    def create(cls, bc: BattleContext, idx: int) -> "BlueSlaver":
        hp = _roll_hp(bc, cls)
        return cls(idx, hp, hp)

    def get_move_for_roll(self, bc: BattleContext, roll: int) -> MoveDef:
        if roll >= 40 and not _last_two(self, "Stab"):
            return self.STAB
        if not _last_two(self, "Rake") or (bc.ascension >= 17 and not _last(self, "Rake")):
            return self.RAKE
        return self.STAB

    def take_turn(self, bc: BattleContext) -> None:
        move = self.move_history[0]
        match move.name:
            case "Stab":
                dmg = bc.calculate_monster_damage(self, 13 if bc.ascension >= 2 else 12)
                bc.log.append(f"{self.display_name} 使用 刺击(Stab)。")
                bc.add_to_bot(Actions.attack_player(self.idx, dmg))
            case "Rake":
                dmg = bc.calculate_monster_damage(self, 8 if bc.ascension >= 2 else 7)
                bc.log.append(f"{self.display_name} 使用 耙击(Rake)。")
                bc.add_to_bot(Actions.attack_player(self.idx, dmg))
                bc.add_to_bot(Actions.debuff_player(PlayerStatus.WEAK, 2 if bc.ascension >= 17 else 1, True))
            case _:
                raise AssertionError(f"未知招式 {move}")
        bc.add_to_bot(Actions.roll_move(self.idx))
        self.turns_taken += 1


class RedSlaver(Monster):
    """红奴役者：Stab 13 伤 / Scrape 8 伤 + 1 层易伤 / Entangle 缠绕。

    wiki/C++ A0：HP 46-50（A7 起 48-52）。首招固定 Stab（lastMove(INVALID)）。
    roll 分段：
      roll ≥ 75 且未用过 Entangle → Entangle（misc_info 记录，整场一次）
      roll ≥ 50 且已用过 Entangle 且 Stab 未连续两回合 → Stab
      Scrape 未连续两回合（A17 起上回合出过即算）→ Scrape
      否则 Stab
    注：lightspeed 从不置位 usedEntangle（可重复缠绕，疑漏写）；
    此处按本体"整场一次"语义在 Entangle 落地时置 misc_info=1。
    """

    name = "Red Slaver"
    zh = "红奴役者"
    hp_range = (46, 50)
    hp_range_high = (48, 52)

    STAB = MoveDef("Stab", "刺击", "attack", base_damage=13)
    ENTANGLE = MoveDef("Entangle", "缠绕", "debuff", intent_text="施加 1 层缠绕")
    SCRAPE = MoveDef("Scrape", "刮擦", "attack", base_damage=8)  # 另施加 1 层易伤

    def __init__(self, idx: int, hp: int, max_hp: int):
        super().__init__(idx, hp, max_hp, "红奴役者(Red Slaver)")

    @classmethod
    def create(cls, bc: BattleContext, idx: int) -> "RedSlaver":
        hp = _roll_hp(bc, cls)
        return cls(idx, hp, hp)

    def get_move_for_roll(self, bc: BattleContext, roll: int) -> MoveDef:
        used_entangle = self.misc_info == 1
        if not self.move_history:  # lastMove(INVALID)：首招固定 Stab
            return self.STAB
        if roll >= 75 and not used_entangle:
            return self.ENTANGLE
        if roll >= 50 and used_entangle and not _last_two(self, "Stab"):
            return self.STAB
        if not _last_two(self, "Scrape") or (bc.ascension >= 17 and not _last(self, "Scrape")):
            return self.SCRAPE
        return self.STAB

    def take_turn(self, bc: BattleContext) -> None:
        move = self.move_history[0]
        match move.name:
            case "Stab":
                dmg = bc.calculate_monster_damage(self, 14 if bc.ascension >= 2 else 13)
                bc.log.append(f"{self.display_name} 使用 刺击(Stab)。")
                bc.add_to_bot(Actions.attack_player(self.idx, dmg))
            case "Entangle":
                bc.log.append(f"{self.display_name} 使用 缠绕(Entangle)。")
                bc.add_to_bot(Actions.debuff_player(PlayerStatus.ENTANGLED, 1, True))
                self.misc_info = 1  # 已用过（本体语义；lightspeed 漏写，见类注释）
            case "Scrape":
                dmg = bc.calculate_monster_damage(self, 9 if bc.ascension >= 2 else 8)
                bc.log.append(f"{self.display_name} 使用 刮擦(Scrape)。")
                bc.add_to_bot(Actions.attack_player(self.idx, dmg))
                bc.add_to_bot(Actions.debuff_player(PlayerStatus.VULNERABLE, 2 if bc.ascension >= 17 else 1, True))
            case _:
                raise AssertionError(f"未知招式 {move}")
        bc.add_to_bot(Actions.roll_move(self.idx))
        self.turns_taken += 1


class SneakyGremlin(Monster):
    """狡诈小鬼：固定 Puncture 9 伤，无 roll（getMoveForRoll 无条件返回）。

    wiki/C++ A0：HP 10-14（A7 起 11-15）。take_turn 尾部无 RollMove/
    NoOpRollMove（逃跑分支死代码外无入队），意图恒为 Puncture。
    """

    name = "Sneaky Gremlin"
    zh = "狡诈小鬼"
    hp_range = (10, 14)
    hp_range_high = (11, 15)

    PUNCTURE = MoveDef("Puncture", "穿刺", "attack", base_damage=9)

    def __init__(self, idx: int, hp: int, max_hp: int):
        super().__init__(idx, hp, max_hp, "狡诈小鬼(Sneaky Gremlin)")

    @classmethod
    def create(cls, bc: BattleContext, idx: int) -> "SneakyGremlin":
        hp = _roll_hp(bc, cls)
        return cls(idx, hp, hp)

    def get_move_for_roll(self, bc: BattleContext, roll: int) -> MoveDef:
        return self.PUNCTURE

    def take_turn(self, bc: BattleContext) -> None:
        dmg = bc.calculate_monster_damage(self, 10 if bc.ascension >= 2 else 9)
        bc.log.append(f"{self.display_name} 使用 穿刺(Puncture)。")
        bc.add_to_bot(Actions.attack_player(self.idx, dmg))
        # 对齐 C++：无 RollMove 入队（第 3 回合逃跑分支为死代码，不实现），
        # 意图保持 Puncture 不变
        self.turns_taken += 1


class FatGremlin(Monster):
    """肥硕小鬼：固定 Smash 4 伤 + 1 层虚弱（A17 起另加 1 层脆弱）。

    wiki/C++ A0：HP 13-17（A7 起 14-18）。take_turn 尾部 NoOpRollMove
    （逃跑分支死代码走 else），意图恒为 Smash。
    """

    name = "Fat Gremlin"
    zh = "肥硕小鬼"
    hp_range = (13, 17)
    hp_range_high = (14, 18)

    SMASH = MoveDef("Smash", "重击", "attack", base_damage=4)  # 另施加 1 层虚弱

    def __init__(self, idx: int, hp: int, max_hp: int):
        super().__init__(idx, hp, max_hp, "肥硕小鬼(Fat Gremlin)")

    @classmethod
    def create(cls, bc: BattleContext, idx: int) -> "FatGremlin":
        hp = _roll_hp(bc, cls)
        return cls(idx, hp, hp)

    def get_move_for_roll(self, bc: BattleContext, roll: int) -> MoveDef:
        return self.SMASH

    def take_turn(self, bc: BattleContext) -> None:
        dmg = bc.calculate_monster_damage(self, 5 if bc.ascension >= 2 else 4)
        bc.log.append(f"{self.display_name} 使用 重击(Smash)。")
        bc.add_to_bot(Actions.attack_player(self.idx, dmg))
        bc.add_to_bot(Actions.debuff_player(PlayerStatus.WEAK, 1, True))
        if bc.ascension >= 17:
            bc.add_to_bot(Actions.debuff_player(PlayerStatus.FRAIL, 1, True))
        # 对齐 C++：逃跑分支死代码 → NoOpRollMove 占位，意图保持 Smash
        bc.add_to_bot(Actions.no_op_roll_move())
        self.turns_taken += 1


class ShieldGremlin(Monster):
    """盾牌小鬼：Protect 为随机存活友军 +7 格挡（A7 起 8 / A17 起 11）。

    wiki/C++ A0：HP 12-15（A7 起 13-17）。getMoveForRoll 恒返回 PROTECT。
    take_turn：入队给随机友军的格挡动作后，若存活数 ≤ 1 则切换
    Shield Bash（6 伤，A2 起 8），此后不再切回（无 roll 入队）。
    随机目标：C++ GainBlockRandomEnemy 用 aiRng 且只排除已死怪；
    本项目按惯例用 misc 流、排除已死/已逃跑（分布级等价，见 DESIGN.md §3）。
    """

    name = "Shield Gremlin"
    zh = "盾牌小鬼"
    hp_range = (12, 15)
    hp_range_high = (13, 17)

    PROTECT = MoveDef("Protect", "防护", "defend", intent_text="为随机存活友军提供格挡")
    SHIELD_BASH = MoveDef("Shield Bash", "盾击", "attack", base_damage=6)

    def __init__(self, idx: int, hp: int, max_hp: int):
        super().__init__(idx, hp, max_hp, "盾牌小鬼(Shield Gremlin)")

    @classmethod
    def create(cls, bc: BattleContext, idx: int) -> "ShieldGremlin":
        hp = _roll_hp(bc, cls)
        return cls(idx, hp, hp)

    @staticmethod
    def _protect_amount(bc: BattleContext) -> int:
        # 对齐 C++ blockAmounts[getTriIdx(asc, 7, 17)]
        if bc.ascension >= 17:
            return 11
        if bc.ascension >= 7:
            return 8
        return 7

    def _gain_block_random_ally(self, amount: int) -> Action:
        def run(bcb: BattleContext) -> None:
            allies = [
                m.idx
                for m in bcb.monsters.monsters
                if m.idx != self.idx and not m.is_dead_or_escaped()
            ]
            target = allies[bcb.rngs.misc.int_inclusive(0, len(allies) - 1)] if allies else self.idx
            Actions.monster_gain_block(target, amount).fn(bcb)

        return Action(run)

    def get_move_for_roll(self, bc: BattleContext, roll: int) -> MoveDef:
        return self.PROTECT

    def take_turn(self, bc: BattleContext) -> None:
        move = self.move_history[0]
        match move.name:
            case "Protect":
                bc.log.append(f"{self.display_name} 使用 防护(Protect)。")
                bc.add_to_bot(self._gain_block_random_ally(self._protect_amount(bc)))
                if bc.monsters.alive_count <= 1:
                    self.set_move(self.SHIELD_BASH)
            case "Shield Bash":
                dmg = bc.calculate_monster_damage(self, 8 if bc.ascension >= 2 else 6)
                bc.log.append(f"{self.display_name} 使用 盾击(Shield Bash)。")
                bc.add_to_bot(Actions.attack_player(self.idx, dmg))
            case _:
                raise AssertionError(f"未知招式 {move}")
        # 对齐 C++：两分支均无 RollMove 入队，意图不经 roll 更新
        self.turns_taken += 1


class GremlinWizard(Monster):
    """小鬼法师：充能（计数挂 misc_info）→ 终极冲击 25 伤，循环。

    wiki/C++ A0：HP 21-25（A7 起 22-26）。开局 roll 时 misc_info 置 1
    （C++ getMoveForRoll 的 monsterData = 1）；每次充能回合 +1，到 3 切
    终极冲击。A0 冲击后清零重充（首轮充 2 回合，此后每轮充 3 回合）；
    A17 起不重充（此后每回合都是终极冲击）。全程无 RollMove 入队。
    充能回合无任何动作（C++ CHARGING 分支只 ++miscInfo）。
    """

    name = "Gremlin Wizard"
    zh = "小鬼法师"
    hp_range = (21, 25)
    hp_range_high = (22, 26)

    CHARGING = MoveDef("Charging", "充能", "unknown", intent_text="正在充能（无动作）")
    ULTIMATE_BLAST = MoveDef("Ultimate Blast", "终极冲击", "attack", base_damage=25)

    def __init__(self, idx: int, hp: int, max_hp: int):
        super().__init__(idx, hp, max_hp, "小鬼法师(Gremlin Wizard)")

    @classmethod
    def create(cls, bc: BattleContext, idx: int) -> "GremlinWizard":
        hp = _roll_hp(bc, cls)
        return cls(idx, hp, hp)

    def get_move_for_roll(self, bc: BattleContext, roll: int) -> MoveDef:
        self.misc_info = 1  # 对齐 C++ monsterData = 1（充能计数起点）
        return self.CHARGING

    def take_turn(self, bc: BattleContext) -> None:
        move = self.move_history[0]
        match move.name:
            case "Charging":
                self.misc_info += 1
                bc.log.append(f"{self.display_name} 正在充能……")
                if self.misc_info == 3:
                    self.set_move(self.ULTIMATE_BLAST)
            case "Ultimate Blast":
                dmg = bc.calculate_monster_damage(self, 30 if bc.ascension >= 2 else 25)
                bc.log.append(f"{self.display_name} 使用 终极冲击(Ultimate Blast)！")
                bc.add_to_bot(Actions.attack_player(self.idx, dmg))
                if bc.ascension < 17:
                    self.misc_info = 0
                    self.set_move(self.CHARGING)
            case _:
                raise AssertionError(f"未知招式 {move}")
        self.turns_taken += 1


class Sentry(Monster):
    """哨卫：Beam 9 伤 / Bolt 塞 2 张眩晕进弃牌堆，严格交替；开局 1 层人工制品。

    wiki/C++ A0：HP 38-42（A8 起 39-45）。首招由奇偶槽位决定：
    firstTurn 时 idx%2==0 先 Bolt、否则先 Beam；此后 take_turn 用
    set_move 交替（无 roll，NoOpRollMove 占位）。Bolt 塞 2 张 DAZED
    （A18 起 3 张）进弃牌堆；Beam 9 伤（A3 起 10）。
    人工制品（ARTIFACT 1）在构造期置位，对齐 C++ preBattleAction。
    """

    name = "Sentry"
    zh = "哨卫"
    hp_range = (38, 42)
    hp_range_high = (39, 45)
    hp_high_asc = 8  # 对齐 C++ initHp：Sentry 的高位 HP 区间从 A8 起

    BEAM = MoveDef("Beam", "光束", "attack", base_damage=9)
    BOLT = MoveDef("Bolt", "闪击", "debuff", intent_text="塞 2 张眩晕进弃牌堆")

    def __init__(self, idx: int, hp: int, max_hp: int):
        super().__init__(idx, hp, max_hp, "哨卫(Sentry)")
        # 对齐 C++ preBattleAction：开局 1 层人工制品
        self.statuses.add(MonsterStatus.ARTIFACT, 1)

    @classmethod
    def create(cls, bc: BattleContext, idx: int) -> "Sentry":
        hp = _roll_hp(bc, cls)
        return cls(idx, hp, hp)

    def get_move_for_roll(self, bc: BattleContext, roll: int) -> MoveDef:
        # 对齐 C++ firstTurn()（moveHistory[0] == INVALID）+ idx 奇偶分支
        if not self.move_history:
            return self.BOLT if self.idx % 2 == 0 else self.BEAM
        # 首回合后不经 roll（take_turn 用 set_move 交替），此处仅兜底
        return self.move_history[0]

    def take_turn(self, bc: BattleContext) -> None:
        move = self.move_history[0]
        match move.name:
            case "Beam":
                dmg = bc.calculate_monster_damage(self, 10 if bc.ascension >= 3 else 9)
                bc.log.append(f"{self.display_name} 使用 光束(Beam)。")
                bc.add_to_bot(Actions.attack_player(self.idx, dmg))
                self.set_move(self.BOLT)
                bc.add_to_bot(Actions.no_op_roll_move())
            case "Bolt":
                n = 3 if bc.ascension >= 18 else 2
                bc.log.append(f"{self.display_name} 使用 闪击(Bolt)，塞 {n} 张眩晕进弃牌堆。")
                for _ in range(n):
                    bc.add_to_bot(Actions.make_temp_card_in_discard(DAZED))
                self.set_move(self.BEAM)
                bc.add_to_bot(Actions.no_op_roll_move())
            case _:
                raise AssertionError(f"未知招式 {move}")
        self.turns_taken += 1

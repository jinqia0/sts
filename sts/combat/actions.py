"""原子动作工厂（对齐 lightspeed src/combat/Actions.cpp，范围裁剪）。

每个工厂返回 Action（闭包）。卡牌/怪物动作体（useAttackCard 的
switch、MonsterSpecific 的 takeTurn）在内容层调用这些工厂把效果
分解为原子动作序列压入队列——结算顺序由此处的入队顺序唯一决定。

未移植（无来源或依赖局外系统）：遗物触发、药水、选卡界面、
stance/orb（铁甲战士无）。临时卡生成（Anger/Wild Strike）以最小
形态引入：战斗内与普通实例无异，不追踪战斗结束回收。
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from sts.combat.queue import Action
from sts.combat.types import InputState, MonsterStatus

if TYPE_CHECKING:
    from sts.combat.battle import BattleContext
    from sts.combat.types import IntEnum
    from sts.content.cards import CardDef


class Actions:
    @staticmethod
    def set_state(state: InputState) -> Action:
        return Action(lambda bc: bc.set_state(state), clear_on_victory=False)

    @staticmethod
    def attack_enemy(idx: int, damage: int) -> Action:
        def run(bc: BattleContext) -> None:
            m = bc.monsters.monsters[idx]
            if not m.is_dead_or_escaped():
                m.attacked(bc, damage)
                bc.check_combat()

        return Action(run)

    @staticmethod
    def attack_all_enemy(base_damage: int) -> Action:
        def run(bc: BattleContext) -> None:
            for m in bc.monsters.monsters:
                if not m.is_dead_or_escaped():
                    m.attacked(bc, bc.calculate_card_damage(bc.cur_card_queue_item, m.idx, base_damage))
            bc.check_combat()

        return Action(run)

    @staticmethod
    def damage_enemy(idx: int, damage: int) -> Action:
        def run(bc: BattleContext) -> None:
            m = bc.monsters.monsters[idx]
            if not m.is_dead_or_escaped():
                m.damage(bc, damage)
                bc.check_combat()

        return Action(run)

    @staticmethod
    def attack_player(enemy_idx: int, damage: int) -> Action:
        def run(bc: BattleContext) -> None:
            bc.player.attacked(bc, enemy_idx, damage)

        return Action(run)

    @staticmethod
    def damage_player(damage: int) -> Action:
        def run(bc: BattleContext) -> None:
            bc.player.damage(bc, damage)

        return Action(run)

    @staticmethod
    def player_lose_hp(hp: int) -> Action:
        def run(bc: BattleContext) -> None:
            bc.player.lose_hp(bc, hp)

        return Action(run)

    @staticmethod
    def heal_player(amount: int) -> Action:
        return Action(lambda bc: bc.player.heal(amount))

    @staticmethod
    def monster_gain_block(idx: int, amount: int) -> Action:
        def run(bc: BattleContext) -> None:
            m = bc.monsters.monsters[idx]
            if not m.is_dead_or_escaped():
                m.block += amount

        return Action(run)

    @staticmethod
    def roll_move(monster_idx: int) -> Action:
        def run(bc: BattleContext) -> None:
            bc.monsters.monsters[monster_idx].roll_move(bc)

        return Action(run)

    @staticmethod
    def no_op_roll_move() -> Action:
        """空转一次 aiRng（对齐 lightspeed noOpRollMove：修正与本体
        RNG 消耗次数的差异）。本项目不做轨迹对齐，保留为占位语义。"""
        return Action(lambda bc: None)

    @staticmethod
    def gain_energy(amount: int) -> Action:
        return Action(lambda bc: setattr(bc.player, "energy", bc.player.energy + amount))

    @staticmethod
    def gain_block(amount: int) -> Action:
        return Action(lambda bc: setattr(bc.player, "block", bc.player.block + amount))

    @staticmethod
    def draw_cards(amount: int) -> Action:
        return Action(lambda bc: bc.draw_cards(amount))

    @staticmethod
    def empty_deck_shuffle() -> Action:
        return Action(lambda bc: bc.on_shuffle())

    # ---- 状态增减（模板的 Python 化：状态作为参数而非模板实参）----
    @staticmethod
    def buff_player(status: IntEnum, amount: int) -> Action:
        return Action(lambda bc: bc.player.statuses.add(status, amount))

    @staticmethod
    def debuff_player(status: IntEnum, amount: int, is_source_monster: bool) -> Action:
        def run(bc: BattleContext) -> None:
            bc.player.statuses.add(status, amount)
            if is_source_monster and status.name in ("WEAK", "VULNERABLE", "FRAIL"):
                bc.player.statuses.set_just_applied(status, True)

        return Action(run)

    @staticmethod
    def buff_enemy(idx: int, status: IntEnum, amount: int) -> Action:
        def run(bc: BattleContext) -> None:
            m = bc.monsters.monsters[idx]
            if not m.is_dead_or_escaped():
                m.statuses.add(status, amount)

        return Action(run)

    @staticmethod
    def debuff_enemy(idx: int, status: IntEnum, amount: int, is_source_monster: bool = False) -> Action:
        def run(bc: BattleContext) -> None:
            m = bc.monsters.monsters[idx]
            if m.is_dead_or_escaped():
                return
            if m.statuses.has(MonsterStatus.ARTIFACT):  # 对齐 debuffEnemy：消耗一层抵消
                m.statuses.decrement(MonsterStatus.ARTIFACT)
                return
            m.statuses.add(status, amount)
            if is_source_monster and status.name in ("WEAK", "VULNERABLE"):
                m.statuses.set_just_applied(status, True)

        return Action(run)

    @staticmethod
    def debuff_all_enemy(status: IntEnum, amount: int, is_source_monster: bool = False) -> Action:
        """对全体敌人施加削弱（对齐 DebuffAllEnemy：逐怪过 ARTIFACT 抵消，
        按索引升序落地——lightspeed 用逆序 addToTop 达到同一净顺序）。"""

        def run(bc: BattleContext) -> None:
            for m in bc.monsters.monsters:
                if m.is_dead_or_escaped():
                    continue
                if m.statuses.has(MonsterStatus.ARTIFACT):
                    m.statuses.decrement(MonsterStatus.ARTIFACT)
                    continue
                m.statuses.add(status, amount)
                if is_source_monster and status.name in ("WEAK", "VULNERABLE"):
                    m.statuses.set_just_applied(status, True)

        return Action(run)

    @staticmethod
    def remove_player_status(status: IntEnum) -> Action:
        """移除玩家状态（对齐 RemoveStatus 动作：LOSE_STRENGTH / NO_DRAW 回合末清除）。"""
        return Action(lambda bc: bc.player.statuses.remove(status))

    # ---- 临时牌（对齐 MakeTempCardInDiscard / MakeTempCardInDrawPile）----
    @staticmethod
    def make_temp_card_in_discard(card: "CardDef", upgraded: bool = False) -> Action:
        """临时牌进弃牌堆（Anger）：战斗内与普通弃牌无异，可被洗回抽到。"""
        return Action(lambda bc: bc.cards.create_temp_card_in_discard(card, upgraded))

    @staticmethod
    def make_temp_card_in_draw_pile(card: "CardDef", upgraded: bool = False, shuffle_into: bool = True) -> Action:
        """临时牌进抽牌堆（Wild Strike 的伤口）。

        shuffle_into：插入随机位置。本体用 cardRandom 流，本项目用
        misc 流（DESIGN.md §3 不做轨迹对齐，分布级等价）。
        """

        def run(bc: BattleContext) -> None:
            if shuffle_into and bc.cards.draw_pile:
                idx = bc.rngs.misc.int_inclusive(0, len(bc.cards.draw_pile) - 1)
            else:
                idx = len(bc.cards.draw_pile)
            bc.cards.create_temp_card_in_draw_pile(card, idx, upgraded)

        return Action(run)

    # ---- 回合流转 ----
    @staticmethod
    def clear_card_queue() -> Action:
        return Action(lambda bc: bc.card_queue.clear(), clear_on_victory=False)

    @staticmethod
    def discard_at_end_of_turn() -> Action:
        return Action(lambda bc: bc.discard_at_end_of_turn_helper(), clear_on_victory=False)

    @staticmethod
    def unnamed_end_of_turn_action() -> Action:
        def run(bc: BattleContext) -> None:
            bc.turn_has_ended = True
            if not bc.skip_monster_turn:
                bc.add_to_bot(Actions.monster_start_turn_action())
                bc.monster_turn_idx = 0

        return Action(run, clear_on_victory=False)

    @staticmethod
    def monster_start_turn_action() -> Action:
        return Action(lambda bc: bc.monsters.apply_pre_turn_logic(bc), clear_on_victory=False)

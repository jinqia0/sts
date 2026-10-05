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

from sts.combat.queue import Action, CardQueueItem
from sts.combat.types import InputState, MonsterStatus, Orb, PlayerStatus, Stance

if TYPE_CHECKING:
    from sts.combat.battle import BattleContext
    from sts.combat.card_manager import CardInstance
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
    def damage_all_enemy(damage: int) -> Action:
        """对所有敌人非攻击 HP 损失（Combust/火息/Mercury Hourglass；不吃攻击管线）。"""

        def run(bc: BattleContext) -> None:
            for m in bc.monsters.monsters:
                if not m.is_dead_or_escaped():
                    m.damage(bc, damage)
            bc.check_combat()

        return Action(run)

    @staticmethod
    def damage_random_enemy(damage: int) -> Action:
        """随机存活敌人受非攻击 HP 损失（Juggernaut；misc 流）。"""

        def run(bc: BattleContext) -> None:
            alive = [m for m in bc.monsters.monsters if m.is_targetable()]
            if alive:
                m = alive[bc.rngs.misc.int_inclusive(0, len(alive) - 1)]
                m.damage(bc, damage)
                bc.check_combat()

        return Action(run)

    @staticmethod
    def attack_random_enemy(damage: int, count: int) -> Action:
        """随机目标多段攻击（Sword Boomerang；每段独立走攻击管线+随机目标）。"""

        def run(bc: BattleContext) -> None:
            for _ in range(count):
                alive = [m for m in bc.monsters.monsters if m.is_targetable()]
                if not alive:
                    return
                idx = alive[bc.rngs.misc.int_inclusive(0, len(alive) - 1)].idx
                m = bc.monsters.monsters[idx]
                dmg = bc.calculate_card_damage(bc.cur_card_queue_item, idx, damage)
                m.attacked(bc, dmg)
            bc.check_combat()

        return Action(run)

    @staticmethod
    def attack_player(enemy_idx: int, damage: int) -> Action:
        def run(bc: BattleContext) -> None:
            bc.player.attacked(bc, enemy_idx, damage)

        return Action(run)

    @staticmethod
    def damage_player(damage: int, self_inflicted: bool = False) -> Action:
        """非攻击 HP 损失（吃格挡）。self_inflicted：Burn/Decay 的回合末结算
        在 C++ 传 selfDamage=true（DamagePlayer 第二参，Actions.cpp:91-95），
        会触发 RUPTURE——对齐之。"""

        def run(bc: BattleContext) -> None:
            bc.player.damage(bc, damage, self_inflicted)

        return Action(run)

    @staticmethod
    def player_lose_hp(hp: int, self_inflicted: bool = False) -> Action:
        def run(bc: BattleContext) -> None:
            bc.player.lose_hp(bc, hp, self_inflicted=self_inflicted)

        return Action(run)

    @staticmethod
    def heal_player(amount: int) -> Action:
        return Action(lambda bc: bc.player.heal(amount, bc))

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
        # 统一走 Player.gain_block：NO_BLOCK 拦截 + Juggernaut 触发
        return Action(lambda bc: bc.player.gain_block(bc, amount))

    @staticmethod
    def exhaust_hand_card(inst: "CardInstance") -> Action:
        """把手中的指定实例送入消耗堆（True Grit/Second Wind 等；走统一消耗钩子）。"""

        def run(bc: BattleContext) -> None:
            try:
                bc.cards.hand.remove(inst)
            except ValueError:
                return
            bc.cards.move_to_exhaust_pile(inst)
            bc.on_card_exhausted(inst)

        return Action(run)

    @staticmethod
    def make_temp_card_in_hand(card: "CardDef", upgraded: bool = False) -> Action:
        return Action(lambda bc: bc.cards.create_temp_card_in_hand(card, upgraded))

    @staticmethod
    def steal_gold(idx: int, amount: int) -> Action:
        """怪物偷金（Looter）：玩家金币减少（至多偷到玩家现有的），存进 misc_info。"""

        def run(bc: BattleContext) -> None:
            m = bc.monsters.monsters[idx]
            stolen = min(amount, bc.player.gold)
            if stolen > 0:
                bc.player.gold -= stolen
                m.misc_info += stolen
                m.statuses.add(MonsterStatus.THIEVERY, 1)
                bc.log.append(f"{m.display_name} 偷走了 {stolen} 金币！")

        return Action(run)

    @staticmethod
    def monster_escape(idx: int) -> Action:
        def run(bc: BattleContext) -> None:
            m = bc.monsters.monsters[idx]
            if not m.is_dead_or_escaped():
                m.escape(bc)

        return Action(run)

    @staticmethod
    def discard_random_from_hand(count: int) -> Action:
        """随机弃置 N 张手牌（All-Out Attack/Unload 等；misc 流）。"""

        def run(bc: BattleContext) -> None:
            for _ in range(count):
                if not bc.cards.hand:
                    return
                idx = bc.rngs.misc.int_inclusive(0, len(bc.cards.hand) - 1)
                bc.manual_discard(bc.cards.hand[idx])

        return Action(run)

    @staticmethod
    def discard_chosen(count: int) -> Action:
        """选卡弃 N 张（Prepared/Acrobatics 等）：CARD_SELECT 必选（手牌
        不足 N 张时空手跳过——open_card_select 的 can_pick_zero 兜底）。"""

        def run(bc: BattleContext) -> None:
            cands = list(bc.cards.hand)
            if not cands:
                return

            def on_choose(bc2, chosen):
                for inst in chosen:
                    bc2.manual_discard(inst)

            bc.open_card_select(cands, on_choose, pick_count=count,
                                can_pick_zero=len(cands) < count, prompt=f"弃置 {count} 张")

        return Action(run)

    @staticmethod
    def discard_all_hand() -> Action:
        """弃置全部手牌（Calculated Gamble/Storm of Steel；每张走 manual_discard）。"""
        return Action(lambda bc: [bc.manual_discard(c) for c in list(bc.cards.hand)])

    @staticmethod
    def _time_eater_replay(item: CardQueueItem) -> Action:
        """TIME_WARP 提前回合：卡队列中被清出的自动播放项原样回放。"""

        def run(bc: BattleContext) -> None:
            bc.add_to_bot_card(item)

        return Action(run)

    @staticmethod
    def play_top_card(exhaust: bool) -> Action:
        """打出抽牌堆顶的牌（Havoc/Mayhem；对齐 PlayTopCard →
        playTopCardInDrawPile，BattleContext.cpp:2515-2530）：随机目标、
        免费（autoplay 项不收能量）、可指定打完消耗；抽牌堆空则先洗
        弃牌堆再重试。"""

        def run(bc: BattleContext) -> None:
            if not bc.cards.draw_pile:
                if not bc.cards.discard_pile:
                    return
                bc.add_to_top(Actions.play_top_card(exhaust))  # 后执行
                bc.add_to_top(Actions.empty_deck_shuffle())  # 先执行（洗牌）
                return
            inst = bc.cards.pop_from_draw_pile()
            item = CardQueueItem(card=inst, random_target=True, exhaust_on_use=exhaust, autoplay=True)
            bc.add_to_top_card(item)

        return Action(run)

    @staticmethod
    def draw_cards(amount: int) -> Action:
        return Action(lambda bc: bc.draw_cards(amount))

    @staticmethod
    def empty_deck_shuffle() -> Action:
        return Action(lambda bc: bc.on_shuffle())

    # ---- Defect 充能球 ----
    @staticmethod
    def channel_orb(orb: Orb) -> Action:
        return Action(lambda bc: bc.player.channel_orb(bc, orb))

    @staticmethod
    def evoke_orb() -> Action:
        return Action(lambda bc: bc.player.evoke_orb(bc))

    @staticmethod
    def evoke_all_orbs() -> Action:
        def run(bc: BattleContext) -> None:
            while bc.player.orbs:
                bc.player.evoke_orb(bc)

        return Action(run)

    @staticmethod
    def modify_orb_slots(delta: int) -> Action:
        return Action(lambda bc: setattr(bc.player, "orb_slots", max(0, bc.player.orb_slots + delta)))

    # ---- 观者姿态 ----
    @staticmethod
    def change_stance(new_stance: Stance) -> Action:
        """切换姿态（钩子链在 Player.change_stance）。"""
        return Action(lambda bc: bc.player.change_stance(bc, new_stance))

    @staticmethod
    def gain_mantra(n: int) -> Action:
        """真言 +N（满 10 进 DIVINITY；结算在 Player.gain_mantra）。"""
        return Action(lambda bc: bc.player.gain_mantra(bc, n))

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
            # SADISTIC：debuff 落地（非 ARTIFACT 抵消）触发（对齐 BattleContext.h:292-294；
            # lightspeed 状态定义有/触发段无——按 wiki 补）
            if bc.player.statuses.has(PlayerStatus.SADISTIC):
                bc.add_to_bot(
                    Actions.damage_enemy(idx, bc.player.statuses.get(PlayerStatus.SADISTIC)))

        return Action(run)

    @staticmethod
    def debuff_all_enemy(status: IntEnum, amount: int, is_source_monster: bool = False) -> Action:
        """对全体敌人施加削弱（对齐 DebuffAllEnemy：逐怪过 ARTIFACT 抵消，
        按索引升序落地——lightspeed 用逆序 addToTop 达到同一净顺序）。"""

        def run(bc: BattleContext) -> None:
            sadistic = bc.player.statuses.get(PlayerStatus.SADISTIC)
            for m in bc.monsters.monsters:
                if m.is_dead_or_escaped():
                    continue
                if m.statuses.has(MonsterStatus.ARTIFACT):
                    m.statuses.decrement(MonsterStatus.ARTIFACT)
                    continue
                m.statuses.add(status, amount)
                if is_source_monster and status.name in ("WEAK", "VULNERABLE"):
                    m.statuses.set_just_applied(status, True)
                if sadistic > 0:
                    bc.add_to_bot(Actions.damage_enemy(m.idx, sadistic))

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

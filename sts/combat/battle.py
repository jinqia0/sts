"""BattleContext：战斗状态 + 主推进循环（sts_lightspeed 架构移植）。

这是引擎的中枢。移植自 lightspeed src/combat/BattleContext.cpp 的
executeActions 主循环与回合生命周期，范围裁剪：无遗物/药水/选卡
界面/stance（铁甲战士无）。临时牌（Anger/Wild Strike）以战斗内
普通实例的最小形态支持。

主循环（execute_actions，对齐 lightspeed 顺序）：
    1. 弹 action_queue 逐个执行
    2. 弹 card_queue 逐张处理（出牌 / 结束回合哨兵）
    3. 敌方阶段：依次 do_monster_turn（take_turn 入队该怪动作）
    4. 全部怪行动完（turn_has_ended）→ after_monster_turns
    5. end_turn_queued → on_turn_ending（弃手牌、置敌方阶段起点）
    6. 回到 PLAYER_NORMAL，等玩家输入

回合生命周期（一次 end_turn 的完整链，对齐 lightspeed）：
    end_turn()                       入队结束回合哨兵
    → call_end_turn_actions()        回合末触发的状态/诅咒卡（范围内无）
    → on_turn_ending()               ClearCardQueue + 弃手牌 + UnnamedEndOfTurn
    → UnnamedEndOfTurnAction         turn_has_ended=True, 置 monster_turn_idx=0,
                                     入队 MonsterStartTurn
    → MonsterStartTurnAction         各怪 apply_start_of_turn_powers（格挡清零）
    → do_monster_turn × N            take_turn：执行意图（入队）+ 回合末 roll_move
    → after_monster_turns()          回合末统一结算（状态衰减/Ritual）
                                     → turn+1 → 玩家回合开始钩子 → 抽牌 → 回能

公开 API（供 CLI / Gym 环境调用）：
    play_card(hand_idx, target=None)   出牌（能量与目标校验在此）
    end_turn()                         结束回合
    input_state / outcome              推进结果查询
"""

from __future__ import annotations

import math

from sts.combat.actions import Actions
from sts.combat.card_manager import CardManager
from sts.combat.entities import Monster, MonsterGroup, Player
from sts.combat.queue import ActionQueue, CardQueue, CardQueueItem
from sts.combat.types import InputState, MonsterStatus, Outcome, PlayerStatus
from sts.rng import RngStreams

ENERGY_PER_TURN = 3
HAND_DRAW = 5
MAX_LOOPS = 100_000  # 主循环保险丝（对齐 lightspeed loopCount 守卫）


class BattleContext:
    def __init__(self, seed: int | None = None, encounter: str = "cultist"):
        # ---- 状态字段（对齐 lightspeed BattleContext.h，裁剪版）----
        self.rngs = RngStreams(seed)
        self.seed = seed
        self.encounter = encounter
        self.outcome = Outcome.UNDECIDED
        self.input_state = InputState.EXECUTING_ACTIONS
        self.monster_turn_idx = 6  # 哨兵：非敌方阶段（> 最大怪数 5）
        self.turn = 0
        self.is_battle_over = False
        self.end_turn_queued = False
        self.turn_has_ended = False
        self.skip_monster_turn = False
        self.action_queue = ActionQueue()
        self.card_queue = CardQueue()
        self.cur_card_queue_item: CardQueueItem | None = None
        self.log: list[str] = []
        self.player = Player(80)
        self.monsters = MonsterGroup()
        self.cards = CardManager()
        self._loop_count = 0

        self._init_content()
        self._start_player_turn()
        self.execute_actions()  # 推进到 PLAYER_NORMAL（等待玩家第一手）

    # ---- 初始化 ----
    def _init_content(self) -> None:
        """内容层装配：牌组实例化进抽牌堆、生成敌人、洗牌、首回合意图。

        内容定义在 sts/content/（纯数据 + play/take_turn 行为），
        引擎不感知具体卡牌与怪物（DESIGN.md 分层）。
        """
        from sts.content.encounters import setup_encounter

        setup_encounter(self)
        # 抽牌堆洗匀（shuffle 流）
        self.rngs.shuffle.shuffle(self.cards.draw_pile)
        # 战斗开始即生成第 1 回合意图（玩家开局可见，DESIGN.md §4.2）
        for m in self.monsters.monsters:
            m.roll_move(self)

    def _start_player_turn(self) -> None:
        """玩家回合开始（对齐 afterMonsterTurns 的玩家侧部分 + 首回合初始化）。"""
        self.turn += 1
        self.player.block = 0
        self.player.apply_start_of_turn_powers(self)
        self.player.energy = ENERGY_PER_TURN
        self.player.cards_played_this_turn = 0
        self.player.attacks_played_this_turn = 0
        self.player.skills_played_this_turn = 0
        self.draw_cards(HAND_DRAW)

    # ---- 主循环（对齐 BattleContext::executeActions）----
    def execute_actions(self) -> None:
        while True:
            self._loop_count += 1
            if self._loop_count > MAX_LOOPS:
                raise RuntimeError("主循环步数超限：疑似死循环或结算异常")

            if self.input_state != InputState.EXECUTING_ACTIONS:
                break
            if self.outcome == Outcome.PLAYER_LOSS:
                break
            if not self.action_queue.is_empty():
                self.action_queue.pop_front().fn(self)
                continue
            if self.outcome != Outcome.UNDECIDED:
                break
            if not self.card_queue.is_empty():
                self.play_card_queue_item(self.card_queue.pop_front())
                continue
            # 我方无牌且无 HP 外伤害手段 → 必败（本场景牌耗尽即败）
            if not (self.cards.hand or self.cards.draw_pile or self.cards.discard_pile):
                self.outcome = Outcome.PLAYER_LOSS
                break
            if self.monster_turn_idx < self.monsters.monster_count:
                self.monsters.do_monster_turn(self)
                continue
            if self.outcome != Outcome.UNDECIDED:
                break
            if self.turn_has_ended:
                self.after_monster_turns()
                continue
            if self.end_turn_queued:
                self.end_turn_queued = False
                self.on_turn_ending()
                continue
            self.set_state(InputState.PLAYER_NORMAL)
            break

    # ---- 队列压入 ----
    def add_to_top(self, a) -> None:
        self.action_queue.push_front(a)

    def add_to_bot(self, a) -> None:
        self.action_queue.push_back(a)

    def add_to_top_card(self, item: CardQueueItem) -> None:
        self.card_queue.push_back(item)  # 单项处理，top/bot 等价；保留接口对齐

    def add_to_bot_card(self, item: CardQueueItem) -> None:
        self.card_queue.push_back(item)

    def set_state(self, state: InputState) -> None:
        self.input_state = state

    # ---- 玩家公开动作 ----
    def play_card(self, hand_idx: int, target: int | None = None) -> None:
        if self.input_state != InputState.PLAYER_NORMAL:
            raise ValueError("当前不在玩家出牌阶段")
        if not (0 <= hand_idx < len(self.cards.hand)):
            raise ValueError(f"手牌编号无效：{hand_idx}")
        inst = self.cards.hand[hand_idx]
        if inst.card.unplayable:
            raise ValueError(f"{inst.card.zh}({inst.card.name}) 不可打出")
        if inst.cost > self.player.energy:
            raise ValueError(f"能量不足：{inst.card.zh} 需要 {inst.cost} 点，当前 {self.player.energy} 点")
        if inst.card.needs_target:
            if target is None:
                if self.monsters.monster_count == 1 and self.monsters.monsters[0].is_targetable():
                    target = 0  # 单敌人自动指向（上层可显式传 target）
                else:
                    raise ValueError("该牌需要选择目标")
            if not self.monsters.monsters[target].is_targetable():
                raise ValueError("目标不可选")

        self.player.energy -= inst.cost
        self.cards.hand.pop(hand_idx)
        item = CardQueueItem(card=inst, target=target)
        self.add_to_bot_card(item)
        self.set_state(InputState.EXECUTING_ACTIONS)
        self.execute_actions()

    def end_turn(self) -> None:
        if self.input_state != InputState.PLAYER_NORMAL:
            raise ValueError("当前不在玩家出牌阶段")
        self.card_queue.push_back(CardQueueItem.end_turn_item())
        self.end_turn_queued = True
        self.set_state(InputState.EXECUTING_ACTIONS)
        self.execute_actions()

    # ---- 卡牌队列处理（对齐 playCardQueueItem / useCard）----
    def play_card_queue_item(self, item: CardQueueItem) -> None:
        self.cur_card_queue_item = item
        if item.is_end_turn:
            self.call_end_turn_actions()
            return
        if item.random_target:
            # 随机目标怪（cardRandom 流）；本场景无来源，占位
            item.target = self.rngs.misc.int_inclusive(0, self.monsters.monster_count - 1)
        if item.trigger_on_use:
            self.use_card()
        else:
            self.use_no_trigger_card()

    def use_card(self) -> None:
        item = self.cur_card_queue_item
        assert item is not None and item.card is not None
        inst = item.card
        item.exhaust_on_use = item.exhaust_on_use or inst.card.exhausts
        self.player.cards_played_this_turn += 1
        self.log.append(f"你打出 {inst.card.zh}({inst.card.name})。")
        # 卡牌效果：内容层 play 把原子动作入队（对齐 useXxxCard 的 switch）
        inst.card.play(self, item)
        # 类型钩子（对齐 onUseXxxCard：通用攻击/技能/能力触发）
        match inst.card.ctype:
            case "Attack":
                self.on_use_attack_card()
            case "Skill":
                self.on_use_skill_card()
            case "Power":
                self.on_use_power_card()
            case _:
                self.on_use_status_or_curse_card()
        self.on_after_use_card()

    def use_no_trigger_card(self) -> None:
        """诅咒/状态卡的自动结算（Burn 等，范围内无来源，占位走弃牌）。"""
        item = self.cur_card_queue_item
        assert item is not None and item.card is not None
        self.cards.move_to_discard_pile(item.card)

    def on_use_attack_card(self) -> None:
        p = self.player
        p.attacks_played_this_turn += 1
        # AFTER_IMAGE/DOUBLE_TAP/RAGE/PEN_NIB 等触发暂无来源，不移植
        if p.statuses.has(PlayerStatus.RAGE):
            self.add_to_bot(Actions.gain_block(p.statuses.get(PlayerStatus.RAGE)))

    def on_use_skill_card(self) -> None:
        self.player.skills_played_this_turn += 1

    def on_use_power_card(self) -> None:
        pass  # 范围内无通用能力触发

    def on_use_status_or_curse_card(self) -> None:
        pass

    def on_after_use_card(self) -> None:
        """出牌收尾：进弃牌堆或消耗堆（对齐 onAfterUseCard）。"""
        item = self.cur_card_queue_item
        assert item is not None and item.card is not None
        if item.purge_on_use:
            return  # 卡直接消失（复制体等）
        if item.card.card.ctype == "Power":
            # 能力卡打出即移出战斗（对齐 onAfterUseCard：不进弃牌/消耗堆）
            return
        if item.exhaust_on_use:
            self.cards.move_to_exhaust_pile(item.card)
            self.log.append(f"{item.card.card.zh}({item.card.card.name}) 被消耗。")
        else:
            self.cards.move_to_discard_pile(item.card)

    # ---- 回合生命周期 ----
    def call_end_turn_actions(self) -> None:
        """结束回合哨兵处理：回合末触发的状态入队（对齐 callEndTurnActions）。

        METALLICIZE（回合末获得格挡）、LOSE_STRENGTH（Flex 临时力量
        扣回）、NO_DRAW（Battle Trance 解除）都在 Player.apply_end_of_turn_powers
        的钩子位入队。
        """
        self.player.apply_end_of_turn_powers(self)

    def on_turn_ending(self) -> None:
        """手牌清空 + 敌方阶段起点（对齐 onTurnEnding）。"""
        self.add_to_bot(Actions.clear_card_queue())
        self.add_to_bot(Actions.discard_at_end_of_turn())
        self.cards.reset_attributes_at_end_of_turn()
        self.add_to_bot(Actions.unnamed_end_of_turn_action())

    def after_monster_turns(self) -> None:
        """敌方阶段结束：回合末统一结算 + 玩家回合开始（对齐 afterMonsterTurns）。"""
        if not self.skip_monster_turn:
            self.apply_end_of_round_powers()
        self.turn += 1
        self.skip_monster_turn = False
        self.turn_has_ended = False

        self.player.apply_start_of_turn_powers(self)
        self.player.block = 0  # BARRICADE/CALIPERS 无来源，直接清零
        if self.outcome != Outcome.UNDECIDED:
            return
        self.add_to_bot(Actions.draw_cards(HAND_DRAW))
        self.player.energy = ENERGY_PER_TURN
        self.player.cards_played_this_turn = 0
        self.player.attacks_played_this_turn = 0
        self.player.skills_played_this_turn = 0

    def apply_end_of_round_powers(self) -> None:
        """回合末统一结算（对齐 applyEndOfRoundPowers 顺序）：
        先各怪 end_of_turn_triggers，再玩家 at_end_of_round（状态衰减），
        再各怪 end_of_round（Ritual/易伤递减）。
        """
        for m in self.monsters.monsters:
            if not m.is_dying and not m.is_dead_or_escaped():
                m.apply_end_of_turn_triggers(self)
        self.player.apply_at_end_of_round_powers(self)
        for m in self.monsters.monsters:
            if not m.is_dying and not m.is_dead_or_escaped():
                m.apply_end_of_round_powers(self)

    # ---- 抽牌（对齐 BattleContext::drawCards）----
    def draw_cards(self, count: int) -> None:
        if count <= 0 or self.player.statuses.has(PlayerStatus.NO_DRAW):
            return  # NO_DRAW（Battle Trance）：本回合禁止抽牌
        for _ in range(count):
            if not self.cards.draw_pile:
                if not self.cards.discard_pile:
                    break  # 两堆皆空
                self.on_shuffle()  # 弃牌堆洗回
            if not self.cards.draw_pile:
                break
            inst = self.cards.pop_from_draw_pile()
            if len(self.cards.hand) < 10:
                self.cards.move_to_hand(inst)
            else:
                # 手牌满：溢出直接弃牌（近似本体手牌上限行为）
                self.cards.move_to_discard_pile(inst)
                self.log.append(f"手牌已满，{inst.card.zh}({inst.card.name}) 被弃置。")

    def on_shuffle(self) -> None:
        self.cards.move_discard_pile_into_draw_pile()
        self.rngs.shuffle.shuffle(self.cards.draw_pile)

    def discard_at_end_of_turn_helper(self) -> None:
        """回合末弃整个手牌（retention 牌暂无来源）。"""
        for inst in self.cards.hand:
            self.cards.move_to_discard_pile(inst)
        self.cards.hand.clear()

    # ---- 伤害管线 ----
    def calculate_card_damage(self, item: CardQueueItem, target_idx: int, base_damage: int) -> int:
        """玩家出伤管线（对齐 calculateCardDamage，范围裁剪）：
        base + 力量(+活力) → 攻方乘算(虚弱) → 守方乘算(易伤) → floor → clamp。
        遗物/stance/FLIGHT/INTANGIBLE 等无来源，管线位置已留空。
        """
        d = float(base_damage)
        d += self.player.statuses.get(PlayerStatus.STRENGTH)
        if self.player.statuses.has(PlayerStatus.VIGOR):
            d += self.player.statuses.get(PlayerStatus.VIGOR)
        if self.player.statuses.has(PlayerStatus.WEAK):
            d *= 0.75
        m = self.monsters.monsters[target_idx]
        if m.statuses.has(MonsterStatus.VULNERABLE):
            d *= 1.5
        return max(0, math.floor(d))

    def calculate_card_block(self, base_block: int) -> int:
        """玩家格挡管线（对齐 calculateCardBlock）：敏捷 → 脆弱 3/4。"""
        block = base_block + self.player.statuses.get(PlayerStatus.DEXTERITY)
        block = max(0, block)
        if self.player.statuses.has(PlayerStatus.FRAIL):
            block = block * 3 // 4
        return block

    def calculate_monster_damage(self, m: Monster, base_damage: int) -> int:
        """怪物出伤管线（对齐 attackPlayerHelper 的伤害计算）。"""
        d = float(base_damage)
        d += m.statuses.get(MonsterStatus.STRENGTH)
        if m.statuses.has(MonsterStatus.WEAK):
            d *= 0.75
        if self.player.statuses.has(PlayerStatus.VULNERABLE):
            d *= 1.5
        return max(0, math.floor(d))

    # ---- 结束判定（对齐 checkCombat / die）----
    def check_combat(self) -> None:
        if self.outcome != Outcome.UNDECIDED and not self.is_battle_over:
            self.is_battle_over = True
            self.action_queue.clear_post_combat()
            self.card_queue.clear()
            self.log.append("战斗胜利！" if self.outcome == Outcome.PLAYER_VICTORY else "你被击败了……")

    # ---- 观测辅助（CLI / 环境用；不引入新信息）----
    @property
    def over(self) -> bool:
        return self.outcome != Outcome.UNDECIDED

    @property
    def won(self) -> bool:
        return self.outcome == Outcome.PLAYER_VICTORY

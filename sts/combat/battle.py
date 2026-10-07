"""BattleContext：战斗状态 + 主推进循环（sts_lightspeed 架构移植）。

这是引擎的中枢。移植自 lightspeed src/combat/BattleContext.cpp 的
executeActions 主循环与回合生命周期。

主循环（execute_actions，对齐 lightspeed 顺序）：
    1. 弹 action_queue 逐个执行
    2. 弹 card_queue 逐张处理（出牌 / 结束回合哨兵 / 诅咒状态自动结算）
    3. 敌方阶段：依次 do_monster_turn（take_turn 入队该怪动作）
    4. 全部怪行动完（turn_has_ended）→ after_monster_turns
    5. end_turn_queued → on_turn_ending（弃手牌、置敌方阶段起点）
    6. 回到 PLAYER_NORMAL / CARD_SELECT，等待玩家输入

回合生命周期（一次 end_turn 的完整链，对齐 lightspeed）：
    end_turn()                       入队结束回合哨兵
    → call_end_turn_actions()        上回合行为快照 → 回合末遗物 → 玩家回合末
                                     状态（METALLICIZE/COMBUST/THE_BOMB…）→
                                     手中诅咒/状态卡入队自动结算
    → on_turn_ending()               ClearCardQueue + 弃手牌（虚无消耗）+ UnnamedEndOfTurn
    → UnnamedEndOfTurnAction         turn_has_ended=True, 置 monster_turn_idx=0,
                                     入队 MonsterStartTurn
    → MonsterStartTurnAction         各怪 apply_start_of_turn_powers（中毒/格挡清零）
    → do_monster_turn × N            take_turn：执行意图（入队）+ 回合末 roll_move
    → after_monster_turns()          回合末统一结算（状态衰减/Ritual）→ turn+1
                                     → 回合开始遗物 → 玩家起手状态 → 格挡衰减
                                     → 抽牌 → 抽牌后遗物/状态 → 回能

公开 API（供 CLI / Gym 环境调用）：
    play_card(hand_idx, target=None)   出牌（能量/目标/缠绕/遗物资格校验在此）
    end_turn()                         结束回合
    open_card_select / choose_cards    选卡界面（CARD_SELECT 挂起/恢复）
    input_state / outcome              推进结果查询
"""

from __future__ import annotations

import math

from sts.combat.actions import Actions
from sts.combat.card_manager import CardManager
from sts.combat.entities import Monster, MonsterGroup, Player
from sts.combat.queue import ActionQueue, CardQueue, CardQueueItem, CardSelectInfo
from sts.combat.relics import BOSS_ENCOUNTERS, RelicContainer
from sts.combat.types import InputState, MonsterStatus, Orb, Outcome, PlayerStatus, Stance
from sts.rng import RngStreams

ENERGY_PER_TURN = 3
HAND_DRAW = 5
MAX_LOOPS = 100_000  # 主循环保险丝（对齐 lightspeed loopCount 守卫）


class BattleContext:
    def __init__(
        self,
        seed: int | None = None,
        encounter: str = "cultist",
        ascension: int = 0,
        deck: list | None = None,
        relics: list | None = None,
        bottled_cards: list[str] | None = None,
        relic_counters: dict | None = None,
        potions: list | None = None,
    ):
        # ---- 状态字段（对齐 lightspeed BattleContext.h）----
        self.rngs = RngStreams(seed)
        self.seed = seed
        self.encounter = encounter
        self.ascension = ascension  # 进阶等级（A0 基准，怪物定义读此字段）
        self._deck_override = deck  # 测试/场景用：覆盖遭遇默认牌组
        self.bottled_cards = list(bottled_cards or [])  # 瓶装遗物选定的卡名（拾取时局外选卡，场景层表达）
        self.relics = RelicContainer(relics)
        # 遗物计数器预置（场景层局外状态：如 ANCIENT_TEA_SET counter=-2 表
        # "休息过，下场战斗首回合 +2 能量"）——须在首回合回能前生效
        if relic_counters:
            for rid, v in relic_counters.items():
                self.relics.set_counter(rid, v)
        self.outcome = Outcome.UNDECIDED
        self.input_state = InputState.EXECUTING_ACTIONS
        self.card_select_info: CardSelectInfo | None = None
        self.scry_cards: list = []  # 当前 Scry 展示的抽牌堆顶牌（按堆顶序）
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

        # 药水初始携带（场景配置；单场模拟不模拟局外药水获取）
        self.player.potion_slots = 3 + self.relics.potion_slot_bonus(self)
        self.player.potions = [None] * self.player.potion_slots
        for i, pd in enumerate(potions or []):
            if i >= self.player.potion_slots:
                break
            self.player.potions[i] = pd
        self._loop_count = 0

        self._init_content()
        self._start_player_turn(first=True)
        self.execute_actions()  # 推进到 PLAYER_NORMAL（等待玩家第一手）

    # ---- 初始化 ----
    def _init_content(self) -> None:
        """内容层装配：牌组实例化进抽牌堆、生成敌人、洗牌、首回合意图。

        内容定义在 sts/content/（纯数据 + play/take_turn 行为），
        引擎不感知具体卡牌与怪物（DESIGN.md 分层）。
        """
        from sts.content.encounters import setup_encounter

        setup_encounter(self)
        if self._deck_override is not None:
            self.cards.draw_pile.clear()
            for card in self._deck_override:
                self.cards.create_deck_card_in_draw_pile(card)
        # 抽牌堆洗匀（shuffle 流）→ 固有牌置顶（Innate）
        self.rngs.shuffle.shuffle(self.cards.draw_pile)
        self.cards.move_innate_to_top()
        # 瓶装牌（Bottled Flame/Lightning/Tornado）置堆顶（在固有之上，
        # 对齐 CardGroup.initializeDeck 的 placeOnTop 顺序）
        if self.bottled_cards:
            self.cards.move_bottled_to_top(self.bottled_cards)
        # 战斗开始即生成第 1 回合意图（玩家开局可见，DESIGN.md §4.2）
        for m in self.monsters.monsters:
            m.roll_move(self)

    def _start_player_turn(self, first: bool = False) -> None:
        """玩家回合开始（首回合初始化 + afterMonsterTurns 的玩家侧部分）。

        首回合（first=True）按 lightspeed initRelics 顺序插入战斗开始
        遗物三桶：即时效果（获取序）→ 抽牌前桶（改抽牌数）→ 抽牌 → 抽牌后桶。
        """
        self.turn += 1
        self.player.cards_discarded_this_turn = 0
        self.player.block = 0
        self.player.apply_start_of_turn_powers(self)
        self._recharge_energy()
        self._reset_turn_counters()
        extra_draw = 0
        if first:
            self.relics.on_battle_start_immediate(self)
            extra_draw = self.relics.on_battle_start_extra_draw(self)
        self.draw_cards(HAND_DRAW + extra_draw)
        if first:
            self.relics.on_battle_start_post_draw(self)

    def _recharge_energy(self) -> None:
        """回合开始回能：基础 3 + Berserk/能量遗物加成 + ICE_CREAM 结转 +
        Flying Knee/Outmaneuver 的下回合能量槽（Silent 卡，special 一次性）。"""
        base = ENERGY_PER_TURN + self.player.energy_per_turn_bonus + self.relics.extra_energy_per_turn(self)
        base += self.relics.first_turn_energy_bonus(self)  # ANCIENT_TEA_SET：休息后首回合（counter=-2 一次性）
        base += self.player.special.pop("next_turn_energy", 0)
        leftover = self.player.energy if self.relics.keeps_leftover_energy(self) else 0
        self.player.energy = base + leftover

    def _reset_turn_counters(self) -> None:
        p = self.player
        p.cards_played_this_turn = 0
        p.attacks_played_this_turn = 0
        p.skills_played_this_turn = 0
        p.cards_discarded_this_turn = 0

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
            if not (self.cards.hand or self.cards.draw_pile or self.cards.discard_pile or self.cards.limbo):
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
        if inst.card.unplayable and not self.relics.makes_unplayable_playable(inst):
            raise ValueError(f"{inst.card.zh}({inst.card.name}) 不可打出")
        if inst.card.play_condition is not None and not inst.card.play_condition(self, inst):
            raise ValueError(f"{inst.card.zh}({inst.card.name}) 当前不满足打出条件")
        if self.player.statuses.has(PlayerStatus.ENTANGLED) and inst.card.ctype == "Attack":
            # 缠绕只拦攻击牌（对齐 lightspeed CardInstance.cpp:292 的 ATTACK 分支）
            raise ValueError("被缠绕：本回合不能打出攻击牌")
        if not self.relics.check_play_allowed(self, inst):
            raise ValueError("遗物限制：当前不能打出卡牌")
        if inst.card.needs_target:
            if target is None:
                if self.monsters.monster_count == 1 and self.monsters.monsters[0].is_targetable():
                    target = 0  # 单敌人自动指向（上层可显式传 target）
                else:
                    raise ValueError("该牌需要选择目标")
            if not self.monsters.monsters[target].is_targetable():
                raise ValueError("目标不可选")

        if inst.card.x_cost:
            # X 费：消耗全部能量，能量快照进队列项（对齐 energyOnUse）；
            # CHEMICAL_X：效果 +2 次（wiki）——快照值 = 能量 + 2
            bonus = self.relics.chemical_x_bonus(self)
            item = CardQueueItem(card=inst, target=target,
                                 energy_on_use=self.player.energy + bonus)
            self.player.energy = 0
        else:
            cost = inst.cost
            if getattr(inst.card, "dynamic_cost", None) is not None:
                cost = inst.card.dynamic_cost(self, inst)
            # Swivel（观者）：下一张攻击牌 0 费（special 一次性）
            if inst.card.ctype == "Attack" and self.player.special.pop("swivel", False):
                cost = 0
            # Corruption：技能牌 0 费（打出即消耗的标志在 use_card 置位）
            if inst.card.ctype == "Skill" and self.player.statuses.has(PlayerStatus.CORRUPTION):
                cost = 0
            if cost > self.player.energy:
                raise ValueError(f"能量不足：{inst.card.zh} 需要 {cost} 点，当前 {self.player.energy} 点")
            self.player.energy -= cost
            item = CardQueueItem(card=inst, target=target)
        self.cards.hand.pop(hand_idx)
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

    # ---- 药水（2026-10-07 批次，对照本体反编译源码）----
    def use_potion(self, slot: int, target: int | None = None, choice: str | None = None) -> None:
        """使用一格药水（AbstractPotion.use 的引擎入口）。

        - 仅 PLAYER_NORMAL（本体 canUse 的 turnHasEnded 拒绝在此收敛为
          出牌阶段可用；CARD_SELECT/SCRY 挂起期间不可用）
        - targeting 药水（恐惧/虚弱/剧毒/火焰）需指定存活敌人（单敌人
          自动指向，与 play_card 口径一致）
        - STANCE_POTION 需 choice ∈ ("wrath", "calm")
        - potency 经 SACRED_BARK ×2（AbstractPotion.getPotency L45-49）
        - TOY_ORNITHOPTER 使用后回复 5 HP
        """
        if self.input_state != InputState.PLAYER_NORMAL:
            raise ValueError("当前不在玩家出牌阶段，无法使用药水")
        if not (0 <= slot < len(self.player.potions)):
            raise ValueError(f"药水槽无效：{slot}")
        pd = self.player.potions[slot]
        if pd is None:
            raise ValueError(f"药水槽 {slot} 为空")
        if pd.escape_only and self.encounter in BOSS_ENCOUNTERS:
            raise ValueError("烟雾弹不能在 Boss 战中使用")
        if pd.auto_only:
            raise ValueError(f"{pd.zh} 不能手动使用")
        if pd.choices and choice not in pd.choices:
            raise ValueError(f"{pd.zh} 需要选择：{list(pd.choices)}")
        if pd.targeting:
            if target is None:
                if self.monsters.monster_count == 1 and self.monsters.monsters[0].is_targetable():
                    target = 0
                else:
                    raise ValueError("该药水需要选择目标")
            if not self.monsters.monsters[target].is_targetable():
                raise ValueError("目标不可选")
        self.player.potions[slot] = None
        potency = pd.potency * (2 if self.relics.sacred_bark_doubles_potions(self) else 1)
        self.log.append(f"你使用了 {pd.zh}({pd.name})。")
        # 先置执行态再入队（与 play_card 同构）：use 内部 open_card_select
        # 可将状态挂起为 CARD_SELECT，随后的 execute_actions 会正确停在挂起态
        self.set_state(InputState.EXECUTING_ACTIONS)
        pd.use(self, target, potency, choice)
        self.relics.on_use_potion(self)
        self.execute_actions()

    def obtain_potion(self, pd) -> bool:
        """获得一瓶药水（空槽放置；SOZU 拦截——"You can no longer
        obtain potions"）。战斗内来源：Venomology 卡 / 熵变酿制药水。"""
        from sts.combat.relics import RelicId

        if self.relics.has(RelicId.SOZU):
            self.log.append("苏珠：无法获得药水。")
            return False
        for i, cur in enumerate(self.player.potions):
            if cur is None:
                self.player.potions[i] = pd
                return True
        return False  # 槽满：丢弃（ObtainPotionAction 的弃置路径）

    def _gen_shiv(self) -> None:
        """生成 1 张 Shiv（AFTER_IMAGE/INFINITE_BLADES 状态结算；SHIV 定义
        在内容层 cards/silent.py，惰性导入沿用 encounters 先例）。"""
        from sts.content.cards.silent import SHIV

        self.cards.create_temp_card_in_hand(SHIV)

    # ---- 选卡界面（对齐 lightspeed CardSelectInfo + chooseXxx 回调族）----
    def open_card_select(
        self,
        candidates: list,
        on_choose,
        pick_count: int = 1,
        can_pick_zero: bool = False,
        can_pick_any_number: bool = False,
        prompt: str = "",
    ) -> None:
        """打开选卡。候选恰好 1 张且必选时直接执行（对齐 lightspeed 单候选
        直执）；候选为空时按 can_pick_zero 决定空执行或跳过；否则挂起为
        CARD_SELECT 等外部调 choose_cards。"""
        if not candidates:
            if can_pick_zero:
                on_choose(self, [])
            return
        if pick_count == 1 and len(candidates) == 1:
            on_choose(self, candidates)
            return
        self.card_select_info = CardSelectInfo(
            candidates=list(candidates),
            on_choose=on_choose,
            pick_count=pick_count,
            can_pick_zero=can_pick_zero,
            can_pick_any_number=can_pick_any_number,
            prompt=prompt,
        )
        self.set_state(InputState.CARD_SELECT)

    def choose_cards(self, indices: list[int]) -> None:
        """完成选卡：执行效果并恢复主循环。indices 为候选列表下标。"""
        if self.input_state != InputState.CARD_SELECT or self.card_select_info is None:
            raise ValueError("当前不在选卡状态")
        info = self.card_select_info
        n = len(indices)
        if n == 0:
            if not info.can_pick_zero:
                raise ValueError("本次选卡至少选择 1 张")
        elif n > info.pick_count and not info.can_pick_any_number:
            raise ValueError(f"最多选择 {info.pick_count} 张")
        chosen = [info.candidates[i] for i in indices]
        self.card_select_info = None
        self.set_state(InputState.EXECUTING_ACTIONS)
        info.on_choose(self, chosen)
        self.execute_actions()

    def choose_card(self, idx: int) -> None:
        self.choose_cards([idx])

    # ---- Scry（批次 E：对齐 InputState::SCRY，C++ 无实现按 wiki 自建）----
    def open_scry(self, count: int) -> None:
        """检视抽牌堆顶 count 张：不足取全部。展示顺序 = 堆顶优先（抽牌
        从 draw_pile 尾弹出，故展示 = 尾部倒序）。无牌时直接结束。
        GOLDEN_EYE：额外检视 2 张（wiki）。"""
        count += self.relics.golden_eye_scry_bonus(self)
        n = min(count, len(self.cards.draw_pile))
        if n <= 0:
            return
        self.scry_cards = self.cards.draw_pile[-n:][::-1]  # [0]=堆顶
        self.set_state(InputState.SCRY)

    def choose_scry(self, keep_top_n: int) -> None:
        """完成 Scry：保留堆顶 keep_top_n 张，其余弃置（不触发手动弃牌
        触发器——Scry 弃牌走独立路径，对齐 wiki"Scry 牌不算被弃"）。
        keep_top_n 从堆顶数起；弃置的按堆序进弃牌堆。"""
        if self.input_state != InputState.SCRY:
            raise ValueError("当前不在检视状态")
        n = len(self.scry_cards)
        keep = max(0, min(keep_top_n, n))
        # scry_cards[0] = 堆顶：保留堆顶 keep 张 = 列表前 keep 个，
        # 弃置其余（列表后段 = 更深处的牌）
        to_discard = self.scry_cards[keep:]
        for inst in to_discard:
            self.cards.draw_pile.remove(inst)
            self.cards.move_to_discard_pile(inst)
            self.log.append(f"检视弃置 {inst.card.zh}({inst.card.name})。")
        # NIRVANA（观者）：每次 Scry 后获得 3/4×弃置数 格挡
        n_block = self.player.special.pop("nirvana", 0)
        if n_block and to_discard:
            self.add_to_bot(Actions.gain_block(n_block * len(to_discard)))
        self.scry_cards = []
        self.set_state(InputState.EXECUTING_ACTIONS)
        self.execute_actions()

    # ---- 卡牌队列处理（对齐 playCardQueueItem / useCard）----
    def play_card_queue_item(self, item: CardQueueItem) -> None:
        self.cur_card_queue_item = item
        if item.is_end_turn:
            self.call_end_turn_actions()
            return
        if item.random_target:
            # 随机目标怪（对齐 cardRandom 流；本项目用 misc 流，分布级等价）
            alive = [m for m in self.monsters.monsters if m.is_targetable()]
            if alive:
                item.target = alive[self.rngs.misc.int_inclusive(0, len(alive) - 1)].idx
            else:
                item.target = -1
        if item.trigger_on_use:
            self.use_card()
        else:
            self.use_no_trigger_card()

    def use_card(self) -> None:
        item = self.cur_card_queue_item
        assert item is not None and item.card is not None
        inst = item.card
        item.exhaust_on_use = item.exhaust_on_use or inst.card.exhausts
        # Corruption：技能牌打出即消耗（对齐 lightspeed useCard 的 CORRUPTION 段）
        if inst.card.ctype == "Skill" and self.player.statuses.has(PlayerStatus.CORRUPTION):
            item.exhaust_on_use = True
        self.player.cards_played_this_turn += 1
        self.log.append(f"你打出 {inst.card.zh}({inst.card.name})。")
        # 卡牌效果：内容层 play 把原子动作入队（对齐 useXxxCard 的 switch）
        inst.card.play(self, item)
        # DUPLICATION（复制药水）：本回合下一张牌打出后额外结算一次
        # （DuplicationPower.onUseCard → queueExtraCard，任意类型；触发即消耗）
        if self.player.statuses.has(PlayerStatus.DUPLICATION) and not item.autoplay:
            self.player.statuses.decrement(PlayerStatus.DUPLICATION)
            replay = CardQueueItem(
                card=item.card, target=item.target, purge_on_use=True,
                autoplay=True, energy_on_use=item.energy_on_use,
            )
            self.add_to_bot_card(replay)
        # PANACHE：每打出 5 张牌全体伤害（C++ 四处 onUseXxxCard 的 --panacheCounter；
        # C++ 归零后不重置系 bug，按 wiki"每打出 5 张"重置计数）
        if self.player.statuses.has(PlayerStatus.PANACHE):
            c = self.player.special.get("panache_counter", 5) - 1
            if c <= 0:
                self.add_to_bot(
                    Actions.damage_all_enemy(self.player.statuses.get(PlayerStatus.PANACHE)))
                c = 5
            self.player.special["panache_counter"] = c
        # A_THOUSAND_CUTS（Silent 千刀万剐）：每打出一张牌全体 1×层 伤
        if self.player.statuses.has(PlayerStatus.A_THOUSAND_CUTS):
            self.add_to_bot(
                Actions.damage_all_enemy(self.player.statuses.get(PlayerStatus.A_THOUSAND_CUTS)))
        # HEX（Chosen 巫咒）：每打出一张**非攻击**牌洗入 1 张 DAZED
        #（本体 HexPower.onUseCard 的 useCard.type != ATTACK 判定；怪物审计
        # 发现 lightspeed 的 onUseXxx 三处含攻击牌段系其偏差，按本体修正）
        if self.player.statuses.has(PlayerStatus.HEX) and inst.card.ctype != "Attack":
            from sts.content.cards import DAZED

            self.add_to_bot(Actions.make_temp_card_in_draw_pile(DAZED, False, shuffle_into=True))
        # AFTER_IMAGE（Silent 残像）：每打出一张牌得 1 格挡（对齐 C++ 四处
        # onUseXxxCard 的 GainBlock 分支与 wiki；原"出技能生成 Shiv"实现错误）
        if self.player.statuses.has(PlayerStatus.AFTER_IMAGE):
            self.add_to_bot(Actions.gain_block(1))
        # CHOKED（Silent Choke）：每打出一张牌，带 CHOKED 的怪受层伤
        for m in self.monsters.monsters:
            if m.is_targetable() and m.statuses.has(MonsterStatus.CHOKED):
                self.add_to_bot(Actions.damage_enemy(m.idx, m.statuses.get(MonsterStatus.CHOKED)))
        # 逐怪"出牌响应"状态（对齐 onAfterUseCard 的 arr[0] 段，BattleContext.cpp:1941-1959；
        # C++ 只查 arr[0]——Time Eater/SLOW/BEAT_OF_DEATH 均为单怪遭遇，沿用）
        if not item.autoplay:
            m0 = self.monsters.monsters[0] if self.monsters.monsters else None
            if m0 is not None and not m0.is_dead_or_escaped():
                if m0.statuses.has(MonsterStatus.TIME_WARP):
                    tw = m0.statuses.get(MonsterStatus.TIME_WARP)
                    if tw >= 11:
                        # 满 12（11+1）：重置、+2 力量、提前结束回合
                        m0.statuses.set(MonsterStatus.TIME_WARP, 0)
                        m0.statuses.add(MonsterStatus.STRENGTH, 2)
                        self._call_end_turn_early()
                    else:
                        m0.statuses.set(MonsterStatus.TIME_WARP, tw + 1)
                if m0.statuses.has(MonsterStatus.SLOW):
                    m0.statuses.add(MonsterStatus.SLOW, 1)
                if m0.statuses.has(MonsterStatus.BEAT_OF_DEATH):
                    self.add_to_bot(Actions.damage_player(m0.statuses.get(MonsterStatus.BEAT_OF_DEATH)))
        # 类型钩子（对齐 onUseXxxCard：通用攻击/技能/能力触发 + 遗物 + 怪物触发器）
        match inst.card.ctype:
            case "Attack":
                self.on_use_attack_card()
            case "Skill":
                self.on_use_skill_card()
            case "Power":
                self.on_use_power_card()
            case _:
                self.on_use_status_or_curse_card(inst)
        self.on_after_use_card()
        # 诅咒 Pain：打出其他牌时失去 HP（按手中剩余 Pain 计）
        pain = sum(c.card.on_play_other_lose_hp for c in self.cards.hand)
        if pain > 0:
            self.add_to_bot(Actions.player_lose_hp(pain))

    def use_no_trigger_card(self) -> None:
        """诅咒/状态卡的自动结算（Burn/Regret/Decay/Doubt/Shame/Pride 等）。

        结算前先移出手牌（效果读到的手牌数不含自身），效果执行后按
        no_trigger_exhausts 走消耗堆或弃牌堆。
        """
        item = self.cur_card_queue_item
        assert item is not None and item.card is not None
        inst = item.card
        try:
            self.cards.hand.remove(inst)
        except ValueError:
            pass  # 不在手牌（防御性：如重复入队）
        if inst.card.no_trigger_effect is not None:
            inst.card.no_trigger_effect(self, item)
        if inst.card.no_trigger_exhausts:
            self.cards.move_to_exhaust_pile(inst)
            self.on_card_exhausted(inst)
        else:
            self.cards.move_to_discard_pile(inst)

    def on_use_attack_card(self) -> None:
        p = self.player
        item = self.cur_card_queue_item
        p.attacks_played_this_turn += 1
        # BLOCK_RETURN（Talk to the Hand）：攻击带此状态的敌人时获得层数格挡
        if item is not None and isinstance(item.target, int) and 0 <= item.target < self.monsters.monster_count:
            m = self.monsters.monsters[item.target]
            if m.statuses.has(MonsterStatus.BLOCK_RETURN):
                self.add_to_bot(Actions.gain_block(m.statuses.get(MonsterStatus.BLOCK_RETURN)))
        if p.statuses.has(PlayerStatus.RAGE):
            self.add_to_bot(Actions.gain_block(p.statuses.get(PlayerStatus.RAGE)))
        self.relics.on_use_attack_card(self)
        # DOUBLE_TAP：本回合下一张攻击牌结算两次（触发后移除；重放项 purge，
        # 不会二次进弃牌堆）
        if p.statuses.has(PlayerStatus.DOUBLE_TAP) and item is not None and not item.autoplay:
            p.statuses.decrement(PlayerStatus.DOUBLE_TAP)  # 升级版 2 层连翻两张
            replay = CardQueueItem(
                card=item.card, target=item.target, purge_on_use=True,
                autoplay=True, energy_on_use=item.energy_on_use,
            )
            self.add_to_bot_card(replay)
        # 怪物 SHARP_HIDE：玩家每打出一张攻击牌，反伤 局 伤（对齐 onUseAttackCard 尾部）
        for m in self.monsters.monsters:
            if m.is_targetable() and m.statuses.has(MonsterStatus.SHARP_HIDE):
                self.add_to_bot(Actions.damage_player(m.statuses.get(MonsterStatus.SHARP_HIDE)))
        # PAINFUL_STABS（Book of Stabbing）：玩家每打出攻击牌受层伤
        for m in self.monsters.monsters:
            if m.is_targetable() and m.statuses.has(MonsterStatus.PAINFUL_STABS):
                self.add_to_bot(Actions.damage_player(m.statuses.get(MonsterStatus.PAINFUL_STABS)))

    def on_use_skill_card(self) -> None:
        p = self.player
        item = self.cur_card_queue_item
        p.skills_played_this_turn += 1
        self.relics.on_use_skill_card(self)
        # BURST（Silent 爆发）：本回合下一张技能牌结算两次（DOUBLE_TAP 的
        # 技能版；触发后递减）
        if p.statuses.has(PlayerStatus.BURST) and item is not None and not item.autoplay:
            p.statuses.decrement(PlayerStatus.BURST)
            replay = CardQueueItem(
                card=item.card, target=item.target, purge_on_use=True,
                autoplay=True, energy_on_use=item.energy_on_use,
            )
            self.add_to_bot_card(replay)
        # 怪物 ENRAGE：玩家每打出一张技能牌，+层 力量（Gremlin Nob）
        for m in self.monsters.monsters:
            if m.is_targetable() and m.statuses.has(MonsterStatus.ENRAGE):
                self.add_to_bot(Actions.buff_enemy(m.idx, MonsterStatus.STRENGTH, m.statuses.get(MonsterStatus.ENRAGE)))

    def on_use_power_card(self) -> None:
        p = self.player
        item = self.cur_card_queue_item
        self.relics.on_use_power_card(self)
        # Storm（Defect）：打出能力牌时引导 ×层 闪电球
        n_storm = p.special.get("storm", 0)
        if n_storm:
            for _ in range(n_storm):
                self.add_to_bot(Actions.channel_orb(Orb.LIGHTNING))
        # Heatsinks：打出能力牌抽 ×层
        n_heat = p.special.get("heatsinks", 0)
        if n_heat:
            self.add_to_bot(Actions.draw_cards(n_heat))
        # Amplify/Echo Form：能力牌双发（Amplify 本回合下 N 张；Echo Form
        # 每回合首张——C++ echoFormCardsDoubled 位）
        double = False
        if p.special.get("amplify", 0) > 0 and item is not None and not item.autoplay:
            p.special["amplify"] -= 1
            double = True
        if p.special.get("echo_form") and not p.special.get("echo_form_used") and item is not None and not item.autoplay:
            p.special["echo_form_used"] = True
            double = True
        if double:
            replay = CardQueueItem(card=item.card, target=item.target, purge_on_use=True,
                                   autoplay=True, energy_on_use=item.energy_on_use)
            self.add_to_bot_card(replay)
        # CURIOSITY（Awakened One）：玩家每打出能力牌 +层 力量（Monster.cpp:196/289）
        for m in self.monsters.monsters:
            if m.is_targetable() and m.statuses.has(MonsterStatus.CURIOSITY):
                self.add_to_bot(
                    Actions.buff_enemy(m.idx, MonsterStatus.STRENGTH, m.statuses.get(MonsterStatus.CURIOSITY)))

    def on_use_status_or_curse_card(self, inst) -> None:
        self.relics.on_use_status_or_curse_card(self, inst)

    def on_after_use_card(self) -> None:
        """出牌收尾：进弃牌堆或消耗堆（对齐 onAfterUseCard；STRANGE_SPOON
        50% 不消耗），手牌打空触发 UNCEASING_TOP。"""
        item = self.cur_card_queue_item
        assert item is not None and item.card is not None
        inst = item.card
        if item.purge_on_use:
            return  # 卡直接消失（复制重放体等）
        if inst.card.ctype == "Power":
            # 能力卡打出即移出战斗（对齐 onAfterUseCard：不进弃牌/消耗堆）
            pass
        elif item.exhaust_on_use:
            if self.relics.on_would_exhaust(self, inst):
                self.cards.move_to_exhaust_pile(inst)
                self.on_card_exhausted(inst)
                self.log.append(f"{inst.card.zh}({inst.card.name}) 被消耗。")
            else:
                self.cards.move_to_discard_pile(inst)
        elif self.player.statuses.has(PlayerStatus.REBOUND):
            # REBOUND（Defect，BattleContext.cpp:1975-1985/1998-2000）：==1 时
            # 本回合下一张打出的牌置于抽牌堆顶并移除状态；>1 减到 1
            if self.player.statuses.get(PlayerStatus.REBOUND) == 1:
                self.player.statuses.remove(PlayerStatus.REBOUND)
                self.cards.append_to_draw_top(inst)
            else:
                self.player.statuses.set(PlayerStatus.REBOUND, 1)
                self.cards.move_to_discard_pile(inst)
        else:
            self.cards.move_to_discard_pile(inst)
        if not self.cards.hand:
            self.relics.on_hand_empty(self)

    def on_card_exhausted(self, inst) -> None:
        """消耗触发（Feel No Pain/Dark Embrace/卡牌自带效果/遗物），一切消耗来源统一走此。

        对齐 triggerAndMoveToExhaustPile（BattleContext.cpp:2814-2834）：
        FEEL_NO_PAIN → DARK_EMBRACE → 卡牌自带消耗效果（Sentinel 回能等）→ 遗物。
        """
        s = self.player.statuses
        if s.has(PlayerStatus.FEEL_NO_PAIN):
            base = self.player.special.get("fnp_base", 3)
            self.add_to_bot(Actions.gain_block(base * s.get(PlayerStatus.FEEL_NO_PAIN)))
        if s.has(PlayerStatus.DARK_EMBRACE):
            self.add_to_bot(Actions.draw_cards(s.get(PlayerStatus.DARK_EMBRACE)))
        eff = getattr(inst.card, "on_exhaust_effect", None)
        if eff is not None:
            eff(self, inst)
        self.relics.on_card_exhausted(self, inst)

    # ---- 回合生命周期 ----
    def call_end_turn_actions(self) -> None:
        """结束回合哨兵处理（对齐 callEndTurnActions 顺序）：
        上回合行为快照 → 回合末遗物（固定序）→ 玩家回合末状态 →
        手中回合末自动结算的诅咒/状态卡入队。
        """
        p = self.player
        p.cards_played_last_turn = p.cards_played_this_turn
        p.attacks_played_last_turn = p.attacks_played_this_turn
        self.relics.on_end_turn(self)
        # 充能球回合结束被动（LIGHTNING 伤/DARK 存层；对齐 C++ 空壳位的
        # 预期位置 callEndTurnActions 的 TriggerEndOfTurnOrbsAction）
        self.player.trigger_orb_passives(self, start=False)
        p.apply_end_of_turn_powers(self)
        # Watcher special 回合末钩子：study（生成 Insight）/omega（全体 50/60）
        if self.player.special.get("study"):
            from sts.content.cards.watcher import INSIGHT

            self.cards.create_temp_card_in_hand(INSIGHT, self.player.special.get("master_reality", False))
        if self.player.special.get("omega"):
            self.add_to_bot(Actions.damage_all_enemy(self.player.special["omega"]))
        # Establishment：保留牌 -1 费（回合末保留进 limbo 前处理）
        if self.player.special.get("establishment") and self.cards.limbo:
            pass  # 已在 discard 阶段处理（费用在保留时递减，见下）
        # Well-Laid Plans（Silent）：回合末选 1 张手牌保留
        if p.special.get("wlp"):
            cands = list(self.cards.hand)
            n_keep = p.special.get("wlp")
            if cands:
                def _retain_chosen(bc2, chosen):
                    for inst in chosen:
                        inst.retain = True
                self.open_card_select(cands, _retain_chosen, pick_count=n_keep,
                                      can_pick_zero=True, prompt=f"选择 {n_keep} 张保留")
        # Burn/Regret/Decay/Doubt/Shame/Pride：以 trigger_on_use=False 入队
        #（对齐 lightspeed callEndTurnActions 的逐张入队；处理时机在
        # on_turn_ending 弃手牌之前）
        for inst in list(self.cards.hand):
            if inst.card.no_trigger_effect is not None:
                self.add_to_bot_card(CardQueueItem(card=inst, trigger_on_use=False))

    def on_turn_ending(self) -> None:
        """手牌清空 + 敌方阶段起点（对齐 onTurnEnding）。"""
        self.add_to_bot(Actions.clear_card_queue())
        self.add_to_bot(Actions.discard_at_end_of_turn())
        self.cards.reset_attributes_at_end_of_turn()
        self.add_to_bot(Actions.unnamed_end_of_turn_action())

    def after_monster_turns(self) -> None:
        """敌方阶段结束：回合末统一结算 + 玩家回合开始（对齐 afterMonsterTurns）：
        回合末衰减（怪→玩家→怪）→ turn+1 → 回合开始遗物 → 玩家起手状态
        → 格挡衰减（BARRICADE/CALIPERS）→ 抽牌 → 抽牌后遗物/状态 → 回能。
        """
        if not self.skip_monster_turn:
            self.apply_end_of_round_powers()
        self.turn += 1
        self.skip_monster_turn = False
        self.turn_has_ended = False

        # DIVINITY 回中性（对齐 BattleContext.cpp:2162-2164：atStartOfTurn 段，
        # 在遗物之前）
        if self.player.stance == Stance.DIVINITY:
            self.player.change_stance(self, Stance.NEUTRAL)
        self.relics.on_turn_start(self)
        # 充能球回合开始被动（FROST 格挡；LOOP 额外触发 orbs[0]）
        self.player.trigger_orb_passives(self, start=True)
        self.restore_retained_cards()  # 保留牌在玩家状态结算后、抽牌前还手
        self.player.apply_start_of_turn_powers(self)
        # ---- 回合开始的 Silent 状态（PHANTASMAL_KILLER 在此翻 DOUBLE_DAMAGE，
        # 使"下回合首次攻击翻倍"成立）----
        # Defect special 回合开始钩子；bias_focus 为持续计数（不 pop，
        # Biased Cognition 每回合 -层）
        n_bias = self.player.special.get("bias_focus", 0)
        if n_bias:
            self.player.statuses.add(PlayerStatus.FOCUS, -n_bias)
        n_hw = self.player.special.pop("hello_world", 0)
        if n_hw:
            from sts.content.cards.defect import random_power_card

            for _ in range(n_hw):
                self.cards.create_temp_card_in_hand(random_power_card(), False)
        n_ca = self.player.special.pop("creative_ai", 0)
        if n_ca:
            from sts.content.cards.defect import random_power_card

            for _ in range(n_ca):
                self.cards.create_temp_card_in_hand(random_power_card(), False)
        # Echo Form：每回合计数复位
        self.player.special.pop("echo_form_used", None)
        # Blasphemy：下回合开始死亡（special 一次性）
        if self.player.special.pop("blasphemy_die", False):
            self.add_to_bot(Actions.player_lose_hp(99999))
        # Watcher special 回合开始钩子：foresight（scry）/battle_hymn（Smite）/
        # deva_form（能量爬坡）/collect_miracles（升级版 Miracle）
        n_scry = self.player.special.pop("foresight", 0)
        if n_scry:
            self.open_scry(n_scry)
        if self.player.special.get("battle_hymn"):
            from sts.content.cards.watcher import SMITE

            for _ in range(self.player.special["battle_hymn"]):
                self.cards.create_temp_card_in_hand(SMITE, self.player.special.get("master_reality", False))
        if self.player.special.get("deva_form"):
            self.player.special["deva_form_counter"] = self.player.special.get("deva_form_counter", 1) + 1
            self.add_to_bot(Actions.gain_energy(self.player.special["deva_form_counter"] - 1))
        if self.player.special.pop("collect_miracles", 0):
            from sts.content.cards.watcher import MIRACLE

            self.cards.create_temp_card_in_hand(MIRACLE, True)  # 必须升级版
        # Wave of the Hand 每回合清零
        self.player.special.pop("wave_of_the_hand", None)
        s = self.player.statuses
        if s.has(PlayerStatus.PHANTASMAL_KILLER):
            s.remove(PlayerStatus.PHANTASMAL_KILLER)
            s.add(PlayerStatus.DOUBLE_DAMAGE, 1)
        if s.has(PlayerStatus.NOXIOUS_FUMES):
            self.add_to_bot(Actions.debuff_all_enemy(MonsterStatus.POISON, s.get(PlayerStatus.NOXIOUS_FUMES), False))
        if s.has(PlayerStatus.INFINITE_BLADES):
            # wiki/C++（Player.cpp 无条件 MakeTempCardInHand(SHIV)）：每回合
            # 无条件生成 ×层 Shiv——原"上回合出过攻击牌"条件系我方误加，去除
            for _ in range(s.get(PlayerStatus.INFINITE_BLADES)):
                self._gen_shiv()
        # 下回合生成槽（Nightmare/Doppelganger）：N 份保留副本入手
        for card_def, upgraded, count in self.player.special.pop("next_turn_cards", []):
            for _ in range(count):
                inst = self.cards.instantiate(card_def)
                inst.upgraded = upgraded
                inst.retain = True  # Nightmare 副本保留到打出
                if len(self.cards.hand) < 10:
                    self.cards.hand.append(inst)
                else:
                    self.cards.move_to_discard_pile(inst)
        # 格挡衰减：BARRICADE 保留全部，CALIPERS 保留 15，否则清零；
        # BLUR（Silent）：标记时本回合格挡全额保留一轮（special 一次性）
        if not self.player.statuses.has(PlayerStatus.BARRICADE):
            if self.player.special.pop("blur_next_turn", False):
                pass  # Blur：跳过本回合衰减
            else:
                retain = self.relics.on_block_decay(self)
                self.player.block = min(self.player.block, retain)
        if self.outcome != Outcome.UNDECIDED:
            return
        # Predator/Doppelganger 的下回合加抽（special 一次性）
        extra = self.player.special.pop("next_turn_draw", 0)
        self.add_to_bot(Actions.draw_cards(HAND_DRAW + extra))
        # Tools of the Trade（Silent）：回合开始抽 1 弃 1（对齐 C++
        # applyStartOfTurnPostDrawPowers 的 TOOLS 分支 + wiki 弃牌口径）
        if self.player.special.get("tott"):
            self.add_to_bot(Actions.draw_cards(1))
            self.add_to_bot(Actions.discard_chosen(1))
        self.relics.on_turn_start_post_draw(self)
        self._recharge_energy()
        self._reset_turn_counters()
        self.player.apply_start_of_turn_post_draw_powers(self)

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
        # DRAW_REDUCTION：每回合抽牌 -层（巫妖形态变体等；无自动衰减）
        count -= self.player.statuses.get(PlayerStatus.DRAW_REDUCTION)
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
            self.on_card_drawn(inst)

    def on_card_drawn(self, inst) -> None:
        """抽牌触发：Void 扣能 / HEX 掉血 / CONFUSED 改费 / EVOLVE /
        FIRE_BREATHING（对齐 CardManager::draw 钩子 + Player.cpp HEX 段）。"""
        s = self.player.statuses
        if inst.card.lose_energy_when_drawn > 0:
            self.player.energy = max(0, self.player.energy - inst.card.lose_energy_when_drawn)
        draw_eff = getattr(inst.card, "on_drawn_effect", None)
        if draw_eff is not None:
            draw_eff(self, inst)
        if s.has(PlayerStatus.CONFUSED):
            # Snecko/Confused：抽到的牌本回合费用随机 0~3（CardManager.cpp:403-412）
            inst.cost_for_turn = self.rngs.misc.int_inclusive(0, 3)
        if inst.card.ctype == "Status":
            if s.has(PlayerStatus.EVOLVE):
                self.draw_cards(s.get(PlayerStatus.EVOLVE))
            if s.has(PlayerStatus.FIRE_BREATHING):
                base = self.player.special.get("fire_breathing_base", 4)
                self.add_to_bot(Actions.damage_all_enemy(base * s.get(PlayerStatus.FIRE_BREATHING)))
        elif inst.card.ctype == "Curse":
            if s.has(PlayerStatus.FIRE_BREATHING):
                base = self.player.special.get("fire_breathing_base", 4)
                self.add_to_bot(Actions.damage_all_enemy(base * s.get(PlayerStatus.FIRE_BREATHING)))

    def on_shuffle(self) -> None:
        self.relics.on_shuffle(self)
        self.cards.move_discard_pile_into_draw_pile()
        self.rngs.shuffle.shuffle(self.cards.draw_pile)

    def discard_at_end_of_turn_helper(self) -> None:
        """回合末弃手牌（对齐 discardAtEndOfTurn，BattleContext.cpp:2465-2499）：
        ① 保留牌（self_retain/retain）移入 limbo（回合开始经
        restore_retained_cards 还手）；② RUNIC_PYRAMID/EQUILIBRIUM：其余整手
        保留；③ 虚无牌消耗；④ 其余弃置。"""
        retained = [c for c in self.cards.hand if c.is_retained]
        if retained:
            # Establishment（观者）：保留的牌费用 -1（每回合保留时）
            if self.player.special.get("establishment"):
                for c in retained:
                    c.cost_override = max(0, c.cost - 1)
            for c in retained:
                self.cards.hand.remove(c)
            self.cards.limbo.extend(retained)
            for c in retained:
                c.retain = False
        keep = self.relics.keeps_hand_at_end_of_turn(self) or self.player.statuses.has(PlayerStatus.EQUILIBRIUM)
        for inst in list(self.cards.hand):
            if inst.is_ethereal:
                self.cards.hand.remove(inst)
                self.cards.move_to_exhaust_pile(inst)
                self.log.append(f"{inst.card.zh}({inst.card.name}) 虚无消散。")
                self.on_card_exhausted(inst)
            elif not keep:
                self.cards.hand.remove(inst)
                self.cards.move_to_discard_pile(inst)

    def restore_retained_cards(self) -> None:
        """回合开始：limbo 中的保留牌还手（对齐 BattleContext.cpp:2571-2578）。
        保留期间触发增量（Watcher 保留族）：Perseverance +2 伤 / Windmill
        Strike +4 伤 / Sands of Time -1 费。"""
        for inst in self.cards.limbo:
            name = inst.card.name
            if name == "Perseverance":
                inst.misc_data += 2
            elif name == "Windmill Strike":
                inst.misc_data += 4
            elif name == "Sands of Time":
                inst.cost_override = max(0, inst.cost - 1)
            if len(self.cards.hand) < 10:
                self.cards.hand.append(inst)
            else:
                self.cards.move_to_discard_pile(inst)
        self.cards.limbo.clear()

    # ---- 手动弃牌管线（批次 A：Silent 弃牌族/Tactician/Reflex/Tingsha 用）----
    def manual_discard(self, inst) -> None:
        """弃置一张手牌（玩家主动弃牌）：进弃牌堆 + 触发 on_discard（卡牌
        自带效果/遗物）。"""
        try:
            self.cards.hand.remove(inst)
        except ValueError:
            pass
        self.cards.move_to_discard_pile(inst)
        self.player.cards_discarded_this_turn += 1
        self.on_manual_discard(inst)

    def on_manual_discard(self, inst) -> None:
        """弃牌触发（对齐 BattleContext.cpp:2787-2795）：卡牌自带效果
        （Tactician/Reflex）→ 遗物（Tingsha/Tough Bandages，lightspeed 未实现
        按 wiki 补）。"""
        eff = getattr(inst.card, "on_discard_effect", None)
        if eff is not None:
            eff(self, inst)
        self.relics.on_manual_discard(self, inst)

    def _call_end_turn_early(self) -> None:
        """TIME_WARP 满：提前结束玩家回合（对齐 callEndTurnEarlySequence，
        BattleContext.cpp:2121-2129）——清空卡队列中的自动播放项并入队重放，
        然后压入结束回合哨兵。"""
        while not self.card_queue.is_empty():
            item = self.card_queue.pop_front()
            if item.autoplay and not item.purge_on_use:
                self.add_to_bot(Actions._time_eater_replay(item))
        self.card_queue.push_back(CardQueueItem.end_turn_item())
        self.end_turn_queued = True

    # ---- 伤害管线 ----
    def calculate_card_damage(self, item: CardQueueItem, target_idx: int, base_damage: int) -> int:
        """玩家出伤管线（对齐 calculateCardDamage）：
        base + 力量(+活力) → 遗物修正（STRIKE_DUMMY/WRIST_BLADE/PEN_NIB）
        → 攻方乘算(虚弱) → 守方乘算(易伤；PAPER_PHROG 1.75) → floor → clamp。
        """
        d = float(base_damage)
        d += self.player.statuses.get(PlayerStatus.STRENGTH)
        if self.player.statuses.has(PlayerStatus.VIGOR):
            d += self.player.statuses.get(PlayerStatus.VIGOR)
        # ACCURACY（Silent 精准）：Shiv 伤害 +层；DOUBLE_DAMAGE：首次攻击
        # 翻倍后移除（Phantasmal Killer 落地态）
        if item.card is not None and item.card.card.name == "Shiv":
            d += self.player.statuses.get(PlayerStatus.ACCURACY)
        if self.player.statuses.has(PlayerStatus.DOUBLE_DAMAGE):
            d *= 2  # 全回合翻倍（衰减在 apply_at_end_of_round_powers）
        d = self.relics.modify_card_damage(self, item, target_idx, d)
        if self.player.statuses.has(PlayerStatus.WEAK):
            d *= 0.75
        # 姿态乘区（对齐 BattleContext.cpp:2706-2710：WEAK 之后、易伤之前）
        if self.player.stance == Stance.WRATH:
            d *= 2
        elif self.player.stance == Stance.DIVINITY:
            d *= 3
        m = self.monsters.monsters[target_idx]
        # SLOW（Giant Head，:2717-2719）：玩家对该怪伤害 ×(1+0.1×层)
        if m.statuses.has(MonsterStatus.SLOW):
            d *= 1 + m.statuses.get(MonsterStatus.SLOW) * 0.1
        if m.statuses.has(MonsterStatus.VULNERABLE):
            d *= self.relics.vulnerable_multiplier(self)
        return max(0, math.floor(d))

    def calculate_card_block(self, base_block: int) -> int:
        """玩家格挡管线（对齐 calculateCardBlock）：NO_BLOCK 归零 → 敏捷 → 脆弱 3/4。"""
        if self.player.statuses.has(PlayerStatus.NO_BLOCK):
            return 0
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
            d *= self.relics.monster_weak_multiplier(self)  # PAPER_KRANE：0.75→0.6
        if self.player.statuses.has(PlayerStatus.VULNERABLE):
            d *= self.relics.player_vulnerable_multiplier(self)  # ODD_MUSHROOM：1.5→1.25
        return max(0, math.floor(d))

    # ---- 结束判定（对齐 checkCombat / die）----
    def check_combat(self) -> None:
        if self.outcome != Outcome.UNDECIDED and not self.is_battle_over:
            self.is_battle_over = True
            if self.outcome == Outcome.PLAYER_VICTORY:
                self.relics.on_victory(self)  # BURNING_BLOOD/MEAT_ON_THE_BONE
                # Self Repair（Defect）：战斗结束回复 3×层（special 槽）
                n = self.player.special.pop("self_repair", 0)
                if n:
                    self.player.heal(3 * n)
            self.action_queue.clear_post_combat()
            self.card_queue.clear()
            if self.outcome == Outcome.PLAYER_VICTORY:
                self.log.append("战斗胜利！")
            elif self.outcome == Outcome.ESCAPED:
                self.log.append("你逃离了战斗。")
            else:
                self.log.append("你被击败了……")

    # ---- 观测辅助（CLI / 环境用；不引入新信息）----
    @property
    def over(self) -> bool:
        return self.outcome != Outcome.UNDECIDED

    @property
    def won(self) -> bool:
        return self.outcome == Outcome.PLAYER_VICTORY

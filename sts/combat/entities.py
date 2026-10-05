"""战斗实体：玩家、怪物、怪物组（对齐 lightspeed Player.cpp / Monster.cpp）。

关键移植点：
- 受击分两条路径：attacked（攻击伤害，走易伤放大后的数值）与
  damage（非攻击 HP 损失，如毒、虚空）——两者的格挡吸收相同，
  状态触发不同。
- 怪物死亡结算在 die()：递减存活数，全员死亡时置胜利并清队列。
- 回合末状态衰减集中在 apply_end_of_round_powers（对齐 lightspeed
  Monster::applyEndOfRoundPowers 的逐状态 if 序列）。
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from sts.combat.actions import Actions
from sts.combat.types import MonsterStatus, Outcome, PlayerStatus, Statuses

if TYPE_CHECKING:
    from sts.combat.battle import BattleContext
    from sts.content.monsters import MoveDef


class Combatant:
    def __init__(self, hp: int, max_hp: int, display_name: str):
        self.hp = hp
        self.max_hp = max_hp
        self.block = 0
        self.statuses = Statuses()
        self.display_name = display_name

    @property
    def alive(self) -> bool:
        return self.hp > 0


class Player(Combatant):
    def __init__(self, hp: int):
        super().__init__(hp, hp, "你")
        self.energy = 0
        self.gold = 99  # 铁甲战士开局金币（Looter 偷金用；单场模拟无经济循环）
        self.cards_played_this_turn = 0
        self.attacks_played_this_turn = 0
        self.skills_played_this_turn = 0
        # 上一回合快照（ART_OF_WAR / POCKETWATCH 等"上回合行为"遗物用；
        # 初始 0 对齐 lightspeed——首回合视为"上回合没出牌"，触发）
        self.cards_played_last_turn = 0
        self.attacks_played_last_turn = 0
        self.energy_per_turn_bonus = 0  # 每回合额外能量（Berserk）
        self.special: dict[str, int] = {}  # 特殊计数槽（对齐 lightspeed bomb/combust 等）

    # ---- 格挡获得（Juggernaut 等触发钩子的统一入口）----
    def gain_block(self, bc: BattleContext, amount: int) -> None:
        """获得格挡（一切格挡来源必须走此入口：NO_BLOCK 拦截 + Juggernaut 触发）。"""
        if self.statuses.has(PlayerStatus.NO_BLOCK):
            return
        self.block += amount
        if self.statuses.has(PlayerStatus.JUGGERNAUT):
            n = self.statuses.get(PlayerStatus.JUGGERNAUT)
            bc.add_to_bot(Actions.damage_random_enemy(5 * n))

    # ---- 玩家受击（对齐 Player::attacked，Player.cpp:209-255）----
    def attacked(self, bc: BattleContext, enemy_idx: int, damage: int) -> None:
        if self.statuses.has(PlayerStatus.INTANGIBLE):
            damage = min(damage, 1)  # C++ 由 attackPlayerHelper 上游钳制，等价
        saved_block = self.block
        self.block = max(0, self.block - damage)
        damage -= saved_block  # damage = 漏过格挡的余量
        # THORNS / FLAME_BARRIER：无论是否漏格挡都反弹，addToTop
        #（对齐 Player.cpp:225-233，THORNS 先、FLAME_BARRIER 后）
        if self.statuses.has(PlayerStatus.THORNS):
            bc.add_to_top(Actions.damage_enemy(enemy_idx, self.statuses.get(PlayerStatus.THORNS)))
        if self.statuses.has(PlayerStatus.FLAME_BARRIER):
            bc.add_to_top(Actions.damage_enemy(enemy_idx, self.statuses.get(PlayerStatus.FLAME_BARRIER)))
        if damage > 0:
            # TORII（漏格挡 ≤5 → 1）→ TUNGSTEN_ROD（-1），对齐 :235-241——
            # 都作用于格挡吸收之后的余量，不空耗格挡
            damage = bc.relics.on_incoming_attack_damage(bc, damage)
            # PLATED_ARMOR：未被格挡的攻击伤害 -1 层（:246-248，仅此路径）
            if self.statuses.has(PlayerStatus.PLATED_ARMOR):
                self.statuses.decrement(PlayerStatus.PLATED_ARMOR)
            self._hp_was_lost(bc, damage, False)

    def damage(self, bc: BattleContext, amount: int) -> None:
        """非攻击 HP 损失（Burn/毒等）。吃格挡但不触发受击类状态
        （对齐 Player::damage，Player.cpp:175-207）。"""
        if self.statuses.has(PlayerStatus.INTANGIBLE):
            amount = min(amount, 1)
        saved_block = self.block
        self.block = max(0, self.block - amount)
        amount -= saved_block
        if amount > 0:
            amount = bc.relics.on_hp_loss_reduce(bc, amount)  # TUNGSTEN_ROD（:201-203）
            if amount > 0:
                self._hp_was_lost(bc, amount, False)

    def lose_hp(self, bc: BattleContext, amount: int, self_inflicted: bool = False) -> None:
        """直接 HP 损失：不吃格挡、不吃易伤（献祭类卡/诅咒；对齐
        Player::loseHp，Player.cpp:257-273）。

        self_inflicted：自伤（Hemokinesis/Offering/Combust）——RUPTURE
        只在自伤时触发（hpWasLost 的 selfDamage 标志）。
        """
        if amount <= 0:
            return
        if self.statuses.has(PlayerStatus.INTANGIBLE):
            amount = 1
        amount = bc.relics.on_hp_loss_reduce(bc, amount)  # TUNGSTEN_ROD（:266-271）
        if amount <= 0:
            return
        self._hp_was_lost(bc, amount, self_inflicted)

    def heal(self, amount: int, bc: BattleContext | None = None) -> None:
        """治疗（对齐 Player::heal，Player.cpp:156-172）：MAGIC_FLOWER 放大
        ×3//2；RED_SKULL 从半血以下回复过线时 -3 力量。"""
        if amount <= 0:
            return
        if bc is not None:
            amount = bc.relics.modify_heal(bc, amount)
        was_bloodied = self.hp * 2 <= self.max_hp
        self.hp = min(self.max_hp, self.hp + amount)
        if bc is not None:
            bc.relics.on_after_heal(bc, was_bloodied)

    def _hp_was_lost(self, bc: BattleContext, amount: int, self_inflicted: bool) -> None:
        """HP 损失的单一漏斗（对齐 Player::hpWasLost，Player.cpp:275-320）：
        扣血 → RUPTURE（仅自伤）→ 遗物 wasHpLost 段 → 败北判定。"""
        was_bloodied = self.hp * 2 <= self.max_hp  # 扣血前快照
        self.hp = max(0, self.hp - amount)
        if self_inflicted and self.statuses.has(PlayerStatus.RUPTURE):
            bc.add_to_bot(Actions.buff_player(PlayerStatus.STRENGTH, self.statuses.get(PlayerStatus.RUPTURE)))
        bc.relics.on_player_hp_was_lost(bc, amount, was_bloodied)
        bc.cards.on_player_damaged()  # Blood for Blood 类受击改费（Player.cpp:317 onTookDamage）
        if self.hp <= 0 and bc.outcome == Outcome.UNDECIDED:
            bc.outcome = Outcome.PLAYER_LOSS
        bc.check_combat()

    # ---- 玩家回合钩子（对齐 Player.cpp 对应方法）----
    def apply_end_of_turn_powers(self, bc: BattleContext) -> None:
        """onTurnEnding 阶段：回合末触发的玩家状态（对齐
        Player::applyEndOfTurnPowers 与 BattleContext::callEndTurnActions
        的玩家 Power 段，顺序：COMBUST → METALLICIZE → THE_BOMB →
        临时状态解除）。
        """
        s = self.statuses
        if s.has(PlayerStatus.COMBUST):
            n = s.get(PlayerStatus.COMBUST)
            bc.add_to_bot(Actions.player_lose_hp(n, self_inflicted=True))
            bc.add_to_bot(Actions.damage_all_enemy(5 * n))
        if s.has(PlayerStatus.METALLICIZE):
            bc.add_to_bot(Actions.gain_block(s.get(PlayerStatus.METALLICIZE)))
        if s.has(PlayerStatus.THE_BOMB):
            # 倒数：层数=剩余回合数，归零时爆发（伤害存 special["the_bomb"]）
            if s.get(PlayerStatus.THE_BOMB) == 1:
                s.remove(PlayerStatus.THE_BOMB)
                bc.add_to_bot(Actions.damage_all_enemy(self.special.get("the_bomb", 40)))
            else:
                s.decrement(PlayerStatus.THE_BOMB)
        if s.has(PlayerStatus.LOSE_STRENGTH):
            n = s.get(PlayerStatus.LOSE_STRENGTH)
            bc.add_to_bot(Actions.debuff_player(PlayerStatus.STRENGTH, -n, False))
            bc.add_to_bot(Actions.remove_player_status(PlayerStatus.LOSE_STRENGTH))
        if s.has(PlayerStatus.NO_DRAW):
            bc.add_to_bot(Actions.remove_player_status(PlayerStatus.NO_DRAW))
        if s.has(PlayerStatus.ENTANGLED):
            bc.add_to_bot(Actions.remove_player_status(PlayerStatus.ENTANGLED))
        if s.has(PlayerStatus.DOUBLE_TAP):
            bc.add_to_bot(Actions.remove_player_status(PlayerStatus.DOUBLE_TAP))
        if s.has(PlayerStatus.PLATED_ARMOR):
            # PLATED_ARMOR（新状态追加结算）：回合末按层数获得格挡，层数保留
            #（BattleContext.cpp:2068-2070，位于 METALLICIZE 之后；本文件
            # 顺序约束下追加在方法尾，格挡增益相互可交换）
            bc.add_to_bot(Actions.gain_block(s.get(PlayerStatus.PLATED_ARMOR)))

    def apply_at_end_of_round_powers(self, bc: BattleContext) -> None:
        """afterMonsterTurns 阶段：玩家侧临时状态衰减（debuff 每回合 -1，
        怪物施加的首轮跳过——just_applied 语义）。"""
        for s in (PlayerStatus.WEAK, PlayerStatus.VULNERABLE, PlayerStatus.FRAIL,
                  PlayerStatus.NO_BLOCK, PlayerStatus.INTANGIBLE):
            if self.statuses.has(s):
                if self.statuses.just_applied(s):
                    self.statuses.set_just_applied(s, False)
                else:
                    self.statuses.decrement(s)

    def apply_start_of_turn_powers(self, bc: BattleContext) -> None:
        """玩家回合开始：仅限回合开始的清除类状态。

        FLAME_BARRIER 只在获得的当回合有效（"this turn"），回合开始移除。
        """
        s = self.statuses
        if s.has(PlayerStatus.FLAME_BARRIER):
            s.remove(PlayerStatus.FLAME_BARRIER)
        if s.has(PlayerStatus.NEXT_TURN_BLOCK):
            # NEXT_TURN_BLOCK（新状态追加结算）：回合开始按层数获得格挡后
            # 移除（Player.cpp:631-634，GainBlock 动作走 gainBlock 入口）
            bc.add_to_bot(Actions.gain_block(s.get(PlayerStatus.NEXT_TURN_BLOCK)))
            s.remove(PlayerStatus.NEXT_TURN_BLOCK)
        if s.has(PlayerStatus.MAYHEM):
            # Mayhem：回合开始自动打出抽牌堆顶 ×层（Player.cpp:625-629）
            for _ in range(s.get(PlayerStatus.MAYHEM)):
                bc.add_to_bot(Actions.play_top_card(exhaust=False))
        if s.has(PlayerStatus.MAGNETISM):
            # Magnetism：回合开始随机无色牌入手 ×层（Player.cpp:621-623；
            # C++ 该分支为注释掉的 CREATE_RANDOM_CARD_IN_HAND_COLORLESS——
            # 生成逻辑由内容层 play 时提供的 special 闭包执行）
            fn = bc.player.special.get("magnetism_gen")
            if fn is not None:
                for _ in range(s.get(PlayerStatus.MAGNETISM)):
                    bc.add_to_bot(fn())

    def apply_start_of_turn_post_draw_powers(self, bc: BattleContext) -> None:
        """玩家回合开始、抽牌之后（对齐 applyStartOfTurnPostDrawPowers）：

        - DEMON_FORM：+层数 力量（层数 = 每回合增量，2/3）
        - BRUTALITY：失去 1×层 HP（自伤）并抽 1×层
        """
        s = self.statuses
        if s.has(PlayerStatus.DEMON_FORM):
            bc.add_to_bot(Actions.buff_player(PlayerStatus.STRENGTH, s.get(PlayerStatus.DEMON_FORM)))
        if s.has(PlayerStatus.BRUTALITY):
            n = s.get(PlayerStatus.BRUTALITY)
            bc.add_to_bot(Actions.player_lose_hp(n, self_inflicted=True))
            bc.add_to_bot(Actions.draw_cards(n))


class Monster(Combatant):
    """怪物基类。具体怪在 content/monsters.py 子类化：

    - hp_range / 构造逻辑（construct）
    - get_move_for_roll(bc, roll)：意图抽样
    - take_turn(bc)：按当前意图入队动作（对齐 MonsterSpecific.cpp 的 switch）
    - move_history[0] 为当前意图，[1] 为上一回合的
    """

    def __init__(self, idx: int, hp: int, max_hp: int, display_name: str):
        super().__init__(hp, max_hp, display_name)
        self.idx = idx
        self.move_history: list[MoveDef] = []  # [0] 当前（对齐 lightspeed 双槽）
        self.turns_taken = 0
        self.is_dying = False
        self.is_escaping = False  # 逃跑（Looter；逃跑后不可选为目标）
        self.misc_info: int = 0  # 通用实例槽（Guardian 阈值/Wizard 充能/Looter 偷金）
        self.unique_power0: int = 0  # 唯一能力计数槽（Hexaghost 火球计数等）

    # ---- 意图 ----
    @property
    def current_move(self) -> MoveDef:
        return self.move_history[0]

    def set_move(self, move: MoveDef) -> None:
        self.move_history.insert(0, move)
        del self.move_history[2:]

    def roll_move(self, bc: BattleContext) -> None:
        """aiRng 0..99 抽样（对齐 Monster::rollMove）。确定性怪不消耗 roll。"""
        roll = bc.rngs.ai.int_inclusive(0, 99)
        self.set_move(self.get_move_for_roll(bc, roll))

    def get_move_for_roll(self, bc: BattleContext, roll: int) -> MoveDef:
        raise NotImplementedError

    def take_turn(self, bc: BattleContext) -> None:
        raise NotImplementedError

    def buff(self, status: MonsterStatus, amount: int) -> None:
        """怪物自我增益（对齐 Monster::buff 模板）。

        RITUAL 特例：施加即置 justApplied——首个回合末跳过结算
        （Java RitualPower 的 skipFirst），Cultist 黑暗打击序列 6, 9, 12。
        """
        if status == MonsterStatus.RITUAL:
            self.statuses.set_just_applied(MonsterStatus.RITUAL, True)
        self.statuses.add(status, amount)

    # ---- 存活判定 ----
    def is_targetable(self) -> bool:
        return self.alive and not self.is_escaping

    def is_dead_or_escaped(self) -> bool:
        return (not self.alive) or self.is_escaping

    # ---- 逃跑（对齐 lightspeed isEscapingB + 存活数判定）----
    def escape(self, bc: BattleContext) -> None:
        """执行逃跑：不可再被指定，存活数 -1；全员死亡/逃跑则判胜。"""
        if self.is_escaping:
            return
        self.is_escaping = True
        group = bc.monsters
        group.alive_count -= 1
        if group.alive_count <= 0 and bc.outcome == Outcome.UNDECIDED:
            bc.outcome = Outcome.PLAYER_VICTORY
            bc.check_combat()

    # ---- 掉血钩子（onHpLost：分裂/Guardian 模式切换在此覆盖意图）----
    def on_hp_lost(self, bc: BattleContext, amount: int) -> None:
        """受到未被格挡吸收的伤害后触发（内容层按怪覆盖）。"""

    # ---- 战斗中生成怪物的意图补 roll（extraRollMoveOnTurn 的简化）----
    def roll_spawned_move(self, bc: BattleContext) -> None:
        """生成怪立即 roll 一次意图（生成时机在怪物回合外，需补 roll）。"""
        self.roll_move(bc)

    # ---- 受击（对齐 Monster::attacked / damage）----
    def attacked(self, bc: BattleContext, damage: int) -> None:
        if self.is_dead_or_escaped():
            return
        if damage < 0:
            damage = 0
        if self.statuses.has(MonsterStatus.ANGRY):  # onAttacked
            self.statuses.add(MonsterStatus.STRENGTH, self.statuses.get(MonsterStatus.ANGRY))
        self._apply_damage(bc, damage, from_attack=True)

    def damage(self, bc: BattleContext, damage: int) -> None:
        """非攻击 HP 损失（毒、Thorns 反伤等）。"""
        if self.is_dead_or_escaped():
            return
        if damage < 0:
            damage = 0
        self._apply_damage(bc, damage, from_attack=False)

    def _apply_damage(self, bc: BattleContext, damage: int, from_attack: bool) -> None:
        saved_block = self.block
        self.block = max(0, self.block - damage)
        damage -= saved_block
        if damage <= 0:
            return
        if from_attack:
            # THE_BOOT：未被格挡吸收的攻击伤害 <5 提到 5
            damage = bc.relics.on_monster_unblocked_attack_damage(bc, damage)
        if from_attack and self.statuses.has(MonsterStatus.CURL_UP):
            # CURL_UP（对齐 lightspeed attackedUnblockedHelper）：首次受到
            # 未被格挡吸收的攻击伤害时，获得 CURL_UP 层数的格挡。格挡动作
            # 入队 bot——不吸收本次伤害，在当前动作之后落地；一次性消耗。
            # 完全被格挡吸收的伤害不触发（damageUnblockedHelper 无此分支）。
            bc.add_to_bot(Actions.monster_gain_block(self.idx, self.statuses.get(MonsterStatus.CURL_UP)))
            self.statuses.remove(MonsterStatus.CURL_UP)
        if saved_block > 0 and self.block == 0:
            # HAND_DRILL：格挡被打空（attacked/damage 两路径都触发，Monster.cpp:433/488）
            bc.relics.on_monster_block_broken(bc, self)
        self.hp = max(0, self.hp - damage)
        if self.hp == 0:
            self.die(bc)
        else:
            # 沉睡唤醒（对齐 damageUnblockedHelper，Monster.cpp:412-414）：
            # 受到漏格挡伤害即醒并移除 8 层金属化（Lagavulin）
            if self.statuses.has(MonsterStatus.ASLEEP):
                self.statuses.remove(MonsterStatus.ASLEEP)
                self.statuses.decrement(MonsterStatus.METALLICIZE, 8)
            self.on_hp_lost(bc, damage)

    # ---- 死亡（对齐 Monster::die）----
    def die(self, bc: BattleContext) -> None:
        self.is_dying = True
        group = bc.monsters
        group.alive_count -= 1
        # THIEVERY（Looter）：死亡时返还偷走的金币
        if self.statuses.has(MonsterStatus.THIEVERY):
            bc.player.gold += self.misc_info
            self.misc_info = 0
            self.statuses.remove(MonsterStatus.THIEVERY)
        if group.alive_count <= 0:
            # 最后一只死亡：战斗直接结束，SPORE_CLOUD/GREMLIN_HORN 不再施加
            #（对齐 lightspeed die()：monstersAlive==0 时先 return）
            bc.outcome = type(bc.outcome)(1)  # PLAYER_VICTORY
            bc.check_combat()
            return
        if self.statuses.has(MonsterStatus.SPORE_CLOUD):
            # 孢子云（Fungi Beast，对齐 lightspeed die() 的 SPORE_CLOUD 分支）：
            # 死亡时给玩家 2 层易伤（addToTop，插在当前动作后立即执行）。
            # is_source_monster = bc.turn_has_ended：怪物阶段死亡（如反伤）则
            # 置 justApplied 跳过紧随的回合末衰减，玩家回合内死亡则当轮递减。
            bc.add_to_top(Actions.debuff_player(PlayerStatus.VULNERABLE, 2, bc.turn_has_ended))
            self.statuses.remove(MonsterStatus.SPORE_CLOUD)
        # 遗物死亡触发（GREMLIN_HORN：+1 能量 +1 抽；THE_SPECIMEN 等）
        bc.relics.on_monster_death(bc, self)
        bc.check_combat()

    # ---- 回合钩子（对齐 Monster.cpp）----
    def apply_start_of_turn_powers(self, bc: BattleContext) -> None:
        """怪物回合开始（MonsterStartTurnAction）：中毒结算 → 格挡清零 + 起手状态。"""
        s = self.statuses
        if s.has(MonsterStatus.POISON):
            n = s.get(MonsterStatus.POISON)
            self.hp = max(0, self.hp - n)  # 中毒：直伤不吃格挡，随后层数-1
            s.decrement(MonsterStatus.POISON)
            if self.hp == 0:
                self.die(bc)
                return
        self.block = 0
        if s.has(MonsterStatus.METALLICIZE):
            self.block += s.get(MonsterStatus.METALLICIZE)

    def apply_end_of_turn_triggers(self, bc: BattleContext) -> None:
        """atEndOfTurnPreEndTurnCards 时机（范围内无，预留）。"""

    def apply_end_of_round_powers(self, bc: BattleContext) -> None:
        """回合末统一结算（对齐 Monster::applyEndOfRoundPowers 的顺序）：

        Ritual（justApplied 首轮跳过）→ WEAK/VULNERABLE 衰减
        （怪物施加的首轮跳过，玩家施加的当轮就递减）。
        """
        s = self.statuses
        if s.has(MonsterStatus.RITUAL):
            if s.just_applied(MonsterStatus.RITUAL):
                s.set_just_applied(MonsterStatus.RITUAL, False)
            else:
                s.add(MonsterStatus.STRENGTH, s.get(MonsterStatus.RITUAL))
        if s.has(MonsterStatus.WEAK):
            if s.just_applied(MonsterStatus.WEAK):
                s.set_just_applied(MonsterStatus.WEAK, False)
            else:
                s.decrement(MonsterStatus.WEAK)
        if s.has(MonsterStatus.VULNERABLE):
            if s.just_applied(MonsterStatus.VULNERABLE):
                s.set_just_applied(MonsterStatus.VULNERABLE, False)
            else:
                s.decrement(MonsterStatus.VULNERABLE)


class MonsterGroup:
    """怪物组（对齐 lightspeed MonsterGroup）。顺序 = 索引 = 行动顺序。"""

    MAX_MONSTERS = 5  # 同屏上限（Act 1 最大 5 只：Lots of Slimes）

    def __init__(self) -> None:
        self.monsters: list[Monster] = []
        self.alive_count = 0

    def add(self, m: Monster) -> None:
        self.monsters.append(m)
        self.alive_count += 1

    # ---- 战斗中生成/分裂（对齐 lightspeed initSpawnedMonster + 槽位重写）----
    def spawn_replace(self, bc: BattleContext, idx: int, m: Monster) -> None:
        """原位替换槽位（大史莱姆分裂：旧怪已死，M 级继承 HP 上位）。"""
        assert 0 <= idx < self.MAX_MONSTERS
        m.idx = idx
        self.monsters[idx] = m
        self.alive_count += 1
        bc.relics.on_monster_spawned(bc, m)

    def spawn_insert(self, bc: BattleContext, idx: int, m: Monster) -> None:
        """在 idx 前插入新怪，其余后移并重排索引（分裂的第二只）。"""
        assert 0 <= idx <= len(self.monsters) < self.MAX_MONSTERS
        self.monsters.insert(idx, m)
        for i, mm in enumerate(self.monsters):
            mm.idx = i
        self.alive_count += 1
        bc.relics.on_monster_spawned(bc, m)

    @property
    def monster_count(self) -> int:
        return len(self.monsters)

    def do_monster_turn(self, bc: BattleContext) -> None:
        """执行第 monster_turn_idx 个怪物的回合（对齐 MonsterGroup::doMonsterTurn）。"""
        m = self.monsters[bc.monster_turn_idx]
        if not m.is_dead_or_escaped():
            m.take_turn(bc)
        bc.monster_turn_idx += 1

    def apply_pre_turn_logic(self, bc: BattleContext) -> None:
        """所有怪物回合开始（对齐 applyPreTurnLogic）。"""
        for m in self.monsters:
            if not m.is_dead_or_escaped():
                m.apply_start_of_turn_powers(bc)

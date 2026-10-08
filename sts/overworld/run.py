"""局外 run 循环（Phase 3a，2026-10-08）——Act 1 完整一局的模拟器。

房间循环：进节点 → 按房型分派（战斗/精英/火堆/商店/宝箱/事件）→
policy 决策 → 结算掉落 → 路线选择 → 下一节点。row 14 完成后进 Boss，
Boss 胜 = 通关（第 17 层 Boss 宝箱三选一为通关后奖励，照抄本体顺序）。

遭遇池（Exordium.java:107-165 + AbstractDungeon.java:1037-1073）：
- monsterList = 3 弱怪 + 1 首强怪（排除规则）+ 12 强怪，FIFO 消费，
  无 AA / 无 ABA；池空再生成 12 强怪
- eliteMonsterList = 10 精英，无 AA，池空再生成
- bossList = 三 Boss 洗牌取首

战斗经 StsBattleEnv 驱动（battle_policy 为 sts/baselines.py 的
``policy(env) -> int`` 签名），HP/max_hp/药水跨场同步，古茶具休息
标记经 relic_counters 透传。战斗种子从 misc 流派生（分布级，
与局外内容流共用一条流——不对齐本体每层重建语义）。

已知省略（DESIGN/计划边界）：Neow 开局祝福、A1+ 数值、Sozu 领取拦截。
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field

from sts.baselines import MAX_STEPS, random_policy
from sts.combat.relics import RelicId
from sts.content.events import (
    CardChoice,
    EventContext,
    EventDef,
    card_wiki_rarity,
)
from sts.content.potions import PotionDef
from sts.overworld.card_pools import COLORLESS_POOLS
from sts.overworld.card_rewards import get_reward_cards
from sts.overworld.drops import (
    elite_relic_drops,
    gold_reward,
    open_chest,
    roll_potion_drop,
)
from sts.overworld.event_roll import initialize_event_pools, pick_event, roll_unknown_room
from sts.overworld.map_gen import MAP_HEIGHT, RoomKind, StsMap, generate_map
from sts.overworld.policy import RandomPolicy, RunPolicy
from sts.overworld.relic_effects import (
    PendingRelicChoice,
    apply_pickup,
    campfire_options,
    on_enter_rest,
    on_enter_shop,
    rest_heal_bonus,
)
from sts.overworld.relic_pools import RelicPools, roll_tier
from sts.overworld.rng import OverworldRngStreams
from sts.overworld.shop import generate_stock, restock
from sts.overworld.state import DeckCard, RunState
from sts.rng import Rng

logger = logging.getLogger(__name__)

# ---- Act 1 遭遇池（Java 显示名 → 注册名映射）----
_WEAK_POOL = [("cultist", 2.0), ("jaw_worm", 2.0), ("louses", 2.0), ("small_slimes", 2.0)]
_STRONG_POOL = [
    ("blue_slaver", 2.0), ("gremlin_gang", 1.0), ("looter", 2.0), ("large_slime", 2.0),
    ("lots_of_slimes", 1.0), ("exordium_thugs", 1.5), ("exordium_wildlife", 1.5),
    ("red_slaver", 1.0), ("three_louse", 2.0), ("two_fungi_beasts", 2.0),
]
_ELITE_POOL = [("gremlin_nob", 1.0), ("lagavulin", 1.0), ("three_sentries", 1.0)]
_BOSSES = ("guardian", "hexaghost", "slime_boss")

# 首强怪排除规则（Exordium.generateExclusions，按当前列表最后一个弱怪）
_FIRST_STRONG_EXCLUSIONS = {
    "looter": {"exordium_thugs"},
    "jaw_worm": set(),
    "cultist": set(),
    "blue_slaver": {"red_slaver", "exordium_thugs"},
    "louses": {"three_louse"},
    "small_slimes": {"large_slime", "lots_of_slimes"},
}

_CAMPFIRE_HEAL_FRACTION = 30  # 30% max_hp


@dataclass
class RunResult:
    won: bool
    floor: int
    hp: int
    max_hp: int
    gold: int
    deck_size: int
    log: list[str] = field(default_factory=list)


class RunSimulator:
    """一局 Act 1（run_policy 管局外，battle_policy 管战斗内）。"""

    def __init__(
        self,
        run_policy: RunPolicy | None = None,
        battle_policy=None,
        seed: int | None = None,
    ):
        self.run_policy = run_policy or RandomPolicy(seed=seed)
        self.battle_policy = battle_policy or random_policy
        self.seed = seed
        self.state = RunState()
        self.rngs = OverworldRngStreams(seed)
        self.map: StsMap | None = None
        self.pools = RelicPools(self.rngs.relic)
        self._battle_seed_rng = Rng(seed)  # 战斗种子独立小流（与局外流解耦）
        self._relic_choice_queue: list[PendingRelicChoice] = []
        self.log: list[str] = []

    # ---- 入口 ----

    def run(self) -> RunResult:
        self._setup()
        starts = self.map.start_nodes()
        i = self.run_policy.choose_start_node(self.state, [(n.x, n.y) for n in starts])
        cur = (starts[i].x, starts[i].y)
        while not self.state.run_over:
            self._enter_node(cur)
            if self.state.run_over:
                break
            if cur[1] == MAP_HEIGHT - 1:  # row 14 完成 → Boss
                break
            children = self.map.node(*cur).edges
            # 羽翼之靴：有充能时可将同层全部连通节点纳入候选（选非边候选即耗 1 充能）
            from sts.overworld.relic_effects import consume_winged_greaves, winged_greaves_charges_left

            candidates = list(children)
            bypass: list[tuple[int, int]] = []
            if winged_greaves_charges_left(self.state) > 0 and cur[1] + 1 < MAP_HEIGHT:
                row_nodes = [
                    (n.x, n.y)
                    for n in self.map.rows[cur[1] + 1]
                    if self.map.connected(n) and (n.x, n.y) not in children
                ]
                bypass = row_nodes
                candidates = children + row_nodes
            j = self.run_policy.choose_path(self.state, candidates)
            chosen = candidates[j]
            if chosen in bypass:
                consume_winged_greaves(self.state)
                self._log(f"羽翼之靴：无视路线走到 {chosen}")
            cur = chosen
        if not self.state.run_over:
            self._do_boss()
        s = self.state
        return RunResult(
            won=s.run_won,
            floor=s.floor,
            hp=s.hp,
            max_hp=s.max_hp,
            gold=s.gold,
            deck_size=len(s.deck),
            log=self.log,
        )

    def _setup(self) -> None:
        self.map = generate_map(self.rngs.map)
        initialize_event_pools(self.state)
        self._populate_monsters()
        bosses = list(_BOSSES)
        self.rngs.monster.shuffle(bosses)
        self.state.boss = bosses[0]
        self._log(f"地图生成完毕；Boss：{self.state.boss}")

    # ---- 遭遇池 ----

    def _weighted_roll(self, pool: list[tuple[str, float]]) -> str:
        total = sum(w for _, w in pool)
        roll = self.rngs.monster.gen.random() * total
        acc = 0.0
        for name, w in pool:
            acc += w
            if roll < acc:
                return name
        return pool[-1][0]

    def _populate_monsters(self) -> None:
        """3 弱怪 + 1 首强怪（排除规则）+ 12 强怪（无 AA/ABA）+ 10 精英（无 AA）。"""
        monster_list: list[str] = []
        for _ in range(3):
            while True:
                m = self._weighted_roll(_WEAK_POOL)
                if not monster_list or m != monster_list[-1]:
                    monster_list.append(m)
                    break
        exclusions = _FIRST_STRONG_EXCLUSIONS.get(monster_list[-1], set())
        while True:
            m = self._weighted_roll(_STRONG_POOL)
            if m not in exclusions:
                monster_list.append(m)
                break
        for _ in range(12):
            while True:
                m = self._weighted_roll(_STRONG_POOL)
                if m == monster_list[-1]:
                    continue
                if len(monster_list) > 1 and m == monster_list[-2]:
                    continue
                monster_list.append(m)
                break
        elite_list: list[str] = []
        for _ in range(10):
            while True:
                m = self._weighted_roll(_ELITE_POOL)
                if not elite_list or m != elite_list[-1]:
                    elite_list.append(m)
                    break
        self.state.monster_list = monster_list
        self.state.elite_list = elite_list

    def _pop_monster(self) -> str:
        if not self.state.monster_list:
            self._populate_monsters()  # 池空再生成（Java generateStrongEnemies(12)）
            self.state.monster_list = self.state.monster_list[-12:]
        return self.state.monster_list.pop(0)

    def _pop_elite(self) -> str:
        if not self.state.elite_list:
            elites: list[str] = []
            for _ in range(10):
                while True:
                    m = self._weighted_roll(_ELITE_POOL)
                    if not elites or m != elites[-1]:
                        elites.append(m)
                        break
            self.state.elite_list = elites
        return self.state.elite_list.pop(0)

    # ---- 房间分派 ----

    def _enter_node(self, pos: tuple[int, int]) -> None:
        x, y = pos
        self.state.floor = y + 1
        from sts.overworld.relic_effects import on_floor_advance

        on_floor_advance(self.state)
        kind = self.map.room_kind(x, y)
        if kind == RoomKind.MONSTER:
            self._combat(self._pop_monster(), "monster")
        elif kind == RoomKind.ELITE:
            self._combat(self._pop_elite(), "elite")
        elif kind == RoomKind.REST:
            self._campfire()
        elif kind == RoomKind.SHOP:
            self._shop()
        elif kind == RoomKind.TREASURE:
            self._treasure()
        elif kind == RoomKind.EVENT:
            self._unknown_room()

    # ---- 战斗 ----

    def _battle_relic_counters(self) -> dict | None:
        """跨场遗物计数器（战斗构造时预置）：古茶具休息标记 + 壶铃举重次数。"""
        s = self.state
        counters: dict = {}
        if s.counter(RelicId.ANCIENT_TEA_SET) == -2:
            counters[RelicId.ANCIENT_TEA_SET] = -2
        if s.has(RelicId.GIRYA) and s.counter(RelicId.GIRYA) > 0:
            counters[RelicId.GIRYA] = s.counter(RelicId.GIRYA)
        return counters or None

    def _combat(self, encounter: str, room: str, gold_range: tuple[int, int] | None = None, reward_relic: RelicId | None = None) -> bool:
        """打一场战斗并结算掉落。返回是否胜利；死亡置 run_over。"""
        from sts.env import StsBattleEnv

        s = self.state
        self._log(f"第 {s.floor} 层：战斗（{encounter}）HP {s.hp}/{s.max_hp}")
        env = StsBattleEnv(
            encounter=encounter,
            relics=list(s.relics),
            potions=[p for p in s.potions if p is not None] or None,
            deck=[(dc.card, dc.upgraded) for dc in s.deck],
            relic_counters=self._battle_relic_counters(),
        )
        battle_seed = self._battle_seed_rng.gen.integers(0, 2**31 - 1)
        env.reset(seed=int(battle_seed))
        bc = env.bc
        bc.player.max_hp = s.max_hp
        bc.player.hp = min(s.hp, s.max_hp)
        for _ in range(MAX_STEPS):
            if bc.over:
                break
            env.step(self.battle_policy(env))
        # 跨场同步（HP/上限/药水——战斗内用掉的药水以槽位 None 落回）
        s.max_hp = bc.player.max_hp
        s.hp = max(0, bc.player.hp)
        held = [p for p in bc.player.potions if p is not None]
        s.potions = (held + [None] * len(s.potions))[: len(s.potions)]
        if s.counter(RelicId.ANCIENT_TEA_SET) == -2:
            s.set_counter(RelicId.ANCIENT_TEA_SET, 0)  # 休息标记已消费
        if not bc.won:
            self._log(f"战斗失败（{encounter}），run 终止")
            s.run_over = True
            return False
        self._log(f"战斗胜利（{encounter}），剩 HP {s.hp}/{s.max_hp}")
        # ---- 胜利结算 ----
        if gold_range is not None:
            g = self.rngs.treasure.int_inclusive(*gold_range)
        else:
            g = gold_reward(self.rngs, room)
        s.add_gold(g)
        dropped_relics = 0
        if room == "elite":
            for relic in elite_relic_drops(s, self.rngs, self.pools):
                self._gain_relic(relic)
                dropped_relics += 1
        if reward_relic is not None:
            self._gain_relic(reward_relic)
            dropped_relics += 1
        # 药水掉落（Boss 房不掉；reward_count ≈ 金币+遗物条数）
        if room != "boss":
            pd = roll_potion_drop(s, self.rngs, reward_count=1 + dropped_relics)
            if pd is not None:
                self._obtain_potion(pd)
        # 卡牌奖励（Boss 恒稀有；转经轮普通房追加一组）
        self._card_reward(room)
        from sts.overworld.relic_effects import extra_card_reward_after_combat

        if extra_card_reward_after_combat(s, room):
            self._card_reward(room)
        self._drain_relic_choices()
        return True

    def _card_reward(self, room: str) -> None:
        cards = get_reward_cards(self.state, self.rngs, room)
        if not cards:
            return
        i = self.run_policy.choose_card_reward(self.state, cards)
        if i is not None and 0 <= i < len(cards):
            self.state.add_card(cards[i])
            self._log(f"卡牌奖励：选 {cards[i].zh}")

    # ---- 火堆 ----

    def _campfire(self) -> None:
        s = self.state
        on_enter_rest(s)
        options = campfire_options(s)
        i = self.run_policy.choose_campfire(s, options)
        opt = options[i]
        self._log(f"第 {s.floor} 层：火堆（{opt}）")
        if opt == "rest":
            heal = s.max_hp * _CAMPFIRE_HEAL_FRACTION // 100 + rest_heal_bonus(s)
            healed = s.heal(heal)
            if s.has(RelicId.ANCIENT_TEA_SET):
                s.set_counter(RelicId.ANCIENT_TEA_SET, -2)  # 休息标记：下场战斗首回合 +2 能量
            # 捕梦网：休息后可加 1 张无色牌（3 选 1，rollRareOrUncommon 0.3）
            if s.has(RelicId.DREAM_CATCHER):
                cards = []
                for _ in range(3):
                    pool = COLORLESS_POOLS["rare" if self.rngs.card.gen.random() < 0.3 else "uncommon"]
                    cards.append(pool[self.rngs.card.int_inclusive(0, len(pool) - 1)])
                j = self.run_policy.choose_colorless_gain(s, cards)
                if j is not None and 0 <= j < len(cards):
                    s.add_card(cards[j])
                    self._log(f"捕梦网：加 {cards[j].zh}")
        elif opt == "smith":
            candidates = s.upgradable_indices()
            idxs = self.run_policy.choose_card_indices(s, "upgrade", candidates, 1)
            if idxs:
                s.upgrade_card(idxs[0])
                self._log(f"锻造：升级 {s.deck[idxs[0]].key}")
        elif opt == "lift":
            s.set_counter(RelicId.GIRYA, s.counter(RelicId.GIRYA) + 1)
        elif opt == "dig":
            relic = self.pools.take_drop(roll_tier(self.rngs.relic), s)
            self._gain_relic(relic)
        elif opt == "smoke":
            candidates = s.purgable_indices()
            idxs = self.run_policy.choose_card_indices(s, "remove", candidates, 1)
            for idx in sorted(idxs, reverse=True):
                s.remove_card(idx)
        self._drain_relic_choices()

    # ---- 商店 ----

    def _shop(self) -> None:
        s = self.state
        healed = on_enter_shop(s)
        self._log(f"第 {s.floor} 层：商店（餐券回 {healed} HP）" if healed else f"第 {s.floor} 层：商店")
        stock = generate_stock(s, self.rngs, self.pools)
        from sts.overworld.shop import discounted

        for _ in range(60):  # 保险丝：防止策略无限购买
            action = self.run_policy.shop_action(s, stock)
            if action is None:
                break
            kind, idx = action
            if kind == "card":
                slot = stock.cards[idx]
                price = discounted(slot.price, s)
                if price > s.gold:
                    break
                s.spend_gold(price, in_shop=True)
                s.add_card(slot.card)
                self._log(f"商店：买 {slot.card.zh}（{price} 金）")
                restock(s, self.rngs, self.pools, stock, "card", idx)
            elif kind == "relic":
                slot = stock.relics[idx]
                price = discounted(slot.price, s)
                if price > s.gold:
                    break
                s.spend_gold(price, in_shop=True)
                self._gain_relic(slot.relic)
                self._log(f"商店：买遗物 {slot.relic.name}（{price} 金）")
                restock(s, self.rngs, self.pools, stock, "relic", idx)
            elif kind == "potion":
                slot = stock.potions[idx]
                price = discounted(slot.price, s)
                if price > s.gold:
                    break
                s.spend_gold(price, in_shop=True)
                if s.obtain_potion(slot.potion) is None:
                    self._potion_overflow(slot.potion)
                self._log(f"商店：买药水 {slot.potion.zh}（{price} 金）")
                restock(s, self.rngs, self.pools, stock, "potion", idx)
            elif kind == "purge":
                cost = stock.purge_cost(s)
                if cost > s.gold or not s.purgable_indices():
                    break
                s.spend_gold(cost, in_shop=True)
                s.purge_uses += 1
                candidates = s.purgable_indices()
                idxs = self.run_policy.choose_card_indices(s, "remove", candidates, 1)
                for di in sorted(idxs, reverse=True):
                    s.remove_card(di)
                self._log(f"商店：删牌（{cost} 金）")
        self._drain_relic_choices()

    # ---- 宝箱 / ？房 ----

    def _treasure(self) -> None:
        loot = open_chest(self.state, self.rngs, self.pools)
        self.state.add_gold(loot.gold)
        for relic in loot.relics:
            self._gain_relic(relic)
        self._log(f"第 {self.state.floor} 层：宝箱（{loot.gold} 金 + {len(loot.relics)} 遗物）")
        self._drain_relic_choices()

    def _unknown_room(self) -> None:
        s = self.state
        result = roll_unknown_room(s, self.rngs)
        self._log(f"第 {s.floor} 层：？房 → {result}")
        if result == "monster":
            self._combat(self._pop_monster(), "monster")
        elif result == "shop":
            self._shop()
        elif result == "treasure":
            self._treasure()
        else:
            event = pick_event(s, self.rngs)
            if event is None:
                self._log("  事件池已空（无事件）")
            else:
                self._run_event(event)

    # ---- 事件 ----

    def _run_event(self, event: EventDef) -> None:
        s = self.state
        self._log(f"第 {s.floor} 层：事件【{event.zh}】")
        ctx = EventContext(s, self.rngs, self.pools)
        while True:
            options = event.options_fn(s) if event.options_fn else event.options
            valid = [i for i, o in enumerate(options) if o.available is None or o.available(s)]
            if not valid:
                break
            i = self.run_policy.choose_event_option(s, event, list(options), valid)
            outcome = options[i].effect(s, self.rngs, ctx)
            self._log(f"  {outcome.log}")
            if outcome.pending_combat is not None:
                pc = outcome.pending_combat
                won = self._combat(pc.encounter, "elite" if pc.elite else "monster", pc.gold, pc.reward_relic)
                if not won:
                    return  # 死亡
                if not outcome.reopen:
                    break
                continue
            if not outcome.reopen:
                break
        # 挂起选牌 / 遗物选择
        for choice in ctx.pending_cards:
            self._do_card_choice(choice)
        self._relic_choice_queue.extend(ctx.pending_relic_choices)
        self._drain_relic_choices()
        if s.hp <= 0:
            self._log("事件中失去 HP 过多，run 终止")
            s.run_over = True

    def _do_card_choice(self, choice: CardChoice) -> None:
        s = self.state
        if choice.kind in ("remove", "transform", "upgrade", "duplicate", "bonfire_sacrifice"):
            candidates = s.upgradable_indices() if choice.kind == "upgrade" else s.purgable_indices()
            if not candidates:
                return
            idxs = self.run_policy.choose_card_indices(s, choice.kind, candidates, choice.n)
            for idx in sorted(set(idxs), reverse=True):
                if idx not in candidates:
                    continue
                dc = s.deck[idx]
                if choice.kind == "remove":
                    s.remove_card(idx)
                    self._log(f"  移除 {dc.key}")
                elif choice.kind == "transform":
                    from sts.content.events import EventContext

                    EventContext(s, self.rngs, self.pools).transform_deck_card(idx)
                    self._log(f"  变化 {dc.key} → {s.deck[idx].key}")
                elif choice.kind == "upgrade":
                    s.upgrade_card(idx)
                    self._log(f"  升级 {dc.key}")
                elif choice.kind == "duplicate":
                    s.deck.append(DeckCard(dc.card, dc.upgraded))
                    self._log(f"  复制 {dc.key}")
                elif choice.kind == "bonfire_sacrifice":
                    self._bonfire_sacrifice(idx, dc)
        elif choice.kind == "gain_colorless":
            rare = self.rngs.card.gen.random() < 0.3
            pool = COLORLESS_POOLS["rare" if rare else "uncommon"]
            cards = [pool[self.rngs.card.int_inclusive(0, len(pool) - 1)] for _ in range(3)]
            j = self.run_policy.choose_colorless_gain(s, cards)
            if j is not None and 0 <= j < len(cards):
                s.add_card(cards[j])

    def _bonfire_sacrifice(self, idx: int, dc: DeckCard) -> None:
        """篝火精灵献祭（按稀有度给奖励，Bonfire.java:95-142）。"""
        s = self.state
        s.remove_card(idx)
        rar = card_wiki_rarity(dc.card)
        if getattr(dc.card, "ctype", "") == "Curse":
            self._gain_relic(RelicId.SPIRIT_POOP)
            self._log(f"  献祭 {dc.key}：精灵便便")
        elif rar == "basic":
            self._log(f"  献祭 {dc.key}（基础牌，仅移除）")
        elif rar == "common":
            s.heal(5)
            self._log(f"  献祭 {dc.key}：回 5 HP")
        elif rar == "uncommon":
            s.heal(s.max_hp - s.hp)
            self._log(f"  献祭 {dc.key}：回满 HP")
        elif rar == "rare":
            s.gain_max_hp(10)
            s.heal(s.max_hp - s.hp)
            self._log(f"  献祭 {dc.key}：最大生命 +10 并回满")
        else:
            s.heal(5)  # 特殊牌按普通处理（java special 分支）
            self._log(f"  献祭 {dc.key}：回 5 HP")

    # ---- 遗物获得 / 挂起选择 ----

    def _gain_relic(self, relic: RelicId) -> None:
        self._relic_choice_queue.extend(apply_pickup(self.state, relic, self.rngs))
        self._log(f"  获得遗物 {relic.name}")

    def _drain_relic_choices(self) -> None:
        s = self.state
        while self._relic_choice_queue:
            prc = self._relic_choice_queue.pop(0)
            if prc.kind == "remove2":
                candidates = s.purgable_indices()
                idxs = self.run_policy.choose_card_indices(s, "remove", candidates, 2)
                for idx in sorted(set(idxs), reverse=True):
                    if idx in candidates:
                        s.remove_card(idx)
            elif prc.kind == "duplicate":
                idxs = self.run_policy.choose_card_indices(s, "duplicate", list(range(len(s.deck))), 1)
                if idxs and 0 <= idxs[0] < len(s.deck):
                    dc = s.deck[idxs[0]]
                    s.deck.append(DeckCard(dc.card, dc.upgraded))
            elif prc.kind == "transform3_upgrade":
                candidates = s.purgable_indices()
                idxs = self.run_policy.choose_card_indices(s, "transform", candidates, 3)
                ctx = EventContext(s, self.rngs, self.pools)
                for idx in sorted(set(idxs), reverse=True):
                    if idx in candidates:
                        ctx.transform_deck_card(idx)
                        s.deck[idx] = DeckCard(s.deck[idx].card, True)
            elif prc.kind in ("card_reward", "card_reward_x5"):
                for _ in range(1 if prc.kind == "card_reward" else 5):
                    self._card_reward("monster")
            elif prc.kind == "calling_bell":
                from sts.content.cards.curses import CURSE_OF_THE_BELL

                s.add_card(CURSE_OF_THE_BELL)
                for tier in ("common", "uncommon", "rare"):
                    self._gain_relic(self.pools.take_drop(tier, s))

    # ---- 药水 ----

    def _obtain_potion(self, pd: PotionDef) -> None:
        if self.state.obtain_potion(pd) is None:
            self._potion_overflow(pd)

    def _potion_overflow(self, incoming: PotionDef) -> None:
        slot = self.run_policy.choose_potion_discard(self.state, incoming)
        if 0 <= slot < len(self.state.potions):
            dropped = self.state.potions[slot]
            self.state.potions[slot] = incoming
            self._log(f"药水满槽：弃 {dropped.zh if dropped else '空'} 换 {incoming.zh}")
        else:
            self._log(f"药水满槽：弃 {incoming.zh}")

    # ---- Boss ----

    def _do_boss(self) -> None:
        s = self.state
        won = self._combat(s.boss, "boss")
        if not won:
            return
        s.run_over = True
        s.run_won = True
        # 第 17 层：Boss 宝箱三选一（可跳过，BossRelicSelectScreen.java:332-363）
        relics = self.pools.take_boss_chest(s)
        i = self.run_policy.choose_boss_relic(s, relics)
        if i is not None and 0 <= i < len(relics):
            self._gain_relic(relics[i])
        self._log(f"Boss {s.boss} 击败，Act 1 通关！")

    def _log(self, msg: str) -> None:
        self.log.append(msg)
        logger.debug(msg)

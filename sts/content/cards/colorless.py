"""无色卡 39 张（随机池 35 张 + 2026-10-07 补齐的事件 SPECIAL 卡 4 张：灵体/噬咬/J.A.X./仪式匕首——
事件获取，不入随机无色池）。

数值与结算顺序以 lightspeed C++ 为准（BattleContext.cpp useAttackCard L958 起 /
useSkillCard L1203 起 / usePowerCard L1515 起 + Actions.cpp 复合动作 + Cards.h
doesCardExhaust / getEnergyCost / isXCost / cardTargetsEnemy + CardPools.h
srcColorlessCardPool 全表），slaythespire.wiki.gg（A0 基准）交叉校验；
与 C++ / wiki / 任务口径不一致处逐卡注释，汇总见迁移报告。

与本文件外协作者的关系（包化后）：
- ironclad.py：_exhaust_from_hand / _upgrade_in_place 复用；CardDef 取自 _base.py。
  无色常量经包 __init__ 的 eager re-export 暴露，`from sts.content.cards import X`
  路径不变。
- 生成池口径：Chrysalis / Metamorphosis / Discovery 的池 = ironclad.py 自身命名
  空间中对应类型的 CardDef（即铁甲战士卡——与 C++ CombatTypeCardPool /
  CombatCardPool 的"单卡池"口径一致；状态/诅咒卡被类型过滤天然排除）。
  Jack of All Trades / Transmutation / Magnetism 的池 = 全部无色卡 -
  Bandage Up（对齐 CombatColorlessCardPool 的 34 张表，CardPools.h L189）。

引擎依赖（本批次标记方案，接线点见迁移报告）：
- Mayhem / Magnetism：引擎钩子已接（entities.Player.apply_start_of_turn_powers
  的 MAYHEM/MAGNETISM 分支，前置提交 8de8f33），本文件 play 落状态即可，
  回合开始行为可全流程测试。
- Sadistic Nature：PlayerStatus.SADISTIC 已有（types.py 前置提交），play 落
  状态；触发段需 Actions.debuff_enemy / debuff_all_enemy 补 SADISTIC 分支
  （C++ BattleContext.h:292-294）。
- Panache：无 PlayerStatus.PANACHE（types.py 不在可改范围），play 落
  special["panache"] / special["panache_counter"] 标记；触发段与回合开始
  计数复位需引擎接线（C++ Player.cpp:638-639 + onUseXxxCard 四处）。
- Dark Shackles：力量 -9/15 仅本回合（SHACKLED 状态配对回补），回补分支需
  entities.Monster.apply_end_of_turn_triggers 接线（C++ Monster.cpp:62-65）。
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from sts.combat.actions import Actions
from sts.combat.card_manager import MAX_HAND_SIZE
from sts.combat.queue import Action
from sts.combat.types import MonsterStatus, PlayerStatus

from sts.content.cards._base import CardDef, _exhaust_from_hand, _upgrade_in_place

if TYPE_CHECKING:
    from sts.combat.battle import BattleContext
    from sts.combat.card_manager import CardInstance
    from sts.combat.queue import CardQueueItem


# ============================================================
# 公共设施
# ============================================================


def _sample_without_replacement(bc: BattleContext, items: list, n: int) -> list:
    """misc 流无放回抽样（分布级等价 C++ 的 cardRandom 流逐张 random）。"""
    remaining = list(items)
    out = []
    for _ in range(min(n, len(remaining))):
        i = bc.rngs.misc.int_inclusive(0, len(remaining) - 1)
        out.append(remaining.pop(i))
    return out


def _add_temp_to_hand(bc: BattleContext, inst: CardInstance) -> None:
    """临时牌入手；手满落弃牌堆（对齐 moveToHandHelper，Cards 上限 10）。"""
    if len(bc.cards.hand) < MAX_HAND_SIZE:
        bc.cards.hand.append(inst)
    else:
        bc.cards.move_to_discard_pile(inst)


def _cards_of_type(ctype: str) -> list:
    """ironclad.py 自身命名空间中对应类型的卡池（铁甲战士卡；即 C++ CombatTypeCardPool
    的对应物——惰性 re-export 不落 __dict__，天然不含无色卡，与 C++ 口径一致）。"""
    import sts.content.cards as base

    return [g for g in vars(base).values() if isinstance(g, CardDef) and g.ctype == ctype]


def _random_colorless_card(bc: BattleContext) -> CardDef:
    """随机无色卡（CombatColorlessCardPool：35 张无色 - Bandage Up = 34）。"""
    import sys

    import sts.content.cards as base

    pool = [g for g in vars(base).values() if isinstance(g, CardDef) and g.colorless]
    pool += [g for g in vars(sys.modules[__name__]).values() if isinstance(g, CardDef)]
    pool = [c for c in pool if c.name != "Bandage Up"]
    return pool[bc.rngs.misc.int_inclusive(0, len(pool) - 1)]


# ============================================================
# 非普通（uncommon）20 张
# ============================================================


def _bandage_up_play(bc: BattleContext, item: CardQueueItem) -> None:
    # C++ BANDAGE_UP：HealPlayer(up?6:4)；消耗（doesCardExhaust 常开）
    bc.add_to_bot(Actions.heal_player(6 if item.card.upgraded else 4))


def _blind_play(bc: BattleContext, item: CardQueueItem) -> None:
    # C++ BLIND：基础单体 2 虚弱，升级全体 2 虚弱（DebuffAllEnemy）。C++
    # cardTargetsEnemy 仅基础版需要目标——引擎 needs_target 为静态位，升级版
    # 仍要求选目标但效果为全体，不影响结算（迁移报告记录）。
    if item.card.upgraded:
        bc.add_to_bot(Actions.debuff_all_enemy(MonsterStatus.WEAK, 2, False))
    else:
        bc.add_to_bot(Actions.debuff_enemy(item.target, MonsterStatus.WEAK, 2, False))


def _dark_shackles_play(bc: BattleContext, item: CardQueueItem) -> None:
    # C++ DARK_SHACKLES：力量 -(9/15)"本回合"——本体以 SHACKLED 状态在怪的
    # 回合末回补（Monster.cpp:62-65）。C++ 原实现的 SHACKLED 挂在与 ARTIFACT
    # 存在性同向的分支（净效果为怪白得 +9 力量的 bug，且 DebuffEnemy 传正数
    # 又叠一层 bug），此处按 wiki 语义修正：ARTIFACT 抵消则两不落地；否则
    # -X 力量 + X 层 SHACKLED。SHACKLED 回补需引擎接线（见模块注释）。
    x = 15 if item.card.upgraded else 9
    t = item.target

    def run(bc2: BattleContext) -> None:
        m = bc2.monsters.monsters[t]
        if m.is_dead_or_escaped():
            return
        if m.statuses.has(MonsterStatus.ARTIFACT):
            m.statuses.decrement(MonsterStatus.ARTIFACT)
            return
        m.statuses.add(MonsterStatus.STRENGTH, -x)
        m.statuses.add(MonsterStatus.SHACKLED, x)

    bc.add_to_bot(Action(run))


def _deep_breath_play(bc: BattleContext, item: CardQueueItem) -> None:
    # C++ DEEP_BREATH：弃牌堆非空 → 洗回抽牌堆（onShuffle + EmptyDeckShuffle +
    # ShuffleDrawPile 三个动作，本项目 on_shuffle 一体完成），随后抽 1/2。
    # C++/wiki 均无消耗（doesCardExhaust 未收录；任务口径"消耗"为笔误）。
    # 时序：洗牌动作先于出牌收尾（on_after_card_used）执行，刚打出的
    # Deep Breath 尚在 limbo、不在弃牌堆——不参与本次洗回，落弃牌堆待
    # 后续循环（对齐 C++ 净状态，空堆判定也天然不含自身）。
    def run(bc2: BattleContext) -> None:
        if not bc2.cards.discard_pile:
            return  # 空堆：不洗（对齐 C++ 出牌时的空堆判定）
        bc2.on_shuffle()

    bc.add_to_bot(Action(run))
    bc.add_to_bot(Actions.draw_cards(2 if item.card.upgraded else 1))


def _discovery_play(bc: BattleContext, item: CardQueueItem) -> None:
    # C++ DISCOVERY：DiscoveryAction → 3 张不重复随机卡（getTrulyRandomCardInCombat
    # 全类型）→ chooseDiscoveryCard：选中卡 setCostForTurn(0) 入手（手满落弃牌堆）。
    # wiki："选中卡本回合 0 费"；升级仅去掉消耗（doesCardExhaust !upgraded）。
    # 池 = ironclad.py 自身卡（铁甲战士，对齐 CombatCardPool 单卡池口径）。
    if not item.card.upgraded:
        item.exhaust_on_use = True

    def run(bc2: BattleContext) -> None:
        pool = (
            [g for g in _cards_of_type("Attack")]
            + [g for g in _cards_of_type("Skill")]
            + [g for g in _cards_of_type("Power")]
        )
        picks = _sample_without_replacement(bc2, pool, 3)
        cands = [bc2.cards.instantiate(c) for c in picks]

        def on_choose(bc3: BattleContext, chosen: list) -> None:
            for inst in chosen:
                inst.cost_for_turn = 0
                _add_temp_to_hand(bc3, inst)

        bc2.open_card_select(
            cands, on_choose, prompt="发现：选择 1 张随机牌加入手牌（本回合 0 费）"
        )

    bc.add_to_bot(Action(run))


def _dramatic_entrance_play(bc: BattleContext, item: CardQueueItem) -> None:
    # C++ DRAMATIC_ENTRANCE：AttackAllEnemy(up?12:8 + VIGOR)——VIGOR 在
    # calculateCardDamage 内已计一次，C++ 调用点显式相加实为双重计入（同
    # Cleave 的既有口径），本项目以管线单次计入（attack_all_enemy 逐怪走
    # 完整管线）。固有 + 消耗。
    bc.add_to_bot(Actions.attack_all_enemy(12 if item.card.upgraded else 8))


def _enlightenment_play(bc: BattleContext, item: CardQueueItem) -> None:
    # C++ EnlightenmentAction：手牌费用 >1 → 本回合费用 1（costForTurn）；
    # 升级版另把基础费用永久改为 1（"rest of combat"，wiki 同）。X 费（-1）
    # 与已 0/1 费卡不受影响。
    up = item.card.upgraded

    def run(bc2: BattleContext) -> None:
        for c in bc2.cards.hand:
            if c.cost > 1:
                c.cost_for_turn = 1
                if up:
                    c.cost_override = 1

    bc.add_to_bot(Action(run))


def _finesse_play(bc: BattleContext, item: CardQueueItem) -> None:
    # C++ FINESSE：格挡 2/4 + 抽 1
    bc.add_to_bot(Actions.gain_block(bc.calculate_card_block(4 if item.card.upgraded else 2)))
    bc.add_to_bot(Actions.draw_cards(1))


def _flash_of_steel_play(bc: BattleContext, item: CardQueueItem) -> None:
    # C++ FLASH_OF_STEEL：3/6 伤 + 抽 1；不消耗（doesCardExhaust 未收录，
    # wiki 同——任务口径"消耗"为笔误）
    dmg = bc.calculate_card_damage(item, item.target, 6 if item.card.upgraded else 3)
    bc.add_to_bot(Actions.attack_enemy(item.target, dmg))
    bc.add_to_bot(Actions.draw_cards(1))


def _forethought_play(bc: BattleContext, item: CardQueueItem) -> None:
    # C++ FORETHOUGHT：选 1 张手牌放抽牌堆底（insertToDrawPile(0)；抽牌从堆顶
    # 弹出，index 0 = 堆底），费用 >0 的卡"打出前 0 费"（freeToPlayOnce）。
    # 引擎无 freeToPlayOnce 位：以 cost_override=0 近似（该实例本场永久 0 费，
    # 与"仅首次打出免费"的差异只在同名实例被再次抽到重打时显现——迁移报告
    # 记录）。升级版任意张（wiki；C++ 该分支为注释掉的 todo 未实现）。
    up = item.card.upgraded

    def run(bc2: BattleContext) -> None:
        def on_choose(bc3: BattleContext, chosen: list) -> None:
            for inst in chosen:
                if inst.cost > 0:
                    inst.cost_override = 0
                bc3.cards.hand.remove(inst)
                bc3.cards.draw_pile.insert(0, inst)  # 堆底（堆顶 = 列表尾）

        bc2.open_card_select(
            list(bc2.cards.hand), on_choose, can_pick_any_number=up,
            prompt="深谋远虑：选择手牌放到抽牌堆底（0 费直到打出）",
        )

    bc.add_to_bot(Action(run))


def _good_instincts_play(bc: BattleContext, item: CardQueueItem) -> None:
    bc.add_to_bot(Actions.gain_block(bc.calculate_card_block(9 if item.card.upgraded else 6)))


def _impatience_play(bc: BattleContext, item: CardQueueItem) -> None:
    # C++ IMPATIENCE 分支存在 hasAttack 恒 false 的笔误（命中攻击牌时写死
    # `hasAttack = false` 后 break，无条件抽牌）；按 wiki 语义实现：手牌
    # （不含已离手的自身）无攻击牌时抽 2/3。
    if not any(c.card.ctype == "Attack" for c in bc.cards.hand):
        bc.add_to_bot(Actions.draw_cards(3 if item.card.upgraded else 2))


def _jack_of_all_trades_play(bc: BattleContext, item: CardQueueItem) -> None:
    # C++ JackOfAllTradesAction：随机无色卡（CombatColorlessCardPool）入手
    # ×(1/2)。生成卡费用不改动——C++/wiki 均无 0 费条款（任务口径"0 费"
    # 为笔误）。
    def run(bc2: BattleContext) -> None:
        for _ in range(2 if item.card.upgraded else 1):
            inst = bc2.cards.instantiate(_random_colorless_card(bc2))
            _add_temp_to_hand(bc2, inst)

    bc.add_to_bot(Action(run))


def _madness_play(bc: BattleContext, item: CardQueueItem) -> None:
    # C++ MadnessAction：随机 1 张当前费用 >0 的手牌 → cost=0 且
    # costForTurn=0（wiki "本场战斗 0 费"）。X 费（-1）与已 0 费卡不会被
    # 选中；无可选卡时空转。升级仅改费 1→0。
    def run(bc2: BattleContext) -> None:
        cands = [c for c in bc2.cards.hand if c.cost > 0]
        if not cands:
            return
        inst = cands[bc2.rngs.misc.int_inclusive(0, len(cands) - 1)]
        inst.cost_override = 0
        inst.cost_for_turn = 0

    bc.add_to_bot(Action(run))


def _mind_blast_play(bc: BattleContext, item: CardQueueItem) -> None:
    # C++ MIND_BLAST：伤害 = 出牌时的抽牌堆张数；固有（isCardInnate）；
    # 费用 2 → 升级 1（Cards.h）
    dmg = bc.calculate_card_damage(item, item.target, len(bc.cards.draw_pile))
    bc.add_to_bot(Actions.attack_enemy(item.target, dmg))


def _panacea_play(bc: BattleContext, item: CardQueueItem) -> None:
    # C++ PANACEA：ARTIFACT 1/2；消耗
    bc.add_to_bot(Actions.buff_player(PlayerStatus.ARTIFACT, 2 if item.card.upgraded else 1))


def _panic_button_play(bc: BattleContext, item: CardQueueItem) -> None:
    # C++ PANIC_BUTTON：格挡 30/40 + NO_BLOCK 2 层（自身格挡先入队不受影响；
    # NO_BLOCK 玩家自施 → 每回合末各递减一层，持续 2 回合）
    bc.add_to_bot(Actions.gain_block(bc.calculate_card_block(40 if item.card.upgraded else 30)))
    bc.add_to_bot(Actions.debuff_player(PlayerStatus.NO_BLOCK, 2, False))


def _purity_play(bc: BattleContext, item: CardQueueItem) -> None:
    # C++ PURITY：ExhaustMany(up?5:3)——手牌选至多 N 张消耗（wiki "up to"
    # → can_pick_any_number；单候选仍走 CARD_SELECT 因 pick_count>1）。消耗
    # 走内容层统一路径（触发 FNP/Dark Embrace/Sentinel/遗物）。
    limit = 5 if item.card.upgraded else 3

    def run(bc2: BattleContext) -> None:
        def on_choose(bc3: BattleContext, chosen: list) -> None:
            for inst in chosen:
                _exhaust_from_hand(bc3, inst)

        bc2.open_card_select(
            list(bc2.cards.hand), on_choose, pick_count=limit, can_pick_any_number=True,
            prompt=f"净化：选择至多 {limit} 张手牌消耗",
        )

    bc.add_to_bot(Action(run))


def _swift_strike_play(bc: BattleContext, item: CardQueueItem) -> None:
    dmg = bc.calculate_card_damage(item, item.target, 10 if item.card.upgraded else 7)
    bc.add_to_bot(Actions.attack_enemy(item.target, dmg))


def _trip_play(bc: BattleContext, item: CardQueueItem) -> None:
    # C++ TRIP：基础单体 2 易伤，升级全体 2 易伤（目标静态位说明同 Blind）
    if item.card.upgraded:
        bc.add_to_bot(Actions.debuff_all_enemy(MonsterStatus.VULNERABLE, 2, False))
    else:
        bc.add_to_bot(Actions.debuff_enemy(item.target, MonsterStatus.VULNERABLE, 2, False))


# ============================================================
# 稀有（rare）15 张（含 Hand of Greed，2026-10-07 自 ironclad.py 迁入）
# ============================================================


def _apotheosis_play(bc: BattleContext, item: CardQueueItem) -> None:
    # C++ ApotheosisAction：四堆（手/抽/弃/消耗）全部可升级实例升级
    # （canUpgrade：非状态/诅咒、未升级或可多次升级）。时序：升级动作先于
    # 出牌收尾（on_after_card_used）执行，打出的神化尚在 limbo、不在任何
    # 堆——天然不升级自身（wiki：不升级自身）。
    def run(bc2: BattleContext) -> None:
        for pile in (bc2.cards.hand, bc2.cards.draw_pile, bc2.cards.discard_pile, bc2.cards.exhaust_pile):
            for inst in pile:
                if (not inst.upgraded or inst.card.multiple_upgrades) and inst.card.ctype not in ("Status", "Curse"):
                    _upgrade_in_place(inst)

    bc.add_to_bot(Action(run))


def _put_random_typed_cards_in_draw_pile(ctype: str, count: int) -> Action:
    # C++ PutRandomCardsInDrawPile：count 张随机对应类型卡进抽牌堆随机位，
    # 每张 cost=0 且 costForTurn=0（wiki "本场 0 费"→ cost_override=0 永久，
    # cost_for_turn=0 本回合）。生成卡不升级。
    def run(bc2: BattleContext) -> None:
        pool = _cards_of_type(ctype)
        if not pool:
            return
        for _ in range(count):
            card = pool[bc2.rngs.misc.int_inclusive(0, len(pool) - 1)]
            inst = bc2.cards.instantiate(card)
            inst.cost_override = 0
            inst.cost_for_turn = 0
            if bc2.cards.draw_pile:
                idx = bc2.rngs.misc.int_inclusive(0, len(bc2.cards.draw_pile) - 1)
            else:
                idx = 0
            bc2.cards.draw_pile.insert(idx, inst)

    return Action(run)


def _chrysalis_play(bc: BattleContext, item: CardQueueItem) -> None:
    # C++ CHRYSALIS：3/5 张随机技能 0 费入抽牌堆；消耗
    bc.add_to_bot(_put_random_typed_cards_in_draw_pile("Skill", 5 if item.card.upgraded else 3))


def _metamorphosis_play(bc: BattleContext, item: CardQueueItem) -> None:
    # C++ METAMORPHOSIS：3/5 张随机攻击 0 费入抽牌堆；消耗
    bc.add_to_bot(_put_random_typed_cards_in_draw_pile("Attack", 5 if item.card.upgraded else 3))


def _magnetism_gen_action() -> Action:
    # 引擎钩子（entities.apply_start_of_turn_powers 的 MAGNETISM 分支）每层
    # 调 special["magnetism_gen"]() 取一次生成动作：随机无色卡入手。
    def run(bc2: BattleContext) -> None:
        inst = bc2.cards.instantiate(_random_colorless_card(bc2))
        _add_temp_to_hand(bc2, inst)

    return Action(run)


def _magnetism_play(bc: BattleContext, item: CardQueueItem) -> None:
    # C++ MAGNETISM：BuffPlayer<PS::MAGNETISM>(1)（回合开始生成段在 C++ 为
    # 注释掉的 todo；本项目引擎前置提交已接 MAGNETISM 钩子，生成逻辑经
    # special["magnetism_gen"] 注入本内容层闭包）。费用 2 → 升级 1。
    bc.player.special["magnetism_gen"] = _magnetism_gen_action
    bc.add_to_bot(Actions.buff_player(PlayerStatus.MAGNETISM, 1))


def _master_of_strategy_play(bc: BattleContext, item: CardQueueItem) -> None:
    # C++ MASTER_OF_STRATEGY：抽 3/4（升级 +1 张，wiki 同；任务口径 3/5 笔误）；消耗
    bc.add_to_bot(Actions.draw_cards(4 if item.card.upgraded else 3))


def _mayhem_play(bc: BattleContext, item: CardQueueItem) -> None:
    # C++ MAYHEM：BuffPlayer<PS::MAYHEM>(1)；回合开始（Player.cpp:625-629）
    # 每层自动免费打出抽牌堆顶牌（不消耗）。引擎钩子已接（前置提交），可
    # 全流程测试。费用 2 → 升级 1。
    bc.add_to_bot(Actions.buff_player(PlayerStatus.MAYHEM, 1))


def _panache_play(bc: BattleContext, item: CardQueueItem) -> None:
    # C++ PANACHE：BuffPlayer<PS::PANACHE>(up?14:10)——每回合每打 5 张牌，
    # 全体敌人受 PANACHE 值伤害（onUseXxxCard 四处的 panacheCounter 倒数；
    # Player.cpp:638-639 回合开始复位计数）。本引擎无 PlayerStatus.PANACHE
    # （types.py 不在可改范围）：special 标记方案，触发段与计数复位需引擎
    # 接线（见迁移报告）。
    bc.player.special["panache"] = 14 if item.card.upgraded else 10
    bc.player.special["panache_counter"] = 5


def _sadistic_nature_play(bc: BattleContext, item: CardQueueItem) -> None:
    # C++ SADISTIC_NATURE：BuffPlayer<PS::SADISTIC>(up?7:5)——debuffEnemy
    # 落地 debuff 时 DamageEnemy 同值（BattleContext.h:292-294；ARTIFACT
    # 抵消的不触发）。PlayerStatus.SADISTIC 已有（前置提交），play 落状态；
    # 触发段需 Actions.debuff_enemy / debuff_all_enemy 接线（见迁移报告）。
    bc.add_to_bot(Actions.buff_player(PlayerStatus.SADISTIC, 7 if item.card.upgraded else 5))


def _make_draw_to_hand_play(ctype: str, prompt: str):
    def _play(bc: BattleContext, item: CardQueueItem) -> None:
        # C++ SECRET_TECHNIQUE / SECRET_WEAPON：DrawToHandAction——抽牌堆中
        # 对应类型的卡入手（移动非复制；无 → 空转；单候选直执）。消耗仅
        # 基础版（doesCardExhaust !upgraded）。
        if not item.card.upgraded:
            item.exhaust_on_use = True

        def run(bc2: BattleContext) -> None:
            cands = [c for c in bc2.cards.draw_pile if c.card.ctype == ctype]

            def on_choose(bc3: BattleContext, chosen: list) -> None:
                for inst in chosen:
                    bc3.cards.draw_pile.remove(inst)
                    _add_temp_to_hand(bc3, inst)

            bc2.open_card_select(cands, on_choose, prompt=prompt)

        bc.add_to_bot(Action(run))

    return _play


_secret_technique_play = _make_draw_to_hand_play(
    "Skill", "秘术：从抽牌堆选择 1 张技能牌加入手牌"
)
_secret_weapon_play = _make_draw_to_hand_play(
    "Attack", "秘密武器：从抽牌堆选择 1 张攻击牌加入手牌"
)


def _the_bomb_play(bc: BattleContext, item: CardQueueItem) -> None:
    # C++ THE_BOMB：BuffPlayer<PS::THE_BOMB>(up?50:40)（wiki 同为 40/50；
    # 任务口径 40/60 笔误）。本项目既有约定：THE_BOMB 状态 3 层倒数 +
    # special["the_bomb"] 存伤害值（entities.apply_end_of_turn_powers
    # 回合末倒数，归零 damage_all_enemy 爆发）。
    bc.player.special["the_bomb"] = 50 if item.card.upgraded else 40
    bc.add_to_bot(Actions.buff_player(PlayerStatus.THE_BOMB, 3))


def _thinking_ahead_play(bc: BattleContext, item: CardQueueItem) -> None:
    # C++ THINKING_AHEAD："same as upgraded warcry"——抽 2 + WarcryAction
    # （选 1 张手牌置抽牌堆顶）。消耗仅基础版（doesCardExhaust !upgraded）。
    if not item.card.upgraded:
        item.exhaust_on_use = True
    bc.add_to_bot(Actions.draw_cards(2))

    def run(bc2: BattleContext) -> None:
        def on_choose(bc3: BattleContext, chosen: list) -> None:
            for inst in chosen:
                bc3.cards.hand.remove(inst)
                bc3.cards.append_to_draw_top(inst)

        bc2.open_card_select(
            list(bc2.cards.hand), on_choose, prompt="未雨绸缪：选择 1 张手牌置于抽牌堆顶"
        )

    bc.add_to_bot(Action(run))


def _transmutation_play(bc: BattleContext, item: CardQueueItem) -> None:
    # C++ TRANSMUTATION：X 费（isXCost）——TransmutationAction：生成
    # max(energyOnUse,0) 张随机无色卡（升级版生成升级卡，wiki 同），各
    # setCostForTurn(0) 入手（手满落弃牌堆）。能量由引擎 x_cost 路径在
    # 出牌时快照并清零（Whirlwind 同款契约）。
    up = item.card.upgraded

    def run(bc2: BattleContext) -> None:
        for _ in range(max(item.energy_on_use, 0)):
            inst = bc2.cards.instantiate(_random_colorless_card(bc2))
            inst.upgraded = up
            inst.cost_for_turn = 0
            _add_temp_to_hand(bc2, inst)

    bc.add_to_bot(Action(run))


def _violence_play(bc: BattleContext, item: CardQueueItem) -> None:
    # C++ ViolenceAction：抽牌堆随机 3/4 张攻击牌移入手（移动非复制；手满
    # 落弃牌堆；攻击牌不足则全取）。
    count = 4 if item.card.upgraded else 3

    def run(bc2: BattleContext) -> None:
        idxs = [i for i, c in enumerate(bc2.cards.draw_pile) if c.card.ctype == "Attack"]
        if not idxs:
            return
        picks = _sample_without_replacement(bc2, idxs, count)
        chosen = [bc2.cards.draw_pile[i] for i in picks]
        for i in sorted(picks, reverse=True):
            del bc2.cards.draw_pile[i]
        for inst in chosen:
            _add_temp_to_hand(bc2, inst)

    bc.add_to_bot(Action(run))


# ============================================================
# 卡牌定义（费用/消耗位全部对齐 Cards.h getEnergyCost / doesCardExhaust）
# ============================================================


BANDAGE_UP = CardDef("Bandage Up", "包扎", 0, "Skill", "回复 4 生命。\n消耗。",
                     False, True, _bandage_up_play, colorless=True)
BLIND = CardDef("Blind", "致盲", 0, "Skill", "给予 2 层虚弱。",
                True, False, _blind_play, colorless=True)
DARK_SHACKLES = CardDef("Dark Shackles", "黑暗镣铐", 0, "Skill", "让一名敌人在本回合内失去 9 点力量。\n消耗。",
                       True, True, _dark_shackles_play, colorless=True)
DEEP_BREATH = CardDef("Deep Breath", "深呼吸", 0, "Skill", "将你的弃牌堆洗牌后放入你的抽牌堆。\n抽 1 张牌。",
                      False, False, _deep_breath_play, colorless=True)
DISCOVERY = CardDef("Discovery", "发现", 1, "Skill", "从 3 张随机牌中选择 1 张加入你的手牌。这张牌在本回合耗能变为 0。\n消耗。",
                    False, False, _discovery_play, colorless=True)
DRAMATIC_ENTRANCE = CardDef("Dramatic Entrance", "闪亮登场", 0, "Attack", "固有。\n对所有敌人造成 8 点伤害。\n消耗。",
                            False, True, _dramatic_entrance_play, innate=True, colorless=True)
ENLIGHTENMENT = CardDef("Enlightenment", "开悟", 0, "Skill", "在这个回合，你当前手牌中所有牌的耗能降低到 1。",
                        False, False, _enlightenment_play, colorless=True)
FINESSE = CardDef("Finesse", "妙计", 0, "Skill", "获得 2 点格挡。\n抽 1 张牌。",
                  False, False, _finesse_play, colorless=True)
FLASH_OF_STEEL = CardDef("Flash of Steel", "亮剑", 0, "Attack", "造成 3 点伤害。\n抽 1 张牌。",
                         True, False, _flash_of_steel_play, colorless=True)
FORETHOUGHT = CardDef("Forethought", "预谋", 0, "Skill", "将手牌中的一张牌放到抽牌堆的底部。\n并且这张牌在被打出之前，耗能变为 0。",
                      False, False, _forethought_play, colorless=True)
GOOD_INSTINCTS = CardDef("Good Instincts", "优秀直觉", 0, "Skill", "获得 6 点格挡。",
                         False, False, _good_instincts_play, colorless=True)
IMPATIENCE = CardDef("Impatience", "急躁", 0, "Skill", "如果你的手牌中没有攻击牌，抽 2 张牌。",
                     False, False, _impatience_play, colorless=True)
JACK_OF_ALL_TRADES = CardDef("Jack of All Trades", "花样百出", 0, "Skill", "增加 1 张随机无色牌到你的手牌。\n消耗。",
                             False, True, _jack_of_all_trades_play, colorless=True)
MADNESS = CardDef("Madness", "疯狂", 1, "Skill", "你手牌中一张随机牌在本场战斗中耗能变为 0。\n消耗。",
                  False, True, _madness_play, upgraded_cost=0, colorless=True)
MIND_BLAST = CardDef("Mind Blast", "心灵震慑", 2, "Attack", "固有。\n造成你抽牌堆中剩余牌数的伤害。",
                     True, False, _mind_blast_play, innate=True, upgraded_cost=1, colorless=True)
PANACEA = CardDef("Panacea", "万能药", 0, "Skill", "获得 1 层人工制品。\n消耗。",
                  False, True, _panacea_play, colorless=True)
PANIC_BUTTON = CardDef("Panic Button", "应急按钮", 0, "Skill", "获得 30 点格挡。\n你在接下来 2 回合内无法再从卡牌中获得格挡。\n消耗。",
                       False, True, _panic_button_play, colorless=True)
PURITY = CardDef("Purity", "净化", 0, "Skill", "从手牌中选择最多 3 张牌消耗。\n消耗。",
                 False, True, _purity_play, colorless=True)
SWIFT_STRIKE = CardDef("Swift Strike", "迅捷打击", 0, "Attack", "造成 7 点伤害。",
                       True, False, _swift_strike_play, colorless=True)
TRIP = CardDef("Trip", "绊倒", 0, "Skill", "给予 2 层易伤。",
               True, False, _trip_play, colorless=True)  # wiki 口径：0 费（此前误记 1）
APOTHEOSIS = CardDef("Apotheosis", "神化", 2, "Skill", "在本场战斗中升级你的所有牌。\n消耗。",
                     False, True, _apotheosis_play, upgraded_cost=1, colorless=True)
CHRYSALIS = CardDef("Chrysalis", "结茧", 2, "Skill", "在你的抽牌堆中加入\n3 张随机技能牌。他们\n在本场战斗中耗能为 0。\n消耗。",
                    False, True, _chrysalis_play, colorless=True)
MAGNETISM = CardDef("Magnetism", "磁力", 2, "Power", "在每回合开始时，增加一张随机无色牌到你的手牌。",
                    False, False, _magnetism_play, upgraded_cost=1, colorless=True)
MASTER_OF_STRATEGY = CardDef("Master of Strategy", "战略大师", 0, "Skill", "抽 3 张牌。\n消耗。",
                              False, True, _master_of_strategy_play, colorless=True)
MAYHEM = CardDef("Mayhem", "乱战", 2, "Power", "在你的回合开始时，打出你抽牌堆顶部的牌。",
                 False, False, _mayhem_play, upgraded_cost=1, colorless=True)
METAMORPHOSIS = CardDef("Metamorphosis", "羽化", 2, "Skill", "在你的抽牌堆中加入\n3 张随机攻击牌。他们\n在本场战斗中耗能为 0。\n消耗。",
                        False, True, _metamorphosis_play, colorless=True)
PANACHE = CardDef("Panache", "神气制胜", 0, "Power", "你每在同个回合内打出 5 张牌，就对所有敌人造成 10 点伤害。",
                  False, False, _panache_play, colorless=True)
SADISTIC_NATURE = CardDef("Sadistic Nature", "残虐天性", 0, "Power", "每当你对一名敌人造成负面状态，使对方受到 5 点伤害。",
                         False, False, _sadistic_nature_play, colorless=True)
SECRET_TECHNIQUE = CardDef("Secret Technique", "秘密技法", 0, "Skill", "从抽牌堆中选择一张技能牌放入你的手牌。\n消耗。",
                           False, False, _secret_technique_play, colorless=True)
SECRET_WEAPON = CardDef("Secret Weapon", "秘密武器", 0, "Skill", "从抽牌堆中选择一张攻击牌放入你的手牌。\n消耗。",
                       False, False, _secret_weapon_play, colorless=True)
THE_BOMB = CardDef("The Bomb", "炸弹", 2, "Skill", "在 3 回合结束后，对所有敌人造成 40 点伤害。",
                   False, False, _the_bomb_play, colorless=True)
THINKING_AHEAD = CardDef("Thinking Ahead", "深谋远虑", 0, "Skill", "抽 2 张牌，然后将手牌中的一张牌放到你抽牌堆的顶端。消耗。",
                         False, False, _thinking_ahead_play, colorless=True)
TRANSMUTATION = CardDef("Transmutation", "转化", -1, "Skill", "在你的手牌中加入 X 张随机无色牌。它们在本回合的耗能变为 0。\n消耗。",
                        False, True, _transmutation_play, x_cost=True, colorless=True)
VIOLENCE = CardDef("Violence", "暴力", 0, "Skill", "随机将你抽牌堆中 3 张攻击牌加入你的手牌。\n消耗。",
                    False, True, _violence_play, colorless=True)

def _hand_of_greed_play(bc: BattleContext, item: CardQueueItem) -> None:
    up = item.card.upgraded
    dmg = bc.calculate_card_damage(item, item.target, 25 if up else 20)

    def run(bc: BattleContext) -> None:
        # 对齐 HandOfGreedAction：注意 C++ 用 m.damage（非攻击 HP 损失）
        # 而非 attacked——不吃 CURL_UP/ANGRY/THE_BOOT 等受击触发
        #（lightspeed 特有口径，wiki 为普通攻击；伤害数值仍按攻击管线在
        # 出牌时算好）。击杀 → +20/25 金币。
        m = bc.monsters.monsters[item.target]
        if m.is_dead_or_escaped():
            return
        m.damage(bc, dmg)
        bc.check_combat()
        if not m.alive:
            bc.player.gold += 25 if up else 20

    bc.add_to_bot(Action(run))


HAND_OF_GREED = CardDef("Hand of Greed", "贪婪之手", 2, "Attack", "造成 20 点伤害。\n斩杀时，获得 20 金币。",
                        True, False, _hand_of_greed_play, colorless=True)


# ============================================================
# 2026-10-07 补齐批次：事件获取的 SPECIAL 无色卡 4 张（Apparition.java /
# Bite.java / JAX.java / RitualDagger.java）。均为事件奖励/事件替换卡，
# 不入 CombatColorlessCardPool（随机无色池仍 35 张）。
# ============================================================


def _apparition_play(bc: BattleContext, item: CardQueueItem) -> None:
    # Apparition.java：ApplyPowerAction(IntangiblePlayerPower, 1)，无升级数值差
    bc.add_to_bot(Actions.buff_player(PlayerStatus.INTANGIBLE, 1))


APPARITION = CardDef("Apparition", "灵体", 1, "Skill",
                     "获得 1 层无实体。\n消耗。\n虚无。",
                     False, True, _apparition_play,
                     ethereal=True, loses_ethereal_on_upgrade=True)


def _bite_play(bc: BattleContext, item: CardQueueItem) -> None:
    # Bite.java：7/8 伤 + HealAction 2/3（Vampires 事件把打击替换为噬咬）
    up = item.card.upgraded
    dmg = bc.calculate_card_damage(item, item.target, 8 if up else 7)
    bc.add_to_bot(Actions.attack_enemy(item.target, dmg))
    bc.add_to_bot(Actions.heal_player(3 if up else 2))


BITE = CardDef("Bite", "噬咬", 1, "Attack",
               "造成 7 点伤害。\n回复 2 点生命。",
               True, False, _bite_play)


def _jax_play(bc: BattleContext, item: CardQueueItem) -> None:
    # JAX.java：LoseHPAction(3) → StrengthPower 2/3（Hand of Greed 事件）
    bc.add_to_bot(Actions.player_lose_hp(3, self_inflicted=True))
    bc.add_to_bot(Actions.buff_player(PlayerStatus.STRENGTH, 3 if item.card.upgraded else 2))


JAX = CardDef("J.A.X.", "J.A.X.", 0, "Skill",
              "失去 3 点生命。\n获得 2 点力量。", False, False, _jax_play)


def _ritual_dagger_play(bc: BattleContext, item: CardQueueItem) -> None:
    # RitualDagger.java：baseDamage = misc（初始 15，斩杀 +3/5 永久）。
    # "永久"跨场提升属局外存档，单场模拟内以实例 misc_data 计数。
    magic = 5 if item.card.upgraded else 3
    inst = item.card
    dmg = bc.calculate_card_damage(item, item.target, 15 + inst.misc_data)
    bc.add_to_bot(Actions.attack_enemy(item.target, dmg))

    def run(bc2: BattleContext) -> None:
        # 对齐 RitualDaggerAction.update 的斩杀判定：目标死亡（isDying/
        # hp<=0）且非 halfDead 复活路径（REGROW 分支复活后 is_dying=False
        # 且满血，天然不触发）
        m = bc2.monsters.monsters[item.target]
        if m.is_dying or not m.alive:
            inst.misc_data += magic

    bc.add_to_bot(Action(run))


RITUAL_DAGGER = CardDef("Ritual Dagger", "仪式匕首", 1, "Attack",
                        "造成 15 点伤害。\n斩杀时，它在本局游戏中的伤害永久性增加 3。\n消耗。",
                        True, True, _ritual_dagger_play)


__all__ = [
    "APOTHEOSIS", "BANDAGE_UP", "BLIND", "CHRYSALIS", "DARK_SHACKLES", "DEEP_BREATH",
    "DISCOVERY", "DRAMATIC_ENTRANCE", "ENLIGHTENMENT", "FINESSE", "FLASH_OF_STEEL",
    "FORETHOUGHT", "GOOD_INSTINCTS", "IMPATIENCE", "JACK_OF_ALL_TRADES", "MADNESS",
    "MAGNETISM", "MASTER_OF_STRATEGY", "MAYHEM", "METAMORPHOSIS", "MIND_BLAST",
    "PANACEA", "PANACHE", "PANIC_BUTTON", "PURITY", "SADISTIC_NATURE",
    "SECRET_TECHNIQUE", "SECRET_WEAPON", "SWIFT_STRIKE", "THE_BOMB",
    "HAND_OF_GREED", "THINKING_AHEAD", "TRANSMUTATION", "TRIP", "VIOLENCE",
    # 2026-10-07 补齐（事件 SPECIAL 卡，不入随机无色池）,
    "APPARITION", "BITE", "JAX", "RITUAL_DAGGER",
]

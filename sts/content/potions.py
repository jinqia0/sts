"""药水 42 种（2026-10-07 批次，对照本体反编译源码 potions/*.java + 本地化文案）。

结构对齐 CardDef 模式：PotionDef 为纯数据 + use 回调
（(bc, target, potency, choice) -> None，向引擎入队原子动作）。

口径：
- potency 是效果的数值基底；SACRED_BARK 遗物使其 ×2
  （AbstractPotion.getPotency L45-49，battle.use_potion 统一计算）。
- 随机抽样（Discovery 卡池 / 熵变酿制 / 唤蛇油改费）统一走 misc 流
  （本体分别用 cardRng/potionRng/miscRng；DESIGN.md §3 不做轨迹对齐）。
- 战斗内获得药水（Venomology 卡 / 熵变酿制）从全池 42 种均匀抽
  （returnRandomPotion(getAll=true)）。

与本体源码的已知差异（逐处注明）：
- 暗之精华（EssenceOfDarknessAction.java:20-25）：源码外层循环条件是
  `i < orbs.size()`（当前已引导球数），引导会增长该值——实际语义为
  "已引导 ≥1 球时按槽位数生成暗球（含满槽唤起），0 球时空转"。
  文案写"每个充能球栏位"，与 0 球空转并存；按源码字面移植。
- 火焰药水（THORNS 伤害类型 + applyEnemyPowersOnly）与爆炸药水
  （createDamageMatrix(potency, true) 纯伤害）：VulnerablePower 只对
  NORMAL 类型乘 1.5，两者均不过任何乘区——统一走非攻击 HP 损失管线。
- 瓶中精灵（FairyPotion）不可手动使用（auto_only），死亡时经
  entities.Player._hp_was_lost 的免死链自动触发（先于 LIZARD_TAIL）。
- 烟雾弹（SmokeBomb）：非 Boss 战专用（canUse 的 EnemyType.BOSS 拦截），
  使用后玩家逃跑、战斗以 Outcome.ESCAPED 结束（不计胜负）。
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

from sts.combat.actions import Actions
from sts.combat.card_manager import MAX_HAND_SIZE
from sts.combat.queue import Action
from sts.combat.types import (
    MonsterStatus,
    Orb,
    Outcome,
    PlayerStatus,
    Stance,
)

if TYPE_CHECKING:
    from sts.combat.battle import BattleContext


@dataclass(frozen=True)
class PotionDef:
    pid: str  # 本体内部 ID（POTION_ID 常量，与本地化键一致）
    name: str
    zh: str
    description: str
    potency: int = 1  # 效果数值基底（SACRED_BARK ×2 在 use_potion 统一算）
    targeting: bool = False  # 使用需指定存活敌人（恐惧/虚弱/剧毒/火焰药水）
    use: "callable | None" = None  # (bc, target, potency, choice) -> None
    choices: tuple[str, ...] = ()  # 需要二选一的选项（姿态药水）
    auto_only: bool = False  # 不可手动使用（瓶中精灵：死亡自动触发）
    escape_only: bool = False  # 逃跑类（烟雾弹）：Boss 战禁用，结束战斗
    on_player_death: bool = False  # 死亡免死触发（瓶中精灵）
    rarity: str = "common"  # common / uncommon / rare / class（随机池分层参考）


# ============================================================
# 共享助手
# ============================================================


def _discovery_into_hand(bc: BattleContext, pool: list) -> None:
    """Discovery 族（攻击/技能/能力/无色药水）：3 张不重复随机卡 →
    选 1 张入手且本回合 0 费（DiscoveryAction：ShowCardAndAddToHandEffect，
    满手进弃牌堆；Master Reality 升级生成卡）。"""
    picks: list = []
    while len(picks) < 3 and len(picks) < len(pool):
        c = pool[bc.rngs.misc.int_inclusive(0, len(pool) - 1)]
        if c not in picks:
            picks.append(c)
    if not picks:
        return
    insts = [bc.cards.instantiate(c) for c in picks]

    def on_choose(bc2: BattleContext, chosen: list) -> None:
        for inst in chosen:
            if bc2.player.special.get("master_reality"):
                inst.upgraded = True
            inst.cost_for_turn = 0
            if len(bc2.cards.hand) < MAX_HAND_SIZE:
                bc2.cards.move_to_hand(inst)
            else:
                bc2.cards.move_to_discard_pile(inst)

    bc.open_card_select(insts, on_choose, pick_count=1,
                        prompt="选择 1 张牌加入手牌（本回合 0 费）")


def _combat_pool(ctype: str) -> list:
    """铁甲色类型池（DiscoveryAction.generateCardChoices 的口径：
    returnTrulyRandomCardInCombat(type) → CombatTypeCardPool）。"""
    from sts.combat.relics import _combat_card_pool

    return _combat_card_pool(ctype)


def _colorless_pool() -> list:
    from sts.combat.relics import _colorless_card_pool

    return _colorless_card_pool()


def _discard_any_draw_equal(bc: BattleContext) -> None:
    """赌徒特酿 / 赌博筹码共用（GamblingChipAction）：弃任意张 → 抽等量。"""
    cands = list(bc.cards.hand)
    if not cands:
        return

    def on_choose(bc2: BattleContext, chosen: list) -> None:
        for inst in chosen:
            bc2.manual_discard(inst)
        if chosen:
            bc2.add_to_bot(Actions.draw_cards(len(chosen)))

    bc.open_card_select(cands, on_choose, pick_count=len(cands),
                        can_pick_zero=True, can_pick_any_number=True,
                        prompt="弃置任意张手牌，然后抽等量")


# ============================================================
# 药水定义（效果数值 = getPotency(ascension=0) 的基底值）
# ============================================================


def _block_potion_use(bc, target, potency, choice):
    bc.add_to_bot(Actions.gain_block(potency))


def _dexterity_potion_use(bc, target, potency, choice):
    bc.add_to_bot(Actions.buff_player(PlayerStatus.DEXTERITY, potency))


def _energy_potion_use(bc, target, potency, choice):
    bc.add_to_bot(Actions.gain_energy(potency))


def _explosive_potion_use(bc, target, potency, choice):
    # 纯伤害矩阵（isPureDamage=true）：无任何乘区，逐怪非攻击 HP 损失
    bc.add_to_bot(Actions.damage_all_enemy(potency))


def _fire_potion_use(bc, target, potency, choice):
    # THORNS 类型 + applyEnemyPowersOnly：Vulnerable 只乘 NORMAL → 纯伤害
    bc.add_to_bot(Actions.damage_enemy(target, potency))


def _strength_potion_use(bc, target, potency, choice):
    bc.add_to_bot(Actions.buff_player(PlayerStatus.STRENGTH, potency))


def _swift_potion_use(bc, target, potency, choice):
    bc.add_to_bot(Actions.draw_cards(potency))


def _weaken_potion_use(bc, target, potency, choice):
    bc.add_to_bot(Actions.debuff_enemy(target, MonsterStatus.WEAK, potency))


def _fear_potion_use(bc, target, potency, choice):
    bc.add_to_bot(Actions.debuff_enemy(target, MonsterStatus.VULNERABLE, potency))


def _attack_potion_use(bc, target, potency, choice):
    _discovery_into_hand(bc, _combat_pool("Attack"))


def _skill_potion_use(bc, target, potency, choice):
    _discovery_into_hand(bc, _combat_pool("Skill"))


def _power_potion_use(bc, target, potency, choice):
    _discovery_into_hand(bc, _combat_pool("Power"))


def _colorless_potion_use(bc, target, potency, choice):
    _discovery_into_hand(bc, _colorless_pool())


def _steroid_potion_use(bc, target, potency, choice):
    bc.add_to_bot(Actions.buff_player(PlayerStatus.STRENGTH, potency))
    bc.add_to_bot(Actions.buff_player(PlayerStatus.LOSE_STRENGTH, potency))


def _speed_potion_use(bc, target, potency, choice):
    bc.add_to_bot(Actions.buff_player(PlayerStatus.DEXTERITY, potency))
    bc.add_to_bot(Actions.buff_player(PlayerStatus.LOSE_DEXTERITY, potency))


def _blessing_of_the_forge_use(bc, target, potency, choice):
    # ArmamentsAction(true)：升级手牌全部（可多次升级卡例外不适用——药水场景
    # 用 CardInstance.upgrade 的 no-op 语义）
    def upgrade_all(bc2: BattleContext) -> None:
        for inst in list(bc2.cards.hand):
            inst.upgrade()

    bc.add_to_bot(Action(upgrade_all))


def _regen_potion_use(bc, target, potency, choice):
    bc.add_to_bot(Actions.buff_player(PlayerStatus.REGEN_P, potency))


def _ancient_potion_use(bc, target, potency, choice):
    bc.add_to_bot(Actions.buff_player(PlayerStatus.ARTIFACT, potency))


def _liquid_bronze_use(bc, target, potency, choice):
    bc.add_to_bot(Actions.buff_player(PlayerStatus.THORNS, potency))


def _gamblers_brew_use(bc, target, potency, choice):
    _discard_any_draw_equal(bc)


def _essence_of_steel_use(bc, target, potency, choice):
    bc.add_to_bot(Actions.buff_player(PlayerStatus.PLATED_ARMOR, potency))


def _duplication_potion_use(bc, target, potency, choice):
    bc.add_to_bot(Actions.buff_player(PlayerStatus.DUPLICATION, potency))


def _distilled_chaos_use(bc, target, potency, choice):
    # PlayTopCardAction(randomMonster, false) ×potency：抽牌堆顶免费
    # 播放（随机目标，不消耗）——与 Havoc 同一原子动作
    for _ in range(potency):
        bc.add_to_bot(Actions.play_top_card(exhaust=False))


def _liquid_memories_use(bc, target, potency, choice):
    # BetterDiscardPileToHandAction(1, 0)：弃牌堆选 1 张入手、本回合 0 费
    cands = list(bc.cards.discard_pile)
    if not cands:
        return

    def on_choose(bc2: BattleContext, chosen: list) -> None:
        for inst in chosen:
            if inst in bc2.cards.discard_pile:
                bc2.cards.discard_pile.remove(inst)
            inst.cost_for_turn = 0
            if len(bc2.cards.hand) < MAX_HAND_SIZE:
                bc2.cards.move_to_hand(inst)
            else:
                bc2.cards.move_to_discard_pile(inst)

    bc.open_card_select(cands, on_choose, pick_count=potency,
                        prompt="选择弃牌堆中的 1 张牌入手（本回合 0 费）")


def _cultist_potion_use(bc, target, potency, choice):
    bc.add_to_bot(Actions.buff_player(PlayerStatus.RITUAL_P, potency))


def _fruit_juice_use(bc, target, potency, choice):
    # increaseMaxHp(5)：上限与当前同时 +5
    def run(bc2: BattleContext) -> None:
        p = bc2.player
        p.max_hp += potency
        p.hp += potency

    bc.add_to_bot(Action(run))


def _snecko_oil_use(bc, target, potency, choice):
    # 先抽 N（RandomizeHandCostAction 在后：对抽完的手牌随机 0-3 费）
    bc.add_to_bot(Actions.draw_cards(potency))

    def randomize(bc2: BattleContext) -> None:
        for inst in bc2.cards.hand:
            inst.cost_for_turn = bc2.rngs.misc.int_inclusive(0, 3)

    bc.add_to_bot(Action(randomize))


def _smoke_bomb_use(bc, target, potency, choice):
    # 玩家逃跑：战斗立即结束（不计胜负；BodyEscapeAction 等价物）
    def run(bc2: BattleContext) -> None:
        if bc2.outcome == Outcome.UNDECIDED:
            bc2.outcome = Outcome.ESCAPED
            bc2.check_combat()
            bc2.log.append("你使用了烟雾弹，逃离了战斗！")

    bc.add_to_bot(Action(run, clear_on_victory=False))


def _entropic_brew_use(bc, target, potency, choice):
    # 所有空槽获得随机药水（ObtainPotionAction 逐槽，满槽丢弃）
    def run(bc2: BattleContext) -> None:
        for _ in range(len(bc2.player.potions)):
            if any(p is None for p in bc2.player.potions):
                bc2.obtain_potion(random_potion(bc2))

    bc.add_to_bot(Action(run))


def _blood_potion_use(bc, target, potency, choice):
    def run(bc2: BattleContext) -> None:
        bc2.player.heal(bc2.player.max_hp * potency // 100, bc2)

    bc.add_to_bot(Action(run))


def _elixir_use(bc, target, potency, choice):
    # 消耗任意张手牌（ExhaustAction(isRandom=false, anyNumber, canPickZero)）
    cands = list(bc.cards.hand)
    if not cands:
        return

    def on_choose(bc2: BattleContext, chosen: list) -> None:
        for inst in chosen:
            for i, c in enumerate(bc2.cards.hand):
                if c is inst:
                    del bc2.cards.hand[i]
                    break
            bc2.cards.move_to_exhaust_pile(inst)
            bc2.on_card_exhausted(inst)

    bc.open_card_select(cands, on_choose, pick_count=len(cands),
                        can_pick_zero=True, can_pick_any_number=True,
                        prompt="消耗任意张手牌")


def _heart_of_iron_use(bc, target, potency, choice):
    bc.add_to_bot(Actions.buff_player(PlayerStatus.METALLICIZE, potency))


def _poison_potion_use(bc, target, potency, choice):
    bc.add_to_bot(Actions.debuff_enemy(target, MonsterStatus.POISON, potency))


def _cunning_potion_use(bc, target, potency, choice):
    # potency 张升级版 Shiv 入手（MakeTempCardInHandAction(shiv upgraded)）
    def run(bc2: BattleContext) -> None:
        from sts.content.cards.silent import SHIV

        for _ in range(potency):
            if len(bc2.cards.hand) < MAX_HAND_SIZE:
                bc2.cards.create_temp_card_in_hand(SHIV, True)
            else:
                bc2.cards.create_temp_card_in_discard(SHIV, True)

    bc.add_to_bot(Action(run))


def _ghost_in_a_jar_use(bc, target, potency, choice):
    bc.add_to_bot(Actions.buff_player(PlayerStatus.INTANGIBLE, potency))


def _focus_potion_use(bc, target, potency, choice):
    bc.add_to_bot(Actions.buff_player(PlayerStatus.FOCUS, potency))


def _potion_of_capacity_use(bc, target, potency, choice):
    bc.add_to_bot(Actions.modify_orb_slots(potency))


def _essence_of_darkness_use(bc, target, potency, choice):
    # 源码字面：while i < len(orbs): channel potency 暗球（引导使 orbs 增长
    # 至槽位上限后循环终止）——已引导 0 球时无任何效果（已知源码怪癖）
    def run(bc2: BattleContext) -> None:
        i = 0
        while i < len(bc2.player.orbs):
            for _ in range(potency):
                bc2.player.channel_orb(bc2, Orb.DARK)
            i += 1

    bc.add_to_bot(Action(run))


def _bottled_miracle_use(bc, target, potency, choice):
    def run(bc2: BattleContext) -> None:
        from sts.content.cards.watcher import MIRACLE

        for _ in range(potency):
            up = bool(bc2.player.special.get("master_reality"))
            if len(bc2.cards.hand) < MAX_HAND_SIZE:
                bc2.cards.create_temp_card_in_hand(MIRACLE, up)
            else:
                bc2.cards.create_temp_card_in_discard(MIRACLE, up)

    bc.add_to_bot(Action(run))


def _stance_potion_use(bc, target, potency, choice):
    # 姿态二选一（ChooseOneAction(ChooseWrath/ChooseCalm)）
    bc.add_to_bot(
        Actions.change_stance(Stance.WRATH if choice == "wrath" else Stance.CALM)
    )


def _ambrosia_use(bc, target, potency, choice):
    bc.add_to_bot(Actions.change_stance(Stance.DIVINITY))


# ============================================================
# 定义表（42 种：通用 30 + 职业专属 12）
# ============================================================

BLOCK_POTION = PotionDef("Block Potion", "Block Potion", "格挡药水", "获得 12 点格挡。", 12, use=_block_potion_use)
DEXTERITY_POTION = PotionDef("Dexterity Potion", "Dexterity Potion", "灵巧药水", "获得 2 层敏捷。", 2, use=_dexterity_potion_use)
ENERGY_POTION = PotionDef("Energy Potion", "Energy Potion", "能量药水", "获得 2 点能量。", 2, use=_energy_potion_use)
EXPLOSIVE_POTION = PotionDef("Explosive Potion", "Explosive Potion", "爆炸药水", "对所有敌人造成 10 点伤害。", 10, use=_explosive_potion_use)
FIRE_POTION = PotionDef("Fire Potion", "Fire Potion", "火焰药水", "对一个敌人造成 20 点伤害。", 20, targeting=True, use=_fire_potion_use)
STRENGTH_POTION = PotionDef("Strength Potion", "Strength Potion", "力量药水", "获得 2 层力量。", 2, use=_strength_potion_use)
SWIFT_POTION = PotionDef("Swift Potion", "Swift Potion", "迅捷药水", "抽 3 张牌。", 3, use=_swift_potion_use)
WEAK_POTION = PotionDef("Weak Potion", "Weak Potion", "虚弱药水", "施加 3 层虚弱。", 3, targeting=True, use=_weaken_potion_use)
FEAR_POTION = PotionDef("FearPotion", "FearPotion", "恐惧药水", "施加 3 层易伤。", 3, targeting=True, use=_fear_potion_use)
ATTACK_POTION = PotionDef("AttackPotion", "AttackPotion", "攻击药水", "从 3 张随机攻击牌中选择 1 张加入手牌，本回合 0 费。", 1, use=_attack_potion_use)
SKILL_POTION = PotionDef("SkillPotion", "SkillPotion", "技能药水", "从 3 张随机技能牌中选择 1 张加入手牌，本回合 0 费。", 1, use=_skill_potion_use)
POWER_POTION = PotionDef("PowerPotion", "PowerPotion", "能力药水", "从 3 张随机能力牌中选择 1 张加入手牌，本回合 0 费。", 1, use=_power_potion_use)
COLORLESS_POTION = PotionDef("ColorlessPotion", "ColorlessPotion", "无色药水", "从 3 张随机无色牌中选择 1 张加入手牌，本回合 0 费。", 1, use=_colorless_potion_use)
STEROID_POTION = PotionDef("SteroidPotion", "SteroidPotion", "类固醇药水", "获得 5 层力量。回合结束失去。", 5, use=_steroid_potion_use)
SPEED_POTION = PotionDef("SpeedPotion", "SpeedPotion", "迅捷药水", "获得 5 层敏捷。回合结束失去。", 5, use=_speed_potion_use)
BLESSING_OF_THE_FORGE = PotionDef("BlessingOfTheForge", "BlessingOfTheForge", "熔炉的祝福", "本场战斗中升级手牌中的所有牌。", 0, use=_blessing_of_the_forge_use)
REGEN_POTION = PotionDef("Regen Potion", "Regen Potion", "再生药水", "获得 5 层再生。", 5, use=_regen_potion_use)
ANCIENT_POTION = PotionDef("Ancient Potion", "Ancient Potion", "远古药水", "获得 1 层人工制品。", 1, use=_ancient_potion_use)
LIQUID_BRONZE = PotionDef("LiquidBronze", "LiquidBronze", "液态青铜", "获得 3 层荆棘。", 3, use=_liquid_bronze_use)
GAMBLERS_BREW = PotionDef("GamblersBrew", "GamblersBrew", "赌徒特酿", "丢弃任意张牌，然后抽相同数量的牌。", 0, use=_gamblers_brew_use)
ESSENCE_OF_STEEL = PotionDef("EssenceOfSteel", "EssenceOfSteel", "钢铁精华", "获得 4 层重甲。", 4, use=_essence_of_steel_use)
DUPLICATION_POTION = PotionDef("DuplicationPotion", "DuplicationPotion", "复制药水", "本回合你的下一张牌将被打出两次。", 1, use=_duplication_potion_use)
DISTILLED_CHAOS = PotionDef("DistilledChaos", "DistilledChaos", "精炼混沌", "打出你抽牌堆顶部的 3 张牌。", 3, use=_distilled_chaos_use)
LIQUID_MEMORIES = PotionDef("LiquidMemories", "LiquidMemories", "液态记忆", "选择弃牌堆中的一张牌放入手牌，本回合 0 费。", 1, use=_liquid_memories_use)
CULTIST_POTION = PotionDef("CultistPotion", "CultistPotion", "邪教徒药水", "在你的回合结束时获得 1 层力量。", 1, use=_cultist_potion_use)
FRUIT_JUICE = PotionDef("Fruit Juice", "Fruit Juice", "果汁", "获得 5 点最大生命值。", 5, use=_fruit_juice_use)
SNECKO_OIL = PotionDef("SneckoOil", "SneckoOil", "唤蛇油", "抽 5 张牌。随机化手牌费用。", 5, use=_snecko_oil_use)
FAIRY_POTION = PotionDef("FairyPotion", "FairyPotion", "瓶中精灵", "当你要死亡时，免死并回复到 30% 最大生命值。", 30, auto_only=True, on_player_death=True)
SMOKE_BOMB = PotionDef("SmokeBomb", "SmokeBomb", "烟雾弹", "从一场非 Boss 战斗中逃离。", 0, escape_only=True, use=_smoke_bomb_use)
ENTROPIC_BREW = PotionDef("EntropicBrew", "EntropicBrew", "熵变酿制", "在所有空药水栏位中获得随机药水。", 0, use=_entropic_brew_use)

# ---- 职业专属（随机全池包含；铁甲初始掉落池为其前 3 个 + 通用 30）----
BLOOD_POTION = PotionDef("BloodPotion", "BloodPotion", "血瓶", "回复 20% 最大生命值。", 20, use=_blood_potion_use, rarity="class")
ELIXIR_POTION = PotionDef("ElixirPotion", "ElixirPotion", "万灵药", "消耗任意张手牌。", 0, use=_elixir_use, rarity="class")
HEART_OF_IRON = PotionDef("HeartOfIron", "HeartOfIron", "铁之心", "获得 6 层金属化。", 6, use=_heart_of_iron_use, rarity="class")
POISON_POTION = PotionDef("Poison Potion", "Poison Potion", "剧毒药水", "施加 6 层中毒。", 6, targeting=True, use=_poison_potion_use, rarity="class")
CUNNING_POTION = PotionDef("CunningPotion", "CunningPotion", "狡诈药水", "将 3 张升级的瞬步加入手牌。", 3, use=_cunning_potion_use, rarity="class")
GHOST_IN_A_JAR = PotionDef("GhostInAJar", "GhostInAJar", "罐中幽灵", "获得 1 层无实体。", 1, use=_ghost_in_a_jar_use, rarity="class")
FOCUS_POTION = PotionDef("FocusPotion", "FocusPotion", "专注药水", "获得 2 层聚能。", 2, use=_focus_potion_use, rarity="class")
POTION_OF_CAPACITY = PotionDef("PotionOfCapacity", "PotionOfCapacity", "容量药水", "获得 2 个充能球栏位。", 2, use=_potion_of_capacity_use, rarity="class")
ESSENCE_OF_DARKNESS = PotionDef("EssenceOfDarkness", "EssenceOfDarkness", "暗之精华", "每个充能球栏位生成暗球（0 球时无效果——源码怪癖）。", 1, use=_essence_of_darkness_use, rarity="class")
BOTTLED_MIRACLE = PotionDef("BottledMiracle", "BottledMiracle", "瓶装奇迹", "将 2 张奇迹加入手牌。", 2, use=_bottled_miracle_use, rarity="class")
STANCE_POTION = PotionDef("StancePotion", "StancePotion", "姿态药水", "进入平静或愤怒。", 0, choices=("wrath", "calm"), use=_stance_potion_use, rarity="class")
AMBROSIA = PotionDef("Ambrosia", "Ambrosia", "神酒", "进入神威。", 2, use=_ambrosia_use, rarity="class")

ALL_POTIONS: list[PotionDef] = [
    # 通用 30
    BLOCK_POTION, DEXTERITY_POTION, ENERGY_POTION, EXPLOSIVE_POTION,
    FIRE_POTION, STRENGTH_POTION, SWIFT_POTION, WEAK_POTION, FEAR_POTION,
    ATTACK_POTION, SKILL_POTION, POWER_POTION, COLORLESS_POTION,
    STEROID_POTION, SPEED_POTION, BLESSING_OF_THE_FORGE, REGEN_POTION,
    ANCIENT_POTION, LIQUID_BRONZE, GAMBLERS_BREW, ESSENCE_OF_STEEL,
    DUPLICATION_POTION, DISTILLED_CHAOS, LIQUID_MEMORIES, CULTIST_POTION,
    FRUIT_JUICE, SNECKO_OIL, FAIRY_POTION, SMOKE_BOMB, ENTROPIC_BREW,
    # 职业专属 12
    BLOOD_POTION, ELIXIR_POTION, HEART_OF_IRON, POISON_POTION,
    CUNNING_POTION, GHOST_IN_A_JAR, FOCUS_POTION, POTION_OF_CAPACITY,
    ESSENCE_OF_DARKNESS, BOTTLED_MIRACLE, STANCE_POTION, AMBROSIA,
]

# 铁甲战士的药水掉落池（PotionHelper.getPotions(IRONCLAD)：3 专属 + 通用 30）
IRONCLAD_POTION_POOL: list[PotionDef] = [
    BLOOD_POTION, ELIXIR_POTION, HEART_OF_IRON,
    *[p for p in ALL_POTIONS if p.rarity == "common"],
]


def random_potion(bc: BattleContext) -> PotionDef:
    """战斗内随机药水（returnRandomPotion(true)：全池 42 均匀抽，misc 流）。"""
    return ALL_POTIONS[bc.rngs.misc.int_inclusive(0, len(ALL_POTIONS) - 1)]


__all__ = [
    "PotionDef", "ALL_POTIONS", "IRONCLAD_POTION_POOL", "random_potion",
    "BLOCK_POTION", "DEXTERITY_POTION", "ENERGY_POTION", "EXPLOSIVE_POTION",
    "FIRE_POTION", "STRENGTH_POTION", "SWIFT_POTION", "WEAK_POTION",
    "FEAR_POTION", "ATTACK_POTION", "SKILL_POTION", "POWER_POTION",
    "COLORLESS_POTION", "STEROID_POTION", "SPEED_POTION",
    "BLESSING_OF_THE_FORGE", "REGEN_POTION", "ANCIENT_POTION", "LIQUID_BRONZE",
    "GAMBLERS_BREW", "ESSENCE_OF_STEEL", "DUPLICATION_POTION",
    "DISTILLED_CHAOS", "LIQUID_MEMORIES", "CULTIST_POTION", "FRUIT_JUICE",
    "SNECKO_OIL", "FAIRY_POTION", "SMOKE_BOMB", "ENTROPIC_BREW",
    "BLOOD_POTION", "ELIXIR_POTION", "HEART_OF_IRON", "POISON_POTION",
    "CUNNING_POTION", "GHOST_IN_A_JAR", "FOCUS_POTION", "POTION_OF_CAPACITY",
    "ESSENCE_OF_DARKNESS", "BOTTLED_MIRACLE", "STANCE_POTION", "AMBROSIA",
]

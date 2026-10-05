"""遗物容器与战斗内钩子（对齐 lightspeed RelicContainer + BattleContext::initRelics）。

设计（对齐 lightspeed，Python 化）：
- RelicContainer = 保序 id 列表 + frozenset（O(1) has）+ 计数 dict
  （对齐 vector<RelicInstance> + relicBits 位图 + relic.data 计数器）。
- **没有通用钩子分发机制**：所有遗物效果是各钩子方法内的固定顺序
  if 查询（对齐 lightspeed 硬编码顺序——同 hook 多遗物按固定序结算，
  非获取顺序）。
- 战斗开始分三桶（对齐 initRelics）：即时效果（获取顺序）→ 抽牌前
  桶（影响抽牌数）→ 抽牌后桶（Bag of Marbles 等）。
- 需要 RNG 的遗物用 misc 流（DESIGN.md §3 不做轨迹对齐）。

钩子位已全部在本文件就位；引擎层（battle/entities）只调用这些方法，
不感知具体遗物。**未实现的遗物在对应钩子中留有 TODO 标注**，迁移时
逐个补齐 if 分支 + 测试（tests/test_relics.py）。
"""

from __future__ import annotations

from enum import IntEnum
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from sts.combat.battle import BattleContext
    from sts.combat.card_manager import CardInstance
    from sts.combat.entities import Monster
    from sts.combat.queue import CardQueueItem

from sts.combat.actions import Actions
from sts.combat.types import MonsterStatus, PlayerStatus


class RelicId(IntEnum):
    """战斗内生效遗物（Act 1 迁移范围 ~55 个；局外遗物不收录）。"""

    # ---- 战斗开始-即时效果 ----
    BURNING_BLOOD = 0  # 铁甲开局：战斗胜利回复 6 HP
    AKABEKO = 1  # lightspeed 实现为开局一次性 VIGOR 8（与原版每回合首次攻击+8 不同，按 lightspeed 移植）
    ANCHOR = 2  # 战斗开始 +10 格挡
    BLOOD_VIAL = 3  # 战斗开始回复 2 HP
    GIRYA = 4  # 战斗开始 +data 力量（计数器存举重次数）
    VAJRA = 5  # 战斗开始 +1 力量
    LANTERN = 6  # 首回合 +1 能量
    BRONZE_SCALES = 7  # 战斗开始获得 1 层 THORNS
    ODDLY_SMOOTH_STONE = 8  # 战斗开始 +1 敏捷
    DU_VU_DOLL = 9  # 每有一个诅咒 +1 力量
    THREAD_AND_NEEDLE = 10  # 战斗开始获得 4 层 PLATED_ARMOR（怪物侧状态？玩家 plated armor）TODO
    MUTAGENIC_STRENGTH = 11  # 战斗开始 +1 力量，首回合末失去
    SLING_OF_COURAGE = 12  # TODO
    PRESERVED_INSECT = 13  # 首回合对非 Boss 最高血怪施加 9 层易伤？TODO 数值核实
    PANTOGRAPH = 14  # TODO
    NEOWS_LAMENT = 15  # TODO
    FOSSILIZED_HELIX = 16  # TODO
    DATA_DISK = 17  # TODO
    ECTOPLASM = 18  # 能量 +1，无法获得金币（战斗内无经济，仅能量）
    SOZU = 19  # 能量 +1，无法使用药水（药水未迁移，仅能量）
    BUSTED_CROWN = 20  # 能量 +2，奖励卡 -2（局外，战斗内仅能量）
    COFFEE_DRIPPER = 21  # 能量 +1（营地限制为局外）
    CURSED_KEY = 22  # 能量 +1（宝箱限制为局外）
    FUSION_HAMMER = 23  # 能量 +2（熔炉限制为局外）
    RUNIC_DOME = 24  # 能量 +1，看不到意图（信息边界：观测侧处理，批次 5）
    VELVET_CHOKER = 25  # 能量 +1，手牌 ≥6 不能出牌
    PHILOSOPHERS_STONE = 26  # 能量 +1，新生怪物 +1 力量
    MARK_OF_PAIN = 27  # 能量 +1，战斗开始 2 张 Wound 洗入抽牌堆
    SNECKO_EYE = 28  # 抽牌 +2，自弃 CONFUSED（CONFUSED 未迁移：TODO 仅抽牌）
    HAPPY_FLOWER = 29  # 每 3 回合 +1 能量
    INCENSE_BURNER = 30  # 每 2 回合获得 1 层 ARTIFACT
    INK_BOTTLE = 31  # TODO（打出 10 张牌 +1 力量）
    INSERTER = 32  # 每 2 回合 1 张保留 TODO（Retain 未实现）
    NUNCHAKU = 33  # 每打出 10 张攻击牌 +1 能量
    PEN_NIB = 34  # 打出第 10 张攻击牌后，下一张攻击伤害翻倍
    SUNDIAL = 35  # 每洗 3 次牌 +2 能量
    OMAMORI = 36  # TODO（抵消 1 次诅咒）
    LIZARD_TAIL = 37  # TODO（免死一次）
    MERCURY_HOURGLASS = 38  # 每回合开始对所有敌人 3 伤
    RED_SKULL = 39  # 每回合首次失去 HP +1 力量
    # ---- 战斗开始-抽牌前桶 ----
    TOOLBOX = 40  # RNG：战斗开始 1 张随机无色牌入手
    # ---- 战斗开始-抽牌后桶 ----
    BAG_OF_MARBLES = 41  # 战斗开始对所有敌人施加 1 层易伤
    BAG_OF_PREPARATION = 42  # 首回合额外抽 2 张
    CLOCKWORK_SOUVENIR = 43  # 战斗开始获得 1 层 ARTIFACT
    GREMLIN_VISAGE = 44  # TODO
    RED_MASK = 45  # TODO
    TWISTED_FUNNEL = 46  # 战斗开始对所有敌人施加 4 层中毒
    # ---- 回合开始（固定序）----
    ART_OF_WAR = 47  # 上回合未打出攻击牌 → +1 能量
    HORN_CLEAT = 48  # 每 5 回合 +14 格挡
    DAMARU = 49  # 每回合 +1 敏捷
    CAPTAINS_WHEEL = 50  # 每 3 回合 +3 格挡？TODO 数值核实
    EMOTION_CHIP = 51  # TODO
    POCKETWATCH = 52  # 上回合未打出任何牌 → 回复 6 HP
    ICE_CREAM = 53  # 能量回合结束不清空
    WARPED_TONGS = 54  # RNG：回合开始 50% 随机升级手牌 1 张
    # ---- 出牌类 ----
    KUNAI = 55  # 每回合每打出 3 张攻击牌 +1 敏捷
    ORNAMENTAL_FAN = 56  # 每打出 3 张攻击牌获得 4 格挡
    SHURIKEN = 57  # 每回合每打出 3 张攻击牌 +1 力量
    NECRONOMICON = 58  # TODO（首个攻击牌打两次，每场一次）
    DUALITY = 59  # TODO
    LETTER_OPENER = 60  # 每打出 3 张技能牌对所有敌人 4 伤
    BIRD_FACED_URN = 61  # 每打出能力牌回复 2 HP
    MUMMIFIED_HAND = 62  # RNG：打出能力牌后随机 1 张手牌本回合 0 费
    # ---- 伤害计算 ----
    STRIKE_DUMMY = 63  # Strike 牌 +3 伤
    WRIST_BLADE = 64  # 0 费攻击牌 +4 伤
    PAPER_PHROG = 65  # 易伤倍率 1.5 → 1.75
    # ---- 回合结束 ----
    CLOAK_CLASP = 66  # 回合末按手牌数获得格挡
    NILRYS_CODEX = 67  # TODO（选卡，需 CARD_SELECT）
    ORICHALCUM = 68  # 回合末若无格挡 +6 格挡
    STONE_CALENDAR = 69  # 第 7 回合末对所有敌人 52 伤
    RUNIC_PYRAMID = 70  # 回合末不弃手牌
    # ---- 受击/HP 类 ----
    TUNGSTEN_ROD = 71  # 每次受到 HP 损失 -1
    TORII = 72  # ≤5 点攻击伤害降为 1
    CENTENNIAL_PUZZLE = 73  # 每场首次失去 HP 抽 3 张牌
    SELF_FORMING_CLAY = 74  # 每回合首次失去 HP +3 格挡
    MAGIC_FLOWER = 75  # TODO
    RUNIC_CUBE = 76  # TODO
    MEAT_ON_THE_BONE = 77  # 战斗结束时若 HP ≤50% 回复 12
    # ---- 洗牌/消耗/死亡 ----
    THE_ABACUS = 78  # 每次洗牌 +6 格挡
    CHARONS_ASHES = 79  # 每消耗 1 张牌对所有敌人 2 伤
    DEAD_BRANCH = 80  # RNG：消耗 1 张牌随机 1 张牌入手
    STRANGE_SPOON = 81  # RNG：打出会消耗的牌 50% 不消耗
    GREMLIN_HORN = 82  # 怪物死亡 +1 能量 +1 抽
    THE_SPECIMEN = 83  # TODO
    HAND_DRILL = 84  # TODO（打空怪物格挡时施加 2 层虚弱？数值待核）
    THE_BOOT = 85  # <5 的未格挡攻击伤害提到 5
    # ---- 出牌资格/手牌 ----
    UNCEASING_TOP = 86  # 手牌打空抽 1 张
    # ---- 格挡衰减 ----
    CALIPERS = 87  # 回合开始保留 15 点格挡
    # ---- RNG/生成类 ----
    ENCHIRIDION = 88  # TODO：战斗开始 1 张随机能力牌入手（1 费）


class RelicContainer:
    """保序遗物列表 + O(1) 集合查询 + 每回合计数器。

    计数器语义（对齐 lightspeed relic.data）：GIRYA 力量等跨回合持久；
    KUNAI/SHURIKEN/NUNCHAKU 等每回合计数在 on_turn_start 重置。
    """

    def __init__(self, relic_ids: list[RelicId] | None = None):
        self.relics: list[RelicId] = list(relic_ids or [])  # 获取顺序
        self._set = frozenset(self.relics)
        self.counters: dict[RelicId, int] = {r: 0 for r in self.relics}

    def has(self, rid: RelicId) -> bool:
        return rid in self._set

    def counter(self, rid: RelicId) -> int:
        return self.counters.get(rid, 0)

    def set_counter(self, rid: RelicId, v: int) -> None:
        if rid in self.counters:
            self.counters[rid] = v

    def bump(self, rid: RelicId) -> int:
        """计数器 +1 并返回新值（不存在时为 no-op 返回 -1）。"""
        if rid in self.counters:
            self.counters[rid] += 1
            return self.counters[rid]
        return -1

    # ============================================================
    # 战斗开始（对齐 initRelics 三桶；引擎 _init_content 按序调用）
    # ============================================================
    def on_battle_start_immediate(self, bc: BattleContext) -> None:
        """即时效果：获取顺序生效，发生在首回合格挡清零之后、抽牌之前。"""
        p = bc.player
        for rid in self.relics:
            if rid == RelicId.VAJRA:
                p.statuses.add(PlayerStatus.STRENGTH, 1)
            elif rid == RelicId.ANCHOR:
                p.gain_block(bc, 10)
            elif rid == RelicId.BLOOD_VIAL:
                p.heal(2)
            elif rid == RelicId.AKABEKO:
                # lightspeed 实现为开局一次性 VIGOR 8（非原版每回合首次攻击+8），
                # 分布级差异已记录，按 lightspeed 移植
                p.statuses.add(PlayerStatus.VIGOR, 8)
            elif rid == RelicId.GIRYA:
                p.statuses.add(PlayerStatus.STRENGTH, self.counter(RelicId.GIRYA))
            elif rid == RelicId.BRONZE_SCALES:
                p.statuses.add(PlayerStatus.THORNS, 1)
            elif rid == RelicId.ODDLY_SMOOTH_STONE:
                p.statuses.add(PlayerStatus.DEXTERITY, 1)
            elif rid == RelicId.MUTAGENIC_STRENGTH:
                p.statuses.add(PlayerStatus.STRENGTH, 1)
                p.statuses.add(PlayerStatus.LOSE_STRENGTH, 1)
            elif rid == RelicId.PHILOSOPHERS_STONE:
                # 新生怪物 +1 力量：战斗开始时已有怪物全部算"新生"
                for m in bc.monsters.monsters:
                    m.statuses.add(MonsterStatus.STRENGTH, 1)
            elif rid == RelicId.MARK_OF_PAIN:
                # 能量 +1 属每回合同加成（见 extra_energy_per_turn）；此处仅洗伤口
                from sts.content.cards import WOUND

                bc.add_to_bot(Actions.make_temp_card_in_draw_pile(WOUND, False, shuffle_into=True))
                bc.add_to_bot(Actions.make_temp_card_in_draw_pile(WOUND, False, shuffle_into=True))
            elif rid == RelicId.LANTERN:
                p.energy += 1  # 首回合额外 1 能量
            elif rid == RelicId.PRESERVED_INSECT:
                # 非 Boss 战斗：血量最高的怪 9 层易伤
                if bc.monsters.monsters:
                    m = max(bc.monsters.monsters, key=lambda m: m.max_hp)
                    bc.add_to_bot(Actions.debuff_enemy(m.idx, MonsterStatus.VULNERABLE, 9, False))
            else:
                # TODO 批次 1：DU_VU_DOLL/THREAD_AND_NEEDLE/SLING_OF_COURAGE/
                # PANTOGRAPH/NEOWS_LAMENT/FOSSILIZED_HELIX/DATA_DISK/ENCHIRIDION/
                # SNECKO_EYE 的自弃/OMAMORI/LIZARD_TAIL 计数器装载
                pass

    def on_battle_start_extra_draw(self, bc: BattleContext) -> int:
        """抽牌前桶：影响首回合抽牌数。"""
        extra = 0
        if self.has(RelicId.BAG_OF_PREPARATION):
            extra += 2
        if self.has(RelicId.SNECKO_EYE):
            extra += 2  # CONFUSED 自弃未迁移（TODO）
        return extra

    def on_battle_start_post_draw(self, bc: BattleContext) -> None:
        """抽牌后桶（Bag of Marbles 等，即时结算）。"""
        if self.has(RelicId.BAG_OF_MARBLES):
            bc.add_to_bot(Actions.debuff_all_enemy(MonsterStatus.VULNERABLE, 1, False))
        if self.has(RelicId.TWISTED_FUNNEL):
            bc.add_to_bot(Actions.debuff_all_enemy(MonsterStatus.POISON, 4, False))
        if self.has(RelicId.CLOCKWORK_SOUVENIR):
            bc.player.statuses.add(PlayerStatus.ARTIFACT, 1)
        if self.has(RelicId.MERCURY_HOURGLASS):
            bc.add_to_bot(Actions.damage_all_enemy(3))
        if self.has(RelicId.TOOLBOX):
            # TODO 批次 3（RNG 遗物）：随机无色牌入手
            pass
        # TODO 批次 1：GREMLIN_VISAGE/RED_MASK/ENCHIRIDION

    # ============================================================
    # 回合开始（after_monster_turns，固定序对齐 lightspeed 字母序）
    # ============================================================
    def on_turn_start(self, bc: BattleContext) -> None:
        p = bc.player
        # 每回合计数器重置（KUNAI/SHURIKEN 连击类 + "每回合一次"类）
        for rid in (RelicId.KUNAI, RelicId.SHURIKEN, RelicId.NUNCHAKU,
                    RelicId.ORNAMENTAL_FAN, RelicId.LETTER_OPENER, RelicId.INK_BOTTLE,
                    RelicId.RED_SKULL, RelicId.SELF_FORMING_CLAY):
            if rid in self.counters:
                self.counters[rid] = 0
        if self.has(RelicId.ART_OF_WAR):
            if p.attacks_played_last_turn == 0:
                bc.add_to_bot(Actions.gain_energy(1))
        if self.has(RelicId.DAMARU):
            p.statuses.add(PlayerStatus.DEXTERITY, 1)
        if self.has(RelicId.HAPPY_FLOWER):
            if self.bump(RelicId.HAPPY_FLOWER) == 3:
                self.set_counter(RelicId.HAPPY_FLOWER, 0)
                bc.add_to_bot(Actions.gain_energy(1))
        if self.has(RelicId.INCENSE_BURNER):
            if self.bump(RelicId.INCENSE_BURNER) == 2:
                self.set_counter(RelicId.INCENSE_BURNER, 0)
                p.statuses.add(PlayerStatus.ARTIFACT, 1)
        if self.has(RelicId.HORN_CLEAT):
            if self.bump(RelicId.HORN_CLEAT) == 5:
                self.set_counter(RelicId.HORN_CLEAT, 0)
                bc.add_to_bot(Actions.gain_block(14))
        if self.has(RelicId.MERCURY_HOURGLASS):
            bc.add_to_bot(Actions.damage_all_enemy(3))
        if self.has(RelicId.CAPTAINS_WHEEL):
            # TODO 批次 2：数值核实（每 3 回合 +3 格挡）
            pass
        # TODO 批次 2：EMOTION_CHIP

    def on_turn_start_post_draw(self, bc: BattleContext) -> None:
        p = bc.player
        if self.has(RelicId.POCKETWATCH):
            if p.cards_played_last_turn == 0:
                p.heal(6)
        if self.has(RelicId.WARPED_TONGS):
            # TODO 批次 3（RNG 遗物）：50% 随机升级手牌 1 张
            pass

    # ============================================================
    # 能量/格挡衰减
    # ============================================================
    def extra_energy_per_turn(self, bc: BattleContext) -> int:
        """能量类遗物的每回合额外能量（SOZU/ECTOPLASM +1，BUSTED_CROWN +2 等）。"""
        extra = 0
        if self.has(RelicId.ECTOPLASM):
            extra += 1
        if self.has(RelicId.SOZU):
            extra += 1
        if self.has(RelicId.COFFEE_DRIPPER):
            extra += 1
        if self.has(RelicId.CURSED_KEY):
            extra += 1
        if self.has(RelicId.VELVET_CHOKER):
            extra += 1
        if self.has(RelicId.RUNIC_DOME):
            extra += 1
        if self.has(RelicId.PHILOSOPHERS_STONE):
            extra += 1
        if self.has(RelicId.FUSION_HAMMER):
            extra += 2
        if self.has(RelicId.BUSTED_CROWN):
            extra += 2
        if self.has(RelicId.MARK_OF_PAIN):
            extra += 1
        return extra

    def keeps_leftover_energy(self, bc: BattleContext) -> bool:
        return self.has(RelicId.ICE_CREAM)

    def on_block_decay(self, bc: BattleContext) -> int:
        """回合开始格挡保留量（默认清零）。CALIPERS：保留 15。"""
        return 15 if self.has(RelicId.CALIPERS) else 0

    # ============================================================
    # 出牌类（use_card 的类型钩子，固定序对齐 onUseXxxCard）
    # ============================================================
    def on_use_attack_card(self, bc: BattleContext) -> None:
        p = bc.player
        if self.has(RelicId.KUNAI):
            if self.bump(RelicId.KUNAI) == 3:
                self.set_counter(RelicId.KUNAI, 0)
                p.statuses.add(PlayerStatus.DEXTERITY, 1)
        if self.has(RelicId.ORNAMENTAL_FAN):
            if self.bump(RelicId.ORNAMENTAL_FAN) == 3:
                self.set_counter(RelicId.ORNAMENTAL_FAN, 0)
                bc.add_to_bot(Actions.gain_block(4))
        if self.has(RelicId.SHURIKEN):
            if self.bump(RelicId.SHURIKEN) == 3:
                self.set_counter(RelicId.SHURIKEN, 0)
                p.statuses.add(PlayerStatus.STRENGTH, 1)
        if self.has(RelicId.PEN_NIB):
            if self.bump(RelicId.PEN_NIB) == 9:
                self.set_counter(RelicId.PEN_NIB, -1)  # 下一张攻击翻倍中
                p.statuses.set(PlayerStatus.PEN_NIB, 1)
        if self.has(RelicId.NUNCHAKU):
            if self.bump(RelicId.NUNCHAKU) == 10:
                self.set_counter(RelicId.NUNCHAKU, 0)
                bc.add_to_bot(Actions.gain_energy(1))
        # TODO 批次 2：INK_BOTTLE/NECRONOMICON/DUALITY；PEN_NIB 触发段见 modify_card_damage

    def on_use_skill_card(self, bc: BattleContext) -> None:
        if self.has(RelicId.LETTER_OPENER):
            if self.bump(RelicId.LETTER_OPENER) == 3:
                self.set_counter(RelicId.LETTER_OPENER, 0)
                bc.add_to_bot(Actions.damage_all_enemy(4))
        # TODO 批次 2：INK_BOTTLE/MUMMIFIED_HAND(lightspeed 标 todo，不移植 skill 段)

    def on_use_power_card(self, bc: BattleContext) -> None:
        if self.has(RelicId.BIRD_FACED_URN):
            bc.player.heal(2)
        if self.has(RelicId.MUMMIFIED_HAND):
            # TODO 批次 3（RNG 遗物）：随机 1 张手牌本回合 0 费
            pass
        # TODO 批次 2：INK_BOTTLE

    def on_use_status_or_curse_card(self, bc: BattleContext) -> None:
        # TODO 批次 2：BLUE_CANDLE/MEDICAL_KIT（诅咒/状态可打出，依赖卡池迁移）
        pass

    def on_would_exhaust(self, bc: BattleContext, inst: CardInstance) -> bool:
        """on_after_use_card 的消耗路由：返回 False 表示改走弃牌堆
        （STRANGE_SPOON 50% 不消耗，misc 流）。"""
        if self.has(RelicId.STRANGE_SPOON):
            return bc.rngs.misc.int_inclusive(0, 9999) >= 5000
        return True

    def check_play_allowed(self, bc: BattleContext, inst: CardInstance) -> bool:
        """出牌资格（VELVET_CHOKER：手牌 ≥6 禁出）。"""
        if self.has(RelicId.VELVET_CHOKER):
            if len(bc.cards.hand) >= 6:
                return False
        return True

    # ============================================================
    # 伤害计算（calculate_card_damage 的查询点）
    # ============================================================
    def modify_card_damage(self, bc: BattleContext, item: CardQueueItem,
                           target_idx: int, base_damage: float) -> float:
        """出伤管线的遗物修正（STRIKE_DUMMY/WRIST_BLADE/PEN_NIB 触发）。
        在力量加成之后、乘算之前对齐 lightspeed 位置调用。"""
        assert item.card is not None
        d = base_damage
        if self.has(RelicId.STRIKE_DUMMY) and item.card.card.name == "Strike":
            d += 3
        if self.has(RelicId.WRIST_BLADE) and item.card.cost == 0 and item.card.card.ctype == "Attack":
            d += 4
        if self.has(RelicId.PEN_NIB) and bc.player.statuses.get(PlayerStatus.PEN_NIB) > 0:
            d *= 2
            bc.player.statuses.set(PlayerStatus.PEN_NIB, 0)
            if RelicId.PEN_NIB in self.counters:
                self.counters[RelicId.PEN_NIB] = 0
        return d

    def vulnerable_multiplier(self, bc: BattleContext) -> float:
        """易伤乘算倍率（PAPER_PHROG：1.5 → 1.75）。"""
        return 1.75 if self.has(RelicId.PAPER_PHROG) else 1.5

    # ============================================================
    # 受击/HP 类（Player.attacked/damage/lose_hp 调用）
    # ============================================================
    def on_incoming_attack_damage(self, bc: BattleContext, damage: int) -> int:
        if self.has(RelicId.TORII) and 0 < damage <= 5:
            damage = 1
        if self.has(RelicId.TUNGSTEN_ROD) and damage > 0:
            damage = max(0, damage - 1)
        return damage

    def on_player_hp_was_lost(self, bc: BattleContext, amount: int) -> None:
        if amount <= 0:
            return
        p = bc.player
        if self.has(RelicId.RED_SKULL) and self.counter(RelicId.RED_SKULL) == 0:
            self.set_counter(RelicId.RED_SKULL, 1)
            p.statuses.add(PlayerStatus.STRENGTH, 1)
        if self.has(RelicId.SELF_FORMING_CLAY) and self.counter(RelicId.SELF_FORMING_CLAY) == 0:
            self.set_counter(RelicId.SELF_FORMING_CLAY, 1)
            bc.add_to_bot(Actions.gain_block(3))
        if self.has(RelicId.CENTENNIAL_PUZZLE) and self.counter(RelicId.CENTENNIAL_PUZZLE) == 0:
            self.set_counter(RelicId.CENTENNIAL_PUZZLE, 1)
            bc.add_to_bot(Actions.draw_cards(3))
        # TODO 批次 3：EMOTION_CHIP/RUNIC_CUBE/MAGIC_FLOWER

    # ============================================================
    # 怪物侧触发
    # ============================================================
    def on_monster_death(self, bc: BattleContext, m: Monster) -> None:
        if self.has(RelicId.GREMLIN_HORN):
            bc.add_to_bot(Actions.gain_energy(1))
            bc.add_to_bot(Actions.draw_cards(1))
        # TODO 批次 3：THE_SPECIMEN

    def on_monster_spawned(self, bc: BattleContext, m: Monster) -> None:
        if self.has(RelicId.PHILOSOPHERS_STONE):
            m.statuses.add(MonsterStatus.STRENGTH, 1)

    def on_monster_unblocked_attack_damage(self, bc: BattleContext, damage: int) -> int:
        if self.has(RelicId.THE_BOOT) and 0 < damage < 5:
            return 5
        return damage

    def on_monster_block_broken(self, bc: BattleContext, m: Monster) -> None:
        # TODO 批次 3：HAND_DRILL（效果数值以 lightspeed 为准核实后补）
        pass

    # ============================================================
    # 洗牌/消耗/抽牌/手牌
    # ============================================================
    def on_shuffle(self, bc: BattleContext) -> None:
        if self.has(RelicId.THE_ABACUS):
            bc.add_to_bot(Actions.gain_block(6))
        if self.has(RelicId.SUNDIAL):
            if self.bump(RelicId.SUNDIAL) == 3:
                self.set_counter(RelicId.SUNDIAL, 0)
                bc.add_to_bot(Actions.gain_energy(2))

    def on_card_exhausted(self, bc: BattleContext, inst: CardInstance) -> None:
        if self.has(RelicId.CHARONS_ASHES):
            bc.add_to_bot(Actions.damage_all_enemy(2))
        if self.has(RelicId.DEAD_BRANCH):
            # TODO 批次 3（RNG 遗物）：随机 1 张牌入手
            pass

    def on_hand_empty(self, bc: BattleContext) -> None:
        if self.has(RelicId.UNCEASING_TOP):
            bc.add_to_bot(Actions.draw_cards(1))

    def keeps_hand_at_end_of_turn(self, bc: BattleContext) -> bool:
        """RUNIC_PYRAMID：回合末不弃手牌。"""
        return self.has(RelicId.RUNIC_PYRAMID)

    # ============================================================
    # 回合结束（call_end_turn_actions，固定序对齐 lightspeed）
    # ============================================================
    def on_end_turn(self, bc: BattleContext) -> None:
        if self.has(RelicId.CLOAK_CLASP):
            n = len(bc.cards.hand)
            if n > 0:
                bc.add_to_bot(Actions.gain_block(n))
        if self.has(RelicId.ORICHALCUM):
            if bc.player.block == 0:
                # 对齐 lightspeed：addToTop（插队，先于本回合其他入队效果）
                bc.add_to_top(Actions.gain_block(6))
        if self.has(RelicId.STONE_CALENDAR) and bc.turn >= 7:
            bc.add_to_bot(Actions.damage_all_enemy(52))
        # TODO 批次 2：NILRYS_CODEX（需 CARD_SELECT 集成）

    # ============================================================
    # 战斗结束
    # ============================================================
    def on_victory(self, bc: BattleContext) -> None:
        p = bc.player
        if self.has(RelicId.BURNING_BLOOD):
            p.heal(6)
        if self.has(RelicId.MEAT_ON_THE_BONE):
            if p.hp * 2 <= p.max_hp:
                p.heal(12)

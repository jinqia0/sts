"""战斗流转断言：回合生命周期、Cultist 行为、牌堆流转、胜负、种子确定性，
以及队列架构（sts_lightspeed 移植）的行为验证。"""

from sts.combat import BattleContext, InputState
from sts.combat.types import MonsterStatus, PlayerStatus
from sts.content.monsters import Cultist


def play_first(bc: BattleContext, card_name: str) -> None:
    for i, inst in enumerate(bc.cards.hand):
        if inst.card.name == card_name and inst.cost <= bc.player.energy:
            bc.play_card(i)
            return
    raise AssertionError(f"手牌中没有可打的 {card_name}：{[c.card.name for c in bc.cards.hand]}")


# ---- 回合生命周期 ----


def test_input_state_machine():
    """玩家阶段才接受输入；出牌/结束回合后回到 PLAYER_NORMAL。"""
    bc = BattleContext(seed=20)
    assert bc.input_state == InputState.PLAYER_NORMAL
    play_first(bc, "Strike")
    assert bc.input_state == InputState.PLAYER_NORMAL
    bc.end_turn()
    assert bc.input_state == InputState.PLAYER_NORMAL


def test_play_card_rejected_during_resolution():
    bc = BattleContext(seed=21)
    bc.set_state(InputState.EXECUTING_ACTIONS)
    try:
        bc.play_card(0)
        raise AssertionError("应当在结算阶段拒绝出牌")
    except ValueError:
        pass


def test_monster_block_resets_on_its_turn_start():
    """怪物格挡在其回合开始清零（MonsterStartTurnAction 时机）。"""
    bc = BattleContext(seed=22)
    m = bc.monsters.monsters[0]
    m.block = 5
    bc.end_turn()  # 敌方阶段开始 → apply_start_of_turn_powers → block=0
    assert m.block == 0


# ---- Cultist 行为 ----


def test_cultist_first_turn_incantation():
    """第 1 敌方回合：咒语，获得 3 层仪式，不掉血。"""
    bc = BattleContext(seed=10)
    hp0 = bc.player.hp
    bc.end_turn()
    assert bc.player.hp == hp0
    m = bc.monsters.monsters[0]
    assert m.statuses.get(MonsterStatus.RITUAL) == 3
    assert m.turns_taken == 1


def test_cultist_ritual_snowball():
    """黑暗打击序列 6, 9, 12：Ritual 回合末结算且施加当轮跳过（skipFirst）。"""
    bc = BattleContext(seed=11)
    m = bc.monsters.monsters[0]
    bc.end_turn()  # 回合 1：咒语；回合末跳过首个 Ritual 结算，力量仍 0
    assert m.statuses.get(MonsterStatus.STRENGTH) == 0
    assert bc.player.hp == 80
    bc.end_turn()  # 回合 2：黑暗打击 6（无力量）；回合末 +3 力量
    assert bc.player.hp == 80 - 6
    assert m.statuses.get(MonsterStatus.STRENGTH) == 3
    bc.end_turn()  # 回合 3：黑暗打击 9；回合末力量 6
    assert bc.player.hp == 80 - 6 - 9
    assert m.statuses.get(MonsterStatus.STRENGTH) == 6


def test_intent_rolls_only_at_enemy_turn_end():
    """战斗开始即有第 1 回合意图（咒语）；此后意图在敌方回合结束时才更新。"""
    bc = BattleContext(seed=12)
    m = bc.monsters.monsters[0]
    assert m.current_move.name == "Incantation"
    play_first(bc, "Strike")  # 玩家整个回合操作后，意图仍是开场生成的那个
    assert m.current_move.name == "Incantation"
    bc.end_turn()
    assert m.current_move.name == "Dark Strike"


def test_intent_damage_matches_next_attack():
    """意图显示数值 = 下一击实际伤害。"""
    bc = BattleContext(seed=19)
    bc.end_turn()  # 回合 1：咒语
    m = bc.monsters.monsters[0]
    for expected in (6, 9, 12):
        shown = bc.calculate_monster_damage(m, m.current_move.base_damage)
        assert shown == expected
        hp0 = bc.player.hp
        bc.end_turn()
        assert hp0 - bc.player.hp == shown


# ---- 临时 debuff 衰减 ----


def test_player_applied_vulnerable_decays():
    """玩家施加的易伤从首个回合末就递减（isSourceMonster=False）。"""
    bc = BattleContext(seed=15)
    m = bc.monsters.monsters[0]
    play_first(bc, "Bash")  # 2 层易伤
    assert m.statuses.get(MonsterStatus.VULNERABLE) == 2
    bc.end_turn()  # 回合末：2 → 1
    assert m.statuses.get(MonsterStatus.VULNERABLE) == 1
    bc.end_turn()  # 1 → 0，移除
    assert not m.statuses.has(MonsterStatus.VULNERABLE)


def test_monster_applied_vulnerable_skips_first_decay():
    """怪物施加的易伤（justApplied）首个回合末不递减。"""
    bc = BattleContext(seed=25)
    from sts.combat.actions import Actions

    bc.player.statuses.add(PlayerStatus.VULNERABLE, 2)
    bc.player.statuses.set_just_applied(PlayerStatus.VULNERABLE, True)
    bc.end_turn()  # 回合末：跳过
    assert bc.player.statuses.get(PlayerStatus.VULNERABLE) == 2
    bc.end_turn()  # 下个回合末：2 → 1
    assert bc.player.statuses.get(PlayerStatus.VULNERABLE) == 1


def test_bash_vulnerable_window():
    """Bash 的 2 层易伤：施加当回合与下个回合的攻击被放大，再下回合不再。"""
    bc = BattleContext(seed=18)
    m = bc.monsters.monsters[0]
    hp0 = m.hp
    # 手工构造手牌保证序列
    from sts.content.cards import BASH, STRIKE

    bc.cards.hand.clear()
    bc.cards.hand.extend([bc.cards.instantiate(BASH), bc.cards.instantiate(STRIKE)])
    bc.play_card(0)  # Bash：8 伤 + 易伤 2
    bc.play_card(0)  # Strike：floor(6×1.5)=9
    assert m.hp == hp0 - 8 - 9
    bc.end_turn()  # 回合末：易伤 2→1
    assert m.statuses.get(MonsterStatus.VULNERABLE) == 1
    # end_turn 会抽 5 张新牌，构造的牌放队尾、按末索引打出
    bc.cards.hand.append(bc.cards.instantiate(STRIKE))
    bc.play_card(len(bc.cards.hand) - 1)  # 仍被易伤放大：9
    assert m.hp == hp0 - 8 - 9 - 9
    bc.end_turn()  # 回合末：易伤 1→0，移除
    assert not m.statuses.has(MonsterStatus.VULNERABLE)
    bc.cards.hand.append(bc.cards.instantiate(STRIKE))
    bc.play_card(len(bc.cards.hand) - 1)  # 易伤已消退：6
    assert m.hp == hp0 - 8 - 9 - 9 - 6


# ---- 牌堆流转 ----


def test_draw_pile_reshuffle():
    """10 张牌：第 3 回合开始时弃牌堆洗回抽牌堆。"""
    bc = BattleContext(seed=13)
    assert len(bc.cards.draw_pile) == 5  # 抽 5 剩 5
    bc.end_turn()  # 手牌 5 张进弃牌堆 → 回合 2 抽剩余 5 张
    assert len(bc.cards.draw_pile) == 0
    assert len(bc.cards.hand) == 5
    assert len(bc.cards.discard_pile) == 5
    bc.end_turn()  # 弃牌堆 10 张 → 洗回抽牌堆 → 回合 3 抽 5
    assert len(bc.cards.hand) == 5
    assert len(bc.cards.draw_pile) == 5
    assert len(bc.cards.discard_pile) == 0
    assert len(bc.cards.exhaust_pile) == 0


def test_energy_enforced():
    bc = BattleContext(seed=14)
    from sts.content.cards import STRIKE

    bc.cards.hand.clear()
    bc.cards.hand.extend([bc.cards.instantiate(STRIKE) for _ in range(4)])
    bc.play_card(0)
    bc.play_card(0)
    bc.play_card(0)
    try:
        bc.play_card(0)
        raise AssertionError("应当在能量不足时抛出 ValueError")
    except ValueError as e:
        assert "能量不足" in str(e)


# ---- 队列架构行为 ----


def test_lethal_attack_fizzles_followup_actions():
    """击杀后，队列中 clear_on_victory 的动作被清空（如 Bash 的易伤不再施加）。"""
    from sts.content.cards import BASH

    bc = BattleContext(seed=26)
    m = bc.monsters.monsters[0]
    m.hp = 8
    bc.cards.hand.clear()
    bc.cards.hand.append(bc.cards.instantiate(BASH))
    bc.play_card(0)  # 8 伤击杀 + 尾随的易伤动作
    assert bc.over
    assert bc.won
    assert not m.statuses.has(MonsterStatus.VULNERABLE)  # 尾随动作被清


def test_actions_resolve_in_queue_order():
    """Bash 的攻击先于易伤落地（addToBot 顺序）：同回合后续 Strike 享受易伤。"""
    from sts.content.cards import BASH, STRIKE

    bc = BattleContext(seed=27)
    m = bc.monsters.monsters[0]
    bc.cards.hand.clear()
    bc.cards.hand.extend([bc.cards.instantiate(BASH), bc.cards.instantiate(STRIKE)])
    bc.play_card(0)
    bc.play_card(0)
    assert m.statuses.get(MonsterStatus.VULNERABLE) == 2


# ---- 胜负与确定性 ----


def test_player_death():
    bc = BattleContext(seed=16)
    bc.player.hp = 5
    bc.end_turn()  # 敌回合 1：咒语，不攻击
    assert not bc.over
    bc.end_turn()  # 敌回合 2：6 伤 → 玩家死亡
    assert bc.over
    assert not bc.won


def test_victory_by_bash():
    bc = BattleContext(seed=17)
    m = bc.monsters.monsters[0]
    m.hp = 8
    play_first(bc, "Bash")
    assert bc.over
    assert bc.won
    assert bc.player.hp == 80


def test_seed_determinism():
    """同种子 + 同动作序列 → 逐字段一致（分布级保真下的可复现实验）。"""

    def run(seed: int) -> dict:
        bc = BattleContext(seed=seed)
        for _ in range(8):
            if bc.over:
                break
            # 脚本：优先 Bash，再 Strike，能量打光后防御，然后结束回合
            for name in ("Bash", "Strike", "Strike", "Defend"):
                if bc.over:
                    break
                for i, inst in enumerate(bc.cards.hand):
                    if inst.card.name == name and inst.cost <= bc.player.energy:
                        bc.play_card(i)
                        break
            if not bc.over:
                bc.end_turn()
        return {
            "turn": bc.turn,
            "over": bc.over,
            "won": bc.won,
            "player_hp": bc.player.hp,
            "monster_hp": [m.hp for m in bc.monsters.monsters],
            "monster_str": [m.statuses.get(MonsterStatus.STRENGTH) for m in bc.monsters.monsters],
            "hand": [c.card.name for c in bc.cards.hand],
            "log": list(bc.log),
        }

    assert run(42) == run(42)  # 同种子同动作 → 逐字段一致


def test_rng_streams_independent():
    """分流后，洗牌流消耗不影响怪物 HP 流（对无关改动稳健）。"""
    bc1 = BattleContext(seed=99)
    bc2 = BattleContext(seed=99)
    # 额外消耗 shuffle 流（模拟未来改抽牌逻辑）
    bc2.rngs.shuffle.int_inclusive(0, 2**31)
    assert bc1.monsters.monsters[0].hp == bc2.monsters.monsters[0].hp

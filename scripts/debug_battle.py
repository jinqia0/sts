#!/usr/bin/env python3
"""战斗过程调试脚本：逐动作追踪引擎内部结算（只挂钩运行时，不改引擎源码）。

一场战斗在引擎里的真实流程（sts_lightspeed 架构）：

    env.step(action)
      └→ BattleContext.play_card / end_turn     玩家动作入口
          └→ 卡牌/怪物把效果分解为原子动作 入队   （＋bot 排队 / ＋top 插队）
              └→ execute_actions 主循环逐个弹出  （└▶ 执行）
                  └→ 实体方法结算                （✦ 受击 / ☠ 死亡 / ◇ 状态衰减）

本脚本在每个环节打印一行追踪，配上每个决策点的局面快照与伤害管线分解。

用法：
    uv run python scripts/debug_battle.py                          # heuristic 自动打一场
    uv run python scripts/debug_battle.py --encounter jaw_worm --seed 7
    uv run python scripts/debug_battle.py --policy random          # 随机策略
    uv run python scripts/debug_battle.py --policy manual           # 自己打，带内部追踪
    uv run python scripts/debug_battle.py --log                     # 结束后再打印完整引擎日志
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))  # 从 scripts/ 找到项目根

import sts.combat.battle as battle_mod
import sts.combat.card_manager as cm_mod
import sts.combat.entities as entities_mod
import sts.combat.queue as queue_mod
from sts.baselines import heuristic_policy, random_policy
from sts.combat.actions import Actions
from sts.combat.types import MonsterStatus, PlayerStatus
from sts.env import ACTION_END_TURN, HAND_SLOT_BASE, TARGETED_BASE, StsBattleEnv

TRACE = {"on": True}


def _p(msg: str) -> None:
    if TRACE["on"]:
        print(msg)


# ---------------------------------------------------------------- 挂钩基建

def hook(cls, name, before=None, after=None):
    """替换 cls.name：原方法前后插入回调。after 拿到 (ret, self, *args)。"""
    orig = getattr(cls, name)

    def wrapper(*args, **kwargs):
        if before:
            before(*args, **kwargs)
        ret = orig(*args, **kwargs)
        if after:
            after(ret, *args, **kwargs)
        return ret

    setattr(cls, name, wrapper)


def _short(x):
    """动作参数的紧凑显示：枚举只打名字。"""
    if isinstance(x, bool):
        return int(x)
    if hasattr(x, "name") and hasattr(x, "value"):  # IntEnum
        return x.name
    return x


def _tag_action_factories() -> None:
    """给每个 Actions 工厂的返回值打上可读描述，入队/出队时就能打印。"""
    for attr, fn in list(vars(Actions).items()):
        if not isinstance(fn, staticmethod) or getattr(fn.__func__, "_tagged", False):
            continue
        orig = fn.__func__

        def make(orig=orig, attr=attr):
            def factory(*a, **k):
                act = orig(*a, **k)
                act.desc = f"{attr}({', '.join(str(_short(x)) for x in a)})"
                return act

            factory._tagged = True
            return factory

        setattr(Actions, attr, staticmethod(make()))


# ---------------------------------------------------------------- 展示辅助

def _cardq_desc(item) -> str:
    if item.is_end_turn:
        return "结束回合哨兵（触发回合末流程）"
    if item.card is not None:
        t = f" →目标{item.target}" if item.target is not None and item.target >= 0 else ""
        return f"{item.card.card.name}{t}"
    return "<未知卡牌项>"


def _m_terms(bc, m, base: int) -> str:
    """怪物出伤管线的分步叙述（镜像 battle.calculate_monster_damage 公式）。"""
    parts = [f"基础{base}"]
    s = m.statuses.get(MonsterStatus.STRENGTH)
    if s:
        parts.append(f"+力量{s}")
    if m.statuses.has(MonsterStatus.WEAK):
        parts.append("×虚弱0.75")
    if bc.player.statuses.has(PlayerStatus.VULNERABLE):
        parts.append("×易伤1.5")
    return " ".join(parts)


def _p_terms(bc, target_idx: int, base: int) -> str:
    """玩家出伤管线的分步叙述（镜像 battle.calculate_card_damage）。"""
    parts = [f"基础{base}"]
    s = bc.player.statuses.get(PlayerStatus.STRENGTH)
    if s:
        parts.append(f"+力量{s}")
    if bc.player.statuses.has(PlayerStatus.WEAK):
        parts.append("×虚弱0.75")
    m = bc.monsters.monsters[target_idx]
    if m.statuses.has(MonsterStatus.VULNERABLE):
        parts.append("×易伤1.5")
    return " ".join(parts)


def _b_terms(bc) -> str:
    if bc.player.statuses.has(PlayerStatus.DEXTERITY):
        return f"+敏捷{bc.player.statuses.get(PlayerStatus.DEXTERITY)}"
    if bc.player.statuses.has(PlayerStatus.FRAIL):
        return "×脆弱3/4"
    return ""


def _intent_text(bc, m) -> str:
    move = m.current_move
    if move.kind == "attack" and move.base_damage is not None:
        TRACE["on"] = False  # 展示用计算，不进追踪
        try:
            return f"攻击{bc.calculate_monster_damage(m, move.base_damage)}"
        finally:
            TRACE["on"] = True
    return f"{move.zh}（{move.intent_text}）" if move.intent_text else move.zh


def snapshot(bc) -> None:
    """决策点局面快照（只用白名单信息，与观测同口径）。"""
    for m in bc.monsters.monsters:
        if not m.alive:
            continue
        print(f"  {m.display_name}  HP {m.hp}/{m.max_hp}  格挡{m.block}  意图[{_intent_text(bc, m)}]  {m.statuses}")
    p = bc.player
    print(f"  你  HP {p.hp}/{p.max_hp}  格挡{p.block}  能量{p.energy}/3  {p.statuses}")
    hand = [inst.card.name for inst in bc.cards.hand]
    print(f"  手牌 {hand}  |  抽牌堆{len(bc.cards.draw_pile)}张 弃牌堆{len(bc.cards.discard_pile)}张 消耗堆{len(bc.cards.exhaust_pile)}张")


def describe_action(bc, a: int) -> str:
    if a == ACTION_END_TURN:
        return "结束回合"
    if a < TARGETED_BASE:
        i = a - HAND_SLOT_BASE
        return f"出牌 手牌槽{i}: {bc.cards.hand[i].card.name}"
    i, j = divmod(a - TARGETED_BASE, 5)
    return f"出牌 手牌槽{i}({bc.cards.hand[i].card.name}) → {bc.monsters.monsters[j].display_name}"


# ---------------------------------------------------------------- 挂钩安装

def install_hooks() -> None:
    # 幂等保护：同一进程重复调用（Jupyter/交互式多次运行）不再叠加挂钩
    if getattr(install_hooks, "_installed", False):
        return
    install_hooks._installed = True

    _tag_action_factories()

    # —— 队列：入队与出队（结算顺序的全部真相）——
    hook(battle_mod.BattleContext, "add_to_bot",
         before=lambda self, a: _p(f"    ┌ 入队bot: {getattr(a, 'desc', '<?>')}"))
    hook(battle_mod.BattleContext, "add_to_top",
         before=lambda self, a: _p(f"    ┌ 入队top(插队): {getattr(a, 'desc', '<?>')}"))
    hook(queue_mod.ActionQueue, "pop_front",
         before=lambda self: _p(f"    └▶ 执行: {getattr(self._q[0], 'desc', '<?>')}"))
    hook(queue_mod.CardQueue, "pop_front",
         before=lambda self: _p(f"    └▶ 处理卡牌项: {_cardq_desc(self._q[0])}"))

    # —— 回合生命周期阶段横幅 ——
    hook(battle_mod.BattleContext, "on_turn_ending",
         before=lambda self: _p("  ▼ on_turn_ending：手牌进弃牌堆，敌方阶段即将开始"))
    hook(entities_mod.MonsterGroup, "apply_pre_turn_logic",
         before=lambda self, bc: _p("  ▼ 敌方回合开始：各存活怪格挡清零"))
    hook(entities_mod.MonsterGroup, "do_monster_turn",
         before=lambda self, bc: _p(f"  ● {self.monsters[bc.monster_turn_idx].display_name} 行动"))
    hook(battle_mod.BattleContext, "after_monster_turns",
         before=lambda self: _p("  ▼ after_monster_turns：回合末统一结算 → 玩家回合开始"))

    # —— 伤害/格挡管线分解 ——
    hook(battle_mod.BattleContext, "calculate_monster_damage",
         after=lambda ret, self, m, base: _p(f"    ∑ 出伤管线 {m.display_name}→你: {_m_terms(self, m, base)} ⇒ {ret}"))
    hook(battle_mod.BattleContext, "calculate_card_damage",
         after=lambda ret, self, item, t, base: _p(f"    ∑ 出伤管线 你→目标{t}: {_p_terms(self, t, base)} ⇒ {ret}"))
    hook(battle_mod.BattleContext, "calculate_card_block",
         after=lambda ret, self, base: _p(f"    ∑ 格挡管线: 基础{base} {_b_terms(self)} ⇒ {ret}"))

    # —— 实体结算结果 ——
    hook(entities_mod.Monster, "attacked",
         after=lambda ret, self, bc, dmg: _p(
             f"      ✦ {self.display_name} 受击后: 格挡{self.block} HP {self.hp}/{self.max_hp}"
             + ("  ☠死亡" if not self.alive else "")))
    hook(entities_mod.Player, "attacked",
         after=lambda ret, self, bc, i, dmg: _p(
             f"      ✦ 你 受击后: 格挡{self.block} HP {self.hp}/{self.max_hp}"))
    hook(entities_mod.Monster, "die",
         before=lambda self, bc: _p(f"      ☠ {self.display_name} 死亡"))

    # —— 意图生成（POMDP 边界：只在怪物回合末发生）——
    hook(entities_mod.Monster, "set_move",
         after=lambda ret, self, move: _p(f"    ⟳ {self.display_name} 生成新意图: {move.name}"))

    # —— 回合末状态衰减结果 ——
    hook(entities_mod.Monster, "apply_end_of_round_powers",
         after=lambda ret, self, bc: _p(f"    ◇ {self.display_name} 回合末结算后: {self.statuses}"))
    hook(entities_mod.Player, "apply_at_end_of_round_powers",
         after=lambda ret, self, bc: _p(f"    ◇ 你 回合末状态衰减后: {self.statuses}"))

    # —— 牌堆移动 ——
    hook(cm_mod.CardManager, "move_to_hand",
         before=lambda self, c: _p(f"    [牌] {c.card.name} → 手牌"))
    hook(cm_mod.CardManager, "move_to_discard_pile",
         before=lambda self, c: _p(f"    [牌] {c.card.name} → 弃牌堆"))
    hook(cm_mod.CardManager, "move_to_exhaust_pile",
         before=lambda self, c: _p(f"    [牌] {c.card.name} → 消耗堆"))
    hook(cm_mod.CardManager, "move_discard_pile_into_draw_pile",
         before=lambda self: _p("    [牌] 弃牌堆 → 洗回抽牌堆"))

    # —— 观测构建不进追踪（意图数值特征会调用伤害管线，纯读取）——
    import sts.env as env_mod

    hook(env_mod.StsBattleEnv, "_get_obs",
         before=lambda self: TRACE.__setitem__("on", False),
         after=lambda ret, self: TRACE.__setitem__("on", True))


# ---------------------------------------------------------------- 主流程

def manual_action(bc) -> int | None:
    line = input("  手牌编号(可带目标: `3 2`=手牌3打敌人2) / e=结束回合 > ").strip()
    if line == "e":
        return ACTION_END_TURN
    parts = line.split()
    if parts and parts[0].isdigit():
        i = int(parts[0]) - 1
        if not (0 <= i < len(bc.cards.hand)):
            print("  手牌编号超范围")
            return None
        if len(parts) > 1 and parts[1].isdigit():
            return TARGETED_BASE + i * 5 + (int(parts[1]) - 1)
        return HAND_SLOT_BASE + i
    print("  无效输入")
    return None


def main() -> None:
    parser = argparse.ArgumentParser(description="战斗过程逐步追踪调试")
    parser.add_argument("--seed", type=int, default=None)
    parser.add_argument("--encounter", default="cultist",
                        choices=["cultist", "jaw_worm", "louses", "slimes_s", "fungi_beast"])
    parser.add_argument("--policy", default="heuristic", choices=["heuristic", "random", "manual"])
    parser.add_argument("--log", action="store_true", help="结束时打印完整引擎日志")
    args = parser.parse_args()

    install_hooks()
    policies = {"heuristic": heuristic_policy, "random": random_policy}

    print(f"══════ 战斗开始：你 vs {args.encounter}（seed={args.seed}，策略={args.policy}）══════")
    print("  （下方为初始化追踪：怪物入场/HP抽样、牌堆洗牌、首回合意图生成、起手抽牌）")
    env = StsBattleEnv(encounter=args.encounter)
    env.reset(seed=args.seed)
    bc = env.bc
    step = 0
    terminated = truncated = False
    while not (terminated or truncated):
        step += 1
        print(f"\n────── 决策点 step={step}（回合 {bc.turn}）──────")
        snapshot(bc)

        if args.policy == "manual":
            action = None
            while action is None:
                action = manual_action(bc)
        else:
            TRACE["on"] = False  # 策略内部的评估计算不进追踪
            try:
                action = policies[args.policy](env)
            finally:
                TRACE["on"] = True

        print(f"  ⇒ 动作: {describe_action(bc, action)}")
        _obs, reward, terminated, truncated, info = env.step(action)

    print("\n══════ 战斗结束 ══════")
    print(f"  结果: {'胜利' if info['won'] else '失败'}  奖励: {reward}  回合数: {info['turns']}  剩余HP: {info['hp_remaining']}")
    if args.log:
        print("\n────── 完整引擎日志 ──────")
        for line in bc.log:
            print(f"  {line}")


if __name__ == "__main__":
    main()

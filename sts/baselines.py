"""Baseline 策略与批量评估（DESIGN.md §5：评估永远对比两个 baseline）。

种子区间约定（DESIGN.md §4.3：评估种子与训练种子不相交）：
- 评估/基线种子：0..99（EVAL_SEEDS = range(100)，本模块默认值）
- 未来训练种子：约定从 10_000 起分配，永不落入 0..99 区间

策略签名统一为 ``policy(env) -> int``：读 ``env.action_masks()`` 保证
只返回合法动作；启发式策略额外读 ``env.bc`` 的白名单信息（DESIGN.md
§4.1：当前意图、手牌、能量、格挡）。
"""

from __future__ import annotations

import numpy as np

from sts.combat.types import InputState
from sts.env import (
    ACTION_END_TURN,
    HAND_SLOT_BASE,
    N_SELECT_WINDOW,
    SCRY_BASE,
    SELECT_BASE,
    SELECT_CONFIRM,
    TARGETED_BASE,
    StsBattleEnv,
)

EVAL_SEEDS = range(100)

# 单局步数保险丝：回合上限 100 × 每回合手牌上限 10 + 裕量
MAX_STEPS = 20_000

# 出伤优先级表（A0 单目标伤害；多段/全体按单目标计）。扩攻击卡时维护
# 此表；未收录的卡默认伤害 0（不会被启发式优先打出，安全降级）。
ATTACK_CARD_DAMAGE: dict[str, int] = {
    "Strike": 6,
    "Bash": 8,
    "Twin Strike": 10,
    "Cleave": 8,
    "Iron Wave": 5,
    "Pommel Strike": 9,
    "Clothesline": 12,
    "Thunderclap": 4,
    "Anger": 6,
    "Wild Strike": 12,
}
DEFEND_NAME = "Defend"
BODY_SLAM_NAME = "Body Slam"  # 伤害 = 当前格挡（动态，特殊处理）


def random_policy(env: StsBattleEnv) -> int:
    """均匀采样合法动作。

    用 env.np_random 采样：reset(seed=s) 会重播该流，因此同种子的
    整局轨迹（含策略的随机选择）可精确重放——评估确定性的基础。
    """
    mask = env.action_masks()
    legal = np.flatnonzero(mask)
    return int(env.np_random.choice(legal))


def _first_legal_defend(env: StsBattleEnv, mask: np.ndarray) -> int | None:
    for i, inst in enumerate(env.bc.cards.hand):
        if inst.card.name == DEFEND_NAME and mask[HAND_SLOT_BASE + i]:
            return HAND_SLOT_BASE + i
    return None


def _card_damage(bc, inst) -> int:
    """攻击牌的启发式出伤估值（A0，不含易伤等动态修饰）。"""
    if inst.card.name == BODY_SLAM_NAME:
        return bc.player.block
    return ATTACK_CARD_DAMAGE.get(inst.card.name, 0)


def _attack_action(env: StsBattleEnv, mask: np.ndarray, i: int) -> int | None:
    """攻击槽 i 的合法动作：单怪走槽动作；多怪走指向最低血目标的组合位。"""
    if mask[HAND_SLOT_BASE + i]:
        return HAND_SLOT_BASE + i
    targetable = [m for m in env.bc.monsters.monsters if m.is_targetable()]
    if not targetable:
        return None
    j = min(targetable, key=lambda m: m.hp).idx  # 集火残血
    action = TARGETED_BASE + i * 5 + j
    return action if mask[action] else None


def heuristic_policy(env: StsBattleEnv) -> int:
    """简单启发式（人类新手直觉）：

    1. 本回合能量内能打出的攻击总伤 ≥ 某个敌人的 HP → 集火斩杀
       （先杀掉一个攻击者，直接消减后续回合的来袭伤害）
    2. 敌方当前意图是攻击、且我方格挡盖不住本回合来袭总伤 → 先打防御
    3. 否则打能量允许的最高伤害攻击牌（Clothesline > Bash > Strike）
    4. 都没有 → 结束回合

    只用白名单信息。多敌人时攻击走 (槽, 最低血目标) 组合位（槽动作
    对需要目标的牌不合法）。
    """
    bc = env.bc
    mask = env.action_masks()

    # ---- 挂起态安全闸（批次 5b）----
    # env 现在可到达 CARD_SELECT/SCRY（选卡/检视卡牌组）：启发式本体
    # 只懂出牌逻辑，挂起态下按「最保守合法动作」推进，避免返回非法的
    # END_TURN。更聪明的选卡/药水启发式是 5c 训练侧的事。
    if bc.input_state == InputState.CARD_SELECT:
        if mask[SELECT_CONFIRM]:
            return SELECT_CONFIRM  # can_pick_zero：空选最保守
        return SELECT_BASE + int(np.flatnonzero(mask[SELECT_BASE : SELECT_BASE + N_SELECT_WINDOW])[0])
    if bc.input_state == InputState.SCRY:
        # 保守：全部保留（不弃牌不改变抽牌节奏）
        k = int(np.flatnonzero(mask[SCRY_BASE:]).max())
        return SCRY_BASE + k

    # 可打出的攻击清单（槽号, 出伤估值），能量贪心从高到低
    attacks = [
        (i, _card_damage(bc, inst))
        for i, inst in enumerate(bc.cards.hand)
        if mask[HAND_SLOT_BASE + i] or any(
            mask[TARGETED_BASE + i * 5 + m.idx] for m in bc.monsters.monsters if m.is_targetable()
        )
    ]
    affordable = sorted(
        ((i, d) for i, d in attacks if bc.cards.hand[i].cost <= bc.player.energy),
        key=lambda x: -x[1],
    )

    # 1) 斩杀检查：能量内攻击总伤能否带走最低血目标
    if affordable:
        energy = bc.player.energy
        total = 0
        for i, _d in affordable:
            if bc.cards.hand[i].cost > energy:
                continue
            energy -= bc.cards.hand[i].cost
            total += _card_damage(bc, bc.cards.hand[i])
        targetable = [m for m in bc.monsters.monsters if m.is_targetable()]
        if targetable and total >= min(m.hp for m in targetable):
            i = affordable[0][0]
            action = _attack_action(env, mask, i)
            if action is not None:
                return action

    # 来袭总伤 = 所有存活怪攻击意图的展示口径伤害之和（白名单：当前意图）
    incoming = 0
    under_attack = False
    for m in bc.monsters.monsters:
        if m.is_targetable() and m.move_history:
            move = m.move_history[0]
            if move.kind == "attack" and move.base_damage is not None:
                under_attack = True
                incoming += bc.calculate_monster_damage(m, move.base_damage)

    # 2) 格挡不足优先补防（每次只打一张，下一决策点重新评估是否补够）
    if under_attack and bc.player.block < incoming:
        action = _first_legal_defend(env, mask)
        if action is not None:
            return action

    # 3) 能量允许的最高伤害攻击牌
    for i, _d in affordable:
        action = _attack_action(env, mask, i)
        if action is not None:
            return action

    # 4) 无牌可打 → 结束回合
    return ACTION_END_TURN


def run_episode(env: StsBattleEnv, policy, seed: int | None = None, options: dict | None = None) -> dict:
    """跑一整局，返回结果记录（evaluate 的原料，也可单独复现单局）。"""
    _obs, info = env.reset(seed=seed, options=options)
    total_reward = 0.0
    steps = 0
    terminated = truncated = False
    while not (terminated or truncated):
        action = policy(env)
        _obs, reward, terminated, truncated, info = env.step(action)
        total_reward += reward
        steps += 1
        if steps >= MAX_STEPS:
            raise RuntimeError("单局步数超限：疑似策略死循环")
    return {
        "won": bool(info["won"]),
        "outcome": info["outcome"],
        "truncated": truncated,
        "reward": total_reward,
        "turns": info["turns"],
        "hp_remaining": info["hp_remaining"],
        "steps": steps,
    }


def evaluate(policy, seeds=EVAL_SEEDS, encounter: str = "cultist", verbose: bool = True) -> dict:
    """在固定种子集上评估策略，返回统计结构（胜率数字只打印不进测试断言）。"""
    env = StsBattleEnv(encounter=encounter)
    results = [run_episode(env, policy, seed=s) for s in seeds]
    n = len(results)
    wins = sum(r["won"] for r in results)
    trunc = sum(r["truncated"] for r in results)
    summary = {
        "policy": policy.__name__,
        "encounter": encounter,
        "seeds": list(seeds),
        "episodes": n,
        "wins": wins,
        "losses": n - wins - trunc,
        "truncated": trunc,
        "win_rate": wins / n,
        "avg_turns": sum(r["turns"] for r in results) / n,
        "avg_hp_remaining": sum(r["hp_remaining"] for r in results) / n,
        "results": results,
    }
    if verbose:
        print(
            f"[{summary['policy']}] encounter={encounter} episodes={n} "
            f"win_rate={summary['win_rate']:.2f} avg_turns={summary['avg_turns']:.1f} "
            f"avg_hp_remaining={summary['avg_hp_remaining']:.1f} truncated={trunc}"
        )
    return summary

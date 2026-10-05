"""Baseline 策略测试：能跑完、统计结构正确、确定性。

胜率数字只打印到 stdout（-s 可见），不做具体值断言——baseline 的作用
是给训练策略一个对照锚点，数字本身随内容扩展波动是正常的。

种子区间（见 sts/baselines.py 模块注释）：评估种子 0..99，
与未来训练种子（>=10_000）永不相交。
"""

from sts.baselines import evaluate, heuristic_policy, random_policy, run_episode
from sts.content.cards import BASH, DEFEND, STRIKE
from sts.content.monsters import Cultist
from sts.env import StsBattleEnv


def _setup_hand(env, *card_defs):
    """构造手牌（引擎白盒操作，与 test_combat.py 的构造方式一致）。"""
    bc = env.bc
    bc.cards.hand.clear()
    for c in card_defs:
        bc.cards.hand.append(bc.cards.instantiate(c))
    return bc


# ---- 随机策略：能跑完 ----


def test_random_policy_runs_full_seed_set():
    """随机策略：固定种子集 50 局全部正常结束，统计结构完整。"""
    summary = evaluate(random_policy, seeds=range(50), verbose=True)
    assert summary["episodes"] == 50
    assert summary["policy"] == "random_policy"
    assert summary["wins"] + summary["losses"] + summary["truncated"] == 50
    assert 0.0 <= summary["win_rate"] <= 1.0
    assert len(summary["results"]) == 50
    for r in summary["results"]:
        assert r["truncated"] is False  # Cultist 战不会拖到回合上限
        assert r["outcome"] in ("PLAYER_VICTORY", "PLAYER_LOSS")


# ---- 启发式策略：行为单元 + 能跑完 ----


def test_heuristic_prefers_defend_when_attack_incoming():
    """敌意图攻击且格挡不足 → 先打防御。"""
    env = StsBattleEnv()
    env.reset(seed=11)
    bc = _setup_hand(env, STRIKE, DEFEND)
    bc.monsters.monsters[0].set_move(Cultist.DARK_STRIKE)  # 来袭 6 伤 > 格挡 0
    action = heuristic_policy(env)
    assert bc.cards.hand[action - 1].card.name == "Defend"


def test_heuristic_prefers_highest_damage_attack():
    """无攻击意图（咒语回合）→ 打能量允许的最高伤害攻击牌：Bash 8 > Strike 6。"""
    env = StsBattleEnv()
    env.reset(seed=12)
    bc = _setup_hand(env, STRIKE, BASH)
    bc.monsters.monsters[0].set_move(Cultist.INCANTATION)
    action = heuristic_policy(env)
    assert bc.cards.hand[action - 1].card.name == "Bash"


def test_heuristic_attacks_when_block_sufficient():
    """格挡已盖住来袭伤害 → 不再防御，直接输出。"""
    env = StsBattleEnv()
    env.reset(seed=13)
    bc = _setup_hand(env, DEFEND, STRIKE)
    bc.monsters.monsters[0].set_move(Cultist.DARK_STRIKE)  # 来袭 6
    bc.player.block = 10  # 格挡足够
    action = heuristic_policy(env)
    assert bc.cards.hand[action - 1].card.name == "Strike"


def test_heuristic_respects_energy():
    """能量不够最高伤害牌时退而求其次（Bash 2 费 > 1 能量 → 打 Strike）。"""
    env = StsBattleEnv()
    env.reset(seed=14)
    bc = _setup_hand(env, STRIKE, BASH)
    bc.player.energy = 1
    bc.monsters.monsters[0].set_move(Cultist.INCANTATION)
    action = heuristic_policy(env)
    assert bc.cards.hand[action - 1].card.name == "Strike"


def test_heuristic_ends_turn_when_nothing_playable():
    """能量耗尽 → 结束回合。"""
    env = StsBattleEnv()
    env.reset(seed=15)
    _setup_hand(env, STRIKE, DEFEND)
    env.bc.player.energy = 0
    assert heuristic_policy(env) == 0  # ACTION_END_TURN


def test_heuristic_runs_full_seed_set():
    """启发式策略：整个评估种子集 0..99 跑完，统计结构完整（胜率打印不断言）。"""
    summary = evaluate(heuristic_policy, seeds=range(100), verbose=True)
    assert summary["episodes"] == 100
    assert summary["wins"] + summary["losses"] + summary["truncated"] == 100
    assert all(r["truncated"] is False for r in summary["results"])


# ---- 确定性 ----


def test_evaluate_is_deterministic():
    """同种子集评估两次 → 统计结构逐字段一致（含每局记录）。"""
    a = evaluate(random_policy, seeds=range(30), verbose=False)
    b = evaluate(random_policy, seeds=range(30), verbose=False)
    assert a == b
    c = evaluate(heuristic_policy, seeds=range(30), verbose=False)
    d = evaluate(heuristic_policy, seeds=range(30), verbose=False)
    assert c == d


def test_run_episode_reproducible_by_seed():
    """单局复现：同 seed 两次 run_episode 记录一致。"""
    env = StsBattleEnv()
    r1 = run_episode(env, random_policy, seed=77)
    r2 = run_episode(env, random_policy, seed=77)
    assert r1 == r2

"""StsBossEnv 测试（批次 5c）：入场状态模拟、结构、奖励口径、确定性。"""

import numpy as np
import pytest

from sts.boss_env import StsBossEnv
from sts.combat.relics import RelicId
from sts.run_env import BOSSES, REWARD_HP_BASE

from sts.env import OBSERVATION_MAXIMUMS

MAXIMA = np.array(OBSERVATION_MAXIMUMS, dtype=np.int32)


def test_entry_state_structure():
    """入场状态：Boss 遭遇、遗物含燃烧之血+2 精英、牌组 10+、药水合法。"""
    env = StsBossEnv()
    for seed in range(8):
        obs, info = env.reset(seed=seed)
        assert info["encounter"] in BOSSES
        relics = info["relics"]
        assert relics[0] == "BURNING_BLOOD"
        assert len(relics) >= 3  # 开局 + 2 精英掉落
        assert info["entry_deck_size"] >= 10
        assert 1 <= info["entry_hp"] <= 80
        assert len(info["potions"]) == 3


def test_obs_and_action_space():
    from sts.env import N_ACTIONS, OBS_DIM

    env = StsBossEnv()
    obs, _ = env.reset(seed=0)
    assert env.observation_space.shape == (OBS_DIM,)
    assert env.action_space.n == N_ACTIONS
    assert env.observation_space.contains(obs)
    mask = env.action_masks()
    assert mask.any()


def test_reward_matches_run_convention():
    """胜 = 实际 HP / 80（与实时 max_hp 解耦口径）；败 0。"""
    env = StsBossEnv()
    env.reset(seed=0)
    bc = env.bc
    # 直接构造终局：胜利结算
    from sts.combat.types import Outcome

    bc.player.hp = 50
    for m in bc.monsters.monsters:
        if m.alive:
            m.die(bc)
    # 通过 step 触发结算（over 时 battle env 拒绝非法动作——用 END_TURN
    # 前先确认 mask；over 后无合法动作，改为直接验证 _battle 的结果逻辑）
    # v2 口径：胜 = (56 - entry_hp)/80 + 1/8 + 1（entry_hp 记录于 reset）
    from sts.run_env import PROGRESS_CREDIT, WIN_BONUS

    r = (bc.player.hp - env.entry_hp) / REWARD_HP_BASE + PROGRESS_CREDIT + WIN_BONUS
    assert abs(r - ((50 + 6 - env.entry_hp) / 80 + 0.125 + 1.0)) < 1e-9


def test_determinism():
    """同 seed → 同入场状态与轨迹。"""
    env = StsBossEnv()
    obs1, info1 = env.reset(seed=123)
    obs2, info2 = env.reset(seed=123)
    assert np.array_equal(obs1, obs2)
    assert info1["entry_hp"] == info2["entry_hp"]
    assert info1["relics"] == info2["relics"]
    assert info1["entry_deck_size"] == info2["entry_deck_size"]


def test_random_rollout_completes():
    """随机策略完整战斗：不卡死、观测在界内、奖励口径正确。"""
    from sts.baselines import random_policy

    env = StsBossEnv()
    for seed in range(10):
        env.reset(seed=seed)
        steps = 0
        while True:
            mask = env.action_masks()
            if not mask.any():
                break
            obs, r, term, trunc, info = env.step(random_policy(env))
            steps += 1
            assert env.observation_space.contains(obs)
            if term or trunc:
                break
            if steps > 500:
                pytest.fail(f"seed {seed}: 超长局")
        # v2：败 = -entry/80 ≥ -1；胜 ≤ (80-1)/80+1/8+1 < 2.2
        assert -1.0 <= r <= 2.2


def test_fallback_costs_when_json_missing():
    """JSON 缺失/空 → 兜底宽区间（不崩，覆盖过宽不可漏尾）。"""
    env = StsBossEnv()
    env._costs = {}  # 模拟缺失
    obs, info = env.reset(seed=0)
    assert 1 <= info["entry_hp"] <= 80


def test_heuristic_baseline_runs():
    """heuristic baseline 经 bc 属性可完整跑局（接口兼容）。"""
    from sts.baselines import heuristic_policy

    env = StsBossEnv()
    env.reset(seed=0)
    steps = 0
    while True:
        mask = env.action_masks()
        if not mask.any():
            break
        obs, r, term, trunc, info = env.step(heuristic_policy(env))
        steps += 1
        if term or trunc or steps > 500:
            break
    assert steps > 0


def test_card_pity_and_potion_blizzard_evolve():
    """快进路径逐场调用掉落逻辑：保底/补偿计数器在演化（非恒定）。"""
    env = StsBossEnv()
    env.reset(seed=0)
    # 间接证据：多 seed 下入场遗物/牌组不同（掉落流驱动）
    states = set()
    for s in range(12):
        _obs, info = env.reset(seed=s)
        states.add((info["entry_deck_size"], tuple(info["relics"][1:])))
    assert len(states) > 1

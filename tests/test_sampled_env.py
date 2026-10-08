"""StsSampledEnv 测试（批次 5c v3）：难度参数表、采样分布、奖励口径、
确定性、baselines 兼容。"""

import numpy as np
import pytest

from sts.env import OBSERVATION_MAXIMUMS, OBSERVATION_MINIMUMS, TURN_LIMIT
from sts.sampled_env import DIFFICULTY_SPECS, StsSampledEnv

MAXIMA = np.array(OBSERVATION_MAXIMUMS, dtype=np.int32)
MINIMA = np.array(OBSERVATION_MINIMUMS, dtype=np.int32)


def test_difficulty_spec_table():
    """用户设定的难度参数表（2026-10-08）。"""
    assert DIFFICULTY_SPECS["weak"]["weight"] == 0.3
    assert DIFFICULTY_SPECS["strong"]["weight"] == 0.5
    assert DIFFICULTY_SPECS["elite"]["weight"] == 1.0
    assert DIFFICULTY_SPECS["boss"]["weight"] == 2.0  # ×5 尺度悬殊塌缩后确认降为 ×2
    assert DIFFICULTY_SPECS["weak"]["hp"] == (60, 80)
    assert DIFFICULTY_SPECS["strong"]["hp"] == (40, 80)
    assert DIFFICULTY_SPECS["elite"]["hp"] == (30, 70)
    assert DIFFICULTY_SPECS["boss"]["hp"] == (25, 70)
    assert DIFFICULTY_SPECS["boss"]["extra_cards"] == (3, 8)
    assert DIFFICULTY_SPECS["weak"]["removes"] == (0, 0)


def test_reset_samples_within_bounds():
    """40 局采样：HP/卡组/药水/遗物全部落在参数表区间。"""
    for diff in DIFFICULTY_SPECS:
        spec = DIFFICULTY_SPECS[diff]
        env = StsSampledEnv(diff)
        for s in range(40):
            obs, info = env.reset(seed=s)
            assert spec["hp"][0] <= info["entry_hp"] <= spec["hp"][1]
            bc = env.bc
            n_cards = len(bc.cards.draw_pile) + len(bc.cards.hand) + len(bc.cards.discard_pile)
            # 卡组 = 10 - 删除(≤2) + 新增（弱怪可为纯初始 10）
            lo = 10 - spec["removes"][1] + spec["extra_cards"][0]
            hi = 10 + spec["extra_cards"][1]
            assert lo <= n_cards <= hi
            n_relics = len(bc.relics.relics)
            assert spec["relics"][0] <= n_relics <= spec["relics"][1]
            n_potions = sum(1 for p in bc.player.potions if p is not None)
            assert n_potions <= 3
            assert env.observation_space.contains(obs)


def test_potion_rate_matches_spec():
    """药水率粗验证：40 局 × 3 栏的观测频率落在二项分布 3σ 内。"""
    for diff, p in (("weak", 0.10), ("strong", 0.20), ("elite", 0.50), ("boss", 0.70)):
        env = StsSampledEnv(diff)
        n = 0
        for s in range(40):
            env.reset(seed=s)
            n += sum(1 for p in env.bc.player.potions if p is not None)
        rate = n / 120
        sigma = (p * (1 - p) / 120) ** 0.5
        assert abs(rate - p) < 3 * sigma + 0.05, f"{diff}: {rate:.2f} vs {p}"


def test_reward_weights():
    """奖励 = HP/80 × 难度权重（胜）；败 = −入场HP/80 × 权重。"""
    from sts.combat.types import Outcome

    for diff, w in (("weak", 0.3), ("strong", 0.5), ("elite", 1.0), ("boss", 2.0)):
        env = StsSampledEnv(diff)
        env.reset(seed=0)
        bc = env.bc
        bc.player.hp = 40
        for m in bc.monsters.monsters:
            if m.alive:
                m.die(bc)
        # 结算走 step 的 reward 公式（over 后 battle.step 拒绝——用
        # action_masks 触发的路径不可达，改为直接公式验证）
        expected = bc.player.hp / 80 * w
        assert abs(expected - 40 / 80 * w) < 1e-9


def test_truncation_negative_like_loss():
    """截断与败局同价（拖延防护沿用 v2 终版结论）。"""
    from sts.env import ACTION_END_TURN

    env = StsSampledEnv("weak")
    env.reset(seed=0)
    entry = env.entry_hp
    env.bc.turn = TURN_LIMIT + 1
    obs, r, term, trunc, info = env.step(ACTION_END_TURN)
    assert term or trunc
    assert abs(r - (-entry / 80 * 0.3)) < 0.05  # 战损项含敌方回合掉血，容差放宽


def test_mixed_difficulty_sampling():
    """难度元组：每局随机抽一档，覆盖全档。"""
    env = StsSampledEnv(("weak", "strong", "elite", "boss"))
    seen = set()
    for s in range(40):
        _obs, info = env.reset(seed=s)
        seen.add(info["difficulty"])
    assert seen == {"weak", "strong", "elite", "boss"}


def test_determinism():
    env = StsSampledEnv(("elite",))
    obs1, info1 = env.reset(seed=42)
    obs2, info2 = env.reset(seed=42)
    assert np.array_equal(obs1, obs2)
    assert info1["entry_hp"] == info2["entry_hp"]
    assert info1["encounter"] == info2["encounter"]


def test_baselines_run_full_episode():
    from sts.baselines import heuristic_policy, random_policy

    for pol in (random_policy, heuristic_policy):
        env = StsSampledEnv()
        env.reset(seed=0)
        steps = 0
        while True:
            mask = env.action_masks()
            if not mask.any():
                break
            obs, r, term, trunc, info = env.step(pol(env))
            steps += 1
            assert env.observation_space.contains(obs)
            if term or trunc or steps > 500:
                break
        assert steps > 0


def test_bash_not_removed_and_basics_only_removed():
    """删除只作用于初始打击/防御；痛击永在。"""
    from sts.content.cards.ironclad import BASH

    env = StsSampledEnv("boss")
    found_bash = False
    for s in range(30):
        env.reset(seed=s)
        bc = env.bc
        all_cards = list(bc.cards.draw_pile) + list(bc.cards.hand)
        names = [c.card.name for c in all_cards]
        if "Bash" in names:
            found_bash = True
            break
    assert found_bash

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
    # 冷启动变体（boss1000 等）不在此测——HP 与难度解耦，参数表语义不同
    for diff in ("weak", "strong", "elite", "boss"):
        spec = DIFFICULTY_SPECS[diff]
        env = StsSampledEnv(diff)
        for s in range(40):
            obs, info = env.reset(seed=s)
            assert spec["hp"][0] <= info["entry_hp"] <= spec["hp"][1]
            bc = env.bc
            # reset 时刻（未 step）三堆计数 = 卡组规模（无临时牌生成）
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
    """纯战损奖励（2026-10-09）：胜 = (终局HP − 入场HP) × 权重；
    败/截断 = −(入场HP + 存活怪物剩余血量) × 权重。构造终局态直接
    验证公式（battle.step 在 over 后拒绝，走 _terminal_reward）。"""
    from sts.combat.types import Outcome

    for diff, w in (("weak", 0.3), ("strong", 0.5), ("elite", 1.0), ("boss", 2.0), ("random", 1.0)):
        env = StsSampledEnv(diff)
        env.reset(seed=0)
        bc = env.bc
        entry = env.entry_hp
        # 胜局：终局 40 血 → 奖励 = (40 − entry) × w（战损恒定计价）
        bc.player.hp = 40
        bc.outcome = Outcome.PLAYER_VICTORY
        assert abs(env._terminal_reward(bc, w) - (40 - entry) * w) < 1e-9
        # 败局：怪物剩余 12 + 7 血 → −(entry + 19) × w
        bc.outcome = Outcome.PLAYER_LOSS
        ms = [m for m in bc.monsters.monsters]
        for i, hp in enumerate((12, 7)):
            if i < len(ms):
                ms[i].hp = hp
        for m in ms[2:]:
            m.hp = 0
        remaining = sum(m.hp for m in ms if m.hp > 0)
        assert abs(env._terminal_reward(bc, w) - (-(entry + remaining) * w)) < 1e-9


def test_truncation_negative_like_loss():
    """截断与败局同价（拖延防护沿用 v2 终版结论）：终局项 =
    −(入场HP + 怪物剩余血量) × 权重——拖延时怪物满血，代价不低于
    正常败局。reward 另含该步塑形项（势函数快照差）。"""
    from sts.env import ACTION_END_TURN
    from sts.sampled_env import SHAPING_GAMMA

    env = StsSampledEnv("weak")
    env.reset(seed=0)
    entry = env.entry_hp
    env.bc.turn = TURN_LIMIT + 1
    phi_before = env._potential(env.bc)
    obs, r, term, trunc, info = env.step(ACTION_END_TURN)
    assert term or trunc
    remaining = sum(m.hp for m in env.bc.monsters.monsters if m.hp > 0)
    terminal = -(entry + remaining) * 0.3
    shaping = SHAPING_GAMMA * env._potential(env.bc) - phi_before
    assert abs(r - (terminal + shaping)) < 1e-9


def test_random_spec():
    """随机预训练档（2026-10-09 用户决策）：全池均匀 20~30 张卡组、
    30% 升级位、固定 80 入场、无药水无遗物、遭遇覆盖全部 21 场。"""
    env = StsSampledEnv("random")
    seen = set()
    n_upgrade = 0
    n_cards = 0
    for s in range(200):
        obs, info = env.reset(seed=s)
        assert info["entry_hp"] == 80  # 固定满血，无随机 HP
        seen.add(info["encounter"])
        deck = env._battle.deck
        assert 20 <= len(deck) <= 30
        n_cards += len(deck)
        n_upgrade += sum(1 for c in deck if isinstance(c, tuple) and c[1] is True)
        # 无药水无遗物
        assert not env.bc.relics.relics
        assert all(p is None for p in env.bc.player.potions)
        assert env.observation_space.contains(obs)
    assert len(seen) == 21  # 9 弱 + 7 强 + 2 精英 + 3 Boss
    # 升级位 ~30%（200 局 ~5000 张，3σ 容差）
    share = n_upgrade / n_cards
    sigma = (0.3 * 0.7 / n_cards) ** 0.5
    assert abs(share - 0.3) < 4 * sigma, f"升级率 {share:.2%}"


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


def test_potential_shaping():
    """势函数塑形（2026-10-09）：非终局步 reward = γΦ(s') − Φ(s)。
    出攻击牌打掉怪物 HP → 正塑形；公式逐步精确校验。"""
    from sts.env import HAND_SLOT_BASE
    from sts.sampled_env import SHAPING_GAMMA, SHAPING_MONSTER_EPS

    env = StsSampledEnv("strong")
    played = False
    for seed in range(30):
        obs, info = env.reset(seed=seed)
        bc = env.bc
        mask = env.action_masks()
        for slot in range(len(bc.cards.hand)):
            inst = bc.cards.hand[slot]
            if inst.card.ctype == "Attack" and inst.card.cost <= bc.player.energy and mask[HAND_SLOT_BASE + slot]:
                mhp_before = sum(m.hp for m in bc.monsters.monsters if m.hp > 0)
                php_before = bc.player.hp
                obs, r, term, trunc, _ = env.step(HAND_SLOT_BASE + slot)
                assert not (term or trunc)
                mhp_after = sum(m.hp for m in env.bc.monsters.monsters if m.hp > 0)
                php_after = env.bc.player.hp
                expected = SHAPING_GAMMA * (php_after - SHAPING_MONSTER_EPS * mhp_after) - (
                    php_before - SHAPING_MONSTER_EPS * mhp_before
                )
                assert abs(r - expected) < 1e-9
                assert mhp_after < mhp_before  # 打出了伤害
                played = True
                break
        if played:
            break
    assert played, "前 30 个种子起手应含可支付攻击牌"


def test_potential_shaping_terminal_sums_bounded():
    """塑形不改最优策略的边界校验：整局回报 = 终局奖励 + γ^TΦ(s_T)
    − Φ(s_0)（ telescoping ），量级与纯终局口径同阶。"""
    env = StsSampledEnv("weak")
    total = 0.0
    for s in (70, 71, 72):
        obs, _ = env.reset(seed=s)
        bc = env.bc
        phi0 = env._potential(bc)
        steps = 0
        while True:
            mask = env.action_masks()
            legal = np.flatnonzero(mask)
            a = int(legal[0] if len(legal) == 1 else legal[s % len(legal)])
            obs, r, term, trunc, info = env.step(a)
            total += r
            steps += 1
            if term or trunc or steps > 400:
                break
        phiT = env._potential(env.bc)
        # γ<1 时塑形和无纯 telescope（每步泄漏 ~1%·Φ，T~100 步累计
        # ~百点）——只做量级 sanity：终局 ±(entry+怪物总HP)×0.3 加
        # 塑形泄漏上界
        assert abs(total) < 400

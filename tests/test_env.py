"""StsBattleEnv 测试：API 合规、mask 正确性、信息泄露审计（DESIGN.md
§4.3，最重要）、确定性重放、观测一致性。"""

import inspect
import random

import numpy as np
import pytest

from sts.content.cards import BASH, STRIKE
from sts.env import (
    ACTION_END_TURN,
    CARD_INDEX,
    HAND_SLOT_BASE,
    N_ACTIONS,
    OBSERVATION_MAXIMUMS,
    OBS_DIM,
    O_PILE_DISCARD,
    O_PLAYER,
    TARGETED_BASE,
    TURN_LIMIT,
    StsBattleEnv,
)

MAXIMA = np.array(OBSERVATION_MAXIMUMS, dtype=np.int32)


# ---- API 合规 ----


def test_action_and_observation_spaces():
    """动作空间 61（编码一步到位）；观测 Box int32 与上界表逐维对齐。"""
    env = StsBattleEnv()
    assert env.action_space.n == N_ACTIONS == 61
    assert env.observation_space.shape == (OBS_DIM,)
    assert env.observation_space.dtype == np.int32
    assert len(OBSERVATION_MAXIMUMS) == OBS_DIM
    obs, info = env.reset(seed=0)
    assert env.observation_space.contains(obs)
    assert info.keys() >= {"hp_remaining", "turns", "won", "outcome", "battle_seed"}


def test_api_signatures():
    """reset/step/action_masks 符合 Gymnasium 与 MaskablePPO 约定。"""
    assert set(inspect.signature(StsBattleEnv.reset).parameters) >= {"seed", "options"}
    assert set(inspect.signature(StsBattleEnv.step).parameters) >= {"action"}
    env = StsBattleEnv()
    env.reset(seed=0)
    mask = env.action_masks()
    assert isinstance(mask, np.ndarray) and mask.dtype == bool
    assert mask.shape == (N_ACTIONS,)


def test_reset_seed_determinism():
    """reset(seed=s) 两次 → 同一场战斗（观测与战斗种子都一致）。"""
    env = StsBattleEnv()
    obs1, info1 = env.reset(seed=123)
    obs2, info2 = env.reset(seed=123)
    assert np.array_equal(obs1, obs2)
    assert info1["battle_seed"] == info2["battle_seed"]
    obs3, _ = env.reset(seed=124)
    assert not np.array_equal(obs1, obs3)


def test_reset_unseeded_varies():
    """不传 seed 的 reset 每场不同（np_random 熵源派生）。"""
    env = StsBattleEnv()
    obs1, _ = env.reset()
    obs2, _ = env.reset()
    assert not np.array_equal(obs1, obs2)


# ---- mask 正确性 ----


def test_mask_basic_shape():
    """玩家阶段：END_TURN 恒合法；实际手牌内的槽合法，空槽不合法；
    单怪遭遇下组合段整体不合法（走槽动作自动指向）。"""
    env = StsBattleEnv()
    env.reset(seed=1)
    bc = env.bc
    mask = env.action_masks()
    assert mask[ACTION_END_TURN]
    n = len(bc.cards.hand)
    assert 0 < n <= 10
    assert mask[HAND_SLOT_BASE : HAND_SLOT_BASE + n].all()  # 开局 3 能量够所有 1~2 费牌
    assert not mask[HAND_SLOT_BASE + n : TARGETED_BASE].any()
    assert not mask[TARGETED_BASE:].any()


def test_mask_energy_gate():
    """能量不足的槽不合法；能量耗尽后只剩 END_TURN。"""
    env = StsBattleEnv()
    env.reset(seed=2)
    bc = env.bc
    bc.cards.hand.clear()
    bc.cards.hand.extend([bc.cards.instantiate(BASH), bc.cards.instantiate(STRIKE)])
    bc.player.energy = 1
    mask = env.action_masks()
    assert not mask[HAND_SLOT_BASE + 0]  # Bash 2 费 > 1 能量
    assert mask[HAND_SLOT_BASE + 1]  # Strike 1 费可打
    bc.player.energy = 0
    mask = env.action_masks()
    assert not mask[HAND_SLOT_BASE:TARGETED_BASE].any()
    assert mask[ACTION_END_TURN]


def test_mask_needs_target_requires_targetable_enemy():
    """需要目标的牌在唯一怪死后无合法出牌动作（怪死即胜利，此处验证
    mask 与引擎自动指向条件一致：构造 monster_count>1 的假场景）。"""
    env = StsBattleEnv()
    env.reset(seed=4)
    bc = env.bc
    # 造一个两怪场景：第二只已死（不可指向）→ 引擎不会自动指向，
    # 组合段应对存活那只怪合法、槽动作不合法
    from sts.content.monsters import Cultist

    dead = Cultist(idx=1, hp=0, max_hp=48)
    dead.move_history.clear()  # 死亡怪无意图
    bc.monsters.monsters.append(dead)
    bc.cards.hand.clear()
    bash = bc.cards.instantiate(BASH)  # needs_target=True
    bc.cards.hand.append(bash)
    mask = env.action_masks()
    assert not mask[HAND_SLOT_BASE + 0]  # 槽动作：引擎 monster_count!=1 会拒绝
    assert mask[TARGETED_BASE + 0 * 5 + 0]  # (槽0, 目标0=存活怪) 合法
    assert not mask[TARGETED_BASE + 0 * 5 + 1]  # 目标 1 已死，不合法


def test_mask_all_false_after_battle_over():
    """战斗结束后全 False；终止后再 step 直接断言失败。"""
    env = StsBattleEnv()
    env.reset(seed=3)
    bc = env.bc
    bc.monsters.monsters[0].hp = 6  # 一张 Strike 正好击杀
    bc.cards.hand.clear()
    bc.cards.hand.append(bc.cards.instantiate(STRIKE))
    obs, reward, terminated, truncated, info = env.step(HAND_SLOT_BASE)
    assert terminated and not truncated
    assert info["won"]
    assert abs(reward - bc.player.hp / bc.player.max_hp) < 1e-9  # 战损口径：终局 HP/max
    assert not env.action_masks().any()
    with pytest.raises(AssertionError):
        env.step(ACTION_END_TURN)


def test_step_rejects_illegal_action():
    """空槽 / 超出能量 / 越界动作都被拒绝（训练依赖 mask，不允许走非法路径）。"""
    env = StsBattleEnv()
    env.reset(seed=6)
    n = len(env.bc.cards.hand)
    with pytest.raises(AssertionError):
        env.step(HAND_SLOT_BASE + n)  # 空槽
    with pytest.raises(AssertionError):
        env.step(N_ACTIONS + 3)  # 越界
    env.bc.player.energy = 0
    with pytest.raises(AssertionError):
        env.step(HAND_SLOT_BASE)  # 能量不足


# ---- 观测一致性与信息泄露审计 ----


def test_step_updates_observation_consistently():
    """出牌后引擎状态与观测逐段一致（能量/手牌数/弃牌堆计数/敌 HP）。"""
    env = StsBattleEnv()
    env.reset(seed=5)
    bc = env.bc
    obs0 = env._get_obs()
    idx = next(i for i, c in enumerate(bc.cards.hand) if c.card.name == "Strike")
    m_hp0 = bc.monsters.monsters[0].hp
    energy0 = bc.player.energy
    obs1, reward, terminated, truncated, info = env.step(HAND_SLOT_BASE + idx)
    assert reward == 0.0 and not terminated and not truncated
    assert bc.player.energy == energy0 - 1
    assert len(bc.cards.hand) == obs0[O_PLAYER + 5] - 1
    assert bc.monsters.monsters[0].hp == m_hp0 - 6  # 无力量/易伤：基础 6 伤
    assert obs1[O_PLAYER + 3] == bc.player.energy
    assert obs1[O_PLAYER + 5] == len(bc.cards.hand)
    # Strike 进弃牌堆：构成计数 +1（开局弃牌堆为空）
    assert obs0[O_PILE_DISCARD + CARD_INDEX["Strike"]] == 0
    assert obs1[O_PILE_DISCARD + CARD_INDEX["Strike"]] == 1


def test_info_leak_audit():
    """DESIGN.md §4.3 信息泄露审计：同一状态下，打乱三堆 list 顺序 +
    烧掉未来随机流（shuffle/ai/misc），两次观测必须逐位一致。

    多个种子 × 多个时刻（每个决策点都审），任何新增观测特征都必须
    继续通过本测试。
    """
    shuffler = random.Random(999)  # 独立于游戏 RNG，纯打乱顺序
    for seed in (0, 7, 42):
        env = StsBattleEnv()
        env.reset(seed=seed)
        for _ in range(6):  # 多个时刻
            bc = env.bc
            obs_a = env._get_obs().copy()
            # 黑名单 1：牌堆顺序——直接乱序三堆的内部 list
            for pile in (bc.cards.draw_pile, bc.cards.discard_pile, bc.cards.exhaust_pile):
                shuffler.shuffle(pile)
            # 黑名单 2/3：未来随机流（未来洗牌/意图/杂项）——烧掉若干抽样
            for _ in range(3):
                bc.rngs.shuffle.int_inclusive(0, 2**20)
                bc.rngs.ai.int_inclusive(0, 99)
                bc.rngs.misc.int_inclusive(0, 2**20)
            assert np.array_equal(obs_a, env._get_obs()), f"种子 {seed} 泄露了不可见信息"
            # 推进一步到下一个时刻（合法随机动作）
            mask = env.action_masks()
            if not mask.any():
                break
            env.step(int(env.np_random.choice(np.flatnonzero(mask))))


# ---- 随机 rollout 与确定性 ----


def _rollout(env, seed):
    """mask 内随机采样跑一整局，返回逐步观测序列与结果。"""
    obs, _ = env.reset(seed=seed)
    seq = [obs.copy()]
    rewards = []
    terminated = truncated = False
    while not (terminated or truncated):
        mask = env.action_masks()
        assert mask.any()  # 玩家阶段至少 END_TURN 合法
        action = int(env.np_random.choice(np.flatnonzero(mask)))
        obs, r, terminated, truncated, info = env.step(action)
        seq.append(obs.copy())
        rewards.append(r)
    return seq, rewards, terminated, truncated, info


def test_random_rollouts_complete_and_deterministic():
    """50 局完整战斗不崩（胜率不做要求）；观测全程在界内；
    同种子重放观测序列与奖励逐位一致。"""
    env = StsBattleEnv()
    for seed in range(50):
        seq1, r1, term1, trunc1, info1 = _rollout(env, seed)
        seq2, r2, term2, trunc2, _ = _rollout(env, seed)
        assert term1 or trunc1  # 每局都正常结束
        assert term1 == term2 and trunc1 == trunc2
        assert r1 == r2
        assert len(seq1) == len(seq2)
        for a, b in zip(seq1, seq2):
            assert np.array_equal(a, b)
        for o in seq1:
            assert o.dtype == np.int32
            assert (o >= 0).all() and (o <= MAXIMA).all()
        # 结束时 info 与奖励口径一致（战损口径：胜=终局HP/max_hp，败=0）
        if info1["outcome"] == "PLAYER_VICTORY":
            assert 0 < r1[-1] <= 1.0
        else:
            assert r1[-1] == 0.0


# ---- 截断保险丝 ----


def test_truncation_at_turn_limit():
    """回合数超 TURN_LIMIT 时 truncated=True、奖励 0（胜负未定）。"""
    env = StsBattleEnv()
    env.reset(seed=9)
    env.bc.turn = TURN_LIMIT + 1  # 直接拨到超限（正常 Cultist 战到不了）
    obs, reward, terminated, truncated, info = env.step(ACTION_END_TURN)
    assert truncated and not terminated
    assert reward == 0.0


# ---- 随机遭遇模式（encounter="random"）----


def test_random_encounter_samples_from_pool():
    """random 模式：遭遇均来自弱怪池，多种子下覆盖多种遭遇。"""
    from sts.env import WEAK_POOL

    env = StsBattleEnv(encounter="random")
    seen = set()
    for s in range(30):
        _obs, info = env.reset(seed=s)
        assert info["encounter"] in WEAK_POOL
        seen.add(info["encounter"])
    assert len(seen) >= 3  # 30 局至少抽到 3 种（概率 < 1e-4 的偶然才不满足）


def test_random_encounter_deterministic():
    """同种子 → 同遭遇 + 同轨迹（复现性）。"""
    env = StsBattleEnv(encounter="random")
    obs1, info1 = env.reset(seed=21)
    enc1 = info1["encounter"]
    import numpy as np

    traj1 = [obs1.copy()]
    for _ in range(4):
        mask = env.action_masks()
        obs1, *_ = env.step(int(np.flatnonzero(mask)[0]))
        traj1.append(obs1.copy())

    obs2, info2 = env.reset(seed=21)
    traj2 = [obs2.copy()]
    for _ in range(4):
        mask = env.action_masks()
        obs2, *_ = env.step(int(np.flatnonzero(mask)[0]))
        traj2.append(obs2.copy())

    assert info2["encounter"] == enc1
    assert all((a == b).all() for a, b in zip(traj1, traj2))


def test_fixed_encounter_unaffected():
    """random 模式不影响指定遭遇的旧行为（回归保护）。"""
    env = StsBattleEnv()  # 默认 cultist
    for s in (1, 2, 3):
        _obs, info = env.reset(seed=s)
        assert info["encounter"] == "cultist"

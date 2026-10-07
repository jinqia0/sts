"""StsBattleEnv 测试：API 合规、mask 正确性、信息泄露审计（DESIGN.md
§4.3，最重要）、确定性重放、观测一致性。批次 5a：全量词表观测
（职业/金币/遗物/药水/limbo/stance/orb 段）+ unplayable mask 修复。"""

import inspect
import random

import numpy as np
import pytest

from sts.combat.relics import RelicId
from sts.content.cards import BASH, CLASH, STRIKE, WOUND
from sts.content.potions import FIRE_POTION
from sts.env import (
    ACTION_END_TURN,
    HAND_SLOT_BASE,
    N_ACTIONS,
    N_TARGET_SLOTS,
    OBSERVATION_MAXIMUMS,
    OBSERVATION_MINIMUMS,
    OBS_DIM,
    O_CLASS,
    O_HAND_SLOT,
    O_PILE_DISCARD,
    O_PILE_LIMBO,
    O_POTION,
    O_PLAYER,
    O_RELIC,
    TARGETED_BASE,
    TURN_LIMIT,
    StsBattleEnv,
)
from sts.vocab import CARD_INDEX, card_vocab_index

MAXIMA = np.array(OBSERVATION_MAXIMUMS, dtype=np.int32)
MINIMA = np.array(OBSERVATION_MINIMUMS, dtype=np.int32)


# ---- API 合规 ----


def test_action_and_observation_spaces():
    """动作空间 120（5b 全量：出牌/药水/选卡/Scry）；观测 Box int32
    与上界表逐维对齐。"""
    env = StsBattleEnv()
    assert env.action_space.n == N_ACTIONS == 120
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
    # Strike 进弃牌堆：构成计数 +1（开局弃牌堆为空）；升级版占 2k+1 位
    strike_base = CARD_INDEX["ironclad:STRIKE"]
    assert obs0[O_PILE_DISCARD + strike_base] == 0
    assert obs1[O_PILE_DISCARD + strike_base] == 1


def test_info_leak_audit():
    """DESIGN.md §4.3 信息泄露审计：同一状态下，打乱四堆 list 顺序 +
    烧掉未来随机流（shuffle/ai/misc），两次观测必须逐位一致。

    多个种子 × 多个时刻（每个决策点都审），任何新增观测特征都必须
    继续通过本测试。批次 5a：审计范围扩到 limbo 保留区（第 4 堆）与
    全部新段（职业/金币/遗物/药水/stance/orb）。
    """
    shuffler = random.Random(999)  # 独立于游戏 RNG，纯打乱顺序
    for seed in (0, 7, 42):
        env = StsBattleEnv()
        env.reset(seed=seed)
        for _ in range(6):  # 多个时刻
            bc = env.bc
            obs_a = env._get_obs().copy()
            # 黑名单 1：牌堆顺序——直接乱序四堆的内部 list
            for pile in (
                bc.cards.draw_pile,
                bc.cards.discard_pile,
                bc.cards.exhaust_pile,
                bc.cards.limbo,
            ):
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
            assert (o >= MINIMA).all() and (o <= MAXIMA).all()
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


# ---- 怪物种类 one-hot（MONSTER_INDEX 词表）----


def test_species_onehot_lights_up():
    """每个存活敌人的种类段有且仅有一个 1，且词表名与遭遇匹配。"""
    from sts.env import MONSTER_INDEX, MONSTER_VOCAB_SIZE, _E_SPECIES, _N_ENEMY_FEAT, O_ENEMY

    expect = {
        "cultist": {"Cultist"},
        "jaw_worm": {"Jaw Worm"},
        "louses": {"Red Louse", "Green Louse"},
        "slimes_s": {"Acid Slime (S)", "Spike Slime (S)"},
        "fungi_beast": {"Fungi Beast"},
    }
    for enc, names in expect.items():
        env = StsBattleEnv(encounter=enc)
        obs, _ = env.reset(seed=1)
        seen = set()
        for si in range(N_TARGET_SLOTS):
            b = O_ENEMY + si * _N_ENEMY_FEAT
            seg = obs[b + _E_SPECIES : b + _E_SPECIES + MONSTER_VOCAB_SIZE]
            assert seg.sum() <= 1  # one-hot 或全零（空槽）
            if seg.sum() == 1:
                idx = int(np.flatnonzero(seg)[0])
                seen.add(next(k for k, v in MONSTER_INDEX.items() if v == idx))
        assert seen == names, f"{enc}: {seen} != {names}"


def test_species_onehot_dead_slot_cleared():
    """死亡怪整槽清零（含种类段），空槽无残留。"""
    from sts.env import MONSTER_VOCAB_SIZE, _E_SPECIES, _N_ENEMY_FEAT, O_ENEMY

    env = StsBattleEnv(encounter="louses")
    obs, _ = env.reset(seed=2)
    env.bc.monsters.monsters[0].hp = 0  # 红虱死亡
    obs = env._get_obs()
    b = O_ENEMY  # 槽 0
    seg = obs[b + _E_SPECIES : b + _E_SPECIES + MONSTER_VOCAB_SIZE]
    assert seg.sum() == 0  # 死亡槽种类段归零


# ---- 批次 5a：全量词表观测段 ----


def test_obs_upgraded_card_counting():
    """升级版占 2k+1 词表位：弃牌堆里 Strike 与 Strike+ 分维计数；
    手牌槽升级位点亮。"""
    from sts.env import _N_SLOT_FEAT, _S_UPGRADED

    env = StsBattleEnv()
    env.reset(seed=1)
    bc = env.bc
    inst = bc.cards.instantiate(STRIKE)
    up = bc.cards.instantiate(STRIKE)
    up.upgraded = True
    bc.cards.discard_pile.extend([inst, up])
    obs = env._get_obs()
    base = card_vocab_index(STRIKE)
    assert obs[O_PILE_DISCARD + base] == 1
    assert obs[O_PILE_DISCARD + base + 1] == 1
    bc.cards.hand.append(up)
    obs = env._get_obs()
    i = len(bc.cards.hand) - 1
    assert obs[O_HAND_SLOT + i * _N_SLOT_FEAT + _S_UPGRADED] == 1


def test_obs_character_segment():
    """职业 one-hot；非铁甲职业 max_hp 构造后修正（观测口径真实）。"""
    env = StsBattleEnv(character="silent")
    obs, info = env.reset(seed=0)
    assert info["character"] == "silent"
    assert obs[O_CLASS + 1] == 1 and obs[O_CLASS : O_CLASS + 4].sum() == 1
    assert obs[O_PLAYER + 1] == 70  # max_hp 修正
    assert 0 < obs[O_PLAYER + 0] <= 70


def test_obs_character_rejects_unknown():
    with pytest.raises(ValueError):
        StsBattleEnv(character="warrior")


def test_obs_gold():
    env = StsBattleEnv()
    env.reset(seed=0)
    env.bc.player.gold = 123
    assert env._get_obs()[O_PLAYER + 6] == 123


def test_obs_relic_segment():
    """遗物 multi-hot + 公开计数器段与引擎 RelicContainer 一致。"""
    from sts.env import _R_COUNTER, _R_ONEHOT, N_RELICS

    env = StsBattleEnv(relics=[RelicId.HAPPY_FLOWER, RelicId.PEN_NIB])
    obs, _ = env.reset(seed=2)
    bc = env.bc
    assert obs[O_RELIC + _R_ONEHOT + RelicId.HAPPY_FLOWER.value] == 1
    assert obs[O_RELIC + _R_ONEHOT + RelicId.PEN_NIB.value] == 1
    assert obs[O_RELIC + _R_ONEHOT : O_RELIC + _R_ONEHOT + N_RELICS].sum() == 2
    assert (
        obs[O_RELIC + _R_COUNTER + RelicId.HAPPY_FLOWER.value]
        == bc.relics.counter(RelicId.HAPPY_FLOWER)
    )
    # 未持有遗物：multi-hot 与计数器都恒 0
    assert obs[O_RELIC + _R_ONEHOT + RelicId.OMAMORI.value] == 0
    assert obs[O_RELIC + _R_COUNTER + RelicId.OMAMORI.value] == 0


def test_obs_potion_segment():
    """药水栏：占用位 + 药水 one-hot，空槽全零（喝药动作段是 5b）。"""
    from sts.env import _N_POTION_FEAT, _P_OCC, _P_ONEHOT
    from sts.vocab import POTION_INDEX

    env = StsBattleEnv(potions=[FIRE_POTION])
    obs, _ = env.reset(seed=3)
    assert obs[O_POTION + _P_OCC] == 1
    assert obs[O_POTION + _P_ONEHOT + POTION_INDEX["Fire Potion"]] == 1
    for i in (1, 2):  # 基础 3 槽的后两格为空
        b = O_POTION + i * _N_POTION_FEAT
        assert obs[b : b + _N_POTION_FEAT].sum() == 0


def test_obs_limbo_segment():
    """limbo 保留区构成计数（Retain 牌上回合在手里，构成可见）。"""
    env = StsBattleEnv()
    env.reset(seed=4)
    bc = env.bc
    bc.cards.limbo.append(bc.cards.instantiate(STRIKE))
    obs = env._get_obs()
    base = card_vocab_index(STRIKE)
    assert obs[O_PILE_LIMBO + base] == 1


# ---- 批次 5a：mask 出牌资格闸（修复 unplayable 缺口）----


def test_mask_unplayable_cards():
    """unplayable 牌（Wound）槽位不合法——原先被误标合法，靠 env 兜底。"""
    env = StsBattleEnv()
    env.reset(seed=5)
    bc = env.bc
    bc.cards.hand.clear()
    bc.cards.hand.extend([bc.cards.instantiate(WOUND), bc.cards.instantiate(STRIKE)])
    mask = env.action_masks()
    assert not mask[HAND_SLOT_BASE + 0]
    assert mask[HAND_SLOT_BASE + 1]


def test_mask_unplayable_unlocked_by_medical_kit():
    """Medical Kit 解锁 Status 牌（Blue Candle 解锁 Curse 同路径）。"""
    env = StsBattleEnv(relics=[RelicId.MEDICAL_KIT])
    env.reset(seed=5)
    bc = env.bc
    bc.cards.hand.clear()
    bc.cards.hand.append(bc.cards.instantiate(WOUND))
    assert env.action_masks()[HAND_SLOT_BASE]


def test_mask_play_condition_clash():
    """Clash：手牌全是攻击牌才可打（play_condition 镜像）。"""
    from sts.content.cards import DEFEND

    env = StsBattleEnv()
    env.reset(seed=6)
    bc = env.bc
    bc.cards.hand.clear()
    bc.cards.hand.append(bc.cards.instantiate(CLASH))
    assert env.action_masks()[HAND_SLOT_BASE]  # 只有 Clash：条件满足
    bc.cards.hand.append(bc.cards.instantiate(STRIKE))
    assert env.action_masks()[HAND_SLOT_BASE]  # Strike 也是攻击牌：仍满足
    bc.cards.hand.append(bc.cards.instantiate(DEFEND))
    mask = env.action_masks()
    assert not mask[HAND_SLOT_BASE]  # 混入 Defend 后不满足
    assert mask[HAND_SLOT_BASE + 2]


def test_mask_entangled_blocks_attacks():
    """缠绕只拦攻击牌（引擎 play_card 同款判定）。"""
    from sts.combat.types import PlayerStatus

    env = StsBattleEnv()
    env.reset(seed=7)
    bc = env.bc
    bc.cards.hand.clear()
    bc.cards.hand.append(bc.cards.instantiate(STRIKE))
    bc.player.statuses.add(PlayerStatus.ENTANGLED, 1)
    assert not env.action_masks()[HAND_SLOT_BASE]


def test_obs_relic_counter_negative_clamped():
    """负计数器（如 ANCIENT_TEA_SET counter=-2 场景预设）钳 0——
    观测 Box 下界为 0，不能越界。"""
    from sts.env import _R_COUNTER

    env = StsBattleEnv(relics=[RelicId.ANCIENT_TEA_SET])
    obs, _ = env.reset(seed=8)
    env.bc.relics.counters[RelicId.ANCIENT_TEA_SET] = -2
    obs = env._get_obs()
    assert obs[O_RELIC + _R_COUNTER + RelicId.ANCIENT_TEA_SET.value] == 0
    assert env.observation_space.contains(obs)


def test_obs_negative_status_encoded():
    """负状态层数真实编码（Lagavulin 虹吸灵魂 -1 力量/敏捷；不钳 0，
    Box 下界放开到 -CAP_STATUS）。"""
    from sts.combat.types import PlayerStatus
    from sts.env import O_PSTAT, PLAYER_STATUS_ORDER

    env = StsBattleEnv(encounter="lagavulin")
    obs, _ = env.reset(seed=1001)
    bc = env.bc
    # 直接构造负层数（引擎路径是怪打虹吸灵魂，这里单元级验证编码）
    bc.player.statuses.add(PlayerStatus.STRENGTH, -1)
    bc.player.statuses.add(PlayerStatus.DEXTERITY, -1)
    obs = env._get_obs()
    k_str = PLAYER_STATUS_ORDER.index(PlayerStatus.STRENGTH)
    k_dex = PLAYER_STATUS_ORDER.index(PlayerStatus.DEXTERITY)
    assert obs[O_PSTAT + k_str] == -1
    assert obs[O_PSTAT + k_dex] == -1
    assert env.observation_space.contains(obs)


# ---- 批次 5b：药水动作段 ----


def test_mask_and_step_potion_self():
    """非 targeting 药水：j=0 动作合法，使用后槽清空、效果生效。"""
    from sts.content.potions import STRENGTH_POTION
    from sts.env import POTION_BASE
    from sts.combat.types import PlayerStatus

    env = StsBattleEnv(potions=[STRENGTH_POTION])
    env.reset(seed=0)
    assert env.action_masks()[POTION_BASE + 0]  # 槽 0 自身用法
    obs, r, term, trunc, info = env.step(POTION_BASE + 0)
    assert env.bc.player.potions[0] is None
    assert env.bc.player.statuses.get(PlayerStatus.STRENGTH) == 2
    # 药水观测段：占用位清零
    from sts.env import O_POTION, _P_OCC
    assert obs[O_POTION + _P_OCC] == 0


def test_mask_potion_targeting_requires_target():
    """targeting 药水（火焰药水）：双怪遭遇下 j=0 非法、显式目标合法；
    使用后对指定怪造成伤害。"""
    from sts.content.potions import FIRE_POTION
    from sts.env import POTION_BASE

    env = StsBattleEnv(encounter="louses", potions=[FIRE_POTION])
    env.reset(seed=2)
    bc = env.bc
    mask = env.action_masks()
    assert not mask[POTION_BASE + 0]  # 双怪：无自动指向
    assert mask[POTION_BASE + 1] and mask[POTION_BASE + 2]  # 两只虱都可指向
    m0_hp = bc.monsters.monsters[0].hp
    env.step(POTION_BASE + 1)  # 目标槽 0
    assert bc.monsters.monsters[0].hp < m0_hp  # 20 点火焰伤害


def test_mask_potion_auto_target_single_enemy():
    """targeting 药水 + 单怪：j=0（自动指向）合法。"""
    from sts.content.potions import FIRE_POTION
    from sts.env import POTION_BASE

    env = StsBattleEnv(potions=[FIRE_POTION])
    env.reset(seed=0)
    assert env.action_masks()[POTION_BASE + 0]


def test_mask_potion_auto_only_rejected():
    """auto_only（瓶中精灵）不可手动使用：动作段全非法。"""
    from sts.content.potions import FAIRY_POTION
    from sts.env import POTION_BASE, POTION_STANCE_BASE, SELECT_BASE

    env = StsBattleEnv(potions=[FAIRY_POTION])
    env.reset(seed=0)
    mask = env.action_masks()
    assert not mask[POTION_BASE : POTION_BASE + 6].any()
    assert not mask[POTION_STANCE_BASE : POTION_STANCE_BASE + 10].any()


def test_mask_potion_escape_only_boss():
    """escape_only（烟雾弹）在 Boss 遭遇禁用；普通遭遇可用。"""
    from sts.combat import relics as relics_mod
    from sts.content.potions import SMOKE_BOMB
    from sts.env import POTION_BASE

    env = StsBattleEnv(potions=[SMOKE_BOMB])
    env.reset(seed=0)
    assert env.action_masks()[POTION_BASE + 0]  # 普通遭遇可用
    relics_mod.BOSS_ENCOUNTERS.add("cultist")  # 原地加：battle/env/relics 三引用同集合
    try:
        env2 = StsBattleEnv(potions=[SMOKE_BOMB])
        env2.reset(seed=0)
        assert not env2.action_masks()[POTION_BASE + 0]
    finally:
        relics_mod.BOSS_ENCOUNTERS.discard("cultist")


def test_step_potion_stance_choice():
    """姿态药水：选择段动作合法，choice 生效进姿态观测段。"""
    from sts.content.potions import STANCE_POTION
    from sts.combat.types import Stance
    from sts.env import O_STANCE, POTION_STANCE_BASE, STANCE_ORDER

    env = StsBattleEnv(character="watcher", potions=[STANCE_POTION])
    env.reset(seed=0)
    mask = env.action_masks()
    assert mask[POTION_STANCE_BASE + 0] and mask[POTION_STANCE_BASE + 1]
    obs, *_ = env.step(POTION_STANCE_BASE + 0)  # c=0 → wrath
    assert env.bc.player.stance == Stance.WRATH
    assert obs[O_STANCE + STANCE_ORDER.index(Stance.WRATH)] == 1


# ---- 批次 5b：CARD_SELECT 自回归 ----


def _open_select(env, cands, pick_count=1, can_pick_zero=False, can_pick_any_number=False):
    """在 env.bc 上挂起一个选卡（记录提交结果），返回 chosen 日志列表。"""
    bc = env.bc
    log: list = []

    def on_choose(bc2, chosen):
        log.extend(chosen)

    bc.open_card_select(
        list(cands), on_choose, pick_count=pick_count, can_pick_zero=can_pick_zero,
        can_pick_any_number=can_pick_any_number,
    )
    return log


def test_card_select_autoregressive_flow():
    """SELECT×n → CONFIRM 提交；窗口按词表位稳定排序；选中态可见。"""
    from sts.env import (
        N_SELECT_WINDOW, O_MODE, O_PRESENT, O_PRESENT_FEAT, O_PRESENT_SEL,
        INPUT_STATE_ORDER, POTION_BASE, SELECT_BASE, SELECT_CONFIRM,
        _PS_OCC, _PS_UPGRADED,
    )
    from sts.combat.types import InputState

    env = StsBattleEnv()
    env.reset(seed=1)
    bc = env.bc
    strike, bash, wound = (bc.cards.instantiate(c) for c in (STRIKE, BASH, WOUND))
    log = _open_select(env, [bash, strike, wound])  # 乱序给入
    assert bc.input_state == InputState.CARD_SELECT

    mask = env.action_masks()
    # 挂起态：普通动作段全关（END_TURN 也不合法——不在玩家出牌阶段）
    assert not mask[ACTION_END_TURN]
    assert not mask[HAND_SLOT_BASE : SELECT_BASE].any()
    # 必选 1：CONFIRM 在选中前不合法
    assert not mask[SELECT_CONFIRM]
    # 窗口 = 词表位升序：WOUND(0) < STRIKE(116) < BASH(120)
    assert mask[SELECT_BASE + 0] and mask[SELECT_BASE + 1] and mask[SELECT_BASE + 2]
    assert not mask[SELECT_BASE + 3 : SELECT_BASE + N_SELECT_WINDOW].any()

    obs = env._get_obs()
    assert obs[O_MODE + INPUT_STATE_ORDER.index(InputState.CARD_SELECT)] == 1
    # 展示窗口槽 0 = WOUND 的词表位
    from sts.vocab import card_vocab_index
    assert obs[O_PRESENT + 0 * 736 + card_vocab_index(WOUND)] == 1
    assert obs[O_PRESENT + 1 * 736 + card_vocab_index(STRIKE)] == 1
    assert obs[O_PRESENT_FEAT + _PS_OCC] == 1
    assert obs[O_PRESENT_SEL + 0] == 0  # 未选

    env.step(SELECT_BASE + 2)  # 选 BASH（窗口位 2）
    obs = env._get_obs()
    assert obs[O_PRESENT_SEL + 2] == 1
    mask = env.action_masks()
    assert mask[SELECT_CONFIRM]
    assert not mask[SELECT_BASE + 0] and not mask[SELECT_BASE + 1]  # 容量 1 已满
    assert mask[SELECT_BASE + 2]  # 已选槽可再选（取消）

    env.step(SELECT_CONFIRM)
    assert log == [bash]
    assert bc.input_state == InputState.PLAYER_NORMAL  # 提交后恢复


def test_card_select_multi_pick_and_any_number():
    """多选（pick_count=2）与任意张（can_pick_any_number）。"""
    from sts.env import SELECT_BASE, SELECT_CONFIRM

    env = StsBattleEnv()
    env.reset(seed=2)
    bc = env.bc
    insts = [bc.cards.instantiate(STRIKE) for _ in range(4)]
    log = _open_select(env, insts, pick_count=2)
    env.step(SELECT_BASE + 0)
    env.step(SELECT_BASE + 2)
    mask = env.action_masks()
    assert not mask[SELECT_BASE + 1] and not mask[SELECT_BASE + 3]  # 容量已满
    assert mask[SELECT_CONFIRM]
    env.step(SELECT_CONFIRM)
    assert log == [insts[0], insts[2]]  # 选卡先后序

    # can_pick_any_number：超过 pick_count 也允许
    log2 = _open_select(env, insts, pick_count=1, can_pick_any_number=True)
    env.step(SELECT_BASE + 0)
    env.step(SELECT_BASE + 1)
    env.step(SELECT_BASE + 2)
    assert env.action_masks()[SELECT_CONFIRM]
    env.step(SELECT_CONFIRM)
    assert log2 == insts[:3]


def test_card_select_can_pick_zero():
    """can_pick_zero：空选择 CONFIRM 合法（如 Well-Laid Plans 可不保留）。"""
    from sts.env import SELECT_CONFIRM

    env = StsBattleEnv()
    env.reset(seed=3)
    bc = env.bc
    # 双候选（单候选+必选会被引擎直执，不挂起）
    log = _open_select(
        env, [bc.cards.instantiate(STRIKE), bc.cards.instantiate(BASH)], can_pick_zero=True
    )
    mask = env.action_masks()
    assert mask[SELECT_CONFIRM]  # 空选合法
    env.step(SELECT_CONFIRM)
    assert log == []


def test_card_select_candidate_order_invariance():
    """§4.3 候选顺序不变式：同一构成、不同内部顺序的候选列表，
    呈现的观测逐位一致（窗口稳定排序防堆序泄露）。"""
    env = StsBattleEnv()
    env.reset(seed=4)
    bc = env.bc
    cards = [bc.cards.instantiate(c) for c in (STRIKE, BASH, WOUND, CLASH)]
    _open_select(env, cards)
    obs1 = env._get_obs().copy()
    # 同一组候选、乱序重新打开（新 CardSelectInfo 身份 → 重建窗口）
    _open_select(env, [cards[3], cards[0], cards[2], cards[1]])
    obs2 = env._get_obs()
    assert np.array_equal(obs1, obs2)


def test_card_select_window_truncation():
    """候选超 10 张：窗口截前 10（词表位序），CONFIRM 仍可提交（近似）。"""
    from sts.env import N_SELECT_WINDOW, SELECT_BASE, SELECT_CONFIRM

    env = StsBattleEnv()
    env.reset(seed=5)
    bc = env.bc
    insts = [bc.cards.instantiate(STRIKE) for _ in range(12)]
    log = _open_select(env, insts, pick_count=1)
    mask = env.action_masks()
    assert mask[SELECT_BASE + 0]
    assert not mask[SELECT_BASE + N_SELECT_WINDOW]  # 第 11 个候选被截断
    env.step(SELECT_BASE + 0)
    env.step(SELECT_CONFIRM)
    assert log == [insts[0]]


def test_card_select_during_end_turn_retain():
    """集成：Well-Laid Plans 回合末保留选卡——END_TURN 步直接挂起进
    CARD_SELECT，选卡提交后战斗继续（挂起态跨 step 的真实路径）。"""
    from sts.combat.types import InputState
    from sts.env import INPUT_STATE_ORDER, O_MODE, SELECT_BASE, SELECT_CONFIRM

    env = StsBattleEnv()
    env.reset(seed=6)
    bc = env.bc
    bc.player.special["wlp"] = 1  # Well-Laid Plans：回合末选 1 张保留
    n_hand = len(bc.cards.hand)
    prev_ids = {c.unique_id for c in bc.cards.hand}
    obs, *_ = env.step(ACTION_END_TURN)
    assert bc.input_state == InputState.CARD_SELECT
    assert obs[O_MODE + INPUT_STATE_ORDER.index(InputState.CARD_SELECT)] == 1
    kept_id = env._select_window[0].unique_id  # 窗口位 0（词表位最小）的实例
    env.step(SELECT_BASE + 0)
    obs, *_ = env.step(SELECT_CONFIRM)
    # 提交后回合继续推进（敌方回合 → 新玩家回合），回到玩家阶段；
    # 保留牌（limbo 瞬态暂存后）回到新手牌，其余旧手牌全部弃置
    assert bc.input_state == InputState.PLAYER_NORMAL
    new_ids = {c.unique_id for c in bc.cards.hand}
    assert prev_ids & new_ids == {kept_id}


# ---- 批次 5b：Scry 动作段 ----


def test_scry_flow():
    """open_scry 挂起 → 观测按堆顶序展示 → keep k 提交 → 弃置其余。"""
    from sts.combat.types import InputState
    from sts.env import (
        INPUT_STATE_ORDER, O_MODE, O_PRESENT, SCRY_BASE, SCRY_KEEP_MAX,
    )

    env = StsBattleEnv()
    env.reset(seed=7)
    bc = env.bc
    n_draw = len(bc.cards.draw_pile)
    top3 = bc.cards.draw_pile[-3:][::-1]  # 引擎口径：[0]=堆顶
    bc.open_scry(3)
    assert bc.input_state == InputState.SCRY

    mask = env.action_masks()
    assert not mask[ACTION_END_TURN]
    for k in range(4):
        assert mask[SCRY_BASE + k]
    assert not mask[SCRY_BASE + 4]  # 只有 3 张：keep 3 封顶

    obs = env._get_obs()
    assert obs[O_MODE + INPUT_STATE_ORDER.index(InputState.SCRY)] == 1
    for i, inst in enumerate(top3):
        assert obs[O_PRESENT + i * 736 + card_vocab_index(inst.card)] == 1

    env.step(SCRY_BASE + 1)  # 保留堆顶 1 张，弃置 2 张
    assert bc.input_state == InputState.PLAYER_NORMAL
    assert len(bc.cards.draw_pile) == n_draw - 2
    assert len(bc.cards.discard_pile) == 2


def test_scry_keep_max_caps():
    """检视张数超 SCRY_KEEP_MAX（内容上限 5+金眼 2=7，此为保险）：保留
    选项钳在窗口内。"""
    from sts.env import SCRY_BASE, SCRY_KEEP_MAX

    env = StsBattleEnv()
    env.reset(seed=8)
    bc = env.bc
    # 补牌到抽牌堆 ≥ 8 张再检视 8（构造超界场景）
    for _ in range(4):
        bc.cards.draw_pile.append(bc.cards.instantiate(STRIKE))
    bc.open_scry(8)
    mask = env.action_masks()
    assert mask[SCRY_BASE + SCRY_KEEP_MAX]  # 保留上限 = 窗口末位（动作 119）
    assert SCRY_BASE + SCRY_KEEP_MAX == N_ACTIONS - 1  # 段尾即动作空间末位


# ---- 批次 5b：信息泄露审计扩展 ----


def test_info_leak_audit_suspended_states():
    """§4.3 审计（挂起态版）：CARD_SELECT / SCRY 挂起期间，乱序底层堆
    + 烧 RNG 流，观测逐位一致（候选/检视窗口是独立快照，不随堆序变）。"""
    shuffler = random.Random(1234)
    for seed in (0, 5):
        env = StsBattleEnv()
        env.reset(seed=seed)
        bc = env.bc
        # CARD_SELECT 挂起
        cands = [bc.cards.instantiate(c) for c in (STRIKE, BASH, WOUND)]
        _open_select(env, cands)
        obs_a = env._get_obs().copy()
        shuffler.shuffle(bc.cards.draw_pile)
        for _ in range(3):
            bc.rngs.misc.int_inclusive(0, 2**20)
        assert np.array_equal(obs_a, env._get_obs())
        # 恢复：选 1 提交
        from sts.env import SCRY_BASE, SELECT_BASE, SELECT_CONFIRM
        env.step(SELECT_BASE + 0)
        env.step(SELECT_CONFIRM)
        # SCRY 挂起
        bc.open_scry(2)
        obs_a = env._get_obs().copy()
        shuffler.shuffle(bc.cards.draw_pile)
        for _ in range(3):
            bc.rngs.misc.int_inclusive(0, 2**20)
        assert np.array_equal(obs_a, env._get_obs())
        env.step(SCRY_BASE + 0)  # 全弃，回到玩家阶段

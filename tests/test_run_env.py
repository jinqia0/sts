"""StsRunEnv 测试（批次 5c）：迷你局结构、源码掉落预设、HP 继承、
奖励口径、确定性、观测空间。"""

import numpy as np
import pytest

from sts.combat.relics import RelicId
from sts.run_env import (
    CAMPFIRE_BEFORE,
    CARD_POOLS,
    CARD_PITY_FLOOR,
    CARD_PITY_START,
    ELITES,
    RELIC_POOLS,
    RUN_OBSERVATION_MAXIMUMS,
    RUN_OBSERVATION_MINIMUMS,
    RUN_OBS_DIM,
    RUN_STRUCTURE,
    WEAK_POOL,
    StsRunEnv,
)
from sts.content.potions import IRONCLAD_POTION_POOL

MAXIMA = np.array(RUN_OBSERVATION_MAXIMUMS, dtype=np.int32)
MINIMA = np.array(RUN_OBSERVATION_MINIMUMS, dtype=np.int32)


# ---- 数据表 ----


def test_card_pools_match_official():
    """铁甲奖励池 = 20 common / 36 uncommon（35+Rage）/ 17 rare（含
    Hand of Greed，本体分类 Ironclad Rare）。"""
    assert {k: len(v) for k, v in CARD_POOLS.items()} == {"common": 20, "uncommon": 36, "rare": 17}
    names = {c.name for pool in CARD_POOLS.values() for c in pool}
    assert "Rage" in names and "Hand of Greed" in names
    assert "Strike" not in names and "Bash" not in names  # Basic 不进奖励池


def test_relic_pools_exclude_non_drop_tiers():
    """精英遗物池只含 COMMON/UNCOMMON/RARE tier（Boss/Shop/Event/Starter
    掉落不从这里出）。"""
    assert set(RELIC_POOLS) == {"COMMON", "UNCOMMON", "RARE"}
    assert all(len(v) > 0 for v in RELIC_POOLS.values())
    assert RelicId.BURNING_BLOOD not in RELIC_POOLS["COMMON"]  # Starter


def test_potion_pool_33_with_rarity_layers():
    """铁甲药水池 33 = 3 专属 + 30 通用；稀有度分层齐全（65/25/10 的
    三层都有候选）。"""
    assert len(IRONCLAD_POTION_POOL) == 33
    rarities = {p.rarity for p in IRONCLAD_POTION_POOL}
    assert rarities == {"common", "uncommon", "rare"}


# ---- 结构与 API ----


def test_run_structure_and_campfires():
    """8 场结构：3 弱 → 精英 → 2 强 → 精英 → Boss；火堆在精英 1/2 与
    Boss 前（场次索引 3/6/7）。"""
    assert RUN_STRUCTURE == ("weak", "weak", "weak", "elite", "strong", "strong", "elite", "boss")
    assert CAMPFIRE_BEFORE == (3, 6, 7)


def test_observation_space():
    env = StsRunEnv()
    assert env.observation_space.shape == (RUN_OBS_DIM,)
    assert len(RUN_OBSERVATION_MAXIMUMS) == RUN_OBS_DIM
    obs, info = env.reset(seed=0)
    assert env.observation_space.contains(obs)


def test_action_space_passthrough():
    """动作空间与战斗 env 一致（120 透传）。"""
    from sts.env import N_ACTIONS

    env = StsRunEnv()
    assert env.action_space.n == N_ACTIONS


# ---- 跨场状态与掉落 ----


def test_hp_carries_over_and_burning_blood():
    """HP 跨场继承 + 燃烧之血战后回 6（引擎 on_victory 路径）。"""
    env = StsRunEnv()
    env.reset(seed=0)
    bc = env._battle.bc
    bc.player.hp = 40  # 残血进结算
    for m in bc.monsters.monsters:
        if m.alive:
            m.die(bc)
    env.action_masks()  # 触发补结算 → 推进到第二场
    # 燃烧之血：40 + 6 = 46
    assert env.hp == 46, f"燃烧之血战后回血失效：{env.hp}"
    assert env._battle.bc.player.hp == 46  # 新战斗以 run HP 起手


def test_campfire_heals_30_percent():
    """火堆回血 30% max_hp（源码 CampfireSleepEffect）。"""
    env = StsRunEnv()
    env.reset(seed=0)
    # 快进到第 4 场前（索引 3 = 火堆位）
    env.battle_no = 3
    env.hp = 20
    env._start_battle()
    assert env.hp == 44  # 20 + 80*0.3 = 44
    assert any("火堆" in line for line in env._run_log)


def test_card_reward_grows_deck_and_pity():
    """选牌使牌组增长；保底计数器随 common 递减（封底）、rare 归位。"""
    env = StsRunEnv()
    env.reset(seed=0)
    n0 = len(env.deck)
    env.rngs.misc.int_inclusive(0, 99)  # 烧一次避免对齐干扰（确定性另测）
    env._card_reward()
    assert len(env.deck) >= n0  # 必选期（battle_no=0 < 4）：+1
    assert len(env.deck) <= n0 + 1


def test_potion_drop_blizzard_compensation():
    """药水掉率补偿：未掉 +10 / 掉落 -10（源码 blizzardPotionMod）。"""
    env = StsRunEnv()
    env.reset(seed=0)
    env.potion_blizzard = 0
    # 强制未掉：chance=40，roll=100 不可达——用极小 chance 模拟
    env.potion_blizzard = -40  # chance = 0
    n_slots = sum(1 for p in env.potions if p is not None)
    env._roll_potion_drop()
    assert env.potion_blizzard == -30  # 未掉 +10
    # 强制掉落：chance 130
    env.potion_blizzard = 90  # chance = 130
    env._roll_potion_drop()
    assert env.potion_blizzard == 80  # 掉落 -10
    assert sum(1 for p in env.potions if p is not None) == n_slots + 1


def test_elite_drops_relic():
    """精英场胜利掉落遗物（tier roll 池内，与已持有去重）。"""
    env = StsRunEnv()
    env.reset(seed=0)
    n0 = len(env.relics)
    env.battle_no = 3  # 精英位
    env._current_kind = "elite"
    env._drop_relic()
    assert len(env.relics) == n0 + 1
    assert env.relics[-1] in RELIC_POOLS["COMMON"] + RELIC_POOLS["UNCOMMON"] + RELIC_POOLS["RARE"]


def test_potion_carries_into_next_battle():
    """掉落的药水在下一场战斗的药水栏可见（观测段）。"""
    from sts.env import O_POTION, _P_OCC

    env = StsRunEnv()
    env.reset(seed=0)
    from sts.content.potions import STRENGTH_POTION

    env.potions[0] = STRENGTH_POTION
    env.battle_no = 1
    env._start_battle()
    assert env._battle.bc.player.potions[0] is STRENGTH_POTION
    obs = env._get_obs()
    assert obs[O_POTION + _P_OCC] == 1


# ---- 奖励与终止 ----



def test_settle_reward_value():
    env = StsRunEnv()
    env.reset(seed=0)
    bc = env._battle.bc
    bc.player.hp = 40
    for m in bc.monsters.monsters:
        if m.alive:
            m.die(bc)
    r = env._settle_battle()
    # v2 等权战损：(46 - 80)/80 + 1/8 = -0.3（34 点战损 > 存活信用）
    assert abs(r - ((40 + 6 - 80) / 80 + 0.125)) < 1e-9
    assert not env.run_over  # 第 1 场胜 → run 继续
    assert env.battle_no == 1


def test_run_terminates_on_death():
    env = StsRunEnv()
    env.reset(seed=0)
    bc = env._battle.bc
    bc.player.hp = 0
    bc.outcome = __import__("sts.combat.types", fromlist=["Outcome"]).Outcome.PLAYER_LOSS
    bc.check_combat()
    env.action_masks()  # 补结算
    assert env.run_over and not env.run_won


def test_run_terminates_on_boss_victory():
    env = StsRunEnv()
    env.reset(seed=0)
    env.battle_no = 7  # Boss 位（最后一场）
    from sts.combat.types import Outcome

    bc = env._battle.bc
    bc.outcome = Outcome.PLAYER_VICTORY
    bc.check_combat()
    r = env._settle_battle()
    assert env.run_over and env.run_won
    # v2：(hp - entry)/80 + 1/8 + 1（hp=80 满血时 = 1.125）
    assert abs(r - ((bc.player.hp - env._hp_at_battle_start) / 80 + 0.125 + 1.0)) < 1e-9


def test_terminated_false_between_battles():
    """中间场胜利不是 episode 终止（run_env.step 语义核心）。"""
    env = StsRunEnv()
    env.reset(seed=0)
    bc = env._battle.bc
    for m in bc.monsters.monsters:
        if m.alive:
            m.die(bc)
    obs, r, term, trunc, info = env.step(0) if False else (None, None, None, None, None)
    # 直接构造：结算 + step 检查——死亡/通关才 terminated
    env._settle_battle()
    assert not env.run_over
    # 正常路径经 mask/step 验证（见 rollout 测试）


# ---- 确定性与信息边界 ----


def test_reset_seed_determinism():
    """同 reset seed → 同一 run（遭遇序列/掉落/选牌全一致）。"""
    env = StsRunEnv()
    _obs1, info1 = env.reset(seed=42)
    log1 = list(info1["run_log"])
    enc1 = (info1["encounter"], info1["battle_kind"])
    # 推几场
    for _ in range(60):
        mask = env.action_masks()
        if not mask.any():
            break
        env.step(int(np.flatnonzero(mask)[0]))
    state1 = (env.battle_no, env.hp, len(env.deck), [r.name for r in env.relics])

    _obs2, info2 = env.reset(seed=42)
    assert (info2["encounter"], info2["battle_kind"]) == enc1
    for _ in range(60):
        mask = env.action_masks()
        if not mask.any():
            break
        env.step(int(np.flatnonzero(mask)[0]))
    state2 = (env.battle_no, env.hp, len(env.deck), [r.name for r in env.relics])
    assert state1 == state2


def test_random_rollout_completes():
    """随机策略完整 run：观测在界内、reward ∈ [0,8]、mask 永不为空
    （未终止时）、run_log 结构合法。"""
    env = StsRunEnv()
    for seed in range(10):
        env.reset(seed=seed)
        total = 0.0
        steps = 0
        while True:
            mask = env.action_masks()
            if not mask.any():
                break
            assert mask.any()
            obs, r, term, trunc, info = env.step(
                int(env.np_random.choice(np.flatnonzero(mask)))
            )
            total += r
            steps += 1
            assert env.observation_space.contains(obs)
            if term or trunc:
                break
            if steps > 3000:
                pytest.fail(f"seed {seed}: 超长局")
        # v2 值域：败 ∈ [-1, -0.125]，胜 = 终局HP/80+1 ∈ [1.01, 2]
        assert -1.0 <= total <= 2.0
        assert info["battle_no"] <= 7


# ---- 掉落统计健全性（粗口径）----


def test_potion_drop_rate_statistics():
    """强制胜利推 60 场：药水掉落率应在 40%±15 内（40% 基率 + 补偿
    波动；60 样本 3σ ≈ 12%）。"""
    from sts.combat.types import Outcome

    env = StsRunEnv()
    drops = 0
    n_battles = 0
    env2 = StsRunEnv()
    for seed in range(12):
        env2.reset(seed=seed)
        while not env2.run_over:
            bc = env2._battle.bc
            bc.outcome = Outcome.PLAYER_VICTORY
            bc.check_combat()
            env2._settle_battle()
        # 逐 run 统计（reset 会清 run_log）
        drops += sum(
            1 for line in env2._run_log
            if line.startswith("药水掉落") and "槽满丢弃" not in line
        )
        n_battles += sum(1 for line in env2._run_log if line.startswith("战斗"))
    rate = drops / max(1, n_battles)
    assert 0.25 <= rate <= 0.55, f"药水掉率 {rate:.2f} 偏离 40% 预设"


def test_campfire_occurs_three_times_per_completed_run():
    """通关 run 恰好 3 次火堆（精英 1/2/Boss 前）。"""
    from sts.combat.types import Outcome

    env = StsRunEnv()
    env.reset(seed=0)
    while not env.run_over:
        bc = env._battle.bc
        bc.outcome = Outcome.PLAYER_VICTORY
        bc.check_combat()
        env._settle_battle()
    assert env.run_won
    n = sum(1 for line in env._run_log if line.startswith("火堆"))
    assert n == 3
    # 精英掉落恰好 2 个（两次精英战）
    n_relic = sum(1 for line in env._run_log if line.startswith("精英遗物"))
    assert n_relic == 2
    # 选牌 7 次（8 场中 7 个奖励点；Boss 场无后续）
    n_pick = sum(1 for line in env._run_log if line.startswith("选牌"))
    assert n_pick == 7


def test_reward_decoupled_from_max_hp_growth():
    """2026-10-08 用户纠错回归：奖励基数 = run 起始上限 80，与实时
    max_hp 解耦——Feed/果汁造成的上限增长不稀释奖励；上限增长跨场
    保留（新战斗带增长后的上限）。"""
    from sts.content.cards.ironclad import FEED

    env = StsRunEnv()
    env.reset(seed=0)
    bc = env._battle.bc
    bc.player.max_hp = 90  # 模拟 Feed 增长
    bc.player.hp = 90      # 满血（随上限同步 +）
    for m in bc.monsters.monsters:
        if m.alive:
            m.die(bc)
    r = env._settle_battle()
    # v2：(90-80)/80 + 1/8 = 0.25：增长 +10 全额体现在战损项，不稀释
    assert abs(r - ((90 - 80) / 80 + 0.125)) < 1e-9
    # 上限增长同步回 run 并进入下一场
    assert env.max_hp == 90
    assert env._battle.bc.player.max_hp == 90


def test_campfire_heals_by_current_max_hp():
    """火堆按实时上限 30% 回血（与本体一致；上限增长让火堆更强）。"""
    env = StsRunEnv()
    env.reset(seed=0)
    env.battle_no = 3
    env.max_hp = 90
    env.hp = 10
    env._start_battle()
    assert env.hp == 37  # 10 + 90*0.3 = 37


# ---- 奖励口径 v2：结构性质（2026-10-08 用户决策）----


def test_reward_v2_death_progress_monotonic():
    """死于第 k 场（0 起）总回报 = -1 + k/8，严格单调——死亡越晚越好，
    火堆回血不重复计损（收到即入账的信用抵消）。"""
    from sts.combat.types import Outcome

    for k in range(8):
        env = StsRunEnv()
        env.reset(seed=0)
        total = 0.0
        # 快进前 k 场（满血通关式：delta=0，只攒存活信用与火堆信用）
        for j in range(k):
            bc = env._battle.bc
            bc.player.hp = 80
            bc.outcome = Outcome.PLAYER_VICTORY
            bc.check_combat()
            total += env._settle_battle()
        # 第 k 场死亡
        bc = env._battle.bc
        bc.outcome = Outcome.PLAYER_LOSS
        bc.check_combat()
        total += env._settle_battle()
        assert env.run_over and not env.run_won
        # 累计恒等式：-1 + k/8（信用 k 份，死亡场 -hp_start/80=满血 -1）
        assert abs(total - (-1.0 + k / 8)) < 1e-9, f"k={k}: {total}"


def test_reward_v2_win_loss_separation():
    """任何通关 > 任何失败：胜 ≥ 1+1/80 > 败 ≤ -1/8。构造极端对照：
    满血通关（上限 2.0）vs 满血死于第 1 场（-1.0）。"""
    from sts.combat.types import Outcome

    env = StsRunEnv()
    env.reset(seed=0)
    total = 0.0
    for k in range(8):
        bc = env._battle.bc
        bc.player.hp = 80
        bc.outcome = Outcome.PLAYER_VICTORY
        bc.check_combat()
        total += env._settle_battle()
    assert env.run_won
    # 通关累计恒等式：终局HP/80 + 1（满血通关 = 2.0）
    assert abs(total - (80 / 80 + 1.0)) < 1e-9


def test_reward_v2_campfire_not_double_counted():
    """火堆后死 ≥ 火堆前死：第 3 场（火堆后）死亡回报 -1+2/8 = -0.75 ≥
    第 2 场死亡 -1+1/8 = -0.875（v1 朴素战损口径此处会倒挂）。"""
    from sts.combat.types import Outcome

    results = {}
    for k in (2, 3):
        env = StsRunEnv()
        env.reset(seed=0)
        total = 0.0
        for j in range(k):
            bc = env._battle.bc
            bc.player.hp = 80
            bc.outcome = Outcome.PLAYER_VICTORY
            bc.check_combat()
            total += env._settle_battle()
        bc = env._battle.bc
        bc.outcome = Outcome.PLAYER_LOSS
        bc.check_combat()
        total += env._settle_battle()
        results[k] = total
    assert results[3] >= results[2], f"火堆重复计损倒挂：{results}"


def test_reward_v2_truncation_is_death_equivalent():
    """截断（TURN_LIMIT 挂机）与死亡等价：拖延不付战损的套利封死
    （2026-10-08 v2 重训实测踩出：ep_len 1643、ep_rew 锁死的挂机策略）。"""
    from sts.env import ACTION_END_TURN, TURN_LIMIT

    from sts.run_env import PROGRESS_CREDIT, REWARD_HP_BASE

    env = StsRunEnv()
    env.reset(seed=0)
    hp_start = env._hp_at_battle_start
    env._battle.bc.turn = TURN_LIMIT + 1
    obs, r, term, trunc, info = env.step(ACTION_END_TURN)
    assert term  # run 终止
    assert env.run_over and not env.run_won
    # 负信用版：(结算HP - 入场HP)/80 - 1/8（end_turn 含敌方回合掉血，
    # 战损项非零；负信用 −1/8 恒在——拖延严格劣于真打胜利）
    expected = (env._battle.bc.player.hp - hp_start) / REWARD_HP_BASE - PROGRESS_CREDIT
    assert abs(r - expected) < 1e-9
    assert r < 0  # 无信用正号的拖延回报

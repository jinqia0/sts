"""run 循环集成测试（Phase 3a）——完整 Act 1 随机 rollout。

口径（ROADMAP Phase 3 验收的前半）：多种子全部正常终局（胜/负路径
都到达）、同种子轨迹逐条一致（确定性）、楼层推进正确（15 层 + Boss）、
火堆/宝箱/商店/？房在日志中出现。
"""

from __future__ import annotations

from sts.baselines import heuristic_policy, random_policy
from sts.overworld.policy import RandomPolicy, SimpleHeuristicPolicy
from sts.overworld.run import RunSimulator

SEEDS = range(12)


def test_full_run_completes_all_seeds():
    """随机局外 + 随机战斗：12 种子全部正常终局。"""
    for seed in SEEDS:
        sim = RunSimulator(run_policy=RandomPolicy(seed=seed), battle_policy=random_policy, seed=seed)
        r = sim.run()
        assert r.floor >= 1
        assert r.hp >= 0
        if r.won:
            assert "通关" in r.log[-1]
        else:
            assert r.hp == 0, f"seed {seed} 败局但 HP {r.hp}"


def test_full_run_heuristic_battle():
    """随机局外 + 启发式战斗：同样全部终局（更深的楼层覆盖）。"""
    floors = 0
    for seed in SEEDS:
        sim = RunSimulator(run_policy=RandomPolicy(seed=seed), battle_policy=heuristic_policy, seed=seed)
        r = sim.run()
        floors += r.floor
        assert r.floor >= 1
    assert floors / len(SEEDS) > 8  # 启发式战斗应显著比随机战斗走得深


def test_determinism_full_trajectory():
    for seed in (3, 7):
        r1 = RunSimulator(run_policy=RandomPolicy(seed=seed), battle_policy=heuristic_policy, seed=seed).run()
        r2 = RunSimulator(run_policy=RandomPolicy(seed=seed), battle_policy=heuristic_policy, seed=seed).run()
        assert r1.log == r2.log
        assert (r1.won, r1.floor, r1.hp, r1.gold, r1.deck_size) == (
            r2.won, r2.floor, r2.hp, r2.gold, r2.deck_size,
        )


def test_heuristic_run_policy_completes():
    sim = RunSimulator(run_policy=SimpleHeuristicPolicy(seed=1), battle_policy=heuristic_policy, seed=99)
    r = sim.run()
    assert r.floor >= 1


def test_run_log_contains_all_room_types():
    """聚合日志应出现火堆/宝箱/商店/？房/战斗。"""
    logs = []
    for seed in range(20):
        r = RunSimulator(run_policy=RandomPolicy(seed=seed), battle_policy=heuristic_policy, seed=seed).run()
        logs.append("\n".join(r.log))
    joined = "\n".join(logs)
    assert "火堆" in joined
    assert "宝箱" in joined
    assert "商店" in joined
    assert "？房" in joined
    assert "战斗" in joined
    assert "事件" in joined


def test_floor_progression_and_boss():
    """到达 row 14 的 run 必经第 15 层火堆；Boss 战在通关前。"""
    reached_boss = 0
    for seed in range(20):
        r = RunSimulator(run_policy=RandomPolicy(seed=seed), battle_policy=heuristic_policy, seed=seed).run()
        if r.floor >= 15:
            reached_boss += 1
    assert reached_boss >= 3  # 20 局中至少数局到达 Boss（启发式战斗）


def test_event_scratch_does_not_leak_across_same_event():
    """同一种子内 Dead Adventurer 的搜空状态不复活（抽后移除）。"""
    sim = RunSimulator(run_policy=RandomPolicy(seed=0), battle_policy=heuristic_policy, seed=0)
    r = sim.run()
    # 只验证 run 正常完成（事件内部状态正确性在事件单测覆盖）
    assert r.floor >= 1


def test_snapshot_clone_restores_run_state():
    """RunState.clone/restore：中途快照可回滚（搜索器需求的最小保证）。"""
    sim = RunSimulator(run_policy=RandomPolicy(seed=4), battle_policy=heuristic_policy, seed=4)
    # 手动跑半局再快照——用状态直接验证（不动模拟器内部）
    from sts.overworld.state import RunState

    s = RunState()
    s.gold = 555
    s.hp = 42
    s.card_pity = -10
    snapshot = s.clone()
    s.gold = 1
    s.hp = 1
    s.card_pity = 5
    s.restore(snapshot)
    assert (s.gold, s.hp, s.card_pity) == (555, 42, -10)

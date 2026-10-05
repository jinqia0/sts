"""场景配置测试：注册表、reward 覆盖、与旧入口的等价性。"""

import numpy as np
import pytest

from sts.env import StsBattleEnv, WEAK_POOL
from sts.scenarios import REWARD_DAMAGE, REWARD_SPARSE_PM1, SCENARIOS, ScenarioSpec, get_scenario


def test_registry_and_get():
    assert "weak" in SCENARIOS
    assert get_scenario("weak") is SCENARIOS["weak"]
    assert get_scenario(None) is SCENARIOS["weak"]  # 默认回落
    spec = ScenarioSpec(name="tmp", pool=("cultist",), reward=REWARD_SPARSE_PM1)
    assert get_scenario(spec) is spec  # 直接传 spec
    with pytest.raises(ValueError):
        get_scenario("不存在")


def test_scenario_equivalent_to_random_encounter():
    """scenario="weak" 与旧入口 encounter="random" 同种子轨迹一致（回退兼容）。"""

    def traj(env):
        obs, _ = env.reset(seed=33)
        seq = [obs.copy()]
        for _ in range(6):
            mask = env.action_masks()
            a = int(np.flatnonzero(mask)[0])
            obs, *_ = env.step(a)
            seq.append(obs.copy())
        return seq

    a, b = traj(StsBattleEnv(scenario="weak")), traj(StsBattleEnv(encounter="random"))
    assert all((x == y).all() for x, y in zip(a, b))


def test_single_encounter_still_works():
    env = StsBattleEnv(encounter="louses")
    for s in (1, 2):
        _obs, info = env.reset(seed=s)
        assert info["encounter"] == "louses"
        assert env.pool == ("louses",)


def test_default_constructor_is_cultist():
    """旧默认行为保留：无参构造 = cultist。"""
    env = StsBattleEnv()
    _obs, info = env.reset(seed=1)
    assert info["encounter"] == "cultist"


def test_reward_mode_from_scenario_and_override():
    """奖励口径：场景配置生效 + 构造参数可覆盖（A/B 实验入口）。"""

    def final_reward(env, hp_setup: int) -> float:
        env.reset(seed=1)
        env.bc.player.hp = hp_setup
        for m in env.bc.monsters.monsters:  # 池内最多 2 怪，全部压到 1 HP
            m.hp = 1
        from sts.content.cards import STRIKE

        env.bc.cards.hand.clear()
        env.bc.cards.hand.extend(env.bc.cards.instantiate(STRIKE) for _ in range(5))
        # 动态选第一个非零合法动作（单怪=槽动作自动指向，
        # 多怪=槽0 的目标组合），逐个击杀直到终局
        import numpy as np

        for _ in range(6):
            legal = [a for a in np.flatnonzero(env.action_masks()) if a != 0]
            if not legal:
                raise AssertionError("无合法攻击动作")
            _obs, r, term, _tr, _info = env.step(int(legal[0]))
            if term:
                return r
        raise AssertionError("未能终结战斗")

    # 场景默认：damage 口径
    assert abs(final_reward(StsBattleEnv(scenario="weak"), 40) - 0.5) < 1e-9
    # 覆盖：sparse_pm1 口径（同局面一律 +1）
    assert final_reward(StsBattleEnv(scenario="weak", reward=REWARD_SPARSE_PM1), 40) == 1.0
    # 单遭遇入口默认 damage
    assert abs(final_reward(StsBattleEnv(encounter="cultist"), 40) - 0.5) < 1e-9


def test_weak_pool_matches_env_constant():
    assert SCENARIOS["weak"].pool == WEAK_POOL

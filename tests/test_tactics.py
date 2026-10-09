"""微场景战术评测（EXP-15）测试：构造正确性、判定逻辑、不变式。

- 构造：手牌/意图/血量/能量按 spec 覆写，抽牌堆 = 初始牌组补集
- 不变式：多种子观测逐位一致（§4.3 审计在脚本局面同样成立）
- 判定：合成动作序列喂 check_scenario，通过/不通过边界逐条覆盖
- 启发式 sanity：规则版 baseline 应通过全部 4 个微场景
  （场景可被规则解出 = 判定标准不是不可能任务）
"""

from __future__ import annotations

import numpy as np
import pytest

from sts.baselines import heuristic_policy, random_policy
from sts.env import StsBattleEnv
from sts.tactics import (
    BASH,
    DEFEND,
    STRIKE,
    TACTICS_SCENARIOS,
    build_scenario,
    check_scenario,
    evaluate_policy,
    rollout,
)


# ---- 构造正确性 ----

@pytest.mark.parametrize("key", list(TACTICS_SCENARIOS))
def test_build_scenario_state(key):
    spec = TACTICS_SCENARIOS[key]
    env = build_scenario(spec, seed=0)
    bc = env.bc
    assert [i.card.name for i in bc.cards.hand] == list(spec.hand)
    assert bc.player.energy == 3
    assert bc.player.hp == spec.player_hp
    m = bc.monsters.monsters[0]
    assert m.move_history[0].name == spec.intent.name
    assert m.move_history[0].kind == spec.intent.kind
    if spec.monster_hp is not None:
        assert m.hp == spec.monster_hp
    # 抽牌堆 = 初始 10 张牌组的补集（构成，不查顺序）
    deck_names = sorted([i.card.name for i in bc.cards.hand] + [i.card.name for i in bc.cards.draw_pile])
    starter = sorted([STRIKE] * 5 + [DEFEND] * 4 + [BASH])
    assert deck_names == starter


def test_obs_invariant_across_seeds():
    """§4.3 审计不变式：抽牌堆洗牌顺序对观测不可见 → 多种子逐位一致。"""
    spec = TACTICS_SCENARIOS["attack_priority"]
    obs = [build_scenario(spec, seed=s)._get_obs() for s in range(3)]
    assert np.array_equal(obs[0], obs[1])
    assert np.array_equal(obs[0], obs[2])


def test_intent_value_in_obs():
    """自定 base_damage 的意图值进观测（规则 3/4 的决策输入）。"""
    env = build_scenario(TACTICS_SCENARIOS["block_then_attack"], seed=0)
    m = env.bc.monsters.monsters[0]
    shown = env.bc.calculate_monster_damage(m, 5)
    assert shown == 5  # 无力量/虚弱修饰，原值进观测


# ---- 判定逻辑（合成序列） ----

def test_check_attack_priority():
    spec = TACTICS_SCENARIOS["attack_priority"]
    assert check_scenario(spec, [STRIKE, STRIKE, "END"], False)[0]
    assert check_scenario(spec, [STRIKE, STRIKE, DEFEND, "END"], False)[0]  # 尾巴防御不影响规则 1
    assert not check_scenario(spec, [DEFEND, STRIKE, STRIKE, "END"], False)[0]  # 防御抢先
    assert not check_scenario(spec, [STRIKE, DEFEND, "END"], False)[0]  # 只打了 1 张打击
    assert not check_scenario(spec, [DEFEND, DEFEND, DEFEND, "END"], False)[0]


def test_check_bash_first():
    spec = TACTICS_SCENARIOS["bash_first"]
    assert check_scenario(spec, [BASH, STRIKE, "END"], False)[0]
    assert not check_scenario(spec, [STRIKE, BASH, "END"], False)[0]  # 打击没吃到易伤
    assert not check_scenario(spec, [BASH, DEFEND, "END"], False)[0]  # 打击没跟上
    assert not check_scenario(spec, [STRIKE, DEFEND, "END"], False)[0]  # 没出痛击


def test_check_block_then_attack():
    spec = TACTICS_SCENARIOS["block_then_attack"]
    assert check_scenario(spec, [DEFEND, STRIKE, STRIKE, "END"], False)[0]
    assert check_scenario(spec, [STRIKE, DEFEND, STRIKE, "END"], False)[0]  # 防先后均可
    assert not check_scenario(spec, [DEFEND, DEFEND, STRIKE, "END"], False)[0]  # 过度防御
    assert not check_scenario(spec, [STRIKE, STRIKE, "END"], False)[0]  # 漏防 5 点
    assert not check_scenario(spec, [DEFEND, "END"], False)[0]  # 剩余能量没攻击


def test_check_lethal_over_defend():
    spec = TACTICS_SCENARIOS["lethal_over_defend"]
    assert check_scenario(spec, [STRIKE, STRIKE, STRIKE], True)[0]  # 击杀即终局，无 END
    assert not check_scenario(spec, [DEFEND, STRIKE, STRIKE, "END"], False)[0]  # 防御浪费时间
    assert not check_scenario(spec, [STRIKE, STRIKE, "END"], False)[0]  # 没杀掉还漏防


# ---- 策略侧 ----

def test_heuristic_passes_all():
    """规则版 baseline 通过全部微场景：判定标准可被规则解出。"""
    for spec in TACTICS_SCENARIOS.values():
        rep = evaluate_policy(heuristic_policy, spec, range(5))
        assert rep["pass"] == rep["total"], (
            f"{spec.key}: heuristic 未通过—— {[r['seq'] for r in rep['results'] if not r['ok']]}"
        )


def test_random_policy_smoke():
    """随机策略 rollout 不出非法动作（mask 一致性冒烟）。"""
    spec = TACTICS_SCENARIOS["bash_first"]
    for s in range(5):
        env = build_scenario(spec, s)
        seq, _dead = rollout(env, random_policy)
        assert seq, "至少应有一步动作"
        assert all(n.split("@")[0] in (STRIKE, DEFEND, BASH, "END") for n in seq)


def test_scenario4_lethal_endstate():
    """全打击路径确实 18 伤斩杀：引擎结算与 spec 一致。"""
    env = build_scenario(TACTICS_SCENARIOS["lethal_over_defend"], seed=0)
    bc = env.bc

    def all_in_policy(env: StsBattleEnv) -> int:
        # 贪心出打击：找手牌第一个合法的 Strike 槽，否则 END
        mask = env.action_masks()
        for i, inst in enumerate(env.bc.cards.hand):
            if inst.card.name == STRIKE and mask[1 + i]:
                return 1 + i
        return 0

    seq, dead = rollout(env, all_in_policy)
    assert seq == [STRIKE, STRIKE, STRIKE]
    assert dead and bc.won

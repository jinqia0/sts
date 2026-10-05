"""场景配置：场景 = 数据而非代码分支（2026-10-05 决策）。

一个训练场景 = 一个 ScenarioSpec 配置对象：怪池、奖励口径、（未来）
牌组分布、回合上限等全部是参数。新场景 = 往 SCENARIOS 注册一个新
条目，旧场景永远可用，一份代码承载所有实验——避免「每场景一个
分支」的代码分叉维护。

奖励口径（reward 字段，2026-10-05 定为 EXP-01 的核心演进）：
    "damage"    终局 = 剩余HP/max_hp（胜），败 0——战损为唯一目标
    "sparse_pm1" 胜 +1 / 负 -1 / 进行中 0（EXP-01 首版的对照口径，
                保留供奖励对比实验，见 DESIGN.md §5）

新增场景的完整流程（三步）：
    1. 这里定义 ScenarioSpec 并注册进 SCENARIOS
    2. （如需新怪/新卡）sts/content/ 加内容定义 + 测试
    3. uv run python scripts/train.py --scenario <名> --out <模型名>

实验记录：docs/EXPERIMENTS.md 按 EXP-NN 追加，场景名写进设定表。
"""

from __future__ import annotations

from dataclasses import dataclass

# 奖励口径常量（env.py 按此分支）
REWARD_DAMAGE = "damage"
REWARD_SPARSE_PM1 = "sparse_pm1"


@dataclass(frozen=True)
class ScenarioSpec:
    """一个训练场景的全部配置。字段只增不改义（旧 checkpoint 对应的
    场景配置动过语义 = 复现失效，改语义请起新场景名）。"""

    name: str
    pool: tuple[str, ...]  # 遭遇池（每局均匀抽一种）
    reward: str = REWARD_DAMAGE  # 见模块注释
    description: str = ""
    species_shuffle: bool = False  # 消融：种类 ID 每局乱序（EXP-03）
    # 未来扩展（现在留默认值，加字段不破坏旧配置）：
    # deck: 卡组分布采样（Phase 2 卡组泛化）


WEAK = ScenarioSpec(
    name="weak",
    pool=("cultist", "jaw_worm", "louses", "slimes_s", "fungi_beast"),
    reward=REWARD_DAMAGE,
    description="弱怪池单场：基础牌组，战损口径（EXP-01/02）",
)

WEAK_SHUFFLED = ScenarioSpec(
    name="weak_shuffled",
    pool=WEAK.pool,
    reward=REWARD_DAMAGE,
    description="EXP-03 消融：同 weak，但种类 one-hot 每局乱序（切断种类信息）",
    species_shuffle=True,
)


SCENARIOS: dict[str, ScenarioSpec] = {
    "weak": WEAK,
    "weak_shuffled": WEAK_SHUFFLED,
}


def get_scenario(key: str | ScenarioSpec | None) -> ScenarioSpec:
    """按名（或直接传 spec）取场景配置；None 回落默认 weak。"""
    if isinstance(key, ScenarioSpec):
        return key
    if key is None:
        return WEAK
    try:
        return SCENARIOS[key]
    except KeyError:
        raise ValueError(f"未知场景：{key}（可选：{sorted(SCENARIOS)}）") from None

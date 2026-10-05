"""内部 RNG：按用途分流（DESIGN.md §3）。

单流 RNG 的问题：任何一处抽样次数的变化（加怪、改洗牌逻辑）都会
平移同种子下后续所有随机数——固定种子的回归测试对无关改动脆弱。
分流后各用途独立演化，互不影响。这是从 sts_lightspeed 借鉴的唯一
RNG 设计（它为种子对齐服务，我们为测试稳健性服务，刻意不做调用
顺序对齐）。

流划分（对齐用途，非对齐调用序）：
    shuffle     洗牌（抽牌堆、弃牌堆洗回）
    monster_hp  敌人 HP 抽样
    ai          敌人意图抽样（Cultist 确定性出招，暂不消耗）
    misc        其他（药水、随机卡等，预留）
"""

from numpy.random import SeedSequence, default_rng


class Rng:
    def __init__(self, seed: int | SeedSequence | None = None):
        self.gen = default_rng(seed)

    def int_inclusive(self, lo: int, hi: int) -> int:
        """[lo, hi] 闭区间均匀整数。"""
        return int(self.gen.integers(lo, hi + 1))

    def shuffle(self, seq: list) -> None:
        """原地 Fisher-Yates 洗牌。"""
        self.gen.shuffle(seq)


class RngStreams:
    """一条主种子派生出互相独立的分流。"""

    def __init__(self, seed: int | None = None):
        children = SeedSequence(seed).spawn(4)
        self.shuffle = Rng(children[0])
        self.monster_hp = Rng(children[1])
        self.ai = Rng(children[2])
        self.misc = Rng(children[3])

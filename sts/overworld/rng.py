"""局外 RNG 分流（Phase 3a，2026-10-08）。

对齐本体 generateSeeds 的流划分（AbstractDungeon.java:378-392）用途，
非对齐调用序（DESIGN.md §3：分布级保真，放弃种子/轨迹对齐）：

    map        地图生成（本体 mapRng 每幕 new Random(seed + actNum)）
    card       卡牌奖励稀有度与选卡（本体 cardRng）
    relic      遗物 tier roll 与选遗物（本体 relicRng）
    potion     药水稀有度与选药水（本体 potionRng）
    event      ？房型 roll 与事件选择（本体 eventRng）
    treasure   宝箱箱型与内容（本体 treasureRng）
    merchant   商店价格浮动与打折卡（本体 merchantRng）
    misc       事件内部随机（本体 miscRng 每层重建——本项目整幕一条流，
               分布等价）
    monster    遭遇池 roll 与 Boss 洗牌（本体 monsterRng）

战斗种子不从这些流消费——由 run 循环独立派生（照 run_env.py 的
隔离模式），保证改掉落逻辑不破坏战斗轨迹的固定种子回归。
"""

from numpy.random import SeedSequence

from sts.rng import Rng

_OVERWORLD_STREAMS = (
    "map",
    "card",
    "relic",
    "potion",
    "event",
    "treasure",
    "merchant",
    "misc",
    "monster",
)


class OverworldRngStreams:
    """一条局外主种子派生出的九条独立分流。"""

    def __init__(self, seed: int | None = None):
        children = SeedSequence(seed).spawn(len(_OVERWORLD_STREAMS))
        for i, name in enumerate(_OVERWORLD_STREAMS):
            setattr(self, name, Rng(children[i]))

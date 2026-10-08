"""地图生成性质测试（Phase 3a）——docs/MAP_GENERATION.md §5 清单。

性质（忠实移植的本体规则）：
- 结构：15×7 网格；边只连下一行、列差 ≤1
- 交叉守卫：无边相交
- 祖先间距：任一节点的任意两个父节点的公共祖先 ≥3 行之上
  （否则违反 MIN_ANCESTOR_GAP 规则）
- 行规则：row 0 全战斗 / row 8 全宝箱 / row 14 全火堆；精英仅 row 5-13；
  火堆仅 row 5-12
- 父/兄弟规则：火堆/宝箱/商店/精英不与父同型；五类不与兄弟同型
- row 0 去重：无两个 row-0 节点指向同一 row-1 节点
- 确定性：同种子逐节点一致
"""

from __future__ import annotations

from sts.overworld.map_gen import (
    MAP_HEIGHT,
    MAP_WIDTH,
    RoomKind,
    _common_ancestor,
    generate_map,
)
from sts.rng import Rng

SEEDS = range(25)


def _maps():
    return [(seed, generate_map(Rng(seed))) for seed in SEEDS]


def test_structure_edges_next_row_adjacent_column():
    for _seed, m in _maps():
        for y in range(MAP_HEIGHT):
            for x in range(MAP_WIDTH):
                for dx, dy in m.rows[y][x].edges:
                    assert dy == y + 1, f"({x},{y}) 边指向非下一行 {dy}"
                    assert abs(dx - x) <= 1, f"({x},{y}) 边列差 >1 → {dx}"


def test_no_edge_crossing():
    """交叉守卫：同层相邻两节点 a<b 的出边不交叉（a 的边目标 ≤ b 的边目标）。"""
    for _seed, m in _maps():
        for y in range(MAP_HEIGHT - 1):
            for x in range(MAP_WIDTH - 1):
                left, right = m.rows[y][x], m.rows[y][x + 1]
                if left.edges and right.edges:
                    assert max(left.edges)[0] <= min(right.edges)[0], (
                        f"({x},{y}) 与 ({x + 1},{y}) 出边交叉"
                    )


def test_ancestor_gap_statistical():
    """祖先间距为软性质：交叉守卫在祖先规则之后可覆盖其结果（本体行为），
    且 _common_ancestor 含 x/y 混比怪癖（低行规则虚设）——聚合违反率
    应显著低于"无规则"基线（无规则时几乎所有同父对都会近距离汇合），
    但非零。200 图聚合违反率实测 ~13%（相对 25.5% 的 x/y 修正前）。
    """
    viol = total = 0
    for seed in range(200):
        m = generate_map(Rng(seed))
        for y in range(1, MAP_HEIGHT):
            for x in range(MAP_WIDTH):
                parents = sorted(set(m.rows[y][x].parents))
                if len(parents) < 2:
                    continue
                for i in range(len(parents)):
                    for j in range(i + 1, len(parents)):
                        anc = _common_ancestor(m.rows, parents[i], parents[j], 5)
                        total += 1
                        if anc is not None and y - anc[1] < 3:
                            viol += 1
    rate = viol / total
    assert 0.02 < rate < 0.30, f"祖先间距违反率异常：{rate:.3f}"


_PREASSIGNED_ROWS = (0, 8, 14)  # 预钉行绕过一切规则（assignRowAsRoomType）


def test_row_assignments():
    for _seed, m in _maps():
        for n in m.rows[0]:
            if m.connected(n):
                assert n.room == RoomKind.MONSTER
        for n in m.rows[8]:
            assert n.room == RoomKind.TREASURE
        for n in m.rows[MAP_HEIGHT - 1]:
            if n.parents:
                assert n.room == RoomKind.REST
        # 规则只约束分配行（预钉行除外）
        for y, row in enumerate(m.rows):
            if y in _PREASSIGNED_ROWS:
                continue
            for n in row:
                if not m.connected(n):
                    continue
                if n.room == RoomKind.ELITE:
                    assert 5 <= y <= 13, f"精英出现在 row {y}"
                if n.room == RoomKind.REST:
                    assert 5 <= y <= 12, f"火堆出现在 row {y}"


def test_parent_sibling_rules():
    """父规则为硬性质（分配时父行已定）；兄弟规则为软性质——兜底路径
    （池耗尽返回 null → lastMinuteNodeChecker 强制战斗房）可产生兄弟同型
    战斗房，实测违反率 ~1%（51/5193）。"""
    _parent_kinds = (RoomKind.REST, RoomKind.TREASURE, RoomKind.SHOP, RoomKind.ELITE)
    _sibling_kinds = (RoomKind.REST, RoomKind.MONSTER, RoomKind.EVENT, RoomKind.ELITE, RoomKind.SHOP)
    sibling_viol = sibling_total = 0
    for _seed, m in _maps():
        for y in range(MAP_HEIGHT):
            if y in _PREASSIGNED_ROWS:
                continue
            for x in range(MAP_WIDTH):
                n = m.rows[y][x]
                if n.room is None or not m.connected(n):
                    continue
                for px, py in set(n.parents):
                    assert not (m.rows[py][px].room == n.room and n.room in _parent_kinds), (
                        f"({x},{y}) 与父 ({px},{py}) 同型 {n.room}"
                    )
                for px, py in set(n.parents):
                    for cx, cy in m.rows[py][px].edges:
                        if (cx, cy) == (x, y):
                            continue
                        sibling_total += 1
                        if m.rows[cy][cx].room == n.room and n.room in _sibling_kinds:
                            sibling_viol += 1
    assert sibling_viol / sibling_total < 0.03, f"兄弟同型违反率异常：{sibling_viol}/{sibling_total}"


def test_row0_no_duplicate_targets():
    for _seed, m in _maps():
        seen: set[tuple[int, int]] = set()
        for n in m.rows[0]:
            for e in n.edges:
                assert e not in seen, f"row 0 重复目标 {e}"
                seen.add(e)


def test_room_statistics_sane():
    """战斗房占多数；六类齐全（多图聚合）。"""
    from collections import Counter

    kinds: Counter = Counter()
    for _seed, m in _maps():
        for row in m.rows:
            for n in row:
                if n.room and m.connected(n) and n.has_edges():
                    kinds[n.room] += 1
    total = sum(kinds.values())
    assert kinds[RoomKind.MONSTER] / total > 0.4
    assert kinds[RoomKind.EVENT] / total > 0.15  # 22% 池比例（过剩丢弃后略降）
    assert kinds[RoomKind.REST] / total > 0.08
    assert kinds[RoomKind.ELITE] / total > 0.03
    assert kinds[RoomKind.SHOP] / total > 0.015


def test_determinism_same_seed():
    for seed in SEEDS:
        m1, m2 = generate_map(Rng(seed)), generate_map(Rng(seed))
        for y in range(MAP_HEIGHT):
            for x in range(MAP_WIDTH):
                n1, n2 = m1.rows[y][x], m2.rows[y][x]
                assert n1.edges == n2.edges
                assert n1.room == n2.room


def test_start_nodes_exist():
    for _seed, m in _maps():
        starts = m.start_nodes()
        assert len(starts) >= 1
        assert len(starts) <= 6  # 6 条路径、路径 2 起点不同

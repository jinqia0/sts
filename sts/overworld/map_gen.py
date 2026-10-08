"""地图生成（Phase 3a，2026-10-08）——忠实移植本体算法。

施工依据：docs/MAP_GENERATION.md（源码梳理定稿，2026-10-07）。
源文件：sts_game_data/decompiled/com/megacrit/cardcrawl/map/
    MapGenerator.java（路径生成）/ RoomTypeAssigner.java（房间分配）/
    AbstractDungeon.generateMap（参数与房间池比例，java:490-520）

已声明的与本体偏差（MAP_GENERATION.md §5）：
- row 14 → (3,16) 的 Boss 假边（纯渲染）不移植
- Endless/模组分支（Uncertain Future / Elite Swarm / MimicInfestation）不移植
- 本体怪癖（房间池过剩丢弃、count 口径扣 row 13、row-0 去重死起点、
  addParent 不去重）全部照抄

A0：精英比例 0.08（A1+ ×1.6 不实现）。
"""

from __future__ import annotations

import enum
import logging
from dataclasses import dataclass, field

from sts.rng import Rng

logger = logging.getLogger(__name__)

MAP_HEIGHT = 15
MAP_WIDTH = 7
PATH_DENSITY = 6

# 房间池比例（Exordium.java:92-96，四 Act 全同）
SHOP_ROOM_CHANCE = 0.05
REST_ROOM_CHANCE = 0.12
TREASURE_ROOM_CHANCE = 0.0
ELITE_ROOM_CHANCE = 0.08
EVENT_ROOM_CHANCE = 0.22

MIN_ANCESTOR_GAP = 3
MAX_ANCESTOR_GAP = 5


class RoomKind(enum.Enum):
    MONSTER = "monster"
    ELITE = "elite"
    REST = "rest"
    SHOP = "shop"
    TREASURE = "treasure"
    EVENT = "event"  # ？房（真事件房；？房内容 roll 在 event_roll.py）


@dataclass
class MapNode:
    x: int
    y: int
    edges: list[tuple[int, int]] = field(default_factory=list)  # (dstX, dstY)，按 dst 去重（本体 addEdge）
    parents: list[tuple[int, int]] = field(default_factory=list)  # 不去重（本体 addParent）
    room: RoomKind | None = None

    def has_edges(self) -> bool:
        return bool(self.edges)

    def add_edge(self, dst: tuple[int, int]) -> None:
        if dst not in self.edges:  # 本体按 compareTo（dstX,dstY）判等去重
            self.edges.append(dst)

    def add_parent(self, parent: tuple[int, int]) -> None:
        self.parents.append(parent)  # 本体不去重，保持原样

    def children(self) -> list[tuple[int, int]]:
        return list(self.edges)


class StsMap:
    """15×7 网格 + 房间类型。生成后视为只读（run 状态另记游标）。"""

    def __init__(self, rows: list[list[MapNode]]):
        self.rows = rows
        self.boss_room = RoomKind.MONSTER  # 第 16 层（占位语义，run 循环用遭遇名）
        self.boss_relic_room = True  # 第 17 层 Boss 宝箱（固定存在）

    def node(self, x: int, y: int) -> MapNode:
        return self.rows[y][x]

    def connected(self, node: MapNode) -> bool:
        return node.has_edges() or bool(node.parents)

    def start_nodes(self) -> list[MapNode]:
        """row 0 中有出边的节点（去重规则可能产生死起点，照抄本体）。"""
        return [n for n in self.rows[0] if n.has_edges()]

    def room_kind(self, x: int, y: int) -> RoomKind:
        return self.rows[y][x].room or RoomKind.MONSTER

    def ascii(self, show_rooms: bool = True) -> str:
        symbols = {
            RoomKind.MONSTER: "M",
            RoomKind.ELITE: "E",
            RoomKind.REST: "R",
            RoomKind.SHOP: "$",
            RoomKind.TREASURE: "T",
            RoomKind.EVENT: "?",
            None: " ",
        }
        lines = []
        for y in range(MAP_HEIGHT - 1, -1, -1):
            # 边行
            edge_cells = []
            for n in self.rows[y]:
                left = mid = right = " "
                for dx, dy in n.edges:
                    if dx < n.x:
                        left = "\\"
                    elif dx == n.x:
                        mid = "|"
                    else:
                        right = "/"
                edge_cells.append(left + mid + right)
            lines.append(" " + "".join(edge_cells))
            # 节点行
            cells = []
            for n in self.rows[y]:
                sym = symbols[RoomKind.MONSTER if y == MAP_HEIGHT - 1 and n.room is None else n.room]
                if not self.connected(n):
                    sym = " "
                elif show_rooms:
                    sym = symbols[n.room]
                else:
                    sym = "."
                cells.append(f" {sym} ")
            lines.append(f"{y} " + "".join(cells))
        return "\n".join(lines)


def generate_map(rng: Rng) -> StsMap:
    """三阶段流水线：createNodes → createPaths → filterRedundant → 房间分配。"""
    rows = _create_nodes()
    _create_paths(rows, PATH_DENSITY, rng)
    _filter_redundant_edges_from_row(rows)
    _assign_rooms(rows, rng)
    return StsMap(rows)


# ---- 阶段① 路径生成（MapGenerator.java:58-207）----


def _create_nodes() -> list[list[MapNode]]:
    return [[MapNode(x, y) for x in range(MAP_WIDTH)] for y in range(MAP_HEIGHT)]


def _create_paths(rows: list[list[MapNode]], path_density: int, rng: Rng) -> None:
    first_start = -1
    for i in range(path_density):
        start = rng.int_inclusive(0, MAP_WIDTH - 1)
        if i == 0:
            first_start = start
        while start == first_start and i == 1:  # 路径 2 起点 ≠ 路径 1（本体 :67-69）
            start = rng.int_inclusive(0, MAP_WIDTH - 1)
        _walk_path(rows, (start, 0), rng)


def _walk_path(rows: list[list[MapNode]], node_pos: tuple[int, int], rng: Rng) -> None:
    """从 node_pos 逐行游走到 row 14（本体 _createPaths 递归的迭代等价）。"""
    x, y = node_pos
    while True:
        node = rows[y][x]
        if y + 1 >= MAP_HEIGHT:
            # row 14 → Boss 假边（渲染用）不移植（MAP_GENERATION.md §5）
            return
        row_end = MAP_WIDTH - 1
        if x == 0:
            lo, hi = 0, 1
        elif x == row_end:
            lo, hi = -1, 0
        else:
            lo, hi = -1, 1
        new_x = x + rng.int_inclusive(lo, hi)
        new_y = y + 1

        # 祖先规则：防分叉后 3 行内汇合（:156-187）
        candidate = rows[new_y][new_x]
        for parent_pos in list(candidate.parents):
            if parent_pos == (x, y):
                continue
            px, py = parent_pos
            ancestor = _common_ancestor(rows, (px, py), (x, y), MAX_ANCESTOR_GAP)
            if ancestor is None:
                continue
            ax, ay = ancestor
            ancestor_gap = new_y - ay
            if ancestor_gap < MIN_ANCESTOR_GAP:
                # dx 往远离该父节点方向推（含边界反弹）
                if candidate.x > x:
                    new_x = x + rng.int_inclusive(-1, 0)
                    if new_x < 0:
                        new_x = x
                elif candidate.x == x:
                    new_x = x + rng.int_inclusive(-1, 1)
                    if new_x > row_end:
                        new_x = x - 1
                    elif new_x < 0:
                        new_x = x + 1
                else:
                    new_x = x + rng.int_inclusive(0, 1)
                    if new_x > row_end:
                        new_x = x
                candidate = rows[new_y][new_x]
                continue
            # 3 ≤ gap < 5：无操作（本体 :186 continue）

        # 交叉守卫（:189-200）：getMaxEdge = dstX 最大者，getMinEdge = dstX 最小者
        if x != 0:
            left_node = rows[y][x - 1]
            if left_node.has_edges():
                right_edge_dst = max(left_node.edges)[0]
                if right_edge_dst > new_x:
                    new_x = right_edge_dst
        if x < row_end:
            right_node = rows[y][x + 1]
            if right_node.has_edges():
                left_edge_dst = min(right_node.edges)[0]
                if left_edge_dst < new_x:
                    new_x = left_edge_dst

        candidate = rows[new_y][new_x]
        node.add_edge((new_x, new_y))
        candidate.add_parent((x, y))
        x, y = new_x, new_y


def _common_ancestor(
    rows: list[list[MapNode]],
    node1: tuple[int, int],
    node2: tuple[int, int],
    max_depth: int,
) -> tuple[int, int] | None:
    """左节点逐层取最右父、右节点取最左父，向上至多 max_depth 行（:107-127）。

    本体怪癖照抄：Java :112 反编译为 ``node1.x < node2.y``（x 与 y 混比）——
    低行（y < x）时 l/r 分配翻转、两侧父链背向而行，公共祖先几乎必查空
    → 祖先规则在这些行形同虚设。按反编译原文照抄（分布级保真）。
    """
    if node1[0] < node2[1]:
        l_pos, r_pos = node1, node2
    else:
        l_pos, r_pos = node2, node1
    start_y = node1[1]
    for _current_y in range(start_y, max(-1, start_y - max_depth), -1):
        l_node, r_node = rows[l_pos[1]][l_pos[0]], rows[r_pos[1]][r_pos[0]]
        if not l_node.parents or not r_node.parents:
            return None
        l_pos = max(l_node.parents)  # 最右父 = x 最大
        r_pos = min(r_node.parents)  # 最左父 = x 最小
        if l_pos == r_pos:
            return l_pos
    return None


def _filter_redundant_edges_from_row(rows: list[list[MapNode]]) -> None:
    """row 0 跨节点去重：禁止两个 row-0 节点指向同一 row-1 节点（:26-44）。

    副作用照抄：某 row-0 节点可能失去全部出边 → 死起点。
    """
    seen: set[tuple[int, int]] = set()
    for node in rows[0]:
        if not node.has_edges():
            continue
        to_delete = [e for e in node.edges if e in seen]
        seen.update(node.edges)
        for e in to_delete:
            node.edges.remove(e)


# ---- 阶段②③④ 房间类型分配 ----


def _count_rooms(rows: list[list[MapNode]]) -> int:
    """count 口径（本体怪癖照抄）：连通节点、扣 row 13、含 row 0/8/14（:497-503）。

    本体 row 14 节点靠 Boss 假边算"有边"——本移植跳过假边（MAP_GENERATION.md §5），
    等价地按"有父节点"计入。
    """
    total = 0
    for row in rows:
        for n in row:
            if n.y == MAP_HEIGHT - 1:
                if n.parents:
                    total += 1
            elif n.y != MAP_HEIGHT - 2 and n.has_edges():
                total += 1
    return total


def _generate_room_list(count: int) -> list[RoomKind]:
    rooms: list[RoomKind] = []
    shops = round(count * SHOP_ROOM_CHANCE)
    rests = round(count * REST_ROOM_CHANCE)
    elites = round(count * ELITE_ROOM_CHANCE)  # A0（A1+ ×1.6 不实现）
    events = round(count * EVENT_ROOM_CHANCE)
    monsters = count - shops - rests - elites - events
    rooms += [RoomKind.SHOP] * shops
    rooms += [RoomKind.REST] * rests
    rooms += [RoomKind.ELITE] * elites
    rooms += [RoomKind.EVENT] * events
    rooms += [RoomKind.MONSTER] * monsters
    return rooms


_SIBLING_RULE_KINDS = (RoomKind.REST, RoomKind.MONSTER, RoomKind.EVENT, RoomKind.ELITE, RoomKind.SHOP)
_PARENT_RULE_KINDS = (RoomKind.REST, RoomKind.TREASURE, RoomKind.SHOP, RoomKind.ELITE)


def _rule_assignable_to_row(y: int, kind: RoomKind) -> bool:
    """精英禁 row ≤4；火堆禁 row ≤4 且禁 row ≥13（RoomTypeAssigner.java:80-87）。"""
    if y <= 4 and kind in (RoomKind.ELITE, RoomKind.REST):
        return False
    if y >= MAP_HEIGHT - 2 and kind == RoomKind.REST:
        return False
    return True


def _siblings(rows: list[list[MapNode]], parents: list[tuple[int, int]], self_pos: tuple[int, int]) -> list[MapNode]:
    out: list[MapNode] = []
    for px, py in parents:
        for child in rows[py][px].edges:
            if child != self_pos:
                out.append(rows[child[1]][child[0]])
    return out


def _rule_parent_matches(parents: list[tuple[int, int]], rows: list[list[MapNode]], kind: RoomKind) -> bool:
    if kind not in _PARENT_RULE_KINDS:
        return False
    for px, py in parents:
        if rows[py][px].room == kind:
            return True
    return False


def _rule_sibling_matches(siblings: list[MapNode], kind: RoomKind) -> bool:
    if kind not in _SIBLING_RULE_KINDS:
        return False
    return any(s.room == kind for s in siblings)


def _next_room_by_rules(rows: list[list[MapNode]], node: MapNode, room_list: list[RoomKind]) -> RoomKind | None:
    pos = (node.x, node.y)
    siblings = _siblings(rows, node.parents, pos)
    for kind in room_list:
        if not _rule_assignable_to_row(node.y, kind):
            continue
        if _rule_parent_matches(node.parents, rows, kind) or _rule_sibling_matches(siblings, kind):
            continue
        return kind
    return None


def _assign_rooms(rows: list[list[MapNode]], rng: Rng) -> None:
    # ② 房间池
    count = _count_rooms(rows)
    room_list = _generate_room_list(count)
    # ③ 预钉三行：row 14 全火堆 / row 0 全战斗 / row 8 全宝箱（:505-511）
    for n in rows[MAP_HEIGHT - 1]:
        n.room = RoomKind.REST
    for n in rows[0]:
        n.room = RoomKind.MONSTER
    for n in rows[8]:
        n.room = RoomKind.TREASURE
    # ④ distribute（:123-139）：nodeCount = 连通未分配（含 row 13！）；池补齐到 nodeCount、洗牌、
    # 逐节点取首个过规则的房间并移除；过剩丢弃（本体 WARNING 分支是常态——口径差异照抄）
    node_count = sum(1 for row in rows for n in row if n.has_edges() and n.room is None)
    while len(room_list) < node_count:
        room_list.append(RoomKind.MONSTER)
    rng.shuffle(room_list)
    for row in rows:
        for n in row:
            if not n.has_edges() or n.room is not None:
                continue
            kind = _next_room_by_rules(rows, n, room_list)
            if kind is not None:
                room_list.remove(kind)
                n.room = kind
    # 兜底：仍无房间的连通节点 → 战斗房（lastMinuteNodeChecker :103-111）
    for row in rows:
        for n in row:
            if n.has_edges() and n.room is None:
                n.room = RoomKind.MONSTER
    if len(room_list) > 0:
        logger.debug("房间池过剩丢弃 %d 件（本体口径怪癖，常态）", len(room_list))

# 地图生成算法（源码梳理，MAP_GENERATION.md）

基于本体反编译源码（sts_game_data/，V2.3.4 CFR 反编译）的完整梳理，**移植口径已定稿（2026-10-07）：忠实移植**——三阶段 + 全部规则 + 本体怪癖一并照抄，性质测试锁行为。本文档是 Phase 3 局外模拟器地图模块的施工依据。file:line 均指反编译源文件。

## 0. 总览：三阶段流水线

```
generateMap()                                    AbstractDungeon.java:490
 ├─ ① generateDungeon(15, 7, 6, mapRng)          骨架 + 6 条路径
 │    ├─ createNodes(15, 7)                      15×7 满网格（无空格概念）
 │    ├─ createPaths(×6)                         逐条随机上游走 + 三类约束
 │    └─ filterRedundantEdgesFromRow             第 0 行去重
 ├─ ② generateRoomTypes(roomList, count)         按比例造"房间池"
 ├─ ③ 预钉三行: row 14=火堆 / row 0=战斗 / row 8=宝箱
 └─ ④ distributeRoomsAcrossMap                   洗牌 + 规则约束分配 + 兜底
```

参数硬编码（`AbstractDungeon.java:492-494`）：**高 15、宽 7、路径密度 6**。RNG 为独立 `mapRng` 流——对齐本项目 RNG 分流设计（现有 shuffle/monster_hp/ai/misc 四流之外新增 map 流）。

楼层编号：row 0~14 = 第 1~15 层；第 16 层 Boss、第 17 层 Boss 宝箱（固定，网格外）；第 9 层 = row 8 = 必为宝箱。

## 1. 阶段①：路径生成（MapGenerator.java）

每条路径 = 从第 0 行随机起点出发、逐行向 row+1 游走的递归（`:129-207`）：

**起点**（`:58-73`）：6 条路径各自在 row 0 均匀抽 x∈[0,6]；唯一约束：**第 2 条路径起点 ≠ 第 1 条**（`while startingNode == firstStartingNode && i == 1`）。路径 3~6 可与路径 1 同起点。

**每步**：从 (x,y) 向 row y+1 走，候选 dx∈{−1,0,+1}（x=0 收缩为 {0,+1}，x=6 收缩为 {−1,0}），先均匀抽取，再依次过三道约束修正：

1. **祖先规则**（`:156-187`，防"分叉后 3 行内再汇合"）：对目标节点的每个既有父节点 p，找 p 与当前节点在 ≤5 行内的共同祖先（`getCommonAncestor` `:107-127`：左节点逐层取最右父、右节点取最左父，向上至多 5 行）。若汇合距离 `newY − ancestor.y < 3` → dx 往远离 p 的方向推（目标在右侧改向左、同列随机带边界反弹、目标在左侧改向右）；距离 ≥3 放行
2. **交叉守卫**（`:189-200`，防边相交）：左邻 (x−1,y) 已有出边时，其最右出边 dstX 不得超过 newEdgeX（超过则抬高 newEdgeX）；右邻同理（其最左出边不得低于 newEdgeX，否则压低）
3. 边确定后加入 `(x,y)→(newX,y+1)`，目标节点记 parent，从新节点递归，直到 row 14

**到达 row 14**（`:135-140`）：加一条到 (3,16) 的假边（isBoss=true）——**纯渲染用**，模拟器忽略。

**收尾去重**（`:26-44`）：只处理 row 0，跨节点累积已见 (dstX,dstY)，后见者删——**禁止两个 row-0 节点指向同一 row-1 节点**。副作用：row-0 节点可能失去全部出边 → 死起点（本体真有此行为，照抄）。

**去重语义**：`MapRoomNode.addEdge` 按目标去重（`:71-78`）；`addParent` **不去重**（`:145-147`）——重复父节点可能存在并影响后续 sibling/parent 规则匹配，保持原样。

## 2. 阶段②③④：房间类型分配

**房间池**（`generateRoomTypes`，`AbstractDungeon.java:538-576`；比例四 Act 全同，`Exordium.java:92-96`）：

| 类型 | 数量 | 说明 |
|---|---|---|
| 商店 | round(0.05·count) | |
| 火堆 | round(0.12·count) | |
| 宝箱 | 0 | 中途宝箱只来自预钉 row 8——每图第 9 层必开一箱 |
| 精英 | round(0.08·count) | A1+ ×1.6；A0 范围用 0.08 |
| 事件 | round(0.22·count) | |
| 战斗 | count − 其余（≈53%） | |

**count 口径怪癖**（`:497-503`）：分母 = 全部连通节点**扣 row 13**、**含即将预钉的 row 0/8/14**；而 `distributeRoomsAcrossMap` 的补齐目标 nodeCount = 连通未分配节点（含 row 13、不含已钉三行）。口径不一致 → 房间池通常**大于**可分配节点数 → 洗牌后**多余房间直接丢弃**（`:128-130` WARNING 分支是常态）。本体已知怪癖，照抄。

**预钉三行**（`:505-511`）：row 14 全火堆、row 0 全战斗、row 8 全宝箱。（Endless MimicInfestation 把 row 8 换精英——范围外不移植。）

**规则分配**（`RoomTypeAssigner.java:89-101`）：按行序遍历连通未分配节点，从洗牌池取**第一个通过全部规则的房间**（取走即移除）：

- **行规则**（`:80-87`）：精英禁 row ≤4；火堆禁 row ≤4 且禁 row ≥13
- **父规则**（`:70-78`）：父节点已是 {火堆, 宝箱, 商店, 精英} → 子禁同型
- **兄弟规则**（`:61-68`）：共享父节点的兄弟已是 {火堆, 战斗, 事件, 精英, 商店} 同型 → 禁（宝箱不在列）
- **row 0 旁路**（`:97-98`）：y==0 时规则失效——但 row 0 已预钉，实际死代码
- **兜底**（`:103-111`）：遍历后仍无房间的连通节点 → 强制战斗房（含池耗尽情形）

`passesDonutCheck`（`AbstractDungeon.java:587`）**无调用方**——死代码，不移植。

## 3. 网格外两层（规划器边界）

- **第 16 层 Boss**：不在网格，`DungeonMap.java:74` 在 `y==14` 房间完成后动态创建（节点 (-1,15)，MonsterRoomBoss）；Boss 由各 Act boss 池抽选（独立 RNG 流）
- **第 17 层 Boss 宝箱**：TreasureRoomBoss = boss 遗物三选一（BossRelicSelectScreen），之后进下一 Act（`ProceedButton.java:106,175`）
- 单 Act 训练范围：**终局 = 第 16 层 Boss 胜利**；第 17 层为终局后奖励决策，首版不做（多 Act 续跑时它是每 Act 末尾的第 7 个决策点）

## 4. 对规划器/V̂ 的直接含义

- "第 5 层前必有战斗、精英最早第 5 层、第 9 层必宝箱、第 15 层必火堆" → 浅层搜索的确定性骨架
- 无连续精英/火堆 + 兄弟不同型 → 路线分支合法组合被裁剪，搜索树天然更小
- `?` 房 = 池中 EventRoom（22%），内容生成走事件池流——对应 DESIGN.md §8.4 信息边界审计点
- V̂ 地图段编码（位置 one-hot ~105 维 + 剩余各行可达房间类型计数 ~90 维，DESIGN.md §8.6-1）恰好消费池比例 + 规则产生的可预期分布

## 5. 移植施工要点

- 纯逻辑约 200 行 Python（三阶段无图形依赖，MapEdge 视觉部分全弃）；无 RNG 调用次数对齐负担（分布级保真）
- RNG：`randRange(rng, min, max) = rng.random(max−min)+min`（`:266-272`）；洗牌对应 `Collections.shuffle(roomList, rng.random)`——均以 map 流 numpy 等价实现
- 性质测试清单：无交叉边、祖先间距 ≥3、行规则（精英 row≥5 / 火堆 5≤row≤12 / row 0 战斗 / row 8 宝箱 / row 14 火堆）、父/兄弟规则、房间类型统计对照（0.05/0.12/0.08/0.22 池比例）、row-0 去重与死起点行为、重复父节点存在性
- 与本体的已声明偏差：假边 (3,16) 渲染逻辑不移植；Endless/模组分支（Uncertain Future、Elite Swarm、MimicInfestation）不移植

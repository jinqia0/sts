# 路线图（ROADMAP.md）

状态标记：`[ ]` 未开始 / `[~]` 进行中 / `[x]` 完成。更新本文档以反映真实进度。
训练场景的完整记录（设定/配置/曲线/结论）见 `docs/EXPERIMENTS.md`。

## Phase 1：战斗模拟器 + 战斗策略

### 第 0 步：RL 练手（用户已完成前可跳过代码部分）
- [ ] 安装 uv、gymnasium、stable-baselines3、sb3-contrib
- [ ] 在 CartPole 或经典控制环境跑通一次 MaskablePPO 训练 + 评估，建立"训练循环/曲线/超参"的手感
- 验收：能看懂训练曲线，知道 learning_rate、n_steps 在哪调

### 第 1 步：最小战斗环境
- [x] 引擎骨架：~~CombatState~~ → **sts_lightspeed 架构级移植（2026-10-05）**：`BattleContext` 双端动作队列 + InputState 状态机 + 回合生命周期（详见 DESIGN.md §3 引擎架构小节）；伤害管线（力量→易伤→虚弱→脆弱，取整钳制）与回合末结算时机（易伤递减、Ritual skipFirst）保持不变
- [x] 内容：铁甲战士初始牌组 10 张（5 Strike / 4 Defend / 1 Bash）+ Cultist（咒语+仪式雪球，意图在敌方回合结束时生成）
- [x] RNG 分流：shuffle/monster_hp/ai/misc 四条独立流
- [x] Gymnasium 封装：`reset`/`step`/观测（691 维 + 每维上界表 `OBSERVATION_MAXIMUMS`）/action mask（扁平 Discrete(61)：END_TURN + 手牌槽 + 槽×5 目标位）；卡牌用稳定词表 multi-hot 计数（手牌顺序玩家可见，牌堆仅构成）
- [x] 信息泄露审计测试（DESIGN.md §4.3）：乱序三堆 + 烧 RNG 流，观测逐位一致
- [x] 双 baseline：随机策略 + 启发式（斩杀优先/集火残血/格挡补足）；EVAL_SEEDS=0..99 与训练种子（≥10_000）不相交
- [x] 内容扩展第一批：Act 1 怪 6 种（Cultist/Jaw Worm/Red & Green Louse/Acid & Spike Slime (S)/Fungi Beast，含 Curl Up/Spore Cloud 通用钩子与多敌人遭遇）+ 铁甲战士卡 14 张（顺劈/双斩/锁喉/燃烧/金属化/怒火/狂野打击等，含 Wound 状态卡）
- 已有人机 CLI：`uv run python -m sts.cli [--encounter cultist|jaw_worm|louses|slimes_s|fungi_beast] [--seed N]`；90 个 pytest 用例（队列架构、伤害管线、逐怪出招分段、逐卡数值、信息泄露审计、baseline 确定性）
- 验收：随机策略能在环境里跑完整场战斗并统计胜率；审计测试通过 ✅（当前数字：Cultist random 0.64 / heuristic 1.00；Jaw Worm 0.86 / 1.00；其余遭遇双 baseline 均 ≥1.00——怪偏弱，MaskablePPO 目标是全遭遇显著超 random、追平或超 heuristic）

### 第 2 步：MaskablePPO 跑通
- [x] 训练场景：`StsBattleEnv(encounter="random")`——基础牌组 vs 弱怪池随机单场遭遇（每局均匀抽一种，无跨场状态；2026-10-05 用户决策：从「连打 5 场」简化，怪间无配合、序列无策略含义，只增加学习难度）
- [x] **奖励 = 战损**（2026-10-05 用户决策）：终局剩余 HP/max_hp（胜），败 0，进行中 0；胜率退化为前提。此口径下 300k 步胜率过早饱和的问题消失，保血有持续梯度
- [x] 训练脚本：`scripts/train.py`（MaskablePPO，训练种子 ≥10_000，周期评估种子 70..99，总体 + 分遭遇双口径对照 random/heuristic）
- [x] 两个 baseline：随机策略、简单启发式（斩杀优先/集火残血/格挡补足），`sts/baselines.py`，评估种子 0..99
- [x] **结果（2026-10-05，模型 models/weak_pool_1m_hp76.zip）**：1M 步 MaskablePPO 平均剩余 HP **76.0**/80，超 random（62.0）+14、超 heuristic（75.5）+0.5；分遭遇 3 胜（louses 77.1 / slimes_s 78.9 / fungi 79.7）1 平 1 负（jaw_worm 68.9 vs 72.9，唯一需跨回合规划的怪，小 MLP + 无记忆快照观测的能力上限附近）。300k 版对照 74.6 存 weak_v2_300k.zip
- 验收：训练策略胜率显著超过两个 baseline ✅

### 第 3 步：扩内容 + 奖励实验
- [ ] 扩到 Act 1 主要卡池（~30 张起步，向 ~75 张推进）与主要敌池（普通怪→精英→Slime Boss/Guardian）
- [ ] 敌人意图系统（行动回合结束时生成，参考真实游戏的 move 表）
- [ ] 奖励对比实验：稀疏 ±1 vs HP shaping
- [ ] 多敌人战斗（最多 5 个槽位）
- 验收：训练策略对 Act 1 敌池多数敌人胜率 > 启发式 baseline

### 第 4 步：卡组泛化（为 Phase 2 铺路）
- [ ] 卡组可变长编码（multi-hot/计数）
- [ ] 卡组分布采样训练（模拟真实选牌过程的随机演化卡组）
- [ ] HP 比例进观测
- 验收：没见过的卡组上胜率不掉得离谱（泛化 sanity check）

## Phase 2：战斗 oracle
- [ ] oracle 接口：V(卡组, 敌人, 进场HP, 药水开关) → (E[战损], P[死))
- [ ] 实现：泛化战斗策略 + N 次 rollout 统计
- [ ] 人工校验：战损排序符合游戏直觉（如 Guardian 比 Louse 贵）
- [ ] 药水加入战斗动作空间
- 验收：oracle 战损统计与 CommunicationMod 真游戏统计分布接近

## Phase 3：局外层
- [ ] 纯启发式 + oracle 跑通完整 Act 1（选牌用启发式）
- [ ] MCTS/expectimax 规划器（战斗转移用多次 rollout 取期望，禁固定种子）
- [ ] 药水开关纳入规划
- [ ] （可选）选牌评估器学习组件
- 验收：完整 Act 1 通关率的 baseline 对比数字

## 可选支线
- 信息价值对照实验：训练一组"可见抽牌堆顺序"的 agent，量化透视的胜率增益（研究副产品）
- BC 预训练：CommunicationMod 录制轨迹 → BC → PPO 微调

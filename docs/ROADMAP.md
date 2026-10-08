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
- **战斗网页调试器（2026-10-07，stdlib http.server 零新依赖）**：`uv run python -m sts.webapp`——浏览器里自定义角色（4 职业，各自初始牌组/最大生命）/ 卡组（全词表 373 卡，可标记升级张数）/ 遗物（129）/ 药水（42）/ 怪物（注册遭遇 65 或 62+ 怪自由组队 ≤5 只），手动打完整场校验结算；手牌不可打原因、意图计算伤害、状态（含 just_applied）全可见，**信息边界对齐 DESIGN.md §4：抽牌堆仅构成可见（同名聚合 + 名称排序，顺序不可见）、选卡候选按名称排序展示（engine_idx 内部映射）**，弃牌/消耗堆按实际顺序可见，引擎异常以 traceback 原文回显页面。引擎零改动（自定义组怪=向 ENCOUNTERS 注册 custom_web 条目）；已知近似：职业最大生命构造后修正。测试 `tests/test_webapp.py` 13 例（含抽牌堆顺序泄露审计）
- 验收：随机策略能在环境里跑完整场战斗并统计胜率；审计测试通过 ✅（当前数字：Cultist random 0.64 / heuristic 1.00；Jaw Worm 0.86 / 1.00；其余遭遇双 baseline 均 ≥1.00——怪偏弱，MaskablePPO 目标是全遭遇显著超 random、追平或超 heuristic）

### 第 2 步：MaskablePPO 跑通
- [x] 训练场景：`StsBattleEnv(encounter="random")`——基础牌组 vs 弱怪池随机单场遭遇（每局均匀抽一种，无跨场状态；2026-10-05 用户决策：从「连打 5 场」简化，怪间无配合、序列无策略含义，只增加学习难度）
- [x] **奖励 = 战损**（2026-10-05 用户决策）：终局剩余 HP/max_hp（胜），败 0，进行中 0；胜率退化为前提。此口径下 300k 步胜率过早饱和的问题消失，保血有持续梯度
- [x] 训练脚本：`scripts/train.py`（MaskablePPO，训练种子 ≥10_000，周期评估种子 70..99，总体 + 分遭遇双口径对照 random/heuristic）
- [x] 两个 baseline：随机策略、简单启发式（斩杀优先/集火残血/格挡补足），`sts/baselines.py`，评估种子 0..99
- [x] **结果（2026-10-05，模型 models/weak_pool_1m_hp76.zip）**：1M 步 MaskablePPO 平均剩余 HP **76.0**/80，超 random（62.0）+14、超 heuristic（75.5）+0.5；分遭遇 3 胜（louses 77.1 / slimes_s 78.9 / fungi 79.7）1 平 1 负（jaw_worm 68.9 vs 72.9，唯一需跨回合规划的怪，小 MLP + 无记忆快照观测的能力上限附近）。300k 版对照 74.6 存 weak_v2_300k.zip
- [~] EXP-02（见 docs/EXPERIMENTS.md）：观测加怪物种类 one-hot（691→851 维，词表 MONSTER_INDEX 稳定 ID），重训 1M 步验证 jaw_worm 短板是否补上——进行中
- 验收：训练策略胜率显著超过两个 baseline ✅

### 第 3 步：扩内容 + 奖励实验

**内容全量迁移（2026-10-05 启动，批次化推进，计划文件见 `~/.claude/plans/lightspeed-pure-harbor.md`）**：

- [x] **批次 0 引擎能力地基**：X 费（energy_on_use 快照）/ CARD_SELECT 选卡状态机（单候选直执）/ Ethereal / Innate / 诅咒状态卡回合末自动结算（no_trigger 路径）/ 六类触发钩子（消耗/抽牌/格挡/自伤/受击/出牌）/ 怪物逃跑+战斗中原位分裂+掉血改意图 / THIEVERY 偷金 / ENTANGLED / POISON / 遗物框架 sts/combat/relics.py（~20 钩子位 + ~35 个已实现遗物）——157 个测试全绿
- [x] **批次 1 简单内容**（2026-10-05）：20 张简单铁甲卡 + 9 种简单怪（双史莱姆 M/奴役者/小鬼帮/哨卫）+ 7 遭遇 + 遗物全量核对（21 处修正）——294 全绿
- [x] **批次 2 中等内容**（2026-10-05）：30 张中等卡（Power 状态族 14/消耗族/虚无/实例计数/生成）+ 精英 Boss 6 怪（Gremlin Nob/Lagavulin/Guardian/Hexaghost/Mad Gremlin/Taskmaster）——352 全绿
- [x] **批次 3 困难内容**（2026-10-05）：Whirlwind（X 费）+ 选卡六件（Armaments/Headbutt/Dual Wield 等）+ 分裂怪（L 级史莱姆/Slime Boss）+ Looter/Mugger + RNG 遗物 6 个——425 全绿
- [x] **批次 4 无色/诅咒/状态卡全量**（2026-10-05）：无色 34 张 + 诅咒 14 张正式化（curses_cards.py）+ RUPTURE 引擎补位 + SADISTIC/PANACHE/SHACKLED 三处接线——545 全绿；**终验：随机策略 21 遭遇×8 种子全跑通无死循环**。铁甲 Act 1 全内容迁移完成（~130 卡 + 27 怪 + ~55 遗物 + 21 遭遇）
- [x] **官方本地化对齐**（2026-10-07）：`scripts/align_zhs.py` codemod 把 content 层中文名/描述与 `sts_game_data/localization/zhs/` 对齐——卡牌 373 张（zh=官方 NAME；text=官方 DESCRIPTION 代入基础数值，数值源=反编译 baseDamage/baseBlock/baseMagicNumber，4 张 misc 型手工覆写；去自造「（升级 X）」注记）、怪物 62 种（display_name 一并改）、招式名（官方 MOVES 有名的 39 个经 `setMove(NAME 常量, byte)` 机械推导 + `MOVE_CONST_ALIAS` 别名表对齐；官方无名的 170 个保留项目现名，见脚本运行报告）、药水 42（描述按反编译 Potion.description 构造行拼接数值）、遗物 `combat/relics.py` 新增 `RELIC_ZH` 全覆盖（9 个内部键名特判，如 DUALITY→Yang/两仪）。锁测试 `tests/test_zhs_alignment.py`（名称全对齐 + text 无占位符/图标/注记残留）。注意：本体内部 ID 与 wiki 名不同的卡经 eng NAME 映射（Apparition→Ghostly、Rushdown→Adaptation 等），monsters.py 日志文案 35 处同步
- [x] **全职业扩展（2026-10-06 完成，超出原 Act 1 范围的用户指令）**：
  - [x] 批次 A 引擎地基：Retain/limbo/手动弃牌管线 + 29 个 Act 2-4 怪物状态 + half_dead 二阶段 + TIME_WARP 提前回合
  - [x] 批次 B：Act 2 全怪 15 种 + 19 遭遇（HEX 语义对齐修正）
  - [x] 批次 C：Silent 全卡 75 张（wiki 权威源 + 弃牌/毒/Shiv 管线接线 + 3 处我方接线语义错误修正）
  - [x] 批次 D：Act 3/4 全怪 20 种 + 18 遭遇（62 种怪全齐：含 Awakened One 二阶段/Time Eater/Corrupt Heart）
  - [x] 批次 E：Watcher 全卡 83 张 + Stance/Scry/真言子系统（姿态能量语义/WRATH 承伤 ×2/Wave of the Hand/BLOCK_RETURN/Nirvana/保留族增量等 15+ 项接线）
  - [x] 批次 F：Defect 全卡 75 张 + 充能球子系统（channel/evoke/passive/FOCUS/LOOP/ELECTRO/REBOUND/BIAS/BUFFER，lightspeed 空壳按 Java 原版自建）
  - 终验：四职业初始牌组 × 58 遭遇 × 456 场随机对局全部正常终局，1245 测试全绿
- [~] **批次 5（进行中，设计已定稿 2026-10-07，详见 DESIGN.md §5.2）**：env 观测/动作空间整体重构 + 铁甲全内容重训。核心决策：平铺计数（词表 (卡名,升级) ≈736）、先铁甲后四职业、CARD_SELECT 自回归 + 候选窗口 10（截断记近似）、首轮帧堆叠。分四小批：
  - [x] 5a 观测侧（2026-10-07 完成，1422 测试全绿）：`sts/vocab.py` 全量词表（卡 368 唯一定义 ×(基础,升级) = 736 位，id="模块:常量名" 按对象身份索引——跨职业同名 Strike 值全同不撞；怪 68/词表 72；药水 42/48；`scripts/gen_vocab.py` 生成 + `tests/test_vocab.py` 锁测试强制内容变动后重生成）；观测 691→4994 维（新增职业/金币/姿态/orb/遗物 multi-hot+计数器/药水/limbo 第 4 堆/手牌升级位），OBSERVATION_MAXIMUMS 同步；状态层数段 Box 下界放开 -99（负力量/敏捷/FOCUS 是真实可见信息，Lagavulin 虹吸路径踩出）；unplayable mask 缺口修复（镜像 play_card 四道资格闸：unplayable+Blue Candle/Medical Kit 解锁、Clash 类 play_condition、ENTANGLED 拦攻击、VELVET_CHOKER）；审计扩四堆+新段；env 新增 character/relics/potions 构造参数（职业 one-hot + 非 80 血职业构造后修正）；65 遭遇×2 种子随机 rollout 全终局无死锁无越界
  - [x] 5b 动作侧（2026-10-07 完成，1437 测试全绿）：动作空间 61→120（Discrete）——药水段 5 槽×(自身/单怪自动+5 目标) + 姿态药水 choice 段（镜像 use_potion 四道闸：PLAYER_ONLY/auto_only/escape_only Boss 禁用/choices+targeting）；CARD_SELECT 自回归（SELECT 再选取消 + CONFIRM，env 侧窗口/选中态经 CardSelectInfo 强引用身份同步，链式选卡与回合末保留选卡路径实测）；SCRY keep_top_n 0..7 段；三挂起态互斥由 mask 表达。观测 +7434 维（12428）：输入状态 one-hot + 展示窗口 10 槽×词表 one-hot/槽特征/选中标志（候选按词表位稳定排序呈现——§4.3 新增候选顺序不变式测试，防堆序泄露）；env 新增 deck 透传参数；baselines 挂起态安全闸（heuristic 在 CARD_SELECT/SCRY 下最保守合法动作，智能启发式留 5c）。集成电池：选卡/检视/药水牌组 × 5 遭遇 × 3 种子随机 rollout（169 选卡点/17 检视/18 药水）零死锁零越界零 mask-引擎不一致
  - [x] **迷你局环境 `sts/run_env.py`（2026-10-07，用户指令升级 5c 范围）**：8 场固定结构（3 弱怪 → 精英 1 → 2 强怪 → 精英 2 → Boss）+ 局外掉落——StsBattleEnv 组合封装（动作 120/观测 12428+16 透传），掉落预设全部取自本体反编译源码：火堆 30% max_hp ×3 次（精英 1/2/Boss 前，CampfireSleepEffect）、药水 40% + blizzard ±10 补偿 + 65/25/10 稀有度 + 铁甲池 33（AbstractRoom/PotionHelper，potions.py rarity 字段按源码修正 26 处）、卡牌奖励 3 张 3/37/60 + 保底计数器（+5 起、common −1 至 −40、rare 归位）+ Act 1 升级率 0%（AbstractRoom.getCardRarity/getRewardCards）、精英遗物 50/32/17 tier roll 去重（MonsterRoomElite，wiki+源码双源 tier 表 79 个入池）。奖励口径（用户决策）：逐场剩血求和；选牌（用户决策）：前 3 场必选、后期 50% 跳过。HP 跨场继承 + 燃烧之血战后回 6 已联动。tests/test_run_env.py 20 例。基线（20 种子）：random 平均 1.48 最远第 5 场 0 通关；heuristic 平均 3.04 最远第 8 场 0 通关（死因：精英 10/强怪 9/Boss 1，梯度合理）
  - [x] **Boss 专家环境 `sts/boss_env.py`（2026-10-08 用户指令）**：run 训练中 Boss 样本稀缺（只有活到第 8 场的轨迹含 Boss 战斗）且无局外学习——按概率模拟 Boss 入场状态单独训练应对策略。入场状态两来源：牌组/遗物/药水/保底计数器走 run 层精确 RNG 重放（StsRunEnv 掉落逻辑逐场快进，分布与策略无关天然正确）；HP 按 `sts/boss_entry_costs.json` 实测条件分布采样（外层 PPO 到达 Boss 轨迹的逐场净损耗，`scripts/estimate_boss_entry.py`；v1 heuristic 标定被否——精英均值 61/死亡率 41% 会把入场 HP 几乎全钳到 1）。火堆 3 次如实结算；奖励与 run 层同口径（胜 = 实际 HP/80，解耦 max_hp）。`tests/test_boss_env.py` 8 例；顺手修 X 费卡 cost=-1 的观测越界（旋风斩进奖励池后踩出）
  - [x] **训练完成（2026-10-08 凌晨链，全部结果见 docs/EXPERIMENTS.md EXP-04/05/06）**：run_v1 2M 3.11/0% 通关 → 网络扫描四档（[512,256]@1M 3.88/10% 通关为甜点，宽度倒 U、深度负收益、大网 2M 步反而更差）→ Boss 专家两网（[512,256] 30% 总胜率 vs baseline 3-7%，guardian 38%）→ 混合架构验证（2/30 通关，短板=boss_env HP 分布缺高值尾部——满血入场 3 局全输；待办：尾部过采样重训 boss_v2 + 帧堆叠验证 hexaghost）。链式执行踩出并修复：EVOLVE 递归爆栈引擎 bug（+洗牌计数语义）、torch/OpenMP 活锁（OMP_NUM_THREADS=4 + 心跳看门狗）
  - [ ] 5c 训练侧：heuristic baseline 挂起态智能规则 + 训练脚本接 run 场景 + 铁甲重训（对照 random 1.48 / heuristic 3.04 基线）
  - [ ] 5d 四职业：单策略 vs 分策略（职业 one-hot / stance / orb 观测段 5a 已建）
  - 旧模型（weak_pool_1m_hp76.zip 等）届时作废。原待办已并入上述小批：CARD_INDEX/MONSTER_INDEX 全词表（5a）、unplayable mask 缺口（5a）、CARD_SELECT/SCRY/X 费动作空间表达（5b，X 费沿用全能量近似）、ScenarioSpec.deck 卡组采样（5c 后视需要）、多职业动作空间差异（5d，四职业动作形态一致已确认）
- 决策点：Gremlin 帮逃跑（lightspeed 未实现、真实游戏有）→ 按分布级保真补齐；Normality 诅咒限制（lightspeed 未实现）→ 跳过并注释

原有子项：
- [ ] 奖励对比实验：稀疏 ±1 vs HP shaping
- [x] 多敌人战斗（最多 5 个槽位）——引擎已支持（MonsterGroup.MAX_MONSTERS=5）
- 验收：训练策略对 Act 1 敌池多数敌人胜率 > 启发式 baseline（批次 5 训练验证）

### 第 4 步：卡组泛化（为 Phase 2 铺路）
- [ ] 卡组可变长编码（multi-hot/计数）
- [ ] 卡组分布采样训练（模拟真实选牌过程的随机演化卡组）
- [ ] HP 比例进观测
- 验收：没见过的卡组上胜率不掉得离谱（泛化 sanity check）

## Phase 2：战斗 oracle
- [ ] oracle 接口：V(卡组, 敌人, 进场HP, 药水开关) → (E[战损], P[死], HP损失分布)——分布以 3~5 分位点输出（DESIGN.md §8.1：局外搜索 HP 分布传递，点期望低估猝死尾部）
- [ ] 实现：泛化战斗策略 + N 次 rollout 统计；结果缓存键 (卡组 multi-hot 哈希, 遭遇, HP 桶化~5%, 药水开关)
- [ ] 人工校验：战损排序符合游戏直觉（如 Guardian 比 Louse 贵）
- [ ] 药水加入战斗动作空间
- 验收：oracle 战损统计与 CommunicationMod 真游戏统计分布接近

## Phase 3：局外层

设计已定稿（2026-10-07，详见 DESIGN.md §8）：**受限深度搜索 + 学习型 run-value 网络 V̂**。价值函数 P(通关) + α·E[终局HP]；选牌不采样未来 draft；商店局部搜索。局外模拟器不依赖 oracle，可在 Phase 2 期间开工。落地前待定项清单见 DESIGN.md §8.6（run 状态规格/动作域/地图生成/随机源/事件/局外遗物/V̂ 训练细节等 10 项）。

- [x] 局外模拟器骨架（2026-10-08，`sts/overworld/` 全套 11 模块 + `sts/content/events.py`）：RunState（含 clone/restore 快照）/ 忠实移植地图生成（map_gen.py + docs/MAP_GENERATION.md）/ RunSimulator 完整 Act 1 房间循环（战斗/精英/？房/宝箱/火堆/商店/Boss→Boss宝箱）/ RunPolicy 协议 + 随机/简单启发式两策略。引擎小扩展：deck 条目 (CardDef, upgraded) 元组 + env 透传 relic_counters（古茶具/壶铃计数器）；RelicId 扩至 180。完整随机 rollout 多种子终局 + 确定性轨迹测试全绿（1547 测试）。已知省略：Neow、A1+、Sozu 领取拦截、DARKSTONE_PERIAPT 战斗面
- [x] 随机源规格落地（2026-10-08）：card_rewards.py（稀有度 3/37/60 + pity + 房间阈值 + 槽内去重 + 棱镜碎片全职业池）/ drops.py（金币/精英遗物/药水 40%+blizzard+65/25/10 拒绝采样/宝箱同 roll 怪癖 + 套娃）/ shop.py（5+2 卡/遗物 3 槽尾取/价格公式/打折卡/Courier 补货）/ event_roll.py（？房型斜坡 + 25% shrine 分流 + 池过滤抽后移除）/ relic_pools.py（铁甲五池 33/31/28/15/22 + 头尾取 + 降级链）/ card_pools.py（职业稀有度池 + 无色池 + 诅咒池）
- [x] Act 1 事件全量 + 局外遗物效果桶（2026-10-08）：events.py 24 事件（11 普通 + 6 神龛 + 7 一次性，NoteForYourself 跳过）；战斗事件直连引擎（冒险者尸体精英三选一/蘑菇巢穴）；局外遗物效果 relic_effects.py（拾取效果/蛋类/营地三件套/商店折扣/？房干预/羽翼之靴旁路/套娃）
- [ ] 3a 纯启发式 + oracle 跑通完整 Act 1（模拟器已就绪，待 oracle：当前 RandomPolicy+启发式战斗 50 种子 0 通关——启发式战斗策略对 Boss 0/20，3a 强度依赖战斗侧）——**兼作 V̂ 的自对弈数据源**
- [ ] 3b 受限深度 expectimax/MCTS 规划器（战斗转移多次 rollout 取期望，禁固定种子；HP 分位点分布传递；oracle 结果缓存）
- [ ] V̂ run-value 网络 + 自对弈数据管线：(run 状态, 真实结局) 监督，无手工奖励，闭环迭代
- [ ] α=0 vs α>0 对照实验（P(通关) 与终局 HP 双指标）
- [ ] 药水开关纳入规划
- [ ] 局外信息边界审计（§8.4：重掷全部内容生成流，估值不变）
- [ ] （可选）选牌评估器学习组件（逼近搜索估值，省在线 oracle 调用）
- 验收：完整 Act 1 通关率的 baseline 对比数字（对照启发式选牌 3a 版）

## 可选支线
- 信息价值对照实验：训练一组"可见抽牌堆顺序"的 agent，量化透视的胜率增益（研究副产品）
- BC 预训练：CommunicationMod 录制轨迹 → BC → PPO 微调

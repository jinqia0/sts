# 参考资料与现有项目盘点（REFERENCES.md）

## 生态关键项目

| 项目 | 是什么 | 对本项目的作用 |
|---|---|---|
| [ForgottenArbiter/CommunicationMod](https://github.com/ForgottenArbiter/CommunicationMod) (155★, MIT) | 一代官方事实标准的 mod 桥接：stdin/stdout 换行分隔 JSON，全量游戏状态推送 + 文本命令（PLAY/END/POTION/CHOOSE/PROCEED…）。依赖 ModTheSpire + BaseMod | 采集轨迹、统计级验证基准、后期真游戏评测。吞吐每秒仅几个决策，不可用于训练 |
| [ForgottenArbiter/spirecomm](https://github.com/ForgottenArbiter/spirecomm) (103★, MIT) | CommunicationMod 的 Python 封装 | 配套使用 |
| [lhy-loveworld/rusted-spire](https://github.com/lhy-loveworld/rusted-spire) | 一代 Rust 无头战斗模拟器（PyO3 → Gym）。去全局静态 + 去动作队列的架构、三层保真度验证方法论（RNG_VALIDATION/COMBAT_TRACES/ELITE_BOSS_AUDIT）、伤害管线钩子链设计 | **架构与验证方法论的主要参考**。内容仅 29 卡/21 怪，其 PPO 结果无效（0/300 胜），只学骨架不学结论 |
| [vvsuby/sts2-rl-agent](https://github.com/vvsuby/sts2-rl-agent) | 二代无头 Python 重实现（577 卡/121 怪/290 遗物），Gymnasium + action masking，BC→PPO 三阶段流水线，~28K steps/s，4500 测试 | **Python 模拟器性能可行性的证据**（28K steps/s 够训练）；BC→PPO 流水线参考。⚠️ 无开源许可证——只能参考思路，禁止抄代码 |
| [gamerpuppy/sts_lightspeed](https://github.com/gamerpuppy/sts_lightspeed) | C++ 高速 RNG 精确 playout 模拟器（rusted-spire 致谢的上游） | 参考其一回合内搜索/精确求解思路 |

## 数据来源

- 一代反编译：CFR（https://www.benf.org/other/cfr/）或 Procyon 反编译 desktop jar，得到 `com.megacrit.cardcrawl.*` 源码，卡牌数值多在构造函数中
- 动态 dump：ModTheSpire + BaseMod 环境下写小 mod 遍历注册表序列化 JSON（一次得到与游戏版本精确一致的全量数据）
- 二代（如未来涉及）：ILSpy 反编译 Assembly-CSharp.dll

## RL 学习资源

- Hugging Face Deep RL Course（免费、有实践）——主要教材
- OpenAI Spinning Up——PPO 直觉补充
- Sutton & Barto——当字典查，不通读
- sb3-contrib MaskablePPO 文档与示例

## 明确跳过

Q-learning/DQN 系、模型类方法（MPC/MuZero）、连续控制、分布式 RL（IMPALA/Ape-X）。

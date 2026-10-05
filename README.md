# STS-RL

杀戮尖塔强化学习 AI 项目。当前阶段：战斗模拟器 + 战斗内策略（Phase 1）。

设计决策见 `docs/DESIGN.md`，进度见 `docs/ROADMAP.md`。

## 最小战斗场景（已完成）

铁甲战士初始牌组（5 打击 / 4 防御 / 1 痛击）vs 邪教徒（Cultist）。

```bash
# 人机 CLI 试玩（可固定种子复现）
uv run python -m sts.cli [--seed N]

# 测试（伤害管线数值、Cultist 行为、牌堆流转、胜负判定、种子确定性）
uv run pytest
```

## 代码结构

```
sts/
  combat.py      # CombatState：一场战斗一个实例，无全局状态；回合流转与结算
  combatants.py  # Combatant / Player / Enemy
  cards.py       # 卡牌定义（不可变单例），初始牌组
  enemies.py     # 敌人定义与意图生成（roll_intent）
  powers.py      # Power 栈 = 钩子系统（伤害管线钩子 + 回合钩子）
  rng.py         # numpy RNG 薄封装（分布级保真，不做种子对齐）
  cli.py         # 人机 CLI
tests/           # pytest
```

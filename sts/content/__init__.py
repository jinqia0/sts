"""内容层：卡牌/怪物/遭遇的纯数据 + 行为定义（对齐 lightspeed constants/）。

引擎（sts/combat/）不感知任何具体卡牌与怪物；本包把效果表达为
「向 BattleContext 入队原子动作」。扩内容 = 往这里加定义，不动引擎。
"""

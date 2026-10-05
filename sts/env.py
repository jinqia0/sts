"""Gymnasium 战斗环境封装（DESIGN.md §4 信息边界 + §5.1 观测设计）。

动作空间（spaces.Discrete(61)，扁平编码，目标位一步到位）：
    0        END_TURN
    1..10    出手牌槽 0..9（needs_target 的牌在单敌人遭遇下自动指向
             唯一存活敌人——与引擎 play_card 的自动指向分支一致）
    11..60   手牌槽 i (0..9) × 目标 j (0..4)，编码 11 + i*5 + j
             （多敌人遭遇时 needs_target 的牌走这一段）
当前只有 Cultist 单怪，但 5 个敌人槽已预留，后续加怪不改动作空间。

观测空间（spaces.Box int32，全整数特征）+ 模块级 OBSERVATION_MAXIMUMS
每维上界表——参考 sts_lightspeed bindings NNInterface 的设计：离散特征
配显式上界，上层可自行归一化或直接做 Embedding。布局（OBS_DIM 维）：

    段                    维数    内容
    O_PLAYER              6       hp, max_hp, block, energy, 能量比, 手牌数
    O_PSTAT               10      玩家状态层数（PlayerStatus 固定枚举序）
    O_HAND_SLOT           60      手牌槽×(占用,类型one-hot×3,费,需目标)
    O_HAND_COUNT          128     手牌构成计数（与 CARD_INDEX 对齐）
    O_ENEMY               255     敌人槽×(hp,max_hp,block,存活,
                                  意图类型one-hot×5,意图数值,状态×9,
                                  种类one-hot×32)
    O_PILE_DRAW 等         384     抽/弃/消耗堆的每种卡计数
    O_TURN                1       回合数

信息边界（DESIGN.md §4，硬性）：观测只有白名单信息；牌堆只给构成
（计数向量），顺序物理上不进编码；未来意图在怪物回合末才生成，观测
中不存在未来值；RNG 状态不进观测。tests/test_env.py 的信息泄露审计
逐位验证以上三条。
"""

from __future__ import annotations

import warnings

import gymnasium as gym
import numpy as np
from gymnasium import spaces

from sts.combat.battle import ENERGY_PER_TURN, BattleContext
from sts.combat.types import InputState, MonsterStatus, Outcome, PlayerStatus

# ---- 动作编码 ----
N_ACTIONS = 61
ACTION_END_TURN = 0
HAND_SLOT_BASE = 1  # 动作 HAND_SLOT_BASE + i = 出手牌槽 i（i ∈ 0..9）
TARGETED_BASE = 11  # 动作 TARGETED_BASE + i*5 + j = 槽 i 指向目标 j
N_HAND_SLOTS = 10
N_TARGET_SLOTS = 5

# 回合上限保险丝：超过即 truncated（正常 Cultist 战 10~15 回合，
# 上层 curriculum 若要更短上限可自行包装 TimeLimit）
TURN_LIMIT = 100

# 弱怪池：encounter="random" 时每局从中均匀抽一种（单场随机遭遇，
# 各怪被采样次数相同——比连打序列的样本分布更干净）
WEAK_POOL = ("cultist", "jaw_worm", "louses", "slimes_s", "fungi_beast")

# ---- 卡牌词表（卡名 → 稳定索引）----
# 扩卡时只向后追加，已分配的索引永不重排（否则旧 checkpoint 的
# 观测语义漂移）。词表固定 128 维，当前 3 张卡只用前几个索引，
# 后续扩卡不改观测维度。
CARD_VOCAB_SIZE = 128
CARD_INDEX: dict[str, int] = {"Strike": 0, "Defend": 1, "Bash": 2}


def card_index(name: str) -> int | None:
    """卡名 → 词表索引；未收录的卡返回 None（该维恒 0，不崩）。"""
    return CARD_INDEX.get(name)


# ---- 特征上界（超界截断，对齐 lightspeed getObservation 的 min() 风格）----
CAP_HP = 999
CAP_BLOCK = 999
CAP_ENERGY = 99
CAP_STATUS = 99
CAP_CARD_COUNT = 99
CAP_INTENT_DAMAGE = 999
CAP_TURN = 999
CAP_ENERGY_RATIO = 100

# ---- 固定枚举顺序（观测维度语义稳定，不受枚举追加影响）----
PLAYER_STATUS_ORDER = tuple(sorted(PlayerStatus, key=lambda s: s.value))
MONSTER_STATUS_ORDER = tuple(sorted(MonsterStatus, key=lambda s: s.value))
INTENT_KINDS = ("attack", "buff", "debuff", "defend", "unknown")

# ---- 怪物种类的稳定词表（玩家可见：怪的名字/立绘，白名单内）----
# 与 CARD_INDEX 同规则：扩怪只向后追加，已分配索引永不重排。
# 32 位覆盖全游戏怪池（一代 70+ 种）绰绰有余。
MONSTER_VOCAB_SIZE = 32
MONSTER_INDEX: dict[str, int] = {
    "Cultist": 0,
    "Jaw Worm": 1,
    "Red Louse": 2,
    "Green Louse": 3,
    "Acid Slime (S)": 4,
    "Spike Slime (S)": 5,
    "Fungi Beast": 6,
}


def monster_index(name: str) -> int | None:
    """怪名 → 词表索引；未收录返回 None（该段全零，不崩）。"""
    return MONSTER_INDEX.get(name)


# ---- 观测布局（段大小与偏移集中定义，_get_obs 与上界表共用）----
_N_PLAYER = 6
_N_PSTAT = len(PLAYER_STATUS_ORDER)
_N_SLOT_FEAT = 6  # (占用, Attack, Skill, Power, 费用, 需目标)
_N_ENEMY_FEAT = (
    4 + len(INTENT_KINDS) + 1 + len(MONSTER_STATUS_ORDER) + MONSTER_VOCAB_SIZE
)  # = 19 + 32

# 手牌槽内偏移
_S_OCC, _S_ATTACK, _S_SKILL, _S_POWER, _S_COST, _S_TARGET = range(6)
# 敌人槽内偏移
_E_HP, _E_MAXHP, _E_BLOCK, _E_ALIVE = 0, 1, 2, 3
_E_INTENT = 4
_E_INTENT_VAL = _E_INTENT + len(INTENT_KINDS)
_E_STATUS = _E_INTENT_VAL + 1
_E_SPECIES = _E_STATUS + len(MONSTER_STATUS_ORDER)  # 种类 one-hot 段

O_PLAYER = 0
O_PSTAT = O_PLAYER + _N_PLAYER
O_HAND_SLOT = O_PSTAT + _N_PSTAT
O_HAND_COUNT = O_HAND_SLOT + N_HAND_SLOTS * _N_SLOT_FEAT
O_ENEMY = O_HAND_COUNT + CARD_VOCAB_SIZE
O_PILE_DRAW = O_ENEMY + N_TARGET_SLOTS * _N_ENEMY_FEAT
O_PILE_DISCARD = O_PILE_DRAW + CARD_VOCAB_SIZE
O_PILE_EXHAUST = O_PILE_DISCARD + CARD_VOCAB_SIZE
O_TURN = O_PILE_EXHAUST + CARD_VOCAB_SIZE
OBS_DIM = O_TURN + 1


def _build_maximums() -> list[int]:
    """每维观测上界，与 _get_obs 的段布局共用同一组常量（防漂移）。

    bounds 测试（tests/test_env.py）持续保证两者一致：任何观测值
    超出本表即测试失败。
    """
    caps: list[int] = []
    caps += [CAP_HP, CAP_HP, CAP_BLOCK, CAP_ENERGY, CAP_ENERGY_RATIO, N_HAND_SLOTS]
    caps += [CAP_STATUS] * _N_PSTAT
    for _ in range(N_HAND_SLOTS):
        caps += [1, 1, 1, 1, CAP_ENERGY, 1]
    caps += [CAP_CARD_COUNT] * CARD_VOCAB_SIZE  # 手牌构成
    for _ in range(N_TARGET_SLOTS):
        caps += [CAP_HP, CAP_HP, CAP_BLOCK, 1]  # hp, max_hp, block, 存活
        caps += [1] * len(INTENT_KINDS)  # 意图类型 one-hot
        caps += [CAP_INTENT_DAMAGE]  # 意图数值
        caps += [CAP_STATUS] * len(MONSTER_STATUS_ORDER)
        caps += [1] * MONSTER_VOCAB_SIZE  # 种类 one-hot
    caps += [CAP_CARD_COUNT] * CARD_VOCAB_SIZE * 3  # 抽/弃/消耗三堆
    caps += [CAP_TURN]
    assert len(caps) == OBS_DIM
    return caps


OBSERVATION_MAXIMUMS: list[int] = _build_maximums()


def _count_into(obs: np.ndarray, base: int, insts) -> None:
    """把一组卡实例按卡名计数进词表段（无序计数，绝不编码顺序）。"""
    for inst in insts:
        idx = card_index(inst.card.name)
        if idx is not None:
            v = obs[base + idx] + 1
            obs[base + idx] = min(v, CAP_CARD_COUNT)


class StsBattleEnv(gym.Env):
    """单场战斗的 Gymnasium 环境：BattleContext 的薄封装。

    - 奖励 = 终局剩余 HP / max_hp（胜利），败/截断 0，进行中 0——
      战损是唯一目标，胜率退化为前提（2026-10-05 用户决策）
    - terminated = 战斗结束；truncated = 回合数超 TURN_LIMIT（防死循环）
    - 训练/评估策略必须经 action_masks() 过滤动作：非法动作在 step
      中直接断言失败，不允许走非法路径把错误延迟到奖励端
    """

    metadata = {"render_modes": []}

    def __init__(self, encounter: str = "cultist") -> None:
        self.encounter = encounter  # 单一遭遇名或 "random"（弱怪池随机）
        self.action_space = spaces.Discrete(N_ACTIONS)
        self.observation_space = spaces.Box(
            low=0,
            high=np.array(OBSERVATION_MAXIMUMS, dtype=np.int32),
            shape=(OBS_DIM,),
            dtype=np.int32,
        )
        # 引擎上下文：对策略/测试公开（heuristic baseline 读白名单信息）
        self.bc: BattleContext | None = None
        self.battle_seed: int | None = None
        self.current_encounter: str = self.encounter

    # ---- Gymnasium API ----

    def reset(self, *, seed: int | None = None, options: dict | None = None):
        super().reset(seed=seed)
        if options is not None and "battle_seed" in options:
            # 复现/测试用：直接指定战斗种子，绕过派生
            self.battle_seed = int(options["battle_seed"])
        else:
            # gymnasium 规范：由环境 np_random 派生战斗种子——
            # reset(seed=s) 两次得到同一场战斗；不传 seed 则每场不同
            self.battle_seed = int(self.np_random.integers(0, 2**31 - 1))
        # 遭遇选择："random" 每局从弱怪池抽一种（np_random 派生，
        # 同种子可复现）；否则用构造时指定的单一遭遇
        if self.encounter == "random":
            self.current_encounter = WEAK_POOL[int(self.np_random.integers(0, len(WEAK_POOL)))]
        else:
            self.current_encounter = self.encounter
        self.bc = BattleContext(seed=self.battle_seed, encounter=self.current_encounter)
        return self._get_obs(), self._get_info()

    def step(self, action):
        if self.bc is None:
            raise RuntimeError("必须先 reset 才能 step")
        action = int(action)
        mask = self.action_masks()
        if not (0 <= action < N_ACTIONS) or not mask[action]:
            raise AssertionError(
                f"非法动作 {action}（合法：{np.flatnonzero(mask).tolist()}）。"
                "训练/评估策略必须经 action_masks() 过滤。"
            )
        bc = self.bc
        try:
            if action == ACTION_END_TURN:
                bc.end_turn()
            elif action < TARGETED_BASE:
                # 单敌人遭遇：引擎在 monster_count==1 时自动指向唯一存活怪
                bc.play_card(action - HAND_SLOT_BASE)
            else:
                i, j = divmod(action - TARGETED_BASE, N_TARGET_SLOTS)
                bc.play_card(i, target=j)
        except ValueError as e:
            # mask 已校验能量/槽位/目标，正常不应到这里——这是引擎边界
            # 情况的兜底（如未来卡牌交互让 play_card 中途抛错）。处理：
            # 该步视为 no-op 转换到回合结束，保证环境永不卡死。
            warnings.warn(f"mask 合法的动作 {action} 被引擎拒绝（{e}），按回合结束兜底")
            if bc.input_state == InputState.PLAYER_NORMAL and not bc.over:
                bc.end_turn()
        terminated = bc.over
        truncated = (not terminated) and bc.turn > TURN_LIMIT
        # 奖励（2026-10-05 用户决策：战损为唯一目标）：
        #   终局 = 剩余 HP / max_hp（胜利）/ 0（败）；进行中恒 0
        #   胜率不再是目标——保不住血自然会输，战损低与获胜在这套
        #   奖励下天然一致。范围 [0,1]，无每步 shaping（HP 变化进
        #   奖励易被「拖回合回血类」歧向利用，DESIGN.md §5 风险）
        if terminated:
            reward = bc.player.hp / bc.player.max_hp if bc.won else 0.0
        else:
            reward = 0.0
        return self._get_obs(), reward, terminated, truncated, self._get_info()

    def action_masks(self) -> np.ndarray:
        """合法动作掩码（sb3-contrib MaskablePPO 约定的入口）。

        战斗结束/非玩家阶段 → 全 False（终止后没有合法动作）。
        玩家阶段：END_TURN 恒合法 + 手牌实际张数内、能量够的槽；
        needs_target 牌在单敌人遭遇走槽动作（引擎自动指向），多敌人
        （或「有死亡怪的遭遇里仅剩一只」）只走 (槽,目标) 组合段。
        """
        mask = np.zeros(N_ACTIONS, dtype=bool)
        bc = self.bc
        if bc is None or bc.over or bc.input_state != InputState.PLAYER_NORMAL:
            return mask
        mask[ACTION_END_TURN] = True
        # 与引擎 play_card 的自动指向条件严格一致（monster_count==1 且可指向）
        single = bc.monsters.monster_count == 1 and bc.monsters.monsters[0].is_targetable()
        for i, inst in enumerate(bc.cards.hand[:N_HAND_SLOTS]):
            if inst.cost > bc.player.energy:
                continue
            if not inst.card.needs_target:
                mask[HAND_SLOT_BASE + i] = True
            elif single:
                mask[HAND_SLOT_BASE + i] = True
            else:
                for j, m in enumerate(bc.monsters.monsters[:N_TARGET_SLOTS]):
                    if m.is_targetable():
                        mask[TARGETED_BASE + i * N_TARGET_SLOTS + j] = True
        return mask

    # ---- 观测与 info ----

    def _get_obs(self) -> np.ndarray:
        """从引擎状态构造观测（只用 DESIGN.md §4.1 白名单信息）。"""
        bc = self.bc
        assert bc is not None
        obs = np.zeros(OBS_DIM, dtype=np.int32)
        p = bc.player

        obs[O_PLAYER + 0] = min(p.hp, CAP_HP)
        obs[O_PLAYER + 1] = min(p.max_hp, CAP_HP)
        obs[O_PLAYER + 2] = min(p.block, CAP_BLOCK)
        obs[O_PLAYER + 3] = min(p.energy, CAP_ENERGY)
        # 能量比（百分比）：让策略不必知道「满能量是几点」这一规则量
        obs[O_PLAYER + 4] = min(round(100 * p.energy / ENERGY_PER_TURN), CAP_ENERGY_RATIO)
        obs[O_PLAYER + 5] = min(len(bc.cards.hand), N_HAND_SLOTS)
        for k, s in enumerate(PLAYER_STATUS_ORDER):
            obs[O_PSTAT + k] = min(p.statuses.get(s), CAP_STATUS)

        # 手牌：槽特征给「第 i 张是什么类型的牌、能不能打」，构成计数
        # 给精确卡名。手牌顺序对玩家可见（UI 顺序），编码顺序合法；
        # 牌堆（下段）则只允许无序计数。
        for i, inst in enumerate(bc.cards.hand[:N_HAND_SLOTS]):
            b = O_HAND_SLOT + i * _N_SLOT_FEAT
            obs[b + _S_OCC] = 1
            ctype = {"Attack": _S_ATTACK, "Skill": _S_SKILL, "Power": _S_POWER}.get(inst.card.ctype)
            if ctype is not None:
                obs[b + ctype] = 1
            obs[b + _S_COST] = min(inst.cost, CAP_ENERGY)
            obs[b + _S_TARGET] = 1 if inst.card.needs_target else 0
        _count_into(obs, O_HAND_COUNT, bc.cards.hand)

        # 敌人槽（0..4，顺序 = 引擎索引 = 行动顺序，对玩家可见）：
        # 死亡怪整槽置零（存活位也是 0，天然区分空槽）
        for si, m in enumerate(bc.monsters.monsters[:N_TARGET_SLOTS]):
            if not m.alive:
                continue
            b = O_ENEMY + si * _N_ENEMY_FEAT
            obs[b + _E_HP] = min(m.hp, CAP_HP)
            obs[b + _E_MAXHP] = min(m.max_hp, CAP_HP)
            obs[b + _E_BLOCK] = min(m.block, CAP_BLOCK)
            obs[b + _E_ALIVE] = 1
            if m.move_history:
                move = m.move_history[0]
                kind = move.kind if move.kind in INTENT_KINDS else "unknown"
                obs[b + _E_INTENT + INTENT_KINDS.index(kind)] = 1
                if move.kind == "attack" and move.base_damage is not None:
                    # 意图数值 = UI 展示口径：走完怪物力量/虚弱、玩家
                    # 易伤管线后的实际伤害（tests/test_combat.py 已验证
                    # 该口径与下一击实伤一致）
                    obs[b + _E_INTENT_VAL] = min(
                        bc.calculate_monster_damage(m, move.base_damage), CAP_INTENT_DAMAGE
                    )
            for k, s in enumerate(MONSTER_STATUS_ORDER):
                obs[b + _E_STATUS + k] = min(m.statuses.get(s), CAP_STATUS)
            # 怪物种类 one-hot（玩家可见：名字/立绘）。Monster 子类的
            # name 属性即词表 key。未收录的怪该段全零，模型按特征兜底
            # ——扩怪时把名字加进 MONSTER_INDEX 即可
            spec = monster_index(m.name)
            if spec is not None:
                obs[b + _E_SPECIES + spec] = 1

        # 三堆构成（无序计数）：抽/弃/消耗的顺序都是黑名单信息（§4.2），
        # 这里只数「每种卡剩几张」——物理上不可能泄露顺序
        _count_into(obs, O_PILE_DRAW, bc.cards.draw_pile)
        _count_into(obs, O_PILE_DISCARD, bc.cards.discard_pile)
        _count_into(obs, O_PILE_EXHAUST, bc.cards.exhaust_pile)

        obs[O_TURN] = min(bc.turn, CAP_TURN)
        return obs

    def _get_info(self) -> dict:
        """调试量（不进观测、不进奖励，评估统计用）。"""
        bc = self.bc
        assert bc is not None
        return {
            "hp_remaining": bc.player.hp,
            "turns": bc.turn,
            "won": bc.won,
            "outcome": bc.outcome.name,
            "battle_seed": self.battle_seed,
            "encounter": self.current_encounter,
        }

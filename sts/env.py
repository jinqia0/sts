"""Gymnasium 战斗环境封装（DESIGN.md §4 信息边界 + §5.1/§5.2 观测设计）。

动作空间（spaces.Discrete(120)，扁平编码，批次 5b 全量接线）：
    0         END_TURN（仅 PLAYER_NORMAL）
    1..10     出手牌槽 0..9（needs_target 的牌在单敌人遭遇下自动指向
              唯一存活敌人——与引擎 play_card 的自动指向分支一致）
    11..60    手牌槽 i (0..9) × 目标 j (0..4)，编码 11 + i*5 + j
    61..90    药水槽 s (0..4) × 用法 j：61 + s*6 + j；j=0 自身/单怪自动
              指向，j=1..5 显式目标 j-1（targeting 药水）
    91..100   姿态药水槽 s × 选择 c：91 + s*2 + c（c=0 愤怒, 1 平静）
    101..110  选卡窗口槽 i（CARD_SELECT 自回归 SELECT(i)，再次选取消）
    111       选卡提交 CONFIRM（空选择需 can_pick_zero）
    112..119  Scry 保留堆顶 k 张：112 + k（k=0..7，SCRY 挂起态）

三种输入挂起态（PLAYER_NORMAL / CARD_SELECT / SCRY）互斥，天然由
mask 表达：每个状态只开放自己的动作段。选卡是自回归多步：引擎
open_card_select 挂起 → env 把候选按稳定卡 ID 排序进 10 槽窗口
（DESIGN.md §5.2：候选顺序与堆内部顺序解耦，防泄露；超窗截断为
已记录近似）→ SELECT×n → CONFIRM 调 choose_cards 一次性提交。

观测空间（spaces.Box int32，全整数特征）+ 模块级 OBSERVATION_MAXIMUMS
每维上界表——参考 sts_lightspeed bindings NNInterface 的设计：离散特征
配显式上界，上层可自行归一化或直接做 Embedding。布局（OBS_DIM 维，
批次 5a 全量词表接线，词表见 sts/vocab.py；5b 增补模式与展示窗口段）：

    段                    维数    内容
    O_PLAYER              7       hp, max_hp, block, energy, 能量比, 手牌数, 金币
    O_CLASS               4       职业 one-hot（env 参数 character，数据级）
    O_PSTAT               68      玩家状态层数（PlayerStatus 全量固定序，可负）
    O_STANCE              4       姿态 one-hot（观者）
    O_ORB                 27      充能球 5 槽×(占用+4类型) + 槽位上限 + 暗球存层
    O_HAND_SLOT           7360    手牌槽×(736 词表one-hot + 8 特征)——槽级
                                  卡牌身份（2026-10-09 修复：原仅聚合特征，
                                  同费同类型牌在槽间不可辨）
    O_HAND_COUNT          736     手牌构成计数（词表位 2k=基础版、2k+1=升级版）
    O_ENEMY               620     敌人槽×(hp,max_hp,block,存活,意图×5,
                                  意图数值,状态42,种类one-hot×72)
    O_PILE_DRAW 等        2944    抽/弃/消耗/保留(limbo)四堆的构成计数
    O_RELIC               258     战斗遗物 129 multi-hot + 129 公开计数器
    O_POTION              245     药水 5 槽×(占用 + 42 one-hot)
    O_TURN                1       回合数
    O_MODE                4       输入状态 one-hot（PLAYER_NORMAL/CARD_SELECT/
                                  SCRY/EXECUTING）
    O_PRESENT             7360    展示窗口 10 槽 × 词表 one-hot——CARD_SELECT
                                  =稳定序候选 / SCRY=堆顶序检视牌（对玩家可见）
    O_PRESENT_FEAT        60      展示窗口槽×(占用,类型×3,费,升级)
    O_PRESENT_SEL         10      选中标志（CARD_SELECT 自回归中间态）

信息边界（DESIGN.md §4，硬性）：观测只有白名单信息；四堆只给构成
（计数向量，词表位按 (卡, 升级) 分维——升级是性能不同的牌），顺序
物理上不进编码；手牌顺序对玩家可见（UI 顺序），编码顺序合法；未来
意图在怪物回合末才生成，观测中不存在未来值；RNG 状态不进观测。
CARD_SELECT 候选按词表位排序呈现（候选顺序 ≠ 堆序，§4.3 审计有
不变式测试）；Scry 展示期间堆顶顺序可见是游戏机制本身（合法）。
tests/test_env.py 的信息泄露审计逐位验证以上各条。
"""

from __future__ import annotations

import warnings

import gymnasium as gym
import numpy as np
from gymnasium import spaces

from sts.combat.battle import ENERGY_PER_TURN, BattleContext
from sts.combat.relics import BOSS_ENCOUNTERS, RelicId
from sts.combat.types import (
    InputState,
    MonsterStatus,
    Orb,
    Outcome,
    PlayerStatus,
    Stance,
)
from sts.scenarios import REWARD_DAMAGE, REWARD_SPARSE_PM1, ScenarioSpec, get_scenario
from sts.vocab import (
    CARD_VOCAB_SIZE,
    CHARACTERS,
    CHARACTER_MAX_HP,
    MONSTER_INDEX,
    MONSTER_VOCAB_SIZE,
    POTION_INDEX,
    POTION_VOCAB_SIZE,
    card_vocab_index,
)

__all__ = [
    "N_ACTIONS", "ACTION_END_TURN", "HAND_SLOT_BASE", "TARGETED_BASE",
    "N_HAND_SLOTS", "N_TARGET_SLOTS", "TURN_LIMIT", "ACTION_LIMIT", "WEAK_POOL",
    "OBSERVATION_MAXIMUMS", "OBS_DIM", "StsBattleEnv",
    "MONSTER_INDEX", "MONSTER_VOCAB_SIZE",  # test_scenarios 等旧引用面
]

# ---- 动作编码（批次 5b 全量，见模块头布局表）----
N_ACTIONS = 120
ACTION_END_TURN = 0
HAND_SLOT_BASE = 1  # 动作 HAND_SLOT_BASE + i = 出手牌槽 i（i ∈ 0..9）
TARGETED_BASE = 11  # 动作 TARGETED_BASE + i*5 + j = 槽 i 指向目标 j
N_HAND_SLOTS = 10
N_TARGET_SLOTS = 5
POTION_BASE = 61  # 61 + s*6 + j：药水槽 s × (j=0 自身/单怪自动, j=1..5 目标 j-1)
POTION_STANCE_BASE = 91  # 91 + s*2 + c：姿态药水槽 s × (c=0 愤怒, 1 平静)
STANCE_CHOICES = ("wrath", "calm")
SELECT_BASE = 101  # 101 + i：选卡窗口槽 i（单调选择：已选槽不可再选）
SELECT_CONFIRM = 111  # 提交当前选择
SCRY_BASE = 112  # 112 + k：Scry 保留堆顶 k 张（k=0..SCRY_KEEP_MAX）
# Scry 上界：内容最大 scry 5（观者卡）+ 金眼遗物 +2 = 7；留 1 位余量
SCRY_KEEP_MAX = 7
N_SELECT_WINDOW = 10  # 选卡候选窗口（DESIGN.md §5.2：超窗截断为已记录近似）

# 回合上限保险丝：超过即 truncated（正常战斗 5~15 回合）。v2 战损奖励
# 下 100 回合是拖延强吸引子（2026-10-08 实测：ep_len 锁死 1035 的防御
# 重播路线）——收紧到 25（真实玩家的宽松上界），配合截断=死亡级定价
# 把僵局窗口压到不值得（上层 curriculum 可自行包装 TimeLimit 再调）
TURN_LIMIT = 25

# 回合内动作预算保险丝（2026-10-08）：TURN_LIMIT 按回合计，挡不住
# 「合法但零进度」的回合内死循环——实测强怪档塌缩策略锁死在
# CARD_SELECT 的 toggle 语义上（SELECT(1) 选/取消往复 296 次，回合
# 永不推进，回合上限失效的吸收态）。正常战斗一局 ≤ ~250 步（25 回合
# × 手牌+药水），预算 300 只切病理区不伤正常轨迹；截断同死亡级定价
ACTION_LIMIT = 300

# 弱怪池：encounter="random" 时每局从中均匀抽一种（单场随机遭遇，
# 各怪被采样次数相同——比连打序列的样本分布更干净）
WEAK_POOL = ("cultist", "jaw_worm", "louses", "slimes_s", "fungi_beast")

# ---- 特征上界（超界截断，对齐 lightspeed getObservation 的 min() 风格）----
CAP_HP = 999
CAP_BLOCK = 999
CAP_ENERGY = 99
CAP_STATUS = 99
CAP_CARD_COUNT = 99
CAP_INTENT_DAMAGE = 999
CAP_TURN = 999
CAP_ENERGY_RATIO = 100
CAP_GOLD = 999
CAP_RELIC_COUNTER = 999

# ---- 固定枚举顺序（观测维度语义稳定，不受枚举追加影响）----
PLAYER_STATUS_ORDER = tuple(sorted(PlayerStatus, key=lambda s: s.value))
MONSTER_STATUS_ORDER = tuple(sorted(MonsterStatus, key=lambda s: s.value))
INTENT_KINDS = ("attack", "buff", "debuff", "defend", "unknown")
STANCE_ORDER = (Stance.NEUTRAL, Stance.CALM, Stance.WRATH, Stance.DIVINITY)
ORB_ORDER = (Orb.LIGHTNING, Orb.FROST, Orb.DARK, Orb.PLASMA)

N_RELICS = len(RelicId)  # 129：multi-hot 与计数器段共用（RelicId 稳定 IntEnum）

# ---- 观测布局（段大小与偏移集中定义，_get_obs 与上界表共用）----
_N_PLAYER = 7
_N_CLASS = len(CHARACTERS)  # 4
_N_PSTAT = len(PLAYER_STATUS_ORDER)  # 68
_N_STANCE = len(STANCE_ORDER)  # 4
_N_ORB_FEAT = 1 + len(ORB_ORDER)  # 占用 + 4 类型 one-hot
N_ORB_SLOTS = 5  # 基础 3 + Runic Capacitor/Capacitor 类加成，5 槽封顶编码
_N_ORB_EXTRA = 2  # 槽位上限, 暗球存层
_N_SLOT_FEAT = 8  # (占用, Attack, Skill, Power, 费用, 需目标, 升级, 不可打出)
_N_ENEMY_FEAT = (
    4 + len(INTENT_KINDS) + 1 + len(MONSTER_STATUS_ORDER) + MONSTER_VOCAB_SIZE
)  # = 4 + 5 + 1 + 42 + 72
_N_POTION_FEAT = 1 + POTION_VOCAB_SIZE  # 占用 + 药水 one-hot
N_POTION_SLOTS = 5  # 基础 3 + 药水带 2

# 输入状态 one-hot 固定序（挂起态是动作路由的分支条件，进观测让
# 策略显式感知「当前在选卡/检视」——否则中间步观测与普通步混淆）
INPUT_STATE_ORDER = (
    InputState.PLAYER_NORMAL,
    InputState.CARD_SELECT,
    InputState.SCRY,
    InputState.EXECUTING_ACTIONS,
)
_N_MODE = len(INPUT_STATE_ORDER)  # 4
_N_PRESENT_FEAT = 6  # 展示窗口槽：(占用, Attack, Skill, Power, 费用, 升级)

# 手牌槽内偏移：词表 one-hot（736）在前，聚合特征在后——身份修复
# 2026-10-09：原槽特征不含卡牌身份，同费同类型不同牌（Strike vs
# Twin Strike）槽间逐位相同，精细出牌选择无从谈起。身份 one-hot
# 与构成计数/选卡窗口同口径（2k 基础 / 2k+1 升级）；空槽整段置零。
_N_SLOT_FEAT = CARD_VOCAB_SIZE + 8
_S_ONEHOT = 0
_S_OCC, _S_ATTACK, _S_SKILL, _S_POWER, _S_COST, _S_TARGET, _S_UPGRADED, _S_UNPLAYABLE = range(
    CARD_VOCAB_SIZE, CARD_VOCAB_SIZE + 8
)
# 展示窗口槽内偏移（偏移复用手牌槽语义）
_PS_OCC, _PS_ATTACK, _PS_SKILL, _PS_POWER, _PS_COST, _PS_UPGRADED = range(6)
# 敌人槽内偏移
_E_HP, _E_MAXHP, _E_BLOCK, _E_ALIVE = 0, 1, 2, 3
_E_INTENT = 4
_E_INTENT_VAL = _E_INTENT + len(INTENT_KINDS)
_E_STATUS = _E_INTENT_VAL + 1
_E_SPECIES = _E_STATUS + len(MONSTER_STATUS_ORDER)  # 种类 one-hot 段
# 药水槽内偏移
_P_OCC, _P_ONEHOT = 0, 1
# 遗物段内偏移（multi-hot 段 + 计数器段）
_R_ONEHOT, _R_COUNTER = 0, N_RELICS

O_PLAYER = 0
O_CLASS = O_PLAYER + _N_PLAYER
O_PSTAT = O_CLASS + _N_CLASS
O_STANCE = O_PSTAT + _N_PSTAT
O_ORB = O_STANCE + _N_STANCE
O_HAND_SLOT = O_ORB + N_ORB_SLOTS * _N_ORB_FEAT + _N_ORB_EXTRA
O_HAND_COUNT = O_HAND_SLOT + N_HAND_SLOTS * _N_SLOT_FEAT
O_ENEMY = O_HAND_COUNT + CARD_VOCAB_SIZE
O_PILE_DRAW = O_ENEMY + N_TARGET_SLOTS * _N_ENEMY_FEAT
O_PILE_DISCARD = O_PILE_DRAW + CARD_VOCAB_SIZE
O_PILE_EXHAUST = O_PILE_DISCARD + CARD_VOCAB_SIZE
O_PILE_LIMBO = O_PILE_EXHAUST + CARD_VOCAB_SIZE
O_RELIC = O_PILE_LIMBO + CARD_VOCAB_SIZE
O_POTION = O_RELIC + 2 * N_RELICS
O_TURN = O_POTION + N_POTION_SLOTS * _N_POTION_FEAT
O_MODE = O_TURN + 1
O_PRESENT = O_MODE + _N_MODE
O_PRESENT_FEAT = O_PRESENT + N_SELECT_WINDOW * CARD_VOCAB_SIZE
O_PRESENT_SEL = O_PRESENT_FEAT + N_SELECT_WINDOW * _N_PRESENT_FEAT
OBS_DIM = O_PRESENT_SEL + N_SELECT_WINDOW


def _build_maximums() -> list[int]:
    """每维观测上界，与 _get_obs 的段布局共用同一组常量（防漂移）。

    bounds 测试（tests/test_env.py）持续保证两者一致：任何观测值
    超出本表即测试失败。
    """
    caps: list[int] = []
    caps += [CAP_HP, CAP_HP, CAP_BLOCK, CAP_ENERGY, CAP_ENERGY_RATIO, N_HAND_SLOTS, CAP_GOLD]
    caps += [1] * _N_CLASS
    caps += [CAP_STATUS] * _N_PSTAT
    caps += [1] * _N_STANCE
    for _ in range(N_ORB_SLOTS):
        caps += [1, 1, 1, 1, 1]  # 占用 + 4 类型 one-hot
    caps += [CAP_STATUS, CAP_STATUS]  # 槽位上限, 暗球存层
    for _ in range(N_HAND_SLOTS):
        caps += [1] * CARD_VOCAB_SIZE  # 槽级身份 one-hot
        caps += [1, 1, 1, 1, CAP_ENERGY, 1, 1, 1]
    caps += [CAP_CARD_COUNT] * CARD_VOCAB_SIZE  # 手牌构成
    for _ in range(N_TARGET_SLOTS):
        caps += [CAP_HP, CAP_HP, CAP_BLOCK, 1]  # hp, max_hp, block, 存活
        caps += [1] * len(INTENT_KINDS)  # 意图类型 one-hot
        caps += [CAP_INTENT_DAMAGE]  # 意图数值
        caps += [CAP_STATUS] * len(MONSTER_STATUS_ORDER)
        caps += [1] * MONSTER_VOCAB_SIZE  # 种类 one-hot
    for _ in range(4):  # 抽/弃/消耗/保留四堆
        caps += [CAP_CARD_COUNT] * CARD_VOCAB_SIZE
    caps += [1] * N_RELICS  # 遗物 multi-hot
    caps += [CAP_RELIC_COUNTER] * N_RELICS  # 遗物公开计数器
    for _ in range(N_POTION_SLOTS):
        caps += [1] * _N_POTION_FEAT  # 占用 + 药水 one-hot
    caps += [CAP_TURN]
    caps += [1] * _N_MODE  # 输入状态 one-hot
    for _ in range(N_SELECT_WINDOW):  # 展示窗口词表 one-hot
        caps += [1] * CARD_VOCAB_SIZE
    for _ in range(N_SELECT_WINDOW):
        caps += [1, 1, 1, 1, CAP_ENERGY, 1]  # 展示窗口槽特征
    caps += [1] * N_SELECT_WINDOW  # 选中标志
    assert len(caps) == OBS_DIM
    return caps


OBSERVATION_MAXIMUMS: list[int] = _build_maximums()


def _build_minimums() -> np.ndarray:
    """每维观测下界：默认 0；状态层数段放开到 -CAP_STATUS——负层数是
    真实可见信息（Lagavulin 虹吸灵魂 -1 力量/敏捷、BIAS 把 FOCUS 拖负、
    SHIFTING 减怪力量），钳 0 会抹掉。int32，与上界表同布局。
    """
    low = np.zeros(OBS_DIM, dtype=np.int32)
    low[O_PSTAT : O_PSTAT + _N_PSTAT] = -CAP_STATUS
    _E_STATUS_OFF = _E_STATUS  # 敌人槽内状态段起点
    for si in range(N_TARGET_SLOTS):
        b = O_ENEMY + si * _N_ENEMY_FEAT + _E_STATUS_OFF
        low[b : b + len(MONSTER_STATUS_ORDER)] = -CAP_STATUS
    return low


OBSERVATION_MINIMUMS: np.ndarray = _build_minimums()


def _count_into(obs: np.ndarray, base: int, insts) -> None:
    """把一组卡实例按 (卡牌定义, 升级) 计数进词表段（无序计数）。

    词表位 2k = 基础版、2k+1 = 升级版（DESIGN.md §5.2：升级是性能
    不同的牌，计数必须分维）；绝不编码顺序。
    """
    for inst in insts:
        idx = card_vocab_index(inst.card)
        if idx is not None:
            idx += 1 if inst.upgraded else 0
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

    def __init__(
        self,
        encounter: str | None = None,
        scenario: str | ScenarioSpec | None = None,
        reward: str | None = None,
        species_shuffle: bool = False,
        character: str = "ironclad",
        relics: list[RelicId] | None = None,
        potions: list | None = None,
        deck: list | None = None,
        relic_counters: dict | None = None,
    ) -> None:
        """构造环境。

        - scenario（推荐）：场景名或 ScenarioSpec（sts/scenarios.py 注册表），
          怪池与奖励口径都由配置决定——训练/评估场景的正确入口
        - encounter：单一遭遇名，或 "random"（等价于默认弱怪池场景，
          保留为轻量测试入口）；与 scenario 二选一，都传以 scenario 为准
        - reward：显式覆盖奖励口径（A/B 实验用），默认取场景配置
        - species_shuffle：消融实验开关——每局 reset 时把种类词表重洗
          （种类 one-hot 变成与真种类无关的每局随机噪声，切断全部
          种类信息；同种子可复现）
        - character：职业（观测职业 one-hot；非铁甲职业按官方最大生命
          修正 Player——引擎固定 80，与 webapp 同款构造后修正近似）。
          批次 5c 起由 ScenarioSpec 携带
        - relics / potions / deck：战斗内遗物、初始药水与牌组覆盖
          （透传 BattleContext，测试与 5c 场景配置用；deck 为
          CardDef 列表，无升级位——升级实例经场景层另行表达）
        """
        if scenario is not None:
            self.scenario = get_scenario(scenario)
            self.encounter = "random"
            self.pool: tuple[str, ...] = self.scenario.pool
            if self.scenario.species_shuffle:
                species_shuffle = True
        else:
            self.scenario = get_scenario(None) if encounter in (None, "random") else None
            self.encounter = "cultist" if encounter is None else encounter
            self.pool = WEAK_POOL if self.encounter == "random" else (self.encounter,)
        self.reward_mode = reward if reward is not None else (
            self.scenario.reward if self.scenario is not None else REWARD_DAMAGE
        )
        self.species_shuffle = species_shuffle
        if character not in CHARACTERS:
            raise ValueError(f"未知职业：{character}（可选：{CHARACTERS}）")
        self.character = character
        self.relics = list(relics or [])
        self.potions = list(potions or [])
        self.deck = list(deck) if deck is not None else None
        # 局外遗物计数器透传（如 ANCIENT_TEA_SET counter=-2 表休息过——
        # 必须在 BattleContext 构造时预置，首回合回能前生效）
        self.relic_counters = dict(relic_counters) if relic_counters else None
        # 消融模式：种类 ID → 乱序 ID 的局内映射（reset 时重洗）
        self._species_map: dict[str, int] | None = None
        # ---- CARD_SELECT 自回归状态（批次 5b）----
        # 强引用当前 CardSelectInfo（保旧对象不被回收 → 新选卡对象的
        # 身份比较可靠，id 复用不致误判"同一次选卡"）；窗口/选中态由
        # _refresh_select_state 按引擎挂起状态同步
        self._select_info = None
        self._select_window: list = []  # 排序截断后的候选（窗口序）
        self._select_engine_idx: list[int] = []  # 窗口位 → 引擎候选下标
        self._select_chosen: list[int] = []  # 已选窗口位（选卡先后序）
        self._n_steps = 0  # 回合内动作预算计数（ACTION_LIMIT 保险丝）
        self.action_space = spaces.Discrete(N_ACTIONS)
        self.observation_space = spaces.Box(
            low=OBSERVATION_MINIMUMS.copy(),
            high=np.array(OBSERVATION_MAXIMUMS, dtype=np.int32),
            shape=(OBS_DIM,),
            dtype=np.int32,
        )
        # 引擎上下文：对策略/测试公开（heuristic baseline 读白名单信息）
        self.bc: BattleContext | None = None
        self.battle_seed: int | None = None
        self.current_encounter: str = self.encounter

    # ---- CARD_SELECT 自回归状态同步 ----

    @staticmethod
    def _word_position(inst) -> int:
        """卡实例的稳定排序键 = 词表位（基础 2k / 升级 2k+1）。
        未收录的卡排窗口末尾（兜底，正常不出现）。"""
        idx = card_vocab_index(inst.card)
        if idx is None:
            return CARD_VOCAB_SIZE
        return idx + (1 if inst.upgraded else 0)

    def _refresh_select_state(self) -> None:
        """把引擎 CARD_SELECT 挂起态同步进 env 的窗口/选中态。

        新选卡（CardSelectInfo 身份变化）→ 候选按词表位排序截前
        N_SELECT_WINDOW 进窗口（DESIGN.md §5.2：候选呈现顺序与堆内部
        顺序解耦，防 §4.2 泄露；超窗截断为已记录近似），选中态清零；
        离开 CARD_SELECT → 全部清空。_select_info 持强引用，故同一选卡
        会话期间身份稳定，连续两个不同选卡不会因 id 复用误判。
        """
        bc = self.bc
        if bc.input_state == InputState.CARD_SELECT and bc.card_select_info is not None:
            info = bc.card_select_info
            if self._select_info is not info:
                order = sorted(
                    range(len(info.candidates)),
                    key=lambda k: self._word_position(info.candidates[k]),
                )[:N_SELECT_WINDOW]
                self._select_info = info
                self._select_engine_idx = order
                self._select_window = [info.candidates[k] for k in order]
                self._select_chosen = []
        else:
            self._select_info = None
            self._select_window = []
            self._select_engine_idx = []
            self._select_chosen = []

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
        # 遭遇选择：从配置的怪池抽一种（np_random 派生，同种子可复现）
        if self.encounter == "random":
            self.current_encounter = self.pool[int(self.np_random.integers(0, len(self.pool)))]
        else:
            self.current_encounter = self.encounter
        # 消融模式：每局重洗种类映射（词表值域内随机置换，np_random
        # 派生 → 同种子可复现）。真实 ID 与观测位完全解耦
        if self.species_shuffle:
            shuffled = list(MONSTER_INDEX.values())
            self.np_random.shuffle(shuffled)
            self._species_map = dict(zip(MONSTER_INDEX, shuffled))
        self.bc = BattleContext(
            seed=self.battle_seed,
            encounter=self.current_encounter,
            relics=self.relics or None,
            potions=self.potions or None,
            deck=self.deck,
            relic_counters=self.relic_counters,
        )
        # 新战斗：清空上一局的选卡自回归状态与动作预算计数
        self._select_info = None
        self._select_window = []
        self._select_engine_idx = []
        self._select_chosen = []
        self._n_steps = 0
        # 职业最大生命近似（引擎固定 Player(80)，构造后修正——BattleContext
        # 构造期间无 HP 变动，webapp 同款路径）：观测的 max_hp/HP 比例才真实
        max_hp = CHARACTER_MAX_HP[self.character]
        if max_hp != 80:
            self.bc.player.max_hp = max_hp
            self.bc.player.hp = min(self.bc.player.hp, max_hp)
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
        self._refresh_select_state()  # 窗口/选中态与引擎挂起态同步
        try:
            if bc.input_state == InputState.CARD_SELECT:
                if action == SELECT_CONFIRM:
                    # 选中态按选卡先后序映射回引擎候选下标提交
                    bc.choose_cards([self._select_engine_idx[w] for w in self._select_chosen])
                else:  # SELECT_BASE + i：单调追加（mask 已挡已选槽，无 toggle）
                    self._select_chosen.append(action - SELECT_BASE)
            elif bc.input_state == InputState.SCRY:
                bc.choose_scry(action - SCRY_BASE)
            elif action == ACTION_END_TURN:
                bc.end_turn()
            elif action < TARGETED_BASE:
                # 单敌人遭遇：引擎在 monster_count==1 时自动指向唯一存活怪
                bc.play_card(action - HAND_SLOT_BASE)
            elif action < POTION_BASE:
                i, j = divmod(action - TARGETED_BASE, N_TARGET_SLOTS)
                bc.play_card(i, target=j)
            elif action < POTION_STANCE_BASE:
                # 药水：j=0 自身/单怪自动指向，j=1..5 显式目标
                s, j = divmod(action - POTION_BASE, 6)
                bc.use_potion(s, target=None if j == 0 else j - 1)
            else:
                # 姿态药水选择（wrath/calm）
                s, c = divmod(action - POTION_STANCE_BASE, 2)
                bc.use_potion(s, choice=STANCE_CHOICES[c])
        except ValueError as e:
            # mask 已校验能量/槽位/目标/资格闸，正常不应到这里——这是引擎
            # 边界情况的兜底（如未来卡牌交互让引擎中途抛错）。
            warnings.warn(f"mask 合法的动作 {action} 被引擎拒绝（{e}），兜底推进")
            self._engine_fallback(bc)
        terminated = bc.over
        self._n_steps += 1
        # 双保险丝：回合数超限（跨回合拖延）或总动作数超预算（回合内
        # 零进度死循环——SELECT toggle / 0 费 X 牌重放等吸收态）
        truncated = (not terminated) and (bc.turn > TURN_LIMIT or self._n_steps > ACTION_LIMIT)
        # 奖励口径由场景配置决定（scenarios.py，可被构造参数覆盖）：
        # - damage（默认，2026-10-05 用户决策：战损为唯一目标）：
        #   终局 = 剩余 HP / max_hp（胜）/ 0（败）；进行中恒 0。
        #   保不住血自然会输，战损低与获胜天然一致；无每步 shaping
        # - sparse_pm1：胜 +1 / 负 -1（EXP-01 首版对照口径，保留供
        #   奖励对比实验）
        if not terminated:
            reward = 0.0
        elif self.reward_mode == REWARD_SPARSE_PM1:
            reward = 1.0 if bc.won else (-1.0 if bc.outcome == Outcome.PLAYER_LOSS else 0.0)
        else:  # REWARD_DAMAGE
            reward = bc.player.hp / bc.player.max_hp if bc.won else 0.0
        return self._get_obs(), reward, terminated, truncated, self._get_info()

    def _engine_fallback(self, bc: BattleContext) -> None:
        """引擎拒绝 mask 合法动作时的兜底（保证环境永不卡死）：
        选卡 → 合法默认选择提交；其余挂起/玩家态 → 尽量推进到回合结束。"""
        if bc.input_state == InputState.CARD_SELECT and bc.card_select_info is not None:
            info = bc.card_select_info
            default = (
                [] if info.can_pick_zero else list(range(min(info.pick_count, len(info.candidates))))
            )
            bc.choose_cards(default)
        elif bc.input_state == InputState.SCRY:
            bc.choose_scry(0)
        elif bc.input_state == InputState.PLAYER_NORMAL and not bc.over:
            bc.end_turn()

    # ---- 动作掩码 ----

    def _card_playable(self, bc: BattleContext, inst) -> bool:
        """镜像 play_card 的出牌资格闸（全部由玩家可见状态决定）：
        不可打出（Blue Candle/Medical Kit 解锁）、打出条件（Clash）、
        缠绕拦攻击、遗物限制（VELVET_CHOKER）。批次 5a 修复：原先
        Wound/Burn/Dazed 等 unplayable 牌被 mask 误标合法。
        """
        card = inst.card
        if card.unplayable and not bc.relics.makes_unplayable_playable(inst):
            return False
        if card.play_condition is not None and not card.play_condition(bc, inst):
            return False
        if bc.player.statuses.has(PlayerStatus.ENTANGLED) and card.ctype == "Attack":
            return False
        if not bc.relics.check_play_allowed(bc, inst):
            return False
        return True

    def action_masks(self) -> np.ndarray:
        """合法动作掩码（sb3-contrib MaskablePPO 约定的入口）。

        三种输入挂起态互斥，各开各的动作段：
        - PLAYER_NORMAL：END_TURN + 出牌槽×目标 + 药水
        - CARD_SELECT：SELECT(窗口槽，再选取消) + CONFIRM（空选择需
          can_pick_zero；超出 pick_count 需 can_pick_any_number）
        - SCRY：保留堆顶 k 张（k ≤ min(张数, SCRY_KEEP_MAX)）
        战斗结束/EXECUTING → 全 False。
        """
        mask = np.zeros(N_ACTIONS, dtype=bool)
        bc = self.bc
        if bc is None or bc.over:
            return mask
        self._refresh_select_state()
        if bc.input_state == InputState.PLAYER_NORMAL:
            mask[ACTION_END_TURN] = True
            # 与引擎 play_card 的自动指向条件严格一致（monster_count==1 且可指向）
            single = (
                bc.monsters.monster_count == 1
                and bc.monsters.monsters[0].is_targetable()
            )
            for i, inst in enumerate(bc.cards.hand[:N_HAND_SLOTS]):
                if inst.cost > bc.player.energy or not self._card_playable(bc, inst):
                    continue
                if not inst.card.needs_target:
                    mask[HAND_SLOT_BASE + i] = True
                elif single:
                    mask[HAND_SLOT_BASE + i] = True
                else:
                    for j, m in enumerate(bc.monsters.monsters[:N_TARGET_SLOTS]):
                        if m.is_targetable():
                            mask[TARGETED_BASE + i * N_TARGET_SLOTS + j] = True
            self._mask_potions(bc, mask)
        elif bc.input_state == InputState.CARD_SELECT:
            info = bc.card_select_info
            assert info is not None
            # 选中容量：any_number 上界 = 窗口长度（引擎只查 pick_count 上界）
            capacity = (
                len(self._select_window) if info.can_pick_any_number else info.pick_count
            )
            for i in range(len(self._select_window)):
                # 单调选择（2026-10-08）：已选槽不可再选——toggle 取消
                # 语义会被确定性策略锁成 SELECT 往复死循环（Boss 退火
                # (50,100) 级 21/30 卡死实录）。选卡子 MDP 保持 DAG，
                # 结构上排除吸收态；代价 = 不可反悔（近似，记录于
                # DESIGN.md §5.4）
                if i not in self._select_chosen and len(self._select_chosen) < capacity:
                    mask[SELECT_BASE + i] = True
            n = len(self._select_chosen)
            if n == 0:
                mask[SELECT_CONFIRM] = bool(info.can_pick_zero)
            else:
                mask[SELECT_CONFIRM] = info.can_pick_any_number or n <= info.pick_count
        elif bc.input_state == InputState.SCRY:
            n = min(len(bc.scry_cards), SCRY_KEEP_MAX)
            for k in range(n + 1):
                mask[SCRY_BASE + k] = True
        return mask

    def _mask_potions(self, bc: BattleContext, mask: np.ndarray) -> None:
        """药水动作段（仅 PLAYER_NORMAL）：镜像 use_potion 的校验闸——
        auto_only 不可手动使用、escape_only 在 Boss 遭遇禁用、choices
        （姿态药水）走选择段、targeting 药水需存活目标（单怪可自动指向）。
        """
        single = (
            bc.monsters.monster_count == 1
            and bc.monsters.monsters[0].is_targetable()
        )
        for s, pd in enumerate(bc.player.potions[:N_POTION_SLOTS]):
            if pd is None:
                continue
            if pd.auto_only:
                continue
            if pd.escape_only and bc.encounter in BOSS_ENCOUNTERS:
                continue
            if pd.choices:
                for c in range(len(STANCE_CHOICES)):
                    mask[POTION_STANCE_BASE + s * 2 + c] = True
                continue
            if pd.targeting:
                if single:
                    mask[POTION_BASE + s * 6] = True
                for j, m in enumerate(bc.monsters.monsters[:N_TARGET_SLOTS]):
                    if m.is_targetable():
                        mask[POTION_BASE + s * 6 + 1 + j] = True
            else:
                mask[POTION_BASE + s * 6] = True

    # ---- 观测与 info ----

    def _get_obs(self) -> np.ndarray:
        """从引擎状态构造观测（只用 DESIGN.md §4.1 白名单信息）。"""
        bc = self.bc
        assert bc is not None
        self._refresh_select_state()  # 展示窗口段依赖同步的选卡状态
        obs = np.zeros(OBS_DIM, dtype=np.int32)
        p = bc.player

        obs[O_PLAYER + 0] = min(p.hp, CAP_HP)
        obs[O_PLAYER + 1] = min(p.max_hp, CAP_HP)
        obs[O_PLAYER + 2] = min(p.block, CAP_BLOCK)
        obs[O_PLAYER + 3] = min(p.energy, CAP_ENERGY)
        # 能量比（百分比）：让策略不必知道「满能量是几点」这一规则量
        obs[O_PLAYER + 4] = min(round(100 * p.energy / ENERGY_PER_TURN), CAP_ENERGY_RATIO)
        obs[O_PLAYER + 5] = min(len(bc.cards.hand), N_HAND_SLOTS)
        obs[O_PLAYER + 6] = min(p.gold, CAP_GOLD)
        obs[O_CLASS + CHARACTERS.index(self.character)] = 1

        for k, s in enumerate(PLAYER_STATUS_ORDER):
            obs[O_PSTAT + k] = min(p.statuses.get(s), CAP_STATUS)

        # 姿态（观者）：one-hot；MANTRA 层数已在 O_PSTAT（PlayerStatus）
        obs[O_STANCE + STANCE_ORDER.index(p.stance)] = 1

        # 充能球（故障）：orbs[0] 最老（先被 evoke），槽序对玩家可见；
        # FOCUS 加成在 O_PSTAT，暗球存层是全场共享计数（引擎口径）
        for i, orb in enumerate(p.orbs[:N_ORB_SLOTS]):
            b = O_ORB + i * _N_ORB_FEAT
            obs[b] = 1
            obs[b + 1 + ORB_ORDER.index(orb)] = 1
        b = O_ORB + N_ORB_SLOTS * _N_ORB_FEAT
        obs[b] = min(p.orb_slots, CAP_STATUS)
        obs[b + 1] = min(p.dark_stacks, CAP_STATUS)

        # 手牌：槽级身份 one-hot（2k 基础 / 2k+1 升级）+ 聚合特征
        # （类型/费/可打性），构成计数给全手牌概览。手牌顺序对玩家
        # 可见（UI 顺序），编码顺序合法；四堆（下段）则只允许无序计数。
        for i, inst in enumerate(bc.cards.hand[:N_HAND_SLOTS]):
            b = O_HAND_SLOT + i * _N_SLOT_FEAT
            idx = card_vocab_index(inst.card)
            if idx is not None:
                obs[b + _S_ONEHOT + idx + (1 if inst.upgraded else 0)] = 1
            obs[b + _S_OCC] = 1
            ctype = {"Attack": _S_ATTACK, "Skill": _S_SKILL, "Power": _S_POWER}.get(inst.card.ctype)
            if ctype is not None:
                obs[b + ctype] = 1
            # X 费模板 cost=-1（"全能量"）：钳 0 编码（X 语义由 x_cost
            # 决定，费用维不承载它；Box 下界 0）
            obs[b + _S_COST] = min(max(inst.cost, 0), CAP_ENERGY)
            obs[b + _S_TARGET] = 1 if inst.card.needs_target else 0
            obs[b + _S_UPGRADED] = 1 if inst.upgraded else 0
            obs[b + _S_UNPLAYABLE] = 1 if inst.card.unplayable else 0
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
            # ——扩怪时重跑 scripts/gen_vocab.py。
            # 消融模式（species_shuffle）：查的是局内乱序映射——观测
            # 位与真种类完全无关
            spec = (self._species_map or MONSTER_INDEX).get(m.name)
            if spec is not None:
                obs[b + _E_SPECIES + spec] = 1

        # 四堆构成（无序计数）：抽/弃/消耗/保留(limbo)的顺序都是黑名单
        # 信息（§4.2），这里只数「每种卡剩几张」——物理上不可能泄露顺序。
        # limbo 是回合末保留牌的暂存区，上回合就在手里，构成对玩家可见
        _count_into(obs, O_PILE_DRAW, bc.cards.draw_pile)
        _count_into(obs, O_PILE_DISCARD, bc.cards.discard_pile)
        _count_into(obs, O_PILE_EXHAUST, bc.cards.exhaust_pile)
        _count_into(obs, O_PILE_LIMBO, bc.cards.limbo)

        # 战斗内遗物：multi-hot + 公开计数器（笔尖/赌博筹码/快乐花等
        # UI 可见的计数）。计数器语义因遗物而异，透传截断；负值钳 0
        # （如 ANCIENT_TEA_SET 用 counter=-2 表「休息过」的场景预设，
        # 观测 Box 下界为 0，非负语义由 multi-hot 之外无信息表达）
        for rid in bc.relics.relics:
            obs[O_RELIC + _R_ONEHOT + rid.value] = 1
            obs[O_RELIC + _R_COUNTER + rid.value] = max(
                0, min(bc.relics.counter(rid), CAP_RELIC_COUNTER)
            )

        # 药水栏：槽位占用 + 药水种类 one-hot（喝药动作段是批次 5b）
        for i, pd in enumerate(bc.player.potions[:N_POTION_SLOTS]):
            if pd is None:
                continue
            b = O_POTION + i * _N_POTION_FEAT
            obs[b + _P_OCC] = 1
            pi = POTION_INDEX.get(pd.pid)
            if pi is not None:
                obs[b + _P_ONEHOT + pi] = 1

        obs[O_TURN] = min(bc.turn, CAP_TURN)

        # 输入状态 one-hot（挂起态是动作分支条件；战斗结束后状态不定，
        # 不在固定序里则该段全零——episode 已终止，无决策意义）
        try:
            obs[O_MODE + INPUT_STATE_ORDER.index(bc.input_state)] = 1
        except ValueError:
            pass

        # 展示窗口（对玩家可见的「当前正在选择的牌」）：
        # - CARD_SELECT：稳定词表位序的候选（防 §4.2 堆序泄露）
        # - SCRY：堆顶序检视牌（检视界面本来就按序展示，合法）
        if bc.input_state == InputState.CARD_SELECT:
            shown = self._select_window
        elif bc.input_state == InputState.SCRY:
            shown = bc.scry_cards[:N_SELECT_WINDOW]
        else:
            shown = []
        for i, inst in enumerate(shown[:N_SELECT_WINDOW]):
            idx = card_vocab_index(inst.card)
            if idx is not None:
                obs[O_PRESENT + i * CARD_VOCAB_SIZE + idx + (1 if inst.upgraded else 0)] = 1
            f = O_PRESENT_FEAT + i * _N_PRESENT_FEAT
            obs[f + _PS_OCC] = 1
            ctype = {
                "Attack": _PS_ATTACK,
                "Skill": _PS_SKILL,
                "Power": _PS_POWER,
            }.get(inst.card.ctype)
            if ctype is not None:
                obs[f + ctype] = 1
            obs[f + _PS_COST] = min(max(inst.cost, 0), CAP_ENERGY)
            obs[f + _PS_UPGRADED] = 1 if inst.upgraded else 0
        # 自回归选中态（仅 CARD_SELECT 有意义；选中位 = 窗口位）
        for w in self._select_chosen:
            obs[O_PRESENT_SEL + w] = 1
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
            "character": self.character,
        }

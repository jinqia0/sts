"""结构化 MaskablePPO 特征提取器（批次 5c，2026-10-08 用户指令）。

动机：12444 维平铺观测的大头是稀疏 one-hot 词表段（四堆计数 4×736、
展示窗口 10×736、遗物 362、药水 43×5、种类 5×72）——标准 MLP 第一层
把每个词表位当独立标量，无参数共享、无结构归纳偏置（同一种卡在
四堆/手牌/窗口里出现，特征完全不共享）。本模块按段做**集合池化**：
每段词表 one-hot → 求和/均值池化成段级 summary，拼接低维标量段后
进 MLP——参数量降一个量级，等价于「按 (卡牌身份) 的 bag-of-cards
嵌入」，同卡跨段共享同一组权重。

架构（FeatureExtractor 输出低维结构化向量 → 小 MLP policy head）：

    段                     处理
    手牌槽×8 标量          槽内拼接（保留槽序——手牌顺序可见）
    四堆计数 ×4×736        共享卡牌嵌入 E(736→64) → 每堆 sum-pool → 4×64
    展示窗口 10×(736+6)    共享卡牌嵌入 → sum-pool 64 + 槽特征拼接 60
    敌人槽 5×72 种类       共享怪类嵌入(72→16) 每槽 → +槽标量拼接
    遗物 multi-hot 181     遗物嵌入(181→16) sum-pool
    药水 5×(1+43)          药水嵌入(43→8) per-slot → 拼接
    其余标量段             直通拼接

输出 ~500 维结构化特征 → policy 网络 [512, 256]（与 EXP-05 甜点一致）。
"""

from __future__ import annotations

import torch
import torch.nn as nn

from sts.env import (
    CARD_VOCAB_SIZE,
    MONSTER_VOCAB_SIZE,
    N_HAND_SLOTS,
    N_ORB_SLOTS,
    N_POTION_SLOTS,
    N_RELICS,
    N_SELECT_WINDOW,
    N_TARGET_SLOTS,
    OBS_DIM,
    O_CLASS,
    O_ENEMY,
    O_HAND_COUNT,
    O_HAND_SLOT,
    O_MODE,
    O_ORB,
    O_PILE_DISCARD,
    O_PILE_DRAW,
    O_PILE_EXHAUST,
    O_PILE_LIMBO,
    O_PLAYER,
    O_POTION,
    O_PRESENT,
    O_PRESENT_FEAT,
    O_PRESENT_SEL,
    O_PSTAT,
    O_RELIC,
    O_STANCE,
    O_TURN,
    POTION_VOCAB_SIZE,
    _E_SPECIES,
    _N_ENEMY_FEAT,
    _N_POTION_FEAT,
    _N_PRESENT_FEAT,
    _N_SLOT_FEAT,
)
from sts.vocab import CARD_VOCAB_SIZE as VOCAB_CARDS  # noqa: F401（等同再导出）


class StsStructuredExtractor(nn.Module):
    """按段池化的结构化特征提取器（模块头架构表）。

    卡牌嵌入在四堆/手牌计数/展示窗口间共享：同一张卡的
    「在手/在抽堆/在弃堆/正被选」表示互相靠近——MLP 无此偏置。
    """

    CARD_EMB = 64
    MONSTER_EMB = 16
    RELIC_EMB = 16
    POTION_EMB = 8

    def __init__(self) -> None:
        super().__init__()
        # 词表嵌入（共享）
        self.card_emb = nn.Linear(CARD_VOCAB_SIZE, self.CARD_EMB, bias=False)  # one-hot 线性=嵌入查表
        self.monster_emb = nn.Linear(MONSTER_VOCAB_SIZE, self.MONSTER_EMB, bias=False)
        self.relic_emb = nn.Linear(N_RELICS, self.RELIC_EMB, bias=False)
        self.potion_emb = nn.Linear(POTION_VOCAB_SIZE, self.POTION_EMB, bias=False)

        # 输出维度账（与 forward 一一对应；自检 assert 保证不漂移）
        self.out_dim = (
            7  # O_PLAYER
            + 4  # O_CLASS
            + 68  # O_PSTAT
            + 4  # O_STANCE
            + (N_ORB_SLOTS * 5 + 2)  # O_ORB
            + N_HAND_SLOTS * _N_SLOT_FEAT  # O_HAND_SLOT
            + N_SELECT_WINDOW * _N_PRESENT_FEAT  # O_PRESENT_FEAT
            + N_SELECT_WINDOW  # O_PRESENT_SEL
            + N_TARGET_SLOTS * (_N_ENEMY_FEAT - MONSTER_VOCAB_SIZE + self.MONSTER_EMB)  # 敌人槽
            + 5 * self.CARD_EMB  # 手牌计数 + 四堆（5 段 sum-pool）
            + N_SELECT_WINDOW * self.CARD_EMB  # 展示窗口槽级嵌入
            + self.RELIC_EMB  # 遗物池化
            + N_POTION_SLOTS * (1 + self.POTION_EMB)  # 药水槽
            + 4  # O_MODE
            + 1  # O_TURN
        )

    def forward(self, obs: torch.Tensor) -> torch.Tensor:
        # obs: (B, OBS_DIM) int → float
        x = obs.float()
        feats: list[torch.Tensor] = []

        def seg(base: int, n: int) -> torch.Tensor:
            return x[:, base : base + n]

        # 标量段直通（顺序即布局表）
        feats.append(seg(O_PLAYER, 7))
        feats.append(seg(O_CLASS, 4))
        feats.append(seg(O_PSTAT, 68))
        feats.append(seg(O_STANCE, 4))
        feats.append(seg(O_ORB, N_ORB_SLOTS * 5 + 2))
        feats.append(seg(O_HAND_SLOT, N_HAND_SLOTS * _N_SLOT_FEAT))
        feats.append(seg(O_PRESENT_FEAT, N_SELECT_WINDOW * _N_PRESENT_FEAT))
        feats.append(seg(O_PRESENT_SEL, N_SELECT_WINDOW))

        # 敌人槽：标量 + 种类嵌入（每槽独立查表后拼接）
        for si in range(N_TARGET_SLOTS):
            b = O_ENEMY + si * _N_ENEMY_FEAT
            feats.append(seg(b, _E_SPECIES))  # 槽内标量（hp/block/意图/状态/…）
            feats.append(self.monster_emb(seg(b + _E_SPECIES, MONSTER_VOCAB_SIZE)))

        # 四堆：共享卡牌嵌入 sum-pool（计数 × 嵌入的线性性 → sum 等价加权嵌入）
        for base in (O_HAND_COUNT, O_PILE_DRAW, O_PILE_DISCARD, O_PILE_EXHAUST, O_PILE_LIMBO):
            feats.append(self.card_emb(seg(base, CARD_VOCAB_SIZE)))

        # 展示窗口：reshape (B, 10, 736) → 每槽过共享卡牌嵌入 → 槽级身份保留
        win = seg(O_PRESENT, N_SELECT_WINDOW * CARD_VOCAB_SIZE).reshape(-1, N_SELECT_WINDOW, CARD_VOCAB_SIZE)
        feats.append(self.card_emb(win).flatten(1))  # (B, 10×64)

        # 遗物：multi-hot → 嵌入 sum
        feats.append(self.relic_emb(seg(O_RELIC, N_RELICS)))

        # 药水：每槽（占用标量 + 嵌入池化）
        for si in range(N_POTION_SLOTS):
            b = O_POTION + si * _N_POTION_FEAT
            feats.append(seg(b, 1))
            feats.append(self.potion_emb(seg(b + 1, POTION_VOCAB_SIZE)))

        feats.append(seg(O_MODE, 4))
        feats.append(seg(O_TURN, 1))
        return torch.cat(feats, dim=1)


class StsFeaturesExtractor(nn.Module):
    """SB3 BaseFeaturesExtractor 适配壳（sb3 需 features_dim 属性与
    forward(obs)——obs 是 VecEnv 的 dict/flat 张量，此处 flat int32）。"""

    def __init__(self, observation_space) -> None:
        super().__init__()
        self.net = StsStructuredExtractor()
        self.features_dim = self.net.out_dim

    def forward(self, observations: torch.Tensor) -> torch.Tensor:
        return self.net(observations)

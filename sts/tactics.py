"""微场景战术规则评测（EXP-15，2026-10-09）。

最小训练设定（固定初始牌组 + 弱怪池 + 纯战损终局奖励）下，检验
策略是否学到 4 条简单战术规则。微场景 = 引擎级脚本局面：

- 怪：jaw_worm 单怪（弱怪池成员，种类 one-hot 在训练词表内），意图
  经 set_move 覆盖为指定招式（咆哮=强化自己 / 自定伤害的重咬）
- 手牌：写死为指定卡名（初始牌组子集，顺序即槽位序——手牌顺序
  玩家可见，合法）
- 抽牌堆：初始牌组剩余构成的实例原样放回，洗牌顺序随种子变化
  （顺序对策略不可见——§4.3 审计不变式，多种子观测逐位一致）
- 能量 3、玩家 80 血；场景 4 怪物 HP 覆盖为 18

四条规则与判定（用户 2026-10-09 设定，通过线 ≥90% 种子符合预期）：

1. attack_priority   怪无攻击意图 → 攻击牌优先于防御
                     （2 打击全出且先于任何防御）
2. bash_first        有痛击时先出痛击再出打击，让打击吃到易伤加成
3. block_then_attack 来袭伤害已被格挡覆盖 → 剩余能量全用于攻击
                     （恰好 1 防御 + 2 打击；防御先出后出均可）
                     ——注意场景 3 里防御 5 恰好盖住 5 伤，多防浪费能量
4. lethal_over_defend 本回合可击杀 → 即使怪是攻击意图也直接杀
                     （3 打击 = 18 伤恰好带走 18 血，0 防御）

信息边界：全部设定只用白名单信息（手牌/意图/HP 均玩家可见），
构造路径不改引擎、不触碰 RNG 状态语义（洗牌用引擎自己的流）。
"""

from __future__ import annotations

from dataclasses import dataclass

from sts.content.monsters import JawWorm, MoveDef
from sts.env import ACTION_END_TURN, HAND_SLOT_BASE, StsBattleEnv, TARGETED_BASE

STRIKE, DEFEND, BASH = "Strike", "Defend", "Bash"

# 怪物意图（jaw_worm 招式表内取或按 Chomp 模板自定伤害——
# take_turn 伤害是硬编码，但评测在玩家回合结束即停，不会执行到）
INTENT_BUFF = JawWorm.BELLOW
INTENT_ATTACK_5 = MoveDef("Chomp", "重咬", "attack", base_damage=5)
INTENT_ATTACK_8 = MoveDef("Chomp", "重咬", "attack", base_damage=8)


@dataclass(frozen=True)
class TacticsScenario:
    """一个微场景的全部配置。"""

    key: str
    rule: str  # 检验的规则（报告用）
    hand: tuple[str, ...]  # 手牌卡名（顺序即槽位序）
    intent: MoveDef  # 覆盖怪当前意图
    expectation: str  # 期望行为（报告用）
    monster_hp: int = 42  # 固定（jaw_worm 抽样区间中值）——观测对种子不变
    player_hp: int = 80


TACTICS_SCENARIOS: dict[str, TacticsScenario] = {
    "attack_priority": TacticsScenario(
        key="attack_priority",
        rule="规则1：无攻击意图时攻击优先于防御",
        hand=(STRIKE, STRIKE, DEFEND, DEFEND, DEFEND),
        intent=INTENT_BUFF,
        expectation="Strike, Strike, END（3 能量 2 打 3 防）",
    ),
    "bash_first": TacticsScenario(
        key="bash_first",
        rule="规则2：先痛击后打击，打击吃易伤加成",
        hand=(STRIKE, STRIKE, DEFEND, DEFEND, BASH),
        intent=INTENT_BUFF,
        expectation="Bash, Strike, END（3 能量 2 打 2 防 1 痛击）",
    ),
    "block_then_attack": TacticsScenario(
        key="block_then_attack",
        rule="规则3：格挡盖住来袭后剩余能量用于攻击",
        hand=(STRIKE, STRIKE, STRIKE, DEFEND, DEFEND),
        intent=INTENT_ATTACK_5,
        expectation="Defend ×1 + Strike ×2（5 伤恰好 1 防；防御先后均可）",
    ),
    "lethal_over_defend": TacticsScenario(
        key="lethal_over_defend",
        rule="规则4：可击杀回合直接击杀，不防御",
        hand=(STRIKE, STRIKE, STRIKE, DEFEND, DEFEND),
        intent=INTENT_ATTACK_8,
        monster_hp=18,  # 3 打击 6×3 = 18 恰好斩杀（用户 2026-10-09 确认）
        expectation="Strike ×3（18 伤斩杀），Defend 0 张",
    ),
}


def build_scenario(spec: TacticsScenario, seed: int) -> StsBattleEnv:
    """构造脚本局面：reset 后覆写手牌/意图/血量。

    实例全部来自引擎开局的真实牌堆（手牌 5 + 抽牌堆 5 = 初始 10 张），
    按卡名重新分配——不新建实例，unique_id 语义不变。
    """
    env = StsBattleEnv(encounter="jaw_worm")
    env.reset(seed=seed)
    bc = env.bc
    by_name: dict[str, list] = {}
    for inst in list(bc.cards.hand) + list(bc.cards.draw_pile):
        by_name.setdefault(inst.card.name, []).append(inst)
    missing = [n for n in spec.hand if not by_name.get(n)]
    if missing:
        raise AssertionError(f"开局牌堆凑不出手牌 {spec.hand}（缺 {missing}）")
    hand = [by_name[n].pop(0) for n in spec.hand]
    rest = [inst for lst in by_name.values() for inst in lst]
    bc.rngs.shuffle.shuffle(rest)  # 顺序随种子变（对策略不可见）
    bc.cards.hand = hand
    bc.cards.draw_pile = rest
    bc.player.energy = 3
    if spec.player_hp != 80:
        bc.player.hp = spec.player_hp
    m = bc.monsters.monsters[0]
    m.hp = spec.monster_hp
    m.max_hp = spec.monster_hp  # 显式覆盖后同步上界，保持 hp ≤ max_hp
    m.set_move(spec.intent)
    return env


def describe_action(env: StsBattleEnv, action: int) -> str:
    """动作 id → 人读名（END / 卡名 / 卡名@目标槽）。"""
    if action == ACTION_END_TURN:
        return "END"
    bc = env.bc
    if HAND_SLOT_BASE <= action < HAND_SLOT_BASE + len(bc.cards.hand):
        return bc.cards.hand[action - HAND_SLOT_BASE].card.name
    i = (action - TARGETED_BASE) // 5
    j = (action - TARGETED_BASE) % 5
    return f"{bc.cards.hand[i].card.name}@{j}"


def rollout(env: StsBattleEnv, policy, max_actions: int = 30) -> tuple[list[str], bool]:
    """从脚本局面推进到玩家回合结束，返回 (动作名序列, 怪是否已死)。

    policy 签名与 baselines 一致：policy(env) -> int（读 action_masks）。
    终止条件：END_TURN / 战斗结束 / 截断（max_actions 防御性上限——
    正常一回合 ≤ 手牌数 + 1 步）。
    """
    seq: list[str] = []
    for _ in range(max_actions):
        action = policy(env)
        seq.append(describe_action(env, int(action)))
        _obs, _r, term, trunc, _info = env.step(int(action))
        if seq[-1] == "END" or term or trunc:
            break
    monster_dead = not env.bc.monsters.monsters[0].alive
    return seq, monster_dead


def _base_names(seq: list[str]) -> list[str]:
    return [s.split("@")[0] for s in seq]


def check_scenario(spec: TacticsScenario, seq: list[str], monster_dead: bool) -> tuple[bool, str]:
    """动作序列 vs 期望规则。返回 (是否通过, 诊断摘要)。"""
    names = _base_names(seq)
    strikes = names.count(STRIKE)
    defends = names.count(DEFEND)
    if spec.key == "attack_priority":
        # 2 打击全出，且都先于任何防御（防御若在打击前出 = 优先级反了）
        first_defend = names.index(DEFEND) if DEFEND in names else len(names)
        last_strike = max((i for i, n in enumerate(names) if n == STRIKE), default=-1)
        ok = strikes == 2 and last_strike < first_defend
        detail = f"Strike×{strikes} Defend×{defends}"
    elif spec.key == "bash_first":
        # 痛击在任何打击之前出（其后至少还有 1 张打击吃到易伤）
        bash_pos = names.index(BASH) if BASH in names else None
        first_strike = names.index(STRIKE) if STRIKE in names else None
        ok = bash_pos is not None and first_strike is not None and bash_pos < first_strike
        detail = f"Strike×{strikes} Defend×{defends} Bash×{names.count(BASH)}"
    elif spec.key == "block_then_attack":
        # 恰好 1 防御（5 挡 5）+ 2 打击（剩余能量全攻）
        ok = defends == 1 and strikes == 2
        detail = f"Strike×{strikes} Defend×{defends}"
    elif spec.key == "lethal_over_defend":
        # 3 打击斩杀，0 防御，怪确实死了
        ok = strikes == 3 and defends == 0 and monster_dead
        detail = f"Strike×{strikes} Defend×{defends} dead={monster_dead}"
    else:
        raise ValueError(f"未知微场景：{spec.key}")
    return ok, detail


def evaluate_policy(policy, spec: TacticsScenario, seeds: range) -> dict:
    """单场景多种子统计。观测对种子不变（§4.3），随机性只来自策略
    自身采样——随机策略经 env.np_random、模型经 predict 采样，
    通过率即「策略概率质量落在预期行为上」的估计。"""
    results = []
    for s in seeds:
        env = build_scenario(spec, s)
        seq, monster_dead = rollout(env, policy)
        ok, detail = check_scenario(spec, seq, monster_dead)
        results.append({"seed": s, "ok": ok, "seq": seq, "detail": detail})
    n_pass = sum(r["ok"] for r in results)
    return {
        "key": spec.key,
        "rule": spec.rule,
        "expectation": spec.expectation,
        "pass": n_pass,
        "total": len(results),
        "pass_rate": n_pass / len(results) if results else 0.0,
        "results": results,
    }


def evaluate_all(policy, seeds: range = range(30)) -> list[dict]:
    """全部 4 个微场景。"""
    return [evaluate_policy(policy, spec, seeds) for spec in TACTICS_SCENARIOS.values()]


def format_report(reports: list[dict], name: str, show_seqs: int = 3) -> str:
    """人读报告：通过率表 + 前 N 个种子动作序列（失败优先展示）。"""
    lines = [f"==== {name}（微场景战术规则）===="]
    for r in reports:
        verdict = "PASS" if r["pass_rate"] >= 0.9 else "FAIL"
        lines.append(
            f"  [{verdict}] {r['key']}  {r['pass']}/{r['total']}（{r['pass_rate']:.0%}）"
            f"  {r['rule']}"
        )
        lines.append(f"         期望：{r['expectation']}")
        shown = [x for x in r["results"] if not x["ok"]][:show_seqs] or r["results"][:show_seqs]
        for x in shown:
            mark = "✓" if x["ok"] else "✗"
            lines.append(f"         {mark} seed={x['seed']}: {' → '.join(x['seq'])}  [{x['detail']}]")
    return "\n".join(lines)


def make_model_policy(model_path: str, deterministic: bool = False):
    """MaskablePPO → policy(env)。懒加载深度学习栈（webapp 同款）。"""
    from sb3_contrib import MaskablePPO

    m = MaskablePPO.load(model_path)

    def policy(env: StsBattleEnv) -> int:
        action, _ = m.predict(
            env._get_obs(), deterministic=deterministic, action_masks=env.action_masks()
        )
        return int(action)

    return policy

"""人机 CLI：铁甲战士初始牌组 vs 当前注册的任意遭遇。

用法：
    uv run python -m sts.cli [--seed N]

交互：输入手牌编号出牌（唯一敌人时攻击牌自动指向它），e 结束回合，q 认输。
选卡界面（CARD_SELECT）按提示输入候选编号（多选逗号分隔，空行跳过可选段）。
"""

from __future__ import annotations

import argparse

from sts.combat import BattleContext
from sts.combat.types import InputState, MonsterStatus, PlayerStatus

STATUS_ZH = {
    PlayerStatus.STRENGTH: "力量",
    PlayerStatus.DEXTERITY: "敏捷",
    PlayerStatus.VULNERABLE: "易伤",
    PlayerStatus.WEAK: "虚弱",
    PlayerStatus.FRAIL: "脆弱",
    PlayerStatus.METALLICIZE: "金属化",
    PlayerStatus.RAGE: "怒火",
    PlayerStatus.ARTIFACT: "神器",
    MonsterStatus.STRENGTH: "力量",
    MonsterStatus.VULNERABLE: "易伤",
    MonsterStatus.WEAK: "虚弱",
    MonsterStatus.RITUAL: "仪式",
    MonsterStatus.METALLICIZE: "金属化",
    MonsterStatus.ANGRY: "愤怒",
    MonsterStatus.CURL_UP: "蜷缩",
    MonsterStatus.SHACKLED: "枷锁",
    MonsterStatus.ARTIFACT: "神器",
}


def _render_powers(statuses) -> str:
    if not statuses.items():
        return ""
    return "  ".join(f"{STATUS_ZH.get(s, s.name)} {n}" for s, n in statuses.items())


def _render_intent(bc: BattleContext, enemy) -> str:
    move = enemy.current_move
    if move.kind == "attack":
        dmg = bc.calculate_monster_damage(enemy, move.base_damage)
        return f"攻击 {dmg}"
    return f"{move.zh}（{move.intent_text}）"


def _render(bc: BattleContext) -> None:
    print("=" * 56)
    print(f"回合 {bc.turn}")
    print("-" * 56)
    for enemy in bc.monsters.monsters:
        if not enemy.alive or enemy.is_escaping:
            continue
        print(f"  {enemy.display_name}  HP {enemy.hp}/{enemy.max_hp}  格挡 {enemy.block}")
        powers = _render_powers(enemy.statuses)
        if powers:
            print(f"    [已生效] {powers}")
        print(f"    意图: {_render_intent(bc, enemy)}")
    p = bc.player
    print("-" * 56)
    print(f"你 (Ironclad)  HP {p.hp}/{p.max_hp}  格挡 {p.block}  能量 {p.energy}/3  金币 {p.gold}")
    powers = _render_powers(p.statuses)
    if powers:
        print(f"  [已生效] {powers}")
    print("手牌:")
    for i, inst in enumerate(bc.cards.hand, 1):
        card = inst.card
        print(f"  [{i}] {card.zh}({card.name})  [{card.ctype}/{inst.cost}费]  {card.text}")
    print("-" * 56)


def _handle_card_select(bc: BattleContext) -> None:
    """CARD_SELECT 挂起时提示选卡（多选逗号分隔；可空选时空行跳过）。"""
    info = bc.card_select_info
    assert info is not None
    print(f"选卡：{info.prompt or '请选择卡牌'}")
    for i, inst in enumerate(info.candidates):
        print(f"  [{i}] {inst.card.zh}({inst.card.name})  {inst.card.text}")
    tip = "回车跳过" if info.can_pick_zero else "至少选 1 张"
    try:
        line = input(f"> 候选编号（逗号分隔，{tip}）: ").strip()
    except EOFError:
        print("(输入结束，选第 1 张)")
        bc.choose_cards([0])
        return
    if not line:
        if info.can_pick_zero:
            bc.choose_cards([])
        else:
            print("  本次不可跳过，自动选第 1 张。")
            bc.choose_cards([0])
        return
    try:
        indices = [int(x) for x in line.replace("，", ",").split(",") if x.strip()]
        bc.choose_cards(indices)
    except (ValueError, IndexError) as e:
        print(f"  选择无效（{e}），自动选第 1 张。")
        bc.choose_cards([0])


def _flush_log(bc: BattleContext, printed: list[int]) -> None:
    for i in range(printed[0], len(bc.log)):
        print(f"  >> {bc.log[i]}")
    printed[0] = len(bc.log)


def main() -> None:
    parser = argparse.ArgumentParser(description="Slay the Spire 最小战斗：Ironclad vs Cultist")
    parser.add_argument("--seed", type=int, default=None, help="战斗种子（默认随机）")
    parser.add_argument("--encounter", default="cultist", help="遭遇名（默认 cultist）")
    args = parser.parse_args()

    bc = BattleContext(seed=args.seed, encounter=args.encounter)
    printed = [0]
    print(f"战斗开始：你 (Ironclad, 初始牌组) vs {args.encounter}")
    _flush_log(bc, printed)

    while not bc.over:
        _render(bc)
        if bc.input_state == InputState.CARD_SELECT:
            _handle_card_select(bc)
            _flush_log(bc, printed)
            continue
        try:
            line = input("> 出牌编号 / e=结束回合 / q=认输: ").strip()
        except EOFError:
            print("(输入结束，退出)")
            return
        if line == "q":
            print("你选择了逃跑（认输）。")
            return
        if line == "e":
            bc.end_turn()
            _flush_log(bc, printed)
            continue
        if line.isdigit():
            try:
                bc.play_card(int(line) - 1)
                _flush_log(bc, printed)
            except ValueError as e:
                print(f"  无法出牌: {e}")
            continue
        print("  无效输入：请输入手牌编号、e 或 q。")

    _render(bc)
    _flush_log(bc, printed)
    if bc.won:
        print(f"胜利！剩余 HP {bc.player.hp}/{bc.player.max_hp}，用时 {bc.turn} 回合。")
    else:
        print(f"战败……第 {bc.turn} 回合倒下。")


if __name__ == "__main__":
    main()

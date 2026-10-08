"""？房 roll / 事件选择 / 事件效果测试（Phase 3a）。"""

from __future__ import annotations

import json
import pathlib

from sts.combat.relics import RelicId
from sts.content.cards import ironclad as cards_ironclad
from sts.content.cards.curses import REGRET
from sts.content.cards.ironclad import DEFEND, STRIKE
from sts.overworld.state import DeckCard
from sts.content.events import (
    ACT1_EVENTS,
    ACT1_ONETIMES,
    ACT1_SHRINES,
    EventContext,
)
from sts.overworld.event_roll import (
    initialize_event_pools,
    pick_event,
    roll_unknown_room,
)
from sts.overworld.relic_pools import RelicPools
from sts.overworld.rng import OverworldRngStreams
from sts.overworld.state import RunState


def _state_with_pools(seed=1):
    s = RunState()
    initialize_event_pools(s)
    rngs = OverworldRngStreams(seed)
    return s, rngs, RelicPools(rngs.relic)


# ---- ？房房型 roll ----


def test_room_roll_base_statistics():
    from collections import Counter

    c = Counter()
    for seed in range(400):
        s = RunState()
        rngs = OverworldRngStreams(seed)
        c[roll_unknown_room(s, rngs)] += 1
    total = sum(c.values())
    # 每种子全新状态单次 roll → 基线概率（斜坡递增见 slope 测试）
    assert c["event"] / total > 0.80
    assert 0.05 < c["monster"] / total < 0.15  # 基线 10%
    assert 0.005 < c["shop"] / total < 0.06  # 基线 3%
    assert 0.0 < c["treasure"] / total < 0.05  # 基线 2%


def test_room_roll_slope_resets():
    s = RunState()
    rngs = OverworldRngStreams(9)
    for _ in range(50):
        before = s.monster_slope
        result = roll_unknown_room(s, rngs)
        if result == "monster":
            assert s.monster_slope == 0.1  # 命中重置
        else:
            assert s.monster_slope == before + 0.1  # 未命中递增


def test_juzu_converts_monster_to_event():
    hits = 0
    for seed in range(300):
        s = RunState()
        s.relics.append(RelicId.JUZU_BRACELET)
        rngs = OverworldRngStreams(seed)
        if roll_unknown_room(s, rngs) != "monster":
            hits += 1
    assert hits == 300  # 佛珠：永不出现 monster 结果


def test_tiny_chest_forces_treasure_every_4th():
    forced = 0
    for seed in range(200):
        s = RunState()
        s.relics.append(RelicId.TINY_CHEST)
        rngs = OverworldRngStreams(seed)
        results = [roll_unknown_room(s, rngs) for _ in range(4)]
        if "treasure" in results[3]:  # 第 4 个 ？房强制宝箱（可能天然也是）
            forced += 1
    assert forced == 200


# ---- 事件选择 ----


def test_event_selection_pools_and_removal():
    s, rngs, _pools = _state_with_pools()
    s.floor = 10  # Dead Adventurer / Mushrooms 需 floor > 6
    s.deck.append(DeckCard(REGRET))  # Fountain 需卡组有诅咒
    seen = []
    for _ in range(len(ACT1_EVENTS) + len(ACT1_SHRINES) + len(ACT1_ONETIMES)):
        e = pick_event(s, rngs)
        if e is None:
            break
        seen.append(e.eid)
    assert len(seen) == 24  # 全部 24 个事件可抽尽（NoteForYourself 除外）
    assert len(seen) == len(set(seen)), "同事件重复出现（应抽后移除）"
    assert set(seen) <= set(ACT1_EVENTS) | set(ACT1_SHRINES) | set(ACT1_ONETIMES)


def test_event_pool_filters():
    # Cleric 需金 ≥35
    s, rngs, _ = _state_with_pools()
    s.gold = 10
    for _ in range(30):
        e = pick_event(s, rngs)
        if e is None:
            break
        assert e.eid != "The Cleric"
    # Dead Adventurer / Mushrooms 需 floor > 6
    s2, rngs2, _ = _state_with_pools()
    s2.floor = 3
    for _ in range(30):
        e = pick_event(s2, rngs2)
        if e is None:
            break
        assert e.eid not in ("Dead Adventurer", "Mushrooms")
    # Fountain 需有诅咒；WomanInBlue 需金 ≥50
    s3, rngs3, _ = _state_with_pools()
    s3.gold = 40
    s3.deck = [DeckCard(STRIKE)] * 10
    for _ in range(30):
        e = pick_event(s3, rngs3)
        if e is None:
            break
        assert e.eid not in ("Fountain of Cleansing", "The Woman in Blue")


def test_shrine_branch_statistics():
    shrine_hits = 0
    trials = 0
    for seed in range(400):
        s, rngs, _ = _state_with_pools(seed)
        s.event_pool = ["Shining Light"]  # 固定普通池，便于归因
        e = pick_event(s, rngs)
        trials += 1
        if e.category in ("shrine", "onetime"):
            shrine_hits += 1
    assert abs(shrine_hits / trials - 0.25) < 0.08


# ---- 事件效果（逐事件确定性）----


def test_zhs_names_aligned():
    zhs = json.load(open(pathlib.Path(__file__).parent.parent / "sts_game_data" / "localization" / "zhs" / "events.json"))
    for reg in (ACT1_EVENTS, ACT1_SHRINES, ACT1_ONETIMES):
        for eid, d in reg.items():
            assert eid in zhs, f"zhs 缺事件 {eid}"
            assert zhs[eid]["NAME"] == d.zh, f"{eid}: {d.zh} != {zhs[eid]['NAME']}"


def test_big_fish_effects():
    s, rngs, pools = _state_with_pools()
    ctx = EventContext(s, rngs, pools)
    out = ACT1_EVENTS["Big Fish"].options[0].effect(s, rngs, ctx)
    assert s.hp == 80  # 满血回 0
    s.lose_hp(40)
    ACT1_EVENTS["Big Fish"].options[0].effect(s, rngs, ctx)
    assert s.hp == 80 - 40 + 80 // 3
    ACT1_EVENTS["Big Fish"].options[1].effect(s, rngs, ctx)
    assert s.max_hp == 85
    n_relics = len(s.relics)
    n_deck = len(s.deck)
    ACT1_EVENTS["Big Fish"].options[2].effect(s, rngs, ctx)
    assert len(s.relics) == n_relics + 1 and len(s.deck) == n_deck + 1  # 诅咒 + 遗物


def test_liars_game_gold_and_curse():
    s, rngs, pools = _state_with_pools()
    ctx = EventContext(s, rngs, pools)
    ACT1_EVENTS["Liars Game"].options[0].effect(s, rngs, ctx)
    assert s.gold == 99 + 175 and len(s.deck) == 11
    assert s.deck[-1].card.ctype == "Curse"


def test_golden_idol_trap_phase():
    s, rngs, pools = _state_with_pools()
    ctx = EventContext(s, rngs, pools)
    ev = ACT1_EVENTS["Golden Idol"]
    assert RelicId.GOLDEN_IDOL not in s.relics
    out = ev.options_fn(s)[0].effect(s, rngs, ctx)
    assert RelicId.GOLDEN_IDOL in s.relics and out.reopen
    trap_options = ev.options_fn(s)  # 陷阱相
    assert [o.label[:2] for o in trap_options] == ["逃跑", "硬抗", "躲藏"]
    trap_options[1].effect(s, rngs, ctx)  # 硬抗 25%
    assert s.hp == 80 - 20
    s2, rngs2, pools2 = _state_with_pools(2)
    ctx2 = EventContext(s2, rngs2, pools2)
    ev2 = ACT1_EVENTS["Golden Idol"]
    ev2.options_fn(s2)[0].effect(s2, rngs2, ctx2)
    ev2.options_fn(s2)[0].effect(s2, rngs2, ctx2)  # 逃跑：受伤诅咒
    assert any(dc.card.name == "Injury" for dc in s2.deck)


def test_world_of_goop():
    s, rngs, pools = _state_with_pools()
    ctx = EventContext(s, rngs, pools)
    ACT1_EVENTS["World of Goop"].options[0].effect(s, rngs, ctx)
    assert s.gold == 99 + 75 and s.hp == 80 - 11
    ACT1_EVENTS["World of Goop"].options[1].effect(s, rngs, ctx)
    assert 99 + 75 - 50 <= s.gold <= 99 + 75 - 20


def test_wheel_of_change_all_faces():
    """6 面（金/遗物/回满/诅咒/移除/损 HP）：由结果日志分类，240 次采样全覆盖。"""
    faces = set()
    for seed in range(240):
        s, rngs, pools = _state_with_pools(seed)
        ctx = EventContext(s, rngs, pools)
        out = ACT1_SHRINES["Wheel of Change"].options[0].effect(s, rngs, ctx)
        if "100 金" in out.log:
            faces.add("gold")
        elif "遗物" in out.log:
            faces.add("relic")
        elif "回满" in out.log:
            faces.add("heal")
        elif "诅咒" in out.log:
            faces.add("curse")
        elif "移除" in out.log:
            faces.add("remove")
        elif "损" in out.log:
            faces.add("hp_loss")
    assert faces == {"gold", "relic", "heal", "curse", "remove", "hp_loss"}, f"面覆盖：{faces}"


def test_woman_in_blue_potions():
    s, rngs, pools = _state_with_pools()
    ctx = EventContext(s, rngs, pools)
    ACT1_ONETIMES["The Woman in Blue"].options[2].effect(s, rngs, ctx)  # 买 3 瓶
    assert s.gold == 99 - 40
    assert sum(1 for p in s.potions if p is not None) == 3


def test_fountain_removes_all_curses():
    from sts.content.cards.curses import REGRET

    s, rngs, pools = _state_with_pools()
    s.deck += [DeckCard(REGRET), DeckCard(REGRET)]
    ctx = EventContext(s, rngs, pools)
    ACT1_ONETIMES["Fountain of Cleansing"].options[0].effect(s, rngs, ctx)
    assert not any(dc.card.ctype == "Curse" for dc in s.deck)
    assert len(s.deck) == 10


def test_dead_adventurer_search_loop():
    """搜索循环：必终止（奖励序列有限 + 遇敌率封顶）。"""
    for seed in range(20):
        s, rngs, pools = _state_with_pools(seed)
        ctx = EventContext(s, rngs, pools)
        ev = ACT1_EVENTS["Dead Adventurer"]
        for _ in range(50):
            out = ev.options[0].effect(s, rngs, ctx)
            if out.pending_combat is not None:
                assert out.pending_combat.elite and out.pending_combat.gold == (25, 35)
                break  # 遇敌分支（run 循环负责接战斗）
            if not out.reopen:
                break  # 搜空


def test_bonfire_sacrifice_rewards_data():
    """献祭选项产出 bonfire_sacrifice 选择（奖励结算在 run 循环，见 run 测试）。"""
    s, rngs, pools = _state_with_pools()
    ctx = EventContext(s, rngs, pools)
    out = ACT1_ONETIMES["Bonfire Elementals"].options[0].effect(s, rngs, ctx)
    assert out.card_choice is not None and out.card_choice.kind == "bonfire_sacrifice"


def test_golden_wing_pray_and_smash():
    s, rngs, pools = _state_with_pools()
    ctx = EventContext(s, rngs, pools)
    out = ACT1_EVENTS["Golden Wing"].options[0].effect(s, rngs, ctx)
    assert s.hp == 73 and out.card_choice.kind == "remove"
    # 摧毁需 baseDamage ≥ 10 攻击牌——初始卡组有 Bash(8) + Strike(6)，不满足
    assert ACT1_EVENTS["Golden Wing"].options[1].available(s) is False
    s.deck.append(DeckCard(cards_ironclad.CLOTHESLINE))  # baseDamage 12 ≥ 10
    assert ACT1_EVENTS["Golden Wing"].options[1].available(s) is True
    ACT1_EVENTS["Golden Wing"].options[1].effect(s, rngs, ctx)
    assert 149 <= s.gold <= 179


def test_meet_again_card_option_availability():
    s, rngs, pools = _state_with_pools()
    ev = ACT1_ONETIMES["WeMeetAgain"]
    # 初始卡组全是基础牌 → 给牌选项不可用
    assert ev.options[2].available(s) is False
    s.deck.append(DeckCard(cards_ironclad.CLEAVE))
    assert ev.options[2].available(s) is True

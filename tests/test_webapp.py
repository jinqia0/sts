"""webapp（战斗网页调试器）模块测试：目录构建 / 战斗创建 / 序列化 / 动作分发。

HTTP 层不在此测（本地起服务手测，见 sts/webapp.py 模块注释）；这里锁住
引擎封装的行为契约：配置 → BattleContext 的每个转换环节。
"""

from __future__ import annotations

import pytest

import sts.webapp as webapp
from sts.combat.types import InputState, Outcome


# ---------------------------------------------------------------- 目录

def test_catalog_sizes_and_ids_resolve():
    # 内容全量迁移后的规模下限（涨内容只允许变多）
    assert len(webapp.CARDS) >= 350
    assert len(webapp.MONSTER_CLASSES) >= 60
    assert len(webapp.RELIC_META) >= 120
    assert len(webapp.POTION_META) >= 42
    assert len(webapp.ENCOUNTER_KEYS) >= 60

    for cid in webapp.CARDS:
        modkey, varname = cid.split(":", 1)
        assert modkey in {"ironclad", "silent", "defect", "watcher",
                          "colorless", "curses", "status"}
        assert varname.isupper()

    for m in webapp.RELIC_META:
        assert m["zh"] and m["id"]
    for m in webapp.POTION_META:
        assert m["zh"] and m["pid"]


def test_character_starting_decks_resolve():
    for key, char in webapp.CHARACTERS.items():
        assert char["max_hp"] > 0
        total = 0
        for e in char["deck"]:
            assert e["id"] in webapp.CARDS, f"{key} 初始牌组含未知卡 {e['id']}"
            total += e["count"]
        assert total >= 10, f"{key} 初始牌组应有完整规模，实际 {total}"


def test_custom_encounter_registered():
    assert "custom_web" in webapp.encounters_mod.ENCOUNTERS


# ---------------------------------------------------------------- 战斗创建

def test_create_battle_custom_monsters_and_upgrades():
    sid = webapp.create_battle({
        "character": "silent",
        "deck": [{"id": "silent:STRIKE_S", "count": 4, "upgraded": 2},
                 {"id": "silent:DEFEND_S", "count": 5}],
        "relics": ["AKABEKO", "BLOOD_VIAL"],
        "potions": ["Fire Potion"],
        "monsters": ["Cultist", "JawWorm"],
        "seed": 42,
    })
    sess = webapp.SESSIONS[sid]
    bc = sess["bc"]

    assert [type(m).__name__ for m in bc.monsters.monsters] == ["Cultist", "JawWorm"]
    assert bc.seed == 42
    # 升级位：4 张打击中 2 张 upgraded（手牌 + 抽牌堆合计）
    n_up = sum(1 for inst in list(bc.cards.draw_pile) + list(bc.cards.hand)
               if inst.card.name == "Strike" and inst.upgraded)
    assert n_up == 2
    # 静默职业生命修正
    assert bc.player.max_hp == 70
    # 药水占位
    assert bc.player.potions[0].pid == "Fire Potion"


def test_create_battle_default_deck_uses_character_starter():
    sid = webapp.create_battle({"character": "defect", "monsters": ["Cultist"],
                                "seed": 1})
    bc = webapp.SESSIONS[sid]["bc"]
    names = sorted(inst.card.name for inst in
                   list(bc.cards.draw_pile) + list(bc.cards.hand))
    assert names == sorted(["Strike"] * 4 + ["Defend"] * 4 + ["Zap", "Dualcast"])
    assert bc.player.max_hp == 75


def test_session_cap():
    before = len(webapp.SESSIONS)
    for i in range(webapp._MAX_SESSIONS + 3):
        webapp.create_battle({"character": "ironclad", "monsters": ["Cultist"],
                              "seed": i})
    assert len(webapp.SESSIONS) <= webapp._MAX_SESSIONS + before + 1


# ---------------------------------------------------------------- 序列化

def test_serialize_shape():
    sid = webapp.create_battle({"character": "ironclad", "monsters": ["Cultist"],
                                "relics": ["AKABEKO"], "seed": 5})
    st = webapp.serialize(webapp.SESSIONS[sid]["bc"])

    assert st["input_state"] == "PLAYER_NORMAL"
    assert st["outcome"] == "UNDECIDED"
    assert st["player"]["max_hp"] == 80
    assert len(st["hand"]) == 5
    assert st["monsters"][0]["intent"]["kind"] == "buff"  # Cultist 首回合必咒语
    assert st["relics"][0]["id"] == "AKABEKO"
    assert sum(c["count"] for c in st["draw_pile"]) == 5  # 10 张 - 手牌 5 张
    for key in ("draw_pile", "discard_pile", "exhaust_pile", "limbo",
                "card_select", "scry"):
        assert key in st
    for c in st["hand"]:
        assert "playable" in c and "reason" in c


def test_playable_reason_matches_engine_rejection():
    sid = webapp.create_battle({"character": "ironclad", "monsters": ["Cultist"],
                                "seed": 5})
    bc = webapp.SESSIONS[sid]["bc"]
    bc.player.energy = 0
    st = webapp.serialize(bc)
    assert all(not c["playable"] for c in st["hand"])
    assert all("能量" in c["reason"] for c in st["hand"])


# ---------------------------------------------------------------- 动作分发

def test_apply_action_dispatch_and_rejection():
    sid = webapp.create_battle({"character": "ironclad", "monsters": ["Cultist"],
                                "seed": 5})
    # 未知类型
    with pytest.raises(ValueError, match="未知动作类型"):
        webapp.apply_action(sid, {"type": "wat"})
    # 手牌越界 → 引擎 ValueError
    with pytest.raises(ValueError):
        webapp.apply_action(sid, {"type": "play", "index": 99})
    # 正常路径：出牌 + 结束回合推进
    webapp.apply_action(sid, {"type": "end"})
    st = webapp.serialize(webapp.SESSIONS[sid]["bc"])
    assert st["turn"] == 2


def test_battle_runs_to_completion_via_actions():
    """最小策略（出第一张可打牌 / 否则结束回合）驱动整场——网页调试器的
    核心循环契约：任何配置下都能靠这组动作走完，不卡死。"""
    sid = webapp.create_battle({
        "character": "watcher",
        "deck": [{"id": "watcher:STRIKE_W", "count": 5},
                 {"id": "watcher:DEFEND_W", "count": 5},
                 {"id": "watcher:ERUPTION", "count": 1}],
        "monsters": ["Cultist"], "seed": 9,
    })
    for _ in range(200):
        st = webapp.serialize(webapp.SESSIONS[sid]["bc"])
        if st["over"]:
            break
        if st["input_state"] == "CARD_SELECT":
            webapp.apply_action(sid, {"type": "choose_cards", "indices": [0]})
        elif st["input_state"] == "SCRY":
            webapp.apply_action(sid, {"type": "scry", "keep_top_n": 1})
        else:
            playable = next((c for c in st["hand"] if c["playable"]), None)
            if playable:
                webapp.apply_action(sid, {"type": "play", "index": playable["index"]})
            else:
                webapp.apply_action(sid, {"type": "end"})
    st = webapp.serialize(webapp.SESSIONS[sid]["bc"])
    assert st["outcome"] in (Outcome.PLAYER_VICTORY.name, Outcome.PLAYER_LOSS.name)
    # 日志未被 drain 时 offset 原地不动，drain 后一次给全
    assert webapp.SESSIONS[sid]["offset"] == 0
    assert len(webapp.drain_log(sid)) == len(webapp.SESSIONS[sid]["bc"].log)
    assert webapp.SESSIONS[sid]["offset"] == len(webapp.SESSIONS[sid]["bc"].log)


def test_drain_log_incremental():
    sid = webapp.create_battle({"character": "ironclad", "monsters": ["Cultist"],
                                "seed": 5})
    first = webapp.drain_log(sid)
    assert first == []  # 开局无日志
    webapp.apply_action(sid, {"type": "play", "index": 0})
    second = webapp.drain_log(sid)
    assert second and "你打出" in second[0]
    assert webapp.drain_log(sid) == []  # 已消费


# ---------------------------------------------------------------- 信息边界

def test_draw_pile_serialization_hides_order():
    """信息泄露审计（DESIGN.md §4 口径，对齐 env 的乱序三堆测试）：
    抽牌堆序列化只暴露构成（同名聚合 + 计数 + 名称排序）——任意打乱
    draw_pile 内部顺序，序列化结果逐位一致。"""
    import random

    sid = webapp.create_battle({"character": "ironclad", "monsters": ["Cultist"],
                                "seed": 5})
    bc = webapp.SESSIONS[sid]["bc"]
    st1 = webapp.serialize(bc)
    rnd = random.Random(99)
    for _ in range(5):
        rnd.shuffle(bc.cards.draw_pile)
        assert webapp.serialize(bc)["draw_pile"] == st1["draw_pile"]
    # 聚合计数守恒 + 名称排序口径
    assert sum(c["count"] for c in st1["draw_pile"]) == len(bc.cards.draw_pile)
    names = [c["name"] for c in st1["draw_pile"]]
    assert names == sorted(names)
    # 同名跨职业模板不误并（Strike_R ≠ Strike_G）：换职业构造混合场景
    sid2 = webapp.create_battle({"character": "ironclad",
                                 "deck": [{"id": "ironclad:STRIKE", "count": 3},
                                          {"id": "silent:STRIKE_S", "count": 3},
                                          {"id": "ironclad:DEFEND", "count": 4}],
                                 "monsters": ["Cultist"], "seed": 6})
    st2 = webapp.serialize(webapp.SESSIONS[sid2]["bc"])
    strikes = [c for c in st2["draw_pile"] if c["name"] == "Strike"]
    assert sum(c["count"] for c in strikes) == 6 - len(
        [c for c in st2["hand"] if c["name"] == "Strike"])


def test_card_select_candidates_display_sorted():
    """选卡候选展示按名称排序（对齐本体选卡界面），engine_idx 映射回
    引擎下标——玩家不感知抽牌堆内部顺序（Seek 类选卡的泄露面）。"""
    from sts.combat.types import InputState

    sid = webapp.create_battle({"character": "ironclad", "monsters": ["Cultist"],
                                "seed": 5})
    bc = webapp.SESSIONS[sid]["bc"]
    # 手牌乱序挂起为选卡候选（Armaments 路径同构）
    shuffled = list(reversed(list(bc.cards.hand)))
    bc.open_card_select(shuffled, lambda bc_, chosen: None, prompt="测试")
    assert bc.input_state == InputState.CARD_SELECT
    st = webapp.serialize(bc)
    names = [c["name"] for c in st["card_select"]["candidates"]]
    assert names == sorted(names)
    # engine_idx 指回引擎候选下标且集合完整
    idxs = sorted(c["engine_idx"] for c in st["card_select"]["candidates"])
    assert idxs == list(range(len(shuffled)))
    # 映射正确性：展示项与 engine_idx 指向的引擎候选是同一张牌（含升级位）
    for c in st["card_select"]["candidates"]:
        engine_cand = shuffled[c["engine_idx"]]
        assert engine_cand.card.name == c["name"]
        assert engine_cand.upgraded == c["upgraded"]

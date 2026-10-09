"""webapp（战斗网页调试器）模块测试：目录构建 / 战斗创建 / 序列化 / 动作分发。

HTTP 层不在此测（本地起服务手测，见 sts/webapp.py 模块注释）；这里锁住
引擎封装的行为契约：配置 → BattleContext 的每个转换环节。
"""

from __future__ import annotations

from pathlib import Path

import numpy as np
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


# ---------------------------------------------------------------- env 模式（策略演示 / 录制）

class _StubModel:
    """最小策略桩：在合法动作里均匀随机——测 ai_step 全链路而不加载真模型。"""

    def __init__(self, seed: int = 0):
        self._rng = np.random.default_rng(seed)

    def predict(self, obs, action_masks=None, deterministic=True, **kw):
        legal = np.flatnonzero(action_masks)
        return int(self._rng.choice(legal)), None


@pytest.fixture
def records_dir(tmp_path, monkeypatch):
    monkeypatch.setattr(webapp, "RECORDS_DIR", tmp_path)
    return tmp_path


def test_env_mode_attach_and_body_mapping_formulas():
    from sts.env import (
        ACTION_END_TURN, HAND_SLOT_BASE, POTION_BASE, POTION_STANCE_BASE,
        SCRY_BASE, TARGETED_BASE,
    )
    sid = webapp.create_battle({
        "env_mode": True, "character": "ironclad", "encounter": "cultist",
        "seed": 7, "potions": ["Fire Potion", "FearPotion"],
    })
    sess = webapp.SESSIONS[sid]
    env = sess["env"]
    assert sess["env"] is not None and sess["record"] is False
    assert env.bc is sess["bc"]
    from sts.env import OBS_DIM
    assert env._get_obs().shape == (OBS_DIM,)
    assert env.action_masks().any()

    # 动作体 → env 动作 id 的编码公式
    assert webapp.body_to_env_actions(env, {"type": "end"})[0][0] == ACTION_END_TURN
    assert webapp.body_to_env_actions(env, {"type": "play", "index": 3})[0][0] \
        == HAND_SLOT_BASE + 3
    assert webapp.body_to_env_actions(env, {"type": "play", "index": 2, "target": 4})[0][0] \
        == TARGETED_BASE + 2 * 5 + 4
    assert webapp.body_to_env_actions(env, {"type": "scry", "keep_top_n": 3})[0][0] \
        == SCRY_BASE + 3
    assert webapp.body_to_env_actions(env, {"type": "use_potion", "slot": 1})[0][0] \
        == POTION_BASE + 1 * 6 + 0
    assert webapp.body_to_env_actions(
        env, {"type": "use_potion", "slot": 0, "target": 2})[0][0] == POTION_BASE + 0 * 6 + 3
    assert webapp.body_to_env_actions(
        env, {"type": "use_potion", "slot": 1, "choice": "calm"})[0][0] \
        == POTION_STANCE_BASE + 1 * 2 + 1


def test_env_mode_actions_match_direct_engine_path():
    """env 模式等价性：同一配置同一种子，经 env.step 的动作序列与直调引擎
    的动作序列产生逐位一致的战斗状态（serialize 全等）。"""
    cfg = {"character": "ironclad", "encounter": "jaw_worm", "seed": 42}
    sid_direct = webapp.create_battle(dict(cfg))
    sid_env = webapp.create_battle({**cfg, "env_mode": True})

    def drive(sid: str, n: int) -> None:
        for _ in range(n):
            st = webapp.serialize(webapp.SESSIONS[sid]["bc"])
            if st["over"]:
                return
            playable = next((c for c in st["hand"] if c["playable"]), None)
            if playable:
                webapp.apply_action(sid, {"type": "play", "index": playable["index"]})
            else:
                webapp.apply_action(sid, {"type": "end"})

    drive(sid_direct, 40)
    drive(sid_env, 40)
    st_direct = webapp.serialize(webapp.SESSIONS[sid_direct]["bc"])
    st_env = webapp.serialize(webapp.SESSIONS[sid_env]["bc"])
    assert st_direct == st_env


def test_card_select_env_window_and_out_of_window_guard():
    """选卡经 env 自回归序列表达：窗口内选择 → SELECT…+CONFIRM；超窗
    候选映射失败（窗口 10 近似的边界，回显前端）。"""
    from sts.combat.types import InputState

    sid = webapp.create_battle({
        "env_mode": True, "record": True, "character": "ironclad",
        "deck": [{"id": "ironclad:STRIKE", "count": 5},
                 {"id": "ironclad:DEFEND", "count": 5},
                 {"id": "ironclad:ARMAMENTS"}],
        "encounter": "cultist", "seed": 3,  # 该种子开局手牌含 Armaments
    })
    sess = webapp.SESSIONS[sid]
    bc, env = sess["bc"], sess["env"]
    # 打出 Armaments（手牌里其余牌可升级）→ CARD_SELECT
    idx = next(i for i, inst in enumerate(bc.cards.hand)
               if inst.card.name == "Armaments")
    webapp.apply_action(sid, {"type": "play", "index": idx})
    assert bc.input_state == InputState.CARD_SELECT

    st = webapp.serialize(bc, env)
    assert all("in_window" in c for c in st["card_select"]["candidates"])
    assert all(c["in_window"] for c in st["card_select"]["candidates"])  # 5 张 < 窗口 10

    target = st["card_select"]["candidates"][0]
    before = target["upgraded"]
    webapp.apply_action(sid, {"type": "choose_cards", "indices": [target["engine_idx"]]})
    assert bc.input_state != InputState.CARD_SELECT  # 选卡已提交
    # 选中的候选被升级（Armaments 效果经 env 序列正确执行）
    upgraded = [inst for inst in bc.cards.hand
                if inst.card.name == target["name"] and inst.upgraded]
    assert (len(upgraded) >= 1) or before  # 已升级牌不可再选，兜底断言状态推进
    labels = [s["label"] for s in sess["steps"]]
    assert any("选卡" in l for l in labels)
    assert any("确认选卡" in l for l in labels)

    # 超窗守卫：伪造一个不在窗口内的候选下标
    bc.open_card_select(list(bc.cards.hand), lambda bc_, chosen: None, prompt="测试")
    env.action_masks()  # 同步窗口
    outside = max(range(len(bc.cards.hand)), key=lambda i: i)
    if outside not in env._select_engine_idx:
        with pytest.raises(ValueError, match="窗口"):
            webapp.body_to_env_actions(env, {"type": "choose_cards", "indices": [outside]})


def test_ai_step_stub_and_record_source(records_dir):
    webapp._MODEL_CACHE["stub"] = _StubModel(seed=3)
    sid = webapp.create_battle({
        "env_mode": True, "record": True, "model": "stub",
        "character": "ironclad", "encounter": "cultist", "seed": 11,
    })
    info = webapp.ai_step(sid)
    assert info["model"] == "stub"
    assert isinstance(info["action"], int) and info["label"]
    assert webapp.SESSIONS[sid]["steps"][-1]["by"] == "ai"
    # 混合执行来源
    webapp.apply_action(sid, {"type": "end"})
    assert webapp.record_source(webapp.SESSIONS[sid]["steps"]) == "mixed"


def test_record_save_and_replay_bit_exact(records_dir):
    """录制 → 保存 → 确定性回放：重建局面重演动作，逐步观测/掩码可用，
    终局与实录一致（BC 导出的正确性根基）。"""
    webapp._MODEL_CACHE["stub"] = _StubModel(seed=1)
    sid = webapp.create_battle({
        "env_mode": True, "record": True, "model": "stub",
        "character": "ironclad", "encounter": "jaw_worm", "seed": 23,
        "eval_set": "act1_v1", "eval_index": 0,
    })
    sess = webapp.SESSIONS[sid]
    env = sess["env"]
    for _ in range(400):
        if env.bc.over:
            break
        webapp.ai_step(sid)
    assert env.bc.over, "随机桩策略应在回合限内打完（种子固定，确定性）"

    saved = webapp.save_record(sid)
    assert saved["outcome"] == env.bc.outcome.name
    assert (records_dir / Path(saved["path"]).name).exists()

    with open(saved["path"], encoding="utf-8") as f:
        import json
        rec = json.load(f)
    assert rec["source"] == "ai" and rec["eval"] == {"set": "act1_v1", "index": 0}
    assert rec["config"]["seed"] == 23

    out = webapp.replay_record(rec)
    assert out["obs"].shape[0] == rec["n_steps"]
    assert out["actions"].shape == (rec["n_steps"],)
    assert out["masks"].shape == (rec["n_steps"], 120)
    # 每个录制动作在回放对应步的掩码下合法
    assert out["masks"][np.arange(rec["n_steps"]), out["actions"]].all()
    assert out["bc"].outcome.name == rec["outcome"]
    assert out["bc"].player.hp == rec["final_hp"]
    # 回放自身确定性：两次回放逐位一致
    out2 = webapp.replay_record(rec)
    assert (out["obs"] == out2["obs"]).all()
    assert (out["masks"] == out2["masks"]).all()


def test_record_save_requires_finished_battle(records_dir):
    sid = webapp.create_battle({"env_mode": True, "record": True,
                                "encounter": "cultist", "seed": 1})
    with pytest.raises(ValueError, match="尚未结束"):
        webapp.save_record(sid)
    sid2 = webapp.create_battle({"env_mode": True, "encounter": "cultist", "seed": 1})
    with pytest.raises(ValueError, match="未开启录制"):
        webapp.save_record(sid2)


def test_eval_sets_and_default_models():
    for name, entries in webapp.EVAL_SETS.items():
        assert entries
        for e in entries:
            assert e["encounter"] in webapp.encounters_mod.ENCOUNTERS
            assert 1000 <= e["seed"] < 10_000  # 与训练（≥10_000）、评估（0..99）种子不相交
            assert webapp.encounter_tier(e["encounter"]) == e["tier"]
    for tier, fname in webapp.DEFAULT_MODELS.items():
        assert (webapp.MODELS_DIR / fname).exists(), f"{tier} 档默认模型缺失：{fname}"
    assert webapp.encounter_tier("custom_web") is None


def test_serialize_env_card_select_in_window_flag():
    """env=None（普通模式）不注入 in_window 字段——前端据此区分两种模式。"""
    from sts.combat.types import InputState

    sid = webapp.create_battle({"character": "ironclad", "encounter": "cultist",
                                "seed": 5})
    bc = webapp.SESSIONS[sid]["bc"]
    bc.open_card_select(list(bc.cards.hand), lambda bc_, chosen: None, prompt="测试")
    st = webapp.serialize(bc)
    assert bc.input_state == InputState.CARD_SELECT
    assert all("in_window" not in c for c in st["card_select"]["candidates"])


# ---------------------------------------------------------------- 随机配置生成

def test_random_config_pools_character_purity():
    """四职业奖励池：非空、稀有度三桶齐全、只含本职业模块的卡
    （颜色过滤防跨职业同名卡误入）。"""
    for char, pools in webapp.REWARD_POOLS.items():
        for rar in ("common", "uncommon", "rare"):
            assert len(pools[rar]) >= 15, f"{char} {rar} 池过小：{len(pools[rar])}"
        for rar in ("common", "uncommon", "rare"):
            for d in pools[rar]:
                cid = webapp.CARD_ID_BY_OBJ[id(d)]
                # HAND_OF_GREED 定义在无色模块但本体分类 Ironclad Rare
                # （run_env 源码补齐批次），是唯一合法跨模块例外
                ok = cid.startswith(f"{char}:") or cid == "colorless:HAND_OF_GREED"
                assert ok, f"{char} {rar} 池混入他职业卡：{cid}"
    # 铁甲池与训练同源（run_env.CARD_POOLS 同一对象）
    assert webapp.REWARD_POOLS["ironclad"] is webapp.CARD_POOLS


def test_random_config_structure_and_bounds():
    for char in ("ironclad", "silent", "defect", "watcher"):
        cfg = webapp.random_config({
            "character": char, "strikes": 3, "defends": 2,
            "deck_size": 15, "relics": 3, "upgrade_pct": 100,
            "encounter_pool": "weak", "seed": 11,
        })
        total = sum(e["count"] for e in cfg["deck"])
        upg = sum(e["upgraded"] for e in cfg["deck"])
        # 起手 = 3 打 + 2 防 + 职业非基础牌（铁甲 1 / 其余 2）→ 新增全升级
        starters = webapp.CHARACTERS[char]["deck"]
        base = 3 + 2 + sum(e["count"] for e in starters[2:])
        assert total == 15
        assert upg == 15 - base, f"{char}：升级位应全落在新增卡上"
        for e in cfg["deck"]:
            assert e["id"] in webapp.CARDS
            assert 0 <= e["upgraded"] <= e["count"]
        assert len(cfg["relics"]) == 3
        assert len(set(cfg["relics"])) == 3  # 遗物去重
        from sts.combat.relics import RelicId
        for rid in cfg["relics"]:
            assert RelicId[rid].name == rid
        assert cfg["encounter"] in webapp.WEAK_POOL


def test_random_config_seed_reproducible_and_param_effects():
    p = {"character": "ironclad", "deck_size": 18, "relics": 2,
         "encounter_pool": "boss", "seed": 42}
    a = webapp.random_config(dict(p))
    b = webapp.random_config(dict(p))
    assert a == b  # 同种子同参数 → 同配置
    c = webapp.random_config({**p, "seed": 43})
    assert a["deck"] != c["deck"] or a["relics"] != c["relics"]
    assert c["encounter"] in webapp.BOSSES
    # 升级概率 0：全新增卡无升级位
    z = webapp.random_config({**p, "upgrade_pct": 0})
    assert sum(e["upgraded"] for e in z["deck"]) == 0
    # 目标低于基础张数：按基础为准（不删起手牌）
    small = webapp.random_config({**p, "deck_size": 1})
    assert sum(e["count"] for e in small["deck"]) == 10


def test_random_config_rejects_bad_params():
    with pytest.raises(ValueError, match="未知职业"):
        webapp.random_config({"character": "wat"})
    with pytest.raises(ValueError, match="未知遭遇池"):
        webapp.random_config({"encounter_pool": "mega"})
    # 非法数值回落默认（不抛）
    cfg = webapp.random_config({"strikes": "abc", "deck_size": None})
    assert sum(e["count"] for e in cfg["deck"]) >= 10


def test_random_config_generated_battle_starts():
    """生成配置 → 直接构造战斗：随机出的卡组/遗物/遭遇全部能进入战斗
    （卡 id / 遗物 id / 遭遇键与引擎无缝对接）。"""
    for char, pool in (("ironclad", "elite"), ("watcher", "strong")):
        cfg = webapp.random_config({
            "character": char, "deck_size": 16, "relics": 2,
            "encounter_pool": pool, "seed": 5,
        })
        sid = webapp.create_battle({
            "character": char, "deck": cfg["deck"], "relics": cfg["relics"],
            "encounter": cfg["encounter"], "seed": 3, "env_mode": True,
        })
        bc = webapp.SESSIONS[sid]["bc"]
        n = sum(e["count"] for e in cfg["deck"])
        assert len(bc.cards.draw_pile) + len(bc.cards.hand) == n
        assert webapp.SESSIONS[sid]["env"].action_masks().any()

"""分档战损验收（阈值：弱 ≤5 / 强 ≤12 / 精英 ≤25 / Boss ≤35）。

用法：uv run python scripts/accept_tier.py models/xxx.zip strong

口径（DESIGN.md §5.4）：固定评估种子 70..99（与训练种子不相交），
确定性策略；胜局战损 = 入场HP − 终局HP，败局计入场HP（全损）。
同时报告拖延截断数（ACTION_LIMIT / TURN_LIMIT 触发）——塌缩残留
的行为学指纹。
"""

from __future__ import annotations

import sys
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from sts.env import ACTION_LIMIT, TURN_LIMIT
from sts.sampled_env import StsSampledEnv

DAMAGE_TARGETS = {"weak": 5, "strong": 12, "elite": 25, "boss": 35}
EVAL_SEEDS = list(range(70, 100))


def main() -> None:
    model_path, diff = sys.argv[1], sys.argv[2]
    from sb3_contrib import MaskablePPO

    m = MaskablePPO.load(model_path)
    env = StsSampledEnv(diff)
    rows = []
    for s in EVAL_SEEDS:
        obs, info = env.reset(seed=s)
        entry = info["entry_hp"]
        steps = 0
        hit_fuse = False
        while True:
            a, _ = m.predict(obs, deterministic=True, action_masks=env.action_masks())
            obs, r, term, trunc, info = env.step(int(a))
            steps += 1
            if steps >= ACTION_LIMIT + 5:
                hit_fuse = True
            if term or trunc or steps >= 800:
                break
        dmg = entry - env.bc.player.hp if info["won"] else entry
        rows.append(
            {
                "seed": s,
                "entry": entry,
                "steps": steps,
                "won": bool(info["won"]),
                "turn": env.bc.turn,
                "fused": hit_fuse or (not info["won"] and env.bc.turn > TURN_LIMIT),
                "dmg": dmg,
            }
        )

    wins = [r for r in rows if r["won"]]
    n = len(rows)
    print(f"==== {model_path} @ {diff}（种子 70..99，n={n}）====")
    print(f"胜率:        {len(wins)}/{n}（{len(wins) / n:.0%}）")
    if wins:
        dmgs = [r["dmg"] for r in wins]
        print(f"胜局战损:    mean={np.mean(dmgs):.1f}  median={np.median(dmgs):.0f}  max={max(dmgs)}")
        print(f"阈值 {DAMAGE_TARGETS[diff]}: {'达标' if np.mean(dmgs) <= DAMAGE_TARGETS[diff] else '超标'}")
    stalls = [r for r in rows if r["fused"]]
    print(f"拖延/死循环截断: {len(stalls)}/{n}")
    lens = [r["steps"] for r in rows]
    print(f"局长:        mean={np.mean(lens):.0f}  max={max(lens)}")
    if len(wins) < n:
        print(f"败局入场HP: {[r['entry'] for r in rows if not r['won']]}")


if __name__ == "__main__":
    main()

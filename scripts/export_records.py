"""录制记录 → BC 训练数据导出。

重放 records/ 下的录制 JSON（webapp 战斗页保存），逐步重建训练同款
(obs, action, mask) 元组，写为 data/bc/<记录名>.npz：

    uv run python scripts/export_records.py                # 全部记录
    uv run python scripts/export_records.py --source human # 只要手操
    uv run python scripts/export_records.py --out data/bc

回放确定性由 tests/test_webapp.py::test_record_save_and_replay_bit_exact
保证：同配置同种子同动作序列必然重建同一场战斗，逐步观测与实录时策略
所见逐位一致（观测只读引擎状态，无任何隐藏随机源）。

npz 内容：
- obs:    (N, OBS_DIM) int32   每步执行前观测（= 训练时策略输入）
- actions:(N,) int16           env 动作 id（Discrete(120)）
- masks:  (N, 120) bool        每步合法动作掩码
- meta:   0-d 数组（json 字符串）：来源/模型/配置/终局等记录元信息
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import sts.webapp as webapp  # noqa: E402

RECORDS_DIR = webapp.RECORDS_DIR


def export_one(rec_path: Path, out_dir: Path) -> Path:
    with open(rec_path, encoding="utf-8") as f:
        rec = json.load(f)
    out = webapp.replay_record(rec)
    meta = {k: rec.get(k) for k in
            ("version", "recorded_at", "source", "model", "eval",
             "config", "outcome", "final_hp", "turns", "n_steps")}
    out_path = out_dir / f"{rec_path.stem}.npz"
    np.savez_compressed(
        out_path,
        obs=out["obs"],
        actions=out["actions"],
        masks=out["masks"],
        meta=np.array(json.dumps(meta, ensure_ascii=False)),
    )
    return out_path


def main() -> None:
    parser = argparse.ArgumentParser(description="录制记录 → BC npz 导出")
    parser.add_argument("--records", type=Path, default=RECORDS_DIR,
                        help="录制目录（默认 records/）")
    parser.add_argument("--out", type=Path, default=Path("data/bc"),
                        help="输出目录（默认 data/bc/）")
    parser.add_argument("--source", choices=["human", "ai", "mixed"],
                        help="只导出指定来源（默认全部）")
    parser.add_argument("--eval-only", action="store_true",
                        help="只导出固定评测集对局")
    args = parser.parse_args()

    files = sorted(args.records.glob("*.json"))
    if args.source:
        files = [f for f in files if _source_of(f) == args.source]
    if args.eval_only:
        files = [f for f in files if _eval_of(f) is not None]
    if not files:
        print(f"没有匹配的记录（{args.records}）——先在网页里录制并保存几局。")
        return

    args.out.mkdir(parents=True, exist_ok=True)
    n_obs = 0
    n_files = 0
    for f in files:
        try:
            path = export_one(f, args.out)
        except ValueError as e:
            print(f"跳过 {f.name}：{e}")
            continue
        data = np.load(path)
        n = data["obs"].shape[0]
        n_obs += n
        n_files += 1
        print(f"{path.name}: {n} 步")
    print(f"共 {n_files} 份记录、{n_obs} 个 (obs, action, mask) 对 → {args.out}/")


def _source_of(path: Path) -> str | None:
    try:
        with open(path, encoding="utf-8") as f:
            return json.load(f).get("source")
    except (OSError, json.JSONDecodeError):
        return None


def _eval_of(path: Path):
    try:
        with open(path, encoding="utf-8") as f:
            return json.load(f).get("eval")
    except (OSError, json.JSONDecodeError):
        return None


if __name__ == "__main__":
    main()

"""Drift monitor for the decision model during the election window (docs/drift-monitor.md).

Each weekly live batch (scripts/vertex_batch.py build live) is labelled by the teacher, gemini-3.8-flash. Those
articles were published after the model was trained, so comparing the model with the teacher on them shows
whether the model still matches the teacher on new news. Same measures as the test set in docs/decision-model.md:
mean shift (model - teacher), slope (model = c + d x teacher) and mean absolute difference, per party, on articles
where both mention the party. Alert thresholds were set before the first batch: |shift| > 0.10 or slope < 0.70.
A batch labelled before the model was trained was part of its training data; only its test split (id hash % 10 == 0,
as in scripts/train_decision_model.py) is used.

    uv run python scripts/monitor_drift.py [--model tw-media-lean-v1]
"""

from __future__ import annotations

import argparse
import glob
import json
from datetime import date
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
ANN = ROOT / "data" / "annotations"
TEACHER = "gemini-3.8-flash"
PARTIES = ("KMT", "DPP")
NAME = {"KMT": "國民黨", "DPP": "民進黨"}
TEST = {"KMT": (886, -0.008, 0.96, 0.44), "DPP": (1028, -0.019, 0.93, 0.41)}  # docs/decision-model.md, test set
MAX_SHIFT, MIN_SLOPE = 0.10, 0.70


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--model", default="tw-media-lean-v1")
    model = ap.parse_args().model
    pred = {}
    for line in open(ANN / f"model_{model}_news.jsonl", encoding="utf-8"):
        d = json.loads(line)
        pred[d["key"].split(":", 1)[1]] = d["label"]

    L = [f"# 決策模型漂移監測\n\n更新：{date.today().isoformat()}　模型：`{model}`　老師：`{TEACHER}`\n",
         "選舉期間每週抽一批即時新聞給老師模型標註。這些文章都在模型訓練之後才刊出，所以拿模型與老師在同一批文章上比較，"
         "可以看出模型面對新新聞是否仍與老師一致（模型訓練前就標好的那一批曾用於訓練，只取其中的測試切分）。指標與[決策模型](decision-model.md)的測試集相同：偏移（模型 − 老師）、"
         f"斜率（模型 = c + d × 老師 的 d）、平均絕對差。警示門檻在第一批之前訂定：偏移絕對值 > {MAX_SHIFT:.2f} 或斜率 < {MIN_SLOPE:.2f}。\n",
         "| 期間 | 政黨 | 篇數 | 偏移 | 斜率 | 平均絕對差 | 警示 |", "|---|---|---|---|---|---|---|"]
    for p in PARTIES:
        n, s, d, m = TEST[p]
        L.append(f"| 測試集（參考） | {NAME[p]} | {n:,} | {s:+.3f} | {d:.2f} | {m:.2f} | — |")
    trained = (ROOT / "data" / "models" / model / "heads.pt").stat().st_mtime
    for f in sorted(glob.glob(str(ANN / f"vertex_{TEACHER}_live_*.jsonl"))):
        a, b = Path(f).stem.split("_")[-2:]
        seen = Path(f).stat().st_mtime < trained  # in the training data: keep the held-out test split only
        span = f"{a[:4]}-{a[4:6]}-{a[6:]}～{b[4:6]}-{b[6:]}" + ("（僅測試切分）" if seen else "")
        rows = {p: [] for p in PARTIES}
        for line in open(f, encoding="utf-8"):
            d = json.loads(line)
            aid, lab = d["key"].split(":", 1)[1], d.get("label") or {}
            if aid not in pred or not lab.get("political") or (seen and int(aid[:8], 16) % 10 != 0):
                continue
            for p in PARTIES:
                t = ((lab.get("parties") or {}).get(p) or {}).get("stance")
                e = pred[aid]["parties"][p]["stance"]
                if t is not None and e is not None and pred[aid]["parties"][p]["mentioned"]:
                    rows[p].append((float(t), float(e)))
        for p in PARTIES:
            x = np.array(rows[p])
            if len(x) < 20:
                L.append(f"| {span} | {NAME[p]} | {len(x)} | — | — | — | 篇數不足 |")
                continue
            t, e = x[:, 0], x[:, 1]
            shift, slope, mae = float(np.mean(e - t)), float(np.polyfit(t, e, 1)[0]), float(np.mean(np.abs(e - t)))
            alert = "**是**" if abs(shift) > MAX_SHIFT or slope < MIN_SLOPE else "否"
            L.append(f"| {span} | {NAME[p]} | {len(x)} | {shift:+.3f} | {slope:.2f} | {mae:.2f} | {alert} |")
    L += ["\n每週樣本約數百篇，比測試集小，單週數字的波動較大；連續兩週超過門檻才視為漂移，屆時以新標註重新校準或重訓。"]
    (ROOT / "docs" / "drift-monitor.md").write_text("\n".join(L) + "\n", encoding="utf-8")
    print("\n".join(L))


if __name__ == "__main__":
    main()

"""Compare Vertex Gemini labels on the pilot90 items with the three OpenCode pilot jurors.

Reports parse rate, Krippendorff's alpha with and without the Vertex juror, mean absolute stance gap to each
existing juror, and press-release anchor accuracy. Appends a section to docs/pilot-annotation.md.
Usage: uv run python scripts/compare_vertex.py gemini-3.8-flash
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import krippendorff
import numpy as np
from pilot_annotation import JURORS, stance

from twmedia.annotate import PARTIES

ROOT = Path(__file__).resolve().parents[1]
ANN = ROOT / "data" / "annotations"
MARK = "\n## 5. Vertex AI 批次（第 4 位陪審員候選）\n"


def labels(path: Path) -> dict[str, dict]:
    return {d["key"]: d["label"] for d in map(json.loads, open(path, encoding="utf-8"))}


def main(model: str) -> None:
    jurors = {j: labels(ANN / f"pilot_{j}.jsonl") for j in JURORS}
    vx = labels(ANN / f"vertex_{model}_pilot90.jsonl")
    summary = json.loads((ROOT / "data" / "vertex" / "pilot90" / "summary.json").read_text())
    keys = list(jurors["gpt-5.6-luna"])
    news = [k for k in keys if k.startswith("news:")]
    src = {json.loads(line)["key"]: json.loads(line)["source"] for line in open(ROOT / "data" / "vertex" / "pilot90" / "items.jsonl")}
    anchors = {k: ("KMT" if src[k] == "party_kmt" else "DPP") for k in keys if k.startswith("anchor:")}

    L = [MARK, f"模型：`{model}`（Vertex AI 批次預測，`us` 多區域，thinking level LOW，temperature 0）。"
         f"同一批 90 篇、同一份提示詞。可解析 {summary['parsed']}/{summary['requests']}；"
         f"token 計 輸入 {summary['tokens_in']:,}、輸出 {summary['tokens_out']:,}，"
         f"依牌價估計 US${summary['est_cost_usd']:.3f}（每篇約 US${summary['usd_per_item']:.4f}）。\n",
         "| 政黨 | α（原 3 位） | α（加 Vertex 共 4 位） | Vertex 與各陪審員的平均絕對差（luna / argon / deepseek） |",
         "|---|---|---|---|"]
    for p in PARTIES:
        m3 = np.array([[stance(jurors[j].get(k), p) for k in news] for j in JURORS])
        v = np.array([stance(vx.get(k), p) for k in news])
        m4 = np.vstack([m3, v])
        a3 = krippendorff.alpha(reliability_data=m3, level_of_measurement="ordinal")
        a4 = krippendorff.alpha(reliability_data=m4, level_of_measurement="ordinal")
        gaps = [np.nanmean(np.abs(row - v)) for row in m3]
        L.append(f"| {p} | {a3:.2f} | {a4:.2f} | {' / '.join(f'{g:.2f}' for g in gaps)} |")
    rival = {"KMT": "DPP", "DPP": "KMT"}
    own = [stance(vx.get(k), p) for k, p in anchors.items()]
    opp = [stance(vx.get(k), rival[p]) for k, p in anchors.items()]
    own, opp = [x for x in own if not np.isnan(x)], [x for x in opp if not np.isnan(x)]
    L.append(f"\n政黨新聞稿錨點：自己黨判為正面 {sum(x > 0 for x in own)}/{len(own)}，對手黨判為負面 {sum(x < 0 for x in opp)}/{len(opp)}。\n")

    doc = ROOT / "docs" / "pilot-annotation.md"
    text = doc.read_text(encoding="utf-8").split(MARK)[0]
    head, sep, tail = text.partition("\n## 限制")
    doc.write_text(head.rstrip() + "\n" + "\n".join(L) + sep + tail, encoding="utf-8")
    print("\n".join(L))


if __name__ == "__main__":
    main(sys.argv[1])

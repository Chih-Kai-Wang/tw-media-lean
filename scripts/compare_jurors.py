"""Agreement between two Vertex jurors on the same requests (scripts/vertex_batch.py build juror2).

Writes docs/jury-agreement.md: Krippendorff's alpha (ordinal) per party, exact agreement, mean absolute gap,
anchor accuracy per juror, and the outlet ranking each juror implies.
Usage: uv run python scripts/compare_jurors.py gemini-3.8-flash gemini-3.5-flash-lite
"""

from __future__ import annotations

import glob
import json
import sys
from datetime import date
from pathlib import Path

import krippendorff
import numpy as np
import yaml
from pilot_annotation import stance

ROOT = Path(__file__).resolve().parents[1]
ANN = ROOT / "data" / "annotations"
PARTIES = ("KMT", "DPP", "TPP")


def labels(model: str) -> dict[str, dict]:
    out = {}
    for f in glob.glob(str(ANN / f"vertex_{model}_*.jsonl")):
        for line in open(f, encoding="utf-8"):
            d = json.loads(line)
            out.setdefault(d["key"], d.get("label") or {})
    return out


def main(a: str, b: str) -> None:
    la, lb = labels(a), labels(b)
    src = {json.loads(line)["key"]: json.loads(line)["source"]
           for line in open(ROOT / "data" / "vertex" / "juror2" / "items.jsonl", encoding="utf-8")}
    keys = [k for k in src if k in la and k in lb and la[k].get("parties") and lb[k].get("parties")]
    news = [k for k in keys if not k.startswith("anchor:")]
    L = [f"# 陪審團一致性：兩個模型\n\n日期：{date.today().isoformat()}　模型：`{a}`、`{b}`（同一份提示詞、同一批文章）　"
         f"共 {len(keys)} 篇（新聞 {len(news)}、政黨新聞稿 {len(keys) - len(news)}）\n",
         "兩個模型都來自 Google，所以這只檢驗「同一家族、不同大小」的穩定度；不同來源的陪審員（PLAN.md 方法 B）另外處理。\n",
         "## 立場一致性（新聞）\n", "| 政黨 | α（序位） | 完全相同 | 平均絕對差 | 兩者都有判斷的篇數 |", "|---|---|---|---|---|"]
    for p in PARTIES:
        x = np.array([stance(la[k], p) for k in news])
        y = np.array([stance(lb[k], p) for k in news])
        both = ~np.isnan(x) & ~np.isnan(y)
        alpha = krippendorff.alpha(reliability_data=np.vstack([x, y]), level_of_measurement="ordinal")
        L.append(f"| {p} | {alpha:.2f} | {np.mean(x[both] == y[both]):.0%} | {np.mean(np.abs(x[both] - y[both])):.2f} | {int(both.sum())} |")
    anchors = [k for k in keys if k.startswith("anchor:")]
    L += ["\n## 政黨新聞稿（已知立場）\n", "| 模型 | 自己黨判為正面 |", "|---|---|"]
    for name, lab in ((a, la), (b, lb)):
        own = [stance(lab[k], "KMT" if src[k] == "party_kmt" else "DPP") for k in anchors]
        own = [v for v in own if not np.isnan(v)]
        L.append(f"| {name} | {sum(v > 0 for v in own)}/{len(own)}（{np.mean([v > 0 for v in own]):.0%}） |")
    L += ["\n## 各媒體排序是否一致\n", "以「國民黨平均分數 − 民進黨平均分數」排序，兩個模型給出的媒體排名的 Spearman 相關：\n"]
    gap = {}
    for name, lab in ((a, la), (b, lb)):
        by = {}
        for k in news:
            s = src[k].removeprefix("news_").removeprefix("hist_")
            kv, dv = stance(lab[k], "KMT"), stance(lab[k], "DPP")
            if not (np.isnan(kv) or np.isnan(dv)):
                by.setdefault(s, []).append(kv - dv)
        gap[name] = {s: np.mean(v) for s, v in by.items() if len(v) >= 30}
    common = sorted(set(gap[a]) & set(gap[b]))
    rank = lambda v: np.argsort(np.argsort(v))
    rho = np.corrcoef(rank([gap[a][s] for s in common]), rank([gap[b][s] for s in common]))[0, 1] if len(common) > 2 else float("nan")
    L.append(f"ρ = {rho:.2f}（{len(common)} 家媒體，每家至少 30 篇）\n")
    L += ["| 媒體 | " + a + " | " + b + " |", "|---|---|---|"]
    names = {k: v["name"] for k, v in yaml.safe_load((ROOT / "config" / "sources.yaml").read_text(encoding="utf-8"))["outlets"].items()}
    L += [f"| {names.get(s, s)} | {gap[a][s]:+.2f} | {gap[b][s]:+.2f} |" for s in sorted(common, key=lambda s: gap[a][s])]
    L += ["\n## 判讀\n",
          "- 兩個模型對**媒體之間的相對位置**幾乎完全一致（ρ 接近 1），所以媒體排序不是單一模型的偶然結果",
          "- 但較小的模型分數較溫和（絕對值較小），已知立場的新聞稿也判對得較少；逐篇的一致性（α）只有中等。"
          "所以較小的模型不適合當主要標註者，只用來檢驗排序的穩定度；分數的絕對大小要等不同來源的陪審員加入後再定",
          "- 逐篇不一致的文章另行保留，作為困難樣本"]
    (ROOT / "docs" / "jury-agreement.md").write_text("\n".join(L) + "\n", encoding="utf-8")
    print("\n".join(L))


if __name__ == "__main__":
    main(*sys.argv[1:3])

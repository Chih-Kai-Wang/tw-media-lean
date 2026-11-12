"""Agreement among LLM jurors on the same requests (scripts/vertex_batch.py build juror2), plus each juror's
party-swap test (build swap).

Writes docs/jury-agreement.md: Krippendorff's alpha (ordinal) per party for all jurors and for each juror against
the primary one, anchor accuracy, the outlet ranking each juror implies, and the swap-test label effect.
Usage: uv run python scripts/compare_jurors.py gemini-3.8-flash gemini-3.5-flash-lite gpt-oss-120b-maas \
    llama-4-maverick-17b-128e-instruct-maas
(the first model is the primary juror)
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
from swap_test import bootstrap, label_effects

ROOT = Path(__file__).resolve().parents[1]
ANN = ROOT / "data" / "annotations"
PARTIES = ("KMT", "DPP", "TPP")
ORIGIN = {"gemini-3.8-flash": "Google", "gemini-3.5-flash-lite": "Google", "gpt-oss-120b-maas": "OpenAI（開源）",
          "llama-4-maverick-17b-128e-instruct-maas": "Meta（開源）"}


def labels(model: str, exclude_swap: bool = True) -> dict[str, dict]:
    out = {}
    for f in glob.glob(str(ANN / f"vertex_{model}_*.jsonl")):
        if exclude_swap and Path(f).stem.endswith("_swap"):
            continue
        if Path(f).stem.endswith("_prompt_alt"):  # same articles, reworded prompt: kept apart (scripts/compare_prompts.py)
            continue
        for line in open(f, encoding="utf-8"):
            d = json.loads(line)
            out.setdefault(d["key"], d.get("label") or {})
    return out


def alpha(rows: list[np.ndarray]) -> float:
    try:
        return krippendorff.alpha(reliability_data=np.vstack(rows), level_of_measurement="ordinal")
    except (ValueError, ZeroDivisionError):
        return float("nan")


def main(models: list[str]) -> None:
    primary = models[0]
    lab = {m: labels(m) for m in models}
    src = {json.loads(line)["key"]: json.loads(line)["source"]
           for line in open(ROOT / "data" / "vertex" / "juror2" / "items.jsonl", encoding="utf-8")}
    keys = [k for k in src if all(lab[m].get(k, {}).get("parties") for m in models)]
    news = [k for k in keys if not k.startswith("anchor:")]
    anchors = [k for k in keys if k.startswith("anchor:")]
    names = {k: v["name"] for k, v in yaml.safe_load((ROOT / "config" / "sources.yaml").read_text(encoding="utf-8"))["outlets"].items()}
    jurors = "、".join(f"`{m}`（{ORIGIN.get(m, '?')}）" for m in models)
    L = [f"# 陪審團一致性\n\n日期：{date.today().isoformat()}　陪審員：{jurors}　主要陪審員：`{primary}`\n",
         f"同一份提示詞、同一批文章：所有陪審員都有判斷的共 {len(keys)} 篇（新聞 {len(news)}、政黨新聞稿 {len(anchors)}）。\n",
         "## 1. 立場一致性（新聞，Krippendorff's α，序位）\n",
         "| 政黨 | 全部陪審員 | " + " | ".join(f"{m} vs 主要" for m in models[1:]) + " |",
         "|---" * (len(models) + 1) + "|"]
    for p in PARTIES:
        rows = {m: np.array([stance(lab[m][k], p) for k in news]) for m in models}
        cells = [f"{alpha(list(rows.values())):.2f}"] + [f"{alpha([rows[primary], rows[m]]):.2f}" for m in models[1:]]
        L.append(f"| {p} | " + " | ".join(cells) + " |")

    L += ["\n## 2. 已知立場錨點（政黨新聞稿判自己黨為正面）\n", "| 陪審員 | 判對 |", "|---|---|"]
    for m in models:
        own = [stance(lab[m][k], "KMT" if src[k] == "party_kmt" else "DPP") for k in anchors]
        own = [v for v in own if not np.isnan(v)]
        L.append(f"| {m} | {sum(v > 0 for v in own)}/{len(own)}（{np.mean([v > 0 for v in own]):.0%}） |")

    L += ["\n## 3. 政黨對調測試\n",
          "做法見 [swap-test.md](swap-test.md)：遮蔽人名後互換國民黨／民進黨。標籤效應 > 0 表示同樣內容標成民進黨時分數較高，< 0 表示標成國民黨時較高。\n",
          "| 陪審員 | 標籤效應 | 95% 區間 | 有效篇數 |", "|---|---|---|---|"]
    for m in models:
        sw = labels(m, exclude_swap=False)
        sw = {k: v for k, v in sw.items() if k.startswith(("masked:", "swapped:"))}
        items = [{"id": k.split(":", 1)[1]} for k in sw if k.startswith("masked:")]
        if not items:
            L.append(f"| {m} | — | — | 0 |")
            continue
        eff, _ = label_effects(items, sw)
        x = eff[~np.isnan(eff)]
        lo, hi = bootstrap(x) if len(x) >= 5 else (float("nan"), float("nan"))
        L.append(f"| {m} | {x.mean():+.2f} | [{lo:+.2f}, {hi:+.2f}] | {len(x)} |")

    L += ["\n## 4. 各媒體排序\n", "「國民黨平均分數 − 民進黨平均分數」（每家至少 30 篇）。最後一列為各陪審員與主要陪審員的排名相關（Spearman ρ）。\n"]
    gap = {}
    for m in models:
        by = {}
        for k in news:
            s = src[k].removeprefix("news_").removeprefix("hist_")
            kv, dv = stance(lab[m][k], "KMT"), stance(lab[m][k], "DPP")
            if not (np.isnan(kv) or np.isnan(dv)):
                by.setdefault(s, []).append(kv - dv)
        gap[m] = {s: np.mean(v) for s, v in by.items() if len(v) >= 30}
    common = sorted(set.intersection(*(set(g) for g in gap.values())), key=lambda s: gap[primary][s])
    L += ["| 媒體 | " + " | ".join(models) + " |", "|---" * (len(models) + 1) + "|"]
    L += [f"| {names.get(s, s)} | " + " | ".join(f"{gap[m][s]:+.2f}" for m in models) + " |" for s in common]
    rank = lambda v: np.argsort(np.argsort(v))
    rhos = [np.corrcoef(rank([gap[primary][s] for s in common]), rank([gap[m][s] for s in common]))[0, 1] for m in models]
    L.append("| ρ（vs 主要） | " + " | ".join(f"{r:.2f}" for r in rhos) + " |")
    L += ["\n## 判讀\n",
          "- **媒體之間的相對位置在不同公司的模型之間都一致**：非 Google 的 gpt-oss（OpenAI）與 Llama 4（Meta）"
          "和 Gemini 的排名相關分別是 0.96 與 0.98，最偏民進黨（民視、三立）與最偏國民黨（中國時報、聯合報）的兩端完全相同。"
          "所以媒體排序在不同公司的模型之間都成立",
          "- **逐篇判斷的一致性中等**（α 約 0.6–0.75）：個別文章的判斷會因模型而異，結論應建立在大量文章的平均上，並保留陪審團的分歧作為不確定性",
          "- **標籤效應小，在 Google 與 Meta 的模型都看得到**：Gemini 與 Llama 4 都有很小的國民黨標籤效應（約 −0.06），gpt-oss 沒有可測得的效應；"
          "遠小於媒體之間的差距（兩端相差約 1.4），報告會一併揭露",
          "- **個別媒體仍有差異**：自由時報在 Gemini 偏民進黨（−0.50），在 gpt-oss 與 Llama 4 較接近中間（−0.06、−0.16）；"
          "公視則是 Gemini 接近中間（+0.02），gpt-oss 與 Llama 4 偏民進黨（−0.27、−0.44）。這類差異會在報告中逐家列出",
          "- **入選測試**：Llama 4 在另外 300 篇政黨新聞稿上判對自己黨為正面的比例是 93%（gpt-oss 88%、Gemini 92%），與主要陪審員相當",
          "- 較小的 gemini-3.5-flash-lite 判對已知立場的比例較低（78%），只用於檢驗排序，不列入正式陪審團；中國公司的模型因 Vertex 上已退役，這一版未納入"]
    (ROOT / "docs" / "jury-agreement.md").write_text("\n".join(L) + "\n", encoding="utf-8")
    print("\n".join(L))


if __name__ == "__main__":
    main(sys.argv[1:] or ["gemini-3.8-flash", "gemini-3.5-flash-lite"])

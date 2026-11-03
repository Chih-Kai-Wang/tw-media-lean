"""Report on the first bulk Vertex annotation: anchors, party-swap test, outlets by period.

Reads data/annotations/vertex_<model>_{anchors,swap,history,live_*}.jsonl and writes docs/bulk-annotation.md
(aggregates only). Usage: uv run python scripts/report_bulk.py [model]
"""

from __future__ import annotations

import glob
import json
import sys
from collections import defaultdict
from datetime import date
from pathlib import Path

import numpy as np
import yaml
from pilot_annotation import stance
from swap_test import bootstrap, label_effects

ROOT = Path(__file__).resolve().parents[1]
ANN = ROOT / "data" / "annotations"
RIVAL = {"KMT": "DPP", "DPP": "KMT"}
# who governed (central government) in each year, for reading the time series
GOV = {y: "KMT" for y in range(2008, 2016)} | {y: "DPP" for y in range(2016, 2027)}


def labels(pattern: str) -> dict[str, dict]:
    out = {}
    for f in glob.glob(str(ANN / pattern)):
        for line in open(f, encoding="utf-8"):
            d = json.loads(line)
            out[d["key"]] = d.get("label") or {}
    return out


def meta() -> dict[str, tuple[str, str]]:
    """article id -> (outlet key, publication date)."""
    out = {}
    for f in glob.glob(str(ROOT / "data" / "raw" / "*" / "*.jsonl")):
        src = Path(f).parent.name
        if not src.startswith(("news_", "hist_", "party_")):
            continue
        outlet = src.split("_", 1)[1].removesuffix("_wb")
        for line in open(f, encoding="utf-8"):
            r = json.loads(line)
            if r.get("id"):
                out[r["id"]] = (outlet, r.get("published") or "")
    return out


def fmt(x: float) -> str:
    return "—" if x is None or np.isnan(x) else f"{x:+.2f}"


def main(model: str = "gemini-3.8-flash") -> None:
    names = {k: v["name"] for k, v in yaml.safe_load((ROOT / "config" / "sources.yaml").read_text(encoding="utf-8"))["outlets"].items()}
    m = meta()
    L = [f"# 第一批大量標註結果\n\n日期：{date.today().isoformat()}　模型：`{model}`（Vertex AI 批次）　codebook v0.1　"
         "程式：`scripts/vertex_batch.py`、`scripts/report_bulk.py`\n",
         "只有一個模型的標註，其他陪審員還沒加入；以下用來檢查標註是否可信，以及看出初步的模式，不是最終結論。\n"]

    # 1. anchors by year
    anc = labels(f"vertex_{model}_anchors.jsonl")
    by_year = defaultdict(lambda: {"own": [], "opp": []})
    for key, lab in anc.items():
        aid = key.split(":", 1)[1]
        if aid not in m:
            continue
        party = m[aid][0].upper()
        year = m[aid][1][:4]
        by_year[(party, year)]["own"].append(stance(lab, party))
        by_year[(party, year)]["opp"].append(stance(lab, RIVAL[party]))
    L += ["## 1. 已知立場錨點：政黨新聞稿\n",
          "政黨自己的新聞稿，對自己的黨應判為正面、對主要對手應判為負面。依年份分開，可以看出模型在不同執政期是否一樣可靠。\n",
          "| 年份 | 國民黨稿：自己正面 | 國民黨稿：民進黨負面 | 民進黨稿：自己正面 | 民進黨稿：國民黨負面 | 執政黨 |",
          "|---|---|---|---|---|---|"]
    rate = lambda xs, f: (lambda v: f"{np.mean([f(x) for x in v]):.0%}（{len(v)}）" if v else "—")([x for x in xs if not np.isnan(x)])
    years = sorted({y for _, y in by_year})
    tot = {"KMT": [0, 0], "DPP": [0, 0]}
    for y in years:
        k, d = by_year.get(("KMT", y)), by_year.get(("DPP", y))
        row = [y]
        for cell in (k, d):
            row += [rate(cell["own"], lambda x: x > 0), rate(cell["opp"], lambda x: x < 0)] if cell else ["—", "—"]
        row.append({"KMT": "國民黨", "DPP": "民進黨"}.get(GOV.get(int(y)), "—"))
        L.append("| " + " | ".join(row) + " |")
    for party in ("KMT", "DPP"):
        own = [x for (p, _), c in by_year.items() if p == party for x in c["own"] if not np.isnan(x)]
        tot[party] = [sum(x > 0 for x in own), len(own)]
    L.append(f"\n合計：國民黨稿判自己正面 {tot['KMT'][0]}/{tot['KMT'][1]}，民進黨稿判自己正面 {tot['DPP'][0]}/{tot['DPP'][1]}。\n")

    # 2. swap test
    sw = labels(f"vertex_{model}_swap.jsonl")
    items = [{"id": k.split(":", 1)[1]} for k in sw if k.startswith("masked:")]
    eff, same = label_effects(items, sw)
    ok = ~np.isnan(eff)
    if ok.sum() >= 5:
        lo, hi = bootstrap(eff[ok])
        L += ["## 2. 政黨對調測試\n",
              "做法同 [swap-test.md](swap-test.md)：先遮蔽人名，再把國民黨／民進黨相關字詞全部互換。**標籤效應**＝同樣內容被標成民進黨時，比被標成國民黨時高幾分（−2 到 +2 量尺）；0 表示沒有偏誤。\n",
              "| 模型 | 標籤效應 | 95% 區間 | 有效篇數 | 判斷完全一致 |", "|---|---|---|---|---|",
              f"| {model} | {eff[ok].mean():+.2f} | [{lo:+.2f}, {hi:+.2f}] | {int(ok.sum())} | {same[ok].mean():.0%} |\n"]
        if lo > 0 or hi < 0:
            side = "民進黨" if lo > 0 else "國民黨"
            L += [f"95% 區間不含 0：同樣的內容標成{side}時，分數平均高 {abs(eff[ok].mean()):.2f} 分。偏誤很小（量尺寬 4 分，"
                  "約是各媒體之間差距的十分之一），但在統計上確實存在。處理方式：最終分數會扣除這個標籤效應；"
                  "加入其他陪審員後，各模型分別估計並在陪審團層級平均，偏誤方向不同的模型可以互相抵消。"
                  "先前 48 篇的小樣本測試（swap-test.md）區間包含 0，是因為樣本太小、測不出這麼小的效應。\n"]

    # 3. outlets by period
    news = labels(f"vertex_{model}_history.jsonl") | labels(f"vertex_{model}_live_*.jsonl")
    cell = defaultdict(lambda: {"KMT": [], "DPP": [], "TPP": []})
    for key, lab in news.items():
        aid = key.split(":", 1)[1]
        if aid not in m or not lab.get("parties"):
            continue
        outlet, pub = m[aid]
        y = pub[:4]
        period = "2012–15" if "2012" <= y <= "2015" else "2016–19" if y <= "2019" else "2020–23" if y <= "2023" else "2024–26" if y <= "2026" else None
        if not period:
            continue
        for p in ("KMT", "DPP", "TPP"):
            v = stance(lab, p)
            if not np.isnan(v):
                cell[(outlet, period)][p].append(v)
    periods = ["2012–15", "2016–19", "2020–23", "2024–26"]
    L += ["## 3. 各媒體、各時期\n",
          "表中為「國民黨平均分數 − 民進黨平均分數」：正值表示對國民黨的呈現比民進黨正面，負值相反。括號內為同時有兩黨分數的最少篇數。"
          "這是未經動態模型平滑、單一模型的原始平均，樣本少於 30 篇的格子不列。2012–15 為國民黨執政、2016 起為民進黨執政。\n",
          "| 媒體 | " + " | ".join(periods) + " |", "|---" * (len(periods) + 1) + "|"]
    for outlet in sorted({o for o, _ in cell}, key=lambda o: names.get(o, o)):
        row = [names.get(outlet, outlet)]
        for per in periods:
            c = cell.get((outlet, per))
            n = min(len(c["KMT"]), len(c["DPP"])) if c else 0
            row.append(f"{np.mean(c['KMT']) - np.mean(c['DPP']):+.2f}（{n}）" if n >= 30 else "—")
        L.append("| " + " | ".join(row) + " |")
    L += ["\n## 限制\n",
          "- 只有一個 LLM 的標註；陪審團（多個不同來源的模型）與一致性檢驗還沒做",
          "- 歷史樣本仍在回補，各家各時期的篇數不同；聯合報、鏡週刊與中央社 2014 年以前來自 Internet Archive，數量較少",
          "- 「政治新聞」的初篩各家不同，這裡納入所有提及兩黨的文章",
          "- 原始平均會受議題組成影響：執政黨是施政與政策爭議的主角，較容易被批評。例如 2012–15 國民黨執政時，中國時報的分數接近 0，"
          "2016 年民進黨執政後轉為 +0.5 左右；這個變化有多少是媒體立場、多少是「批評執政者」的一般傾向，要用議題控制與跨媒體比較來分開",
          "- 正式結果要用動態模型、控制議題，並附不確定區間"]
    (ROOT / "docs" / "bulk-annotation.md").write_text("\n".join(L) + "\n", encoding="utf-8")
    print("\n".join(L))


if __name__ == "__main__":
    main(*sys.argv[1:])

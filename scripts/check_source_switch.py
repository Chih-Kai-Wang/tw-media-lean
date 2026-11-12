"""Why the trends step up when the data switch from the historical sample to live collection (docs/source-switch.md).

Before 2026-10 an outlet's articles come from the monthly historical sample (twmedia history), which keeps only
politics-section articles; from 2026-10-31 they come from live collection (twmedia news), which keeps every
section. The decision-model trends jump at that boundary, mostly upward for KMT. Three checks, decision model
v1 throughout, articles the model calls political and that mention the party:

1. Same pipeline restricted to the politics section: live 2026-10/11 politics-section articles (URL or
   category, the live equivalent of each outlet's history rule) vs historical 2026-08/09.
2. Model vs teacher on the live batches the teacher labelled (same articles).
3. The usual pre-election movement: in the historical sample, Oct-Nov minus Aug-Sep in 2014, 2018 and 2022.

    uv run python scripts/check_source_switch.py

docs/source-switch.md gets the per-outlet tables (published before the election since 2026-11-12, see PLAN.md);
--summary writes only medians and ranges across outlets there. The per-outlet version is always also written to
private/source-switch-full.md.
"""

from __future__ import annotations

import argparse
import glob
import json
import re
from collections import defaultdict
from datetime import date
from pathlib import Path

import numpy as np
import yaml

ROOT = Path(__file__).resolve().parents[1]
MODEL = "tw-media-lean-v1"
TEACHER = "gemini-3.8-flash"
YEARS = ("2014", "2018", "2022", "2026")  # local elections, all held in late November
PARTIES = ("KMT", "DPP")
NAME = {"KMT": "國民黨", "DPP": "民進黨"}
# Live records carry the URL and the site's category; these match each outlet's history rule (config/sources.yaml).
LIVE_URL = {"ltn": r"/news/politics/", "udn": r"/story/6656/", "ebc": r"/news/politics/", "tvbs": r"/politics/",
            "cna": r"/news/aipl/"}
LIVE_CAT = {"ettoday": "政治", "setn": "政治", "chinatimes": "政治", "ftv": "政治", "pts": "政治", "mirror": "政治", "ctinews": "要聞"}


def stances(d: dict) -> dict[str, float]:
    if d["probs"]["political"][1] < 0.5:
        return {}
    ps = d["label"]["parties"]
    return {p: ps[p]["stance"] for p in PARTIES if ps[p]["mentioned"] and ps[p]["stance"] is not None}


def live_section(outlet: str, r: dict) -> str:
    url = f"{r.get('final_url') or ''} {r.get('url') or ''}"
    cat = r.get("categories")
    cat = " ".join(cat) if isinstance(cat, list) else str(cat or "")
    if outlet in LIVE_URL:
        return "pol" if re.search(LIVE_URL[outlet], url) else "other"
    if outlet in LIVE_CAT:
        return "pol" if LIVE_CAT[outlet] in cat else "other"
    return "unknown"


def fmt(v: list[float]) -> str:
    return f"{np.mean(v):+.2f}（{len(v):,}）" if v else "—"


def summary(rows: list[tuple[str, float]], label: str) -> str:
    v = [x for _, x in rows]
    return f"| {label} | {len(v)} | {np.median(v):+.2f} | {min(v):+.2f} 至 {max(v):+.2f} |"


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--summary", action="store_true", help="docs/ gets medians and ranges across outlets only")
    full = not ap.parse_args().summary
    model = {}
    for f in glob.glob(str(ROOT / "data" / "annotations" / f"model_{MODEL}_*.jsonl")):
        for line in open(f, encoding="utf-8"):
            d = json.loads(line)
            model[d["key"].split(":", 1)[1]] = d
    names = {k: v["name"] for k, v in yaml.safe_load((ROOT / "config" / "sources.yaml").read_text(encoding="utf-8"))["outlets"].items()}

    switch, season, same, outlet_of = defaultdict(list), defaultdict(list), defaultdict(list), {}
    for f in glob.glob(str(ROOT / "data" / "raw" / "news_*" / "*.jsonl")) + glob.glob(str(ROOT / "data" / "raw" / "hist_*" / "*.jsonl")):
        kind, outlet = Path(f).parent.name.split("_", 1)
        outlet = outlet.removesuffix("_wb")
        for line in open(f, encoding="utf-8"):
            r = json.loads(line)
            if r["id"] not in model:
                continue
            outlet_of[r["id"]] = outlet
            pub = (r.get("published") or "")[:7]
            s = stances(model[r["id"]])
            if kind == "hist" and pub in ("2026-08", "2026-09"):
                grp = "hist"
            elif kind == "news" and pub in ("2026-10", "2026-11"):
                grp = live_section(outlet, r)
            else:
                grp = None
            if kind == "hist" and pub[:4] in YEARS and pub[5:7] in ("08", "09", "10", "11"):
                for p, v in s.items():
                    season[(pub[:4], outlet, p, "before" if pub[5:7] < "10" else "after")].append(v)
            if pub == "2026-10" and (kind == "hist" or grp == "pol"):  # the same month through both pipelines
                for p, v in s.items():
                    same[(outlet, p, kind)].append(v)
            if grp:
                for p, v in s.items():
                    switch[(outlet, p, grp)].append(v)

    L = [f"# 資料來源切換前後的變化\n\n日期：{date.today().isoformat()}　模型：`{MODEL}`　程式：`scripts/check_source_switch.py`\n",
         "2026 年 10 月以前，每家媒體的文章來自每月的歷史抽樣，只收政治版；2026-10-31 起改為即時收集，各版面都收。"
         "趨勢在這個分界上跳動，國民黨多半往上。這份文件拆解原因。以下都只計決策模型判為政治新聞、且提到該黨的文章。\n",
         "## 1. 只看政治版\n",
         "即時收集的文章依網址或網站分類標出政治版，規則近似歷史抽樣的條件（`config/sources.yaml`；中國時報與公視的歷史抽樣另外收進含政黨關鍵詞的其他版面文章）。"
         "風傳媒的即時資料沒有可對應的分類，不列入；TVBS 與鏡週刊 2026 年 8–9 月沒有歷史樣本。\n",
         "| 媒體 | 政黨 | 歷史 8–9 月 | 即時 政治版 | 即時 其他版 | 變化（全部） | 變化（政治版） |", "|---|---|---|---|---|---|---|"]
    steps, pub1 = defaultdict(list), defaultdict(list)
    for o in sorted({k[0] for k in switch}, key=lambda o: names.get(o, o)):
        for p in PARTIES:
            h, po, ot = (switch.get((o, p, g), []) for g in ("hist", "pol", "other"))
            if not h or not po:
                continue
            a, b = np.mean(po + ot) - np.mean(h), np.mean(po) - np.mean(h)
            steps[p].append(b)
            pub1[(p, "all")].append((o, a))
            pub1[(p, "pol")].append((o, b))
            L.append(f"| {names.get(o, o)} | {NAME[p]} | {fmt(h)} | {fmt(po)} | {fmt(ot)} | {a:+.2f} | {b:+.2f} |")
    L.append("\n政治版變化的中位數：" + "，".join(f"{NAME[p]} {np.median(steps[p]):+.2f}" for p in PARTIES) + "。\n")

    L += ["## 2. 模型與老師在同一批即時新聞上的差異\n",
          f"選舉期間每週的即時新聞批次由老師模型 `{TEACHER}` 標註（[drift-monitor.md](drift-monitor.md)）。差異 = 模型平均 − 老師平均。\n",
          "| 媒體 | 政黨 | 篇數 | 老師 | 模型 | 差異 |", "|---|---|---|---|---|---|"]
    tm = defaultdict(lambda: ([], []))
    for f in glob.glob(str(ROOT / "data" / "annotations" / f"vertex_{TEACHER}_live_*.jsonl")):
        for line in open(f, encoding="utf-8"):
            d = json.loads(line)
            aid, lab = d["key"].split(":", 1)[1], d.get("label") or {}
            if aid not in model or aid not in outlet_of or not lab.get("political"):
                continue
            s = stances(model[aid])
            for p in PARTIES:
                t = ((lab.get("parties") or {}).get(p) or {}).get("stance")
                if t is not None and p in s:
                    for o in (outlet_of[aid], "*"):
                        tm[(o, p)][0].append(float(t))
                        tm[(o, p)][1].append(s[p])
    pub2 = defaultdict(list)
    for (o, p) in sorted(tm, key=lambda k: (k[0] == "*", names.get(k[0], k[0]), k[1])):
        t, e = map(np.array, tm[(o, p)])
        L.append(f"| {'全部' if o == '*' else names.get(o, o)} | {NAME[p]} | {len(t):,} | {t.mean():+.2f} | {e.mean():+.2f} | {e.mean() - t.mean():+.2f} |")
        if o == "*":
            pub2[p].append(f"| {NAME[p]} | {len(t):,} | {t.mean():+.2f} | {e.mean():+.2f} | {e.mean() - t.mean():+.2f} |")
        else:
            pub2[(p, "outlets")].append((o, e.mean() - t.mean()))

    L += ["\n## 3. 過去九合一選舉的選前變化\n",
          "同一套歷史抽樣，10–11 月平均減 8–9 月平均（每家每期至少 20 篇），列出各媒體的中位數與範圍。"
          "這三年與 2026 年都在 11 月底投票，所以 10–11 月同樣是投票前最後兩個月。\n",
          "| 年 | 政黨 | 媒體數 | 中位數 | 範圍 |", "|---|---|---|---|---|"]
    for y in YEARS:
        for p in PARTIES:
            v = [np.mean(season[(y, o, p, "after")]) - np.mean(season[(y, o, p, "before")])
                 for o in {k[1] for k in season if k[0] == y}
                 if len(season.get((y, o, p, "before"), [])) >= 20 and len(season.get((y, o, p, "after"), [])) >= 20]
            if v:
                L.append(f"| {y if y != '2026' else '2026（歷史抽樣補到的月份）'} | {NAME[p]} | {len(v)} | {np.median(v):+.2f} | {min(v):+.2f} 至 {max(v):+.2f} |")

    T4 = ["\n## 4. 同一個月，兩種收集方式\n",
          "2026 年 10 月同時有歷史抽樣（事後補抽，政治版）與即時收集的政治版文章。差異 = 即時政治版平均 − 歷史抽樣平均；"
          "兩者是同月份、同版面的不同文章，差異反映收集方式本身。\n",
          "| 媒體 | 政黨 | 歷史抽樣 | 即時 政治版 | 差異 |", "|---|---|---|---|---|"]
    pub4 = defaultdict(list)
    for o in sorted({k[0] for k in same}, key=lambda o: names.get(o, o)):
        for p in PARTIES:
            h, n = same.get((o, p, "hist"), []), same.get((o, p, "news"), [])
            if len(h) >= 20 and len(n) >= 20:
                pub4[p].append((o, np.mean(n) - np.mean(h)))
                T4.append(f"| {names.get(o, o)} | {NAME[p]} | {fmt(h)} | {fmt(n)} | {np.mean(n) - np.mean(h):+.2f} |")
    if pub4:  # needs the October historical sample
        L += T4

    L += ["\n## 判讀\n",
          "- **版面組成**：即時收集包含地方、社會等版面，那些版面的分數可能與政治版不同。聯合報最明顯：只看政治版，國民黨與 8–9 月幾乎相同，"
          "整體的上升幾乎全來自其他版面。但多數媒體只看政治版，變化與全部文章差不多，所以版面組成只解釋一部分",
          "- **模型偏寬鬆**：在即時新聞上，模型給國民黨的分數平均比老師高（表 2），與漂移監測一致，各媒體程度不同。"
          "依漂移監測的規則，若下週仍超過門檻，就用即時批次的老師標籤重新校準",
          "- **選前的固定變化**：同一套歷史抽樣在 2014、2018、2022 年也看得到國民黨選前上升（表 3）。今年政治版的上升大於這個幅度，"
          "差距與模型偏寬鬆的幅度相近",
          "- 因此，分界前後的變化不能直接解讀為媒體傾向改變。網站在這段期間加註說明；重新校準之後，再以政治版的即時文章重算這段趨勢並更新本文件"]
    full_text = "\n".join(L) + "\n"
    private = ROOT / "private" / "source-switch-full.md"
    private.parent.mkdir(exist_ok=True)
    private.write_text(full_text, encoding="utf-8")
    if full:
        (ROOT / "docs" / "source-switch.md").write_text(full_text, encoding="utf-8")
        print(full_text)
        return
    head, rest = full_text.split("## 1. 只看政治版", 1)
    interp = rest[rest.index("## 判讀"):]
    P = [head.rstrip() + "\n",
         "這裡只列跨媒體的中位數與範圍。\n",
         "## 1. 只看政治版\n",
         "即時收集的文章依網址或網站分類標出政治版，規則近似歷史抽樣的條件（`config/sources.yaml`；中國時報與公視的歷史抽樣另外收進含政黨關鍵詞的其他版面文章）。變化 = 即時 2026 年 10–11 月平均 − 歷史抽樣 8–9 月平均。"
         "風傳媒的即時資料沒有可對應的分類；TVBS 與鏡週刊 2026 年 8–9 月沒有歷史樣本，三家都不列入。\n",
         "| 項目 | 媒體數 | 中位數 | 範圍 |", "|---|---|---|---|"]
    for p in PARTIES:
        P += [summary(pub1[(p, "all")], f"{NAME[p]}，全部文章"), summary(pub1[(p, "pol")], f"{NAME[p]}，只看政治版")]
    P += ["\n聯合報是唯一只看政治版後變化接近 0 的媒體（國民黨約 −0.04），其餘媒體只看政治版，變化與全部文章差不多。\n",
          "## 2. 模型與老師在同一批即時新聞上的差異\n",
          f"選舉期間每週的即時新聞批次由老師模型 `{TEACHER}` 標註（[drift-monitor.md](drift-monitor.md)）。差異 = 模型平均 − 老師平均。\n",
          "| 政黨 | 篇數 | 老師 | 模型 | 差異 |", "|---|---|---|---|---|", *pub2["KMT"], *pub2["DPP"],
          "\n各媒體的差異：", ]
    P[-1] += "；".join(f"{NAME[p]}中位數 {np.median([x for _, x in pub2[(p, 'outlets')]]):+.2f}（{min(x for _, x in pub2[(p, 'outlets')]):+.2f} 至 {max(x for _, x in pub2[(p, 'outlets')]):+.2f}）" for p in PARTIES) + "。\n"
    P += [rest[rest.index("## 3."):rest.index("## 4." if pub4 else "## 判讀")].rstrip() + "\n"]
    if pub4:
        P += ["## 4. 同一個月，兩種收集方式\n",
              "2026 年 10 月同時有歷史抽樣（事後補抽，政治版）與即時收集的政治版文章。差異 = 即時政治版平均 − 歷史抽樣平均。\n",
              "| 項目 | 媒體數 | 中位數 | 範圍 |", "|---|---|---|---|"] + [summary(pub4[p], NAME[p]) for p in PARTIES if pub4[p]] + [""]
    P += [interp]
    (ROOT / "docs" / "source-switch.md").write_text("\n".join(P), encoding="utf-8")
    print("\n".join(P))


if __name__ == "__main__":
    main()

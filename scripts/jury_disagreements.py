"""Articles on which the formal LLM jurors disagree (PLAN.md §D: 意見不一致的文章另行整理公開).

Reads the juror2 set (the same news articles judged by every juror, scripts/vertex_batch.py build juror2) and lists
each article x party where the jurors' stances are at least 2 points apart or point in opposite directions.
Writes data/derived/jury_disagreements.csv (outlet, publication date, URL, title, each juror's stance; no article
text, as PLAN.md requires) and docs/jury-disagreements.md (definition and counts).

    uv run python scripts/jury_disagreements.py
"""

from __future__ import annotations

import csv
import glob
import json
from collections import Counter
from datetime import date
from pathlib import Path

import numpy as np
import yaml
from compare_jurors import ORIGIN, labels
from pilot_annotation import stance

ROOT = Path(__file__).resolve().parents[1]
JURORS = ["gemini-3.8-flash", "gpt-oss-120b-maas", "llama-4-maverick-17b-128e-instruct-maas"]
PARTIES = ("KMT", "DPP", "TPP")
NAME = {"KMT": "國民黨", "DPP": "民進黨", "TPP": "民眾黨"}


def article_meta(wanted: dict[str, str]) -> dict[str, dict]:
    """key -> {url, title, published} for the wanted keys (key -> raw source directory)."""
    out = {}
    for src in sorted(set(wanted.values())):
        ids = {k.split(":", 1)[1]: k for k, s in wanted.items() if s == src}
        for f in glob.glob(str(ROOT / "data" / "raw" / src / "*.jsonl")):
            for line in open(f, encoding="utf-8"):
                i = line.find('"id": "')
                aid = line[i + 7 : line.find('"', i + 7)] if i >= 0 else ""
                if aid in ids and ids[aid] not in out:
                    r = json.loads(line)
                    out[ids[aid]] = {"url": r.get("final_url") or r.get("url") or "", "title": r.get("title") or "",
                                     "published": (r.get("published") or "")[:10]}
    return out


def main() -> None:
    lab = {m: labels(m) for m in JURORS}
    src = {json.loads(line)["key"]: json.loads(line)["source"]
           for line in open(ROOT / "data" / "vertex" / "juror2" / "items.jsonl", encoding="utf-8")}
    news = [k for k in src if not k.startswith("anchor:") and all(lab[m].get(k, {}).get("parties") for m in JURORS)]
    names = {k: v["name"] for k, v in yaml.safe_load((ROOT / "config" / "sources.yaml").read_text(encoding="utf-8"))["outlets"].items()}
    outlet = lambda k: names.get(src[k].split("_", 1)[1].removesuffix("_wb"), src[k])

    rows, judged = [], Counter()
    for k in news:
        for p in PARTIES:
            v = np.array([stance(lab[m][k], p) for m in JURORS])
            if np.isnan(v).any():  # some juror did not see this party in the article
                continue
            judged[p] += 1
            if v.max() - v.min() >= 2 or (v.max() > 0 and v.min() < 0):
                rows.append((k, p, v))
    meta = article_meta({k: src[k] for k, _, _ in rows})

    path = ROOT / "data" / "derived" / "jury_disagreements.csv"
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8", newline="") as f:
        w = csv.writer(f)
        w.writerow(["outlet", "published", "url", "title", "party", *JURORS, "spread"])
        for k, p, v in sorted(rows, key=lambda r: (outlet(r[0]), meta.get(r[0], {}).get("published", ""), r[1])):
            m = meta.get(k, {})
            w.writerow([outlet(k), m.get("published", ""), m.get("url", ""), m.get("title", ""), p,
                        *[f"{x:g}" for x in v], f"{v.max() - v.min():g}"])

    by_party = Counter(p for _, p, _ in rows)
    opposite = Counter(p for _, p, v in rows if v.max() > 0 and v.min() < 0)
    by_outlet = Counter(outlet(k) for k, _, _ in rows)
    per_outlet = Counter(outlet(k) for k in news)
    jurors = "、".join(f"`{m}`（{ORIGIN.get(m, '?')}）" for m in JURORS)
    L = [f"# 陪審團意見不一致的文章\n\n日期：{date.today().isoformat()}　陪審員：{jurors}\n",
         f"範圍：陪審一致性測試（[jury-agreement.md](jury-agreement.md)）中三位正式陪審員都判斷過的 {len(news)} 篇新聞。"
         "某篇文章對某個政黨，只要三位陪審員都給了立場分數，而且分數相差至少 2 分（−2 到 +2 的量尺），"
         "或有人判正面、有人判負面，就列為意見不一致。\n",
         "清單只含媒體、日期、網址、標題與各陪審員的分數，不含內文；隨資料集一起公開（`jury_disagreements.csv`）。\n",
         "## 各政黨\n", "| 政黨 | 三位都有判斷 | 意見不一致 | 比例 | 其中正負相反 |", "|---|---|---|---|---|"]
    L += [f"| {NAME[p]} | {judged[p]} | {by_party[p]} | {by_party[p] / max(judged[p], 1):.0%} | {opposite[p]} |" for p in PARTIES]
    L += ["\n## 各媒體\n", "每篇文章可能對不只一個政黨意見不一致，所以件數可能大於篇數。\n",
          "| 媒體 | 篇數 | 意見不一致（件） |", "|---|---|---|"]
    L += [f"| {o} | {per_outlet[o]} | {by_outlet[o]} |" for o in sorted(per_outlet, key=lambda o: -by_outlet[o] / per_outlet[o])]
    L += ["\n## 用途\n",
          "- 以陪審員標籤擬合的趨勢中，同一篇文章有多位陪審員時，他們的分歧會放寬該期的不確定區間（[trend-model.md](trend-model.md)）",
          "- 讀者可以自行檢視這些文章，判斷哪一位陪審員比較合理，或標註規則哪裡需要釐清",
          "- 下一版標註規則若有修改，會先用這批文章檢驗分歧是否減少"]
    (ROOT / "docs" / "jury-disagreements.md").write_text("\n".join(L) + "\n", encoding="utf-8")
    print("\n".join(L))
    print(f"{len(rows)} rows -> {path.relative_to(ROOT)}; meta found for {len(meta)}/{len({k for k, _, _ in rows})}")


if __name__ == "__main__":
    main()

"""Pilot: annotate a small stratified sample with three LLM jurors and report agreement and validity.

Sample: 5 political articles per outlet (12 outlets) + 10 KMT and 10 DPP press releases (known-direction
anchors) + a party-swap copy of 10 articles. Writes raw labels to data/annotations/ (not published) and an
aggregate report to docs/pilot-annotation.md. Usage: uv run python scripts/pilot_annotation.py
"""

from __future__ import annotations

import glob
import json
import random
import re
from concurrent.futures import ThreadPoolExecutor
from datetime import date
from pathlib import Path

import krippendorff
import numpy as np

from twmedia.annotate import CODEBOOK_VERSION, PARTIES, annotate, swap_parties

ROOT = Path(__file__).resolve().parents[1]
JURORS = {
    "gpt-5.6-luna": "opencode-go/gpt-5.6-luna",  # US (OpenAI)
    "gemini-4-argon": "opencode-go/gemini-4-argon",  # US (Google)
    "deepseek-v4.1-flash": "opencode-go/deepseek-v4.1-flash",  # China
}
POLITICAL = re.compile(r"國民黨|民進黨|民眾黨|藍營|綠營|白營|藍白|黨團|賴清德|鄭麗文|黃國昌|柯文哲")
OUT = ROOT / "data" / "annotations"


def load(source: str) -> list[dict]:
    rows = []
    for f in sorted(glob.glob(str(ROOT / "data" / "raw" / source / "*.jsonl"))):
        rows += [json.loads(line) for line in open(f, encoding="utf-8")]
    return [r for r in rows if r.get("text") and len(r["text"]) > 200]


def sample() -> list[dict]:
    rng = random.Random(20261101)
    items = []
    for src in sorted(Path(ROOT / "data" / "raw").glob("news_*")):
        pool = [r for r in load(src.name) if POLITICAL.search((r.get("title") or "") + r["text"])]
        for r in rng.sample(pool, min(5, len(pool))):
            items.append({"kind": "news", "source": src.name, **r})
    for party in ("kmt", "dpp"):
        pool = [r for r in load(f"party_{party}") if POLITICAL.search(r["text"])]
        for r in rng.sample(pool, min(10, len(pool))):
            items.append({"kind": "anchor", "anchor_party": party.upper(), "source": f"party_{party}", **r})
    swaps = [dict(i, kind="swap", swap_of=i["id"], text=swap_parties(i["text"]), title=swap_parties(i.get("title") or ""))
             for i in rng.sample([i for i in items if i["kind"] == "news"], 10)]
    return items + swaps


def run(items: list[dict]) -> dict[str, dict]:
    OUT.mkdir(parents=True, exist_ok=True)
    results: dict[str, dict] = {j: {} for j in JURORS}
    for juror in JURORS:  # resume support
        f = OUT / f"pilot_{juror}.jsonl"
        if f.exists():
            for line in open(f, encoding="utf-8"):
                d = json.loads(line)
                results[juror][d["key"]] = d["label"]

    def job(juror_item):
        juror, it = juror_item
        key = f"{it['kind']}:{it['id']}"
        if key in results[juror]:
            return
        try:
            label = annotate(JURORS[juror], it.get("title") or "", it["text"])
        except Exception as e:  # timeouts etc.: record as missing
            label = {"error": str(e)[:200]}
        results[juror][key] = label
        with open(OUT / f"pilot_{juror}.jsonl", "a", encoding="utf-8") as f:
            f.write(json.dumps({"key": key, "label": label, "codebook": CODEBOOK_VERSION}, ensure_ascii=False) + "\n")

    with ThreadPoolExecutor(max_workers=6) as pool:
        list(pool.map(job, [(j, it) for it in items for j in JURORS]))
    return results


def stance(label: dict | None, party: str):
    if not label or "parties" not in label:
        return np.nan
    v = label["parties"].get(party, {}).get("stance")
    return np.nan if v is None else float(v)


def report(items: list[dict], results: dict[str, dict]) -> str:
    news = [i for i in items if i["kind"] == "news"]
    lines = [f"# LLM 標註試標報告\n\n日期：{date.today().isoformat()}　codebook v{CODEBOOK_VERSION}　"
             f"陪審員：{', '.join(f'`{m}`' for m in JURORS.values())}（經 OpenCode Go，試標用途）\n",
             f"樣本：{len(news)} 篇新聞（12 家媒體各最多 5 篇，含政黨關鍵字）、"
             f"{sum(i['kind'] == 'anchor' for i in items)} 篇政黨新聞稿、"
             f"{sum(i['kind'] == 'swap' for i in items)} 篇政黨對調版本。只公開彙總結果，不公開原文。\n"]

    valid = {j: sum(1 for i in items if (results[j].get(f"{i['kind']}:{i['id']}") or {}).get("parties")) for j in JURORS}
    lines.append("## 1. 輸出可用率\n\n| 陪審員 | 可解析的標註 |\n|---|---|")
    lines += [f"| {j} | {valid[j]}/{len(items)} |" for j in JURORS]

    lines.append("\n## 2. 陪審員一致性（新聞樣本，Krippendorff's α，序位尺度）\n\n| 政黨 | α | 三位都有判斷的篇數 |\n|---|---|---|")
    for p in PARTIES:
        mat = np.array([[stance(results[j].get(f"news:{i['id']}"), p) for i in news] for j in JURORS])
        n_full = int(np.sum(~np.isnan(mat).any(axis=0)))
        alpha = krippendorff.alpha(reliability_data=mat, level_of_measurement="ordinal") if np.sum(~np.isnan(mat)) > 3 else float("nan")
        lines.append(f"| {p} | {alpha:.2f} | {n_full} |")

    lines.append("\n## 3. 已知立場錨點（政黨新聞稿）\n\n新聞稿對自己的黨應判為正面（stance > 0）；若同時提及主要對手黨，對手應判為負面（stance < 0）。\n\n"
                 "| 陪審員 | 自己黨判為正面 | 對手黨判為負面 |\n|---|---|---|")
    rival = {"KMT": "DPP", "DPP": "KMT"}
    for j in JURORS:
        own = [stance(results[j].get(f"anchor:{i['id']}"), i["anchor_party"]) for i in items if i["kind"] == "anchor"]
        opp = [stance(results[j].get(f"anchor:{i['id']}"), rival[i["anchor_party"]]) for i in items if i["kind"] == "anchor"]
        own_v = [v for v in own if not np.isnan(v)]
        opp_v = [v for v in opp if not np.isnan(v)]
        lines.append(f"| {j} | {sum(v > 0 for v in own_v)}/{len(own_v)} | {sum(v < 0 for v in opp_v)}/{len(opp_v)} |")

    lines.append("\n## 4. 政黨對調測試\n\n把文中「國民黨」「民進黨」等黨名互換（人名不換），沒有偏誤的模型，對調後 KMT 的分數應約等於原本 DPP 的分數，反之亦然。"
                 "表中為對調前後分數差的平均（越接近 0 越好；人名未對調，所以這只是粗略檢查）。\n\n| 陪審員 | KMT 差異 | DPP 差異 | 有效篇數 |\n|---|---|---|---|")
    for j in JURORS:
        dk, dd = [], []
        for i in items:
            if i["kind"] != "swap":
                continue
            orig, sw = results[j].get(f"news:{i['swap_of']}"), results[j].get(f"swap:{i['id']}")
            a, b = stance(sw, "KMT") - stance(orig, "DPP"), stance(sw, "DPP") - stance(orig, "KMT")
            if not np.isnan(a):
                dk.append(a)
            if not np.isnan(b):
                dd.append(b)
        fmt = lambda xs: f"{np.mean(xs):+.2f}" if xs else "—"
        lines.append(f"| {j} | {fmt(dk)} | {fmt(dd)} | {min(len(dk), len(dd))} |")

    lines.append("\n## 限制\n\n- 樣本很小，只用來檢查流程與問題設計，不能拿來比較媒體\n"
                 "- 樣本只來自 11/01 收集到的文章，議題集中在台北市長辯論等少數事件\n"
                 "- 三位陪審員中兩位來自美國公司、一位來自中國公司；台灣模型（TAIDE）尚未加入\n")
    return "\n".join(lines) + "\n"


def main() -> None:
    items = sample()
    results = run(items)
    (ROOT / "docs" / "pilot-annotation.md").write_text(report(items, results), encoding="utf-8")
    print((ROOT / "docs" / "pilot-annotation.md").read_text(encoding="utf-8"))


if __name__ == "__main__":
    main()

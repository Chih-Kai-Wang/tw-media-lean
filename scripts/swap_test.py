"""Party-swap test with people's names masked (PLAN.md §5.5 item 3).

For news articles that mention both KMT and DPP, each juror labels two versions: names masked
(「國民黨籍人士甲」) and names masked + KMT/DPP labels exchanged. Same content, opposite labels, so an unbiased
juror gives stance_DPP(swapped) == stance_KMT(masked) and stance_KMT(swapped) == stance_DPP(masked).
Label effect = mean of [stance_DPP(swapped) - stance_KMT(masked)] and [stance_DPP(masked) - stance_KMT(swapped)],
halved: how much more favourably the juror rates the same content when it is labelled DPP rather than KMT
(> 0 means a pro-DPP label effect). Bootstrap 95% interval over articles.

Raw labels go to data/annotations/ (not published); the aggregate report to docs/swap-test.md.
Usage: uv run python scripts/swap_test.py [--n 48]
"""

from __future__ import annotations

import argparse
import json
import random
from concurrent.futures import ThreadPoolExecutor
from datetime import date
from pathlib import Path

import numpy as np
from pilot_annotation import JURORS, load, stance

from twmedia.annotate import CODEBOOK_VERSION, _roster, annotate, mask_people, swap_parties

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "data" / "annotations"
PER_OUTLET = 4


def sample(n: int) -> list[dict]:
    rng = random.Random(20261102)
    items = []
    for src in sorted((ROOT / "data" / "raw").glob("news_*")):
        pool = []
        for r in load(src.name):
            title, text = mask_people(r.get("title") or "", r["text"][:3000])
            if "國民黨" in title + text and "民進黨" in title + text:
                pool.append({"id": r["id"], "source": src.name, "title": title, "text": text})
        items += rng.sample(pool, min(PER_OUTLET, len(pool)))
    rng.shuffle(items)
    return items[:n]


def run(items: list[dict]) -> dict[str, dict]:
    OUT.mkdir(parents=True, exist_ok=True)
    results: dict[str, dict] = {j: {} for j in JURORS}
    for juror in JURORS:  # resume support
        f = OUT / f"swap_{juror}.jsonl"
        if f.exists():
            for line in open(f, encoding="utf-8"):
                d = json.loads(line)
                results[juror][d["key"]] = d["label"]

    def job(args):
        juror, it, version = args
        key = f"{version}:{it['id']}"
        if key in results[juror]:
            return
        title, text = (it["title"], it["text"]) if version == "masked" else (swap_parties(it["title"]), swap_parties(it["text"]))
        try:
            label = annotate(JURORS[juror], title, text)
        except Exception as e:  # timeouts etc.: record as missing
            label = {"error": str(e)[:200]}
        results[juror][key] = label
        with open(OUT / f"swap_{juror}.jsonl", "a", encoding="utf-8") as f:
            f.write(json.dumps({"key": key, "label": label, "codebook": CODEBOOK_VERSION}, ensure_ascii=False) + "\n")

    with ThreadPoolExecutor(max_workers=6) as pool:
        list(pool.map(job, [(j, it, v) for it in items for v in ("masked", "swapped") for j in JURORS]))
    return results


def label_effects(items: list[dict], res: dict) -> tuple[np.ndarray, np.ndarray]:
    """Per-article label effect (> 0: same content rated better when labelled DPP; NaN when not computable),
    and whether every available comparison for the article was exactly equal."""
    out, same = [], []
    for it in items:
        m, s = res.get(f"masked:{it['id']}"), res.get(f"swapped:{it['id']}")
        a = stance(s, "DPP") - stance(m, "KMT")  # KMT-side content: labelled DPP minus labelled KMT
        b = stance(m, "DPP") - stance(s, "KMT")  # DPP-side content: labelled DPP minus labelled KMT
        pair = [d for d in (a, b) if not np.isnan(d)]
        out.append(np.mean(pair) if pair else np.nan)
        same.append(bool(pair) and all(d == 0 for d in pair))
    return np.array(out), np.array(same)


def bootstrap(x: np.ndarray, reps: int = 5000) -> tuple[float, float]:
    rng = np.random.default_rng(0)
    means = [rng.choice(x, len(x)).mean() for _ in range(reps)]
    return float(np.percentile(means, 2.5)), float(np.percentile(means, 97.5))


def report(items: list[dict], results: dict[str, dict]) -> str:
    lines = [
        f"# 政黨對調測試（人名遮蔽版）\n\n日期：{date.today().isoformat()}　codebook v{CODEBOOK_VERSION}　"
        f"陪審員：{', '.join(f'`{m}`' for m in JURORS.values())}（經 OpenCode Go，試標用途）\n",
        f"樣本：{len(items)} 篇同時提及國民黨與民進黨的新聞（每家媒體最多 {PER_OUTLET} 篇）。只公開彙總結果，不公開原文。\n",
        "## 做法\n",
        "1. 先把文中已知政治人物的名字換成帶黨籍的代號，例如「國民黨籍人士甲」（名單：`config/politicians.yaml`，"
        f"第 8–11 屆立委、主要首長與黨主席，加上從新聞自動找出的 2026 候選人，共 {len(_roster()[0])} 人）。人名本身就透露黨籍，不遮蔽的話，只換黨名測不出偏誤。",
        "2. 每篇做兩個版本：只遮蔽人名（原版），以及遮蔽後再把國民黨／民進黨相關字詞全部互換（對調版，代號裡的黨名也一起換）。",
        "3. 兩個版本內容相同、黨派標籤相反。沒有偏誤的模型，對調版的 DPP 分數應等於原版的 KMT 分數，反之亦然。",
        "4. **標籤效應**＝同樣的內容被標成民進黨時，比被標成國民黨時，分數高多少（-2 到 +2 的量尺）。"
        "正值表示偏向民進黨標籤，負值表示偏向國民黨標籤，0 表示沒有偏誤。區間為對文章重抽樣 5,000 次的 95% 區間。\n",
        "## 結果\n",
        "| 陪審員 | 標籤效應 | 95% 區間 | 有效篇數 | 判斷完全一致的比例 |",
        "|---|---|---|---|---|",
    ]
    for j in JURORS:
        eff, same = label_effects(items, results[j])
        ok = ~np.isnan(eff)
        x = eff[ok]
        if len(x) < 5:
            lines.append(f"| {j} | — | — | {len(x)} | — |")
            continue
        lo, hi = bootstrap(x)
        lines.append(f"| {j} | {x.mean():+.2f} | [{lo:+.2f}, {hi:+.2f}] | {len(x)} | {same[ok].mean():.0%} |")
    lines += [
        "\n## 怎麼解讀\n",
        "- 區間包含 0：在這個樣本量下看不出系統性偏誤",
        "- 區間不含 0：該模型會因為黨名不同而給同樣內容不同分數，要在最終模型裡校正，偏誤大的移出陪審團（PLAN.md §5.3）",
        "- 「判斷完全一致的比例」低，不一定是偏誤，也可能是模型本身每次回答都有隨機變動",
        "\n## 限制\n",
        "- 名單外的人名、只用姓氏加職稱的稱呼（例如「賴總統」）、綽號（例如「柯P」）沒有遮蔽，仍可能透露黨籍",
        "- 對調後的文章可能出現不符事實的組合（例如「民進黨籍人士甲」擔任在野黨主席），模型可能因此困惑",
        "- 只測國民黨與民進黨互換；民眾黨的偏誤要另外設計",
        "- 樣本只來自 2026-11 初收集到的文章",
    ]
    return "\n".join(lines) + "\n"


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--n", type=int, default=48)
    items = sample(ap.parse_args().n)
    results = run(items)
    path = ROOT / "docs" / "swap-test.md"
    path.write_text(report(items, results), encoding="utf-8")
    print(path.read_text(encoding="utf-8"))


if __name__ == "__main__":
    main()

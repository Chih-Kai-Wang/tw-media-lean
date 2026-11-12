"""Method A (PLAN.md §5.2): a phrase-based slant index that uses no LLM, after Gentzkow & Shapiro (2010).

1. Speech: Legislative Yuan question-period transcripts, terms 10-11 (aigrant/taiwan-legislator-transcript,
   Apache-2.0). Each row is a whole question period with ministers' replies interleaved, so only turns whose
   speaker label is the row's own legislator (「黃委員國昌：」) are kept. Party: openfun/tw-ly-legislator.
2. Phrases: character 2-3-grams that do not cross punctuation; politicians' names and party labels are
   removed first (they would otherwise be the most "partisan" phrases). 臺 is folded into 台.
3. Selection: phrases used by >= MIN_SPEAKERS legislators, found in 0.05%-10% of news articles, and with a
   speech-to-news rate ratio within 1/REGISTER..REGISTER (drops spoken-only words such as 請問、其實 that
   separate questioning from answering rather than party), ranked by Pearson chi-square of KMT vs DPP counts;
   the top N_PHRASES are kept. Outlets are scored on political articles only (POLITICAL).
4. Slant: for each phrase, regress its relative frequency across legislators on a KMT dummy (DPP = 0, KMT = 1)
   to get (a_p, b_p); a text's slant is sum_p b_p (f_p - a_p) / sum_p b_p^2, so DPP-like language scores
   near 0 and KMT-like language near 1. Outlets are compared with each other, not read as absolute.

Caveat: KMT is in opposition and DPP in government throughout terms 10-11, so the dimension mixes party with
"questioning vs defending the executive". Inputs in data/external/ly/ and data/raw/; report in
docs/phrase-baseline*.md.
Usage: uv run python scripts/phrase_baseline.py [transcripts|interp8|interp9]
  interp8/interp9: written interpellations of term 8 (2012-2015, KMT in government) or term 9 (2016-2019, DPP
  in government), openfun/tw-ly-interpellation (CC BY 4.0); comparing them separates party from government role.
"""

from __future__ import annotations

import csv
import glob
import json
import re
import sys
from collections import Counter, defaultdict
from datetime import date
from pathlib import Path

import numpy as np
import yaml

from twmedia.annotate import _roster

ROOT = Path(__file__).resolve().parents[1]
LY = ROOT / "data" / "external" / "ly"
PARTY = {"中國國民黨": "KMT", "民主進步黨": "DPP", "台灣民眾黨": "TPP"}
MIN_SPEAKERS, N_PHRASES, REGISTER = 10, 1000, 3.0
CORPORA = {
    "transcripts": {"terms": (10, 11), "years": "2021–2025", "suffix": "", "gov": "DPP",
                    "desc": "第 10–11 屆質詢逐字稿（aigrant/taiwan-legislator-transcript，Apache-2.0），只保留立委本人說的話，去掉官員回答"},
    "interp8": {"terms": (8,), "years": "2012–2015", "suffix": "-term8", "gov": "KMT",
                "desc": "第 8 屆書面質詢（openfun/tw-ly-interpellation，CC BY 4.0；2012–2015，國民黨執政、民進黨在野），事由加說明"},
    "interp9": {"terms": (9,), "years": "2016–2019", "suffix": "-term9", "gov": "DPP",
                "desc": "第 9 屆書面質詢（openfun/tw-ly-interpellation，CC BY 4.0；2016–2019，民進黨執政、國民黨在野），事由加說明"},
}
POLITICAL = re.compile(r"國民黨|民進黨|民眾黨|立法院|立委|行政院|總統|市長|縣長|議員|選舉|參選|候選人|政府")
TURN = re.compile(r"(?:^|\n)([^\n：]{2,12})：")
TIME = re.compile(r"^（\d+時\d+分）")
CJK_RUN = re.compile(r"[一-鿿]+")
PARTY_WORDS = re.compile(
    r"中國國民黨|民主進步黨|台灣民眾黨|國民黨|民進黨|民眾黨|藍營|綠營|白營|泛藍|泛綠|藍委|綠委|藍白|黨團|藍|綠|國昌|清德|英文"
)


def cjk_head(name: str) -> str:
    return CJK_RUN.match(name.strip()).group(0)


def clean(text: str) -> str:
    _, names = _roster()
    text = text.replace("臺", "台")
    return PARTY_WORDS.sub("＃", names.sub("＃", text))


def grams(text: str, allowed: set[str] | None = None) -> Counter:
    c: Counter = Counter()
    for run in CJK_RUN.findall(clean(text)):
        for n in (2, 3):
            g = (run[i : i + n] for i in range(len(run) - n + 1))
            c.update(g if allowed is None else (x for x in g if x in allowed))
    return c


def legislator_party(terms: tuple[int, ...]) -> dict[tuple[int, str], str]:
    out = {}
    for term in terms:
        for line in open(LY / f"legislator-{term:02d}.jsonl", encoding="utf-8"):
            r = json.loads(line)
            if r.get("黨籍") in PARTY:
                out[(term, cjk_head(r["委員姓名"]))] = PARTY[r["黨籍"]]
    return out


def own_turns(name: str, transcript: str) -> str:
    """Keep only what the row's legislator said; labels look like 「許委員智傑：」 or 「張廖委員萬堅：」."""
    parts = TURN.split(transcript)
    kept = []
    for label, body in zip(parts[1::2], parts[2::2]):
        if "委員" in label and label.replace("委員", "", 1) == name:
            kept.append(TIME.sub("", body.strip()))
    return "\n".join(kept)


def speeches(corpus: str, allowed: set[str]) -> dict[tuple[str, str], Counter]:
    """(legislator, party) -> counts of `allowed` phrases over all their own turns or written interpellations."""
    terms = CORPORA[corpus]["terms"]
    parties = legislator_party(terms)
    out: dict[tuple[str, str], Counter] = defaultdict(Counter)
    if corpus.startswith("interp"):
        for term in terms:
            for line in open(LY / f"interpellation-{term:02d}.jsonl", encoding="utf-8"):
                r = json.loads(line)
                if len(r["質詢委員"]) != 1:  # co-signed: skip rather than guess whose words they are
                    continue
                name = cjk_head(r["質詢委員"][0])
                party = parties.get((term, name))
                if party in ("KMT", "DPP"):
                    out[(name, party)].update(grams((r.get("事由") or "") + "\n" + (r.get("說明") or ""), allowed))
        return out
    csv.field_size_limit(10**9)
    for f in sorted(LY.glob("transcript-*.csv")):
        term = int(f.stem.split("-")[1])
        for r in csv.DictReader(open(f, encoding="utf-8")):
            name = cjk_head(r["legislator_name"] or "?")
            party = parties.get((term, name))
            if party in ("KMT", "DPP"):
                out[(name, party)].update(grams(own_turns(name, r["transcript"]), allowed))
    return out


def load_texts(pattern: str) -> list[dict]:
    rows = []
    for f in sorted(glob.glob(str(ROOT / "data" / "raw" / pattern / "*.jsonl"))):
        for line in open(f, encoding="utf-8"):
            r = json.loads(line)
            if r.get("text") and len(r["text"]) > 200:
                r["source"] = Path(f).parent.name
                rows.append(r)
    return rows


def in_range(df: int, n_news: int) -> bool:
    return 0.0005 * n_news <= df <= 0.10 * n_news


def select(spk: dict, news_df: Counter, n_news: int, news_tf: Counter) -> list[str]:
    kmt, dpp = Counter(), Counter()
    users: Counter = Counter()
    for (_, party), c in spk.items():
        (kmt if party == "KMT" else dpp).update(c)
        users.update(c.keys())
    tot_k, tot_d = sum(kmt.values()), sum(dpp.values())
    tot_news = sum(news_tf.values())
    scored = []
    for p in users:
        if users[p] < MIN_SPEAKERS or not in_range(news_df[p], n_news):
            continue
        ratio = ((kmt[p] + dpp[p]) / (tot_k + tot_d)) / (news_tf[p] / tot_news)
        if not 1 / REGISTER <= ratio <= REGISTER:
            continue
        a, b = kmt[p], dpp[p]
        c, d = tot_k - a, tot_d - b
        chi2 = (a * d - b * c) ** 2 * (a + b + c + d) / ((a + b) * (c + d) * (a + c) * (b + d))
        scored.append((chi2, p))
    return [p for _, p in sorted(scored, reverse=True)[:N_PHRASES]]


def freqs(c: Counter, phrases: list[str]) -> np.ndarray:
    v = np.array([c[p] for p in phrases], dtype=float)
    return v / v.sum() if v.sum() else v


def fit(spk: dict, phrases: list[str]) -> tuple[np.ndarray, np.ndarray]:
    F = np.array([freqs(c, phrases) for c in spk.values()])
    y = np.array([1.0 if party == "KMT" else 0.0 for _, party in spk])
    X = np.column_stack([np.ones_like(y), y])
    (a, b), *_ = np.linalg.lstsq(X, F, rcond=None)
    return a, b


def slant(c: Counter, phrases: list[str], a: np.ndarray, b: np.ndarray) -> float:
    f = freqs(c, phrases)
    return float(b @ (f - a) / (b @ b)) if f.sum() else float("nan")


def cross_validate(spk: dict, news_df: Counter, n_news: int, news_tf: Counter, folds: int = 5) -> list[tuple[str, float]]:
    """Fit on 4/5 of legislators, score the held-out fifth: (true party, slant) pairs."""
    keys = sorted(spk)
    rng = np.random.default_rng(0)
    fold = dict(zip(keys, rng.permutation(len(keys)) % folds))
    out = []
    for k in range(folds):
        train = {key: spk[key] for key in keys if fold[key] != k}
        phrases = select(train, news_df, n_news, news_tf)
        a, b = fit(train, phrases)
        out += [(key[1], slant(spk[key], phrases, a, b)) for key in keys if fold[key] == k]
    return out


def auc(pairs: list[tuple[str, float]]) -> float:
    k = [s for p, s in pairs if p == "KMT" and not np.isnan(s)]
    d = [s for p, s in pairs if p == "DPP" and not np.isnan(s)]
    return float(np.mean([(x > y) + 0.5 * (x == y) for x in k for y in d]))


def main(corpus: str = "transcripts") -> None:
    news = load_texts("news_*")
    news_counts = [grams((r.get("title") or "") + "\n" + r["text"]) for r in news]
    news_df: Counter = Counter()
    for c in news_counts:
        news_df.update(c.keys())
    allowed = {p for p, df in news_df.items() if in_range(df, len(news))}
    news_counts = [Counter({p: n for p, n in c.items() if p in allowed}) for c in news_counts]
    news_tf: Counter = Counter()
    for c in news_counts:
        news_tf.update(c)
    spk = speeches(corpus, allowed)

    cv = cross_validate(spk, news_df, len(news), news_tf)
    phrases = select(spk, news_df, len(news), news_tf)
    political = [i for i, r in enumerate(news) if POLITICAL.search((r.get("title") or "") + r["text"])]
    a, b = fit(spk, phrases)

    by_outlet: dict[str, Counter] = defaultdict(Counter)
    for i in political:
        by_outlet[news[i]["source"]].update(news_counts[i])
    outlet_scores = {s: slant(c, phrases, a, b) for s, c in by_outlet.items()}
    # bootstrap over articles for an interval per outlet
    rng = np.random.default_rng(1)
    idx = defaultdict(list)
    for i in political:
        idx[news[i]["source"]].append(i)
    intervals = {}
    for s, ids in idx.items():
        reps = []
        for _ in range(200):
            c: Counter = Counter()
            for i in rng.choice(ids, len(ids)):
                c.update(news_counts[i])
            reps.append(slant(c, phrases, a, b))
        intervals[s] = (np.percentile(reps, 2.5), np.percentile(reps, 97.5))

    party_rel = {}
    for src in ("party_kmt", "party_dpp"):
        by_year: dict[str, Counter] = defaultdict(Counter)
        for r in load_texts(src):
            year = (r.get("published") or "")[:4]
            if year.isdigit():
                by_year[year].update(grams(r["text"], allowed))
        party_rel[src] = {y: slant(c, phrases, a, b) for y, c in sorted(by_year.items())}

    ranked = sorted(zip(b, phrases), reverse=True)
    report(corpus, spk, cv, outlet_scores, intervals, {s: len(v) for s, v in idx.items()}, party_rel, ranked, len(political))
    out = ROOT / "data" / "derived"
    out.mkdir(parents=True, exist_ok=True)
    (out / f"phrase_baseline{CORPORA[corpus]['suffix']}.json").write_text(json.dumps(
        {"phrases": phrases, "a": a.tolist(), "b": b.tolist(), "outlets": outlet_scores, "party_releases": party_rel},
        ensure_ascii=False, indent=1), encoding="utf-8")


def report(corpus, spk, cv, outlet_scores, intervals, n_articles, party_rel, ranked, n_news) -> None:
    n_k = sum(p == "KMT" for _, p in spk)
    n_d = sum(p == "DPP" for _, p in spk)
    cv_k = np.nanmean([s for p, s in cv if p == "KMT"])
    cv_d = np.nanmean([s for p, s in cv if p == "DPP"])
    meta = CORPORA[corpus]
    cfg = yaml.safe_load((ROOT / "config" / "sources.yaml").read_text(encoding="utf-8"))
    names = {f"news_{k}": v["name"] for k, v in cfg["outlets"].items()}
    L = [
        f"# 方法 A：用語基準法（不用 LLM）{'' if corpus == 'transcripts' else '— ' + meta['years']}\n\n日期：{date.today().isoformat()}　程式：`scripts/phrase_baseline.py`\n",
        "仿 Gentzkow & Shapiro (2010)：先從立委質詢找出國民黨與民進黨立委用法差最多的詞，再看各媒體比較常用哪一邊的詞。"
        "完全不經過 LLM，用來和 LLM 標註（方法 B／C）互相檢查。\n",
        "## 資料與做法\n",
        f"- 立委發言：{meta['desc']}。國民黨 {n_k} 位、民進黨 {n_d} 位立委。民眾黨立委人數太少，這一版先不估民眾黨方向",
        "- 詞：不跨標點的連續 2–3 個漢字；先刪掉政治人物姓名與黨名（否則最「有黨派」的詞會是人名），「臺」一律改成「台」",
        f"- 選詞：至少 {MIN_SPEAKERS} 位立委用過、出現在 0.05%–10% 的新聞裡，而且在發言和新聞裡的使用頻率相差不到 {REGISTER:g} 倍"
        f"（去掉「請問」「其實」這類口語詞，它們區分的是「質詢 vs 答詢」）；依國民黨／民進黨用量差的卡方值取前 {N_PHRASES} 個",
        "- 分數：0 ≈ 民進黨立委的用語，1 ≈ 國民黨立委的用語。只適合拿來**比較媒體之間的相對位置**",
        "\n## 檢驗 1：能不能分出立委的黨籍\n",
        f"把立委分成 5 份，用其中 4 份選詞與估參數，再替沒看過的那 1 份打分數。"
        f"AUC = {auc(cv):.2f}（1 = 完全分得開，0.5 = 亂猜）；沒看過的國民黨立委平均 {cv_k:.2f}，民進黨立委平均 {cv_d:.2f}。\n",
        "## 檢驗 2：政黨新聞稿\n",
        f"政黨自己的新聞稿立場已知，國民黨的分數應該高於民進黨。這也能看出分數是否隨時間漂移（新聞稿多年份，這裡用的立委發言只有 {meta['years']}）。\n",
        "| 年份 | 國民黨新聞稿 | 民進黨新聞稿 |",
        "|---|---|---|",
    ]
    years = sorted(set(party_rel["party_kmt"]) | set(party_rel["party_dpp"]))
    fmt = lambda v: "—" if v is None or np.isnan(v) else f"{v:.2f}"
    L += [f"| {y} | {fmt(party_rel['party_kmt'].get(y))} | {fmt(party_rel['party_dpp'].get(y))} |" for y in years]
    L += [
        f"\n## 各媒體（2026-10-31 起收集、含政治關鍵字的 {n_news} 篇新聞）\n",
        "區間：對文章重抽樣 200 次的 95% 區間。\n",
        "| 媒體 | 分數 | 95% 區間 | 篇數 |",
        "|---|---|---|---|",
    ]
    for s, v in sorted(outlet_scores.items(), key=lambda x: x[1]):
        lo, hi = intervals[s]
        L.append(f"| {names.get(s, s)} | {v:.2f} | [{lo:.2f}, {hi:.2f}] | {n_articles[s]} |")
    L += [
        "\n## 最偏向各黨的詞（前 30）\n",
        "| 國民黨立委較常用 | 民進黨立委較常用 |",
        "|---|---|",
    ]
    L += [f"| {k} | {d} |" for (_, k), (_, d) in zip(ranked[:30], ranked[::-1][:30])]
    L += [
        "\n## 限制\n",
        GOV_CAVEAT[corpus],
        "- 立委發言是口語，新聞是書面語；選詞時已要求詞要出現在新聞裡，但仍可能有語體差異" if corpus == "transcripts"
        else "- 書面質詢多由助理撰寫，可能比口頭質詢更制式；但語體比較接近新聞",
        "- 媒體樣本只有幾天，議題集中在 2026 選戰；要等歷史資料補齊後才能看長期變化",
        "- 斷詞用字元 n-gram，不用 ckip 斷詞；之後可比較兩者結果是否一致",
    ]
    (ROOT / "docs" / f"phrase-baseline{meta['suffix']}.md").write_text("\n".join(L) + "\n", encoding="utf-8")


GOV_CAVEAT = {
    "transcripts": "- 第 10–11 屆期間民進黨執政、國民黨在野，所以這個方向同時混了「黨派」和「質詢政府 vs 替政府辯護」，也混了議題差異。"
    "檢驗 2 看得出來：2016 年後兩黨新聞稿分得很開，但 2008–2015 民進黨在野時，民進黨新聞稿的分數接近、甚至高於國民黨。"
    "所以這個分數**只能在同一個執政期間內比較**；跨越政黨輪替的比較見 docs/phrase-baseline-term8.md（國民黨執政期）",
    "interp8": "- 第 8 屆期間國民黨執政、民進黨在野，和第 10–11 屆正好相反。兩邊都分得出黨籍的詞，比較可能是真正的黨派用語；"
    "只在其中一邊有效的詞，比較可能是「執政 vs 在野」的角色差異",
    "interp9": "- 第 9 屆期間民進黨執政、國民黨在野，執政角色和第 10–11 屆相同，可以當作同一方向、不同時期的重複檢驗",
}

if __name__ == "__main__":
    main(sys.argv[1] if len(sys.argv) > 1 else "transcripts")

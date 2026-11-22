"""The 2026 campaign weeks on live articles only (docs/campaign-weeks.md).

    uv run python scripts/campaign_weeks.py

The trend charts smooth across the change of collection at the end of October 2026 (docs/source-switch.md). This
report uses only live articles (published from 2026-10-31), so every number in it comes from the same collection.
It gives raw weekly means for whole weeks (Monday to Sunday), the daily score of each camp's own party, and the
weekend effect, checked against the 2012-2026 historical sample and the teacher's labels.
Decision model v1, articles it calls political, KMT and DPP stance only.
"""

from __future__ import annotations

import glob
import json
from datetime import date, timedelta
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
ANN = ROOT / "data" / "annotations"
MODEL = "tw-media-lean-v1"
TEACHER = "gemini-3.8-flash"
LIVE_FIRST = "2026-10-31"  # first day of live collection for most outlets (中天 from 2026-11-12)
NAME = dict(cna="中央社", ltn="自由時報", chinatimes="中國時報", ettoday="ETtoday", tvbs="TVBS", setn="三立", ftv="民視",
            ebc="東森", pts="公視", storm="風傳媒", mirror="鏡週刊", udn="聯合報", ctinews="中天")
# Camps by the sign of the 2024-01..2026-09 KMT-DPP gap (docs/findings.md section 1); 中央社 and 公視 are near 0.
GREEN = ["ftv", "setn", "ltn", "mirror"]
BLUE = ["ebc", "tvbs", "ettoday", "udn", "ctinews", "chinatimes", "storm"]
CAMP = {**{o: "green" for o in GREEN}, **{o: "blue" for o in BLUE}}
OWN = {"green": "dpp", "blue": "kmt"}  # the party each camp leans toward
CAMP_NAME = {"green": "偏民進黨的媒體（民視、三立、自由時報、鏡週刊）", "blue": "偏國民黨的媒體（中國時報、中天、聯合報、ETtoday、TVBS、東森、風傳媒）"}
# Campaign months in the historical sample: the two months before each local election, and the December and January
# before each presidential election.
CAMPAIGN = {"2014-10", "2014-11", "2018-10", "2018-11", "2022-10", "2022-11",
            "2015-12", "2016-01", "2019-12", "2020-01", "2023-12", "2024-01"}
# Short swings in the daily table, identified by reading the titles of that camp's most negative articles.
SWINGS = {
    ("green", "dpp", "2026-11-09", "2026-11-12"): "歌手羅大佑批評蔡英文與民進黨的發言，以及各方回應",
}


def load_meta(kind: str) -> dict[str, tuple[str, str]]:
    meta = {}
    for f in glob.glob(str(ROOT / "data" / "raw" / f"{kind}_*" / "*.jsonl")):
        outlet = Path(f).parent.name.split("_", 1)[1].removesuffix("_wb")
        for line in open(f, encoding="utf-8"):
            r = json.loads(line)
            if r.get("id") and r.get("published"):
                meta[r["id"]] = (outlet, r["published"][:10])
    return meta


def load_model(kind: str) -> pd.DataFrame:
    meta, rows = load_meta(kind), []
    for line in open(ANN / f"model_{MODEL}_{'news' if kind == 'news' else 'hist'}.jsonl", encoding="utf-8"):
        d = json.loads(line)
        aid = d["key"].split(":", 1)[1]
        if d["probs"]["political"][1] < 0.5 or aid not in meta:
            continue
        P = d["label"]["parties"]
        k = P["KMT"]["stance"] if P["KMT"]["mentioned"] else None
        p = P["DPP"]["stance"] if P["DPP"]["mentioned"] else None
        rows.append((aid, *meta[aid], k, p))
    return pd.DataFrame(rows, columns=["aid", "outlet", "date", "kmt", "dpp"]).drop_duplicates("aid")


def load_teacher() -> pd.DataFrame:
    meta, rows = load_meta("hist"), []
    for line in open(ANN / f"vertex_{TEACHER}_history.jsonl", encoding="utf-8"):
        d = json.loads(line)
        aid, lab = d["key"].split(":", 1)[1], d.get("label") or {}
        if aid in meta and lab.get("political"):
            P = lab.get("parties") or {}
            rows.append((aid, *meta[aid], (P.get("KMT") or {}).get("stance"), (P.get("DPP") or {}).get("stance")))
    return pd.DataFrame(rows, columns=["aid", "outlet", "date", "kmt", "dpp"])


def add_cols(df: pd.DataFrame) -> pd.DataFrame:
    df = df[df.date.str.match(r"\d{4}-\d\d-\d\d$")].copy()
    d = pd.to_datetime(df.date)
    df["weekend"] = d.dt.day_of_week >= 5
    df["monday"] = (d - pd.to_timedelta(d.dt.day_of_week, unit="D")).dt.strftime("%Y-%m-%d")
    df["camp"] = df.outlet.map(CAMP)
    return df


def f(x: float) -> str:
    return "—" if pd.isna(x) else f"{x:+.2f}"


def diff(a: pd.Series, b: pd.Series) -> tuple[float, float]:
    """Difference of means and its 95% half-width."""
    a, b = a.dropna(), b.dropna()
    if len(a) < 20 or len(b) < 20:
        return np.nan, np.nan
    return a.mean() - b.mean(), 1.96 * np.sqrt(a.var(ddof=0) / len(a) + b.var(ddof=0) / len(b))


def main() -> None:
    live = add_cols(load_model("news"))
    live = live[live.date >= LIVE_FIRST]
    last_day = live.date.max()
    # whole weeks only, and only weeks that end before the last (possibly incomplete) day of collection
    weeks = sorted(m for m in live.monday.unique()
                   if m >= LIVE_FIRST and (date.fromisoformat(m) + timedelta(days=6)).isoformat() < last_day)
    lw = live[live.monday.isin(weeks)]
    out = [
        "# 選戰期間的週資料（只用即時收集）",
        "",
        f"日期：{date.today().isoformat()}　模型：`{MODEL}`　程式：`scripts/campaign_weeks.py`",
        "",
        f"網站上的趨勢圖跨過 2026 年 10 月底收集方式的改變做平滑（[source-switch.md](source-switch.md)），分界前後的變化有一部分來自資料本身。"
        f"這份文件只用即時收集的文章（{LIVE_FIRST} 起刊出），所有數字都來自同一種收集方式。只計完整的週（週一到週日），"
        f"目前到 {(date.fromisoformat(weeks[-1]) + timedelta(days=6)).isoformat()}；只計決策模型判為政治新聞的文章。"
        "決策模型在即時文章上給國民黨的分數比老師高約 0.1 分，各週的偏差大小不同（[drift-monitor.md](drift-monitor.md)），"
        "所以 0.1 分左右的逐週變化要和漂移監測一起看。",
        "",
        "## 1. 每週平均",
        "",
        "「國民黨 − 民進黨」的原始週平均（未平滑），正值偏國民黨。括號內為提到國民黨的篇數。",
        "",
        "| 媒體 | " + " | ".join(f"{m[5:].replace('-', '/')} 起" for m in weeks) + " | 變化 |",
        "|---|" + "---:|" * (len(weeks) + 1),
    ]
    g = lw.groupby(["outlet", "monday"]).agg(kmt=("kmt", "mean"), dpp=("dpp", "mean"), nk=("kmt", "count"), nd=("dpp", "count"))
    g["gap"] = g.kmt - g.dpp
    g.loc[(g.nk < 20) | (g.nd < 20), "gap"] = np.nan
    order = g.groupby("outlet").gap.mean().sort_values().index
    for o in order:
        vals = [g.gap.get((o, m), np.nan) for m in weeks]
        ns = [int(g.nk.get((o, m), 0)) for m in weeks]
        ok = [v for v in vals if not pd.isna(v)]
        change = ok[-1] - ok[0] if len(ok) >= 2 else np.nan
        out.append(f"| {NAME[o]} | " + " | ".join(f"{f(v)} ({n})" for v, n in zip(vals, ns)) + f" | {f(change)} |")
    out += ["", "變化為最後一週減第一週。中天 11/12 才加入即時收集。", ""]

    # each camp's own party, by day
    out += ["## 2. 各陣營對自己偏好政黨的逐日分數", "",
            "每天合併計算。短期的起伏對得上單一新聞事件，幾天內就回到原來的水準；看趨勢時要用整週以上的平均。", ""]
    days = sorted(lw.date.unique())
    for camp in ("green", "blue"):
        party = OWN[camp]
        s = lw[lw.camp == camp].groupby("date")[party].agg(["mean", "count"])
        base = s["mean"].mean()
        out += [f"**{CAMP_NAME[camp]}，{'民進黨' if party == 'dpp' else '國民黨'}分數**（期間平均 {f(base)}）", "",
                "| " + " | ".join(d[5:].replace("-", "/") for d in days) + " |", "|" + "---:|" * len(days),
                "| " + " | ".join(f(s["mean"].get(d, np.nan)) for d in days) + " |", ""]
        for (c, p, a, b), what in SWINGS.items():
            if c == camp and p == party and a in s.index:
                dip = s.loc[a:b, "mean"].mean()
                out += [f"{a[5:].replace('-', '/')}–{b[5:].replace('-', '/')} 平均 {f(dip)}，比期間平均低 {abs(dip - base):.2f}："
                        f"這幾天分數最低的文章，主要是{what}。", ""]

    # weekend effect
    out += ["## 3. 週末的報導比較友善", "",
            "週六、週日刊出的政治新聞，兩黨的分數都比平日高。", "",
            "| 資料 | 陣營 | 國民黨：週末 − 平日 | 民進黨：週末 − 平日 |", "|---|---|---:|---:|"]

    def row(label: str, df: pd.DataFrame) -> None:
        for camp in ("blue", "green"):
            c = df[df.camp == camp]
            cells = []
            for party in ("kmt", "dpp"):
                v, h = diff(c[c.weekend][party], c[~c.weekend][party])
                mark = "**" if party == OWN[camp] else ""
                cells.append(f"{mark}{f(v)}{mark} ±{h:.2f}" if not pd.isna(v) else "—")
            out.append(f"| {label} | {'偏國民黨' if camp == 'blue' else '偏民進黨'} | " + " | ".join(cells) + " |")

    row(f"2026 即時（{weeks[0][5:].replace('-', '/')} 起 {len(weeks)} 週）", lw)
    hist = add_cols(load_model("hist"))
    hist = hist[(hist.date >= "2012-01-01") & (hist.date < "2026-10-01")]
    hist["month"] = hist.date.str[:7]
    row("歷史抽樣，選前月份", hist[hist.month.isin(CAMPAIGN)])
    row("歷史抽樣，其他月份", hist[~hist.month.isin(CAMPAIGN)])
    teach = add_cols(load_teacher())
    teach = teach[(teach.date >= "2012-01-01") & (teach.date < "2026-10-01")]
    row("歷史抽樣，老師的標籤", teach)
    out += ["", "粗體為該陣營偏好的政黨；± 為 95% 區間。選前月份為地方選舉前兩個月，以及總統大選前的 12 月與 1 月。", "",
            "兩黨週末都比較高，這在 2026 年即時資料、歷史抽樣的選前與其他月份都成立；用老師自己的標籤重算，四項中有三項方向相同，幅度較小。"
            "各陣營偏好的那一黨週末上升較多，這在 2026 年即時資料與歷史抽樣的其他月份看得到，在歷史上的選前月份與老師的標籤裡不明顯，"
            "目前只算初步觀察。可能的原因是週末立法院與政府的攻防較少，造勢、參訪與地方活動的報導較多。"
            "這會影響只有部分天數的週資料：剛好包含週末的未完成週，分數會偏高，所以網站上最新一週的數字要等整週收齊後再看。", ""]
    (ROOT / "docs" / "campaign-weeks.md").write_text("\n".join(out), encoding="utf-8")
    print("\n".join(out))


if __name__ == "__main__":
    main()

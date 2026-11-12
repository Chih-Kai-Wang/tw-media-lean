"""Patterns in the decision-model scores beyond the outlet ranking (docs/findings.md).

    uv run python scripts/findings.py

Uses decision model v1 on the historical sample only (2012-01 to 2026-09), so that the change of collection in
2026-10 (docs/source-switch.md) does not enter. Articles the model calls political, KMT and DPP stance only.
Each pattern is checked against the teacher's own labels (gemini-3.8-flash, history batch) where the teacher
sample is large enough, and against a fixed set of outlets present every year, so that outlets entering the
sample cannot create a trend. Patterns that did not survive those checks are listed at the end.
"""

from __future__ import annotations

import glob
import json
from datetime import date
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
ANN = ROOT / "data" / "annotations"
MODEL = "tw-media-lean-v1"
TEACHER = "gemini-3.8-flash"
NAME = dict(cna="中央社", ltn="自由時報", chinatimes="中國時報", ettoday="ETtoday", tvbs="TVBS", setn="三立", ftv="民視",
            ebc="東森", pts="公視", storm="風傳媒", mirror="鏡週刊", udn="聯合報")
FIXED = ["chinatimes", "cna", "ltn", "setn", "storm", "tvbs"]  # every year 2014-2026 has >= 30 articles per party
TOPIC = dict(election="選舉", cross_strait="兩岸", foreign_defense="外交國防", economy="經濟", energy_environment="能源環境",
             justice_scandal="司法醜聞", legislature="立法院", social_welfare="社福", other="其他")
# Months found by section 7, identified by reading the titles of their most negative (or positive) articles.
EVENTS = {
    "2014-03": "太陽花學運、服貿爭議",
    "2016-07": "黨產條例通過後的國民黨黨產爭議",
    "2016-11": "一例一休修法、日本核災區食品進口爭議",
    "2017-07": "前瞻基礎建設特別條例，國民黨團在立法院杯葛",
    "2017-08": "815 大停電與限電",
    "2020-07": "高雄市長補選，國民黨候選人李眉蓁論文抄襲案",
    "2021-08": "國民黨主席選舉與公投連署",
    "2023-06": "政界 #MeToo 性騷擾事件",
    "2025-04": "共諜案、美國關稅、罷免爭議",
    "2025-08": "823 罷免投票前國民黨的反罷免造勢",
}


def load() -> tuple[pd.DataFrame, pd.DataFrame]:
    meta = {}
    for f in glob.glob(str(ROOT / "data" / "raw" / "hist_*" / "*.jsonl")):
        outlet = Path(f).parent.name.split("_", 1)[1].removesuffix("_wb")
        archive = Path(f).parent.name.endswith("_wb")
        for line in open(f, encoding="utf-8"):
            r = json.loads(line)
            if r.get("id") and r.get("published"):
                meta[r["id"]] = (outlet, r["published"][:10], archive)
    rows = []
    for line in open(ANN / f"model_{MODEL}_hist.jsonl", encoding="utf-8"):
        d = json.loads(line)
        aid = d["key"].split(":", 1)[1]
        if d["probs"]["political"][1] < 0.5 or aid not in meta:
            continue
        lab, (o, pub, wb) = d["label"], meta[aid]
        rows.append((aid, o, pub, wb, lab["genre"], lab["topic"], lab["parties"]["KMT"]["stance"], lab["parties"]["DPP"]["stance"]))
    m = pd.DataFrame(rows, columns=["aid", "outlet", "date", "archive", "genre", "topic", "kmt", "dpp"]).drop_duplicates("aid")
    m = m[(m.date >= "2012-01-01") & (m.date < "2026-10-01")].copy()
    m["year"], m["month"] = m.date.str[:4], m.date.str[:7]
    rows = []
    for line in open(ANN / f"vertex_{TEACHER}_history.jsonl", encoding="utf-8"):
        d = json.loads(line)
        aid, lab = d["key"].split(":", 1)[1], d.get("label") or {}
        if aid in meta and lab.get("political"):
            P = lab.get("parties") or {}
            rows.append((aid, meta[aid][0], meta[aid][1], lab.get("genre"), lab.get("topic"),
                         (P.get("KMT") or {}).get("stance"), (P.get("DPP") or {}).get("stance")))
    t = pd.DataFrame(rows, columns=["aid", "outlet", "date", "genre", "topic", "kmt", "dpp"])
    t = t[(t.date >= "2012-01-01") & (t.date < "2026-10-01")].copy()
    t["year"] = t.date.str[:4]
    return m, t


def cells(df: pd.DataFrame, by: list[str], min_n: int) -> pd.DataFrame:
    g = df.groupby(by).agg(kmt=("kmt", "mean"), dpp=("dpp", "mean"), nk=("kmt", "count"), nd=("dpp", "count")).reset_index()
    g = g[(g.nk >= min_n) & (g.nd >= min_n)].copy()
    g["gap"] = g.kmt - g.dpp
    return g


def f(x: float) -> str:
    return "—" if pd.isna(x) else f"{x:+.2f}"


def main() -> None:
    m, t = load()
    L = ["# 分數裡的其他規律\n",
         f"日期：{date.today().isoformat()}　模型：`{MODEL}`　程式：`scripts/findings.py`\n",
         "這份文件整理媒體排序以外的規律。資料只用歷史抽樣（2012-01 至 2026-09），避開 2026 年 10 月起收集方式的改變"
         "（[source-switch.md](source-switch.md)）；只計決策模型判為政治新聞的文章，以及國民黨、民進黨的立場。"
         f"每一項都盡量用老師模型 `{TEACHER}` 自己的標籤重算一次，跨年比較則只用每年都有資料的同一組 6 家媒體"
         "（中國時報、中央社、自由時報、三立、風傳媒、TVBS），避免媒體加入或退出樣本造成假的趨勢。"
         "沒有通過這些檢查的觀察，列在最後一節。\n",
         "這些都是描述性的規律，不是因果結論。分數的意義與限制見 [README](../README.md) 第 10 節。\n"]

    # 1. lean through the opponent
    a = cells(m[m.year >= "2024"], ["outlet"], 30).set_index("outlet")
    b = cells(t[t.year >= "2019"], ["outlet"], 30).set_index("outlet")
    L += ["## 1. 傾向主要來自對另一黨的負面報導\n",
          "把「國民黨 − 民進黨」拆回兩黨各自的平均分數。偏國民黨的媒體，對國民黨的報導大約中性，差距幾乎全來自對民進黨的負面報導；"
          "偏民進黨的媒體，對國民黨明顯負面，對民進黨只是微幅正面。沒有一家媒體對國民黨的平均是明顯正面的。\n",
          "| 媒體 | 模型：國民黨 | 模型：民進黨 | 模型：差距 | 老師：國民黨 | 老師：民進黨 | 老師篇數 |",
          "|---|---|---|---|---|---|---|"]
    for o, r in a.sort_values("gap").iterrows():
        tb = b.loc[o] if o in b.index else None
        L.append(f"| {NAME[o]} | {f(r.kmt)} | {f(r.dpp)} | {f(r.gap)} | {f(tb.kmt) if tb is not None else '—'} | "
                 f"{f(tb.dpp) if tb is not None else '—'} | {int(tb.nk) if tb is not None else '—'} |")
    L.append("\n模型為 2024-01 至 2026-09；老師為 2019-01 至 2026-09（老師的樣本較少，所以取較長期間）。老師篇數為提到國民黨的篇數。\n")

    # 2. topic composition
    d = m[m.year >= "2020"]
    common = d.topic.value_counts(normalize=True)
    rows = []
    for o, g in d.groupby("outlet"):
        by = cells(g, ["topic"], 15).set_index("topic")
        w = common.reindex(by.index)
        rows.append((o, g.kmt.mean() - g.dpp.mean(), float((by.gap * w / w.sum()).sum())))
    rows.sort(key=lambda r: r[1])
    sd = cells(d, ["topic", "outlet"], 30).groupby("topic").gap.std()
    L += ["## 2. 差異不是議題組成造成的\n",
          "一家媒體可能只是比較常報導對某黨不利的議題。把每家媒體都換成同一個議題比例（全體 2020-01 至 2026-09 的議題分布）重新加權，"
          "差距幾乎不變。在每一個議題裡，媒體之間的差距也都差不多大，所以傾向是全面性的，不是集中在某一類新聞。\n",
          "| 媒體 | 原始差距 | 同一議題比例 |", "|---|---|---|"]
    L += [f"| {NAME[o]} | {f(x)} | {f(y)} |" for o, x, y in rows]
    L.append(f"\n各議題內，媒體之間差距的標準差：{'、'.join(f'{TOPIC[k]} {v:.2f}' for k, v in sd.sort_values().items())}。\n")

    # 3. opinion vs news
    mo = cells(m[m.year >= "2019"], ["outlet", "genre"], 30)
    to = cells(t[t.year >= "2019"], ["outlet", "genre"], 15)
    L += ["## 3. 評論比新聞更偏，但仍然不是在稱讚自己人\n",
          "在有足夠評論文章的媒體裡，評論的差距大約是新聞的 1.4 到 3 倍。增加的部分主要來自對另一黨更負面，評論對自己人甚至比新聞略差。""鏡週刊的評論方向與新聞相反（偏國民黨），但只有 36 篇。"
          "風傳媒最明顯：老師標籤下，它的新聞只略偏國民黨，偏向大多來自評論。"
          "歷史抽樣以政治版為主，評論只占約 2%，各家評論被抽到的比例也不同，所以這裡只比較同一家媒體內部的新聞與評論。\n",
          "| 媒體 | 來源 | 新聞：國民黨／民進黨／差距（篇數） | 評論：國民黨／民進黨／差距（篇數） |", "|---|---|---|---|"]
    for src, tab in (("模型", mo), ("老師", to)):
        for o in [o for o in tab.outlet.unique() if {"news", "opinion"} <= set(tab[tab.outlet == o].genre)]:
            n, p = (tab[(tab.outlet == o) & (tab.genre == g)].iloc[0] for g in ("news", "opinion"))
            L.append(f"| {NAME[o]} | {src} | {f(n.kmt)}／{f(n.dpp)}／{f(n.gap)}（{int(n.nk):,}） | {f(p.kmt)}／{f(p.dpp)}／{f(p.gap)}（{int(p.nk):,}） |")
    L.append("\n2019-01 至 2026-09；模型每格至少 30 篇，老師至少 15 篇。\n")

    # 4. issues
    eq = cells(m[m.year >= "2020"], ["topic", "outlet"], 30).groupby("topic").agg(kmt=("kmt", "mean"), dpp=("dpp", "mean"))
    tt = t[t.year >= "2019"].groupby("topic").agg(kmt=("kmt", "mean"), dpp=("dpp", "mean"), n=("kmt", "count"))
    L += ["## 4. 各黨在哪些議題上被呈現得最好與最差\n",
          "模型欄是每家媒體權重相同的平均（避免篇數多的媒體主導），老師欄是全部文章合併。"
          "外交國防是民進黨唯一平均接近或高於 0 的議題；能源環境與司法醜聞是民進黨最負面的議題。"
          "國民黨在兩岸、立法院與司法醜聞上最負面。\n",
          "| 議題 | 模型：國民黨 | 模型：民進黨 | 老師：國民黨 | 老師：民進黨 | 老師篇數 |", "|---|---|---|---|---|---|"]
    for k in eq.sort_values("dpp").index:
        L.append(f"| {TOPIC[k]} | {f(eq.loc[k, 'kmt'])} | {f(eq.loc[k, 'dpp'])} | {f(tt.kmt.get(k))} | {f(tt.dpp.get(k))} | {int(tt.n.get(k, 0)):,} |")
    L.append("\n模型為 2020-01 至 2026-09，老師為 2019-01 至 2026-09。能源環境的文章較少（模型只有 8 家媒體達到門檻）。\n")

    # 5. spread over time
    y = cells(m[m.outlet.isin(FIXED)], ["year", "outlet"], 30)
    ys = y.groupby("year").agg(sd=("gap", "std"), lo=("gap", "min"), hi=("gap", "max"), mean=("gap", "mean"), n=("gap", "count"))
    ys = ys[ys.n == len(FIXED)]
    bins, labels = [2011, 2015, 2018, 2022, 2026], ["2012–15", "2016–18", "2019–22", "2023–26"]
    per = {}
    for src, df in (("模型", m), ("老師", t)):
        x = df[df.outlet.isin(FIXED)].copy()
        x["per"] = pd.cut(x.year.astype(int), bins, labels=labels)
        per[src] = cells(x, ["per", "outlet"], 20).groupby("per", observed=True).gap.agg(["std", "count"])
    L += ["## 5. 媒體之間的距離從 2018–2019 年開始拉大，不是 2016 年政黨輪替\n",
          "同一組 6 家媒體每年「國民黨 − 民進黨」的標準差：2014–2017 年約 0.3–0.4，2019 年之後維持在 0.55–0.70。"
          "拉大主要來自中國時報與風傳媒往國民黨方向移動、三立在 2019–2020 年更偏民進黨。老師標籤的分期結果方向相同。\n",
          "| 年 | 標準差 | 最低 | 最高 | 平均 |", "|---|---|---|---|---|"]
    L += [f"| {yr} | {r.sd:.2f} | {f(r.lo)} | {f(r.hi)} | {f(r['mean'])} |" for yr, r in ys.iterrows()]
    L += ["\n| 期間 | 模型標準差（媒體數） | 老師標準差（媒體數） |", "|---|---|---|"]
    for lab in labels:
        cell = lambda s: f"{per[s].loc[lab, 'std']:.2f}（{int(per[s].loc[lab, 'count'])}）" if lab in per[s].index else "—"
        L.append(f"| {lab} | {cell('模型')} | {cell('老師')} |")
    L.append("\n老師每格至少 20 篇，模型每年每家至少 30 篇。\n")

    # 6. governing party
    L += ["## 6. 執政黨普遍被呈現得較差\n",
          "上表「平均」一欄是 6 家媒體差距的平均：國民黨執政的 2014–2015 年約 −0.28，民進黨執政後逐年移向 0，2021 年之後約 0。"
          "也就是說，兩黨的相對位置大約移動了 0.3，相當於每個政黨執政時約少拿 0.15 分。"
          "這個移動是逐年發生的，不是在 2016 年一次跳動，所以也可能混有其他長期變化。比較同一家媒體在不同執政期的分數時，要先考慮這個效應。\n"]

    # 7. common shocks
    mm = cells(m[(m.outlet.isin(FIXED)) & (m.year >= "2014")], ["outlet", "month"], 10)
    cm = mm.groupby("month").agg(kmt=("kmt", "mean"), dpp=("dpp", "mean"), n=("kmt", "count"))
    cm = cm[cm.n == len(FIXED)]
    for p in ("kmt", "dpp"):
        cm[p + "_dev"] = cm[p] - cm[p].rolling(13, center=True, min_periods=7).median()
    L += ["## 7. 模型自己找到的重大事件\n",
          "模型不知道任何事件。把同一組 6 家媒體每月的平均分數，減去前後一年的中位數，找出所有媒體一起偏離的月份，"
          "再讀那幾個月最負面（或最正面）文章的標題，辨認是什麼事件。結果大多對得上已知的重大事件，這也是一項額外的效度檢查。\n",
          "| 月份 | 政黨 | 偏離 | 那幾個月的報導主要在講 |", "|---|---|---|---|"]
    picks = [(cm.kmt_dev.nsmallest(3), "國民黨"), (cm.dpp_dev.nsmallest(3), "民進黨"), (cm.kmt_dev.nlargest(1), "國民黨")]
    shown = set()
    for s, party in picks:
        for mon, v in s.items():
            shown.add(mon)
            L.append(f"| {mon} | {party} | {f(v)} | {EVENTS.get(mon, '（尚未辨認）')} |")
    lvl = cm.kmt.idxmin()
    L.append(f"\n若不扣除長期水準，國民黨分數最低的月份是 {lvl}（{f(cm.kmt.min())}，{EVENTS.get(lvl, '尚未辨認')}）。"
             "偏離最大的月份會隨扣除長期水準的方式而略有不同；事件的辨認是我們讀標題的判斷，不是模型的輸出。\n")

    # 8. caveats
    ftv = cells(m[m.outlet == "ftv"], ["year", "archive"], 30)
    pre = ftv[(ftv.archive) & (ftv.year <= "2017")].gap.mean()
    post = ftv[(~ftv.archive) & (ftv.year >= "2019") & (ftv.year <= "2021")].gap.mean()
    cna = cells(m[(m.outlet == "cna") & (m.year == "2014")], ["archive"], 30).set_index("archive").gap
    votes = ["2012-01", "2014-11", "2016-01", "2018-11", "2020-01", "2022-11", "2024-01"]
    pre_vote = {f"{(int(v[:4]) * 12 + int(v[5:]) - 1 - k) // 12}-{(int(v[5:]) - 1 - k) % 12 + 1:02d}" for v in votes for k in range(3)}
    allm = cells(m, ["month", "outlet"], 20).groupby("month").gap.agg(["std", "count"])
    allm = allm[allm["count"] >= 6]
    fixm = cells(m[m.outlet.isin(FIXED)], ["month", "outlet"], 20).groupby("month").gap.agg(["std", "count"])
    fixm = fixm[fixm["count"] == len(FIXED)]
    sd_pre, sd_other = allm[allm.index.isin(pre_vote)]["std"].mean(), allm[~allm.index.isin(pre_vote)]["std"].mean()
    L += ["## 8. 需要小心或沒有通過檢查的觀察\n",
          f"- **民視的跳動與資料來源重疊**：民視 2017 年以前來自 Internet Archive（2012–2017 平均差距 {f(pre)}），2019 年起來自自家網站"
          f"（2019–2021 平均 {f(post)}），中間缺 2018 年，同時期也更換了董事長。目前無法分開真實變化與來源造成的差異；"
          "作為對照，中央社 2014 年兩種來源都有，差距分別是 "
          f"{f(cna.get(True))}（Internet Archive）與 {f(cna.get(False))}（自家網站）。",
          "- **公營媒體跟著執政黨移動**：2016 年後多數媒體往國民黨方向移動，中央社反向往民進黨移動。但中央社 2014 年以前來自 Internet Archive，"
          "變化又發生在 2015 年（政黨輪替之前），樣本也只有中央社與公視兩家，目前不作為結論。",
          f"- **最極化的月份**：用當月所有達到門檻的媒體計算，媒體之間標準差最大的月份是 {allm['std'].idxmax()}"
          f"（{allm['std'].max():.2f}）；改用固定 6 家，最大的是 {fixm['std'].idxmax()}（{fixm['std'].max():.2f}）。"
          "結果取決於當月有哪些媒體，所以不作為結論。",
          f"- **選前是否更極化**：投票前 3 個月與其他月份，媒體之間的標準差平均為 {sd_pre:.2f} 與 {sd_other:.2f}，"
          "看不出差別，但只有 7 次全國性選舉，檢定力很低。\n"]
    out = ROOT / "docs" / "findings.md"
    out.write_text("\n".join(L), encoding="utf-8")
    print("\n".join(L))


if __name__ == "__main__":
    main()

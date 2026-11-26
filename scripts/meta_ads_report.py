"""Political and issue ads on Meta (Facebook, Instagram) paid for by the 13 outlets and by the parties.

    uv run python scripts/meta_ads_report.py

Reads the Meta Ad Library Report for Taiwan (data/raw/meta_adlib/report_TW_*/, downloaded by
scripts/meta_report_download.py) and the per-Page ad lists (data/raw/meta_adlib/*_pages_*.jsonl, from
scripts/meta_adlibrary.py), and writes docs/meta-ads.md. Only aggregates are written; ad text stays local.
"""

from __future__ import annotations

import csv
import glob
import json
import re
from collections import defaultdict
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
RAW = ROOT / "data" / "raw" / "meta_adlib"

# Each outlet's flagship news Page(s) on Facebook, by Page ID. 中央社 has no Page in the report.
FLAGSHIP = {
    "自由時報": ["394896373929368"], "中時新聞網": ["188311137478"], "ETtoday": ["242305665805605"],
    "TVBS": ["220050085932"], "三立": ["110699089014688"], "民視": ["235679595900"], "東森": ["124616330906800"],
    "公視": ["852969588088569"], "風傳媒": ["186758878172497"], "鏡週刊／鏡新聞": ["1855418728011324", "850754301947812"],
    "聯合新聞網／聯合報": ["241284961029", "219315794887869"], "中天": ["223683434464256"],
}
# Names in the "Paid for by" disclaimer that identify the outlet or its company, for the group total.
PAYER = {
    "自由時報": ["自由時報"], "中時新聞網": ["時報資訊", "時際創意"], "ETtoday": [], "TVBS": ["TVBS"], "三立": ["三立"],
    "民視": ["民視新聞"], "東森": ["東森新聞", "東森財經", "東森電視", "EBC Co"], "公視": ["公視", "公共電視"],
    "風傳媒": ["風傳媒", "風生活"], "鏡週刊／鏡新聞": ["鏡週刊", "鏡新聞", "鏡電視"],
    "聯合新聞網／聯合報": ["聯合新聞網", "聯合報", "經濟日報", "udn.com"], "中天": [],
}
PARTIES = {"中國國民黨": ["131181017972"], "民主進步黨": ["150336441057"], "台灣民眾黨": ["104699394209550"],
           "時代力量": ["891084220962935"]}


def amount(x: dict) -> int:
    v = x["Amount spent (TWD)"]
    return int(v) if v.isdigit() else 0  # "≤100" counts as 0


def load(preset: str) -> tuple[str, list[dict]]:
    files = sorted(glob.glob(str(RAW / "report_TW_*" / f"FacebookAdLibraryReport_*_TW_{preset}_advertisers.csv")))
    f = files[-1]
    day = re.search(r"Report_(\d{4}-\d\d-\d\d)_", f).group(1)
    return day, list(csv.DictReader(open(f, encoding="utf-8-sig")))


def by_page(rows: list[dict], ids: list[str]) -> tuple[int, int]:
    hit = [x for x in rows if x["Page ID"] in ids]
    return sum(amount(x) for x in hit), sum(int(x["Number of ads in Library"]) for x in hit)


def by_group(rows: list[dict], ids: list[str], names: list[str]) -> tuple[int, int]:
    """The flagship Pages plus every Page whose disclaimer names the outlet or its company."""
    hit = [x for x in rows if x["Page ID"] in ids or any(n.lower() in x["Disclaimer"].lower() for n in names)]
    return sum(amount(x) for x in hit), sum(int(x["Number of ads in Library"]) for x in hit)


def nt(v: int) -> str:
    return f"{v:,}" if v else "0"


def main() -> None:
    day, life = load("lifelong")
    _, d90 = load("last_90_days")
    total = sum(amount(x) for x in life)
    out = [
        "# Meta 上的政治與議題廣告：媒體與政黨",
        "",
        f"日期：{date.today().isoformat()}　資料：Meta 廣告檔案庫報告（台灣，截至 {day}）　程式：`scripts/meta_ads_report.py`",
        "",
        "Meta 要求在台灣投放社會議題、選舉或政治廣告的廣告主先通過身分驗證並標示出資者，這些廣告保存在廣告檔案庫。"
        "檔案庫報告列出每個粉絲專頁與出資者組合的總花費與廣告數。"
        f"台灣自 2019 年 11 月起共 {len(life):,} 個組合，加總 NT${total:,}（「≤100」以 0 計；報告頁顯示的總額為 NT$903,085,366）。"
        "媒體付費推廣自己的貼文，若 Meta 判定屬於社會議題、選舉或政治類，也會列入檔案庫，所以媒體本身也出現在報告裡。"
        "讀過各媒體粉專的廣告文字，這些廣告包含兩類：推廣自己的政治新聞，以及替企業或政府機關製作的贊助內容"
        "（例如永續專題、交通安全宣導、市府消費活動）。下表的金額是兩類的合計。",
        "",
        "## 1. 各媒體的花費",
        "",
        "「主要粉專」為各媒體的新聞主粉專（公視為公視+）；「同集團」為主要粉專加上出資者欄標示該媒體或其公司的其他粉專（含財經、房產等子頻道）。"
        "金額為新台幣，「≤100」的組合以 0 計。",
        "",
        "| 媒體 | 主要粉專：全期 | 廣告數 | 主要粉專：近 90 天 | 廣告數 | 同集團：全期 |",
        "|---|---:|---:|---:|---:|---:|",
    ]
    rows = []
    for o, ids in FLAGSHIP.items():
        la, ln = by_page(life, ids)
        na, nn = by_page(d90, ids)
        ga, _ = by_group(life, ids, PAYER[o])
        rows.append((la, f"| {o} | {nt(la)} | {ln:,} | {nt(na)} | {nn:,} | {nt(ga)} |"))
    out += [r for _, r in sorted(rows, key=lambda r: -r[0])]
    out += ["| 中央社 | 0 | 0 | 0 | 0 | 0 |", "",
            "ETtoday 與中天的廣告多數沒有標示出資者，同集團金額只含主要粉專。報告中另有多個以中天主播為名的粉專，"
            "無法確認是否為官方帳號，未計入。", ""]

    out += ["## 2. 政黨的花費（對照）", "", "| 政黨 | 全期 | 廣告數 | 近 90 天 | 廣告數 |", "|---|---:|---:|---:|---:|"]
    for p, ids in PARTIES.items():
        la, ln = by_page(life, ids)
        na, nn = by_page(d90, ids)
        out.append(f"| {p} | {nt(la)} | {ln:,} | {nt(na)} | {nn:,} |")
    out += ["", "只計各黨中央的主粉專；地方黨部、黨團、青年部與候選人個人粉專另計。", ""]

    # campaign-period ads of the flagship pages, from the per-Page lists
    ads = {}
    for f in sorted(glob.glob(str(RAW / "*_pages_*.jsonl"))):
        for line in open(f, encoding="utf-8"):
            a = json.loads(line)
            ads[a["library_id"]] = a
    if ads:
        name = {pid: o for o, ids in FLAGSHIP.items() for pid in ids}
        g = defaultdict(lambda: [0, 0, 0])
        for a in ads.values():
            o = name.get(a["query"])
            if not o or not a.get("start") or a["start"] < "2026-08-26":
                continue
            body = a.get("body") or ""
            r = g[o]
            r[0] += 1
            r[1] += "國民黨" in body or "藍營" in body
            r[2] += "民進黨" in body or "綠營" in body
        out += ["## 3. 選戰期間付費推廣的貼文（2026-08-26 起）", "",
                "從各主要粉專在檔案庫中的廣告清單計算。檔案庫把使用同一份素材的多則廣告合併顯示，清單以開始投放日篩選，報告則計入期間內有曝光的廣告，所以兩欄的計法不同。"
                "「提到」為貼文文字包含該黨名稱或藍營、綠營。", "",
                "| 媒體 | 素材數 | 報告的廣告數（近 90 天） | 提到國民黨 | 提到民進黨 |", "|---|---:|---:|---:|---:|"]
        for o, (n, k, d) in sorted(g.items(), key=lambda z: -z[1][0]):
            out.append(f"| {o} | {n} | {by_page(d90, FLAGSHIP[o])[1]:,} | {k} | {d} |")
        out += ["", "鏡新聞與中天新聞的粉專在這段期間沒有這類廣告。選戰期間付費推廣的貼文提到政黨的，集中在民視與鏡週刊；"
                "其他媒體推廣的多半是贊助內容或非選舉議題。", ""]

    out += ["## 4. 資料取得方式", "",
            "廣告檔案庫報告由報告頁的「Download report」下載，各粉專的廣告清單由公開的檔案庫網頁讀取，兩者都不登入，"
            "使用標明本研究的 User-Agent，每頁間隔 15 秒。facebook.com 的 robots.txt 不允許自動程式存取；"
            "因為 Meta 的官方 API 需要另行申請身分驗證，本研究改用開源工具"
            "（[crawl4ai](https://github.com/unclecode/crawl4ai)，解析方式參考 "
            "[facebook-ads-library-mcp](https://github.com/RamsesAguirre777/facebook-ads-library-mcp)）讀取這些公開頁面。"
            "原始頁面與貼文文字只留在本機，公開的只有上方的彙總數字。", ""]
    (ROOT / "docs" / "meta-ads.md").write_text("\n".join(out), encoding="utf-8")
    print("\n".join(out))


if __name__ == "__main__":
    main()

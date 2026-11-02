"""Pick the political YouTube channels to track, by a fixed rule (PLAN.md §4.6).

1. Search YouTube (official Data API) for recent Taiwanese political videos and channels.
2. Keep channels that are Taiwanese, still active in 2026, and not one of the 12 outlets already tracked.
3. An LLM reads each candidate's latest video titles and estimates the share that is about politics.
4. Channels with a political share >= 0.5 are ranked by subscribers; the top 15 are selected.

Outputs config/youtube_channels.yaml (used by the collector) and docs/youtube-selection.md.
Usage:  uv run python scripts/select_youtube_channels.py
"""

from __future__ import annotations

import json
import re
import subprocess
import sys
import tempfile
from datetime import date
from pathlib import Path

import yaml

from twmedia.collectors.youtube import _get, api_key
from twmedia.http import PoliteClient

ROOT = Path(__file__).resolve().parents[1]
LLM = "opencode-go/deepseek-v4.1-flash"
TOP_N = 15
MIN_SHARE = 0.5
MIN_SUBSCRIBERS = 50_000
ACTIVE_SINCE = "2026-01-01"
CANDIDATES_TO_SCORE = 60
VIDEO_QUERIES = [
    "政論節目", "台灣政治 評論", "國民黨", "民進黨", "民眾黨", "立法院 質詢", "2026 九合一 選舉",
    "台北市長 辯論", "賴清德", "鄭麗文", "黃國昌", "兩岸 關係 評論", "罷免", "時事 評論 台灣",
]
CHANNEL_QUERIES = ["政論", "台灣 時事 評論", "政治 頻道 台灣", "新聞 評論"]
CJK_TRAD = re.compile(r"[們這個國會與說時於為對後過還點]")  # common traditional-only forms

PROMPT = """You classify YouTube channels for a study of Taiwanese political media.
For each channel below you get its name and its latest video titles.
Estimate political_share: the fraction of titles about Taiwanese politics (parties, elections,
legislature, government, cross-strait politics, political commentary). Entertainment, lifestyle,
general accidents/weather, sports, finance tips do not count.
Also set taiwan: true if the channel mainly targets a Taiwanese audience.
Set owner to one of:
- "news_org": run by a TV station, newspaper or news website (including its program channels);
  put the company/brand in parent (e.g. "三立", "TVBS", "民視", "東森", "中天", "年代", "台視")
- "politician_or_party": run by a politician, party, campaign or government office
- "independent": an independent commentator, YouTuber or podcast
- "other"
Answer ONLY with a JSON array, one object per channel, in the same order:
[{{"id": "...", "political_share": 0.0, "taiwan": true, "owner": "news_org", "parent": "三立"}}]

{channels}
"""


def search_channel_ids(client: PoliteClient, key: str) -> dict[str, int]:
    hits: dict[str, int] = {}
    for q in VIDEO_QUERIES:
        res = _get(client, "search", key, part="snippet", type="video", q=q, regionCode="TW",
                   relevanceLanguage="zh-Hant", order="viewCount", maxResults=50,
                   publishedAfter="2026-05-01T00:00:00Z")
        for it in res.get("items", []):
            cid = it["snippet"]["channelId"]
            hits[cid] = hits.get(cid, 0) + 1
    for q in CHANNEL_QUERIES:
        res = _get(client, "search", key, part="snippet", type="channel", q=q, regionCode="TW",
                   relevanceLanguage="zh-Hant", maxResults=50)
        for it in res.get("items", []):
            cid = it["snippet"]["channelId"]
            hits[cid] = hits.get(cid, 0) + 1
    return hits


def channel_details(client: PoliteClient, key: str, ids: list[str]) -> list[dict]:
    out = []
    for i in range(0, len(ids), 50):
        res = _get(client, "channels", key, part="snippet,statistics,contentDetails", id=",".join(ids[i:i + 50]))
        out.extend(res.get("items", []))
    return out


def recent_titles(client: PoliteClient, key: str, uploads: str) -> tuple[list[str], str | None]:
    res = _get(client, "playlistItems", key, part="snippet", playlistId=uploads, maxResults=25)
    items = res.get("items", [])
    titles = [i["snippet"]["title"] for i in items]
    latest = max((i["snippet"].get("publishedAt", "") for i in items), default=None)
    return titles, latest


def classify(batch: list[dict]) -> list[dict]:
    text = "\n\n".join(
        f"id: {c['id']}\nname: {c['title']}\ntitles:\n" + "\n".join(f"- {t}" for t in c["titles"]) for c in batch
    )
    # Run in an empty directory so the coding agent behind `opencode run` has no project files to touch.
    with tempfile.TemporaryDirectory() as empty:
        out = subprocess.run(["opencode", "run", "-m", LLM, "--agent", "plan", "--pure", PROMPT.format(channels=text)],
                             capture_output=True, text=True, timeout=300, cwd=empty).stdout
    m = re.search(r"\[.*\]", out, re.S)
    if not m:
        raise RuntimeError(f"LLM gave no JSON: {out[-500:]}")
    return json.loads(m.group(0))


OUTLET_BRANDS = {
    "cna": ["中央社"], "ltn": ["自由"], "udn": ["聯合", "udn"], "chinatimes": ["中時", "中國時報"],
    "ettoday": ["ETtoday", "東森新聞雲"], "tvbs": ["TVBS"], "setn": ["三立", "SET"], "ftv": ["民視", "Formosa"],
    "ebc": ["東森"], "pts": ["公視", "PTS"], "storm": ["風傳媒"], "mirror": ["鏡"],
}


def outlet_of(c: dict, sources: dict) -> str | None:
    """Map a news-org channel to one of the 12 tracked outlets by brand name, if it belongs to one."""
    text = f"{c.get('parent') or ''} {c['title']}"
    for key, brands in OUTLET_BRANDS.items():
        if key in sources["outlets"] and any(b.lower() in text.lower() for b in brands):
            return "ettoday" if key == "ebc" and "ETtoday" in text else key
    return None


def main() -> None:
    key = api_key()
    if not key:
        sys.exit("YOUTUBE_API_KEY missing")
    sources = yaml.safe_load((ROOT / "config" / "sources.yaml").read_text(encoding="utf-8"))
    outlet_ids = {o["youtube"] for o in sources["outlets"].values() if o.get("youtube")}
    client = PoliteClient(min_interval=0.5)

    # Searches cost 100 quota units each; cache today's results so a rerun only redoes the LLM step.
    cache = ROOT / "data" / f"youtube_selection_cache_{date.today().isoformat()}.json"
    if cache.exists():
        hits, details = json.loads(cache.read_text(encoding="utf-8"))
    else:
        hits = search_channel_ids(client, key)
        details = channel_details(client, key, [c for c in hits if c not in outlet_ids])
        cache.write_text(json.dumps([hits, details], ensure_ascii=False), encoding="utf-8")

    cands = []
    for ch in details:
        sn, st = ch["snippet"], ch.get("statistics", {})
        text = sn.get("title", "") + sn.get("description", "")
        taiwanese = sn.get("country") == "TW" or (sn.get("country") is None and bool(CJK_TRAD.search(text)))
        subs = int(st.get("subscriberCount", 0)) if not st.get("hiddenSubscriberCount") else 0
        if taiwanese and subs >= MIN_SUBSCRIBERS:
            cands.append({"id": ch["id"], "title": sn.get("title"), "country": sn.get("country"),
                          "subscribers": subs, "search_hits": hits[ch["id"]],
                          "uploads": ch["contentDetails"]["relatedPlaylists"]["uploads"]})
    cands.sort(key=lambda c: c["subscribers"], reverse=True)
    cands = cands[:CANDIDATES_TO_SCORE]

    for c in cands:
        c["titles"], c["latest_upload"] = recent_titles(client, key, c["uploads"])
    cands = [c for c in cands if c["latest_upload"] and c["latest_upload"] >= ACTIVE_SINCE]

    scores = {}
    for i in range(0, len(cands), 10):
        for s in classify(cands[i:i + 10]):
            scores[s["id"]] = s
    for c in cands:
        s = scores.get(c["id"], {})
        c["political_share"] = s.get("political_share")
        c["taiwan_audience"] = s.get("taiwan")
        c["owner"] = s.get("owner")
        c["parent"] = s.get("parent")
        c["outlet"] = outlet_of(c, sources) if c["owner"] == "news_org" else None

    political = [c for c in cands if (c["political_share"] or 0) >= MIN_SHARE and c["taiwan_audience"]]
    # Program channels of the 12 tracked outlets join that outlet; politicians' channels are anchors, not media.
    sub_channels = [c for c in political if c["outlet"]]
    party_channels = [c for c in political if c["owner"] == "politician_or_party"]
    eligible = [c for c in political if not c["outlet"] and c["owner"] != "politician_or_party"]
    selected = eligible[:TOP_N]

    today = date.today().isoformat()
    (ROOT / "config" / "youtube_channels.yaml").write_text(
        f"# Generated by scripts/select_youtube_channels.py on {today}. Do not edit by hand; rerun the script.\n"
        f"# Rule: Taiwanese, active since {ACTIVE_SINCE}, >= {MIN_SUBSCRIBERS} subscribers, LLM political share >= {MIN_SHARE}"
        f" ({LLM}), top {TOP_N} by subscribers. The 12 outlets' own channels are tracked separately.\n"
        + yaml.safe_dump({
            "selected_on": today,
            "channels": [{"id": c["id"], "title": c["title"], "subscribers": c["subscribers"],
                          "political_share": c["political_share"], "owner": c["owner"], "parent": c["parent"]}
                         for c in selected],
            "outlet_subchannels": [{"id": c["id"], "title": c["title"], "outlet": c["outlet"]} for c in sub_channels],
            "party_channels": [{"id": c["id"], "title": c["title"]} for c in party_channels],
        }, allow_unicode=True, sort_keys=False),
        encoding="utf-8",
    )
    rows = "\n".join(
        f"| {'✓' if c in selected else '媒體子頻道→' + c['outlet'] if c in sub_channels else '政治人物' if c in party_channels else ''}"
        f" | {c['title']} | {c['owner'] or '—'} | {c['subscribers']:,} | "
        f"{c['political_share'] if c['political_share'] is not None else '—'} | {c['latest_upload'][:10]} |"
        for c in cands
    )
    (ROOT / "docs" / "youtube-selection.md").write_text(
        f"# YouTube 政治頻道篩選結果\n\n執行日期：{today}。規則見 `scripts/select_youtube_channels.py` 開頭與 PLAN.md 第 4.6 節。\n\n"
        f"- 搜尋：{len(VIDEO_QUERIES)} 組影片關鍵字（2026-05 以後、依觀看數）、{len(CHANNEL_QUERIES)} 組頻道關鍵字，地區 TW\n"
        f"- 門檻：台灣頻道、訂閱 {MIN_SUBSCRIBERS:,} 以上、{ACTIVE_SINCE} 後仍有上傳；12 家媒體的官方頻道另外追蹤，不列入\n"
        f"- 政治內容比例：由 `{LLM}` 讀取最新 25 支影片標題估計，門檻 {MIN_SHARE}\n"
        f"- 分類：同一個 LLM 判斷頻道經營者。屬於已追蹤的 12 家媒體的節目頻道，併入該媒體；政治人物或政黨的頻道不算媒體，另列為立場錨點\n"
        f"- 結果：{len(cands)} 個候選，{len(political)} 個政治內容達門檻；其中 {len(sub_channels)} 個是 12 家媒體的子頻道、"
        f"{len(party_channels)} 個是政治人物或政黨；其餘 {len(eligible)} 個依訂閱數取前 {TOP_N} 個（✓）\n\n"
        "LLM 的判斷每次可能略有不同；重跑時以新產生的檔案為準，並保留舊版於 git 紀錄。\n\n"
        "| 入選 | 頻道 | 經營者 | 訂閱數 | 政治內容比例 | 最近上傳 |\n|---|---|---|---|---|---|\n" + rows + "\n",
        encoding="utf-8",
    )
    print(f"candidates={len(cands)} political={len(political)} sub={len(sub_channels)} party={len(party_channels)} selected={len(selected)}")
    for c in sub_channels:
        print(f"  sub   {c['outlet']:10} {c['title']}")
    for c in party_channels:
        print(f"  party            {c['title']}")
    for c in selected:
        print(f"  {c['subscribers']:>10,}  {c['political_share']}  {c['title']}")


if __name__ == "__main__":
    main()

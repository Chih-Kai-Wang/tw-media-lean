"""Meta Ad Library (Taiwan, political and issue ads) by keyword, without login or API token.

    uv run --with crawl4ai python scripts/meta_adlibrary.py search 國民黨 民進黨     # keyword search
    uv run --with crawl4ai python scripts/meta_adlibrary.py search --since 2026-09-01 九合一
    uv run --with crawl4ai python scripts/meta_adlibrary.py outlets               # the 13 outlets' names
    uv run --with crawl4ai python scripts/meta_adlibrary.py report                # Ad Library Report page, Taiwan
    uv run --with crawl4ai python scripts/meta_adlibrary.py reportcsv 2026-11-23  # report CSVs (all dates, 90, 30, 7 days)
    uv run --with crawl4ai python scripts/meta_adlibrary.py pages 150336441057 ... # every political ad of these Page IDs

Renders the public Ad Library page in headless Chromium (crawl4ai), scrolls it, and parses the ad cards.
The render and parse code follow RamsesAguirre777/facebook-ads-library-mcp (MIT).
No login, no cookies, no proxy, no stealth mode; the project's own user agent. One page every 15 seconds.
Stops at a login wall or a checkpoint page. Raw pages go to data/raw/meta_adlib/ (git-ignored).
"""

from __future__ import annotations

import asyncio
import json
import re
import sys
import time
from datetime import datetime
from pathlib import Path
from urllib.parse import quote

from crawl4ai import AsyncWebCrawler, BrowserConfig, CacheMode, CrawlerRunConfig

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "data" / "raw" / "meta_adlib"
UA = "twmedia-research/0.1 (+https://github.com/Chih-Kai-Wang)"
BASE = "https://www.facebook.com/ads/library/"
SCROLLS = 6
PAUSE = 15  # seconds between pages


# Names the 13 outlets use as advertisers or in "Paid for by"; matched locally against advertiser and paid_for_by.
OUTLETS = ["中央社", "自由時報", "中時新聞網", "ETtoday", "TVBS", "三立新聞", "民視新聞", "東森新聞", "公視新聞",
           "風傳媒", "鏡週刊", "聯合新聞網", "中天新聞"]


def url_for(q: str, since: str = "") -> str:
    p = {"active_status": "all", "ad_type": "political_and_issue_ads", "country": "TW", "media_type": "all",
         "search_type": "keyword_unordered", "q": q}
    if since:
        p["start_date[min]"] = since
    return BASE + "?" + "&".join(f"{quote(k)}={quote(v)}" for k, v in p.items())


def page_url(pid: str, since: str = "") -> str:
    p = {"active_status": "all", "ad_type": "political_and_issue_ads", "country": "TW", "media_type": "all",
         "search_type": "page", "view_all_page_id": pid}
    if since:
        p["start_date[min]"] = since
    return BASE + "?" + "&".join(f"{quote(k)}={quote(v)}" for k, v in p.items())


REPORT = "https://www.facebook.com/ads/library/report/?source=nav-header&country=TW"


async def render(url: str) -> tuple[int | None, str, str]:
    bc = BrowserConfig(headless=True, user_agent=UA, headers={"Accept-Language": "en-US,en;q=0.9"},
                       viewport_width=1400, viewport_height=1600, verbose=False)
    js = "await new Promise(r=>setTimeout(r,8000));" + "".join(
        "window.scrollTo(0, document.body.scrollHeight);await new Promise(r=>setTimeout(r,2500));" for _ in range(SCROLLS))
    cfg = CrawlerRunConfig(cache_mode=CacheMode.BYPASS, delay_before_return_html=4, page_timeout=120000,
                           js_code=[js], verbose=False)
    async with AsyncWebCrawler(config=bc) as c:
        r = await c.arun(url=url, config=cfg)
        md = r.markdown.raw_markdown if hasattr(r.markdown, "raw_markdown") else str(r.markdown or "")
        return r.status_code, md or "", r.html or ""


def money(s: str | None) -> tuple[int | None, int | None]:
    """'NT$125K - NT$150K' -> (125000, 150000); '< NT$100' -> (0, 100)."""
    if not s:
        return None, None
    mult = {"": 1, "K": 1_000, "M": 1_000_000}
    v = [int(float(a) * mult[b.upper()]) for a, b in re.findall(r"NT\$\s?([\d.]+)\s?([KkMm]?)", s.replace(",", ""))]
    if not v:
        return None, None
    return (0, v[0]) if "<" in s else (v[0], v[-1])


def parse(md: str) -> list[dict]:
    """Ad cards start at a "Library ID: <digits>" line, with Active/Inactive on the line before it."""
    ads, seen = [], set()
    parts = re.split(r"\n(Active|Inactive)\nLibrary ID:\s*", md)
    for status, chunk in zip(parts[1::2], parts[2::2]):
        m = re.match(r"(\d+)", chunk)
        if not m or m.group(1) in seen:
            continue
        lid = m.group(1)
        seen.add(lid)
        ad = {"library_id": lid, "active": status == "Active"}
        m = re.search(r"\n([A-Z][a-z]{2} \d{1,2}, \d{4})(?: - ([A-Z][a-z]{2} \d{1,2}, \d{4}))?(?: · [^\n]*)?\n", chunk) \
            or re.search(r"Started running on ([A-Z][a-z]{2} \d{1,2}, \d{4})()", chunk)
        fmt = lambda x: datetime.strptime(x, "%b %d, %Y").date().isoformat() if x else None
        ad["start"], ad["end"] = (fmt(m.group(1)), fmt(m.group(2))) if m else (None, None)
        m = re.search(r"\[([^\]]+)\]\(https://www\.facebook\.com/([^/)?]+)/?\)\n\*\*Sponsored", chunk) \
            or re.search(r"\[([^\]]+)\]\(https://www\.facebook\.com/([^/)?]+)/?\)", chunk)
        if m:
            ad["advertiser"], ad["advertiser_handle"] = m.group(1), m.group(2)
        m = re.search(r"Paid for by \*\*([^*\n]+)\*\*", chunk)
        ad["paid_for_by"] = m.group(1).strip() if m else None
        m = re.search(r"Amount spent[^:]*:\s*\**([^\n*]+)", chunk)
        ad["spend_low"], ad["spend_high"] = money(m.group(1) if m else None)
        m = re.search(r"Impressions:\s*\**([^\n*]+)", chunk)
        ad["impressions"] = m.group(1).strip() if m else None
        m = re.search(r"Estimated audience size:\s*\**([^\n*]+)", chunk)
        ad["audience"] = m.group(1).strip() if m else None
        m = re.search(r"\*\*Sponsored\*\*[^\n]*\n(.+?)(?:\n\[!\[|\n(?:Active|Inactive)\n|$)", chunk, re.S)
        ad["body"] = re.sub(r"\s+", " ", m.group(1)).strip()[:3000] if m else None  # stays local (data/raw)
        ads.append(ad)
    return ads


def report_csv(day: str) -> None:
    """The report page's "Download report" file: spend and ad count per Page and disclaimer, ending on `day`
    (Meta keeps only the most recent 7 days). Plain HTTP GET with the project's user agent."""
    import urllib.request
    OUT.mkdir(parents=True, exist_ok=True)
    for i, preset in enumerate(["lifelong", "last_90_days", "last_30_days", "last_7_days"]):
        if i:
            time.sleep(PAUSE)
        url = f"https://www.facebook.com/ads/library/report/v2/download/?report_ds={day}&country=TW&time_preset={preset}"
        req = urllib.request.Request(url, headers={"User-Agent": UA, "Accept-Language": "en-US,en;q=0.9"})
        try:
            with urllib.request.urlopen(req, timeout=120) as r:
                body, ctype, status = r.read(), r.headers.get("Content-Type", ""), r.status
        except Exception as e:  # HTTP errors included
            print(json.dumps({"preset": preset, "error": str(e)[:200]}, ensure_ascii=False), flush=True)
            continue
        ext = ".zip" if body[:2] == b"PK" else ".csv" if b"," in body[:200] and b"<html" not in body[:500].lower() else ".html"
        path = OUT / f"report_TW_{day}_{preset}{ext}"
        path.write_bytes(body)
        print(json.dumps({"preset": preset, "status": status, "type": ctype, "bytes": len(body),
                          "saved": str(path.relative_to(ROOT))}, ensure_ascii=False), flush=True)
        if ext == ".html":
            print("stopped: got a web page instead of the report file")
            break


def main() -> None:
    args = sys.argv[1:] or ["search", "國民黨"]
    mode, rest = args[0], args[1:]
    if mode == "reportcsv":
        report_csv(rest[0] if rest else (datetime.now().date().fromordinal(datetime.now().date().toordinal() - 4)).isoformat())
        return
    since = ""
    if "--since" in rest:
        i = rest.index("--since")
        since, rest = rest[i + 1], rest[:i] + rest[i + 2:]
    if mode == "report":
        jobs = [("report", REPORT)]
    elif mode == "outlets":
        jobs = [(q, url_for(q, since)) for q in OUTLETS]
    elif mode == "pages" and rest:
        global SCROLLS
        SCROLLS = 20  # a Page's own list is shorter than a keyword search, so go deeper
        jobs = [(pid, page_url(pid, since)) for pid in rest]
    elif mode == "search" and rest:
        jobs = [(q, url_for(q, since)) for q in rest]
    else:
        sys.exit(__doc__)
    OUT.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    for i, (q, url) in enumerate(jobs):
        if i:
            time.sleep(PAUSE)
        status, md, html = asyncio.run(render(url))
        base = OUT / f"{stamp}_{mode}_{i:02d}"
        base.with_suffix(".md").write_text(md, encoding="utf-8")
        base.with_suffix(".html").write_text(html, encoding="utf-8")
        ads = parse(md) if mode != "report" else []
        meta = {"query": q, "since": since, "url": url, "fetched": datetime.now().isoformat(timespec="seconds")}
        base.with_suffix(".jsonl").write_text("".join(json.dumps({**meta, **a}, ensure_ascii=False) + "\n" for a in ads),
                                              encoding="utf-8")
        # the nav bar always has a "Log in" link, so look for the wall's own wording
        wall = bool(re.search(r"You must log in|log in to continue|checkpoint|security check|安全檢查", md, re.I)) and not ads
        total = re.search(r"~?([\d,]+) results", md)
        print(json.dumps({"query": q, "status": status, "md_chars": len(md), "results": total.group(1) if total else None,
                          "cards": len(ads), "with_spend": sum(a["spend_high"] is not None for a in ads),
                          "login_wall_or_checkpoint": wall, "saved": str(base.relative_to(ROOT))}, ensure_ascii=False), flush=True)
        if wall:
            print("stopped: login wall or checkpoint")
            break


if __name__ == "__main__":
    main()

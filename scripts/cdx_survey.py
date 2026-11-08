#!/usr/bin/env python3
"""Survey how much 2012-2015 Taiwanese news is recoverable from the Wayback CDX API.

Per outlet x year it counts distinct archived article-page URLs (status 200,
collapse=urlkey) for ONE sampled month per year (default: March) and extrapolates
x12.  Raw CDX responses are cached under data/history_survey/cdx/ so reruns are
cheap.  Then it spot-checks trafilatura extraction on one 2012 and one 2015
snapshot per outlet.  Results: data/history_survey/{counts.json,extraction.json}.

Politeness: honest User-Agent, request starts >= 2 s apart globally (a few worker
threads only overlap the slow server-side latency), backoff on 429/503/504.

    uv run python scripts/cdx_survey.py [--budget-min 30] [--month 03] [--workers 3]
"""
from __future__ import annotations

import argparse
import hashlib
import json
import re
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import httpx
import trafilatura

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "data" / "history_survey"
CACHE = OUT / "cdx"
UA = "twmedia-research/0.1 (+https://github.com/Chih-Kai-Wang)"
CDX = "https://web.archive.org/cdx/search/cdx"
FULL_LIMIT = LIMIT = 5000  # a raw result of LIMIT rows means the count is only a lower bound
YEARS = (2012, 2013, 2014, 2015)

# (outlet key, display name, prefix url for CDX (matchType=prefix), regex on original URL)
# Regexes are Java regex run by the CDX server; they select article pages only.
SPECS = [
    # {ym} -> YYYYMM, {mon} -> jan..dec of the sampled month; used to narrow the prefix when
    # the URL embeds the date (keeps the server-side scan small enough to avoid 504s).
    ("cna", "中央社", "cna.com.tw/news/aall/{ym}", r"cna\.com\.tw(:80)?/news/aall/[0-9]{12}"),
    ("cna", "中央社", "cna.com.tw/news/aipl/{ym}", r"cna\.com\.tw(:80)?/news/aipl/[0-9]{12}"),
    ("cna", "中央社", "cna.com.tw/news/aopl/{ym}", r"cna\.com\.tw(:80)?/news/aopl/[0-9]{12}"),
    ("ltn", "自由時報", "news.ltn.com.tw/news/politics/", r"news\.ltn\.com\.tw(:80)?/news/politics/(paper|breakingnews)/[0-9]+"),
    ("ltn", "自由時報", "www.libertytimes.com.tw/{year}/new/{mon}/", r"libertytimes\.com\.tw(:80)?/20[0-9]{2}/new/[a-z]{3}/[0-9]{1,2}/today-[a-z0-9-]+\.htm"),
    ("ltn", "自由時報", "iservice.ltn.com.tw/", r"iservice\.ltn\.com\.tw(:80)?/.*[0-9]{5,}"),
    ("udn", "聯合報", "udn.com/news/story/", r"udn\.com(:80)?/news/story/[0-9]+/[0-9]+"),
    ("udn", "聯合報", "udn.com/NEWS/", r"udn\.com(:80)?/NEWS/[A-Z]+/[A-Z0-9]+/[0-9]+\.shtml"),
    ("chinatimes", "中國時報", "www.chinatimes.com/newspapers/{ym}", r"chinatimes\.com(:80)?/newspapers/[0-9]{8,}"),
    ("chinatimes", "中國時報", "www.chinatimes.com/realtimenews/{ym}", r"chinatimes\.com(:80)?/realtimenews/[0-9]{8,}"),
    ("ettoday", "ETtoday", "www.ettoday.net/news/{ym}", r"ettoday\.net(:80)?/news/[0-9]{8}/[0-9]+\.htm"),
    ("tvbs", "TVBS", "news.tvbs.com.tw/politics/", r"news\.tvbs\.com\.tw(:80)?/politics/[0-9]{5,}"),
    ("tvbs", "TVBS", "news.tvbs.com.tw/entry/", r"news\.tvbs\.com\.tw(:80)?/entry/[0-9]{5,}"),
    ("setn", "三立", "www.setn.com/News.aspx?NewsID=", r"setn\.com(:80)?/News\.aspx\?NewsID=[0-9]+"),
    ("ftv", "民視", "www.ftvnews.com.tw/", r"ftvnews\.com\.tw(:80)?/.*[0-9A-Za-z]{5,}"),
    ("ebc", "東森", "news.ebc.net.tw/news.php?nid=", r"news\.ebc\.net\.tw(:80)?/news\.php\?nid=[0-9]+"),
    ("pts", "公視", "news.pts.org.tw/detail.php?NEWS_ID=", r"news\.pts\.org\.tw(:80)?/detail\.php\?NEWS_ID=[0-9]+"),
    ("storm", "風傳媒", "www.storm.mg/article/", r"storm\.mg(:80)?/article/[0-9]+"),
]
PATTERN_DOC = {(s[0], s[2]): s[3] for s in SPECS}


class Throttle:
    """Global rate limit: request starts at least `gap` seconds apart."""

    def __init__(self, gap: float = 2.0):
        self.gap, self.lock, self.next = gap, threading.Lock(), 0.0

    def wait(self):
        with self.lock:
            now = time.monotonic()
            start = max(now, self.next)
            self.next = start + self.gap
        if start > now:
            time.sleep(start - now)


THROTTLE = Throttle()
DEADLINE = [0.0]


def get(client: httpx.Client, url: str, params: dict | None = None, timeout: float = 120):
    """GET with backoff on 429/5xx/timeouts. Returns response or None (gave up / out of time)."""
    backoff = 8.0
    for _ in range(3):
        if time.monotonic() > DEADLINE[0]:
            return None
        THROTTLE.wait()
        try:
            r = client.get(url, params=params, timeout=timeout)
        except httpx.HTTPError:
            r = None
        if r is not None and r.status_code == 200 and "Temporarily Offline" not in r.text[:500]:
            return r
        if r is not None and r.status_code in (400, 403, 404):
            return r
        time.sleep(backoff)
        backoff *= 2
    return None


def cdx_query(client, key: str, prefix_t: str, regex: str, year: int, month: str):
    """Article URLs (client-side regex) for one outlet-pattern in one sampled month; cached."""
    mon = ["jan", "feb", "mar", "apr", "may", "jun", "jul", "aug", "sep", "oct", "nov", "dec"][int(month) - 1]
    prefix = prefix_t.format(ym=f"{year}{month}", mon=mon, year=year)
    params = [
        ("url", prefix), ("matchType", "prefix"), ("output", "json"),
        ("fl", "timestamp,original,statuscode,mimetype"), ("collapse", "urlkey"),
        ("from", f"{year}{month}01"), ("to", f"{year}{month}31"), ("limit", str(LIMIT)),
        ("filter", "statuscode:200"),
    ]
    stem = f"{key}_{hashlib.md5(prefix.encode()).hexdigest()[:8]}_{year}{month}"
    cf = CACHE / (stem + ".json" if LIMIT == FULL_LIMIT else f"{stem}_l{LIMIT}.json")
    for c in (CACHE / (stem + ".json"), cf):  # a full-limit result also satisfies a probe run
        if c.exists():
            return json.loads(c.read_text())
    r = get(client, CDX, params=params)
    if r is None or r.status_code != 200:
        return None  # not cached: a rerun retries it
    try:
        data = r.json()
    except ValueError:
        data = []
    raw = data[1:] if data else []
    rx = re.compile(regex, re.I)
    rows = [(a, b) for a, b, st, mt in raw if rx.search(b) and "html" in mt]
    res = {"outlet": key, "prefix": prefix, "year": year, "month": month,
           "raw": len(raw), "n": len(rows), "truncated": len(raw) >= LIMIT, "rows": rows[:300]}
    cf.parent.mkdir(parents=True, exist_ok=True)
    cf.write_text(json.dumps(res, ensure_ascii=False))
    return res


def run_counts(args):
    DEADLINE[0] = time.monotonic() + args.budget_min * 60
    # outlet-balanced order: 2012 and 2015 first (they matter most), then 2013, 2014
    order = [(s, y) for y in (2012, 2015, 2013, 2014) for s in SPECS]
    results, failed = {}, []

    def work(item):
        (key, _name, prefix_t, regex), year = item
        if key == "storm" and year < 2014:
            return item, "n/a"
        with httpx.Client(headers={"User-Agent": UA}, follow_redirects=True) as c:
            return item, cdx_query(c, key, prefix_t, regex, year, args.month)

    with ThreadPoolExecutor(args.workers) as ex:
        for item, res in ex.map(work, order):
            (key, name, prefix_t, _), year = item
            prefix = prefix_t
            tag = f"{key:10s} {prefix_t:42s} {year}"
            if res == "n/a":
                continue
            if res is None:
                failed.append(f"{key}|{prefix_t}|{year}")
                print(f"FAIL  {tag}", flush=True)
            else:
                results[f"{key}|{prefix_t}|{year}"] = {k: v for k, v in res.items() if k != "rows"} | {"sample": res["rows"][:20]}
                print(f"{'>=' if res['truncated'] else '  '}{res['n']:6d}/{res['raw']:<5d} {tag}", flush=True)
    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / "counts.json").write_text(json.dumps(
        {"month": args.month, "limit": LIMIT, "results": results, "failed": failed,
         "patterns": {f"{k}|{p}": v for (k, p), v in PATTERN_DOC.items()}},
        ensure_ascii=False, indent=1))
    return results


def spot_check(results, args):
    """Fetch one 2012 and one 2015 snapshot per outlet, run trafilatura."""
    DEADLINE[0] = time.monotonic() + 15 * 60
    out = {}
    with httpx.Client(headers={"User-Agent": UA}, follow_redirects=True) as c:
        for key in dict.fromkeys(s[0] for s in SPECS):
            for yr in ("2012", "2015") if key != "storm" else ("2014", "2015"):
                cands = [row for k, v in results.items() if k.startswith(key + "|") and k.endswith("|" + yr)
                         for row in v["sample"]]
                tag = f"{key}_{yr}"
                if not cands:
                    out[tag] = {"status": "no-snapshot-found"}
                    continue
                ts, orig = cands[min(3, len(cands) - 1)]
                r = get(c, f"https://web.archive.org/web/{ts}id_/{orig}", timeout=60)
                if r is None or r.status_code != 200:
                    out[tag] = {"status": "fetch-failed", "url": orig, "ts": ts}
                    continue
                text = trafilatura.extract(r.content, url=orig, favor_recall=True) or ""
                zh = len(re.findall(r"[一-鿿]", text))
                out[tag] = {"status": "pass" if len(text) > 200 and zh > 100 else "fail",
                            "url": orig, "ts": ts, "chars": len(text), "zh_chars": zh,
                            "head": text[:60].replace("\n", " ")}
                print(tag, out[tag]["status"], out[tag].get("chars"), orig, flush=True)
    (OUT / "extraction.json").write_text(json.dumps(out, ensure_ascii=False, indent=1))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--budget-min", type=float, default=30)
    ap.add_argument("--month", default="03", help="sampled month MM (extrapolated x12)")
    ap.add_argument("--workers", type=int, default=3)
    ap.add_argument("--limit", type=int, default=FULL_LIMIT,
                    help="rows per query; use a small value (e.g. 300) as a 'probe' pass for cells that 504 at 5000")
    ap.add_argument("--no-spot-check", action="store_true")
    args = ap.parse_args()
    global LIMIT
    LIMIT = args.limit
    res = run_counts(args)
    if not args.no_spot_check:
        spot_check(res, args)


if __name__ == "__main__":
    main()

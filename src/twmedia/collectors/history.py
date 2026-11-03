"""Historical news sample (PLAN.md §3): a fixed number of political articles per outlet per month, 2012-2026.

Each outlet's `history` block in config/sources.yaml picks one way to draw random candidate URLs for a month:

- date_seq: the URL holds the date and a daily sequence number (e.g. CNA .../aipl/201603010123.aspx).
    template: "https://.../{date:%Y%m%d}{seq:04d}.aspx", seq_max: 600
- id_range: a global numeric ID; `anchors` are known [YYYY-MM, first id of that month] points, linearly
    interpolated. Pages whose date falls outside the month are kept but not counted for it.
    template: "https://.../{id}", anchors: [["2012-01", 123], ["2016-01", 456], ...]
- sitemap_month: the outlet keeps per-month (or per-day) sitemaps.
    template: "https://.../sitemap-{month:%Y-%m}.xml"  (or {date:%Y-%m-%d} for daily ones; or {y}-{m}-{n} for
    numbered monthly parts, taken from the sitemap `index`)
- sitemap_numbered: one long series of numbered sitemaps in time order (中時 sitemap_article_1..1023.xml),
    listed by `index` URLs. A month's files are found by binary search on each file's URL dates
    (`url_date`, a regex whose first group is YYYYMMDD); file date ranges are cached in data/cache/.
    At most `max_list` URLs per month are kept (a random subset) to bound memory.
- wayback_cdx: the article list comes from the Wayback CDX index and pages from web.archive.org (id_ mode).
    prefix: "cna.com.tw/news/aipl/{month:%Y%m}", url_pattern: regex on archived URLs

An outlet may list several `streams` (e.g. Liberty Times' paper and breaking-news ID series), each with its
own method and optional `first`/`last` months; a month's draws are split across the streams active then.

Whether an article counts as political: `political_section` (exact match on article:section / JSON-LD
articleSection), `political_og_url`, `political_final_url` (the URL after redirects; e.g. Liberty Times
redirects non-political IDs away from /news/politics/), `political_breadcrumb` (regex on breadcrumb links),
`political_url`, `political_title` (e.g. CNA's 「| 政治 |」), `political_html` (regex on the raw page) or
`political_text` (party keywords) decides; rules set on a stream override the outlet-level ones whether an article counts toward the month's quota; non-political pages are stored anyway, flagged,
because topic shares are themselves a measure (PLAN.md §2). Months are visited round-robin in small rounds,
so an interrupted run still covers every month evenly; progress lives in data/state.sqlite.
"""

from __future__ import annotations

import calendar
import hashlib
import json
import logging
import random
import re
import socket
import time
from bisect import bisect_right
from datetime import date

from lxml import html as lhtml

from ..http import Blocked, Disallowed, PoliteClient
from ..store import DATA_DIR, Store
from .news import extract, parse_sitemap

log = logging.getLogger(__name__)
CDX = "https://web.archive.org/cdx/search/cdx"
POLITICAL_TEXT = re.compile(r"國民黨|民進黨|民眾黨|立法院|立委|行政院|總統府|藍營|綠營|黨團")


def months(first: str, last: str) -> list[str]:
    y, m = map(int, first.split("-"))
    out = []
    while f"{y}-{m:02d}" <= last:
        out.append(f"{y}-{m:02d}")
        y, m = (y + 1, 1) if m == 12 else (y, m + 1)
    return out


def _month_start(month: str) -> date:
    y, m = map(int, month.split("-"))
    return date(y, m, 1)


def interpolate_ids(anchors: list[list], month: str) -> tuple[int, int]:
    """[first, next-month-first) ID range for a month from known (date, id) anchors ("YYYY-MM" means the 1st)."""
    by_day: dict[int, int] = {}  # one anchor per day (a calibrated anchor can share a day with a configured one)
    for d, i in anchors:  # YAML turns 2012-01-09 into a date object, hence str()
        x = (date.fromisoformat(str(d)) if len(str(d)) == 10 else _month_start(str(d))).toordinal()
        by_day[x] = max(by_day.get(x, 0), int(i))
    pts = sorted(by_day.items())
    best = 0
    for k, (x, i) in enumerate(pts):  # IDs only grow with time: smooth out late-published or back-dated pages
        best = max(best, i)
        pts[k] = (x, best)
    xs = [p[0] for p in pts]

    def at(o: int) -> int:
        k = min(max(bisect_right(xs, o) - 1, 0), len(pts) - 2)
        (x0, y0), (x1, y1) = pts[k], pts[k + 1]
        return round(y0 + (y1 - y0) * (o - x0) / (x1 - x0))

    start = _month_start(month)
    nxt = date(start.year + start.month // 12, start.month % 12 + 1, 1)
    return at(start.toordinal()), at(nxt.toordinal())


def page_meta(html: str) -> dict:
    """Section labels, og:url and breadcrumb links: where outlets say which desk an article belongs to."""
    try:
        doc = lhtml.fromstring(html)
    except (ValueError, lhtml.etree.ParserError):
        return {"sections": [], "og_url": "", "breadcrumb": []}
    sections = [m.get("content", "") for m in doc.xpath('//meta[@property="article:section" or @name="article:section"]')]
    for script in doc.xpath('//script[@type="application/ld+json"]/text()'):
        try:
            data = json.loads(script)
        except json.JSONDecodeError:
            continue
        for node in data if isinstance(data, list) else data.get("@graph", [data]) if isinstance(data, dict) else []:
            sec = node.get("articleSection") if isinstance(node, dict) else None
            sections += sec if isinstance(sec, list) else [sec] if sec else []
    og = doc.xpath('//meta[@property="og:url"]/@content')
    crumbs = doc.xpath('//*[contains(@class,"breadcrumb") or contains(@class,"Breadcrumb")]//a/@href')
    return {"sections": [str(x).strip() for x in sections if x], "og_url": og[0] if og else "", "breadcrumb": crumbs}


class Sampler:
    """Draws candidate URLs for one outlet and month, across the streams active in that month."""

    def __init__(self, cfg: dict, client: PoliteClient, rng: random.Random, observed: dict[int, list] | None = None,
                 wayback: str = "include"):
        self.streams = cfg.get("streams") or [cfg]
        # "only" / "skip": Wayback runs from a different machine (the Internet Archive refuses cloud IPs)
        self.wayback = wayback
        self.client, self.rng = client, rng
        self._lists: dict[tuple[int, str], list[str]] = {}
        # (date, id) pairs read off fetched pages; they correct the configured anchors as sampling goes on
        self.observed: dict[int, list] = observed or {}

    def observe(self, stream: int, item: int | None, published: str) -> bool:
        if item is None or len(published) < 10 or self.streams[stream]["method"] != "id_range":
            return False
        self.observed.setdefault(stream, []).append([published[:10], item])
        return True

    def active(self, month: str) -> list[int]:
        def wanted(st: dict) -> bool:
            wb = st["method"] == "wayback_cdx"
            return {"include": True, "only": wb, "skip": not wb}[self.wayback]
        return [i for i, st in enumerate(self.streams)
                if str(st.get("first", "0000")) <= month <= str(st.get("last", "9999")) and wanted(st)]

    def candidates(self, month: str, k: int) -> list[tuple[str, int, int | None]]:
        """(url, stream index, numeric id or None) triples."""
        active = self.active(month)
        out = []
        for j, i in enumerate(active):
            share = k // len(active) + (1 if j < k % len(active) else 0)
            out += self._draw(i, month, share)
        return out

    def _draw(self, i: int, month: str, k: int) -> list[tuple[str, int, int | None]]:
        self.cfg = cfg = self.streams[i]
        kind = cfg["method"]
        y, m = map(int, month.split("-"))
        if kind == "date_seq":
            days = calendar.monthrange(y, m)[1]
            out = []
            for _ in range(k):
                d = date(y, m, self.rng.randint(1, days))
                seq = self.rng.randint(cfg.get("seq_min", 1), cfg["seq_max"])
                # {mc}: one-character month (1-9, A-C), as in 民視's sno codes
                out.append((cfg["template"].format(date=d, seq=seq, y=y, mc="123456789ABC"[m - 1], dd=d.day), i, None))
            return out
        if kind == "id_range":
            lo, hi = interpolate_ids(list(cfg["anchors"]) + self.observed.get(i, []), month)
            ids = [self.rng.randrange(max(lo, 1), max(hi, lo + 1, 2)) for _ in range(k)]
            return [(cfg["template"].format(id=n), i, n) for n in ids]
        key = (i, month)
        if key not in self._lists:
            self._lists[key] = self._list_month(month)
            self.rng.shuffle(self._lists[key])
        pool = self._lists[key]
        taken, self._lists[key] = pool[:k], pool[k:]
        return [(u, i, None) for u in taken]

    def _numbered_month(self, start: date) -> list[str]:
        if not hasattr(self, "_numbered"):
            self._numbered = _NumberedSitemaps(self.cfg, self.client)
        return self._numbered.month(start, self.rng, self.cfg.get("max_list", 3000))

    def _list_month(self, month: str) -> list[str]:
        start = _month_start(month)
        pattern = re.compile(self.cfg.get("url_pattern", ".*"), re.I)
        if self.cfg["method"] == "sitemap_month":
            urls = []
            tpl = self.cfg["template"]
            if "{date" in tpl:
                days = [date(start.year, start.month, d) for d in range(1, calendar.monthrange(start.year, start.month)[1] + 1)]
                sitemaps = [tpl.format(date=d) for d in days]
            elif "{n}" in tpl:  # numbered parts of a month (風傳媒 article-YYYY-M-N.xml), as listed in the index
                if not hasattr(self, "_index"):
                    self._index = parse_sitemap(self.client.get(self.cfg["index"]).content)[1]
                part = re.compile(re.escape(tpl.format(month=start, y=start.year, m=start.month, n="@")).replace("@", r"\d+") + "$")
                sitemaps = [u for u in self._index if part.search(u)]
            else:
                sitemaps = [tpl.format(month=start, y=start.year, m=start.month)]
            for sm in sitemaps:
                r = self.client.get(sm)
                if r.status_code != 200:
                    continue
                items, _ = parse_sitemap(r.content)
                urls += [c.url for c in items if pattern.search(c.url)]
            return urls
        if self.cfg["method"] == "sitemap_numbered":
            return self._numbered_month(start)
        # wayback_cdx
        prefix = self.cfg["prefix"].format(month=start)
        last = calendar.monthrange(start.year, start.month)[1]
        q = (f"{CDX}?url={prefix}&matchType=prefix&from={start:%Y%m}01&to={start:%Y%m}{last:02d}"
             "&output=json&fl=timestamp,original&filter=statuscode:200&collapse=urlkey&limit=20000")
        r = self.client.get(q)
        if r.status_code != 200:  # 503/504 are common: raise so the month is retried, not marked empty
            raise RuntimeError(f"CDX {r.status_code}")
        rows = json.loads(r.text or "[]")[1:]
        return [f"https://web.archive.org/web/{ts}id_/{url}" for ts, url in rows if pattern.search(url)]


class _NumberedSitemaps:
    """Date ranges of a time-ordered series of numbered sitemaps, cached on disk between runs."""

    def __init__(self, cfg: dict, client: PoliteClient):
        self.cfg, self.client = cfg, client
        self.url_date = re.compile(cfg["url_date"])
        self.pattern = re.compile(cfg.get("url_pattern", ".*"))
        self.cache = DATA_DIR / "cache" / f"sitemap_ranges_{hashlib.sha1(cfg['index'][0].encode()).hexdigest()[:8]}.json"
        self.ranges: dict[str, list[str]] = json.loads(self.cache.read_text()) if self.cache.exists() else {}
        children = []
        for idx in cfg["index"]:
            children += parse_sitemap(self.client.get(idx).content)[1]
        num = re.compile(r"(\d+)\.xml")
        self.children = sorted(set(children), key=lambda u: int(num.search(u).group(1)))

    def _fetch(self, i: int) -> list[tuple[str, str]]:
        r = self.client.get(self.children[i])
        if r.status_code != 200:
            return []
        items, _ = parse_sitemap(r.content)
        dated = [(m.group(1), c.url) for c in items if (m := self.url_date.search(c.url))]
        if dated:
            days = sorted(d for d, _ in dated)
            self.ranges[self.children[i]] = [days[0], days[-1]]
            self.cache.parent.mkdir(parents=True, exist_ok=True)
            self.cache.write_text(json.dumps(self.ranges))
        return dated

    def _range(self, i: int) -> list[str] | None:
        if self.children[i] not in self.ranges:
            self._fetch(i)
        return self.ranges.get(self.children[i])

    def month(self, start: date, rng: random.Random, max_list: int) -> list[str]:
        first = f"{start:%Y%m}01"
        last = f"{start:%Y%m}{calendar.monthrange(start.year, start.month)[1]:02d}"
        lo, hi = 0, len(self.children) - 1  # first file whose newest date reaches the month
        while lo < hi:
            mid = (lo + hi) // 2
            rg = self._range(mid)
            if rg and rg[1] < first:
                lo = mid + 1
            else:
                hi = mid
        urls = []
        for i in range(lo, len(self.children)):
            rg = self.ranges.get(self.children[i])
            if rg and rg[0] > last:
                break
            dated = self._fetch(i)
            if not dated:
                continue
            urls += [u for d, u in dated if first <= d <= last and self.pattern.search(u)]
            if min(d for d, _ in dated) > last:
                break
        rng.shuffle(urls)
        return urls[:max_list]


def online() -> bool:
    """Is there a working connection at all? (The laptop running this is often offline while commuting.)"""
    for host in ("1.1.1.1", "8.8.8.8"):
        try:
            socket.create_connection((host, 443), timeout=5).close()
            return True
        except OSError:
            continue
    return False


def wait_for_network(source: str) -> None:
    if online():
        return
    log.warning("%s: offline, waiting for the network", source)
    while not online():
        time.sleep(30)
    log.warning("%s: back online", source)


def is_political(cfg: dict, url: str, art: dict, meta: dict | None = None, final_url: str = "", html: str = "") -> bool:
    meta = meta or {}
    if cfg.get("political_html") and re.search(str(cfg["political_html"]), html):
        return True
    if cfg.get("political_section") and set(cfg["political_section"]) & set(meta.get("sections", [])):
        return True
    if cfg.get("political_og_url") and re.search(str(cfg["political_og_url"]), meta.get("og_url", "")):
        return True
    if cfg.get("political_final_url") and re.search(str(cfg["political_final_url"]), final_url):
        return True
    if cfg.get("political_breadcrumb") and any(re.search(str(cfg["political_breadcrumb"]), h) for h in meta.get("breadcrumb", [])):
        return True
    if cfg.get("political_url") and re.search(str(cfg["political_url"]), url, re.I):
        return True
    if cfg.get("political_title") and re.search(str(cfg["political_title"]), art.get("title") or ""):
        return True
    cats = " ".join(art.get("categories") or []) if isinstance(art.get("categories"), list) else (art.get("categories") or "")
    if any(c in cats for c in cfg.get("political_categories", [])):
        return True
    if cfg.get("political_text", False):  # fall back to keywords when an outlet has no usable category:
        # one in the title, or at least two in the opening of the text (a single passing mention is not enough)
        title, body = art.get("title") or "", (art.get("text") or "")[:1500]
        return bool(POLITICAL_TEXT.search(title)) or len(POLITICAL_TEXT.findall(body)) >= 2
    return False


def _progress(store: Store, source: str) -> dict[str, list[int]]:
    with store._lock:  # one SQLite connection is shared by every collector thread
        store._db.execute("CREATE TABLE IF NOT EXISTS history_progress (source TEXT, month TEXT, political INT,"
                          " attempts INT, PRIMARY KEY (source, month))")
        rows = store._db.execute("SELECT month, political, attempts FROM history_progress WHERE source=?",
                                 (source,)).fetchall()
    return {m: [p, a] for m, p, a in rows}


def _observed(store: Store, source: str) -> dict[int, list]:
    with store._lock:
        store._db.execute("CREATE TABLE IF NOT EXISTS history_anchor (source TEXT, stream INT, day TEXT, id INT)")
        rows = store._db.execute("SELECT stream, day, id FROM history_anchor WHERE source=?", (source,)).fetchall()
    out: dict[int, list] = {}
    for stream, day, item in rows:
        out.setdefault(stream, []).append([day, item])
    return out


def _save_anchor(store: Store, source: str, stream: int, day: str, item: int) -> None:
    with store._lock:
        store._db.execute("INSERT INTO history_anchor VALUES (?,?,?,?)", (source, stream, day[:10], item))
        store._db.commit()


def _save_progress(store: Store, source: str, month: str, pa: list[int]) -> None:
    with store._lock:
        store._db.execute("INSERT OR REPLACE INTO history_progress VALUES (?,?,?,?)", (source, month, *pa))
        store._db.commit()


def collect(outlet: str, cfg: dict, client: PoliteClient, store: Store, first: str, last: str,
            per_month: int = 300, round_size: int = 10, max_attempt_ratio: int = 8, seed: int = 20261102,
            wayback: str = "include") -> dict:
    """Round-robin over months until each has `per_month` political articles or ran out of attempts.

    wayback="only" keeps its own source name (hist_<outlet>_wb), so a machine doing only the Wayback part
    never shares progress rows with one doing the rest."""
    source = f"hist_{outlet}" + ("_wb" if wayback == "only" else "")
    h = cfg["history"]
    rng = random.Random(f"{seed}-{outlet}-{wayback}")
    sampler = Sampler(h, client, rng, _observed(store, source), wayback)
    if not any(sampler.active(m) for m in months(first, last)):
        return {"political": 0, "other": 0, "missing": 0, "failed": 0, "stopped": "no stream for this run"}
    progress = _progress(store, source)
    stats = {"political": 0, "other": 0, "missing": 0, "failed": 0, "stopped": None}
    todo = [m for m in months(first, last)]
    in_range = set(todo)
    listing_failures: dict[str, int] = {}
    while todo:
        next_round = []
        for month in todo:
            if not sampler.active(month):
                continue  # handled by another run (see `wayback`), or outside every stream's period
            pa = progress.setdefault(month, [0, 0])
            if pa[0] >= per_month or pa[1] >= per_month * max_attempt_ratio:
                continue
            try:
                urls = sampler.candidates(month, round_size)
            except (Blocked, Disallowed) as e:
                stats["stopped"] = f"{type(e).__name__}: {e}"
                return stats
            except Exception as e:  # a month's list failed to load (Wayback is often 503/504): retry in a later round
                if not online():  # our own connection dropped: wait, and don't hold it against the month
                    wait_for_network(source)
                    next_round.append(month)
                    continue
                log.warning("%s %s listing failed: %s", source, month, e)
                stats["failed"] += 1
                listing_failures[month] = listing_failures.get(month, 0) + 1
                if listing_failures[month] < 20:
                    next_round.append(month)
                continue
            if not urls:
                pa[1] = per_month * max_attempt_ratio  # nothing more to draw for this month
                _save_progress(store, source, month, pa)
                continue
            for url, stream, num in urls:
                item_id = hashlib.sha1(url.encode()).hexdigest()
                if store.is_seen(source, item_id):
                    continue
                pa[1] += 1
                rules = {k: v for k, v in h.items() if k != "streams"} | sampler.streams[stream]  # a stream may override
                try:
                    # `redirect_means_other`: the outlet redirects non-political IDs away from the politics path,
                    # so a redirect is the answer and its target need not be fetched (half the requests)
                    # one retry only: a sampled article that fails is cheaper to replace than to wait for
                    r = client.get(url, follow_redirects=not rules.get("redirect_means_other"), retries=1)
                except (Blocked, Disallowed) as e:
                    stats["stopped"] = f"{type(e).__name__}: {e}"
                    _save_progress(store, source, month, pa)
                    return stats
                except Exception as e:
                    if not online():  # our connection dropped, not the site: undo the attempt and wait
                        pa[1] -= 1
                        wait_for_network(source)
                        continue
                    log.warning("%s fetch failed %s: %s", source, url, e)
                    stats["failed"] += 1
                    continue
                if r.is_redirect and rules.get("redirect_means_other"):
                    store.save(source, item_id, {"url": url, "month": month, "redirect": r.headers.get("location"),
                                                 "political_guess": False})
                    stats["other"] += 1
                    continue
                if r.status_code in (404, 410):
                    store.save(source, item_id, {"url": url, "month": month, "missing": True})
                    stats["missing"] += 1
                    continue
                if r.status_code != 200:
                    stats["failed"] += 1
                    continue
                art = extract(r.text, url, h.get("body_selector") or cfg.get("body_selector"))
                meta = page_meta(r.text)
                if not (art.get("text") or "").strip():
                    store.save(source, item_id, {"url": url, "month": month, "missing": True, "status": r.status_code})
                    stats["missing"] += 1
                    continue
                published = art.get("date") or ""
                if sampler.observe(stream, num, published):
                    _save_anchor(store, source, stream, published, num)
                # credit the month the article was actually published in (ID-based draws can land a month off)
                actual = published[:7] if published[:7] in in_range else (month if not published else "")
                in_month = actual == month
                political = is_political(rules, url, art, meta, str(r.url), r.text)
                store.save(source, item_id, {"url": url, "final_url": str(r.url), "month": month, "published": published,
                                             "sections": meta["sections"], "og_url": meta["og_url"],
                                             "political_guess": political, "in_month": in_month, **art})
                if political and actual:
                    target = progress.setdefault(actual, [0, 0])
                    target[0] += 1
                    if actual != month:
                        _save_progress(store, source, actual, target)
                    stats["political"] += 1
                else:
                    stats["other"] += 1
            _save_progress(store, source, month, pa)
            next_round.append(month)
        todo = next_round
    return stats

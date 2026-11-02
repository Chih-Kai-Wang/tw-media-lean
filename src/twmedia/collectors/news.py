"""News websites: discover article URLs from Google News sitemaps (or a homepage), then fetch and extract text."""

from __future__ import annotations

import hashlib
import json
import logging
import re
from dataclasses import dataclass, field
from urllib.parse import urljoin

import trafilatura
from lxml import etree
from lxml import html as lhtml

from ..http import Blocked, Disallowed, PoliteClient
from ..store import Store

log = logging.getLogger(__name__)

NS = {
    "sm": "http://www.sitemaps.org/schemas/sitemap/0.9",
    "news": "http://www.google.com/schemas/sitemap-news/0.9",
}
MAX_CHILD_SITEMAPS = 2


@dataclass
class Candidate:
    url: str
    title: str | None = None
    published: str | None = None
    keywords: list[str] = field(default_factory=list)


def parse_sitemap(xml: bytes) -> tuple[list[Candidate], list[str]]:
    """Return (article candidates, child sitemap URLs) from a sitemap or sitemap index."""
    root = etree.fromstring(xml, parser=etree.XMLParser(recover=True, huge_tree=True))
    if root is None:
        return [], []

    children = []
    for sm in root.findall("sm:sitemap", NS):
        loc = sm.findtext("sm:loc", namespaces=NS)
        if loc:
            children.append((sm.findtext("sm:lastmod", default="", namespaces=NS), loc.strip()))
    # Newest first when lastmod is given; otherwise keep document order.
    if any(lastmod for lastmod, _ in children):
        children.sort(key=lambda c: c[0], reverse=True)

    items = []
    for u in root.findall("sm:url", NS):
        loc = u.findtext("sm:loc", namespaces=NS)
        if not loc:
            continue
        news = u.find("news:news", NS)
        kw = news.findtext("news:keywords", default="", namespaces=NS) if news is not None else ""
        items.append(
            Candidate(
                url=loc.strip(),
                title=news.findtext("news:title", namespaces=NS) if news is not None else None,
                published=news.findtext("news:publication_date", namespaces=NS)
                if news is not None
                else u.findtext("sm:lastmod", namespaces=NS),
                keywords=[k.strip() for k in kw.split(",") if k.strip()],
            )
        )
    return items, [loc for _, loc in children]


def discover(client: PoliteClient, cfg: dict, all_children: bool = False) -> list[Candidate]:
    if "sitemap" in cfg:
        items, children = parse_sitemap(client.get(cfg["sitemap"]).content)
        for child in children if all_children else children[:MAX_CHILD_SITEMAPS]:
            more, _ = parse_sitemap(client.get(child).content)
            items.extend(more)
        if cfg.get("url_pattern"):
            items = [c for c in items if re.search(cfg["url_pattern"], c.url)]
        return items

    html = client.get(cfg["homepage"]).text
    seen, items = set(), []
    for path in re.findall(cfg["link_pattern"], html):
        url = urljoin(cfg["homepage"], path)
        if url not in seen:
            seen.add(url)
            items.append(Candidate(url=url))
    return items


EXTRACTOR_VERSION = 2  # 2: optional per-source body_selector (drops related-article teasers)


def extract(html: str, url: str, body_selector: str | None = None) -> dict:
    raw = trafilatura.extract(
        html, url=url, output_format="json", with_metadata=True, include_comments=False
    )
    if not raw:
        return {}
    meta = json.loads(raw)
    keep = ("title", "author", "date", "text", "description", "sitename", "categories", "tags")
    out = {k: meta.get(k) for k in keep}
    if body_selector:
        nodes = lhtml.fromstring(html).cssselect(body_selector)
        if nodes:
            body = trafilatura.extract(lhtml.tostring(nodes[0], encoding="unicode"), include_comments=False)
            out["text"] = body or nodes[0].text_content().strip()
    out["extractor_version"] = EXTRACTOR_VERSION
    return out


def id_candidates(cfg: dict, newest: list[Candidate]) -> list[Candidate]:
    """For sites with sequential article IDs (cfg["id_url"] has one {} slot): every ID up to the newest seen."""
    pattern = re.escape(cfg["id_url"]).replace(r"\{\}", r"(\d+)")
    ids = [int(m.group(1)) for c in newest if (m := re.fullmatch(pattern, c.url))]
    return [Candidate(url=cfg["id_url"].format(i)) for i in range(max(ids, default=0), 0, -1)]


def collect(
    source: str, cfg: dict, client: PoliteClient, store: Store, max_items: int, backfill: bool = False
) -> dict:
    """One pass. With backfill=True, walk every child sitemap (or every sequential ID) instead of the newest."""
    stats = {"discovered": 0, "new": 0, "failed": 0, "stopped": None}
    try:
        candidates = discover(client, cfg, all_children=backfill)
    except (Blocked, Disallowed) as e:
        stats["stopped"] = f"{type(e).__name__}: {e}"
        return stats
    if backfill and cfg.get("id_url"):
        candidates = id_candidates(cfg, candidates)
    stats["discovered"] = len(candidates)

    for cand in candidates:
        if stats["new"] >= max_items:
            break
        item_id = hashlib.sha1(cand.url.encode()).hexdigest()
        if store.is_seen(source, item_id):
            continue
        try:
            r = client.get(cand.url)
        except (Blocked, Disallowed) as e:
            stats["stopped"] = f"{type(e).__name__}: {e}"
            break
        except Exception as e:  # network errors: retry on a later run
            log.warning("%s fetch failed %s: %s", source, cand.url, e)
            stats["failed"] += 1
            continue
        if r.status_code == 404 and backfill:
            store.save(source, item_id, {"url": cand.url, "missing": True})  # gap in an ID range; don't retry
            continue
        if r.status_code != 200:
            stats["failed"] += 1
            continue
        art = extract(r.text, cand.url, cfg.get("body_selector"))
        text = art.get("text") or ""
        store.save(
            source,
            item_id,
            {
                "url": cand.url,
                "final_url": str(r.url),
                "sitemap_title": cand.title,
                "published": cand.published or art.get("date"),
                "keywords": cand.keywords,
                "text_sha1": hashlib.sha1(text.encode()).hexdigest() if text else None,
                **art,
            },
        )
        stats["new"] += 1
    return stats

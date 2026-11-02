"""LINE TODAY: hourly snapshots of what each tab shows on its first screen.

LINE TODAY republishes other outlets' stories, so we do not fetch article text here (the
original outlets are collected directly). What matters is distribution: which outlets'
stories LINE TODAY puts in front of readers, and in what order. The server-rendered page
only carries the first screen (about 5-10 items per tab); the rest loads client-side.
"""

from __future__ import annotations

import json
import re
from datetime import datetime, timezone

from ..http import Blocked, Disallowed, PoliteClient
from ..store import Store

TAB = "https://today.line.me/tw/v2/tab/{}"
ARTICLE = "https://today.line.me/tw/v2/article/{}"


def parse_tab(page: str) -> list[dict]:
    m = re.search(r'<script id="__NEXT_DATA__"[^>]*>(.*?)</script>', page, re.S)
    if not m:
        return []
    fallback = json.loads(m.group(1))["props"]["pageProps"].get("fallback", {})
    items = []
    for key, value in fallback.items():
        entries = value if isinstance(value, list) else value.get("items", []) if isinstance(value, dict) else []
        for e in entries:
            if not isinstance(e, dict) or "title" not in e or "publisher" not in e:
                continue
            url_hash = (e.get("url") or {}).get("hash")
            items.append(
                {
                    "module": key.split("_", 1)[0],
                    "rank": len(items) + 1,
                    "article_id": e.get("id"),
                    "url": ARTICLE.format(url_hash) if url_hash else None,
                    "title": e.get("title"),
                    "publisher": e.get("publisher"),
                    "publisher_id": e.get("publisherId"),
                    "category": e.get("categoryName"),
                    "published": datetime.fromtimestamp(e["publishTimeUnix"] / 1000, timezone.utc).isoformat()
                    if e.get("publishTimeUnix")
                    else None,
                    "summary": e.get("shortDescription"),
                }
            )
    return items


def collect(source: str, tabs: list[str], client: PoliteClient, store: Store) -> dict:
    stats = {"discovered": 0, "new": 0, "failed": 0, "stopped": None}
    hour = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H")
    for tab in tabs:
        try:
            r = client.get(TAB.format(tab))
        except (Blocked, Disallowed) as e:
            stats["stopped"] = f"{type(e).__name__}: {e}"
            break
        if r.status_code != 200:
            stats["failed"] += 1
            continue
        items = parse_tab(r.text)
        stats["discovered"] += len(items)
        if items and store.save(source, f"{tab}@{hour}", {"tab": tab, "snapshot_hour": hour, "items": items}):
            stats["new"] += 1
    return stats

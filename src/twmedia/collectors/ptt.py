"""PTT boards via the public web interface.

robots.txt sets Content-Signal ai-train=no, so every record carries `usage: no-ai-train`
and PTT text must never be used to train or fine-tune models (PLAN.md §4.3).
User IDs are pseudonymized before storage.
"""

from __future__ import annotations

import re
from collections import Counter
from urllib.parse import urljoin

from lxml import html as lhtml

from ..http import Blocked, Disallowed, PoliteClient
from ..store import Store, pseudonymize

BASE = "https://www.ptt.cc"
OVER18 = {"over18": "1"}  # the site's own age-confirmation cookie, not an access bypass


def parse_index(page: str) -> tuple[list[dict], str | None]:
    doc = lhtml.fromstring(page)
    posts = []
    for ent in doc.cssselect("div.r-ent"):
        a = ent.cssselect("div.title a")
        if not a:  # deleted post
            continue
        posts.append({"url": urljoin(BASE, a[0].get("href")), "title": a[0].text_content().strip()})
    prev = None
    for btn in doc.cssselect("div.btn-group-paging a"):
        if "上頁" in btn.text_content() and btn.get("href"):
            prev = urljoin(BASE, btn.get("href"))
    return posts, prev


def parse_post(page: str) -> dict:
    doc = lhtml.fromstring(page)
    main = doc.get_element_by_id("main-content", None)
    if main is None:
        return {}
    meta = {
        m.cssselect(".article-meta-tag")[0].text_content().strip(): m.cssselect(".article-meta-value")[0].text_content().strip()
        for m in main.cssselect("div.article-metaline")
        if m.cssselect(".article-meta-tag") and m.cssselect(".article-meta-value")
    }
    pushes = []
    for p in main.cssselect("div.push"):
        tag = p.cssselect(".push-tag")
        user = p.cssselect(".push-userid")
        content = p.cssselect(".push-content")
        if tag and user and content:
            pushes.append(
                {
                    "tag": tag[0].text_content().strip(),
                    "user": pseudonymize(user[0].text_content().strip()),
                    "text": content[0].text_content().lstrip(": ").strip(),
                }
            )
    for el in main.cssselect("div.article-metaline, div.article-metaline-right, div.push"):
        el.drop_tree()
    body = main.text_content()
    body = re.split(r"\n※ 發信站", body)[0].strip()
    author = meta.get("作者", "")
    return {
        "author": pseudonymize(author.split(" ")[0]) if author else None,
        "title": meta.get("標題"),
        "posted": meta.get("時間"),
        "text": body,
        "push_counts": dict(Counter(p["tag"] for p in pushes)),
        "pushes": pushes,
    }


def collect(source: str, board: str, pages: int, client: PoliteClient, store: Store) -> dict:
    stats = {"discovered": 0, "new": 0, "failed": 0, "stopped": None}
    url = f"{BASE}/bbs/{board}/index.html"
    try:
        for _ in range(pages):
            posts, prev = parse_index(client.get(url, cookies=OVER18).text)
            stats["discovered"] += len(posts)
            for post in posts:
                item_id = post["url"].rsplit("/", 1)[-1].removesuffix(".html")
                if store.is_seen(source, item_id):
                    continue
                r = client.get(post["url"], cookies=OVER18)
                if r.status_code != 200:
                    stats["failed"] += 1
                    continue
                rec = parse_post(r.text)
                store.save(source, item_id, {"board": board, "url": post["url"], "usage": "no-ai-train", **rec})
                stats["new"] += 1
            if not prev:
                break
            url = prev
    except (Blocked, Disallowed) as e:
        stats["stopped"] = f"{type(e).__name__}: {e}"
    return stats

"""Threads via the official Threads API (graph.threads.com, v1.0).

Needs THREADS_ACCESS_TOKEN in the environment or `.env` (a Threads tester's long-lived user token).
- keyword_search: public posts matching political keywords. Until Meta approves the app's
  `threads_keyword_search` permission, results only include the token owner's own posts.
- profile_posts: posts of listed public accounts (media outlets). Until `threads_profile_discovery`
  has advanced access, only a few official Meta accounts can be looked up.
Ordinary users' usernames are pseudonymized; accounts listed in config (outlets, politicians) are kept.
Keyword search quota: 2,200 queries per user per rolling 24 hours.
"""

from __future__ import annotations

import os
from pathlib import Path
from urllib.parse import urlencode

from ..http import Blocked, Disallowed, PoliteClient
from ..store import Store, pseudonymize

API = "https://graph.threads.com/v1.0"
FIELDS = "id,text,media_type,timestamp,username,has_replies,is_quote_post,is_reply"


def access_token() -> str | None:
    if os.environ.get("THREADS_ACCESS_TOKEN"):
        return os.environ["THREADS_ACCESS_TOKEN"]
    env = Path(__file__).resolve().parents[3] / ".env"
    if env.exists():
        for line in env.read_text(encoding="utf-8").splitlines():
            if line.startswith("THREADS_ACCESS_TOKEN="):
                return line.split("=", 1)[1].strip() or None
    return None


def _get(client: PoliteClient, path: str, token: str, **params) -> dict:
    r = client.get(f"{API}/{path}?{urlencode({**params, 'access_token': token})}", official_api=True)
    if r.status_code != 200:
        raise RuntimeError(f"Threads API {path} {r.status_code}: {r.text[:200].replace(token, '***')}")
    return r.json()


def to_record(post: dict, public_accounts: set[str], query: dict) -> dict:
    user = post.get("username")
    return {
        "text": post.get("text"),
        "published": post.get("timestamp"),
        "media_type": post.get("media_type"),
        "is_reply": post.get("is_reply"),
        "is_quote_post": post.get("is_quote_post"),
        "has_replies": post.get("has_replies"),
        # keep names of listed public accounts; hash everyone else (個資保護)
        "username": user if user in public_accounts else None,
        "user_hash": pseudonymize(user),
        "query": query,
    }


def collect(source: str, cfg: dict, client: PoliteClient, store: Store) -> dict:
    stats = {"discovered": 0, "new": 0, "failed": 0, "stopped": None}
    token = access_token()
    if not token:
        stats["stopped"] = "no THREADS_ACCESS_TOKEN"
        return stats
    public = set(cfg.get("public_accounts", [])) | set(cfg.get("profiles", []))
    try:
        for kw in cfg.get("keywords", []):
            res = _get(client, "keyword_search", token, q=kw, search_type="RECENT", limit=100, fields=FIELDS)
            for p in res.get("data", []):
                stats["discovered"] += 1
                stats["new"] += int(store.save(source, p["id"], to_record(p, public, {"keyword": kw})))
        for username in cfg.get("profiles", []):
            res = _get(client, "profile_posts", token, username=username, limit=100, fields=FIELDS)
            for p in res.get("data", []):
                stats["discovered"] += 1
                stats["new"] += int(store.save(source, p["id"], to_record(p, public, {"profile": username})))
    except (Blocked, Disallowed) as e:
        stats["stopped"] = f"{type(e).__name__}: {e}"
    except RuntimeError as e:
        stats["stopped"] = str(e)
    return stats

"""YouTube via the official Data API v3 (channel RSS feeds are disallowed by robots.txt).

Needs an API key in the YOUTUBE_API_KEY environment variable (or a `.env` file at the repo root).
Quota cost per channel per run: 1 (uploads playlist, cached) + 1 (playlistItems) + 1 (videos) units;
the free daily quota is 10,000 units, so hourly runs over all channels use well under 10%.
Captions come later via yt-dlp (PLAN.md §4.5).
"""

from __future__ import annotations

import os
from pathlib import Path

from ..http import Blocked, Disallowed, PoliteClient
from ..store import Store

API = "https://www.googleapis.com/youtube/v3"
_uploads_cache: dict[str, str] = {}


def api_key() -> str | None:
    if os.environ.get("YOUTUBE_API_KEY"):
        return os.environ["YOUTUBE_API_KEY"]
    env = Path(__file__).resolve().parents[3] / ".env"
    if env.exists():
        for line in env.read_text(encoding="utf-8").splitlines():
            if line.startswith("YOUTUBE_API_KEY="):
                return line.split("=", 1)[1].strip() or None
    return None


def _get(client: PoliteClient, path: str, key: str, **params) -> dict:
    query = "&".join(f"{k}={v}" for k, v in params.items())
    r = client.get(f"{API}/{path}?{query}&key={key}", official_api=True)
    if r.status_code != 200:
        raise RuntimeError(f"YouTube API {path} {r.status_code}: {r.text[:200].replace(key, '***')}")
    return r.json()


def collect(source: str, channel_id: str, client: PoliteClient, store: Store) -> dict:
    stats = {"discovered": 0, "new": 0, "failed": 0, "stopped": None}
    key = api_key()
    if not key:
        stats["stopped"] = "no YOUTUBE_API_KEY"
        return stats
    try:
        if channel_id not in _uploads_cache:
            ch = _get(client, "channels", key, part="contentDetails,snippet", id=channel_id)
            _uploads_cache[channel_id] = ch["items"][0]["contentDetails"]["relatedPlaylists"]["uploads"]
        items = _get(
            client, "playlistItems", key, part="contentDetails", playlistId=_uploads_cache[channel_id], maxResults=50
        )["items"]
        ids = [i["contentDetails"]["videoId"] for i in items]
        stats["discovered"] = len(ids)
        new_ids = [v for v in ids if not store.is_seen(source, v)]
        if not new_ids:
            return stats
        videos = _get(client, "videos", key, part="snippet,statistics,contentDetails", id=",".join(new_ids))["items"]
    except (Blocked, Disallowed) as e:
        stats["stopped"] = f"{type(e).__name__}: {e}"
        return stats

    for v in videos:
        sn, st = v["snippet"], v.get("statistics", {})
        saved = store.save(
            source,
            v["id"],
            {
                "channel_id": channel_id,
                "channel_title": sn.get("channelTitle"),
                "url": f"https://www.youtube.com/watch?v={v['id']}",
                "title": sn.get("title"),
                "published": sn.get("publishedAt"),
                "description": sn.get("description"),
                "tags": sn.get("tags"),
                "duration": v.get("contentDetails", {}).get("duration"),
                "views_at_collection": int(st["viewCount"]) if "viewCount" in st else None,
                "comments_at_collection": int(st["commentCount"]) if "commentCount" in st else None,
            },
        )
        stats["new"] += int(saved)
    return stats

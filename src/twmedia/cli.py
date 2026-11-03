"""Command line entry point.

    uv run twmedia collect              # one full collection pass
    uv run twmedia collect --only news_cna yt_tvbs
    uv run twmedia status               # items stored per source
"""

from __future__ import annotations

import argparse
import fcntl
import json
import logging
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import yaml

from .collectors import history, line_today, news, ptt, threads, youtube
from .http import PoliteClient
from .store import Store, now_utc

CONFIG = Path(__file__).resolve().parents[2] / "config" / "sources.yaml"


def build_jobs(cfg: dict, client: PoliteClient, store: Store, max_items: int) -> dict:
    jobs = {}
    for key, o in cfg["outlets"].items():
        jobs[f"news_{key}"] = lambda k=f"news_{key}", o=o: news.collect(k, o, client, store, max_items)
        if o.get("youtube"):
            jobs[f"yt_{key}"] = lambda k=f"yt_{key}", c=o["youtube"]: youtube.collect(k, c, client, store)
    for key, a in cfg.get("aggregators", {}).items():
        jobs[f"agg_{key}"] = lambda k=f"agg_{key}", a=a: news.collect(k, a, client, store, max_items)
    for key, a in cfg.get("parties", {}).items():
        jobs[f"party_{key}"] = lambda k=f"party_{key}", a=a: news.collect(k, a, client, store, max_items)
    # Channels chosen by scripts/select_youtube_channels.py (political media, outlet sub-channels, politicians).
    yt_file = CONFIG.with_name("youtube_channels.yaml")
    if yt_file.exists():
        yt = yaml.safe_load(yt_file.read_text(encoding="utf-8")) or {}
        groups = [("media", c, c["id"]) for c in yt.get("channels", [])]
        groups += [(c["outlet"], c, c["id"]) for c in yt.get("outlet_subchannels", [])]
        groups += [("party", c, c["id"]) for c in yt.get("party_channels", [])]
        for group, _, cid in groups:
            name = f"yt_{group}_{cid}"
            jobs[name] = lambda k=name, c=cid: youtube.collect(k, c, client, store)
    if cfg.get("threads", {}).get("enabled", True):
        jobs["threads"] = lambda t=cfg["threads"]: threads.collect("threads", t, client, store)
    if cfg.get("line_today"):
        tabs = cfg["line_today"]["tabs"]
        jobs["line_today"] = lambda: line_today.collect("line_today", tabs, client, store)
    pages = cfg["ptt"]["pages_per_run"]
    for board in cfg["ptt"]["boards"]:
        jobs[f"ptt_{board}"] = lambda k=f"ptt_{board}", b=board: ptt.collect(k, b, pages, client, store)
    return jobs


def cmd_collect(args) -> None:
    cfg = yaml.safe_load(CONFIG.read_text(encoding="utf-8"))
    store = Store()
    lock = (store.root / "collect.lock").open("w")
    try:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except BlockingIOError:
        print("another collection pass is still running; skipping")
        return
    client = PoliteClient(min_interval=args.interval)
    jobs = build_jobs(cfg, client, store, args.max_items)
    if args.only:
        jobs = {k: v for k, v in jobs.items() if k in args.only}

    started = now_utc()
    t0 = time.monotonic()
    results = {}

    def run(name):
        try:
            results[name] = jobs[name]()
        except Exception as e:  # one broken source must not stop the others
            logging.exception("%s crashed", name)
            results[name] = {"error": f"{type(e).__name__}: {e}"}
        logging.info("%s %s", name, results[name])

    with ThreadPoolExecutor(max_workers=args.workers) as pool:
        list(pool.map(run, jobs))
    client.close()

    summary = {"started": started, "seconds": round(time.monotonic() - t0), "results": results}
    with (store.root / "runs.jsonl").open("a", encoding="utf-8") as f:
        f.write(json.dumps(summary, ensure_ascii=False) + "\n")
    for name in sorted(results):
        print(f"{name:22} {results[name]}")


def cmd_backfill(args) -> None:
    """Walk a source's full history (all child sitemaps, or every sequential ID). Long-running."""
    cfg = yaml.safe_load(CONFIG.read_text(encoding="utf-8"))
    sources = {f"party_{k}": v for k, v in cfg.get("parties", {}).items()}
    sources |= {f"news_{k}": v for k, v in cfg["outlets"].items() if "sitemap" in v}
    unknown = set(args.sources) - set(sources)
    if unknown:
        raise SystemExit(f"unknown or unsupported sources: {sorted(unknown)}; choose from {sorted(sources)}")
    store = Store()
    client = PoliteClient(min_interval=args.interval)
    with ThreadPoolExecutor(max_workers=len(args.sources)) as pool:
        futures = {
            name: pool.submit(news.collect, name, sources[name], client, store, args.max_items, True)
            for name in args.sources
        }
        for name, f in futures.items():
            print(f"{name:22} {f.result()}")
    client.close()


def cmd_history(args) -> None:
    """Monthly random sample of historical political articles (collectors/history.py). Long-running."""
    cfg = yaml.safe_load(CONFIG.read_text(encoding="utf-8"))
    outlets = {k: v for k, v in cfg["outlets"].items() if "history" in v}
    unknown = set(args.outlets) - set(outlets)
    if unknown:
        raise SystemExit(f"no history config for: {sorted(unknown)}; configured: {sorted(outlets)}")
    store = Store()
    # Wayback CDX queries can take a minute and its index often answers 503: the Internet Archive gets a slower pace
    client = PoliteClient(min_interval=args.interval, timeout=90, host_intervals={"web.archive.org": 5.0})
    with ThreadPoolExecutor(max_workers=len(args.outlets)) as pool:
        futures = {o: pool.submit(history.collect, o, outlets[o], client, store, args.first, args.last, args.per_month,
                                  wayback=args.wayback)
                   for o in args.outlets}
        for o, f in futures.items():
            print(f"hist_{o:17} {f.result()}")
    client.close()


def cmd_status(args) -> None:
    for source, n, last in Store().counts():
        print(f"{source:22} {n:>8}  last={last}")


def main() -> None:
    p = argparse.ArgumentParser(prog="twmedia")
    sub = p.add_subparsers(dest="cmd", required=True)
    c = sub.add_parser("collect", help="run one collection pass")
    c.add_argument("--only", nargs="*", help="source names, e.g. news_cna yt_tvbs ptt_HatePolitics")
    c.add_argument("--max-items", type=int, default=150, help="max new articles per news source per run")
    c.add_argument("--interval", type=float, default=2.0, help="seconds between requests to one host")
    c.add_argument("--workers", type=int, default=8)
    c.set_defaults(func=cmd_collect)
    b = sub.add_parser("backfill", help="walk a source's full history (slow; run in the background)")
    b.add_argument("sources", nargs="+", help="e.g. party_kmt party_dpp")
    b.add_argument("--max-items", type=int, default=1_000_000)
    b.add_argument("--interval", type=float, default=2.0)
    b.set_defaults(func=cmd_backfill)
    h = sub.add_parser("history", help="monthly random sample of past political articles (slow; background)")
    h.add_argument("outlets", nargs="+", help="outlet keys with a history block in config/sources.yaml, e.g. cna")
    h.add_argument("--first", default="2012-01")
    h.add_argument("--last", default="2026-09")
    h.add_argument("--per-month", type=int, default=300)
    h.add_argument("--interval", type=float, default=1.0, help="seconds between requests to one outlet")
    h.add_argument("--wayback", choices=["include", "skip", "only"], default="include",
                   help="the cloud VM runs 'skip' (web.archive.org refuses cloud IPs); a home machine runs 'only'")
    h.set_defaults(func=cmd_history)
    s = sub.add_parser("status", help="items stored per source")
    s.set_defaults(func=cmd_status)
    args = p.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    logging.getLogger("httpx").setLevel(logging.WARNING)  # request URLs can carry the YouTube API key
    args.func(args)


if __name__ == "__main__":
    main()

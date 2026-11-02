"""Fit the outlet x party trend model (src/twmedia/trend.py) to every annotation file available.

Reads data/annotations/{vertex_*,pilot_*}.jsonl, pools jurors per article (each juror's stance is one value),
groups articles by outlet, party and period (--period month|week|day, by publication date), and writes
data/derived/trends.json for the website. Usage: uv run python scripts/fit_trends.py [--period week] [--since 2026-10-28]
"""

from __future__ import annotations

import argparse
import glob
import json
from collections import defaultdict
from datetime import date, datetime
from pathlib import Path

import numpy as np

from twmedia.annotate import PARTIES
from twmedia.trend import smooth, summarize

ROOT = Path(__file__).resolve().parents[1]


def period_of(published: str, kind: str) -> str | None:
    try:
        d = datetime.fromisoformat(published.replace("Z", "+00:00")).date()
    except (ValueError, AttributeError):
        return None
    if kind == "month":
        return f"{d.year}-{d.month:02d}"
    if kind == "week":
        y, w, _ = d.isocalendar()
        return f"{y}-W{w:02d}"
    return d.isoformat()


def all_periods(first: str, last: str, kind: str) -> list[str]:
    """Every period between first and last, so that empty ones are bridged by the random walk."""
    if kind == "month":
        y, m = map(int, first.split("-"))
        out = []
        while f"{y}-{m:02d}" <= last:
            out.append(f"{y}-{m:02d}")
            y, m = (y + 1, 1) if m == 12 else (y, m + 1)
        return out
    if kind == "week":
        start = date.fromisocalendar(int(first[:4]), int(first[6:]), 1)
        end = date.fromisocalendar(int(last[:4]), int(last[6:]), 1)
        return sorted({period_of(date.fromordinal(o).isoformat(), "week") for o in range(start.toordinal(), end.toordinal() + 1)})
    a, b = date.fromisoformat(first), date.fromisoformat(last)
    return [date.fromordinal(o).isoformat() for o in range(a.toordinal(), b.toordinal() + 1)]


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--period", choices=["month", "week", "day"], default="month")
    ap.add_argument("--since", default="", help="only articles published on or after this date (YYYY-MM-DD)")
    args = ap.parse_args()
    kind = args.period

    meta = {}
    for f in glob.glob(str(ROOT / "data" / "raw" / "news_*" / "*.jsonl")):
        for line in open(f, encoding="utf-8"):
            r = json.loads(line)
            meta[r["id"]] = (Path(f).parent.name, r.get("published") or "")

    votes: dict[str, dict[str, list[float]]] = defaultdict(lambda: defaultdict(list))  # article -> party -> stances
    files = glob.glob(str(ROOT / "data" / "annotations" / "vertex_*.jsonl")) + glob.glob(str(ROOT / "data" / "annotations" / "pilot_*.jsonl"))
    for f in files:
        for line in open(f, encoding="utf-8"):
            d = json.loads(line)
            if not d["key"].startswith("news:"):
                continue
            for party, v in ((d.get("label") or {}).get("parties") or {}).items():
                if party in PARTIES and v and v.get("stance") is not None:
                    votes[d["key"][5:]][party].append(float(v["stance"]))

    cells: dict[tuple[str, str], dict[str, list[list[float]]]] = defaultdict(lambda: defaultdict(list))
    for aid, by_party in votes.items():
        if aid not in meta:
            continue
        source, published = meta[aid]
        if published[:10] < args.since:
            continue  # e.g. an old article that a sitemap re-listed
        per = period_of(published, kind)
        if per:
            for party, stances in by_party.items():
                cells[(source, party)][per].append(stances)

    out = {"period": kind, "generated": date.today().isoformat(), "files": [Path(f).name for f in files], "series": []}
    for (source, party), by_per in sorted(cells.items()):
        pers = all_periods(min(by_per), max(by_per), kind)
        fit = smooth([summarize(by_per.get(p, [])) for p in pers])
        out["series"].append({
            "outlet": source, "party": party, "tau": fit["tau"],
            "points": [{"period": p, "n": len(by_per.get(p, [])), "mean": round(float(m), 3),
                        "lo": round(float(lo), 3), "hi": round(float(hi), 3)}
                       for p, m, lo, hi in zip(pers, fit["mean"], fit["lo"], fit["hi"])],
        })
    path = ROOT / "data" / "derived" / f"trends_{kind}.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(out, ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"{len(out['series'])} series, {len(votes)} annotated articles -> {path.relative_to(ROOT)}")
    for s in out["series"][:6]:
        print(s["outlet"], s["party"], [(p["period"], p["n"], p["mean"]) for p in s["points"]][:4])


if __name__ == "__main__":
    np.seterr(all="ignore")
    main()

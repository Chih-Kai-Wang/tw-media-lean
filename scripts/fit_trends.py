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
import yaml

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


def load_events(kind: str) -> tuple[float, dict[str, list[dict]]]:
    """config/events.yaml -> (variance multiplier, outlet -> [{period, kind, note}]); "*" holds all-outlet events."""
    cfg = yaml.safe_load((ROOT / "config" / "events.yaml").read_text(encoding="utf-8"))
    by_outlet: dict[str, list[dict]] = defaultdict(list)
    for e in cfg["events"]:
        day = str(e["date"]) if len(str(e["date"])) == 10 else f"{e['date']}-01"
        per = period_of(day, kind)
        for o in (["*"] if e["outlets"] == "all" else [f"news_{k}" for k in e["outlets"]]):
            by_outlet[o].append({"period": per, "date": str(e["date"]), "kind": e["kind"], "note": e["note"]})
    return float(cfg["jump"]), by_outlet


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--period", choices=["month", "week", "day"], default="month")
    ap.add_argument("--since", default="", help="only articles published on or after this date (YYYY-MM-DD)")
    ap.add_argument("--labels", choices=["llm", "model"], default="llm",
                    help="llm: Vertex/pilot jurors; model: the trained decision model (all sampled articles)")
    ap.add_argument("--model", default="tw-media-lean-v1", help="decision model name, with --labels model")
    ap.add_argument("--no-events", action="store_true",
                    help="ignore config/events.yaml (plain random walk; the fit Method F's event studies read)")
    ap.add_argument("--jump", type=float, default=None, help="override the variance multiplier (sensitivity checks)")
    args = ap.parse_args()
    kind = args.period

    meta = {}  # article id -> (outlet as news_<key>, publication date); the historical sample counts as the same outlet
    for f in glob.glob(str(ROOT / "data" / "raw" / "news_*" / "*.jsonl")) + glob.glob(str(ROOT / "data" / "raw" / "hist_*" / "*.jsonl")):
        outlet = "news_" + Path(f).parent.name.split("_", 1)[1].removesuffix("_wb")
        for line in open(f, encoding="utf-8"):
            r = json.loads(line)
            if r.get("id"):
                meta[r["id"]] = (outlet, r.get("published") or "")

    votes: dict[str, dict[str, list[float]]] = defaultdict(lambda: defaultdict(list))  # article -> party -> stances
    if args.labels == "model":
        files = glob.glob(str(ROOT / "data" / "annotations" / f"model_{args.model}_*.jsonl"))
        for f in files:
            for line in open(f, encoding="utf-8"):
                d = json.loads(line)
                src, aid = d["key"].split(":", 1)
                if not src.startswith(("news_", "hist_")) or d["probs"]["political"][1] < 0.5:
                    continue
                for party in ("KMT", "DPP"):  # the model's TPP stance is not calibrated (docs/decision-model.md)
                    v = d["label"]["parties"][party]
                    if v["mentioned"] and v["stance"] is not None:
                        votes[aid][party].append(float(v["stance"]))
    files = files if args.labels == "model" else [  # flash-lite only checks the ranking; it is not a juror (jury-agreement.md)
        f for f in glob.glob(str(ROOT / "data" / "annotations" / "vertex_*.jsonl")) + glob.glob(str(ROOT / "data" / "annotations" / "pilot_*.jsonl"))
        if "flash-lite" not in Path(f).name]
    for f in ([] if args.labels == "model" else files):
        for line in open(f, encoding="utf-8"):
            d = json.loads(line)
            if not d["key"].startswith(("news:", "hist:")):
                continue
            for party, v in ((d.get("label") or {}).get("parties") or {}).items():
                if party in PARTIES and v and v.get("stance") is not None:
                    votes[d["key"].split(":", 1)[1]][party].append(float(v["stance"]))

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
                if party == "TPP" and published[:7] < "2019-08":
                    continue  # 台灣民眾黨 was founded in 2019-08; earlier mentions are other parties or misreadings
                cells[(source, party)][per].append(stances)

    mult, events = (1.0, {}) if args.no_events else load_events(kind)
    mult = args.jump if args.jump is not None else mult
    out = {"period": kind, "generated": date.today().isoformat(), "files": [Path(f).name for f in files],
           "events": not args.no_events, "jump": mult, "series": []}
    for (source, party), by_per in sorted(cells.items()):
        pers = all_periods(min(by_per), max(by_per), kind)
        ev = [e for e in events.get("*", []) + events.get(source, []) if e["period"] in pers[1:]]
        jump = np.ones(len(pers))
        for e in ev:  # the first period has no step before it, so an event there changes nothing
            jump[pers.index(e["period"])] = mult
        fit = smooth([summarize(by_per.get(p, [])) for p in pers], jump=jump)
        out["series"].append({
            "outlet": source, "party": party, "tau": fit["tau"], "events": ev,
            "points": [{"period": p, "n": len(by_per.get(p, [])), "mean": round(float(m), 3),
                        "lo": round(float(lo), 3), "hi": round(float(hi), 3)}
                       for p, m, lo, hi in zip(pers, fit["mean"], fit["lo"], fit["hi"])],
        })
    path = ROOT / "data" / "derived" / (f"trends_{kind}{'_model' if args.labels == 'model' else ''}"
                                         f"{'_noevents' if args.no_events else ''}"
                                         f"{f'_jump{mult:g}' if args.jump is not None else ''}.json")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(out, ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"{len(out['series'])} series, {len(votes)} annotated articles -> {path.relative_to(ROOT)}")
    for s in out["series"][:6]:
        print(s["outlet"], s["party"], [(p["period"], p["n"], p["mean"]) for p in s["points"]][:4])


if __name__ == "__main__":
    np.seterr(all="ignore")
    main()

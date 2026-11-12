"""Copy aggregate results into docs/assets/ for the website, which GitHub Pages serves from docs/ (no article text, no user data).

    uv run python scripts/export_site.py [--model tw-media-lean-v1]

Reads the decision-model trend fits with known events (scripts/fit_trends.py --labels model; monthly 2012-2026 and
weekly from 2026-08) and config/sources.yaml, and writes docs/assets/trends.json. Only per outlet x party x period
article counts, means and 95% intervals, plus the events from config/events.yaml, leave the machine, as PLAN.md
requires. The decision model does not score TPP stance (docs/decision-model.md), so the site shows KMT and DPP only.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[1]
PARTIES = ("KMT", "DPP")
START ={"month": "2012-01", "week": ""}  # the study period starts in 2012; a few outlets' archives go back further


def load(period: str) -> dict:
    d = json.loads((ROOT / "data" / "derived" / f"trends_{period}_model.json").read_text(encoding="utf-8"))
    series = [{"outlet": s["outlet"], "party": s["party"],
               "points": [{k: p[k] for k in ("period", "n", "mean", "lo", "hi")} for p in s["points"] if p["period"] >= START[period]]}
              for s in d["series"] if s["party"] in PARTIES]
    events = {}
    for s in d["series"]:
        for e in (e for e in s.get("events", []) if e["period"] >= START[period]):
            events.setdefault(s["outlet"], {})[e["date"]] = {k: e[k] for k in ("period", "date", "kind", "note")}
    return {"generated": d["generated"], "series": series,
            "events": {o: sorted(v.values(), key=lambda e: e["date"]) for o, v in events.items()}}


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--model", default="tw-media-lean-v1")
    model = ap.parse_args().model
    cfg = yaml.safe_load((ROOT / "config" / "sources.yaml").read_text(encoding="utf-8"))
    month, week = load("month"), load("week")
    out = {
        "model": model,
        "generated": max(month["generated"], week["generated"]),
        "outlets": {s["outlet"]: cfg["outlets"].get(s["outlet"].removeprefix("news_"), {}).get("name", s["outlet"])
                    for s in month["series"]},
        "month": month,
        "week": week,
    }
    path = ROOT / "docs" / "assets" / "trends.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(out, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
    print(f"month {len(month['series'])} + week {len(week['series'])} series, "
          f"{sum(len(v) for v in month['events'].values())} outlet events -> {path.relative_to(ROOT)}")


if __name__ == "__main__":
    main()

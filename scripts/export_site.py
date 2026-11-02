"""Copy aggregate results into site/data/ for the static website (no article text, no user data).

    uv run python scripts/export_site.py [--period month]

Reads data/derived/trends_<period>.json (scripts/fit_trends.py) and config/sources.yaml; writes
site/data/trends.json with outlet display names. Only per outlet x party x period means and intervals leave
the machine, as PLAN.md §4.2 and §10 require.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[1]


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--period", default="month")
    period = ap.parse_args().period
    trends = json.loads((ROOT / "data" / "derived" / f"trends_{period}.json").read_text(encoding="utf-8"))
    cfg = yaml.safe_load((ROOT / "config" / "sources.yaml").read_text(encoding="utf-8"))
    names = {f"news_{k}": v["name"] for k, v in cfg["outlets"].items()}
    out = {
        "period": trends["period"],
        "generated": trends["generated"],
        "outlets": {s["outlet"]: names.get(s["outlet"], s["outlet"]) for s in trends["series"]},
        "series": [{k: s[k] for k in ("outlet", "party", "points")} for s in trends["series"]],
    }
    path = ROOT / "site" / "data" / "trends.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(out, ensure_ascii=False), encoding="utf-8")
    print(f"{len(out['series'])} series -> {path.relative_to(ROOT)}")


if __name__ == "__main__":
    main()

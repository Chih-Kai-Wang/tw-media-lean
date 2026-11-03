"""Compare a decision model with its teacher on outlet x period cells (docs/decision-model.md).

Cell value = mean KMT stance - mean DPP stance (as in scripts/report_bulk.py), cells with >= 30 articles for each
party. Two comparisons per model:
  same  - the model on exactly the teacher-labelled articles (mostly training data, so it checks the scale only)
  all   - the model on every political article it labelled in the cell, which is how its labels are used
Reports Spearman rho, mean absolute cell difference and mean shift against the teacher.

    uv run python scripts/compare_model_cells.py tw-media-lean-v0 tw-media-lean-v1
"""

from __future__ import annotations

import glob
import json
import sys
from collections import defaultdict

import numpy as np
from pilot_annotation import stance
from report_bulk import ANN, labels, meta

TEACHER = "gemini-3.8-flash"
PARTIES = ("KMT", "DPP")


def period(pub: str) -> str | None:
    y = pub[:4]
    return "2012–15" if "2012" <= y <= "2015" else "2016–19" if y <= "2019" else "2020–23" if y <= "2023" else "2024–26" if y <= "2026" else None


def cells(lab: dict[str, dict], m: dict, keep=None) -> dict[tuple[str, str], float]:
    acc = defaultdict(lambda: {p: [] for p in PARTIES})
    for aid, la in lab.items():
        if aid not in m or (keep is not None and aid not in keep) or not la.get("parties"):
            continue
        outlet, pub = m[aid]
        per = period(pub)
        if per is None:
            continue
        for p in PARTIES:
            v = stance(la, p)
            if not np.isnan(v):
                acc[(outlet, per)][p].append(v)
    return {c: np.mean(v["KMT"]) - np.mean(v["DPP"]) for c, v in acc.items() if min(len(v["KMT"]), len(v["DPP"])) >= 30}


def by_id(lab: dict[str, dict]) -> dict[str, dict]:
    return {k.split(":", 1)[1]: v for k, v in lab.items()}


def compare(t: dict, e: dict) -> dict:
    common = sorted(set(t) & set(e))
    a, b = np.array([t[c] for c in common]), np.array([e[c] for c in common])
    rank = lambda v: np.argsort(np.argsort(v))
    return {"cells": len(common), "rho": round(float(np.corrcoef(rank(a), rank(b))[0, 1]), 2),
            "mae": round(float(np.abs(b - a).mean()), 2), "shift": round(float((b - a).mean()), 2)}


def main(models: list[str]) -> None:
    m = meta()
    teacher = by_id(labels(f"vertex_{TEACHER}_history.jsonl") | labels(f"vertex_{TEACHER}_live_*.jsonl"))
    tc = cells(teacher, m)
    out = {}
    for name in models:
        lab = {}
        for f in glob.glob(str(ANN / f"model_{name}_*.jsonl")):
            for line in open(f, encoding="utf-8"):
                d = json.loads(line)
                if d["label"].get("political"):
                    lab[d["key"].split(":", 1)[1]] = d["label"]
        out[name] = {"same": compare(tc, cells(lab, m, keep=set(teacher))), "all": compare(tc, cells(lab, m))}
    print(json.dumps(out, indent=1, ensure_ascii=False))


if __name__ == "__main__":
    main(sys.argv[1:] or ["tw-media-lean-v0", "tw-media-lean-v1"])

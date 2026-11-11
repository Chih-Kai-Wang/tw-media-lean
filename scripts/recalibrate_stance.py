"""Refit the decision model's stance calibration on the weekly live batches (docs/drift-monitor.md).

The drift rule: when a party exceeds the alert threshold two weeks in a row, recalibrate on new teacher labels.
The model's outputs keep the full stance probabilities, so no new inference is needed: per party, fit a new
linear map a + b x (expected stance) onto the teacher's stance, using the live batches labelled after the model
was trained. The map is fitted in the inverse direction (see fit()), so that group means are unbiased.

Before applying, each live week is held out in turn (fit on the other weeks) and the held-out shift, slope and
mean absolute difference are compared with the current calibration. Applying writes a new model directory
whose config carries the new map (the encoder and heads are linked, not copied), then relabels the existing
predictions into model_<new>_{news,hist}.jsonl.

    uv run python scripts/recalibrate_stance.py                      # evaluate only
    uv run python scripts/recalibrate_stance.py --apply tw-media-lean-v1.1
"""

from __future__ import annotations

import argparse
import glob
import json
from pathlib import Path

import numpy as np
from predict_decision_model import to_label

ROOT = Path(__file__).resolve().parents[1]
ANN = ROOT / "data" / "annotations"
TEACHER = "gemini-3.8-flash"
PARTIES = ("KMT", "DPP")


def expected(probs: list[float]) -> float:
    return sum((i - 2) * q for i, q in enumerate(probs))


def measures(e: np.ndarray, t: np.ndarray) -> tuple[float, float, float]:
    return float(np.mean(e - t)), float(np.polyfit(t, e, 1)[0]), float(np.mean(np.abs(e - t)))


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--model", default="tw-media-lean-v1")
    ap.add_argument("--apply", default="", help="name of the recalibrated model to write")
    args = ap.parse_args()
    mdir = ROOT / "data" / "models" / args.model
    cfg = json.loads((mdir / "config.json").read_text())
    trained = (mdir / "heads.pt").stat().st_mtime
    probs = {}
    for line in open(ANN / f"model_{args.model}_news.jsonl", encoding="utf-8"):
        d = json.loads(line)
        probs[d["key"].split(":", 1)[1]] = d

    weeks = {}  # batch name -> party -> [(raw expected stance, teacher stance)]
    for f in sorted(glob.glob(str(ANN / f"vertex_{TEACHER}_live_*.jsonl"))):
        if Path(f).stat().st_mtime < trained:  # labelled before training: part of the training data
            continue
        rows = {p: [] for p in PARTIES}
        for line in open(f, encoding="utf-8"):
            d = json.loads(line)
            aid, lab = d["key"].split(":", 1)[1], d.get("label") or {}
            if aid not in probs or not lab.get("political"):
                continue
            m = probs[aid]
            for p in PARTIES:
                t = ((lab.get("parties") or {}).get(p) or {}).get("stance")
                if t is not None and m["label"]["parties"][p]["mentioned"]:
                    rows[p].append((expected(m["probs"][f"{p}_stance"]), float(t)))
        weeks[Path(f).stem.split("_", 3)[-1]] = {p: np.array(v) for p, v in rows.items()}
    if len(weeks) < 2:
        raise SystemExit(f"need at least two live weeks after training, have {len(weeks)}")

    old = cfg["stance_scale"]
    cal = lambda x, ab: np.clip(ab[0] + ab[1] * x, -2, 2)
    def fit(x: np.ndarray, t: np.ndarray) -> list[float]:
        # Inverse calibration: regress the raw expected stance on the teacher (x = c + d t) and invert, so that
        # the calibrated stance has slope 1 and no shift against the teacher -- unbiased group means, which is
        # what the trends need. Regressing the teacher on x instead shrinks toward the mean when x is noisy.
        d, c = np.polyfit(t, x, 1)
        return [float(-c / d), float(1 / d)]
    print("held-out week | party | n | current: shift slope MAE | refit: shift slope MAE")
    for w in weeks:
        for p in PARTIES:
            test = weeks[w][p]
            train = np.concatenate([weeks[o][p] for o in weeks if o != w])
            if len(test) < 20 or len(train) < 20:
                continue
            new = fit(train[:, 0], train[:, 1])
            a = measures(cal(test[:, 0], old[p]), test[:, 1])
            b = measures(cal(test[:, 0], new), test[:, 1])
            print(f"{w} | {p} | {len(test)} | {a[0]:+.3f} {a[1]:.2f} {a[2]:.2f} | {b[0]:+.3f} {b[1]:.2f} {b[2]:.2f}")

    allw = {p: np.concatenate([weeks[w][p] for w in weeks]) for p in PARTIES}
    scale = dict(old)
    for p in PARTIES:
        scale[p] = fit(allw[p][:, 0], allw[p][:, 1])
    print("current map:", {p: [round(x, 3) for x in old[p]] for p in PARTIES})
    print("refit on all live weeks:", {p: [round(x, 3) for x in scale[p]] for p in PARTIES}, {p: len(allw[p]) for p in PARTIES})
    if not args.apply:
        return

    new_dir = ROOT / "data" / "models" / args.apply
    new_dir.mkdir(parents=True, exist_ok=True)
    for name in ("encoder", "heads.pt"):
        if not (new_dir / name).exists():
            (new_dir / name).symlink_to(mdir / name)
    cfg.update(stance_scale=scale, recalibrated_from=args.model, recalibrated_on=sorted(weeks))
    (new_dir / "config.json").write_text(json.dumps(cfg, indent=1))
    for tag in ("news", "hist"):
        src, dst = ANN / f"model_{args.model}_{tag}.jsonl", ANN / f"model_{args.apply}_{tag}.jsonl"
        with open(src, encoding="utf-8") as fi, open(dst, "w", encoding="utf-8") as fo:
            for line in fi:
                d = json.loads(line)
                d.update(label=to_label(d["probs"], scale), model=args.apply)
                fo.write(json.dumps(d, ensure_ascii=False) + "\n")
        print(f"-> {dst.relative_to(ROOT)}")


if __name__ == "__main__":
    main()

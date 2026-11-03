"""Inverse stance calibration for a trained decision model (docs/decision-model.md).

On the validation split, fit the model's expected stance on the teacher's, e = c + d*t, per party; the corrected
score is t_hat = (e - c) / d. Unlike regressing teacher on model (which shrinks spread by construction), this
removes both the shift and the compression, at the cost of more per-article noise, which averages out in the
outlet x period means the model is used for. Writes stance_scale = [-c/d, 1/d] into the model's config.json and
reports test-split shift and slope against the published thresholds (|shift| < 0.03, slope > 0.8).

    uv run --extra train python scripts/calibrate_stance.py data/models/tw-media-lean-v1
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import numpy as np
import torch
from train_decision_model import HEADS, IGNORE, PARTIES, Model, load_examples, predict, shift_and_slope

from transformers import AutoTokenizer


def expected(logits: torch.Tensor, temp: float) -> np.ndarray:
    return ((logits / temp).softmax(-1) * torch.arange(-2, 3).float()).sum(-1).numpy()


def main(mdir: str) -> None:
    mdir = Path(mdir)
    cfg = json.loads((mdir / "config.json").read_text())
    temps = cfg["temperatures"]
    device = "mps" if torch.backends.mps.is_available() else "cpu"
    tok = AutoTokenizer.from_pretrained(mdir / "encoder")
    model = Model(str(mdir / "encoder"))
    model.heads.load_state_dict(torch.load(mdir / "heads.pt", map_location="cpu"))
    model.to(device)
    ex = load_examples()
    split = lambda e: int(e["id"][:8], 16) % 10
    val = [e for e in ex if split(e) == 1]
    test = [e for e in ex if split(e) == 0]
    vl, vy = predict(model, val, tok, 32, cfg["max_len"], device)
    tl, ty = predict(model, test, tok, 32, cfg["max_len"], device)

    scale = {}
    for p in PARTIES:
        h = f"{p}_stance"
        keep = vy[h] != IGNORE
        e = expected(vl[h][keep], temps.get(h, 1.0))
        t = vy[h][keep].numpy() - 2.0
        d, c = np.polyfit(t, e, 1)  # model on teacher
        scale[p] = [float(-c / d), float(1 / d)]
    result = {"raw": shift_and_slope(tl, ty, temps, None), "inverse": shift_and_slope(tl, ty, temps, scale)}
    passed = all(abs(result["inverse"][p]["mean_diff"]) < 0.03 and result["inverse"][p]["slope"] > 0.8 for p in ("KMT", "DPP"))
    cfg["stance_scale"] = scale
    cfg["stance_scale_method"] = "inverse: e = c + d*t fitted on validation; t_hat = (e - c) / d"
    (mdir / "config.json").write_text(json.dumps(cfg, indent=1))
    metrics = json.loads((mdir / "metrics.json").read_text())
    metrics["stance_scale"] = scale
    metrics["stance_vs_teacher"]["inverse"] = result["inverse"]
    metrics["criteria_passed"] = passed
    (mdir / "metrics.json").write_text(json.dumps(metrics, indent=1))
    print(json.dumps({"scale": scale, **result, "passed (KMT, DPP)": passed}, indent=1))


if __name__ == "__main__":
    main(sys.argv[1])

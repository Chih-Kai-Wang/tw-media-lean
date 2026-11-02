"""Label articles with a trained decision model (scripts/train_decision_model.py) and write calibrated probabilities.

    uv run --extra train python scripts/predict_decision_model.py --model data/models/<name> --sources "news_*"

Output: data/annotations/model_<name>.jsonl, one line per article: key, per-head class probabilities (after
temperature scaling), and the codebook-style label (argmax; stance as the expected value). PTT may be labelled
here (inference only, nothing is trained on it), but its results are only published in aggregate.
"""

from __future__ import annotations

import argparse
import glob
import json
from pathlib import Path

import torch
from train_decision_model import GENRES, HEADS, PARTIES, TOPICS, Model

from transformers import AutoTokenizer

ROOT = Path(__file__).resolve().parents[1]


def to_label(probs: dict[str, list[float]]) -> dict:
    arg = {h: max(range(len(p)), key=p.__getitem__) for h, p in probs.items()}
    label = {"political": bool(arg["political"]), "genre": GENRES[arg["genre"]], "topic": TOPICS[arg["topic"]], "parties": {}}
    for p in PARTIES:
        mentioned = bool(arg[f"{p}_mentioned"])
        stance = sum((i - 2) * q for i, q in enumerate(probs[f"{p}_stance"]))
        label["parties"][p] = {"mentioned": mentioned, "stance": round(stance, 3) if mentioned else None,
                               "salience": arg[f"{p}_salience"] if mentioned else 0}
    return label


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--model", required=True)
    ap.add_argument("--sources", default="news_*")
    ap.add_argument("--batch", type=int, default=32)
    args = ap.parse_args()
    mdir = Path(args.model)
    cfg = json.loads((mdir / "config.json").read_text())
    device = "cuda" if torch.cuda.is_available() else "cpu"
    tok = AutoTokenizer.from_pretrained(mdir / "encoder")
    model = Model(str(mdir / "encoder"))
    model.heads.load_state_dict(torch.load(mdir / "heads.pt", map_location="cpu"))
    model.to(device).eval()
    temps = cfg["temperatures"]

    rows = []
    for f in sorted(glob.glob(str(ROOT / "data" / "raw" / args.sources / "*.jsonl"))):
        for line in open(f, encoding="utf-8"):
            r = json.loads(line)
            if r.get("text"):
                rows.append((f"{Path(f).parent.name}:{r['id']}", (r.get("title") or "") + "\n" + r["text"]))
    out_path = ROOT / "data" / "annotations" / f"model_{mdir.name}.jsonl"
    with open(out_path, "w", encoding="utf-8") as out, torch.no_grad():
        for i in range(0, len(rows), args.batch):
            chunk = rows[i : i + args.batch]
            enc = tok([t for _, t in chunk], truncation=True, max_length=cfg["max_len"], padding=True, return_tensors="pt")
            logits = model(**{k: v.to(device) for k, v in enc.items()})
            probs = {h: (logits[h].float().cpu() / temps.get(h, 1.0)).softmax(-1).tolist() for h in HEADS}
            for j, (key, _) in enumerate(chunk):
                p = {h: [round(x, 4) for x in probs[h][j]] for h in HEADS}
                out.write(json.dumps({"key": key, "probs": p, "label": to_label(p), "model": mdir.name}, ensure_ascii=False) + "\n")
    print(f"{len(rows)} articles -> {out_path.relative_to(ROOT)}")


if __name__ == "__main__":
    main()

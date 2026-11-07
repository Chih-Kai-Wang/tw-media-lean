"""Label articles with a trained decision model (scripts/train_decision_model.py) and write calibrated probabilities.

    uv run --extra train python scripts/predict_decision_model.py --model data/models/<name> --sources "news_*"
    (add --update to label only articles not yet in the output file, --political-only to skip articles naming no party)

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
from vertex_batch import POLITICAL

from transformers import AutoTokenizer

ROOT = Path(__file__).resolve().parents[1]


def to_label(probs: dict[str, list[float]], scale: dict | None = None) -> dict:
    arg = {h: max(range(len(p)), key=p.__getitem__) for h, p in probs.items()}
    label = {"political": bool(arg["political"]), "genre": GENRES[arg["genre"]], "topic": TOPICS[arg["topic"]], "parties": {}}
    for p in PARTIES:
        mentioned = bool(arg[f"{p}_mentioned"])
        stance = sum((i - 2) * q for i, q in enumerate(probs[f"{p}_stance"]))
        if scale and p in scale:  # map back onto the teacher's scale (fitted on validation data, v1+)
            a, b = scale[p]
            stance = min(2.0, max(-2.0, a + b * stance))
        label["parties"][p] = {"mentioned": mentioned, "stance": round(stance, 3) if mentioned else None,
                               "salience": arg[f"{p}_salience"] if mentioned else 0}
    return label


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--model", required=True)
    ap.add_argument("--sources", default="news_*")
    ap.add_argument("--batch", type=int, default=32)
    ap.add_argument("--update", action="store_true", help="keep existing output and label only new articles")
    ap.add_argument("--political-only", action="store_true",
                    help="skip articles that name no party or party leader (the jury's sampling filter); the model "
                         "would label almost all of them non-political, and the history backfill is mostly such articles")
    args = ap.parse_args()
    mdir = Path(args.model)
    cfg = json.loads((mdir / "config.json").read_text())
    device = "cuda" if torch.cuda.is_available() else "mps" if torch.backends.mps.is_available() else "cpu"
    tok = AutoTokenizer.from_pretrained(mdir / "encoder")
    model = Model(str(mdir / "encoder"))
    model.heads.load_state_dict(torch.load(mdir / "heads.pt", map_location="cpu"))
    model.to(device).eval()
    temps = cfg["temperatures"]

    rows = []
    for f in sorted(glob.glob(str(ROOT / "data" / "raw" / args.sources / "*.jsonl"))):
        for line in open(f, encoding="utf-8"):
            r = json.loads(line)
            if r.get("text") and not (args.political_only and not POLITICAL.search((r.get("title") or "") + r["text"])):
                rows.append((f"{Path(f).parent.name}:{r['id']}", (r.get("title") or "") + "\n" + r["text"]))
    tag = args.sources.replace("*", "").strip("_") or "all"
    out_path = ROOT / "data" / "annotations" / f"model_{mdir.name}_{tag}.jsonl"
    if args.update and out_path.exists():
        done = {json.loads(line)["key"] for line in open(out_path, encoding="utf-8")}
        rows = [r for r in rows if r[0] not in done]
    with open(out_path, "a" if args.update else "w", encoding="utf-8") as out, torch.no_grad():
        for i in range(0, len(rows), args.batch):
            chunk = rows[i : i + args.batch]
            enc = tok([t for _, t in chunk], truncation=True, max_length=cfg["max_len"], padding=True, return_tensors="pt")
            logits = model(**{k: v.to(device) for k, v in enc.items()})
            probs = {h: (logits[h].float().cpu() / temps.get(h, 1.0)).softmax(-1).tolist() for h in HEADS}
            for j, (key, _) in enumerate(chunk):
                p = {h: [round(x, 4) for x in probs[h][j]] for h in HEADS}
                out.write(json.dumps({"key": key, "probs": p, "label": to_label(p, cfg.get("stance_scale")), "model": mdir.name}, ensure_ascii=False) + "\n")
    print(f"{len(rows)} articles -> {out_path.relative_to(ROOT)}")


if __name__ == "__main__":
    main()

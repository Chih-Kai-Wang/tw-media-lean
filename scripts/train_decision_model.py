"""Method C (PLAN.md §5.4), route 2: a Chinese encoder with one classification head per codebook question.

Distils the LLM-jury labels into a small open model that can label every sampled article for free.
Heads: political (2), genre (4), topic (9), and per party: mentioned (2), stance (5, -2..+2, trained only where
mentioned), salience (4). Labels: for each article and question, the majority (stance: rounded mean) over the
available jurors. Sources whose robots.txt says ai-train=no are never used for training: PTT, and outlets marked
`ai_train: false` in config/sources.yaml (CNA); they are still labelled by the trained model.
Calibration: one temperature per head fitted on the validation split (temperature scaling).

    uv run --extra train python scripts/train_decision_model.py --base ckiplab/bert-tiny-chinese --epochs 1   # smoke test
    (on Kaggle GPU) python train_decision_model.py --base ckiplab/bert-base-chinese --epochs 3

Writes the model, tokenizer, heads and calibration to data/models/<name>/ and metrics to metrics.json.
"""

from __future__ import annotations

import argparse
import glob
import json
import random
from collections import Counter, defaultdict
from pathlib import Path

import numpy as np
import torch
import yaml
from torch import nn
from transformers import AutoModel, AutoTokenizer

ROOT = Path(__file__).resolve().parents[1]
PARTIES = ("KMT", "DPP", "TPP")
GENRES = ("news", "opinion", "press_release", "other")
TOPICS = ("election", "cross_strait", "foreign_defense", "economy", "energy_environment", "justice_scandal",
          "legislature", "social_welfare", "other")
HEADS = {"political": 2, "genre": len(GENRES), "topic": len(TOPICS)} | {
    f"{p}_{q}": n for p in PARTIES for q, n in (("mentioned", 2), ("stance", 5), ("salience", 4))}
IGNORE = -100
TEACHER = "gemini-3.8-flash"


def majority(values: list):
    return Counter(values).most_common(1)[0][0] if values else None


def targets(labels: list[dict]) -> dict[str, int]:
    """Collapse several jurors' labels for one article into one class index per head (IGNORE if unknown)."""
    t = {h: IGNORE for h in HEADS}
    pol = majority([bool(l.get("political")) for l in labels if "political" in l])
    if pol is not None:
        t["political"] = int(pol)
    g = majority([l.get("genre") for l in labels if l.get("genre") in GENRES])
    if g:
        t["genre"] = GENRES.index(g)
    tp = majority([l.get("topic") for l in labels if l.get("topic") in TOPICS])
    if tp:
        t["topic"] = TOPICS.index(tp)
    for p in PARTIES:
        votes = [l["parties"][p] for l in labels if isinstance(l.get("parties", {}).get(p), dict)]
        m = majority([bool(v.get("mentioned")) for v in votes])
        if m is None:
            continue
        t[f"{p}_mentioned"] = int(m)
        sal = [v.get("salience") for v in votes if isinstance(v.get("salience"), int) and 0 <= v["salience"] <= 3]
        if sal:
            t[f"{p}_salience"] = int(round(np.mean(sal)))
        st = [v.get("stance") for v in votes if isinstance(v.get("stance"), (int, float)) and -2 <= v["stance"] <= 2]
        if m and st:
            t[f"{p}_stance"] = int(round(np.mean(st))) + 2
    return t


def no_train_sources() -> set[str]:
    cfg = yaml.safe_load((ROOT / "config" / "sources.yaml").read_text(encoding="utf-8"))
    return {f"{prefix}_{k}" for k, v in cfg["outlets"].items() if v.get("ai_train") is False for prefix in ("news", "hist")}


def load_examples() -> list[dict]:
    texts = {}
    excluded = no_train_sources()
    files = glob.glob(str(ROOT / "data" / "raw" / "news_*" / "*.jsonl")) + glob.glob(str(ROOT / "data" / "raw" / "hist_*" / "*.jsonl")) \
        + glob.glob(str(ROOT / "data" / "raw" / "party_*" / "*.jsonl"))
    for f in files:
        if Path(f).parent.name.removesuffix("_wb") in excluded:
            continue
        for line in open(f, encoding="utf-8"):
            r = json.loads(line)
            if r.get("text"):
                texts[r["id"]] = ((r.get("title") or "") + "\n" + r["text"], r.get("published") or "")
    by_article: dict[str, list[dict]] = defaultdict(list)
    # teacher: the primary juror only (the smaller model is weaker on anchors, docs/jury-agreement.md); the OpenCode
    # pilot labels are not used for training
    for f in glob.glob(str(ROOT / "data" / "annotations" / f"vertex_{TEACHER}_*.jsonl")):
        if Path(f).stem.endswith("_swap"):
            continue  # masked/swapped texts are tests, not training data
        for line in open(f, encoding="utf-8"):
            d = json.loads(line)
            kind, aid = d["key"].split(":", 1)
            if kind in ("news", "anchor", "hist") and isinstance(d.get("label"), dict) and "parties" in d["label"]:
                by_article[aid].append(d["label"])
    return [{"id": a, "text": texts[a][0], "published": texts[a][1], "y": targets(ls)}
            for a, ls in by_article.items() if a in texts]


class Model(nn.Module):
    def __init__(self, base: str):
        super().__init__()
        self.encoder = AutoModel.from_pretrained(base)
        dim = self.encoder.config.hidden_size
        self.dropout = nn.Dropout(0.1)
        self.heads = nn.ModuleDict({h: nn.Linear(dim, n) for h, n in HEADS.items()})

    def forward(self, **enc):
        cls = self.dropout(self.encoder(**enc).last_hidden_state[:, 0])
        return {h: head(cls) for h, head in self.heads.items()}


def batches(examples, tok, size, max_len, shuffle):
    order = list(range(len(examples)))
    if shuffle:
        random.shuffle(order)
    for i in range(0, len(order), size):
        chunk = [examples[j] for j in order[i : i + size]]
        enc = tok([e["text"] for e in chunk], truncation=True, max_length=max_len, padding=True, return_tensors="pt")
        y = {h: torch.tensor([e["y"][h] for e in chunk]) for h in HEADS}
        yield enc, y


@torch.no_grad()
def predict(model, examples, tok, size, max_len, device):
    model.eval()
    logits, ys = defaultdict(list), defaultdict(list)
    for enc, y in batches(examples, tok, size, max_len, shuffle=False):
        out = model(**{k: v.to(device) for k, v in enc.items()})
        for h in HEADS:
            logits[h].append(out[h].float().cpu())
            ys[h].append(y[h])
    return {h: torch.cat(logits[h]) for h in HEADS}, {h: torch.cat(ys[h]) for h in HEADS}


def fit_temperature(logits: torch.Tensor, y: torch.Tensor) -> float:
    keep = y != IGNORE
    if keep.sum() < 10:
        return 1.0
    z, t = logits[keep], y[keep]
    best = min(np.geomspace(0.25, 8, 40), key=lambda T: nn.functional.cross_entropy(z / T, t).item())
    return float(best)


def evaluate(logits, ys, temps) -> dict:
    out = {}
    for h in HEADS:
        keep = ys[h] != IGNORE
        if keep.sum() == 0:
            continue
        z, t = logits[h][keep] / temps.get(h, 1.0), ys[h][keep]
        prob = z.softmax(-1)
        conf, pred = prob.max(-1)
        bins = torch.linspace(0, 1, 11)
        ece = sum(((conf > lo) & (conf <= hi)).float().mean().item()
                  * abs((pred[(conf > lo) & (conf <= hi)] == t[(conf > lo) & (conf <= hi)]).float().mean().item()
                        - conf[(conf > lo) & (conf <= hi)].mean().item())
                  for lo, hi in zip(bins[:-1], bins[1:]) if ((conf > lo) & (conf <= hi)).any())
        m = {"n": int(keep.sum()), "accuracy": round((pred == t).float().mean().item(), 3), "ece": round(ece, 3)}
        if h.endswith("_stance"):
            expected = (prob * torch.arange(-2, 3).float()).sum(-1)
            m["mae"] = round((expected - (t.float() - 2)).abs().mean().item(), 3)
        out[h] = m
    return out


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--base", default="ckiplab/bert-base-chinese")
    ap.add_argument("--epochs", type=int, default=3)
    ap.add_argument("--batch", type=int, default=16)
    ap.add_argument("--max-len", type=int, default=512)
    ap.add_argument("--lr", type=float, default=3e-5)
    ap.add_argument("--name", default=None)
    args = ap.parse_args()
    random.seed(0)
    torch.manual_seed(0)
    device = "cuda" if torch.cuda.is_available() else "mps" if torch.backends.mps.is_available() else "cpu"

    examples = load_examples()
    # split by article id hash so the split is stable as more labels arrive
    split = lambda e: int(e["id"][:8], 16) % 10 if all(c in "0123456789abcdef" for c in e["id"][:8]) else hash(e["id"]) % 10
    train = [e for e in examples if split(e) >= 2]
    val = [e for e in examples if split(e) == 1]
    test = [e for e in examples if split(e) == 0]
    print(f"{len(examples)} labelled articles: train {len(train)}, val {len(val)}, test {len(test)}; device {device}")

    tok = AutoTokenizer.from_pretrained(args.base)
    model = Model(args.base).to(device)
    opt = torch.optim.AdamW(model.parameters(), lr=args.lr, weight_decay=0.01)
    loss_fn = nn.CrossEntropyLoss(ignore_index=IGNORE)
    for epoch in range(args.epochs):
        model.train()
        total = 0.0
        for step, (enc, y) in enumerate(batches(train, tok, args.batch, args.max_len, shuffle=True)):
            out = model(**{k: v.to(device) for k, v in enc.items()})
            losses = [loss_fn(out[h], y[h].to(device)) for h in HEADS if (y[h] != IGNORE).any()]
            loss = torch.stack(losses).sum()
            opt.zero_grad()
            loss.backward()
            opt.step()
            total += loss.item()
        print(f"epoch {epoch + 1}: train loss {total / (step + 1):.3f}")

    val_logits, val_y = predict(model, val, tok, args.batch, args.max_len, device)
    temps = {h: fit_temperature(val_logits[h], val_y[h]) for h in HEADS}
    test_logits, test_y = predict(model, test, tok, args.batch, args.max_len, device)
    metrics = {"base": args.base, "n": {"train": len(train), "val": len(val), "test": len(test)},
               "test": evaluate(test_logits, test_y, temps), "temperatures": temps}
    name = args.name or args.base.split("/")[-1]
    out = ROOT / "data" / "models" / name
    out.mkdir(parents=True, exist_ok=True)
    model.encoder.save_pretrained(out / "encoder")
    tok.save_pretrained(out / "encoder")
    torch.save(model.heads.state_dict(), out / "heads.pt")
    (out / "config.json").write_text(json.dumps({"heads": HEADS, "genres": GENRES, "topics": TOPICS,
                                                 "parties": PARTIES, "max_len": args.max_len, "temperatures": temps}, indent=1))
    (out / "metrics.json").write_text(json.dumps(metrics, indent=1))
    print(json.dumps(metrics["test"], indent=1)[:1500])


if __name__ == "__main__":
    main()

"""LLM annotation through Vertex AI Gemini batch prediction (PLAN.md §5.3; budget terms in private/gcp.md).

    uv run python scripts/vertex_batch.py build  pilot90|pilot1000|anchors|swap|history
    uv run python scripts/vertex_batch.py build  live 2026-10-28 2026-11-08   # election window, by publication date
    uv run python scripts/vertex_batch.py submit pilot90
    uv run python scripts/vertex_batch.py fetch  pilot90      # waits for the job, parses, prints token cost

pilot90 re-labels the exact items of the OpenCode pilot (keys in data/annotations/pilot_*.jsonl) so Vertex
can be compared with the three existing jurors. pilot1000: 75 political articles per outlet + 50 KMT and 50 DPP
press releases (2016 on). PTT is never included. Every GCS object, request and job is labelled
project=tw-media-lean. Batch output carries no custom key, so results are matched by a hash of the prompt.
GCP settings (TWM_GCP_PROJECT, TWM_GCLOUD_CONFIG, TWM_GCS_BUCKET) come from the environment or `.env`;
credentials come from gcloud and are never printed.
"""

from __future__ import annotations

import glob
import hashlib
import json
import os
import random
import re
import subprocess
import sys
import time
from pathlib import Path

import httpx
import yaml

from twmedia.annotate import CODEBOOK_VERSION, build_prompt, mask_people, parse, swap_parties

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "data" / "vertex"
def _env(key: str, default: str = "") -> str:
    if os.environ.get(key):
        return os.environ[key]
    env = ROOT / ".env"
    for line in env.read_text(encoding="utf-8").splitlines() if env.exists() else []:
        if line.startswith(key + "="):
            return line.split("=", 1)[1].strip()
    return default


PROJECT, GCLOUD_CONFIG = _env("TWM_GCP_PROJECT"), _env("TWM_GCLOUD_CONFIG", "default")
LOCATION = os.environ.get("TWM_VERTEX_LOCATION", "us")  # multi-region; amendment 2026-11-02, see private/gcp.md
BUCKET = _env("TWM_GCS_BUCKET")
MODEL = os.environ.get("TWM_VERTEX_MODEL", "gemini-3.8-flash")
LABELS = {"project": "tw-media-lean"}
# USD per 1M tokens, batch (50% of online), checked 2026-11-02 on cloud.google.com/vertex-ai/generative-ai/pricing
PRICE = {"gemini-3.8-flash": (0.4125, 2.0625)}  # non-global, introductory price through 2026-12-31
# Gemini 3 takes a thinking level instead of a budget; 3.8 Flash's lowest is LOW
THINKING = {"gemini-3.8-flash": {"thinkingLevel": "LOW"}}
POLITICAL = re.compile(r"國民黨|民進黨|民眾黨|藍營|綠營|白營|藍白|黨團|賴清德|鄭麗文|黃國昌|柯文哲")
# multi-regions (us, eu) use the regional-endpoint host, single regions the {region}- prefix
HOST = {"global": "aiplatform.googleapis.com", "us": "aiplatform.us.rep.googleapis.com",
        "eu": "aiplatform.eu.rep.googleapis.com"}.get(LOCATION, f"{LOCATION}-aiplatform.googleapis.com")
API = f"https://{HOST}/v1/projects/{PROJECT}/locations/{LOCATION}"


def gcloud(*args: str) -> str:
    return subprocess.run(["gcloud", f"--configuration={GCLOUD_CONFIG}", *args], check=True,
                          capture_output=True, text=True).stdout.strip()


def headers() -> dict:
    return {"Authorization": f"Bearer {gcloud('auth', 'print-access-token')}", "x-goog-user-project": PROJECT}


def no_ai_input() -> set[str]:
    """Sources whose owners reserve AI use (config `ai_input: false`): never sent to an LLM."""
    cfg = yaml.safe_load((ROOT / "config" / "sources.yaml").read_text(encoding="utf-8"))
    return {f"{p}_{k}" for k, v in cfg["outlets"].items() if v.get("ai_input") is False for p in ("news", "hist")}


def load(source_glob: str) -> dict[str, dict]:
    rows = {}
    excluded = no_ai_input()
    for f in sorted(glob.glob(str(ROOT / "data" / "raw" / source_glob / "*.jsonl"))):
        if Path(f).parent.name in excluded:
            continue
        for line in open(f, encoding="utf-8"):
            r = json.loads(line)
            if r.get("text") and len(r["text"]) > 200:
                rows[r["id"]] = {**r, "source": Path(f).parent.name}
    return rows


def items_pilot90() -> list[dict]:
    pool = load("news_*") | load("party_*")
    out = []
    for line in open(ROOT / "data" / "annotations" / "pilot_gpt-5.6-luna.jsonl", encoding="utf-8"):
        kind, rid = json.loads(line)["key"].split(":", 1)
        r = pool[rid]
        title, text = r.get("title") or "", r["text"]
        if kind == "swap":
            title, text = swap_parties(title), swap_parties(text)
        out.append({"key": f"{kind}:{rid}", "source": r["source"], "title": title, "text": text})
    return out


def items_pilot1000() -> list[dict]:
    rng = random.Random(20261102)
    news = load("news_*")
    out = []
    for src in sorted({r["source"] for r in news.values()}):
        pool = sorted((r for r in news.values() if r["source"] == src and POLITICAL.search((r.get("title") or "") + r["text"])),
                      key=lambda r: r["id"])
        out += [{"key": f"news:{r['id']}", "source": src, "title": r.get("title") or "", "text": r["text"]}
                for r in rng.sample(pool, min(75, len(pool)))]
    for party in ("kmt", "dpp"):
        pool = sorted((r for r in load(f"party_{party}").values()
                       if (r.get("published") or "") >= "2016" and POLITICAL.search(r["text"])), key=lambda r: r["id"])
        out += [{"key": f"anchor:{r['id']}", "source": f"party_{party}", "title": r.get("title") or "", "text": r["text"]}
                for r in rng.sample(pool, min(50, len(pool)))]
    return out


def annotated() -> set[str]:
    """Keys already labelled by any Vertex batch, so a new batch never pays for them twice."""
    done = set()
    for f in glob.glob(str(ROOT / "data" / "annotations" / "vertex_*.jsonl")):
        done |= {json.loads(line)["key"] for line in open(f, encoding="utf-8")}
    return done


def _item(kind: str, r: dict, title: str | None = None, text: str | None = None) -> dict:
    return {"key": f"{kind}:{r['id']}", "source": r["source"], "title": title if title is not None else r.get("title") or "",
            "text": text if text is not None else r["text"]}


def items_live(first: str, last: str, per_day: int = 15) -> list[dict]:
    """Election window: up to `per_day` political articles per outlet per publication day."""
    rng, done = random.Random(f"live-{first}-{last}"), annotated()
    by_cell: dict[tuple[str, str], list[dict]] = {}
    for r in load("news_*").values():
        day = (r.get("published") or "")[:10]
        if first <= day <= last and f"news:{r['id']}" not in done and POLITICAL.search((r.get("title") or "") + r["text"]):
            by_cell.setdefault((r["source"], day), []).append(r)
    out = []
    for cell in sorted(by_cell):
        pool = sorted(by_cell[cell], key=lambda r: r["id"])
        out += [_item("news", r) for r in rng.sample(pool, min(per_day, len(pool)))]
    return out


def items_anchors(per_party: int = 1000) -> list[dict]:
    """Party press releases spread evenly over the years they exist (known-direction anchors)."""
    rng, done, out = random.Random(20261103), annotated(), []
    for party in ("kmt", "dpp"):
        by_year: dict[str, list[dict]] = {}
        for r in load(f"party_{party}").values():
            year = (r.get("published") or "")[:4]
            if year >= "2012" and f"anchor:{r['id']}" not in done and POLITICAL.search(r["text"]):
                by_year.setdefault(year, []).append(r)
        quota = per_party // max(len(by_year), 1)
        for year in sorted(by_year):
            pool = sorted(by_year[year], key=lambda r: r["id"])
            out += [_item("anchor", r) for r in rng.sample(pool, min(quota, len(pool)))]
    return out


def items_swap(n: int = 500) -> list[dict]:
    """Party-swap test at scale (docs/swap-test.md): names masked, then KMT/DPP labels exchanged."""
    rng, out = random.Random(20261104), []
    pool = []
    for r in sorted(load("news_*").values(), key=lambda r: r["id"]):
        title, text = mask_people(r.get("title") or "", r["text"][:3000])
        if "國民黨" in title + text and "民進黨" in title + text:
            pool.append((r, title, text))
    for r, title, text in rng.sample(pool, min(n, len(pool))):
        out.append(_item("masked", r, title, text))
        out.append(_item("swapped", r, swap_parties(title), swap_parties(text)))
    return out


def items_history(per_cell: int = 12) -> list[dict]:
    """Historical sample: `per_cell` political articles per outlet per month (scripts/history.sh, vm_sync.sh)."""
    rng, done = random.Random(20261105), annotated()
    excluded = no_ai_input()
    by_cell: dict[tuple[str, str], list[dict]] = {}
    for f in sorted(glob.glob(str(ROOT / "data" / "raw" / "hist_*" / "*.jsonl"))):
        source = Path(f).parent.name.removesuffix("_wb")
        if source in excluded:
            continue
        for line in open(f, encoding="utf-8"):
            r = json.loads(line)
            month = (r.get("published") or "")[:7] or r.get("month", "")
            if r.get("political_guess") and r.get("text") and len(r["text"]) > 200 and f"hist:{r.get('id', '')}" not in done:
                r["source"] = source
                r["id"] = hashlib.sha1(r["url"].encode()).hexdigest()
                by_cell.setdefault((source, month), []).append(r)
    out = []
    for cell in sorted(by_cell):
        pool = sorted(by_cell[cell], key=lambda r: r["id"])
        out += [_item("hist", r) for r in rng.sample(pool, min(per_cell, len(pool)))]
    return out


def prompt_hash(prompt: str) -> str:
    return hashlib.sha256(prompt.encode()).hexdigest()[:20]


def build(name: str, *args: str) -> None:
    makers = {"pilot90": items_pilot90, "pilot1000": items_pilot1000, "anchors": items_anchors,
              "swap": items_swap, "history": items_history, "live": items_live}
    items = makers[name](*args)
    if name == "live":
        name = f"live_{args[0].replace('-', '')}_{args[1].replace('-', '')}"
    d = OUT / name
    d.mkdir(parents=True, exist_ok=True)
    with open(d / "requests.jsonl", "w", encoding="utf-8") as req, open(d / "items.jsonl", "w", encoding="utf-8") as idx:
        for it in items:
            prompt = build_prompt(it["title"], it["text"])
            req.write(json.dumps({"request": {
                "contents": [{"role": "user", "parts": [{"text": prompt}]}],
                "generationConfig": {"temperature": 0, "maxOutputTokens": 1024, "responseMimeType": "application/json",
                                     "thinkingConfig": THINKING.get(MODEL, {"thinkingLevel": "MINIMAL"})},
                "labels": LABELS,
            }}, ensure_ascii=False) + "\n")
            idx.write(json.dumps({"hash": prompt_hash(prompt), "key": it["key"], "source": it["source"]}) + "\n")
    print(f"{len(items)} requests -> {d.relative_to(ROOT)}")


def submit(name: str) -> None:
    d = OUT / name
    if not subprocess.run(["gcloud", f"--configuration={GCLOUD_CONFIG}", "storage", "buckets", "describe", BUCKET],
                          capture_output=True).returncode == 0:
        gcloud("storage", "buckets", "create", BUCKET, f"--project={PROJECT}", f"--location={LOCATION}",
               "--uniform-bucket-level-access")
        gcloud("storage", "buckets", "update", BUCKET, "--update-labels=project=tw-media-lean")
    stamp = time.strftime("%Y%m%d-%H%M%S")
    src = f"{BUCKET}/{name}/{stamp}/requests.jsonl"
    gcloud("storage", "cp", str(d / "requests.jsonl"), src)
    body = {
        "displayName": f"tw-media-lean-{name}-{stamp}",
        "model": f"publishers/google/models/{MODEL}",
        "inputConfig": {"instancesFormat": "jsonl", "gcsSource": {"uris": [src]}},
        "outputConfig": {"predictionsFormat": "jsonl", "gcsDestination": {"outputUriPrefix": f"{BUCKET}/{name}/{stamp}/out"}},
        "labels": LABELS,
    }
    r = httpx.post(f"{API}/batchPredictionJobs", headers=headers(), json=body, timeout=60)
    if r.status_code != 200:
        sys.exit(f"submit failed {r.status_code}: {r.text[:500]}")
    job = r.json()
    (d / "job.json").write_text(json.dumps({"name": job["name"], "model": MODEL, "input": src}, indent=1))
    print("submitted", job["name"].split("/")[-1], job.get("state"))


def fetch(name: str) -> None:
    d = OUT / name
    job_name = json.loads((d / "job.json").read_text())["name"]
    while True:
        job = httpx.get(f"https://{HOST}/v1/{job_name}", headers=headers(), timeout=60).json()
        state = job.get("state")
        if state in ("JOB_STATE_SUCCEEDED", "JOB_STATE_FAILED", "JOB_STATE_CANCELLED", "JOB_STATE_PARTIALLY_SUCCEEDED"):
            break
        print(time.strftime("%H:%M"), state, flush=True)
        time.sleep(120)
    if state == "JOB_STATE_FAILED":
        sys.exit(f"job failed: {json.dumps(job.get('error'))[:500]}")
    out_dir = job["outputInfo"]["gcsOutputDirectory"]
    local = d / "out"
    local.mkdir(exist_ok=True)
    gcloud("storage", "cp", "-r", f"{out_dir}/*", str(local))
    index = {json.loads(line)["hash"]: json.loads(line) for line in open(d / "items.jsonl", encoding="utf-8")}
    tokens_in = tokens_out = ok = 0
    labels = []
    for f in local.rglob("*.jsonl"):
        for line in open(f, encoding="utf-8"):
            row = json.loads(line)
            it = index.get(prompt_hash(row["request"]["contents"][0]["parts"][0]["text"]))
            if not it:
                continue
            usage = row.get("response", {}).get("usageMetadata", {})
            tokens_in += usage.get("promptTokenCount", 0)
            tokens_out += usage.get("candidatesTokenCount", 0) + usage.get("thoughtsTokenCount", 0)
            try:
                text = row["response"]["candidates"][0]["content"]["parts"][0]["text"]
                label = parse(text)
            except (KeyError, IndexError):
                label = {"error": str(row.get("status"))[:200]}
            ok += bool(label and label.get("parties"))
            labels.append({"key": it["key"], "label": label, "codebook": CODEBOOK_VERSION, "model": MODEL})
    with open(ROOT / "data" / "annotations" / f"vertex_{MODEL}_{name}.jsonl", "w", encoding="utf-8") as f:
        f.writelines(json.dumps(x, ensure_ascii=False) + "\n" for x in labels)
    p_in, p_out = PRICE[MODEL]
    cost = tokens_in / 1e6 * p_in + tokens_out / 1e6 * p_out
    summary = {"set": name, "model": MODEL, "state": state, "requests": len(index), "parsed": ok,
               "tokens_in": tokens_in, "tokens_out": tokens_out, "est_cost_usd": round(cost, 4),
               "usd_per_item": round(cost / max(len(index), 1), 6)}
    (d / "summary.json").write_text(json.dumps(summary, indent=1))
    print(json.dumps(summary, indent=1))


if __name__ == "__main__":
    {"build": build, "submit": submit, "fetch": fetch}[sys.argv[1]](*sys.argv[2:])

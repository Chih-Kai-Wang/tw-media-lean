"""Prompt-sensitivity check (PLAN.md §D.4): the same articles under the original and a reworded prompt.

Reads each juror's labels on data/vertex/prompt_alt/ (scripts/vertex_batch.py build prompt_alt) and its labels on
the same articles with the original prompt, and writes docs/prompt-sensitivity.md: per-article agreement
(Krippendorff's alpha, ordinal), the mean shift, and the outlet ranking under each prompt.

    uv run python scripts/compare_prompts.py
"""

from __future__ import annotations

import json
from datetime import date
from pathlib import Path

import numpy as np
import yaml
from compare_jurors import ANN, ORIGIN, alpha, labels
from pilot_annotation import stance

ROOT = Path(__file__).resolve().parents[1]
JURORS = ["gemini-3.8-flash", "gpt-oss-120b-maas", "llama-4-maverick-17b-128e-instruct-maas"]
PARTIES = ("KMT", "DPP", "TPP")


def alt_labels(model: str) -> dict[str, dict]:
    f = ANN / f"vertex_{model}_prompt_alt.jsonl"
    return {json.loads(line)["key"]: json.loads(line).get("label") or {} for line in open(f, encoding="utf-8")} if f.exists() else {}


def main() -> None:
    src = {json.loads(line)["key"]: json.loads(line)["source"]
           for line in open(ROOT / "data" / "vertex" / "prompt_alt" / "items.jsonl", encoding="utf-8")}
    names = {k: v["name"] for k, v in yaml.safe_load((ROOT / "config" / "sources.yaml").read_text(encoding="utf-8"))["outlets"].items()}
    outlet = lambda k: names.get(src[k].split("_", 1)[1].removesuffix("_wb"), src[k])
    jurors = [m for m in JURORS if alt_labels(m)]
    L = [f"# 換提示詞測試\n\n日期：{date.today().isoformat()}　陪審員：" + "、".join(f"`{m}`（{ORIGIN.get(m, '?')}）" for m in jurors) + "\n",
         f"研究設計 D.4：換一種說法，結論不應改變。從陪審一致性測試的新聞中，每家媒體抽 50 篇（不足者全取），共 {len(src)} 篇。"
         "標註規則與輸出格式相同；改寫的提示詞換了措辭，政黨順序改為民進黨、民眾黨、國民黨，立場量尺由正到負描述"
         "（`src/twmedia/annotate.py` 的 `PROMPT_ALT_HEAD`）。文章內容與遮蔽方式完全相同。\n",
         "## 1. 逐篇一致性（新舊提示詞，Krippendorff's α，序位）與平均偏移\n",
         "偏移 = 改寫後平均分數 − 原提示詞平均分數（兩者都有分數的文章）。\n",
         "| 陪審員 | 政黨 | 篇數 | α | 偏移 |", "|---|---|---|---|---|"]
    gaps = {}
    for m in jurors:
        orig, alt = labels(m), alt_labels(m)
        keys = [k for k in src if orig.get(k, {}).get("parties") and alt.get(k, {}).get("parties")]
        for p in PARTIES:
            a = np.array([stance(orig[k], p) for k in keys])
            b = np.array([stance(alt[k], p) for k in keys])
            both = ~np.isnan(a) & ~np.isnan(b)
            L.append(f"| {m} | {p} | {both.sum()} | {alpha([a, b]):.2f} | {np.mean(b[both] - a[both]):+.2f} |")
        for tag, lab in (("原", orig), ("改", alt)):
            by = {}
            for k in keys:
                for p in ("KMT", "DPP"):
                    v = stance(lab[k], p)
                    if not np.isnan(v):
                        by.setdefault((outlet(k), p), []).append(v)
            ok = lambda o: all(len(by.get((o, p), [])) >= 10 for p in ("KMT", "DPP"))
            gaps[(m, tag)] = {o: np.mean(by[(o, "KMT")]) - np.mean(by[(o, "DPP")]) for o, _ in by if ok(o)}

    L += ["\n## 2. 各媒體排序\n",
          "國民黨平均分數 − 民進黨平均分數（每家每黨至少 10 篇；每家只有約 50 篇，數值本身不穩定，只看排序是否一致）。最後一列為同一位陪審員新舊提示詞的排名相關（Spearman ρ）。\n"]
    common = sorted(set.intersection(*(set(g) for g in gaps.values())), key=lambda o: gaps[(jurors[0], "原")][o])
    cols = [(m, t) for m in jurors for t in ("原", "改")]
    L += ["| 媒體 | " + " | ".join(f"{m}（{t}）" for m, t in cols) + " |", "|---" * (len(cols) + 1) + "|"]
    L += [f"| {o} | " + " | ".join(f"{gaps[c][o]:+.2f}" for c in cols) + " |" for o in common]
    rank = lambda v: np.argsort(np.argsort(v))
    rho = {m: np.corrcoef(rank([gaps[(m, "原")][o] for o in common]), rank([gaps[(m, "改")][o] for o in common]))[0, 1] for m in jurors}
    L.append("| ρ（新舊） | " + " | ".join(f"{rho[m]:.2f}" if t == "改" else "" for m, t in cols) + " |")
    L += ["\n## 判讀\n",
          "- **主要陪審員 Gemini 幾乎不受措辭影響**：逐篇 α 0.84–0.96，媒體排序 ρ 0.99，平均偏移不超過 0.1 分。"
          "正式結果以它的標籤為主（決策模型也是向它學習），所以這項檢驗主要回答的是：結論不是某一種提示詞寫法造成的",
          "- **兩個開源模型對措辭較敏感**：α 約 0.7–0.8，排序 ρ 0.81–0.85。這與不同模型之間的一致程度相近"
          "（[jury-agreement.md](jury-agreement.md)），所以它們的分數變動應視為陪審團不確定性的一部分",
          "- 偏移沒有一致方向：同一個政黨在不同陪審員下有正有負，看不出改寫系統性地偏向某一黨",
          "- 每家媒體只有約 50 篇，個別媒體的數值不穩定（例如公視在 Llama 4 下由負轉正）；這裡只用來檢驗排序與方向，媒體位置以大樣本結果為準"]
    (ROOT / "docs" / "prompt-sensitivity.md").write_text("\n".join(L) + "\n", encoding="utf-8")
    print("\n".join(L))


if __name__ == "__main__":
    main()

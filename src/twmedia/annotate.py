"""LLM annotation following docs/codebook.md.

Pilot use only through `opencode run` (OpenCode Go terms: coding-agent traffic; no bulk extraction).
Bulk annotation will go through Vertex AI batch prediction instead (PLAN.md §5.3).
PTT text (robots.txt ai-train=no) is never sent here.
"""

from __future__ import annotations

import json
import re
import subprocess
import tempfile
from functools import cache
from pathlib import Path

import yaml

CODEBOOK_VERSION = "0.1"
PARTIES = ("KMT", "DPP", "TPP")
MAX_CHARS = 3000

PROMPT = """你是政治傳播研究的標註員。請依照下列標註規則，判斷一篇台灣新聞文章如何呈現三個政黨。

政黨：KMT＝中國國民黨，DPP＝民主進步黨，TPP＝台灣民眾黨。
「提及某黨」包括：政黨名稱、黨職人員、該黨籍民選公職與候選人、該黨立法院黨團、該黨執政的政府（以執政黨身分被評論時）。

每篇文章：
- political：主題是否與台灣政治有關（true/false）
- genre：news（新聞報導）、opinion（評論社論）、press_release（政黨或政府新聞稿）、other
- topic：election、cross_strait、foreign_defense、economy、energy_environment、justice_scandal、legislature、social_welfare、other（單選）

每個政黨：
- mentioned：是否提及（true/false）
- stance：文章呈現該黨的方式。-2 強烈負面、-1 負面、0 中立或正負平衡、1 正面、2 強烈正面；未提及填 null
- salience：0 未提及、1 順帶一提、2 次要角色、3 主角
- quoted：是否直接引述該黨人士說法（true/false）

判斷原則：
1. 判斷的是文章怎麼呈現該黨，不是事件本身的好壞。平實陳述並給予回應空間，比帶情緒、只呈現單方說法的報導，stance 更接近 0。
2. 引述不等於立場：引述 A 黨批評 B 黨，但平衡呈現 B 黨回應時，B 黨 stance 偏向 0。
3. 只看文章本身。

只輸出一個 JSON 物件，不要其他文字：
{{"political": true, "genre": "news", "topic": "election",
  "parties": {{"KMT": {{"mentioned": true, "stance": 0, "salience": 2, "quoted": false}},
              "DPP": {{"mentioned": false, "stance": null, "salience": 0, "quoted": false}},
              "TPP": {{"mentioned": false, "stance": null, "salience": 0, "quoted": false}}}}}}

標題：{title}

內文：
{text}
"""

# Same codebook and output format, reworded, with the parties and the stance scale in the opposite order. For the
# prompt-sensitivity check (PLAN.md §D.4): conclusions should not depend on the wording. Not used for labelling.
PROMPT_ALT_HEAD = """請以媒體研究者的角度閱讀下面這篇台灣新聞，依照固定的編碼規則，記錄文章對三個政黨的呈現方式。

三個政黨的代號：DPP 是民主進步黨，TPP 是台灣民眾黨，KMT 是中國國民黨。
以下都算「提及」該黨：黨名、黨職人員、該黨的民選公職或候選人、該黨的立法院黨團，以及以執政黨身分被評論的該黨政府。

整篇文章要記錄：
- political：內容是否和台灣政治相關，填 true 或 false
- genre：opinion（評論、社論）、news（新聞報導）、press_release（政黨或政府的新聞稿）、other，四選一
- topic：從 election、cross_strait、foreign_defense、economy、energy_environment、justice_scandal、legislature、social_welfare、other 中選一個

每個政黨要記錄：
- mentioned：文章有沒有提到這個黨，填 true 或 false
- stance：文章把這個黨呈現得多正面或多負面。2 非常正面、1 正面、0 中立或正負相抵、-1 負面、-2 非常負面；沒提到就填 null
- salience：3 主角、2 次要角色、1 只是順帶提到、0 沒提到
- quoted：文章有沒有直接引用這個黨的人說的話，填 true 或 false

注意：
1. 要記錄的是文章如何呈現該黨，不是事件本身是好是壞。語氣平實、也讓對方有回應空間的報導，比情緒化或只有單方說法的報導更接近 0。
2. 有引述不代表有立場：文章引述甲黨批評乙黨，但也平衡呈現乙黨的回應，乙黨的 stance 就應接近 0。
3. 只根據這篇文章本身判斷。

請只輸出一個 JSON 物件，不要加任何說明：
{"political": true, "genre": "news", "topic": "election",
  "parties": {"DPP": {"mentioned": true, "stance": 0, "salience": 2, "quoted": false},
              "TPP": {"mentioned": false, "stance": null, "salience": 0, "quoted": false},
              "KMT": {"mentioned": false, "stance": null, "salience": 0, "quoted": false}}}

"""

OUTLET_NAMES = re.compile(
    r"中央社|中央通訊社|自由時報|聯合報|聯合新聞網|中國時報|中時新聞網|ETtoday|東森|TVBS|三立|SETN|民視|公視|風傳媒|鏡週刊|鏡新聞"
)
_PAIRS = [("中國國民黨", "民主進步黨"), ("國民黨", "民進黨"), ("藍營", "綠營"), ("泛藍", "泛綠"), ("藍委", "綠委"),
          ("藍軍", "綠軍"), ("KMT", "DPP")]
SWAP = {a: b for a, b in _PAIRS} | {b: a for a, b in _PAIRS}
ROSTER = Path(__file__).resolve().parents[2] / "config" / "politicians.yaml"
PARTY_ZH = {"KMT": "國民黨", "DPP": "民進黨", "TPP": "民眾黨"}
ORDINALS = "甲乙丙丁戊己庚辛壬癸"


def mask_outlets(text: str) -> str:
    """Codebook rule 3: the annotator must not see which outlet wrote the piece."""
    return OUTLET_NAMES.sub("【媒體】", text)


@cache
def _roster() -> tuple[dict[str, str], re.Pattern]:
    people = yaml.safe_load(ROSTER.read_text(encoding="utf-8"))["people"]
    return people, re.compile("|".join(map(re.escape, sorted(people, key=len, reverse=True))))


def mask_people(*texts: str) -> list[str]:
    """Replace known politicians' names with party-labelled placeholders (「國民黨籍人士甲」).

    Names reveal party as surely as party names do, so the swap test masks them first; the label inside the
    placeholder then flips with swap_parties. One numbering is shared across all texts (title and body).
    """
    people, pattern = _roster()
    seen: dict[str, str] = {}
    counts: dict[str, int] = {}

    def repl(m: re.Match) -> str:
        name = m.group(0)
        if name not in seen:
            party = people[name]
            i = counts.get(party, 0)
            counts[party] = i + 1
            seen[name] = f"{PARTY_ZH[party]}籍人士{ORDINALS[i] if i < len(ORDINALS) else i + 1}"
        return seen[name]

    return [pattern.sub(repl, t) for t in texts]


def swap_parties(text: str) -> str:
    """Counterfactual for the party-swap test: exchange KMT and DPP labels. Mask people's names first."""
    keys = sorted(SWAP, key=len, reverse=True)
    return re.sub("|".join(map(re.escape, keys)), lambda m: SWAP[m.group(0)], text)


def build_prompt(title: str, text: str) -> str:
    return PROMPT.format(title=mask_outlets(title or ""), text=mask_outlets((text or "")[:MAX_CHARS]))


def parse(output: str) -> dict | None:
    m = re.search(r"\{.*\}", output, re.S)
    if not m:
        return None
    try:
        d = json.loads(m.group(0))
    except json.JSONDecodeError:
        return None
    if not isinstance(d.get("parties"), dict) or not all(p in d["parties"] for p in PARTIES):
        return None
    return d


def annotate(model: str, title: str, text: str, timeout: int = 180) -> dict | None:
    """One article, one model, via the read-only `plan` agent in an empty directory."""
    with tempfile.TemporaryDirectory() as empty:
        out = subprocess.run(
            ["opencode", "run", "-m", model, "--agent", "plan", "--pure", build_prompt(title, text)],
            capture_output=True, text=True, timeout=timeout, cwd=empty,
        ).stdout
    return parse(out)

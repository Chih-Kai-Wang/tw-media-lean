"""Build config/politicians.yaml: politician name -> party, for masking names in the party-swap test.

Source: legislators of terms 8-11 (2012-2026) from openfun/tw-ly-legislator (CC BY 4.0), downloaded to
data/external/ly/, plus a short hand-kept list of non-legislator figures (EXTRA), plus 2026 candidates mined from collected news
by fixed patterns like 「國民黨新北市長候選人李四川」 (kept only with >= 3 mentions, >= 90% with one party and a
common surname). A legislator who changed party keeps the party of their latest term. Usage: uv run python scripts/build_roster.py
"""

from __future__ import annotations

import glob
import json
import re
from collections import Counter, defaultdict
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[1]
PARTY = {"中國國民黨": "KMT", "民主進步黨": "DPP", "台灣民眾黨": "TPP"}
CJK_HEAD = re.compile(r"^[\u4e00-\u9fff]+")
SKIP = {"黃仁"}  # prefix of 黃仁勳; masking it would hit far more non-political text than it fixes
# party heads, presidents, premiers, mayors and candidates who were not legislators in terms 8-11
EXTRA = {
    "KMT": ["馬英九", "朱立倫", "鄭麗文", "盧秀燕", "蔣萬安", "侯友宜", "吳敦義", "洪秀柱", "連勝文", "張善政", "謝國樑", "郝龍斌", "趙少康"],
    "DPP": ["蔡英文", "陳水扁", "蕭美琴", "卓榮泰", "陳建仁", "蘇貞昌", "林佳龍", "鄭文燦", "陳其邁", "黃偉哲", "林右昌", "賴清德"],
    "TPP": ["柯文哲"],
}
CANDIDATE = re.compile(
    r"(國民黨|民進黨|民眾黨)籍?[\u4e00-\u9fff]{0,6}?(?:市長|縣長|議員|立委|里長|鄉長|鎮長)?(?:參選人|候選人|提名人)([\u4e00-\u9fff]{3})"
)
SHORT = {"國民黨": "KMT", "民進黨": "DPP", "民眾黨": "TPP"}
SURNAMES = set(
    "陳林黃張李王吳劉蔡楊許鄭謝郭洪曾邱廖賴周徐蘇葉莊呂江何蕭羅高潘簡朱鍾游彭詹胡施沈余盧梁趙顏柯翁魏孫戴范方宋鄧杜"
    "傅侯曹薛丁卓阮馬董温溫唐藍蔣石古紀姚連馮歐程湯黃田康姜白汪鄒尤巫鐘黎涂龔嚴韓袁金童陸夏柳邵錢伍倪溫于譚駱熊任甘秦顧毛章史官萬俞雷粘饒"
)
LEFT = ["高虹安"]  # left their legislator-era party after their last term in the data (2024)


def main() -> None:
    roster: dict[str, str] = {}
    for term in ("08", "09", "10", "11"):
        for line in open(ROOT / "data" / "external" / "ly" / f"legislator-{term}.jsonl", encoding="utf-8"):
            r = json.loads(line)
            party = PARTY.get(r.get("黨籍"))
            # indigenous names come as "伍麗華Saidhai‧Tahovecahe": keep the Chinese part, which news uses
            name = CJK_HEAD.match(r["委員姓名"].strip()).group(0)
            if name in SKIP:
                continue
            if party:
                roster[name] = party
            else:
                roster.pop(name, None)  # left the three parties by their latest term
    for party, names in EXTRA.items():
        roster.update({n: party for n in names})
    mentions: dict[str, Counter] = defaultdict(Counter)
    for f in glob.glob(str(ROOT / "data" / "raw" / "news_*" / "*.jsonl")):
        for line in open(f, encoding="utf-8"):
            for party, name in CANDIDATE.findall(json.loads(line).get("text") or ""):
                mentions[name][SHORT[party]] += 1
    mined = 0
    for name, c in mentions.items():
        party, n = c.most_common(1)[0]
        if name[0] in SURNAMES and n >= 3 and n / sum(c.values()) >= 0.9 and name not in roster:
            roster[name] = party
            mined += 1
    print(f"{mined} candidates mined from news")
    for name in LEFT:
        roster.pop(name, None)
    out = {
        "source": "openfun/tw-ly-legislator terms 8-11 (CC BY 4.0) + scripts/build_roster.py EXTRA",
        "people": dict(sorted(roster.items())),
    }
    path = ROOT / "config" / "politicians.yaml"
    path.write_text(yaml.safe_dump(out, allow_unicode=True, sort_keys=False), encoding="utf-8")
    counts = {p: sum(v == p for v in roster.values()) for p in PARTY.values()}
    print(f"{len(roster)} people -> {path.relative_to(ROOT)} {counts}")


if __name__ == "__main__":
    main()

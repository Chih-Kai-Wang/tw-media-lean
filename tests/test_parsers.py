import httpx

from twmedia.collectors.line_today import parse_tab
from twmedia.collectors.news import parse_sitemap
from twmedia.collectors.ptt import parse_index, parse_post
from twmedia.http import _is_challenge
from twmedia.store import Store, pseudonymize

NEWS_SITEMAP = """<?xml version="1.0" encoding="UTF-8"?>
<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9"
        xmlns:news="http://www.google.com/schemas/sitemap-news/0.9">
  <url>
    <loc>https://example.tw/news/1</loc>
    <news:news>
      <news:publication_date>2026-11-01T08:00:00+08:00</news:publication_date>
      <news:title>測試標題</news:title>
      <news:keywords>國民黨, 民進黨</news:keywords>
    </news:news>
  </url>
</urlset>""".encode()

SITEMAP_INDEX = b"""<?xml version="1.0" encoding="UTF-8"?>
<sitemapindex xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">
  <sitemap><loc>https://example.tw/old.xml</loc><lastmod>2026-10-01</lastmod></sitemap>
  <sitemap><loc>https://example.tw/new.xml</loc><lastmod>2026-11-01</lastmod></sitemap>
</sitemapindex>"""

PTT_INDEX = """<html><body>
<div class="btn-group btn-group-paging">
  <a class="btn wide" href="/bbs/HatePolitics/index4000.html">&lsaquo; 上頁</a>
</div>
<div class="r-ent"><div class="title"><a href="/bbs/HatePolitics/M.1.A.ABC.html">[討論] 測試</a></div></div>
<div class="r-ent"><div class="title">(本文已被刪除)</div></div>
</body></html>"""

PTT_POST = """<html><body><div id="main-content">
<div class="article-metaline"><span class="article-meta-tag">作者</span><span class="article-meta-value">someone (暱稱)</span></div>
<div class="article-metaline"><span class="article-meta-tag">標題</span><span class="article-meta-value">[討論] 測試</span></div>
<div class="article-metaline"><span class="article-meta-tag">時間</span><span class="article-meta-value">Sun Nov  1 01:33:42 2026</span></div>
內文第一行
--
※ 發信站: 批踢踢實業坊(ptt.cc)
<div class="push"><span class="push-tag">推 </span><span class="push-userid">alice</span><span class="push-content">: 同意</span></div>
<div class="push"><span class="push-tag">噓 </span><span class="push-userid">bob</span><span class="push-content">: 不同意</span></div>
</div></body></html>"""


def test_news_sitemap():
    items, children = parse_sitemap(NEWS_SITEMAP)
    assert children == []
    assert items[0].url == "https://example.tw/news/1"
    assert items[0].title == "測試標題"
    assert items[0].keywords == ["國民黨", "民進黨"]


def test_sitemap_index_newest_first():
    items, children = parse_sitemap(SITEMAP_INDEX)
    assert items == []
    assert children == ["https://example.tw/new.xml", "https://example.tw/old.xml"]


def test_ptt_index_skips_deleted_and_finds_prev():
    posts, prev = parse_index(PTT_INDEX)
    assert [p["title"] for p in posts] == ["[討論] 測試"]
    assert prev == "https://www.ptt.cc/bbs/HatePolitics/index4000.html"


def test_ptt_post_pseudonymizes_users():
    rec = parse_post(PTT_POST)
    assert rec["title"] == "[討論] 測試"
    assert rec["author"] == pseudonymize("someone")
    assert "someone" not in str(rec) and "alice" not in str(rec)
    assert rec["push_counts"] == {"推": 1, "噓": 1}
    assert rec["text"].startswith("內文第一行")


def test_challenge_detection():
    page = httpx.Response(200, headers={"content-type": "text/html"}, text="<title>Just a moment...</title>")
    assert _is_challenge(page)
    assert not _is_challenge(httpx.Response(200, headers={"content-type": "text/html"}, text="<p>ok</p>"))


def test_store_saves_once(tmp_path):
    store = Store(tmp_path)
    assert store.save("src", "1", {"x": 1})
    assert not store.save("src", "1", {"x": 2})
    assert store.is_seen("src", "1")
    assert store.counts()[0][:2] == ("src", 1)


def test_line_today_tab():
    data = {"props": {"pageProps": {"fallback": {
        "getTabsData": {"modules": []},
        "abc_{\"offset\":0}": [
            {"id": "1", "title": "標題", "publisher": "中央通訊社", "publishTimeUnix": 1793449260000, "url": {"hash": "xyz"}}
        ],
    }}}}
    import json
    page = '<script id="__NEXT_DATA__" type="application/json">' + json.dumps(data, ensure_ascii=False) + "</script>"
    items = parse_tab(page)
    assert len(items) == 1
    assert items[0]["publisher"] == "中央通訊社"
    assert items[0]["url"] == "https://today.line.me/tw/v2/article/xyz"
    assert items[0]["published"].startswith("2026-")


def test_id_candidates_walk_down_from_newest():
    from twmedia.collectors.news import Candidate, id_candidates

    cfg = {"id_url": "https://example.tw/media/contents/{}"}
    newest = [Candidate(url="https://example.tw/media/contents/3"), Candidate(url="https://example.tw/other/9")]
    assert [c.url for c in id_candidates(cfg, newest)] == [
        "https://example.tw/media/contents/3",
        "https://example.tw/media/contents/2",
        "https://example.tw/media/contents/1",
    ]


def test_threads_record_hashes_ordinary_users():
    from twmedia.collectors.threads import to_record

    rec = to_record({"id": "1", "text": "t", "username": "someone"}, {"cna_tw"}, {"keyword": "x"})
    assert rec["username"] is None and rec["user_hash"] == pseudonymize("someone")
    rec = to_record({"id": "2", "text": "t", "username": "cna_tw"}, {"cna_tw"}, {"keyword": "x"})
    assert rec["username"] == "cna_tw"


def test_errors_never_include_query_strings(monkeypatch):
    import pytest
    from twmedia.http import Disallowed, PoliteClient

    client = PoliteClient(min_interval=0)
    rp = type("RP", (), {"can_fetch": lambda self, a, u: False})()
    monkeypatch.setattr(client, "_robots_for", lambda scheme, host: rp)
    with pytest.raises(Disallowed) as e:
        client.get("https://api.example.com/v1/me?access_token=SECRET123")
    assert "SECRET123" not in str(e.value)


def test_mask_then_swap_flips_labels_consistently():
    from twmedia.annotate import mask_people, swap_parties

    title, body = mask_people("賴清德批國民黨", "中國國民黨主席鄭麗文回應賴清德")
    assert "賴清德" not in title + body and "鄭麗文" not in body
    assert title.startswith("民進黨籍人士甲") and body.endswith("民進黨籍人士甲")  # one numbering across texts
    swapped = swap_parties(body)
    assert swapped == "民主進步黨主席民進黨籍人士甲回應國民黨籍人士甲"
    assert swap_parties(swapped) == body  # the swap is its own inverse


def test_history_id_interpolation_and_months():
    from twmedia.collectors.history import interpolate_ids, months

    assert months("2012-11", "2013-02") == ["2012-11", "2012-12", "2013-01", "2013-02"]
    anchors = [["2012-01", 1000], ["2013-01", 13000]]
    lo, hi = interpolate_ids(anchors, "2012-01")
    assert lo == 1000 and 1900 < hi < 2100  # about 1000 IDs a month
    lo2, _ = interpolate_ids(anchors, "2012-02")
    assert lo2 == hi
    assert interpolate_ids(anchors, "2014-01")[0] > 13000  # extrapolates past the last anchor


def test_history_date_seq_candidates_stay_in_month():
    import random

    from twmedia.collectors.history import Sampler

    cfg = {"method": "date_seq", "template": "https://x.test/aipl/{date:%Y%m%d}{seq:04d}.aspx", "seq_max": 500}
    urls = Sampler(cfg, None, random.Random(0)).candidates("2016-02", 50)
    assert len(urls) == 50 and all("/aipl/201602" in u for u, _, _ in urls)


def test_history_observed_ids_correct_the_anchors():
    import random

    from twmedia.collectors.history import Sampler

    cfg = {"method": "id_range", "template": "https://x.test/{id}", "anchors": [["2016-01", 0], ["2017-01", 12000]]}
    s = Sampler(cfg, None, random.Random(0))
    s.observe(0, 9000, "2016-03-01T08:00:00")  # the outlet published far more early in the year than assumed
    s.observe(0, 9500, "2016-04-01T08:00:00")
    ids = [n for _, _, n in s.candidates("2016-03", 20)]
    assert all(9000 <= n < 9500 for n in ids)

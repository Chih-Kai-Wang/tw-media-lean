# 歷史新聞（2012–2015）Wayback 可回收量調查

調查日期：2026-11-01（第二輪 2026-11-02）。程式：`scripts/cdx_survey.py`；原始 CDX 回應與統計：`data/history_survey/`。

> **更正（2026-11-02）**：中央社的 `aopl` 是「國際」（國內政治是 `aipl`，`acn` 是兩岸），所以下表中央社的數字應讀為「政治＋國際」。實際的歷史回補改用 `twmedia history`，見 [collection-status.md](collection-status.md) 與 [archive-url-schemes.md](archive-url-schemes.md)。

本文件為早期調查，各媒體網址結構與抽樣方法已由 [archive-url-schemes.md](archive-url-schemes.md) 取代；此處保留實測數字。調查期間 Internet Archive CDX 極不穩定（大量 504 與 `Temporarily Offline`），11 家中僅 4 家取得部分數字；「未量到」不等於沒有存檔，所有數字均為抽樣月份的下限或估計。

## 方法

- 端點 `https://web.archive.org/cdx/search/cdx`：`output=json`、`fl=timestamp,original,statuscode,mimetype`、`filter=statuscode:200`、`collapse=urlkey`、`matchType=prefix`、`limit=5000`（第二輪 probe 為 300）。
- 每年只抽 3 月（`from=YYYY0301&to=YYYY0331`），以月計數 × 12 推估全年；3 月無事件偏誤的假設未驗證（2014-03 有太陽花運動）。
- 以 URL 前綴縮小範圍，再以正則挑出文章頁、排除首頁與分類頁，要求 `mimetype` 含 html；計數為 `urlkey` 去重後的網址數。
- UA `twmedia-research/0.1 (+https://github.com/Chih-Kai-Wang)`；全域每 2 秒最多啟動 1 個請求；429／5xx／逾時退避重試至多 3 次（8、16、32 秒）。
- 抽驗：每家取 2012 與 2015 各一篇（風傳媒 2014／2015），以 `https://web.archive.org/web/<timestamp>id_/<url>` 取得，trafilatura 擷取，內文 >200 字元且中文字 >100 為通過。

## 文章網址型態（調查當時）

| 媒體 | 前綴／正則（精簡） | 備註 |
|---|---|---|
| 中央社 | `cna.com.tw/news/{aall,aipl,aopl}/YYYYMM…`，`/news/<cat>/\d{12}` | 存檔網址大小寫混用（如 `/News/aALL/`）、含 `:80`、有 `www3`；`aall` 只在 2012 有文章 |
| 自由時報 | `libertytimes.com.tw/YYYY/new/<mon>/<d>/today-*.htm`；`news.ltn.com.tw/news/politics/(paper\|breakingnews)/\d+` | 2012–2014 為 libertytimes 舊版；`iservice.ltn.com.tw` 只命中廣告端點，已排除 |
| 聯合報 | `udn.com/NEWS/<CAT>/<SUB>/<id>.shtml`；`udn.com/news/story/<n>/<id>` | 全數 504 |
| 中國時報 | `chinatimes.com/newspapers/YYYYMMDD…`、`/realtimenews/YYYYMMDD…` | 2012–2013 回 0，很可能是網址型態不對 |
| ETtoday | `ettoday.net/news/YYYYMMDD/<id>.htm` | 日期在網址內，前綴最精準 |
| TVBS | `news.tvbs.com.tw/{politics,entry}/<id>` | 僅 2015 的 `entry` 有結果 |
| 三立 | `setn.com/News.aspx?NewsID=<id>` | 全數 504 |
| 民視 | `ftvnews.com.tw/…`（舊站可能為 `ftvn.com.tw`） | 全數 504，型態未確認 |
| 東森 | `news.ebc.net.tw/news.php?nid=<id>` | 回 0，型態可能不對 |
| 公視 | `news.pts.org.tw/detail.php?NEWS_ID=<id>` | 回 0，型態可能不對或存檔很少 |
| 風傳媒 | `storm.mg/article/<id>` | 2014 起；全數 504 |

## 估計文章數（3 月抽樣網址數）

格式：`3 月實測數 → 年推估`。「≥」為被 `limit` 截斷的下限；「未量到」為查詢 504／離線，數量未知；「0*」為查詢成功但回 0，多半是網址型態問題。

| 媒體 | 2012 | 2013 | 2014 | 2015 |
|---|---|---|---|---|
| 中央社（僅抽到的類別） | aall 709＋aipl 364＋aopl ≥300 → 約 ≥1,370／月（估） | aipl 490＋aopl 639 = 1,129／月 → 約 13,500／年 | aipl 1,174＋aopl 1,312 = 2,486／月 → 約 29,800／年 | aipl 525＋aopl 946 = 1,471／月 → 約 17,700／年 |
| 自由時報 | ≥2,812／月（libertytimes，截斷）→ ≥33,700／年 | ≥2,873／月 → ≥34,500／年 | ≥2,975／月 → ≥35,700／年 | 政治類 ≥300／月（probe，截斷）；libertytimes 0 |
| 聯合報 | 未量到 | 未量到 | 未量到 | 未量到 |
| 中國時報 | 0* | 0* | ≥5,000＋≥5,000／月（截斷） | ≥5,000＋≥5,000／月（第二輪，截斷） |
| ETtoday | ≥4,990／月 → ≥59,900／年 | ≥4,999／月 → ≥60,000／年 | ≥4,996／月 → ≥60,000／年 | ≥300／月（probe，截斷） |
| TVBS | 0* | 未量到 | 未量到 | 2,505／月（entry，第二輪）→ 約 30,000／年 |
| 三立 | 未量到 | 未量到 | 未量到 | 未量到 |
| 民視 | 未量到 | 未量到 | 未量到 | 未量到 |
| 東森 | 0* | 0* | 未量到 | 0* |
| 公視 | 0* | 0* | 未量到 | 0* |
| 風傳媒 | 不適用 | 不適用 | 未量到 | 未量到 |

年推估假設其他月份與 3 月相當；截斷值上限未知，ETtoday、自由時報舊站與中國時報 2014 實際可能遠高於表中數字。

## 抽驗（trafilatura）

| 媒體 | 2012 | 2015 | 說明 |
|---|---|---|---|
| 中央社 | 通過（324 字） | 通過（508 字） | 稿頭有少量雜訊（時間戳、字級） |
| 自由時報 | 通過（924 字） | 失敗 | 2012 舊版頁首混入選單文字，需指定 selector；2015 樣本因正則過鬆抽到廣告端點，不代表文章頁無法擷取 |
| ETtoday | 通過（560 字） | 無樣本 | |
| 中國時報 | 無樣本 | 通過（1,798 字） | 第二輪 |
| TVBS | 無樣本 | 通過（547 字） | 第二輪 |
| 其餘 6 家 | 無樣本 | 無樣本 | 無可用 CDX 列 |

## 限制

1. 寬前綴查詢幾乎一律 504，單次請求 15–60 秒，與限速無關；IA 穩定時重跑可能改善（快取已保存，重跑只補缺）。
2. 每年僅量 3 月，季節與事件偏誤未校正。
3. 截斷格只是下限；probe 只能說明「至少 300」。
4. CDX 會低估：`collapse=urlkey` 且只計 200 回應，漏掉 301／302 與帶追蹤參數的網址；Wayback 亦非全站爬取。存檔網址數不等於實際發稿量。
5. 中國時報 2012–2013、TVBS 2012、東森、公視的 0 很可能是型態猜錯；中央社 `aall` 以外類別、自由時報其他子站未納入。
6. 未做政治類別判定，政治文章數須在回補階段另行篩選。

## 結論

中央社（2012–2015）、ETtoday（2012–2014）、自由時報舊版（2012–2014）、中國時報（2014–2015）每月存檔至少數百到數千個網址，足以支撐每月約 300 篇的抽樣。其餘媒體在本調查中無法判斷；後續做法見 [archive-url-schemes.md](archive-url-schemes.md)，Wayback 取不到時的替代來源包括 Common Crawl（2012–2015 索引可查）、圖書館與商業新聞資料庫（聯合報、中國時報、自由時報）及 GDELT（2015-02 起）。

# 資料收集狀態

最後實測：2026-11-01。所有請求都使用誠實的 User-Agent（`twmedia-research/0.1`），先檢查 robots.txt，每日收集時同一網站每 2 秒最多一次請求；遇到 403、429 或機器人驗證頁就停止該來源，不繞過。

## 新聞網站

| 來源 | 取得方式 | 狀態 |
|---|---|---|
| 中央社 | Google 新聞 sitemap | 可用 |
| 自由時報 | sitemap | 可用 |
| 聯合報 | sitemap 索引 | 可用 |
| 中國時報 | sitemap | 可用 |
| ETtoday | sitemap | 可用 |
| TVBS | sitemap | 可用 |
| 三立 | sitemap | 可用 |
| 民視 | 首頁連結 | 可用。robots.txt 無法讀取（回傳 Cloudflare 403），依一般慣例視為沒有限制；RSS 回傳 403，不使用 |
| 東森 | sitemap | 可用 |
| 公視 | sitemap | 可用 |
| 風傳媒 | sitemap 索引 | 可用；頁面會附上相關文章摘要，以 `#editorWrapper` 限定內文範圍（`extractor_version: 2` 起）。11/01 最早收的約 40 筆仍夾雜相關文章 |
| 鏡週刊 | sitemap | 可用 |
| Yahoo奇摩新聞 | sitemap 索引 | 可用（轉載多家媒體）；頁面會無限捲動載入其他新聞，只取第一個 `<article>`（`extractor_version: 2` 起） |

sitemap 只列最近一兩天的文章，所以每小時跑一次。

## 歷史回補（2012–2026，11/02 上線）

`twmedia history <媒體>`（`src/twmedia/collectors/history.py`）：每家媒體每月隨機抽政治新聞，目標 300 篇；各月份輪流抽，中途停止時各月仍平均分布，進度存在 `data/state.sqlite`，重跑會接續。每個網站每秒至多一個請求，Internet Archive 每 5 秒一個。網址結構調查見 [archive-url-schemes.md](archive-url-schemes.md)。

| 媒體 | 來源 | 期間 | 政治判定 |
|---|---|---|---|
| 中央社 | 自家網站（日期＋流水號）；2014-07 以前用 Wayback | 2012– | `og:url` 類別 `aipl`；Wayback 用網址 |
| 自由時報 | 自家網站（報紙版、即時兩條 ID）；網站拒絕雲端機房 IP，改從一般網路連線抽樣 | 2012– | 請求 `/news/politics/` 沒被轉走 |
| 聯合報 | Wayback（政治版 `story/6656`）；2015 年以前的 `/NEWS/` 被聯合報 robots.txt 禁止，不抓 | 2015– | 網址 |
| 中國時報 | 自家網站的時序 sitemap（到 2025-06）；之後用日期＋流水號 | 2012– | 版別 `260407`、頁面類別；2012–2013 只有報紙版，用關鍵詞 |
| ETtoday、TVBS | 自家網站（全站流水號） | 2012– | `article:section` |
| 三立 | 自家網站 | 2013-10– | `articleSection`、標題 |
| 民視 | 自家網站（`sno` 編碼，P 字頭），2019 年起；2012–2017 用 Wayback；2018 年尚無樣本 | 2012– | 頁面類別＋關鍵詞 |
| 東森 | 自家網站 | 2018-03– | `/news/politics/` 只對政治文章有效 |
| 公視 | 自家網站 | 2012– | 頁面類別＋關鍵詞（舊文類別常缺） |
| 風傳媒 | 自家網站的每月 sitemap | 2014– | 麵包屑 `/channel/7` |
| 鏡週刊 | Wayback | 2016– | 頁面裡的類別 `political` |

ID 型的媒體：設定檔裡的「ID↔日期」錨點只是起點，每抓到一篇就記下它的 ID 和發布日，之後的抽樣用這些實測點修正 ID 範圍；抽到別的月份的政治文章，算進它實際發布的月份。

各家「政治新聞」的判定方式不同（有的看網站分類，有的用關鍵詞），所以抽樣框不完全一致；最後是否為政治新聞，一律由 LLM 標註與決策模型重新判斷（codebook 的 `political` 欄位）。

## 社群與討論平台

| 來源 | 狀態 | 說明 |
|---|---|---|
| YouTube | 可用（11/01 起） | 頻道 RSS（`/feeds/videos.xml`）被 YouTube 的 robots.txt 禁止，改用官方 Data API v3。12 家媒體的頻道 ID 已從各家官網連結取得並核對頻道名稱 |
| PTT | 可用 | HatePolitics、Gossiping。robots.txt 標示 `ai-train=no`：**PTT 文字不得用於訓練或微調模型**，每筆紀錄都標 `usage: no-ai-train`。帳號已雜湊 |
| Dcard | **被擋** | 公開 API 與頁面都回傳 Cloudflare 驗證頁（403）。依原則不繞過；改寫信向 Dcard 申請研究用資料 |
| Facebook 公開粉專 | **不可行** | 未登入只看到登入牆，頁面沒有貼文內容。依原則不登入、不繞過 |
| LINE TODAY | 可用（部分） | 每小時記錄「焦點」「國內」兩個分頁第一屏的新聞（約 5–10 則）：哪家媒體、排第幾。只有伺服器端產生的第一屏可讀，其餘由前端載入，不另外呼叫內部 API。「2026 選舉」專題頁第一屏沒有資料，暫不收 |
| Threads | 卡在商家驗證 | 已建立 Meta 應用程式並以 OAuth 取得含 `threads_keyword_search`、`threads_profile_discovery` 的 60 天權杖（11/01）。標準權限下：關鍵字搜尋只搜得到授權者自己的貼文，公開帳號只能讀 Meta 官方帳號。要讀公開資料須提交應用程式審查，而提交審查要先成為「技術供應商」，前提是完成 Meta 商家驗證（須為登記的商業實體，且不可撤回）。個人學生目前無法完成，待決定替代方案。11/01 評估「不登入讀公開頁」：threads.com 的 robots.txt 對所有爬蟲 `Disallow: /`，並註明未經書面許可禁止自動收集，違反本專案「遵守 robots.txt」原則，不採用 |
| Instagram | 待準備 | Business Discovery 需要一個 IG 專業帳號並連結 Facebook 粉專 |
| Meta 廣告檔案庫 | 待準備 | Ad Library API 需要先完成 Meta 的身分驗證（上傳證件），須本人操作 |
| TikTok | 待合作 | Research API 僅開放美國、歐洲研究者 |

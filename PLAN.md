# 研究設計

以公開、可重現的方法，量化台灣主要媒體在不同時期如何呈現國民黨、民進黨與民眾黨，給出附不確定區間的分數與時間軸，並對照公開的資金資料。

產出：技術報告（arXiv）、Hugging Face 上的資料集與模型、一個說明方法與限制的公開網站。

## 範圍

| 項目 | 範圍 |
|---|---|
| 即時觀測 | 2026 年九合一選舉（投票日 11/28），觀測至 12/28 |
| 歷史 | 2012–2026，涵蓋 2016 年政黨輪替 |
| 新聞媒體 | 中央社、自由時報、聯合報、中國時報、ETtoday、TVBS、三立、民視、東森、公視、風傳媒、鏡週刊、中天（2026-11-12 加入） |
| 平台 | YouTube、PTT、LINE TODAY、Yahoo 奇摩新聞；Threads、Dcard、Facebook、Instagram、TikTok 視取得管道而定 |

平台依路透新聞學研究所《數位新聞報告》台灣篇選定：台灣民眾每週用來看新聞的主要平台都納入。

## 測量什麼

對每個「媒體 × 月」、每個政黨分別估計：

- **立場**：報導呈現該黨的方式，從 −2（強烈負面）到 +2（強烈正面）
- **份量**：是否提及、是主角還是順帶一提
- **消息來源**：是否直接引述該黨人士
- **用語**：用詞較接近哪一黨的立委

三黨分開估計，不壓成單一的藍綠分數。標註規則見 [docs/codebook.md](docs/codebook.md)。

## 資料

**新聞網站。** 選舉期間每小時收集各家新聞網站的最新文章。歷史資料採分層抽樣：每家媒體每月隨機抽取固定數量（目標 300 篇）的政治新聞，來源依序為媒體自家網站與 Internet Archive。各家網址結構與可回溯年份見 [docs/archive-url-schemes.md](docs/archive-url-schemes.md)，收集狀態見 [docs/collection-status.md](docs/collection-status.md)。

**社群與討論平台。** 媒體的官方帳號（機構帳號）與一般使用者的討論分開分析。YouTube 使用官方 Data API；PTT 讀取公開看板；LINE TODAY 與 Yahoo 奇摩新聞記錄各家新聞的曝光。Threads、Facebook、Instagram、TikTok 與 Dcard 需要平台授權或研究合作，取得前不納入。

**參照文本。** 立法院質詢逐字稿與書面質詢（g0v／openfun 整理之開放資料）、兩大黨官網新聞稿，用作用語基準與已知立場的驗證錨點。

**資金資料。** 政府採購決標、政治獻金、政策宣導支出與所有權變動，見 [docs/money-sources.md](docs/money-sources.md)。

## 方法

```
新聞與社群文本
  ├─ A. 用語基準法（不使用 LLM）
  └─ B. LLM 陪審團標註 → C. 自訓決策模型 → 全量推論
                                      ↓
              D. 自動驗證 → E. 動態貝氏模型 → F. 資金關聯分析
```

**A. 用語基準法。** 仿 Gentzkow & Shapiro (2010)，從立委質詢找出兩黨用法差異最大的詞，再看各媒體較常使用哪一側的詞。完全不經過 LLM，作為獨立對照。結果與限制見 [docs/phrase-baseline-comparison.md](docs/phrase-baseline-comparison.md)。

**B. LLM 陪審團標註。** 數個不同來源的大型語言模型依同一份標註規則，各自判斷每篇文章；模型看不到媒體名稱。中國公司開發的模型至多一個，並逐一接受政黨對調測試。標註量約 3–5 萬篇，涵蓋各媒體與各時期。

**C. 自訓決策模型。** 以陪審團標註訓練一個中文編碼器，每個標註問題一個分類頭，輸出經溫度校準的機率，用來標註其餘所有抽樣文章。模型與模型卡公開於 Hugging Face。

**D. 自動驗證。** 本研究不使用人工標註：一是擔心研究者個人的主觀政治判斷直接進入標籤，二是一個人的人力不足以標註數萬篇文章。LLM 同樣可能帶有偏誤，因此採用多個不同來源的模型，並以下列可公開重跑的方式檢驗：

1. 陪審團一致性（Krippendorff's α）
2. 已知立場錨點：政黨自己的新聞稿應判為對自己有利
3. 政黨對調測試：遮蔽人名、互換黨名後，分數應跟著互換（[docs/swap-test.md](docs/swap-test.md)）
4. 換提示詞、換模型，結論不應改變（[docs/prompt-sensitivity.md](docs/prompt-sensitivity.md)、[docs/jury-agreement.md](docs/jury-agreement.md)）
5. 用語基準法與 LLM 標註在媒體層級的一致程度

錨點比一般新聞立場鮮明，因此錨點上的準確率是上限參考，不代表一般新聞的準確率。陪審團分歧納入不確定區間；意見不一致的文章另行整理公開（[docs/jury-disagreements.md](docs/jury-disagreements.md)）。

**E. 動態貝氏模型。** 每家媒體、每個政黨一條隨機漫步軌跡，在已知事件（政黨輪替、所有權變動）允許跳躍；文章少或陪審團分歧大的時期區間較寬。事件規則與有無事件的比較見 [docs/trend-model.md](docs/trend-model.md)。

**F. 資金關聯分析。** 參考 Di Tella & Franceschelli (2011)，以事件研究與差異中之差異檢驗資金變化前後的報導變化。只報告相關，除非設計足以支持因果解釋。

## 資料使用原則

- 使用誠實的 User-Agent，遵守 robots.txt，每個網站每秒至多一個請求；不登入、不繞過驗證或防護，被封鎖即停止該來源
- robots.txt 標示禁止用於 AI 訓練的來源（PTT、中央社 `ai-train=no`），只用於標註與推論，不放入模型訓練資料
- 聯合報系於 robots.txt 註明保留 LLM／AI 用途；本研究為非營利學術研究，仍納入分析，並在報告的方法章節揭露
- robots.txt 回應 4xx 時依 RFC 9309 視為無限制
- YouTube 字幕與音訊所在路徑受 robots.txt 限制，因此只使用 Data API 的標題、說明與統計
- 不公開新聞全文；只公開網址、標題、衍生特徵與分數
- 討論平台的帳號一律單向雜湊，只公開彙總結果；隱私權政策見 [docs/privacy.md](docs/privacy.md)
- 分數描述為「在定義好的測量軸上的位置」，附方法、區間與限制

## 產出與時程

| 時間 | 產出 |
|---|---|
| 2026-11 | 資料收集上線；標註規則與試標；用語基準法；歷史抽樣；大量標註、決策模型、動態模型；網站 v1 上線（11/12） |
| 2026-12 | 選舉期間觀測至 12/28；依漂移監測重新校準；更新網站 |
| 2027-01 | 資金關聯分析；技術報告 |
| 2027-02 | arXiv；Hugging Face 資料集與模型；網站 v2 |

原本規劃網站在選後才上線，以免在模型完成驗證前、於最敏感的時期發布結果。2026-11-12 起改為提前公開：決策模型已通過事先訂定的測試集標準，各項驗證結果也已公開。選舉期間的週資料標為初步結果，網站與文件同時說明資料來源切換（[docs/source-switch.md](docs/source-switch.md)）與模型漂移（[docs/drift-monitor.md](docs/drift-monitor.md)）的影響。分數描述的是報導對政黨的呈現，不是對選民的投票建議。

## 已知限制

- 不使用人工標註，所有標籤來自 LLM；可信度仰賴上述自動驗證
- 歷史回溯受各家網站保留期限與 Internet Archive 存檔範圍限制，部分媒體的早期年份樣本較少（見 [docs/collection-status.md](docs/collection-status.md)）
- 各家「政治新聞」的初篩方式不同（網站分類或關鍵詞），最終由標註重新判定
- 用語基準法混入「執政 vs 在野」的角色差異，只適合在同一執政期間內比較
- Facebook、Instagram、Threads 的公開資料只能經 Meta Content Library 取得，須由學術機構的教師擔任主申請人；本研究未取得，因此不納入 Meta 平台。TikTok 的研究 API 只開放美國與歐洲的研究者
- 政治獻金只有 2018 年起有開放資料，因此獻金相關分析不涵蓋 2016 年政黨輪替；採購、政策宣導與所有權資料仍涵蓋 2012 年起

## 授權

程式碼採 MIT。衍生資料與模型另行標示授權；使用 ckip-transformers（GPL-3.0）時隔離為獨立前處理步驟。

## 參考文獻

- Gentzkow, M. & Shapiro, J. (2010). What drives media slant? *Econometrica*.
- Gentzkow, M., Shapiro, J. & Taddy, M. (2019). Measuring group differences in high-dimensional choices. *Econometrica*.
- Di Tella, R. & Franceschelli, I. (2011). Government advertising and media coverage of corruption scandals. *AEJ: Applied*.
- Durante, R. & Knight, B. (2012). Partisan control, media bias, and viewer responses. *JEEA*.
- Gilardi, F., Alizadeh, M. & Kubli, M. (2023). ChatGPT outperforms crowd workers for text-annotation tasks. *PNAS*.
- Martin, A. & Quinn, K. (2002). Dynamic ideal point estimation via MCMC. *Political Analysis*.
- Kao, How the pro-Beijing media influences voters. *APSR*.
- Reuters Institute, [Digital News Report 2026: Taiwan](https://reutersinstitute.politics.ox.ac.uk/digital-news-report/2026/taiwan).

# 台灣媒體政黨傾向分析

這個研究專案用公開、可重現的方法，量化台灣主要媒體在不同時期如何呈現國民黨、民進黨與民眾黨，並把結果對照公開的資金資料。

- 研究設計：[PLAN.md](PLAN.md)
- 標註規則：[docs/codebook.md](docs/codebook.md)
- 資料收集狀態：[docs/collection-status.md](docs/collection-status.md)
- 驗證與試標結果：[docs/](docs/)

## 安裝

需要先安裝 [uv](https://docs.astral.sh/uv/)。

```bash
uv sync
```

## 使用

收集一輪最新資料，來源包括新聞網站、YouTube、PTT、LINE TODAY 等：

```bash
uv run twmedia collect
```

歷史抽樣會從每家媒體每月的政治新聞中隨機抽取，中斷後可以接著跑：

```bash
uv run twmedia history cna ltn ettoday
```

查看各來源已收集的數量：

```bash
uv run twmedia status
```

資料存在 `data/`，這個資料夾不進 git，原文也不公開。每筆紀錄是一行 JSON，路徑為 `data/raw/<來源>/<YYYY-MM-DD>.jsonl`。

YouTube 資料透過官方 Data API v3 取得，需要在專案根目錄的 `.env` 設定 `YOUTUBE_API_KEY`。macOS 上每小時自動收集的排程範本在 `scripts/tw.twmedia.collect.plist`。

## 收集原則

- 收集程式使用誠實的 User-Agent，遵守 robots.txt，對每個網站每秒最多送出一個請求。
- 程式不登入，也不繞過驗證或防護；被某個來源封鎖時，就停止收集該來源。
- 新聞全文不會公開，討論平台上的帳號一律經過雜湊處理。
- robots.txt 標示 `ai-train=no` 的來源，不會拿來訓練模型。

## 測試

```bash
uv run pytest
```

## 授權

程式碼採用 [MIT](LICENSE) 授權。衍生資料與模型的授權會另外標示。

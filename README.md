# 台灣媒體政黨傾向分析

以公開、可重現的方法，量化台灣主要媒體在不同時期如何呈現國民黨、民進黨與民眾黨，並對照公開的資金資料。

- 研究設計：[PLAN.md](PLAN.md)
- 標註規則：[docs/codebook.md](docs/codebook.md)
- 資料收集狀態：[docs/collection-status.md](docs/collection-status.md)
- 驗證與試標結果：[docs/](docs/)

## 安裝

需要 [uv](https://docs.astral.sh/uv/)。

```bash
uv sync
```

## 使用

收集一輪最新資料（新聞網站、YouTube、PTT、LINE TODAY 等）：

```bash
uv run twmedia collect
```

歷史抽樣（每家媒體每月隨機抽政治新聞，可中斷後續跑）：

```bash
uv run twmedia history cna ltn ettoday
```

查看各來源已收集的數量：

```bash
uv run twmedia status
```

資料存在 `data/`（不進 git、不公開原文），每筆紀錄一行 JSON：`data/raw/<來源>/<YYYY-MM-DD>.jsonl`。

YouTube 使用官方 Data API v3，需在專案根目錄的 `.env` 設定 `YOUTUBE_API_KEY`。macOS 上每小時自動收集的排程範本在 `scripts/tw.twmedia.collect.plist`。

## 收集原則

- 誠實的 User-Agent，遵守 robots.txt，每個網站每秒至多一個請求
- 不登入、不繞過驗證或防護；被封鎖即停止該來源
- 不公開新聞全文；討論平台帳號一律雜湊
- 標示 `ai-train=no` 的來源不用於模型訓練

## 測試

```bash
uv run pytest
```

## 授權

程式碼採 [MIT](LICENSE)。衍生資料與模型另行標示授權。

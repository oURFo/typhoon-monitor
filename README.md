# 東亞颱風監測

颱風路徑、暴風圈、衛星雲圖，以及桃園 / 松山 / 高雄 / 臺中機場航班查詢。

## 功能

- 東亞活躍颱風列表與地圖（路徑、暴風圈、衛星圖層）
- 航班狀態：依**航空公司代碼 + 班次**查詢（例：`5J` + `310` → `5J310`）
- 涵蓋機場：桃園、松山、高雄、臺中（不含臺南）
- 航班資料由 **GitHub Actions 每 10 分鐘**抓取並寫入 `data/flights.json`，網站直接讀取 GitHub 上的檔案

## 本機開發

```bat
copy .env.example .env
:: 編輯 .env 填入 CWA_API_KEY
start.bat
```

瀏覽器開啟 http://127.0.0.1:8000

## 部署到 GitHub + Render（建議）

此專案含 Python 後端（需保護 CWA 金鑰），**無法**只用 GitHub Pages 靜態託管。建議：

**GitHub** 放程式碼 → **Render** 免費執行後端。

### 步驟 1：推送到 GitHub

```bash
git init
git add .
git commit -m "Initial commit: typhoon monitor"
git branch -M main
git remote add origin https://github.com/你的帳號/typhoon-monitor.git
git push -u origin main
```

> 勿提交 `.env`（已在 `.gitignore`）

### 步驟 2：Render 部署

1. 登入 [Render](https://render.com)，連結 GitHub
2. **New → Blueprint**，選此 repo（會讀取 `render.yaml`）
3. 在環境變數設定 **`CWA_API_KEY`**（與本機 `.env` 相同）
4. 部署完成後取得網址，例如 `https://typhoon-monitor.onrender.com`

### 步驟 3：驗證

- `https://你的網址/api/health`
- `https://你的網址/api/flights?airline=5J&number=310`

## 航班資料更新機制

1. **GitHub Actions**（`.github/workflows/refresh-flights.yml`）每 10 分鐘執行 `scripts/fetch_flights_snapshot.py`
2. 腳本抓取各機場開放資料，寫入 **`data/flights.json`** 並 push 回 GitHub
3. 前端從 jsDelivr 讀取：`https://cdn.jsdelivr.net/gh/oURFo/typhoon-monitor@main/data/flights.json`
4. Render 僅負責颱風 API（需 CWA 金鑰）；`data/**` 變更不觸發 Render 重新部署

手動更新：GitHub → Actions → **Refresh flights** → Run workflow

本機產生快照：

```bat
python scripts\fetch_flights_snapshot.py
```

## API

| 端點 | 說明 |
|------|------|
| `GET /api/typhoons` | 颱風列表與路徑 |
| `GET /api/flights` | 本機除錯：讀取 repo 內 `data/flights.json` |

## 環境變數

| 變數 | 必填 | 說明 |
|------|------|------|
| `CWA_API_KEY` | 是 | [氣象署開放資料](https://opendata.cwa.gov.tw) 授權碼 |
| `PORT` | 否 | 雲端平台自動注入（本機預設 8000） |

## 資料來源

- 颱風：中央氣象署 Open Data
- 衛星雲圖：CWA 色調強化紅外線（O-B0030-002，地理配準）
- 航班：各機場官網免費 JSON（無需 API Key）

## 授權

僅供參考，請以政府機關與機場官方公告為準。

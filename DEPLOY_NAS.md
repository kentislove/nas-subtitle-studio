# NAS Subtitle Studio 部署手冊

## 1. 本地搬移

目前 Codex 產生於：

```powershell
F:\AI股票投資分析\NAS-Subtitle-Studio.nas
```

若要放到你指定的正式本地路徑，請在 PowerShell 執行：

```powershell
Copy-Item -Recurse -Force `
  "F:\AI股票投資分析\NAS-Subtitle-Studio.nas" `
  "F:\NAS-Subtitle-Studio.nas"
```

## 2. 上傳到 NAS

把整個資料夾：

```text
F:\NAS-Subtitle-Studio.nas
```

複製到：

```text
/volume1/NewStorage/NAS-Subtitle-Studio.nas
```

## 3. 建立環境檔

在 NAS SSH 執行：

```bash
cd /volume1/NewStorage/NAS-Subtitle-Studio.nas
cp .env.example .env
vi .env
```

填入：

```text
GEMINI_API_KEY=你的 Gemini API Key
DB_BACKEND=mssql
MSSQL_HOST=你的 MSSQL IP 或主機名
MSSQL_PORT=1433
MSSQL_DATABASE=NASSubtitleStudio
MSSQL_USER=你的 MSSQL 帳號
MSSQL_PASSWORD=你的 MSSQL 密碼
```

## 4. MSSQL 建立資料庫與資料表

在 MSSQL 主機上先建立資料庫。可以用 SSMS / Azure Data Studio 執行：

```text
database/mssql_create_database.sql
```

再建立資料表與索引：

```text
database/mssql_schema.sql
```

若你的 `MSSQL_USER` 有建表權限，也可以只先建立空資料庫，後端啟動時會依 `DB_AUTO_CREATE=true` 自動建立下列資料表：

```text
dbo.nas_subtitle_videos
dbo.nas_subtitle_segments
dbo.nas_subtitle_chapters
```

也可以在能連到 MSSQL 的 Windows / NAS 環境用 Python 腳本建立：

```bash
python scripts/create_mssql_database.py --env .env --database NASSubtitleStudio
python scripts/check_mssql_connection.py --env .env
```

如果是在 SQL Server 主機本機執行，建議用不需要 Python / sqlcmd 的 PowerShell 腳本：

```powershell
powershell -ExecutionPolicy Bypass -File `
  ".\scripts\create_mssql_database.ps1" `
  -EnvPath ".\.env" `
  -Database "NASSubtitleStudio"
```

若要沿用 V12 的 MSSQL 主機、帳號與密碼，可在 Windows PowerShell 先產生本專案 `.env`：

```powershell
powershell -ExecutionPolicy Bypass -File `
  "F:\AI股票投資分析\NAS-Subtitle-Studio.nas\scripts\prepare_env_from_v12.ps1"
```

## 5. 建置與啟動

```bash
cd /volume1/NewStorage/NAS-Subtitle-Studio.nas

sudo /usr/local/bin/docker-compose build --no-cache backend frontend
sudo /usr/local/bin/docker-compose up -d
sudo /usr/local/bin/docker-compose ps
```

## 6. 網址

```text
http://NAS_IP:54320
```

## 7. 檢查

```bash
sudo /usr/local/bin/docker-compose logs --tail=80 backend
sudo /usr/local/bin/docker-compose logs --tail=80 frontend
```

API 健康檢查：

```text
http://NAS_IP:54320/api/health
```

## 8. 儲存位置

NAS 上影片與匯出檔會放在：

```text
/volume1/NewStorage/NAS-Subtitle-Studio.nas/data
```

包含：

```text
videos
subtitles
exports
```

影片索引、字幕段落、章節與處理狀態會放在 MSSQL。

## 9. Gateway 反向代理

若你要掛到 Gateway：

```text
/subtitle/ -> http://127.0.0.1:54320/
```

注意：瀏覽器螢幕錄影 API 通常需要 HTTPS 或 localhost。若透過 Tailscale HTTPS Gateway 開啟，較適合正式使用。

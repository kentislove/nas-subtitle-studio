# Security Policy

## 金鑰與敏感資料

請勿將下列資料提交到 GitHub：

- `.env`
- `data/`
- `data/studio_settings.json`
- Gemini API Key
- MSSQL host / user / password
- GitHub Personal Access Token
- 任何錄影檔、字幕檔、匯出影片

本專案已透過 `.gitignore` 排除上述常見敏感資料。

## Gemini API Key

Gemini API Key 可透過網頁輸入，儲存在：

```text
data/studio_settings.json
```

這是 runtime 設定，不應進版控。

## MSSQL

MSSQL 連線資訊請放在 `.env`：

```env
MSSQL_HOST=
MSSQL_PORT=1433
MSSQL_DATABASE=NASSubtitleStudio
MSSQL_USER=
MSSQL_PASSWORD=
```

請勿把正式帳號密碼寫進 README、程式碼或 issue。

## GitHub Token

若曾經把 GitHub token 貼到對話、設定檔或 log，請視為已外洩。

建議：

1. 到 GitHub 取消舊 token。
2. 重新建立 fine-grained token。
3. 僅授權指定 repository。
4. 只給必要權限，例如 Contents read/write。
5. 使用 `gh auth login` 或系統憑證管理，不要把 token 寫入專案檔案。

## 上架前檢查

```bash
git status --ignored
grep -RIn "ghp_\\|github_pat_\\|GEMINI_API_KEY=\\|MSSQL_PASSWORD=\\|aaaa1027" .
```

若有命中，請先移除或改成範例佔位符。

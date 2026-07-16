# GitHub 上架檢查清單

## 上架前不要提交

確認這些檔案沒有被 git 追蹤：

```text
.env
data/
*.mp4
*.webm
*.srt
*.vtt
*.lnk
__pycache__/
```

檢查：

```bash
git status --ignored
```

## 敏感字串掃描

```bash
grep -RIn "ghp_\\|github_pat_\\|GEMINI_API_KEY=\\|MSSQL_PASSWORD=\\|aaaa1027\\|100.86.212.9\\|192.168.66.21" .
```

如果命中正式密碼或 token，請移除後再 commit。

## 建議 repository 名稱

```text
nas-subtitle-studio
nas-caption-studio
subtitle-studio-nas
```

## 建議描述

```text
Self-hosted NAS video recording, Gemini captioning, subtitle editing, and hard-subtitle MP4 export tool.
```

## 初始化 Git

```bash
cd /path/to/NAS-Subtitle-Studio.nas
git init
git add .
git status
git commit -m "Initial release"
```

## 建立遠端

建議使用 GitHub CLI：

```bash
gh auth login
gh repo create nas-subtitle-studio --private --source . --remote origin --push
```

或手動建立 repo 後：

```bash
git remote add origin https://github.com/<your-account>/nas-subtitle-studio.git
git branch -M main
git push -u origin main
```

## Token 安全建議

如果曾經在任何檔案或對話中出現 `ghp_` token，請不要再使用它。  
請到 GitHub 重新產生 fine-grained token，並只授權指定 repo。

## 發布前驗證

```bash
docker-compose build --no-cache backend frontend
docker-compose config
```

NAS 端：

```bash
sudo /usr/local/bin/docker-compose up -d
sudo /usr/local/bin/docker-compose ps
sudo /usr/local/bin/docker-compose logs --tail=80 backend
sudo /usr/local/bin/docker-compose logs --tail=80 frontend
```

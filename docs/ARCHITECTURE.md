# 架構與資料流程

## 系統目標

NAS Subtitle Studio 的目標是建立一套可自架、可內網使用、資料可控的影片字幕工作台。  
它避免依賴大型剪輯軟體，只處理錄影、上傳、字幕辨識、字幕編輯與硬字幕匯出。

## 架構圖

```mermaid
flowchart TB
    subgraph Client["使用端"]
      Browser["Chrome / Edge<br/>錄影、上傳、字幕編輯"]
    end

    subgraph NAS["NAS Docker Host"]
      Nginx["frontend<br/>Nginx 靜態檔與反向代理"]
      FastAPI["backend<br/>FastAPI"]
      Data["data volume<br/>videos / subtitles / exports"]
    end

    subgraph External["外部服務"]
      Gemini["Google Gemini API"]
      MSSQL["Microsoft SQL Server"]
    end

    Browser --> Nginx
    Nginx --> FastAPI
    FastAPI --> Data
    FastAPI --> MSSQL
    FastAPI --> Gemini
```

## 容器

| 服務 | 說明 | 對外 |
|---|---|---|
| frontend | Nginx 靜態前端與 `/api` proxy | `54320:80` |
| backend | FastAPI、Gemini、FFmpeg、MSSQL 存取 | 只在 Docker network |

## 影片處理流程

```mermaid
flowchart LR
    Upload["錄影或上傳"] --> Save["寫入 NAS data/videos"]
    Save --> Index["MSSQL 建立影片紀錄"]
    Index --> Prepare{"格式檢查"}
    Prepare -->|webm/mp4| Ready["可處理"]
    Prepare -->|mov/mkv/m4v/avi| Transcode["轉成 MP4"]
    Transcode --> Ready
    Ready --> Caption["Gemini 產字幕"]
    Caption --> Normalize["字幕切段與排版整理"]
    Normalize --> Store["寫入 MSSQL + SRT/VTT/TXT"]
    Store --> Export["FFmpeg 燒錄字幕"]
    Export --> AAC["音訊轉 AAC"]
    AAC --> Done["產生含字幕 MP4"]
```

## 字幕資料

字幕會同時保存在：

- MSSQL：供網頁編輯與狀態查詢
- NAS `data/subtitles`：供下載 SRT / VTT / TXT / chapters

## 為什麼影片不進 MSSQL

影片檔案可能很大，不適合放進關聯式資料庫。  
本專案採用：

```text
MSSQL = metadata / subtitle / chapter / status
NAS filesystem = video / subtitle files / exports
```

這樣備份、搬移與效能都比較可控。

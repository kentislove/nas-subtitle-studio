from __future__ import annotations

import json
from pathlib import Path
from uuid import uuid4

from fastapi import BackgroundTasks, FastAPI, File, HTTPException, Query, Request, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from app.config import EXPORTS_DIR, SUBTITLES_DIR, VIDEOS_DIR, settings
from app.gemini_service import generate_subtitles_with_gemini
from app.models import GeminiSettingsUpdate, SubtitleUpdate, VideoRecord
from app.runtime_settings import is_gemini_configured, save_gemini_api_key
from app.storage import create_video, delete_video, get_video, init_db, list_videos, update_video, utc_now
from app.subtitle_utils import (
    clamp_imported_segments,
    decode_subtitle_bytes,
    fit_subtitle_segments_to_duration,
    parse_subtitle_text,
    sanitize_subtitle_segments,
    write_subtitle_files,
)
from app.video_tools import analyze_audio_waveform, burn_subtitles, probe_duration, transcode_to_mp4

app = FastAPI(title="NAS Subtitle Studio API", version="0.1.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

init_db()

app.mount("/media/videos", StaticFiles(directory=str(VIDEOS_DIR)), name="videos")
app.mount("/media/subtitles", StaticFiles(directory=str(SUBTITLES_DIR)), name="subtitles")
app.mount("/media/exports", StaticFiles(directory=str(EXPORTS_DIR)), name="exports")


@app.exception_handler(Exception)
async def unhandled_exception_handler(_: Request, exc: Exception) -> JSONResponse:
    return JSONResponse(
        status_code=500,
        content={"detail": f"伺服器處理失敗：{exc}"},
    )


def clean_text(value: str, max_length: int, fallback: str) -> str:
    cleaned = "".join(ch for ch in (value or "").strip() if ch >= " " and ch != "\x7f")
    if not cleaned:
        cleaned = fallback
    return cleaned[:max_length]


def video_path(record: VideoRecord) -> Path:
    return VIDEOS_DIR / record.stored_filename


def normalized_mp4_path(record: VideoRecord) -> Path:
    return VIDEOS_DIR / f"{record.id}.mp4"


def subtitle_base(record: VideoRecord) -> Path:
    return SUBTITLES_DIR / record.id / "subtitles"


def export_path(record: VideoRecord) -> Path:
    return EXPORTS_DIR / f"{record.id}_captioned.mp4"


def waveform_cache_path(record: VideoRecord, points: int) -> Path:
    return SUBTITLES_DIR / record.id / f"waveform-{Path(record.stored_filename).stem}-{points}.json"


def normalize_video_task(video_id: str) -> None:
    record = get_video(video_id)
    if not record:
        return
    src = video_path(record)
    try:
        suffix = src.suffix.lower()
        update_video(video_id, status="preparing", error=None)
        if suffix == ".mp4":
            duration = probe_duration(src)
            if duration is None:
                dst = normalized_mp4_path(record)
                if dst == src:
                    dst = VIDEOS_DIR / f"{record.id}.normalized.mp4"
                update_video(video_id, status="transcoding", error=None)
                transcode_to_mp4(src, dst)
                duration = probe_duration(dst)
                if duration is None:
                    raise RuntimeError("MP4 轉檔後仍無法取得影片長度")
                src = dst
            update_video(
                video_id,
                stored_filename=src.name,
                status="ready",
                duration=duration,
                error=None,
            )
            return

        if suffix == ".webm":
            update_video(video_id, status="transcoding", error=None)
            dst = normalized_mp4_path(record)
            transcode_to_mp4(src, dst)
            duration = probe_duration(dst)
            if duration is None:
                raise RuntimeError("WebM 轉成 MP4 後仍無法取得影片長度")
            update_video(
                video_id,
                stored_filename=dst.name,
                status="ready",
                duration=duration,
                error=None,
            )
            return

        update_video(video_id, status="transcoding", error=None)
        dst = normalized_mp4_path(record)
        transcode_to_mp4(src, dst)
        duration = probe_duration(dst)
        if duration is None:
            raise RuntimeError("影片轉成 MP4 後仍無法取得影片長度")
        update_video(
            video_id,
            stored_filename=dst.name,
            status="ready",
            duration=duration,
            error=None,
        )
    except Exception as exc:
        update_video(video_id, status="failed", error=str(exc))


def generate_subtitle_task(video_id: str) -> None:
    record = get_video(video_id)
    if not record:
        return
    try:
        update_video(video_id, status="captioning", error=None)
        transcript, segments, chapters = generate_subtitles_with_gemini(video_path(record), record.duration)
        segments = fit_subtitle_segments_to_duration(segments, record.duration)
        write_subtitle_files(subtitle_base(record), segments, chapters, transcript, normalize=False)
        update_video(
            video_id,
            status="editable",
            transcript=transcript,
            subtitles=segments,
            chapters=chapters,
            error=None,
        )
    except Exception as exc:
        update_video(video_id, status="failed", error=f"產生字幕失敗：{exc}")


def export_captioned_task(video_id: str) -> None:
    record = get_video(video_id)
    if not record:
        return
    try:
        update_video(video_id, status="exporting", error=None)
        final = export_path(record)
        tmp = final.with_name(f"{final.stem}.tmp.mp4")
        for file in (final, tmp):
            if file.exists():
                file.unlink()
        files = write_subtitle_files(
            subtitle_base(record),
            record.subtitles,
            record.chapters,
            record.transcript,
            normalize=False,
        )
        burn_subtitles(video_path(record), files["srt"], final)
        update_video(video_id, status="exported", error=None)
    except Exception as exc:
        update_video(video_id, status="failed", error=str(exc))


@app.get("/api/health")
def health() -> dict:
    return {
        "ok": True,
        "gemini_configured": is_gemini_configured(),
        "db_backend": settings.db_backend,
        "mssql_configured": bool(settings.mssql_host) if settings.db_backend.lower() == "mssql" else None,
        "data_dir": str(settings.app_data_dir),
    }


@app.get("/api/settings")
def app_settings() -> dict:
    return {
        "gemini_configured": is_gemini_configured(),
        "db_backend": settings.db_backend,
        "data_dir": str(settings.app_data_dir),
    }


@app.put("/api/settings/gemini")
def update_gemini_settings(payload: GeminiSettingsUpdate) -> dict:
    save_gemini_api_key(payload.api_key)
    return {"gemini_configured": is_gemini_configured()}


@app.get("/api/videos")
def videos() -> list[VideoRecord]:
    return list_videos()


@app.post("/api/videos/upload")
async def upload_video(background_tasks: BackgroundTasks, file: UploadFile = File(...)) -> VideoRecord:
    original = file.filename or "recording.webm"
    suffix = Path(original).suffix.lower() or ".webm"
    if suffix not in {".mp4", ".webm", ".mov", ".mkv", ".m4v", ".avi", ".mpg", ".mpeg"}:
        raise HTTPException(status_code=400, detail="僅支援 mp4/webm/mov/mkv/m4v/avi/mpg/mpeg")

    video_id = str(uuid4())
    stored_name = f"{video_id}{suffix}"
    target = VIDEOS_DIR / stored_name
    tmp_target = VIDEOS_DIR / f"{stored_name}.uploading"
    written = 0
    limit_bytes = settings.max_upload_mb * 1024 * 1024
    try:
        with tmp_target.open("wb") as out:
            while True:
                chunk = await file.read(1024 * 1024)
                if not chunk:
                    break
                written += len(chunk)
                if written > limit_bytes:
                    raise HTTPException(status_code=413, detail=f"檔案超過上限 {settings.max_upload_mb} MB")
                out.write(chunk)
        if written == 0:
            raise HTTPException(status_code=400, detail="上傳檔案是空的")
        tmp_target.replace(target)
    except HTTPException:
        for item in (tmp_target, target):
            if item.exists():
                item.unlink()
        raise
    except Exception:
        for item in (tmp_target, target):
            if item.exists():
                item.unlink()
        raise HTTPException(status_code=500, detail="影片寫入 NAS 儲存區失敗，請檢查 data 目錄權限")
    finally:
        await file.close()

    now = utc_now()
    try:
        record = create_video(VideoRecord(
            id=video_id,
            title=clean_text(Path(original).stem, 255, "未命名影片"),
            filename=clean_text(original, 500, stored_name),
            stored_filename=stored_name,
            status="uploaded",
            created_at=now,
            updated_at=now,
        ))
    except Exception as exc:
        if target.exists():
            target.unlink()
        raise HTTPException(status_code=500, detail=f"影片已上傳，但寫入資料庫失敗：{exc}") from exc
    background_tasks.add_task(normalize_video_task, video_id)
    return record


@app.get("/api/videos/{video_id}")
def video_detail(video_id: str) -> VideoRecord:
    record = get_video(video_id)
    if not record:
        raise HTTPException(status_code=404, detail="找不到影片")
    return record


@app.get("/api/videos/{video_id}/waveform")
def video_waveform(video_id: str, points: int = Query(default=1600, ge=200, le=5000)) -> dict:
    record = get_video(video_id)
    if not record:
        raise HTTPException(status_code=404, detail="找不到影片")
    src = video_path(record)
    if not src.exists():
        raise HTTPException(status_code=404, detail="找不到影片檔")
    cache = waveform_cache_path(record, points)
    source_mtime = src.stat().st_mtime
    if cache.exists():
        try:
            cached = json.loads(cache.read_text(encoding="utf-8"))
            if cached.get("source_mtime") == source_mtime:
                return cached
        except Exception:
            pass
    try:
        waveform = analyze_audio_waveform(src, points)
    except Exception as exc:
        raise HTTPException(status_code=422, detail=f"無法讀取音訊波形：{exc}") from exc
    payload = {
        "video_id": record.id,
        "stored_filename": record.stored_filename,
        "source_mtime": source_mtime,
        **waveform,
    }
    cache.parent.mkdir(parents=True, exist_ok=True)
    cache.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
    return payload


@app.delete("/api/videos/{video_id}")
def remove_video(video_id: str) -> dict:
    record = get_video(video_id)
    if not record:
        raise HTTPException(status_code=404, detail="找不到影片")
    files = [
        video_path(record),
        normalized_mp4_path(record),
        export_path(record),
        subtitle_base(record).with_suffix(".srt"),
        subtitle_base(record).with_suffix(".vtt"),
        subtitle_base(record).with_suffix(".txt"),
        subtitle_base(record).with_suffix(".chapters.md"),
    ]
    return {"deleted": delete_video(video_id, files)}


@app.post("/api/videos/{video_id}/caption")
def caption_video(video_id: str, background_tasks: BackgroundTasks) -> dict:
    record = get_video(video_id)
    if not record:
        raise HTTPException(status_code=404, detail="找不到影片")
    background_tasks.add_task(generate_subtitle_task, video_id)
    return {"queued": True, "status": "captioning"}


@app.put("/api/videos/{video_id}/subtitles")
def update_subtitles(video_id: str, payload: SubtitleUpdate) -> VideoRecord:
    record = get_video(video_id)
    if not record:
        raise HTTPException(status_code=404, detail="找不到影片")
    segments = sanitize_subtitle_segments(payload.subtitles, max_duration=record.duration)
    write_subtitle_files(subtitle_base(record), segments, payload.chapters, payload.transcript, normalize=False)
    return update_video(
        video_id,
        subtitles=segments,
        chapters=payload.chapters,
        transcript=payload.transcript,
        status="editable",
        error=None,
    )


@app.post("/api/videos/{video_id}/subtitles/import")
async def import_subtitles(video_id: str, file: UploadFile = File(...)) -> VideoRecord:
    record = get_video(video_id)
    if not record:
        raise HTTPException(status_code=404, detail="找不到影片")
    original = file.filename or "subtitles.srt"
    suffix = Path(original).suffix.lower()
    if suffix not in {".srt", ".vtt"}:
        raise HTTPException(status_code=400, detail="僅支援匯入 SRT 或 VTT 字幕檔")
    try:
        data = await file.read(5 * 1024 * 1024 + 1)
    finally:
        await file.close()
    if not data:
        raise HTTPException(status_code=400, detail="字幕檔是空的")
    if len(data) > 5 * 1024 * 1024:
        raise HTTPException(status_code=413, detail="字幕檔超過 5 MB")

    try:
        imported = parse_subtitle_text(decode_subtitle_bytes(data))
        segments = clamp_imported_segments(imported, record.duration)
    except Exception as exc:
        raise HTTPException(status_code=400, detail=f"字幕檔解析失敗：{exc}") from exc
    if not segments:
        raise HTTPException(status_code=400, detail="字幕檔沒有可匯入的時間軸字幕")

    transcript = "\n".join(seg.text for seg in segments)
    write_subtitle_files(subtitle_base(record), segments, record.chapters, transcript, normalize=False)
    return update_video(
        video_id,
        subtitles=segments,
        transcript=transcript,
        status="editable",
        error=None,
    )


@app.post("/api/videos/{video_id}/export")
def export_video(video_id: str, background_tasks: BackgroundTasks) -> dict:
    record = get_video(video_id)
    if not record:
        raise HTTPException(status_code=404, detail="找不到影片")
    if not record.subtitles:
        raise HTTPException(status_code=400, detail="尚無字幕可匯出")
    background_tasks.add_task(export_captioned_task, video_id)
    return {"queued": True, "status": "exporting"}


@app.get("/api/videos/{video_id}/download/{kind}")
def download_file(video_id: str, kind: str) -> FileResponse:
    record = get_video(video_id)
    if not record:
        raise HTTPException(status_code=404, detail="找不到影片")
    mapping = {
        "video": video_path(record),
        "srt": subtitle_base(record).with_suffix(".srt"),
        "vtt": subtitle_base(record).with_suffix(".vtt"),
        "txt": subtitle_base(record).with_suffix(".txt"),
        "chapters": subtitle_base(record).with_suffix(".chapters.md"),
        "export": export_path(record),
    }
    if kind == "export" and record.status != "exported":
        raise HTTPException(status_code=409, detail="含字幕 MP4 尚未匯出完成")
    file = mapping.get(kind)
    if not file or not file.exists():
        raise HTTPException(status_code=404, detail="檔案尚未產生")
    return FileResponse(file, filename=file.name)

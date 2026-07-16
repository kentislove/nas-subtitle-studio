from __future__ import annotations

import json
import re
import sqlite3
from contextlib import contextmanager
from datetime import datetime, timezone
from decimal import Decimal
from pathlib import Path
from typing import Any, Iterator

from app.config import DB_PATH, settings
from app.models import Chapter, SubtitleSegment, VideoRecord


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _use_mssql() -> bool:
    return settings.db_backend.lower() == "mssql"


def _to_text(value: Any) -> str:
    if isinstance(value, datetime):
        return value.isoformat(timespec="seconds")
    return str(value)


def _to_float(value: Any) -> float | None:
    if value is None:
        return None
    if isinstance(value, Decimal):
        return float(value)
    return float(value)


def _safe_database_name(name: str) -> str:
    if not re.fullmatch(r"[A-Za-z0-9_]+", name):
        raise RuntimeError("MSSQL_DATABASE 僅支援英數字與底線")
    return name


@contextmanager
def _mssql_connection(database: str | None = None, autocommit: bool = False) -> Iterator[Any]:
    import pymssql

    if not settings.mssql_host:
        raise RuntimeError("MSSQL_HOST 尚未設定")
    conn = pymssql.connect(
        server=settings.mssql_host,
        port=settings.mssql_port,
        user=settings.mssql_user,
        password=settings.mssql_password,
        database=database or settings.mssql_database,
        charset="UTF-8",
        autocommit=autocommit,
    )
    try:
        yield conn
    finally:
        conn.close()


def init_db() -> None:
    if _use_mssql():
        if settings.db_auto_create:
            _init_mssql()
        return
    _init_sqlite()


def _init_sqlite() -> None:
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    with sqlite3.connect(DB_PATH) as conn:
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS videos (
                id TEXT PRIMARY KEY,
                title TEXT NOT NULL,
                filename TEXT NOT NULL,
                stored_filename TEXT NOT NULL,
                status TEXT NOT NULL,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                duration REAL,
                transcript TEXT NOT NULL DEFAULT '',
                chapters_json TEXT NOT NULL DEFAULT '[]',
                subtitles_json TEXT NOT NULL DEFAULT '[]',
                error TEXT
            )
            """
        )
        conn.commit()


def _init_mssql() -> None:
    _ensure_mssql_database()
    statements = [
        """
        IF OBJECT_ID(N'dbo.nas_subtitle_videos', N'U') IS NULL
        CREATE TABLE dbo.nas_subtitle_videos (
            id NVARCHAR(36) NOT NULL,
            title NVARCHAR(255) NOT NULL,
            filename NVARCHAR(500) NOT NULL,
            stored_filename NVARCHAR(500) NOT NULL,
            status NVARCHAR(40) NOT NULL,
            created_at DATETIMEOFFSET(0) NOT NULL,
            updated_at DATETIMEOFFSET(0) NOT NULL,
            duration_seconds DECIMAL(18, 3) NULL,
            transcript NVARCHAR(MAX) NOT NULL CONSTRAINT DF_nas_subtitle_videos_transcript DEFAULT N'',
            error NVARCHAR(MAX) NULL,
            CONSTRAINT PK_nas_subtitle_videos PRIMARY KEY CLUSTERED (id)
        )
        """,
        """
        IF OBJECT_ID(N'dbo.nas_subtitle_segments', N'U') IS NULL
        CREATE TABLE dbo.nas_subtitle_segments (
            video_id NVARCHAR(36) NOT NULL,
            segment_id NVARCHAR(64) NOT NULL,
            sort_order INT NOT NULL,
            start_seconds DECIMAL(18, 3) NOT NULL,
            end_seconds DECIMAL(18, 3) NOT NULL,
            text NVARCHAR(MAX) NOT NULL,
            CONSTRAINT PK_nas_subtitle_segments PRIMARY KEY CLUSTERED (video_id, segment_id),
            CONSTRAINT FK_nas_subtitle_segments_video FOREIGN KEY (video_id)
                REFERENCES dbo.nas_subtitle_videos(id) ON DELETE CASCADE
        )
        """,
        """
        IF OBJECT_ID(N'dbo.nas_subtitle_chapters', N'U') IS NULL
        CREATE TABLE dbo.nas_subtitle_chapters (
            video_id NVARCHAR(36) NOT NULL,
            chapter_index INT NOT NULL,
            start_seconds DECIMAL(18, 3) NOT NULL,
            title NVARCHAR(255) NOT NULL,
            CONSTRAINT PK_nas_subtitle_chapters PRIMARY KEY CLUSTERED (video_id, chapter_index),
            CONSTRAINT FK_nas_subtitle_chapters_video FOREIGN KEY (video_id)
                REFERENCES dbo.nas_subtitle_videos(id) ON DELETE CASCADE
        )
        """,
        """
        IF NOT EXISTS (
            SELECT 1 FROM sys.indexes
            WHERE name = N'IX_nas_subtitle_videos_created_at'
              AND object_id = OBJECT_ID(N'dbo.nas_subtitle_videos')
        )
        CREATE INDEX IX_nas_subtitle_videos_created_at
        ON dbo.nas_subtitle_videos(created_at DESC)
        """,
        """
        IF NOT EXISTS (
            SELECT 1 FROM sys.indexes
            WHERE name = N'IX_nas_subtitle_segments_video_sort'
              AND object_id = OBJECT_ID(N'dbo.nas_subtitle_segments')
        )
        CREATE INDEX IX_nas_subtitle_segments_video_sort
        ON dbo.nas_subtitle_segments(video_id, sort_order)
        """,
        """
        IF NOT EXISTS (
            SELECT 1 FROM sys.indexes
            WHERE name = N'IX_nas_subtitle_chapters_video_sort'
              AND object_id = OBJECT_ID(N'dbo.nas_subtitle_chapters')
        )
        CREATE INDEX IX_nas_subtitle_chapters_video_sort
        ON dbo.nas_subtitle_chapters(video_id, chapter_index)
        """,
    ]
    with _mssql_connection() as conn:
        cursor = conn.cursor()
        for statement in statements:
            cursor.execute(statement)
        conn.commit()


def _ensure_mssql_database() -> None:
    database = _safe_database_name(settings.mssql_database)
    with _mssql_connection("master", autocommit=True) as conn:
        cursor = conn.cursor()
        cursor.execute(
            f"""
            IF DB_ID(N'{database}') IS NULL
            BEGIN
                CREATE DATABASE [{database}]
            END
            """
        )


def _sqlite_row_to_record(row: sqlite3.Row) -> VideoRecord:
    return VideoRecord(
        id=row["id"],
        title=row["title"],
        filename=row["filename"],
        stored_filename=row["stored_filename"],
        status=row["status"],
        created_at=row["created_at"],
        updated_at=row["updated_at"],
        duration=row["duration"],
        transcript=row["transcript"] or "",
        chapters=[Chapter(**item) for item in json.loads(row["chapters_json"] or "[]")],
        subtitles=[SubtitleSegment(**item) for item in json.loads(row["subtitles_json"] or "[]")],
        error=row["error"],
    )


def _mssql_row_to_record(row: dict[str, Any], subtitles: list[SubtitleSegment], chapters: list[Chapter]) -> VideoRecord:
    return VideoRecord(
        id=row["id"],
        title=row["title"],
        filename=row["filename"],
        stored_filename=row["stored_filename"],
        status=row["status"],
        created_at=_to_text(row["created_at"]),
        updated_at=_to_text(row["updated_at"]),
        duration=_to_float(row["duration_seconds"]),
        transcript=row["transcript"] or "",
        chapters=chapters,
        subtitles=subtitles,
        error=row["error"],
    )


def _load_mssql_children(conn: Any, video_id: str) -> tuple[list[SubtitleSegment], list[Chapter]]:
    cursor = conn.cursor(as_dict=True)
    cursor.execute(
        """
        SELECT segment_id, start_seconds, end_seconds, text
        FROM dbo.nas_subtitle_segments
        WHERE video_id = %s
        ORDER BY sort_order, start_seconds
        """,
        (video_id,),
    )
    subtitles = [
        SubtitleSegment(
            id=row["segment_id"],
            start=float(row["start_seconds"]),
            end=float(row["end_seconds"]),
            text=row["text"],
        )
        for row in cursor.fetchall()
    ]
    cursor.execute(
        """
        SELECT start_seconds, title
        FROM dbo.nas_subtitle_chapters
        WHERE video_id = %s
        ORDER BY chapter_index, start_seconds
        """,
        (video_id,),
    )
    chapters = [
        Chapter(start=float(row["start_seconds"]), title=row["title"])
        for row in cursor.fetchall()
    ]
    return subtitles, chapters


def list_videos() -> list[VideoRecord]:
    if _use_mssql():
        return _list_videos_mssql()
    with sqlite3.connect(DB_PATH) as conn:
        conn.row_factory = sqlite3.Row
        rows = conn.execute("SELECT * FROM videos ORDER BY created_at DESC").fetchall()
    return [_sqlite_row_to_record(row) for row in rows]


def _list_videos_mssql() -> list[VideoRecord]:
    with _mssql_connection() as conn:
        cursor = conn.cursor(as_dict=True)
        cursor.execute("SELECT * FROM dbo.nas_subtitle_videos ORDER BY created_at DESC")
        rows = cursor.fetchall()
        records: list[VideoRecord] = []
        for row in rows:
            subtitles, chapters = _load_mssql_children(conn, row["id"])
            records.append(_mssql_row_to_record(row, subtitles, chapters))
        return records


def get_video(video_id: str) -> VideoRecord | None:
    if _use_mssql():
        return _get_video_mssql(video_id)
    with sqlite3.connect(DB_PATH) as conn:
        conn.row_factory = sqlite3.Row
        row = conn.execute("SELECT * FROM videos WHERE id = ?", (video_id,)).fetchone()
    return _sqlite_row_to_record(row) if row else None


def _get_video_mssql(video_id: str) -> VideoRecord | None:
    with _mssql_connection() as conn:
        cursor = conn.cursor(as_dict=True)
        cursor.execute("SELECT * FROM dbo.nas_subtitle_videos WHERE id = %s", (video_id,))
        row = cursor.fetchone()
        if not row:
            return None
        subtitles, chapters = _load_mssql_children(conn, video_id)
        return _mssql_row_to_record(row, subtitles, chapters)


def create_video(record: VideoRecord) -> VideoRecord:
    if _use_mssql():
        return _create_video_mssql(record)
    with sqlite3.connect(DB_PATH) as conn:
        conn.execute(
            """
            INSERT INTO videos (
                id, title, filename, stored_filename, status, created_at, updated_at,
                duration, transcript, chapters_json, subtitles_json, error
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                record.id,
                record.title,
                record.filename,
                record.stored_filename,
                record.status,
                record.created_at,
                record.updated_at,
                record.duration,
                record.transcript,
                json.dumps([c.model_dump() for c in record.chapters], ensure_ascii=False),
                json.dumps([s.model_dump() for s in record.subtitles], ensure_ascii=False),
                record.error,
            ),
        )
        conn.commit()
    return record


def _create_video_mssql(record: VideoRecord) -> VideoRecord:
    with _mssql_connection() as conn:
        cursor = conn.cursor()
        cursor.execute(
            """
            INSERT INTO dbo.nas_subtitle_videos (
                id, title, filename, stored_filename, status, created_at, updated_at,
                duration_seconds, transcript, error
            ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
            """,
            (
                record.id,
                record.title,
                record.filename,
                record.stored_filename,
                record.status,
                record.created_at,
                record.updated_at,
                record.duration,
                record.transcript,
                record.error,
            ),
        )
        _replace_mssql_children(cursor, record)
        conn.commit()
    return record


def update_video(video_id: str, **fields) -> VideoRecord:
    current = get_video(video_id)
    if not current:
        raise KeyError(video_id)
    payload = current.model_dump()
    payload.update(fields)
    payload["updated_at"] = utc_now()
    updated = VideoRecord(**payload)
    if _use_mssql():
        return _update_video_mssql(video_id, updated)
    with sqlite3.connect(DB_PATH) as conn:
        conn.execute(
            """
            UPDATE videos SET
                title = ?, filename = ?, stored_filename = ?, status = ?, updated_at = ?,
                duration = ?, transcript = ?, chapters_json = ?, subtitles_json = ?, error = ?
            WHERE id = ?
            """,
            (
                updated.title,
                updated.filename,
                updated.stored_filename,
                updated.status,
                updated.updated_at,
                updated.duration,
                updated.transcript,
                json.dumps([c.model_dump() for c in updated.chapters], ensure_ascii=False),
                json.dumps([s.model_dump() for s in updated.subtitles], ensure_ascii=False),
                updated.error,
                video_id,
            ),
        )
        conn.commit()
    return updated


def _update_video_mssql(video_id: str, updated: VideoRecord) -> VideoRecord:
    with _mssql_connection() as conn:
        cursor = conn.cursor()
        cursor.execute(
            """
            UPDATE dbo.nas_subtitle_videos SET
                title = %s,
                filename = %s,
                stored_filename = %s,
                status = %s,
                updated_at = %s,
                duration_seconds = %s,
                transcript = %s,
                error = %s
            WHERE id = %s
            """,
            (
                updated.title,
                updated.filename,
                updated.stored_filename,
                updated.status,
                updated.updated_at,
                updated.duration,
                updated.transcript,
                updated.error,
                video_id,
            ),
        )
        _replace_mssql_children(cursor, updated)
        conn.commit()
    return updated


def _replace_mssql_children(cursor: Any, record: VideoRecord) -> None:
    cursor.execute("DELETE FROM dbo.nas_subtitle_segments WHERE video_id = %s", (record.id,))
    cursor.execute("DELETE FROM dbo.nas_subtitle_chapters WHERE video_id = %s", (record.id,))
    for index, subtitle in enumerate(record.subtitles):
        cursor.execute(
            """
            INSERT INTO dbo.nas_subtitle_segments (
                video_id, segment_id, sort_order, start_seconds, end_seconds, text
            ) VALUES (%s, %s, %s, %s, %s, %s)
            """,
            (record.id, subtitle.id, index, subtitle.start, subtitle.end, subtitle.text),
        )
    for index, chapter in enumerate(record.chapters):
        cursor.execute(
            """
            INSERT INTO dbo.nas_subtitle_chapters (
                video_id, chapter_index, start_seconds, title
            ) VALUES (%s, %s, %s, %s)
            """,
            (record.id, index, chapter.start, chapter.title),
        )


def delete_video(video_id: str, files: list[Path]) -> bool:
    if not get_video(video_id):
        return False
    if _use_mssql():
        with _mssql_connection() as conn:
            conn.cursor().execute("DELETE FROM dbo.nas_subtitle_videos WHERE id = %s", (video_id,))
            conn.commit()
    else:
        with sqlite3.connect(DB_PATH) as conn:
            conn.execute("DELETE FROM videos WHERE id = ?", (video_id,))
            conn.commit()
    for file in files:
        try:
            if file.exists():
                file.unlink()
        except OSError:
            pass
    return True

from __future__ import annotations

import html
import re
from pathlib import Path
from uuid import uuid4

from app.models import Chapter, SubtitleSegment

MAX_SUBTITLE_SECONDS = 5.0
MAX_LINE_CHARS = 18
MAX_LINES = 2
MAX_SEGMENT_CHARS = MAX_LINE_CHARS * MAX_LINES


def seconds_to_srt_time(value: float) -> str:
    ms_total = max(0, int(round(value * 1000)))
    ms = ms_total % 1000
    total_seconds = ms_total // 1000
    seconds = total_seconds % 60
    minutes = (total_seconds // 60) % 60
    hours = total_seconds // 3600
    return f"{hours:02d}:{minutes:02d}:{seconds:02d},{ms:03d}"


def seconds_to_vtt_time(value: float) -> str:
    return seconds_to_srt_time(value).replace(",", ".")


def segments_to_srt(segments: list[SubtitleSegment]) -> str:
    blocks = []
    for index, seg in enumerate(segments, start=1):
        text = layout_subtitle_text(seg.text)
        blocks.append(
            f"{index}\n{seconds_to_srt_time(seg.start)} --> {seconds_to_srt_time(seg.end)}\n{text}"
        )
    return "\n\n".join(blocks) + ("\n" if blocks else "")


def segments_to_vtt(segments: list[SubtitleSegment]) -> str:
    blocks = ["WEBVTT\n"]
    for seg in segments:
        text = html.escape(layout_subtitle_text(seg.text))
        blocks.append(
            f"{seconds_to_vtt_time(seg.start)} --> {seconds_to_vtt_time(seg.end)}\n{text}"
        )
    return "\n\n".join(blocks) + ("\n" if len(blocks) > 1 else "")


def split_subtitle_text(text: str) -> list[str]:
    cleaned = re.sub(r"\s+", "", (text or "").strip())
    if not cleaned:
        return []
    parts = [p for p in re.split(r"(?<=[。！？!?；;，,、])", cleaned) if p]
    chunks: list[str] = []
    current = ""
    for part in parts or [cleaned]:
        if len(current) + len(part) <= MAX_SEGMENT_CHARS:
            current += part
            continue
        if current:
            chunks.append(current)
            current = ""
        while len(part) > MAX_SEGMENT_CHARS:
            chunks.append(part[:MAX_SEGMENT_CHARS])
            part = part[MAX_SEGMENT_CHARS:]
        current = part
    if current:
        chunks.append(current)
    return chunks


def layout_subtitle_text(text: str) -> str:
    cleaned = re.sub(r"\s+", "", (text or "").strip())
    if len(cleaned) <= MAX_LINE_CHARS:
        return cleaned
    lines = []
    remaining = cleaned
    for _ in range(MAX_LINES):
        if not remaining:
            break
        if len(remaining) <= MAX_LINE_CHARS:
            lines.append(remaining)
            remaining = ""
            break
        cut = MAX_LINE_CHARS
        for mark in "，、。！？；,.!?;":
            pos = remaining.rfind(mark, 0, MAX_LINE_CHARS + 1)
            if pos >= 8:
                cut = pos + 1
                break
        lines.append(remaining[:cut])
        remaining = remaining[cut:]
    if remaining and lines:
        lines[-1] = lines[-1].rstrip("，、；,;") + "…"
    return "\n".join(lines)


def normalize_subtitle_segments(segments: list[SubtitleSegment]) -> list[SubtitleSegment]:
    normalized: list[SubtitleSegment] = []
    for seg in sorted(segments, key=lambda item: (item.start, item.end)):
        start = max(0.0, float(seg.start))
        end = max(start + 0.5, float(seg.end))
        chunks = split_subtitle_text(seg.text) or [seg.text.strip()]
        count = len(chunks)
        duration = max(1.2, (end - start) / count)
        duration = min(MAX_SUBTITLE_SECONDS, duration)
        for index in range(count):
            chunk = chunks[index] if index < len(chunks) else chunks[-1]
            item_start = start + index * duration
            item_end = min(end, item_start + duration)
            if item_end <= item_start:
                item_end = item_start + min(MAX_SUBTITLE_SECONDS, max(1.2, end - start))
            normalized.append(SubtitleSegment(
                id=str(uuid4()),
                start=item_start,
                end=item_end,
                text=layout_subtitle_text(chunk),
            ))
    return normalized


def chapters_to_markdown(chapters: list[Chapter]) -> str:
    lines = ["# 影片章節", ""]
    for chapter in chapters:
        minutes = int(chapter.start // 60)
        seconds = int(chapter.start % 60)
        lines.append(f"- {minutes:02d}:{seconds:02d} {chapter.title}")
    return "\n".join(lines) + "\n"


def write_subtitle_files(base: Path, segments: list[SubtitleSegment],
                         chapters: list[Chapter], transcript: str) -> dict[str, Path]:
    base.parent.mkdir(parents=True, exist_ok=True)
    srt = base.with_suffix(".srt")
    vtt = base.with_suffix(".vtt")
    txt = base.with_suffix(".txt")
    md = base.with_suffix(".chapters.md")
    normalized = normalize_subtitle_segments(segments)
    srt.write_text(segments_to_srt(normalized), encoding="utf-8")
    vtt.write_text(segments_to_vtt(normalized), encoding="utf-8")
    txt.write_text(transcript or "", encoding="utf-8")
    md.write_text(chapters_to_markdown(chapters), encoding="utf-8")
    return {"srt": srt, "vtt": vtt, "txt": txt, "chapters": md}


def safe_subtitle_filename(value: str) -> str:
    return re.sub(r"[^A-Za-z0-9_.-]+", "_", value)

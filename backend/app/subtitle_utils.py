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
TIMECODE_RE = re.compile(
    r"(?P<start>\d{1,2}:\d{2}(?::\d{2})?[\.,]\d{1,3})\s*-->\s*"
    r"(?P<end>\d{1,2}:\d{2}(?::\d{2})?[\.,]\d{1,3})"
)


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


def subtitle_time_to_seconds(value: str) -> float:
    text = value.strip().replace(",", ".")
    parts = text.split(":")
    if len(parts) == 2:
        hours = 0
        minutes, seconds = parts
    elif len(parts) == 3:
        hours, minutes, seconds = parts
    else:
        raise ValueError(f"不支援的字幕時間格式：{value}")
    return int(hours) * 3600 + int(minutes) * 60 + float(seconds)


def clean_imported_subtitle_text(lines: list[str]) -> str:
    text = "\n".join(line.strip() for line in lines).strip()
    text = re.sub(r"</?[^>]+>", "", text)
    return html.unescape(text).strip()


def decode_subtitle_bytes(data: bytes) -> str:
    for encoding in ("utf-8-sig", "utf-16", "cp950", "big5"):
        try:
            return data.decode(encoding)
        except UnicodeDecodeError:
            continue
    return data.decode("utf-8", errors="replace")


def parse_subtitle_text(content: str) -> list[SubtitleSegment]:
    text = content.replace("\r\n", "\n").replace("\r", "\n").lstrip("\ufeff")
    lines = text.split("\n")
    segments: list[SubtitleSegment] = []
    index = 0
    while index < len(lines):
        line = lines[index].strip()
        match = TIMECODE_RE.search(line)
        if not match:
            index += 1
            continue
        index += 1
        cue_lines: list[str] = []
        while index < len(lines) and lines[index].strip():
            cue_lines.append(lines[index])
            index += 1
        cue_text = clean_imported_subtitle_text(cue_lines)
        if cue_text:
            start = subtitle_time_to_seconds(match.group("start"))
            end = subtitle_time_to_seconds(match.group("end"))
            if end > start:
                segments.append(SubtitleSegment(
                    id=str(uuid4()),
                    start=start,
                    end=end,
                    text=cue_text,
                ))
        index += 1
    return sanitize_subtitle_segments(segments)


def clamp_imported_segments(
    segments: list[SubtitleSegment],
    max_duration: float | None,
) -> list[SubtitleSegment]:
    if not max_duration or max_duration <= 0:
        return sanitize_subtitle_segments(segments)
    limit = float(max_duration)
    clipped: list[SubtitleSegment] = []
    for seg in segments:
        if seg.end <= 0 or seg.start >= limit:
            continue
        clipped.append(SubtitleSegment(
            id=seg.id,
            start=max(0.0, seg.start),
            end=min(limit, seg.end),
            text=seg.text,
        ))
    return sanitize_subtitle_segments(clipped)


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
    while remaining:
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


def sanitize_subtitle_segments(segments: list[SubtitleSegment], max_duration: float | None = None) -> list[SubtitleSegment]:
    sanitized: list[SubtitleSegment] = []
    for seg in sorted(segments, key=lambda item: (item.start, item.end)):
        text = (seg.text or "").strip()
        if not text:
            continue
        start = max(0.0, float(seg.start))
        end = max(start + 0.15, float(seg.end))
        if max_duration is not None:
            limit = max(0.15, float(max_duration))
            start = min(start, max(0.0, limit - 0.15))
            end = min(max(start + 0.15, end), limit)
        sanitized.append(SubtitleSegment(
            id=seg.id or str(uuid4()),
            start=start,
            end=end,
            text=text,
        ))
    return sanitized


def fit_subtitle_segments_to_duration(
    segments: list[SubtitleSegment],
    duration: float | None,
) -> list[SubtitleSegment]:
    sanitized = sanitize_subtitle_segments(segments)
    if not sanitized or not duration or duration <= 0:
        return sanitized
    limit = float(duration)
    last_end = max(seg.end for seg in sanitized)
    if last_end <= limit + 0.5:
        return sanitize_subtitle_segments(sanitized, max_duration=limit)
    first_start = min(seg.start for seg in sanitized)
    if last_end <= first_start:
        return sanitize_subtitle_segments(sanitized, max_duration=limit)
    scale = max(0.01, (limit - first_start) / (last_end - first_start))
    fitted: list[SubtitleSegment] = []
    for seg in sanitized:
        start = first_start + (seg.start - first_start) * scale
        end = first_start + (seg.end - first_start) * scale
        fitted.append(SubtitleSegment(
            id=seg.id,
            start=start,
            end=max(start + 0.15, end),
            text=seg.text,
        ))
    return sanitize_subtitle_segments(fitted, max_duration=limit)


def chapters_to_markdown(chapters: list[Chapter]) -> str:
    lines = ["# 影片章節", ""]
    for chapter in chapters:
        minutes = int(chapter.start // 60)
        seconds = int(chapter.start % 60)
        lines.append(f"- {minutes:02d}:{seconds:02d} {chapter.title}")
    return "\n".join(lines) + "\n"


def write_subtitle_files(base: Path, segments: list[SubtitleSegment],
                         chapters: list[Chapter], transcript: str,
                         normalize: bool = True) -> dict[str, Path]:
    base.parent.mkdir(parents=True, exist_ok=True)
    srt = base.with_suffix(".srt")
    vtt = base.with_suffix(".vtt")
    txt = base.with_suffix(".txt")
    md = base.with_suffix(".chapters.md")
    normalized = normalize_subtitle_segments(segments) if normalize else sanitize_subtitle_segments(segments)
    srt.write_text(segments_to_srt(normalized), encoding="utf-8")
    vtt.write_text(segments_to_vtt(normalized), encoding="utf-8")
    txt.write_text(transcript or "", encoding="utf-8")
    md.write_text(chapters_to_markdown(chapters), encoding="utf-8")
    return {"srt": srt, "vtt": vtt, "txt": txt, "chapters": md}


def safe_subtitle_filename(value: str) -> str:
    return re.sub(r"[^A-Za-z0-9_.-]+", "_", value)

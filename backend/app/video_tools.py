from __future__ import annotations

import json
import math
import subprocess
from array import array
from pathlib import Path


def run_command(args: list[str]) -> subprocess.CompletedProcess[str]:
    return subprocess.run(args, capture_output=True, text=True, check=True)


def run_binary_command(args: list[str]) -> bytes:
    result = subprocess.run(args, capture_output=True, check=True)
    return result.stdout


def _escape_subtitle_filter_path(path: Path) -> str:
    return str(path).replace("\\", "/").replace("'", r"\'")


def probe_duration(path: Path) -> float | None:
    try:
        result = run_command([
            "ffprobe",
            "-v",
            "error",
            "-show_entries",
            "format=duration",
            "-of",
            "json",
            str(path),
        ])
        data = json.loads(result.stdout or "{}")
        duration = data.get("format", {}).get("duration")
        return float(duration) if duration else None
    except Exception:
        return None


def transcode_to_mp4(src: Path, dst: Path) -> None:
    dst.parent.mkdir(parents=True, exist_ok=True)
    run_command([
        "ffmpeg",
        "-y",
        "-i",
        str(src),
        "-c:v",
        "libx264",
        "-preset",
        "veryfast",
        "-crf",
        "20",
        "-c:a",
        "aac",
        "-b:a",
        "160k",
        "-movflags",
        "+faststart",
        str(dst),
    ])


def analyze_audio_waveform(src: Path, points: int = 1600) -> dict:
    points = max(200, min(5000, int(points or 1600)))
    sample_rate = 8000
    raw = run_binary_command([
        "ffmpeg",
        "-v",
        "error",
        "-i",
        str(src),
        "-map",
        "0:a:0",
        "-ac",
        "1",
        "-ar",
        str(sample_rate),
        "-f",
        "s16le",
        "-",
    ])
    samples = array("h")
    samples.frombytes(raw)
    if not samples:
        return {"duration": 0.0, "sample_rate": sample_rate, "peaks": []}
    chunk_size = max(1, math.ceil(len(samples) / points))
    peaks = []
    for start in range(0, len(samples), chunk_size):
        chunk = samples[start:start + chunk_size]
        peak = max(abs(value) for value in chunk) / 32768
        peaks.append(round(min(1.0, peak), 4))
    return {
        "duration": round(len(samples) / sample_rate, 3),
        "sample_rate": sample_rate,
        "peaks": peaks,
    }


def extract_audio(src: Path, dst: Path) -> None:
    dst.parent.mkdir(parents=True, exist_ok=True)
    run_command([
        "ffmpeg",
        "-y",
        "-i",
        str(src),
        "-vn",
        "-ac",
        "1",
        "-ar",
        "16000",
        "-b:a",
        "96k",
        str(dst),
    ])


def burn_subtitles(src: Path, srt: Path, dst: Path) -> None:
    dst.parent.mkdir(parents=True, exist_ok=True)
    tmp_dst = dst.with_name(f"{dst.stem}.tmp.mp4")
    if tmp_dst.exists():
        tmp_dst.unlink()
    escaped_srt = _escape_subtitle_filter_path(srt)
    force_style = (
        "FontName=Noto Sans CJK TC,"
        "FontSize=15,"
        "PrimaryColour=&H00FFFFFF,"
        "OutlineColour=&H00000000,"
        "BorderStyle=1,"
        "Outline=1.2,"
        "Shadow=1,"
        "Alignment=2,"
        "MarginV=28"
    )
    subtitle_filter = (
        f"subtitles=filename='{escaped_srt}':"
        f"charenc=UTF-8:"
        f"force_style='{force_style}'"
    )
    run_command([
        "ffmpeg",
        "-y",
        "-i",
        str(src),
        "-vf",
        subtitle_filter,
        "-c:v",
        "libx264",
        "-preset",
        "slow",
        "-crf",
        "18",
        "-pix_fmt",
        "yuv420p",
        "-c:a",
        "aac",
        "-b:a",
        "160k",
        "-ac",
        "2",
        "-movflags",
        "+faststart",
        str(tmp_dst),
    ])
    tmp_dst.replace(dst)

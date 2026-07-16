from __future__ import annotations

import json
import time
from pathlib import Path
from uuid import uuid4

from app.models import Chapter, SubtitleSegment
from app.runtime_settings import get_gemini_api_key


PROMPT = """
你是繁體中文影片字幕助理。請分析這支操作教學影片或音訊，輸出嚴格 JSON。

要求：
1. transcript：完整繁體中文逐字稿，可修正常見口語贅字，但不要改變意思。
2. subtitles：句子級字幕，時間以秒為單位，適合 SRT。每段 1 到 2 行，不要太長。
3. 字幕斷句要符合人機操作教學語氣：一個操作、一個提醒、或一個短句為一段。
4. 每段字幕建議 3 到 5 秒，最長不要超過 5 秒。
5. 每段字幕不要超過 36 個中文字；太長請拆成下一段。
6. chapters：教學章節，依操作流程分段，title 使用繁體中文。
7. 如果聽不清楚，字幕文字用「（聽不清楚）」。

JSON schema：
{
  "transcript": "文字",
  "subtitles": [{"start": 0.0, "end": 2.5, "text": "字幕"}],
  "chapters": [{"start": 0.0, "title": "章節標題"}]
}

輸出限制：
- 只輸出單一 JSON object。
- 不要輸出 Markdown。
- JSON 字串內不要放未跳脫的換行。
- 所有雙引號都必須正確跳脫。
"""


def _clean_json(text: str) -> dict:
    content = text.strip()
    if content.startswith("```"):
        content = content.strip("`")
        content = content.replace("json\n", "", 1).replace("JSON\n", "", 1)
    start = content.find("{")
    end = content.rfind("}")
    if start >= 0 and end >= start:
        content = content[start:end + 1]
    data = json.loads(content)
    if not isinstance(data, dict):
        raise ValueError("Gemini 回傳內容不是 JSON object")
    return data


def _repair_json_with_gemini(client, broken_json: str, error: Exception) -> dict:
    repair_prompt = f"""
請修復以下 JSON，使它成為可被 json.loads 解析的嚴格 JSON。

規則：
1. 只輸出修復後的 JSON object。
2. 不要輸出 Markdown，不要解釋。
3. 保留 transcript、subtitles、chapters 三個欄位。
4. subtitles 必須是陣列，每筆包含 start、end、text。
5. chapters 必須是陣列，每筆包含 start、title。
6. 所有字串內的換行、雙引號、反斜線都要正確跳脫。

原始解析錯誤：
{error}

待修復內容：
{broken_json}
"""
    response = client.models.generate_content(
        model="gemini-2.5-flash",
        contents=repair_prompt,
        config={
            "response_mime_type": "application/json",
        },
    )
    return _clean_json(response.text or "{}")


def _parse_or_repair_json(client, raw_text: str) -> dict:
    try:
        return _clean_json(raw_text)
    except (json.JSONDecodeError, ValueError) as first_error:
        try:
            return _repair_json_with_gemini(client, raw_text, first_error)
        except Exception as repair_error:
            raise RuntimeError(
                f"Gemini 回傳 JSON 格式錯誤，且自動修復失敗：{repair_error}"
            ) from repair_error


def generate_subtitles_with_gemini(video_path: Path) -> tuple[str, list[SubtitleSegment], list[Chapter]]:
    api_key = get_gemini_api_key()
    if not api_key:
        raise RuntimeError("GEMINI_API_KEY 未設定，無法產生字幕")

    from google import genai

    client = genai.Client(api_key=api_key)
    uploaded = client.files.upload(file=str(video_path))
    while uploaded.state and uploaded.state.name == "PROCESSING":
        time.sleep(5)
        uploaded = client.files.get(name=uploaded.name)
    if uploaded.state and uploaded.state.name == "FAILED":
        raise RuntimeError("Gemini File API 處理影片失敗")

    response = client.models.generate_content(
        model="gemini-2.5-flash",
        contents=[uploaded, PROMPT],
        config={
            "response_mime_type": "application/json",
        },
    )
    data = _parse_or_repair_json(client, response.text or "{}")
    transcript = str(data.get("transcript") or "")
    segments = []
    for item in data.get("subtitles") or []:
        start = float(item.get("start") or 0)
        end = float(item.get("end") or start + 2)
        if end <= start:
            end = start + 2
        segments.append(SubtitleSegment(
            id=str(item.get("id") or uuid4()),
            start=start,
            end=end,
            text=str(item.get("text") or "").strip(),
        ))
    chapters = []
    for item in data.get("chapters") or []:
        chapters.append(Chapter(
            start=float(item.get("start") or 0),
            title=str(item.get("title") or "未命名章節").strip(),
        ))
    return transcript, segments, chapters

from pydantic import BaseModel, Field


class SubtitleSegment(BaseModel):
    id: str
    start: float = Field(ge=0)
    end: float = Field(ge=0)
    text: str


class Chapter(BaseModel):
    start: float = Field(ge=0)
    title: str


class VideoRecord(BaseModel):
    id: str
    title: str
    filename: str
    stored_filename: str
    status: str
    created_at: str
    updated_at: str
    duration: float | None = None
    transcript: str = ""
    chapters: list[Chapter] = Field(default_factory=list)
    subtitles: list[SubtitleSegment] = Field(default_factory=list)
    error: str | None = None


class SubtitleUpdate(BaseModel):
    subtitles: list[SubtitleSegment]
    transcript: str = ""
    chapters: list[Chapter] = Field(default_factory=list)


class GeminiSettingsUpdate(BaseModel):
    api_key: str = Field(default="", max_length=4096)

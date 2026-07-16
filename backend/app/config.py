from pathlib import Path

from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    app_data_dir: Path = Path("/data")
    gemini_api_key: str = ""
    public_base_url: str = "http://localhost:54320"
    max_upload_mb: int = 4096
    db_backend: str = "sqlite"
    db_auto_create: bool = True
    mssql_host: str = ""
    mssql_port: int = 1433
    mssql_database: str = "NASSubtitleStudio"
    mssql_user: str = ""
    mssql_password: str = ""

    class Config:
        env_file = ".env"
        extra = "ignore"


settings = Settings()

VIDEOS_DIR = settings.app_data_dir / "videos"
SUBTITLES_DIR = settings.app_data_dir / "subtitles"
EXPORTS_DIR = settings.app_data_dir / "exports"
DB_PATH = settings.app_data_dir / "studio.db"

for path in (VIDEOS_DIR, SUBTITLES_DIR, EXPORTS_DIR):
    path.mkdir(parents=True, exist_ok=True)

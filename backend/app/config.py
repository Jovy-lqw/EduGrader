from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict


ROOT_DIR = Path(__file__).resolve().parents[2]


class AppSettings(BaseSettings):
    app_name: str = "EduGrader"
    host: str = "127.0.0.1"
    port: int = 8000
    data_dir: Path = ROOT_DIR / "data"
    browser_profile_dir: Path = ROOT_DIR / "browser-profile"
    download_dir: Path = ROOT_DIR / "downloads"
    frontend_dist_dir: Path = ROOT_DIR / "frontend" / "dist"

    model_config = SettingsConfigDict(
        env_file=(ROOT_DIR / ".env", ROOT_DIR / ".env.local"),
        env_prefix="EDUGRADER_",
        extra="ignore",
    )

    def ensure_directories(self) -> None:
        self.data_dir.mkdir(parents=True, exist_ok=True)
        self.browser_profile_dir.mkdir(parents=True, exist_ok=True)
        self.download_dir.mkdir(parents=True, exist_ok=True)


settings = AppSettings()

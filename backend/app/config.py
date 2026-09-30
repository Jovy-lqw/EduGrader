import os
from pathlib import Path
from typing import Optional

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


ROOT_DIR = Path(__file__).resolve().parents[2]


def _default_storage_root(
    *,
    platform_name: Optional[str] = None,
    local_app_data: Optional[str] = None,
) -> Path:
    if (platform_name or os.name) != "nt":
        return ROOT_DIR
    local_app_data = local_app_data or os.getenv("LOCALAPPDATA")
    base_dir = (
        Path(local_app_data)
        if local_app_data
        else Path.home() / "AppData" / "Local"
    )
    return base_dir / "EduGrader"


class AppSettings(BaseSettings):
    app_name: str = "EduGrader"
    host: str = "127.0.0.1"
    port: int = 8000
    data_dir: Path = Field(
        default_factory=lambda: _default_storage_root() / "data"
    )
    browser_profile_dir: Path = Field(
        default_factory=lambda: _default_storage_root() / "browser-profile"
    )
    download_dir: Path = Field(
        default_factory=lambda: _default_storage_root() / "downloads"
    )
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

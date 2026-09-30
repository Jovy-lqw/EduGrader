import json
import os
import tempfile
from pathlib import Path
from threading import RLock
from typing import Literal, Optional

from pydantic import BaseModel, Field, field_validator

from .config import settings


class RuntimeConfig(BaseModel):
    llm_base_url: str = "https://api.openai.com/v1"
    llm_model: str = "gpt-4o-mini"
    request_timeout_seconds: int = Field(default=60, ge=10, le=300)
    llm_max_output_tokens: int = Field(default=8192, ge=512)
    max_pdf_megabytes: int = Field(default=50, ge=1, le=500)
    max_model_characters: int = Field(default=120_000, ge=10_000, le=500_000)
    keep_downloaded_pdfs: bool = False
    require_human_confirmation_default: bool = False
    adapter_mode: Literal["zhihuishu", "mock"] = "zhihuishu"

    @field_validator("llm_base_url")
    @classmethod
    def normalize_base_url(cls, value: str) -> str:
        value = value.strip().rstrip("/")
        if not value.startswith(("http://", "https://")):
            raise ValueError("大模型地址必须以 http:// 或 https:// 开头")
        return value


class RuntimeConfigUpdate(RuntimeConfig):
    llm_api_key: Optional[str] = None


class RuntimeConfigPublic(RuntimeConfig):
    llm_api_key_configured: bool = False


class RuntimeConfigStore:
    def __init__(self, data_dir: Path = settings.data_dir) -> None:
        self._config_path = data_dir / "settings.json"
        self._secret_path = data_dir / "secrets.json"
        self._lock = RLock()

    def load(self) -> RuntimeConfig:
        with self._lock:
            if not self._config_path.exists():
                return RuntimeConfig()
            data = json.loads(self._config_path.read_text(encoding="utf-8"))
            return RuntimeConfig.model_validate(data)

    def get_api_key(self) -> Optional[str]:
        env_key = os.getenv("EDUGRADER_LLM_API_KEY")
        if env_key:
            return env_key
        with self._lock:
            if not self._secret_path.exists():
                return None
            data = json.loads(self._secret_path.read_text(encoding="utf-8"))
            return data.get("llm_api_key") or None

    def public(self) -> RuntimeConfigPublic:
        config = self.load()
        return RuntimeConfigPublic(
            **config.model_dump(),
            llm_api_key_configured=bool(self.get_api_key()),
        )

    def save(self, update: RuntimeConfigUpdate) -> RuntimeConfigPublic:
        settings.ensure_directories()
        config = RuntimeConfig.model_validate(
            update.model_dump(exclude={"llm_api_key"})
        )
        with self._lock:
            self._atomic_json_write(self._config_path, config.model_dump())
            if update.llm_api_key is not None:
                key = update.llm_api_key.strip()
                payload = {"llm_api_key": key} if key else {}
                self._atomic_json_write(self._secret_path, payload, mode=0o600)
        return self.public()

    @staticmethod
    def _atomic_json_write(
        path: Path, payload: dict, mode: int = 0o644
    ) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        fd, temp_name = tempfile.mkstemp(dir=path.parent, prefix=f".{path.name}.")
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as handle:
                json.dump(payload, handle, ensure_ascii=False, indent=2)
                handle.write("\n")
            os.chmod(temp_name, mode)
            os.replace(temp_name, path)
        finally:
            if os.path.exists(temp_name):
                os.unlink(temp_name)


runtime_config_store = RuntimeConfigStore()

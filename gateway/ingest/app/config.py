from pathlib import Path
from typing import Literal

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

Scenario = Literal["both_worn", "helmet_only", "vest_only", "none_worn", "no_person", "random"]


class Settings(BaseSettings):
    """환경변수에서 읽는다 (gateway/.env.example 참고). 이름은 대소문자 무시."""

    model_config = SettingsConfigDict(extra="ignore")

    device_token: str
    data_dir: Path = Path("/data")
    log_level: str = "INFO"

    inference_mode: Literal["http", "mock"] = "http"
    inference_url: str = "http://inference:8001"
    mock_scenario: Scenario = "random"
    infer_timeout_sec: float = Field(15.0, gt=0)
    infer_max_backoff_sec: float = Field(300.0, gt=0)

    debug_keep_compliant: bool = False
    local_image_max_mb: int = Field(2048, ge=1)
    violation_retention_days: int = Field(7, ge=1)
    cleanup_interval_sec: float = Field(60.0, gt=0)
    min_free_disk_mb: int = Field(200, ge=0)

    @field_validator("device_token")
    @classmethod
    def _token_not_empty(cls, v: str) -> str:
        if not v.strip():
            raise ValueError("DEVICE_TOKEN must not be empty")
        return v

    @property
    def images_dir(self) -> Path:
        return self.data_dir / "images"

    @property
    def local_image_max_bytes(self) -> int:
        return self.local_image_max_mb * 1024 * 1024

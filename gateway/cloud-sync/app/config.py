from pathlib import Path
from typing import Literal

from pydantic import Field, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """환경변수에서 읽는다 (gateway/.env.example 참고). 이름은 대소문자 무시."""

    model_config = SettingsConfigDict(extra="ignore")

    data_dir: Path = Path("/data")
    log_level: str = "INFO"

    sync_mode: Literal["supabase", "dry_run"] = "supabase"
    supabase_url: str = ""
    supabase_service_role_key: str = ""
    supabase_bucket: str = "violation-images"

    sync_poll_interval_sec: float = Field(2.0, gt=0)
    sync_max_backoff_sec: float = Field(300.0, gt=0)
    sync_timeout_sec: float = Field(30.0, gt=0)
    sync_batch_size: int = Field(20, ge=1)

    @model_validator(mode="after")
    def _supabase_credentials(self) -> "Settings":
        if self.sync_mode == "supabase":
            if not self.supabase_url.startswith("https://") and not self.supabase_url.startswith("http://"):
                raise ValueError("SYNC_MODE=supabase requires SUPABASE_URL (or use SYNC_MODE=dry_run)")
            if not self.supabase_service_role_key.strip():
                raise ValueError("SYNC_MODE=supabase requires SUPABASE_SERVICE_ROLE_KEY (or use SYNC_MODE=dry_run)")
        return self

    @property
    def images_dir(self) -> Path:
        return self.data_dir / "images"

    @property
    def dry_run_dir(self) -> Path:
        return self.data_dir / "sync-dryrun"

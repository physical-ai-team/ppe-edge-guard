from pathlib import Path

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """환경변수에서 읽는다 (gateway/.env.example의 inference 항목). 이름은 대소문자 무시."""

    model_config = SettingsConfigDict(extra="ignore", protected_namespaces=())

    log_level: str = "INFO"
    model_path: Path = Path("/models/yolov8n-ppehf-416-v1.onnx")
    model_classes: Path = Path("/models/classes.yaml")
    infer_imgsz: int | None = None  # 참고용. 실제 입력 크기는 ONNX 입력 shape를 따른다
    conf_threshold: float = Field(0.40, gt=0, lt=1)
    iou_threshold: float = Field(0.45, gt=0, lt=1)
    ort_num_threads: int = Field(3, ge=1)
    max_image_mb: float = Field(4.0, gt=0)  # ingest 상한(2MB)보다 여유 있게

    @property
    def max_image_bytes(self) -> int:
        return int(self.max_image_mb * 1024 * 1024)

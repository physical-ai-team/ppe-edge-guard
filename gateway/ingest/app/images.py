import io
import os
from pathlib import Path

from PIL import Image, UnidentifiedImageError

MAX_IMAGE_BYTES = 2 * 1024 * 1024  # docs/interfaces.md ①


class InvalidImage(ValueError):
    pass


def inspect_jpeg(data: bytes) -> tuple[int, int]:
    """JPEG인지 확인하고 (width, height)를 돌려준다. 헤더만 읽으므로 가볍다."""
    if not data.startswith(b"\xff\xd8"):
        raise InvalidImage("not a JPEG (missing FF D8)")
    try:
        with Image.open(io.BytesIO(data)) as img:
            if img.format != "JPEG":
                raise InvalidImage(f"unexpected format {img.format}")
            return img.size
    except (UnidentifiedImageError, OSError) as e:
        raise InvalidImage(str(e)) from e


def save_atomic(path: Path, data: bytes) -> None:
    """임시 파일에 쓰고 fsync 후 rename. 202를 돌려준 사진은 전원이 꺼져도 남아야 한다."""
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + ".tmp")
    with open(tmp, "wb") as f:
        f.write(data)
        f.flush()
        os.fsync(f.fileno())
    os.replace(tmp, path)


def delete_image(path: Path) -> None:
    path.unlink(missing_ok=True)

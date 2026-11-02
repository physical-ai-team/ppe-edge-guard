"""ESP32 대신 ingest에 사진을 보낸다 (docs/interfaces.md ① 형식 그대로).

예)
  # 합성 이미지 3장, 처리 결과까지 확인
  python gateway/scripts/fake_esp32.py --count 3 --wait
  # 폴더의 jpg를 2초 간격으로, 다른 PC의 게이트웨이로
  python gateway/scripts/fake_esp32.py --images D:/ppe-frames --interval 2 --url http://192.168.0.50:8000
  # 재시도 중복 제거 확인 (같은 X-Capture-Id 두 번 → 202, 200)
  python gateway/scripts/fake_esp32.py --count 1 --resend

토큰은 --token > 환경변수 DEVICE_TOKEN > gateway/.env 의 DEVICE_TOKEN 순서로 찾는다.
--images 없이 실행하면 Pillow로 합성 JPEG을 만든다 (ppe-ingest conda 환경에 포함).
"""
import argparse
import io
import json
import os
import secrets
import sys
import time
import urllib.error
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

RETRY_DELAYS = (1, 2, 4)  # 펌웨어와 같은 재시도 정책
FINAL = {"compliant", "pending_upload", "uploaded", "infer_failed"}


def load_token(cli_token: str | None) -> str:
    if cli_token:
        return cli_token
    if os.environ.get("DEVICE_TOKEN"):
        return os.environ["DEVICE_TOKEN"]
    env_file = Path(__file__).resolve().parents[1] / ".env"
    if env_file.exists():
        for line in env_file.read_text(encoding="utf-8").splitlines():
            if line.strip().startswith("DEVICE_TOKEN="):
                return line.split("=", 1)[1].strip()
    sys.exit("DEVICE_TOKEN not found: use --token, $env:DEVICE_TOKEN, or gateway/.env")


def iter_images(paths: list[str], count: int, size: tuple[int, int]):
    if paths:
        files = []
        for p in map(Path, paths):
            files += sorted(f for f in p.rglob("*") if f.suffix.lower() in (".jpg", ".jpeg")) if p.is_dir() else [p]
        if not files:
            sys.exit("no .jpg files found")
        for i in range(count or len(files)):
            f = files[i % len(files)]
            yield f.name, f.read_bytes()
        return
    try:
        from PIL import Image, ImageDraw
    except ImportError:
        sys.exit("Pillow not installed: use --images, or run in the ppe-ingest conda env")
    for i in range(count or 1):
        img = Image.new("RGB", size, (40 + 30 * i % 200, 90, 140))
        ImageDraw.Draw(img).text((20, 20), f"fake_esp32 #{i} {datetime.now():%H:%M:%S}", fill=(255, 255, 255))
        buf = io.BytesIO()
        img.save(buf, "JPEG", quality=85)
        yield f"synthetic-{i}", buf.getvalue()


def post(url: str, data: bytes, headers: dict) -> tuple[int, dict]:
    """(status, body). 네트워크 오류·5xx는 재시도, 4xx는 즉시 반환."""
    for attempt, delay in enumerate((0, *RETRY_DELAYS)):
        if delay:
            print(f"    retry {attempt}/{len(RETRY_DELAYS)} in {delay}s")
            time.sleep(delay)
        req = urllib.request.Request(url, data=data, headers=headers, method="POST")
        try:
            with urllib.request.urlopen(req, timeout=10) as r:
                return r.status, json.loads(r.read() or b"{}")
        except urllib.error.HTTPError as e:
            body = json.loads(e.read() or b"{}")
            if e.code < 500:
                return e.code, body
            print(f"    {e.code} {body}")
        except (urllib.error.URLError, TimeoutError, ConnectionError) as e:
            print(f"    network error: {e}")
    return 0, {"error": "gave_up"}


def wait_event(base: str, event_id: str, timeout: float = 30) -> dict | None:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        with urllib.request.urlopen(f"{base}/api/v1/events/{event_id}", timeout=5) as r:
            ev = json.loads(r.read())
        if ev["status"] in FINAL:
            return ev
        time.sleep(0.3)
    return None


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--url", default="http://localhost:8000", help="ingest base URL")
    ap.add_argument("--token")
    ap.add_argument("--device-id", default="cam-fake")
    ap.add_argument("--images", nargs="*", default=[], help="jpg files or folders")
    ap.add_argument("--count", type=int, default=0, help="number to send (default: all images, or 1 synthetic)")
    ap.add_argument("--interval", type=float, default=1.0, help="seconds between sends")
    ap.add_argument("--size", default="1280x1024", help="synthetic image size")
    ap.add_argument("--trigger", default="manual")
    ap.add_argument("--no-captured-at", action="store_true", help="simulate ESP32 without NTP")
    ap.add_argument("--resend", action="store_true", help="send each capture twice with the same X-Capture-Id")
    ap.add_argument("--wait", action="store_true", help="poll each event until inference finishes")
    args = ap.parse_args()

    base = args.url.rstrip("/")
    token = load_token(args.token)
    boot_id = secrets.token_hex(4)
    size = tuple(int(v) for v in args.size.lower().split("x"))

    for seq, (name, data) in enumerate(iter_images(args.images, args.count, size)):
        if seq:
            time.sleep(args.interval)
        headers = {
            "Content-Type": "image/jpeg",
            "X-Device-Id": args.device_id,
            "X-Device-Token": token,
            "X-Capture-Id": f"{boot_id}-{seq:06d}",
            "X-Trigger": args.trigger,
            "X-Firmware-Version": "fake-esp32",
        }
        if not args.no_captured_at:
            headers["X-Captured-At"] = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")

        for n in range(2 if args.resend else 1):
            status, body = post(f"{base}/api/v1/captures", data, headers)
            label = "resend" if n else "send"
            print(f"[{seq}] {label} {name} ({len(data)} B) -> {status} {body}")
        if args.wait and status in (200, 202):
            ev = wait_event(base, body["event_id"])
            if ev is None:
                print("    still processing after 30s (is inference running? INFERENCE_MODE=mock?)")
            else:
                s = (ev.get("result") or {}).get("summary", {})
                print(f"    -> {ev['status']}  persons={s.get('person_count')} "
                      f"missing_helmet={s.get('missing_helmet')} missing_vest={s.get('missing_vest')} "
                      f"clock_synced={ev['clock_synced']}")


if __name__ == "__main__":
    main()

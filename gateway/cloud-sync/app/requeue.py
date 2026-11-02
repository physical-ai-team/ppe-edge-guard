"""upload_failed 이벤트를 pending_upload로 되돌린다 (원인을 고친 뒤 수동 재시도).

    docker compose exec cloud-sync python -m app.requeue              # 전체
    docker compose exec cloud-sync python -m app.requeue <event_id>   # 하나만
"""
import argparse

from ppe_common import db
from ppe_common.timeutil import to_iso, utcnow

from . import store
from .config import Settings


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("event_id", nargs="?", help="이 이벤트만 되돌린다 (생략하면 upload_failed 전체)")
    args = parser.parse_args(argv)

    settings = Settings(sync_mode="dry_run")  # DATA_DIR만 필요. 업로드는 실행 중인 cloud-sync가 한다
    with db.connect(db.db_path(settings.data_dir)) as conn:
        n = store.requeue_upload_failed(conn, to_iso(utcnow()), args.event_id)
    print(f"requeued {n} upload_failed event(s) → pending_upload")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

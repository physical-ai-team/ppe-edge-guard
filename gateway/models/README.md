# gateway/models

inference 컨테이너에 `/models`(읽기 전용)로 마운트되는 폴더. 모델 파일은 **이미지에 굽지 않고 git에도 올리지 않는다** (`*.onnx`, `*.pt`는 gitignore). 팀 공유 드라이브로 배포한다.

파일명 = `model_version` (`{아키텍처}-{데이터}-{입력크기}-v{번호}`, [docs/interfaces.md](../../docs/interfaces.md#모델-버전-이름-model_version))

| 파일 | 설명 |
|---|---|
| `yolov8n-coco-416-v1.onnx` | COCO 사전학습 YOLOv8n, 입력 416. 사람만 감지 (트랙 I1 임시) |
| `yolov8n-ppe-416-v1.onnx` | Roboflow Construction Site Safety로 학습, 입력 416 (트랙 T1) |
| `classes.yaml` | `model_version`, 원본 클래스 이름 → 정규화 5종 매핑, 판정 규칙 (트랙 I1에서 추가) |

I1에서는 COCO 사전학습 모델로 먼저 동작을 확인하고, T1에서 학습한 모델로 교체한다. `.env`의 `MODEL_PATH`만 바꾸면 된다.

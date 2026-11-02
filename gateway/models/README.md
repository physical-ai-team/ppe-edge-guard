# gateway/models

inference 컨테이너에 `/models`(읽기 전용)로 마운트되는 폴더. 모델 파일은 **이미지에 굽지 않고 git에도 올리지 않는다** (`*.onnx`, `*.pt`는 gitignore).

| 파일 | 설명 |
|---|---|
| `ppe_yolov8n_416.onnx` | YOLOv8n, 입력 416×416, Colab에서 export (7단계) |
| `classes.yaml` | 클래스 인덱스 → 의미 매핑 + 위반 판정 규칙 (4단계에서 추가) |

4단계에서는 공개 사전학습 모델로 먼저 동작을 확인하고, 7단계에서 직접 학습한 모델로 교체한다.

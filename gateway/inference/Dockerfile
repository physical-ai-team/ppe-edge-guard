# 빌드 컨텍스트: gateway/  (docker compose가 지정)
# amd64(팀원 노트북) / arm64(Raspberry Pi 5) 공용
# 모델 파일은 이미지에 넣지 않는다 → gateway/models를 /models로 읽기 전용 마운트
FROM mambaorg/micromamba:2.0.5

COPY --chown=$MAMBA_USER:$MAMBA_USER inference/environment.yml /tmp/environment.yml
RUN micromamba install -y -n base -f /tmp/environment.yml && \
    micromamba clean --all --yes

WORKDIR /app
COPY --chown=$MAMBA_USER:$MAMBA_USER common/ppe_common /app/ppe_common
COPY --chown=$MAMBA_USER:$MAMBA_USER inference/app /app/app

ENV PYTHONPATH=/app \
    PYTHONUNBUFFERED=1 \
    MODEL_PATH=/models/yolov8n-ppehf-640-v1.onnx \
    MODEL_CLASSES=/models/classes.yaml

EXPOSE 8001
CMD ["uvicorn", "app.main:create_app", "--factory", "--host", "0.0.0.0", "--port", "8001"]

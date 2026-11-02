# 빌드 컨텍스트: gateway/  (docker compose가 지정)
# amd64(팀원 노트북) / arm64(Raspberry Pi 5) 공용
FROM mambaorg/micromamba:2.0.5

COPY --chown=$MAMBA_USER:$MAMBA_USER cloud-sync/environment.yml /tmp/environment.yml
RUN micromamba install -y -n base -f /tmp/environment.yml && \
    micromamba clean --all --yes

# named volume이 처음 생성될 때 이 디렉터리의 소유자(mambauser)를 물려받는다
USER root
RUN mkdir -p /data && chown $MAMBA_USER:$MAMBA_USER /data
USER $MAMBA_USER

WORKDIR /app
COPY --chown=$MAMBA_USER:$MAMBA_USER common/ppe_common /app/ppe_common
COPY --chown=$MAMBA_USER:$MAMBA_USER cloud-sync/app /app/app

ENV PYTHONPATH=/app \
    PYTHONUNBUFFERED=1 \
    DATA_DIR=/data

EXPOSE 8002
CMD ["uvicorn", "app.main:create_app", "--factory", "--host", "0.0.0.0", "--port", "8002"]

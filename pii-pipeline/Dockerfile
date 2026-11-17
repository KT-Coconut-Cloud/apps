# syntax=docker/dockerfile:1
# 빌드 컨텍스트는 저장소 루트 (rules/를 이미지에 포함하기 위함)
#   docker build -f pii-pipeline/Dockerfile .
FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1

WORKDIR /app
RUN apt-get update && apt-get upgrade -y && rm -rf /var/lib/apt/lists/*

COPY pii-pipeline/requirements.txt .
RUN pip install -r requirements.txt

COPY pii-pipeline/pipeline/ pipeline/
# 규칙은 이미지에 고정. 규칙이 바뀌면 이미지 태그(커밋 SHA)도 바뀜
COPY rules/ /rules/

ARG GIT_SHA=dev
ENV PII_PIPELINE_GIT_SHA=${GIT_SHA}

RUN useradd --uid 10001 --no-create-home appuser
USER 10001

ENTRYPOINT ["python", "-m", "pipeline"]

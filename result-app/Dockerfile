# syntax=docker/dockerfile:1
FROM python:3.12-slim AS base

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1

WORKDIR /app

COPY requirements.txt .
RUN pip install -r requirements.txt

COPY app/ app/

# 이미지 태그와 같은 커밋 SHA 7자리를 /healthz 응답에 노출
ARG GIT_SHA=dev
ENV RESULT_APP_GIT_SHA=${GIT_SHA}

# k3s securityContext(runAsNonRoot)와 맞추기 위해 비루트 사용자로 실행
RUN useradd --uid 10001 --no-create-home appuser
USER 10001

EXPOSE 8000
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]

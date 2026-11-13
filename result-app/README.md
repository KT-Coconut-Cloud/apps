# result-app

데이터 분석 신청 및 분석 결과 조회 웹 (정책기획팀, 정보보호팀)


## 화면

| 팀 | 메뉴 |
| --- | --- |
| 정책기획팀 | 분석 신청, 신청 현황, 분석 결과, 분석 데이터 현황 |
| 정보보호팀 | 반출 기록, 검토 중단 및 탐지 현황, 분석 신청 기록 |

- 등록된 분석 템플릿만 사용 (자유 SQL 조회 방식 아님)
- 5 미만 집계값 X 처리
- 조회 범위: 정제 버킷 `results/`, `reports/`


## Stack

FastAPI, Jinja2, htmx, KRDS, ECharts, pandas, boto3, pytest


## Run

```bash
pip install -r requirements-dev.txt
uvicorn app.main:app --reload
pytest
```

- 기본값: `sample-data/`를 버킷 대신 사용
- 개발용 계정: `accounts.dev.json`


## Env

| 이름 | 기본값 | AWS |
| --- | --- | --- |
| `RESULT_APP_DATA_SOURCE` | `local` | `s3` |
| `RESULT_APP_S3_BUCKET` | - | 정제 버킷 |
| `RESULT_APP_ANALYSIS_BACKEND` | `local` | `lambda` |
| `RESULT_APP_SESSION_SECRET` | `change-me` | 필수 변경 |


## CI/CD

`main` 병합 → Jenkins (pytest → build → Trivy → GHCR push) → gitops 태그 갱신 → Argo CD 배포

이미지: `ghcr.io/kt-coconut-cloud/result-app:<commit sha>`

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


## 분석 템플릿

대상 테이블: `livelihood_payment` (생계급여 지급 건 1행, 지급월 2025-12)

| 템플릿 | 집계 단위 | 조건 | 추가로 필요한 컬럼 |
| --- | --- | --- | --- |
| 시도별 생계급여 재확인 필요 지급 건 | 시도 | 지급월, 가구원 수, 연령대 | - |
| 가구원 수별 재확인 필요 지급 건 | 가구원 수 | 지급월, 시도 | - |
| 연령대별 재확인 필요 지급 건 | 연령대 | 지급월, 시도, 성별 | - |
| 재확인 필요 건의 기준 초과 정도 | 시도 | 지급월, 가구원 수 | - |
| 부양의무자 고재산 기준 점검 | 가구원 수 | 지급월, 시도, 연령대 | `obligor_asset_band` |
| 사망 이후 생계급여 지급 | 연령대 | 지급월, 시도 | `death_month` |
| 해외 장기 체류 중 생계급여 지급 | 시도 | 지급월, 연령대 | `abroad_days_band` |

- 판정 기준: `income_ratio_band` (소득인정액 ÷ 선정기준 구간)
- 분석 신청 화면은 고른 데이터셋의 반출 CSV 헤더를 읽고, 필요한 컬럼이 있는 템플릿만 보여 준다. 람다도 같은 검사를 한다.
- 새 컬럼은 반출 CSV 맨 뒤에 붙인다. Athena CSV 테이블은 컬럼을 순서로 읽는다.

- 템플릿 정의: `app/catalog.py`, Athena 쿼리: `../lambda/catalog.py` (두 파일 함께 수정)
- 샘플 데이터: `python scripts/make_sample_data.py`


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

# lambda

AWS 측 Lambda 함수 코드. 리소스 생성과 IAM은 AWS 담당이 구성

## 구성

| 함수 | 핸들러 | 호출 주체 | 하는 일 |
| --- | --- | --- | --- |
| pii-check | `check.handler` | Step Functions | 온프렘 보고서를 정제 버킷 `reports/`로 복사, CSV 해시와 행 수 대조, Macie 작업 시작 |
| pii-classify | `classify.handler` | Step Functions | Macie 결과로 판정(PASS, FAIL, ERROR), CSV를 정제 또는 격리 버킷으로 이동, `macie_result.json` 작성, FAIL과 ERROR는 SNS 알림 |
| analysis-request | `analyze.handler` | 결과 조회 앱 (Invoke) | 신청 검증과 기록, Athena 쿼리 실행, `result.csv` 저장 |

- 런타임 Python 3.12, 추가 패키지 없음. 세 함수 모두 같은 zip 사용
- 분석 템플릿 쿼리는 `catalog.py`에 있음. 5 미만 집계는 쿼리 안에서 NULL로 처리되어 Athena 밖으로 나가지 않음
- 상태 머신 정의는 `statemachine.json` (`${CheckFunctionArn}`, `${ClassifyFunctionArn}`을 실제 ARN으로 교체)

## 흐름

```text
온프렘 반출 단계 → coconut-pii-ingest/run_id=<id>/ (CSV 3개, adequacy_review.json, export_record.json 마지막)
  → EventBridge (export_record.json 생성)
  → Step Functions
       pii-check → [scan] 60초 대기 ↔ Macie 상태 조회 → pii-classify
                   [error] → pii-classify
                   [skip, 적정성 검토 탈락] → 종료 (보고서만 복사됨)

결과 조회 앱 → analysis-request → Athena → coconut-pii-clean/results/requests/<요청ID>/
```

## 패키징

```powershell
cd apps\lambda
Compress-Archive -Path *.py -DestinationPath functions.zip -Force
```

## 설정값

| 함수 | 환경변수 | 값 |
| --- | --- | --- |
| pii-check | `LANDING_BUCKET`, `CLEAN_BUCKET` | 반입, 정제 버킷 |
| pii-check | `MACIE_CUSTOM_IDENTIFIER_IDS` | Macie 사용자 지정 식별자 ID, 쉼표 구분 |
| pii-classify | `LANDING_BUCKET`, `CLEAN_BUCKET`, `QUARANTINE_BUCKET` | 반입, 정제, 격리 버킷 |
| pii-classify | `ALERT_TOPIC_ARN` | SNS `coconut-alerts` ARN |
| analysis-request | `CLEAN_BUCKET`, `ATHENA_DATABASE`, `ATHENA_WORKGROUP` | 정제 버킷, `coconut_db`, `analysis` |
| analysis-request | `MIN_CELL_SIZE` | 비공개 기준, 기본 5 |

| 함수 | 제한 시간 | 메모리 |
| --- | --- | --- |
| pii-check | 2분 | 256MB |
| pii-classify | 1분 | 256MB |
| analysis-request | 60초 | 256MB |

## AWS 설정

- EventBridge 규칙: `coconut-pii-ingest`의 Object Created, 키 suffix `export_record.json` → 상태 머신
- Macie 사용자 지정 식별자 이름은 `KR_RRN`, `KR_MOBILE_PHONE` (결과 조회 앱이 이 이름으로 표시)
- Athena 테이블은 `sql/tables.sql`로 생성. `run_id`는 partition projection이라 회차가 늘어도 추가 작업 없음
- 반입 버킷 버전 관리 필수. 분류 단계가 해시를 확인한 버전(VersionId)을 복사

## 버킷 경로

| 버킷 | 경로 | 작성 |
| --- | --- | --- |
| 반입 | `run_id=<id>/<테이블>.csv`, `adequacy_review.json`, `export_record.json` | 온프렘 반출 단계 |
| 정제 | `reports/run_id=<id>/adequacy_review.json`, `export_record.json` | pii-check |
| 정제 | `reports/run_id=<id>/macie_result.json` | pii-classify |
| 정제 | `data/<테이블>/run_id=<id>/<테이블>.csv` | pii-classify (PASS) |
| 정제 | `results/run_id=<id>/manifest.json` | pii-classify (PASS, 분석 가능 표시) |
| 정제 | `results/requests/<요청ID>/request.json`, `manifest.json`, `result.csv` | analysis-request |
| 정제 | `reports/analysis_requests/<요청ID>.json` | analysis-request |
| 격리 | `run_id=<id>/<테이블>.csv` | pii-classify (FAIL, ERROR. 한 파일이라도 탐지되면 회차 전체) |

## 테스트

```bash
pip install boto3 "moto[s3]" pytest
python -m pytest lambda
```

# 복지데이터 안심분석시스템 (결과 조회 앱)

하이브리드 클라우드 개인정보 보호 분석 인프라 프로젝트의 결과 조회 앱이다. 정책기획팀은 승인된 분석 템플릿으로 분석을 신청하고 결과를 받으며, 정보보호팀은 반출 기록과 분석 신청 기록을 확인한다.

미리보기: https://heeyeon-yang.github.io/hybrid-privacy-viewer/ (샘플 데이터로 만든 정적 화면)

## 기능

| 팀 | 화면 | 내용 |
| --- | --- | --- |
| 정책기획팀 | 분석 신청 | 데이터 기준일, 분석 템플릿, 조건, 분석 목적을 골라 신청 |
| 정책기획팀 | 신청 현황, 분석 결과 | 처리 상태 확인, 결과 차트와 표, CSV 내려받기 |
| 정책기획팀 | 분석 데이터 현황 | 분석에 쓸 수 있는 반출 데이터 목록 |
| 정보보호팀 | 반출 기록 | 회차별 적용 규칙, 적정성 검토, 반출 파일과 해시, Macie 결과 |
| 정보보호팀 | 검토 중단 및 탐지 현황 | 기간별 중단 사유, 탐지 유형, 규칙 버전별 결과 |
| 정보보호팀 | 분석 신청 기록 | 신청자, 목적, 조건, 비공개 처리된 값의 수 |

- 자유 SQL 없이 등록된 템플릿과 조건으로만 분석한다.
- 결과에서 5 미만인 집계는 X로 비공개 처리한다.
- 앱은 원본 DB와 가명처리 데이터를 읽지 않고, 정제 버킷의 `results/`, `reports/`만 읽는다.

## 기술 스택

| 구분 | 사용 기술 |
| --- | --- |
| 서버 | Python 3.12, FastAPI, Uvicorn, Jinja2, pydantic-settings |
| 화면 | KRDS, htmx, Apache ECharts |
| 데이터 | pandas (로컬 분석), boto3 (S3, Lambda) |
| 테스트 | pytest, moto |
| 배포 | Docker, GitHub Actions (정적 미리보기) |

사용한 오픈소스의 버전과 라이선스는 [THIRD_PARTY_NOTICES.md](THIRD_PARTY_NOTICES.md)에 정리했다.

## 로컬 실행

```bash
uv venv -p 3.12
uv pip install -r requirements-dev.txt
uv run uvicorn app.main:app --reload
```

`sample-data/`를 버킷처럼 읽고, AWS Lambda 대신 로컬 함수가 샘플 데이터를 집계한다. 개발용 계정은 `accounts.dev.json`에 있다.

| 환경변수 | 기본값 | AWS 연결 시 |
| --- | --- | --- |
| `RESULT_APP_DATA_SOURCE` | `local` | `s3` |
| `RESULT_APP_S3_BUCKET` | 없음 | 정제 버킷 이름 |
| `RESULT_APP_ANALYSIS_BACKEND` | `local` | `lambda` |
| `RESULT_APP_SESSION_SECRET` | `change-me` | 임의의 긴 값 |

## 테스트

```bash
uv run pytest
```

## 정적 미리보기 만들기

```bash
uv run python scripts/build_static_site.py --base /hybrid-privacy-viewer/
```

`site/`에 화면별 HTML이 생긴다. `main`에 push하면 GitHub Actions가 테스트 후 같은 명령으로 Pages에 올린다.

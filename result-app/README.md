# 복지데이터 안심분석시스템 (결과 조회 앱)

1. 정책기획팀 - 승인된 분석 템플릿으로 데이터 분석을 신청하고 결과를 확인
2. 정보보호팀 - 데이터 반출 기록과 분석 신청 기록을 확인

미리보기: https://heeyeon-yang.github.io/hybrid-privacy-viewer/ (샘플 데이터로 만든 기능 확인용 화면)

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
- 앱은 원본 DB와 가명처리 데이터를 읽지 않고, 정제 완료된 버킷의 `results/`, `reports/`만 읽는다.
  

## 실행
```bash
pip install -r requirements-dev.txt
uvicorn app.main:app --reload
pytest
```

기본값은 sample-data/를 버킷 대신 읽는다. 개발용 계정은 accounts.dev.json에 있다.

| 환경변수 | 기본값 | AWS 연결 시 |
| --- | --- | --- |
| `RESULT_APP_DATA_SOURCE` | `local` | `s3` |
| `RESULT_APP_S3_BUCKET` | 없음 | 정제 버킷 이름 |
| `RESULT_APP_ANALYSIS_BACKEND` | `local` | `lambda` |
| `RESULT_APP_SESSION_SECRET` | `change-me` | 임의의 긴 값 |


## 배포
main에 병합되면 Jenkins가 테스트, 이미지 빌드, Trivy 검사 후 ghcr.io/kt-coconut-cloud/result-app:<커밋 SHA>로 push하고 gitops 저장소의 태그를 갱신한다. 배포는 Argo CD가 맡는다.

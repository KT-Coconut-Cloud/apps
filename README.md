# apps

결과 조회 앱과 가명처리 파이프라인의 소스 코드 저장소
- 배포 매니페스트는 gitops 저장소에서 관리

## 구성

| 폴더 | 내용 |
| --- | --- |
| result-app/ | 결과 조회 웹 (FastAPI) |
| pii-pipeline/ | 가명처리, 적정성 검토, 반출 |
| rules/ | 가명처리, 적정성 검토 규칙. 변경 시 보안 담당 리뷰 필수 |
| testdata/ | 합성 데이터만 저장 |

## 작업 규칙

- main 직접 push 금지. PR과 승인 1명 필요
- 브랜치: `feat/<대상>-<내용>`, `fix/<대상>-<내용>`
- 커밋: `feat(result-app): 로그인 추가`

## 배포 흐름

main 머지 → Jenkins(검사, 빌드) → GHCR → gitops 이미지 태그 수정 → ArgoCD 배포

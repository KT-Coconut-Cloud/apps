# 사용한 오픈소스

버전은 `requirements.txt`, `requirements-dev.txt`와 `app/static/vendor/`에 포함한 파일 기준이다.

## 브라우저에서 쓰는 라이브러리 (`app/static/vendor/`에 포함)

온프렘 망에서 외부 CDN에 접속할 수 없다고 보고 파일을 저장소에 함께 넣었다.

| 이름 | 버전 | 라이선스 | 쓰는 곳 | 출처 |
| --- | --- | --- | --- | --- |
| KRDS (대한민국 정부 디자인 시스템) | 배포 파일에 버전 표기 없음 | ISC (npm `krds-uiux` 기준) | 화면 스타일, 버튼, 입력, 표, 단계 표시 | https://www.krds.go.kr, https://www.npmjs.com/package/krds-uiux |
| Pretendard GOV | KRDS 포함본 | SIL Open Font License 1.1 | 화면 글꼴 | https://github.com/orioncactus/pretendard |
| htmx | 2.0.4 | Zero-Clause BSD | 조건 입력칸 교체, 분석 상태 자동 갱신 | https://htmx.org |
| Apache ECharts | 5.6.0 | Apache License 2.0 | 결과와 집계 차트 | https://echarts.apache.org |

Apache ECharts NOTICE: Apache ECharts, Copyright 2017-2024 The Apache Software Foundation. This product includes software developed at The Apache Software Foundation (https://www.apache.org/).

## 서버 (Python)

| 이름 | 버전 | 라이선스 | 쓰는 곳 | 출처 |
| --- | --- | --- | --- | --- |
| FastAPI | 0.162.5 | MIT | 웹 서버, 라우팅 | https://github.com/fastapi/fastapi |
| Starlette | FastAPI 의존 | BSD-3-Clause | 세션 미들웨어, 정적 파일 | https://github.com/encode/starlette |
| Uvicorn | 0.54.0 | BSD-3-Clause | ASGI 서버 | https://github.com/encode/uvicorn |
| Jinja2 | 3.1.6 | BSD-3-Clause | 서버 렌더링 템플릿 | https://github.com/pallets/jinja |
| Pydantic, pydantic-settings | 2.16.2 (settings) | MIT | 보고서 파일 검증, 환경변수 설정 | https://github.com/pydantic/pydantic-settings |
| pandas | 3.0.5 | BSD-3-Clause | 결과 CSV 집계, 로컬 분석 | https://github.com/pandas-dev/pandas |
| boto3 | 1.44.1 | Apache License 2.0 | S3 읽기, Lambda 호출 | https://github.com/boto/boto3 |
| itsdangerous | 2.2.0 | BSD-3-Clause | 세션 쿠키 서명 | https://github.com/pallets/itsdangerous |
| python-multipart | 0.0.32 | Apache License 2.0 | 폼 입력 처리 | https://github.com/Kludex/python-multipart |

## 개발과 테스트

| 이름 | 버전 | 라이선스 | 쓰는 곳 | 출처 |
| --- | --- | --- | --- | --- |
| pytest | 9.1.1 | MIT | 테스트 | https://github.com/pytest-dev/pytest |
| HTTPX | 0.28.1 | BSD-3-Clause | 테스트 클라이언트 | https://github.com/encode/httpx |
| moto | 5.2.5 | Apache License 2.0 | S3 모의 테스트 | https://github.com/getmoto/moto |

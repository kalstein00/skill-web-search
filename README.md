# 웹 검색 중계

내부망 PC의 표준 라이브러리 Python 클라이언트가 LAN의 Windows 웹 중계 서버를 통해 공개 웹 정보를 얻습니다. 프로젝트 파일과 전체 대화를 전송하지 않습니다.

## 개발 환경

Python 3.12 이상과 uv를 준비한 뒤 `uv sync --locked`로 서버 개발 의존성을 설치합니다. 개발 환경 준비에는 인터넷이 필요합니다. 클라이언트 실행은 서버 의존성 없이 가능합니다.

서버: `uv run python -m relay --host 127.0.0.1 --port 8765 --token YOUR_SHARED_TOKEN`

LAN에서 사용할 때는 서버의 LAN 수신 주소를 지정하고 운영 환경에 맞게 방화벽을 구성합니다. 서버는 공유 토큰이 없으면 시작하지 않습니다. 첫 버전은 HTTP이며 토큰·검색어·본문을 전송 중 암호화하지 않습니다. 신뢰할 수 있는 사내망에서 운영해야 합니다.

클라이언트가 사용할 프로젝트 루트의 `.env`:

```dotenv
WEB_RELAY_URL=http://192.168.1.10:8765
WEB_RELAY_TOKEN=YOUR_SHARED_TOKEN
```

클라이언트: `python client.py --project-root C:/your/project fetch https://example.com`

명시한 루트의 설정만 읽으며 부모 디렉터리나 환경변수에서 설정을 가져오지 않습니다. LAN 연결에 시스템 프록시를 사용하지 않으며 서버 리다이렉트도 따르지 않습니다. 자동 재시도하지 않습니다.

## 공개 호출 계약

- `POST /fetch`: `{"url":"https://example.com"}`, `Authorization: Bearer <token>`.
- `POST /search`: `{"query":"Python documentation"}`. 동일 인증을 사용하고 `{"ok":true,"results":[{"title":"...","url":"...","snippet":"..."}]}`를 반환합니다. 기본 최대 5개이며 검색 결과가 없다는 명확한 응답만 빈 배열로 반환합니다.
- 성공: `{"ok":true,"url":"...","text":"...","truncated":false}`. 출처는 최종 URL이며 본문은 최대 20,000자입니다.
- 실패: `{"ok":false,"error":{"code":"...","message":"..."}}`.
- 설정 오류 `configuration_error`, 연결 실패 `connection_failed`, 인증 실패 `authentication_failed`, 주소 정책 위반 `address_policy`, 지원 불가 `unsupported`, 접근 차단 `access_blocked`, 시간 초과 `timeout`, 외부 응답 오류 `upstream_error`를 구별합니다.
- 클라이언트 stdout은 JSON 하나, stderr는 오류 코드이며 성공은 종료 코드 0, 실패는 1입니다.
- 일반 공개 HTML만 지원합니다. PDF·로그인·JavaScript 본문은 지원하지 않으며 판별 가능한 사유를 반환합니다. 사이트별 숨겨진 접근 요건을 완전히 탐지할 수는 없습니다. HTML 전송 크기는 압축 해제 후 4 MB로 제한합니다.
- 웹 연결의 DNS 결과와 실제 연결 주소를 일치시키며 비공개 주소·IPv6 전환 주소·비표준 숫자 주소 및 그 주소로의 리다이렉트를 차단합니다. 서버의 외부 HTTP 연결은 환경 프록시를 사용하지 않습니다.
- 애플리케이션은 요청 내용·토큰을 로그나 영속 데이터로 저장하지 않습니다.

검색 개발 환경에서 `PLAYWRIGHT_BROWSERS_PATH`를 저장소의 `.browsers` 절대 경로로 설정한 뒤 `uv run playwright install chromium`으로 전용 브라우저를 준비합니다. 같은 환경변수로 서버를 실행합니다. 검색 API는 사용하지 않습니다. CAPTCHA는 `captcha`, 브라우저 실행 문제는 `browser_error`로 반환하며 CAPTCHA 우회나 자동 재시도를 하지 않습니다. 인식하지 못한 Google 화면은 `upstream_error`입니다. 검색 브라우저의 GET 요청은 공개 주소 검증 전송 계층으로만 처리하고, 직접 네트워크 연결·WebSocket·서비스 워커·미디어 다운로드를 제한합니다. 요청별 임시 프로필은 성공·실패 후 삭제됩니다.

검색 문서의 리다이렉트는 목적지를 다시 검증해 새 브라우저 탐색으로 처리합니다. 브라우저 도구가 리다이렉트 이후 요청을 가로채지 않는 경로를 피하기 위해, 검색 부가 리소스의 리다이렉트는 `unsupported`로 실패합니다.

검색·본문 조회는 하나의 실행 슬롯을 공유하며 처리 중 새 요청은 HTTP 409의 `busy`로 즉시 반환합니다. 요청 본문 수신부터 웹 작업까지 30초로 제한하고, 클라이언트 연결이 끊기면 진행 중 작업을 취소합니다. 자원 정리가 끝난 뒤 다음 요청을 받습니다. 운영 로그에는 처리 결과 코드와 처리 시간만 남깁니다.

Windows 서버 실행은 Job Object로 브라우저·드라이버 자식 프로세스를 서버 수명에 묶습니다. 강제 종료 시 자식도 종료되며, 다음 시작에서 소유한 임시 프로필을 정리합니다. 기본 임시 경로는 OS 임시 폴더 아래 서버 수신 주소·포트별 디렉터리입니다. `--data-dir`로 전용 디렉터리를 지정할 수 있으며 서버 하나가 잠금으로 독점합니다. 다른 용도로 쓰는 디렉터리는 지정하지 마세요.

## 검증

`uv run pytest`, `uv run mypy`, `uv run ruff check relay client.py tests`.

검증 경계는 공개 클라이언트 프로세스 → 실제 HTTP 서버 → JSON 결과입니다. 외부 웹 응답만 통제합니다. Linux 호환 클라이언트 구현은 유지하지만, 사용자 지시에 따라 Linux·WSL 설치와 실행 검증은 제외합니다. Cline 검증에는 기존 모델 설정을 그대로 사용합니다.

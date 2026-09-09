# Windows x64 웹 중계 서버

`web-relay` 폴더 전체를 인터넷에 접근 가능한 Windows x64 PC에 복사합니다. 실행파일만 따로 옮기면 동작하지 않습니다. Python·Cline·개발 도구를 설치할 필요 없이 포함된 런타임과 전용 Chromium을 사용합니다.

PowerShell 실행 예시:

```powershell
& "C:/WebRelay/web-relay.exe" --host 192.168.1.10 --port 8765 --token YOUR_SHARED_TOKEN
```

수신 주소는 인터넷 PC의 LAN 주소로 지정합니다. 필요한 포트의 방화벽 설정은 조직 운영 정책을 따릅니다. 토큰은 필수이며 클라이언트 프로젝트 설정의 토큰과 같아야 합니다. 명령행 토큰은 해당 PC에서 프로세스 명령행을 조회할 권한이 있는 사용자에게 보일 수 있습니다.

종료는 실행 터미널에서 Ctrl+C를 누릅니다. Windows 서비스 등록은 제공하지 않습니다. 요청 중 새 요청은 `busy`로 반환하고, 웹 작업은 30초로 제한합니다. 연결 중단이나 실패 후 임시 프로필을 정리합니다. 강제 종료 시 브라우저 자식도 종료하며 다음 시작에서 남은 프로필을 정리합니다.

기본 임시 경로는 OS 임시 디렉터리 아래 `web-search-relay`의 수신 주소·포트별 하위 폴더입니다. 필요하면 `--data-dir C:/WebRelay/runtime`으로 이 서버만 사용할 폴더를 지정합니다. 하나의 데이터 폴더에 서버 하나만 실행할 수 있습니다.

HTTP 전송은 암호화되지 않습니다. 공유 토큰과 검색어·본문이 전송 중 암호화되지 않는 조건을 수용하는 신뢰할 수 있는 사내망에서 사용합니다. HTTPS·사용자 계정 관리·병렬 작업·재시도는 제공하지 않습니다.

Google CAPTCHA·접근 차단은 실패로 반환하며 우회하지 않습니다. 일반 공개 HTML 본문만 지원하고, PDF·로그인·JavaScript 본문은 지원 범위 밖입니다. 실제 Google 화면 변경이나 네트워크 조건에 따라 검색이 실패할 수 있습니다.

## 클라이언트

함께 제공하는 `client-skill/web-search`를 내부망 PC 프로젝트의 `.cline/skills/web-search`로 복사합니다. 내부망 PC에는 Python 3.12 이상과 uv가 사전 설치되어 있어야 합니다. 프로젝트 루트 `.env`에 다음 값을 설정합니다.

```dotenv
WEB_RELAY_URL=http://192.168.1.10:8765
WEB_RELAY_TOKEN=YOUR_SHARED_TOKEN
```

Cline의 기존 모델·공급자 설정으로 web-search 스킬을 사용합니다. 스킬이 명시한 프로젝트 설정만 읽으며, 클라이언트 실행 중 Python·패키지를 다운로드하지 않습니다.

## 빌드와 검증

저장소에서 `uv sync --locked`로 개발 환경을 준비합니다. `PLAYWRIGHT_BROWSERS_PATH`를 저장소 `.browsers`의 절대 경로로 설정하고 `uv run playwright install chromium --no-shell`을 실행합니다. 이어서 `uv run python tools/build_windows.py`를 실행합니다. `dist/web-relay`가 서버 배포 폴더이며 `dist/client-skill/web-search`가 스킬입니다. 라이브러리 버전과 잠금 파일 해시는 `build-manifest.json`에 기록됩니다.

`WEB_RELAY_BUNDLE_TEST=1`을 설정하고 `uv run pytest tests/test_bundle.py -s`로 실제 배포본을 확인합니다. 개발 PC의 PATH와 Python 환경을 비운 실행은 별도 깨끗한 Windows PC 검증과 다릅니다. 현재 검증 범위와 미충족 사항은 저장소의 `docs/validation.md`를 확인하세요. Linux·WSL 검증은 제외합니다.

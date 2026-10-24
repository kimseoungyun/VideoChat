# VideoChat

Django · Channels · Redis · WebRTC 기반의 1:1 화상 대화 서비스입니다.
카메라/마이크 미리보기, 게스트 매칭, 텍스트 채팅, 다음 상대, 대화 종료와 계정 로그인을 지원합니다.

## 변경된 구조

- 애플리케이션을 가상환경에서 분리해 `backend/`로 이동했습니다.
- 설치 라이브러리, 실행 파일, 로컬 DB, 바이트코드를 Git 추적에서 제외했습니다. 기존 Git 이력은 유지됩니다.
- 숫자 방 번호와 SQL 인원 카운터 대신 Redis Lua로 두 사용자를 원자적으로 배정합니다.
- 참가자는 브라우저의 미디어 준비 후 매칭됩니다. 서버가 offer 생성자를 지정하고, 매칭 ID가 다른 신호는 폐기합니다.
- 다음 상대는 페이지 새로고침 없이 연결만 교체합니다. 카메라 토글은 트랙을 재생성하지 않습니다.
- 15초 heartbeat, 60초 presence TTL, 연결 종료 정리로 수동 방 초기화가 필요하지 않습니다.
- Django는 5.2.18로 올렸으며 기존 DB 마이그레이션은 유지했습니다.

## 로컬 실행

Python 3.12, Redis, Node.js 22 이상(브라우저 테스트에만 필요).

PowerShell:

```powershell
python -m venv .venv
.venv\Scripts\python.exe -m pip install -r requirements.txt
$env:REDIS_URL = 'redis://127.0.0.1:6379/0'
.venv\Scripts\python.exe backend/manage.py migrate
.venv\Scripts\python.exe backend/manage.py runserver 127.0.0.1:8000
```

Redis는 별도로 먼저 실행하세요. Docker가 있으면 `docker compose up redis -d`로 실행할 수 있습니다.
전체 개발 환경은 `docker compose up --build`로 실행합니다.
접속 주소: http://127.0.0.1:8000/chat/

`.env.example`은 환경변수 목록입니다. Django는 이 파일을 자동으로 읽지 않습니다.
PowerShell의 `$env:이름` 또는 배포 환경의 환경변수 설정을 사용하세요.
기존 사용자의 DB는 `backend/db.sqlite3`에 유지되며 Git에는 포함하지 않습니다.

## 테스트

Redis를 실행한 상태에서:

```powershell
.venv\Scripts\python.exe backend/manage.py test chat main -v 2
.venv\Scripts\python.exe backend/manage.py check
npm install
npx playwright install chromium
$env:BASE_URL = 'http://127.0.0.1:8000/chat/'
npm run test:e2e
```

브라우저 테스트는 개발 서버를 별도로 실행해야 합니다. 기본 주소는 `http://127.0.0.1:8017/chat/`입니다.
기본 Chromium 대신 설치된 Edge를 쓰려면 `$env:BROWSER_CHANNEL='msedge'`를 지정하세요.
가상 카메라/마이크를 사용하므로 실제 개인정보를 촬영하지 않습니다.
스크린샷은 `test-results/`에 저장됩니다.

## 운영 환경

- HTTPS와 WebSocket 업그레이드를 지원하는 리버스 프록시 뒤에서 Daphne ASGI 서버를 실행합니다.
- `DJANGO_DEBUG=0`, 충분히 긴 `DJANGO_SECRET_KEY`, 정확한 `DJANGO_ALLOWED_HOSTS`를 설정합니다.
- 프록시가 전달 헤더를 덮어쓰도록 설정한 경우에만 `TRUST_PROXY=1`을 사용합니다.
- `python backend/manage.py collectstatic --noinput` 결과인 `backend/staticfiles/`를 프록시에서 제공합니다.
- Redis는 외부 공개 없이 애플리케이션에서만 접근하게 설정합니다. 매칭은 임시 데이터이므로 복구할 필요가 없습니다.
- 서로 다른 네트워크/방화벽 환경에서 연결하려면 실제 TURN 서버가 필요합니다. `TURN_URLS`와 coturn의 공유 비밀키에 해당하는 `TURN_SECRET`을 설정하면 1시간 유효한 자격증명을 생성합니다.
- TURN 공유 비밀키 자체는 브라우저로 전달하지 않습니다. 공개 서비스에서는 자격증명 발급과 계정 API에 IP별 요청 제한도 적용해야 합니다.
- 각 매칭 직전에 `/chat/rtc-config/`에서 새 인증정보를 받습니다. 오래 열린 페이지에서도 다음 연결에 만료된 인증정보를 재사용하지 않으며, 5초 요청 제한과 종료 시 요청 취소를 적용합니다.
- 서버는 채팅 내용을 영구 저장하지 않지만 신호 전달용 Redis 채널에는 짧게 보관됩니다. 현재 화면의 메시지는 브라우저 메모리에만 남습니다.

이 변경은 로컬 실행과 자동 검증까지 포함합니다. 외부 배포, TURN 서버 개설 및 다른 실제 네트워크 간 연결 검증은 포함하지 않습니다.
자세한 책임 분리와 제한은 [구조 문서](docs/architecture.md), 검증 결과는 [검증 문서](docs/verification.md)를 참고하세요.

기존 공개 이력의 DB/개발용 키와 라이선스 상태는 [저장소 점검](docs/repository-audit.md)에 기록했습니다.

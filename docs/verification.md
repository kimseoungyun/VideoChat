# 검증 결과

최초 검증일: 2026-10-21 / 추가 검증일: 2026-10-23

## 실행 환경

- Windows, Python 3.12.14, Django 5.2.18, Node.js 24.19.0
- Playwright 1.62.1 + 전용 Chromium 151, 가상 카메라/마이크
- 로컬 Redis 5.0.14.1 (기존 저장소의 실행 파일을 로컬 검증에만 사용)
- 개발 서버 http://127.0.0.1:8018/chat/, Redis 127.0.0.1:6380
- Docker/CI 설정은 Redis 7.4를 사용. 현재 호스트에 Docker가 없어 컨테이너 실행은 미검증.

## 자동 검증

| 경계 | 결과 | 증거 |
| --- | --- | --- |
| 매칭 서비스 | 통과 | 200개 동시 참가 요청 → 각 참가자 정확히 한 상대, 100개 고유 쌍 |
| 중복 참가/다음/종료 | 통과 | 중복 대기열 방지, 이전 상대 제외, 반복 종료 처리 |
| presence | 통과 | 사라진 참가자/대기열 정리, presence 유실 시 재접속 요구 |
| WebSocket | 통과 | 지정된 상대에게만 채팅, 잘못된 JSON/미디어 입력 거부, 이전 매칭 신호 무시 |
| WebSocket 경계 | 통과 | 잘못된 Origin 거부, 32 KiB 초과 프레임 종료 |
| 사용자 계정 | 통과 | 회원가입, 중복 이름/약한 비밀번호 거부, 로그인, POST 전용 로그아웃 |
| 상태 확인 | 통과 | /health/에서 Redis 연결 확인 |
| 브라우저 → 서버 → Redis → 브라우저 | 통과 | 실제 Redis channel layer로 두 브라우저의 매칭/신호 중계 |
| WebRTC | 통과 | 양쪽 remote video 크기 > 0, 원격 audio 트랙 live 확인 |
| 브라우저 조작 | 통과 | 텍스트 채팅, 카메라/마이크 토글, 세 번째 사용자로 다음 매칭 |
| 종료/장애 UI | 통과 | 종료 시 srcObject 해제, 소켓 종료 후 재연결, 권한 거부 시 대기열에 들어가지 않음 |
| 화면 | 통과 | 1440px 데스크톱 및 390px 모바일 스크린샷 확인, 가로 넘침 없음 |
| JS 오류 | 통과 | 브라우저 테스트에서 pageerror 없음 |

- `python backend/manage.py test chat main`: **13 tests, OK** (2026-10-23)
- `makemigrations --check --dry-run`: **No changes detected**
- `pip check`: **No broken requirements found**
- `check --deploy`: 운영용 환경변수를 지정한 상태에서 **no issues**
- `collectstatic --noinput`: 정적 파일 **134개 수집**
- `node tests/browser.cjs`: 모든 흐름 **PASS**
- `node tests/rtc-config.cjs`: RTC 설정 API 실패 시 UI 복구, 설정 요청 도중 종료 시 PeerConnection 미생성 및 로컬 미디어 해제 **PASS**
- 추가 서버 테스트: 시간 경과 후 TURN 인증정보 재발급, HMAC 검증, no-store/private 캐시 정책, 공유 비밀키 미노출, GET 전용 API **PASS**
- 이 결과는 매칭 정확성 검증입니다. 200명이 실제 영상을 동시에 송수신하는 부하 시험이나 기존 대비 속도 향상 수치를 뜻하지 않습니다.

## 남은 검증 범위

- 서로 다른 실제 네트워크/방화벽에서의 TURN relay, 실제 장치 음질/화질, Safari/Firefox 및 모바일 실기기 검증
- 실제 HTTPS 도메인과 운영 프록시, TURN 자격증명 및 릴레이 용량
- Docker 빌드/실행, GitHub Actions 원격 실행 (설정 파일만 추가)
- 대규모 WebSocket/영상 부하 시험, 운영 지연시간/오류율 측정
- 외부 서비스 배포는 수행하지 않음. GitHub 업로드의 실제 브랜치/커밋 결과는 작업 완료 보고를 기준으로 확인.

스크린샷은 로컬 `test-results/lobby-desktop.png`, `connected-desktop.png`, `lobby-mobile.png`에 있습니다.
테스트 DB와 실행 로그는 `.runtime/`에 있으며 Git 추적 대상에서 제외됩니다.

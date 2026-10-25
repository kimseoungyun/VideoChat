# 검증 결과

최초 검증일: 2026-10-21 / 추가 검증일: 2026-10-23, 2026-10-25

## 실행 환경

- Windows 11, Python 3.12.14, Django 5.2.18, Daphne 4.1.2, Node.js 24
- Playwright 1.62.1 + 전용 Chromium(revision 1234), 가상 카메라/마이크
- 로컬 Redis 5.0.14.1 (127.0.0.1:6380, 검증 전용)
- GitHub Actions `ubuntu-latest`: Redis 7.4, Docker, Playwright Chromium·Firefox. 로컬에 Docker가 없어서 컨테이너는 CI에서 검증

## 자동 검증

| 경계 | 결과 | 증거 |
| --- | --- | --- |
| 매칭 서비스 | 통과 | 200개 동시 참가 요청 → 각 참가자 정확히 한 상대, 100개 고유 쌍 |
| 중복 참가/다음/종료 | 통과 | 중복 대기열 방지, 이전 상대 제외(상대가 먼저 나간 뒤 next 포함), 반복 종료 처리 |
| presence | 통과 | 사라진 참가자/대기열 정리, presence 유실 시 재접속 요구 |
| WebSocket | 통과 | 지정된 상대에게만 채팅, 잘못된 JSON/미디어 입력 거부, 이전 매칭 신호 및 다음 상대 이후 늦은 메시지 미전달 |
| WebSocket 경계 | 통과 | 잘못된 Origin 거부, 32 KiB 초과 프레임 종료, IP별 동시 연결 한도(4029)와 종료 후 슬롯 반환 |
| 신고/차단 | 통과 | 잘못된 사유 거부, 신고 시 상대 종료 알림, 매칭당 1회, 신고한 신원 간 재매칭 차단, 서로 다른 신고자 누적 시 제한, 같은 IP 게스트 간 신고가 IP 전체를 막지 않음, DB에 원본 IP 미저장 |
| 사용자 계정 | 통과 | 회원가입, 중복 이름/약한 비밀번호 거부, 로그인, POST 전용 로그아웃 |
| 요청 제한 | 통과 | 로그인 실패 5회 후 올바른 비밀번호도 429, 성공 시 카운터 초기화, 가입/RTC 설정 한도 |
| 지표 | 통과 | 운영 모드에서 토큰 없으면 404, 토큰으로 Prometheus 형식 응답 |
| 상태 확인 | 통과 | /health/에서 Redis 연결 확인 |
| 브라우저 → 서버 → Redis → 브라우저 | 통과 | 실제 Redis channel layer로 두 브라우저의 매칭/신호 중계 |
| WebRTC | 통과 | 양쪽 remote video 크기 > 0, 원격 audio 트랙 live 확인 |
| 브라우저 조작 | 통과 | 텍스트 채팅, 카메라/마이크 토글, 세 번째 사용자로 다음 매칭, 신고 다이얼로그 취소/제출 |
| 종료/장애 UI | 통과 | 종료 시 srcObject 해제, 소켓 종료 후 재연결, 권한 거부 시 대기열에 들어가지 않음 |
| 화면 | 통과 | 1440px 데스크톱 및 390px 모바일 스크린샷 확인, 가로 넘침 없음 |
| JS 오류 | 통과 | 브라우저 테스트에서 pageerror 없음 |
| 브라우저 간 상호 운용 | 통과 (CI) | Chromium ↔ Firefox 영상 협상, 양방향 채팅, 종료 알림 |
| 레거시 계정 마이그레이션 | 통과 | CustomUser 행이 같은 비밀번호 해시로 auth.User에 이동, 이름이 겹치면 기존 계정 유지. 로컬 DB 복사본에서도 확인(원본 DB 미변경) |
| channel layer 과부하 | 통과 | 수신함 용량 5·20(로컬)·50(Linux)에서 동시 접속 100% 매칭. 매칭 알림 전달 실패를 주입하면 재시도로 매칭되고, 3번 실패하면 둘 다 대기열로 돌아가 다음 사용자와 매칭 |
| Docker | 통과 (CI) | 개발 compose 기동 후 `/health/`, 운영 이미지(Daphne, DEBUG=0)에서 `/metrics/` 토큰 검사와 실제 WebSocket 200명 매칭 100% |

- `python backend/manage.py test chat main`: **28 tests, OK** (2026-10-25, 로컬과 CI)
- `makemigrations --check --dry-run`: **No changes detected**
- `check --deploy`: 운영용 환경변수(무작위 SECRET_KEY)를 지정한 상태에서 **no issues**
- `collectstatic --noinput`: 정적 파일 **134개 수집**
- `npm run test:e2e` (`browser.cjs`, `rtc-config.cjs`, `report.cjs`): 모두 **PASS**, 신고 테스트를 앞뒤로 연속 실행해도 통과
- 부하: [benchmarks/README.md](benchmarks/README.md) — Windows에서 1,000명·4개 프로세스, Linux CI에서 1,000명·1개 프로세스와 2,000명·4개 프로세스 동시 접속 모두 100% 정상 매칭, 원본 대비 비교 포함
- `npm run test:interop`: Windows에서는 Playwright Firefox의 가짜 장치가 `AbortError`로 열리지 않아 CI(Linux)에서만 실행합니다.

## 남은 검증 범위

- 서로 다른 실제 네트워크/방화벽에서의 TURN relay, 실제 장치 음질/화질, Safari 및 모바일 실기기 검증
- 실제 HTTPS 도메인과 운영 프록시(nginx), coturn 설정과 릴레이 용량
- 클라이언트와 서버를 다른 머신에 둔 부하 시험, 영상 미디어 부하
- 외부 서비스 배포는 수행하지 않음(서버·도메인·TURN 계정 필요)

스크린샷은 로컬 `test-results/`에 생성됩니다(`lobby-desktop.png`, `connected-desktop.png`, `lobby-mobile.png`, `report-dialog.png`).

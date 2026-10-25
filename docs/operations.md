# 운영 기능

남용 방지, 신고/차단, 모니터링 지표의 동작과 설정입니다. 모든 카운터와 제한 상태는 Redis에 있으므로 ASGI 프로세스가 여러 개여도 같은 값을 봅니다.

## 신원(identity)

| 사용자 | 신원 | 비고 |
| --- | --- | --- |
| 로그인 사용자 | `u<id>` | 계정 단위 |
| 게스트 | `ip` + HMAC-SHA256(SECRET_KEY, IP) 앞 20자 | 원본 IP는 Redis 키와 DB에 저장하지 않음. **가명 처리**이며 익명 처리는 아님: IPv4는 경우의 수가 2^32뿐이라 SECRET_KEY를 가진 사람은 전수 대입으로 되돌릴 수 있음. SECRET_KEY 접근을 개인정보 접근과 같은 수준으로 관리 |

- 같은 공유기·NAT의 게스트는 신원을 공유합니다. 그래서 IP별 한도를 넉넉하게 잡았고, 같은 신원끼리의 신고는 신원 차단에 반영하지 않습니다([T9](troubleshooting.md#t9-같은-공유기-사용자끼리-신고하면-그-ip-전체가-매칭-불가)).
- 프록시 뒤에서는 `TRUST_PROXY=1`일 때만 `X-Forwarded-For`의 **마지막** 값을 사용합니다. 그 앞의 값은 클라이언트가 위조할 수 있습니다.
- **상대에게 보이는 정보**: 영상이 P2P로 연결되므로 ICE 후보에 담긴 공인 IP를 상대 브라우저가 볼 수 있습니다. TURN을 설정하고 `ICE_RELAY_ONLY=1`로 두면 모든 영상이 중계 서버를 거쳐 IP가 노출되지 않습니다. 대신 TURN 대역폭 비용이 늘어납니다. 운영 정책에 맞춰 고르고, 이용자에게 고지해야 합니다. 로그인 사용자의 아이디는 채팅 이름으로 상대에게 표시됩니다.

## 요청 제한

| 대상 | 기본값 | 초과 시 |
| --- | --- | --- |
| IP당 동시 WebSocket | 10 (`WS_MAX_PER_IP`) | 연결 수락 후 close 4029 → "연결이 너무 많습니다" 안내, 자동 재연결 안 함 |
| IP당 새 WebSocket | 분당 60 (`WS_CONNECT_RATE`) | close 4029 |
| 소켓당 메시지 | 순간 100개, 초당 30개 | close 4008 |
| 매칭 요청(join/next) | 소켓당 1초 1회 | 오류 메시지 |
| 로그인 시도 (사이트와 `/admin/` 모두) | 계정당 15분 5회, IP당 15분 20회 | HTTP 429. 비밀번호를 검사하기 **전에** 시도를 세므로 동시 요청으로도 넘을 수 없음. 성공하면 계정 카운터를 초기화하고 IP 카운트 1회를 되돌림 |
| 신고 | 신원당 시간당 20건 (`REPORTS_PER_HOUR`) | 오류 안내. 신고마다 대화가 함께 저장되므로 저장소 공격을 막음 |
| 회원가입 | IP당 시간당 5회 | HTTP 429 |
| RTC 설정(TURN 자격증명) | IP당 분당 300회 (`RTC_CONFIG_PER_IP`) | HTTP 429, "같은 네트워크에서 연결 요청이 많습니다" 안내. 매칭마다 1회씩 쓰므로 NAT 공유를 고려해 넉넉하게 둠([T13](troubleshooting.md#t13-같은-ip를-쓰는-사용자가-많으면-정상-사용자도-연결에-실패)) |

- 동시 연결 수는 Redis sorted set에 소켓마다 만료 시각을 넣어 셉니다. 15초 ping마다 갱신하고 연결 종료 시 제거합니다. 프로세스가 강제 종료돼도 60초 뒤 자동으로 빠집니다.
- 고정 윈도 카운터는 `INCR`과 첫 증가 시 `EXPIRE`를 Lua 하나로 실행합니다. 따라서 만료 없는 키가 남지 않습니다.
- Redis 장애 시 제한은 **통과(fail-open)** 시킵니다. 장애는 `/health/`가 503으로 알리고, 매칭 자체가 Redis를 쓰므로 서비스는 어차피 중단됩니다. 로그인 잠금이 Redis 장애 때문에 모든 사용자를 막지 않게 하려는 선택입니다.
- Redis가 내려가면 channels_redis의 수신 루프가 먼저 실패해 WebSocket이 close 1011로 끊깁니다(애플리케이션이 처리할 수 있는 지점 이전). 브라우저는 1/2/4초 간격으로 3번 재연결한 뒤 "서버에 연결할 수 없습니다"를 안내합니다.

## 신고와 차단

1. 대화 중이거나 상대가 방금 나간 뒤 **신고** 버튼 → 사유(부적절한 노출 / 욕설·괴롭힘 / 스팸·광고 / 기타) 선택
2. 서버 처리
   - 신고자 신원과 대상 신원을 24시간 서로 매칭하지 않음(양방향 확인)
   - 24시간 동안 **서로 다른 신고자 3명**이 신고하면 대상 신원을 1시간 매칭에서 제외. 같은 신고자의 중복 신고는 1회로 셈
   - 대화 종료(상대에게는 일반 종료와 같은 "상대방이 대화를 종료했어요"로 표시해 신고 사실을 알리지 않음)
   - `chat.Report`에 신고자/대상 신원, 사유, match_id, 제한 여부, **최근 대화** 저장 → Django admin에서 검토
3. 매칭당 신고는 1회만 받습니다. 제한된 사용자가 매칭을 요청하면 남은 시간을 안내합니다.

**신고 근거(최근 대화)**
- 신고자의 consumer가 최근 2개 매칭에서 **서버가 직접 중계한** 채팅을 매칭당 최대 20줄(줄당 500자) 메모리에 들고 있다가, 신고할 때만 `Report.evidence`에 저장합니다. 브라우저가 보낸 대화 기록을 받지 않으므로 신고자가 내용을 꾸며낼 수 없습니다.
- 평소에는 아무것도 저장하지 않습니다. 직전 매칭까지 신고할 수 있으므로, 신고 다이얼로그를 여는 사이 새 상대가 연결돼도 이전 상대를 정확히 신고합니다([코드 리뷰 #3](code-review.md)).
- **보관 기한**: `REPORT_RETENTION_DAYS`(기본 90일)가 지난 신고와 대화는 `python manage.py purge_reports`로 삭제합니다. 매일 실행하도록 cron이나 systemd timer에 등록합니다. 기한은 신고 다이얼로그에 표시됩니다.
- 신고 다이얼로그와 채팅창에 "신고 시 최근 메시지 보관"을 안내합니다. admin에는 줄 수와 대화(신고자/신고 대상 구분, 시각)를 읽기 전용으로 보여 줍니다.
- 영상은 서버를 거치지 않으므로 근거로 남지 않습니다.

| 설정 | 기본값 |
| --- | --- |
| `REPORT_BAN_THRESHOLD` | 3 (서로 다른 신고자) |
| `REPORT_BAN_SECONDS` | 3600 |
| 신고 집계 창 / 상호 차단 기간 | 24시간 |

**알려진 한계**
- 게스트 제한은 IP 기준이므로 IP를 바꾸면 피할 수 있습니다. 반대로 휴대폰 통신사 NAT처럼 IP를 많은 사람이 공유하면 무관한 사용자가 함께 제한될 수 있습니다. 그래서 제한 시간을 1시간으로 짧게 두었습니다.
- 로그인 사용자는 로그아웃 후 게스트로 접속하면 계정 제한을 피할 수 있습니다.
- 여러 IP를 가진 사람이 한 명을 집중 신고하면 제한을 걸 수 있습니다. 자동 제한은 짧게 유지하고 영구 조치는 admin 검토로 결정하는 전제입니다.
- 영상 내용을 서버가 보지 않으므로(P2P) 자동 유해성 판별은 없습니다.

## 지표 (`/metrics/`)

Prometheus 텍스트 형식입니다. `DEBUG=1`이면 열려 있고, 운영에서는 `METRICS_TOKEN`을 설정해야 하며 `Authorization: Bearer <토큰>`이 없으면 404를 반환합니다.

| 지표 | 종류 | 의미 |
| --- | --- | --- |
| `videochat_ws_active` | gauge | 살아 있는 WebSocket 수 |
| `videochat_queue_waiting` | gauge | 매칭 대기 중인 사용자 수 |
| `videochat_ws_connections_total` | counter | 수락한 WebSocket |
| `videochat_ws_rejected_total{reason}` | counter | `ip_limit`, `connect_rate`, `banned` |
| `videochat_matches_total` | counter | 성사된 매칭 |
| `videochat_match_wait_seconds` | histogram | 매칭까지 기다린 시간(0.5–60초 버킷). 대기열에 있던 쪽과 바로 매칭된 쪽 모두 기록 |
| `videochat_reports_total`, `videochat_bans_total` | counter | 신고, 자동 제한 |
| `videochat_http_ratelimited_total{scope}` | counter | `login`, `signup`, `rtc_config` |
| `videochat_channel_full_dropped_total` | counter | 수신함이 약 3초 동안 가득 차 있어 버린 메시지. 0이 아니면 `CHANNEL_CAPACITY` 상향 또는 프로세스 추가 |
| `videochat_matches_by_preference_total{kind}` | counter | `shared`(공통 관심사), `open`(선호 없음), `relaxed`(기다리다 조건 완화) |
| `videochat_calls_total{outcome}` | counter | 매칭 후 영상이 `connected` / `failed` (브라우저 보고, 매칭당 1회) |
| `videochat_call_setup_seconds` | histogram | 매칭부터 영상 연결까지(0.5–20초 버킷) |
| `videochat_calls_relayed_total` | counter | TURN을 거쳐 연결된 통화 |
| `videochat_ice_restarts_total{outcome}` | counter | 미디어 끊김 후 ICE restart 결과 `recovered` / `failed` |
| `videochat_sessions_suspended_total` | counter | 통화 중 소켓이 끊겨 재개를 기다린 횟수 |
| `videochat_sessions_resumed_total{outcome}` | counter | 재개 결과 `resumed` / `expired` |

## 모니터링 스택

`docker compose --profile monitoring up`을 실행하면 개발 서버와 함께 Prometheus(:9090)와 Grafana(:3000, 익명 읽기)가 뜹니다. 설정 파일은 `deploy/monitoring/`에 있습니다.

- `prometheus.yml`: 15초 간격으로 `/metrics/`를 수집합니다. 운영에서는 `authorization: {credentials: <METRICS_TOKEN>}`을 넣고 모든 Daphne 프로세스를 대상으로 지정합니다.
- `alerts.yml`: 경보 6개를 정의합니다. CI에서 `promtool check rules`로 검증합니다.

  | 경보 | 조건 |
  | --- | --- |
  | VideoChatDown | 지표 수집 실패 1분 |
  | CallSetupFailing | 15분간 영상 연결 실패율 20% 초과 |
  | MatchWaitHigh | 매칭 대기 p95 30초 초과 |
  | ChannelLayerDropping | channel layer 메시지 유실 발생 |
  | ResumesExpiring | 끊긴 통화의 절반 이상이 재개되지 못함 |
  | AbuseRejectSpike | WebSocket 거부 초당 1회 초과 |

- `grafana/`: 데이터소스와 "VideoChat overview" 대시보드를 자동으로 등록합니다. 대시보드에는 접속·대기 수, 통화 연결 성공률, TURN 경유 비율, 선호별 매칭, 대기·연결 시간, 끊김 복구, 거부·신고, channel layer 유실이 들어 있습니다.

CI의 docker job이 이 스택을 실제로 띄워 세 가지를 확인합니다. Prometheus가 `videochat_ws_active`를 수집하는지, 경보 규칙이 로드되는지, Grafana에 대시보드가 등록되는지입니다.

## 통화·매칭 설정

| 설정 | 기본값 | 의미 |
| --- | --- | --- |
| `RESUME_GRACE_SECONDS` | 15 | 소켓이 끊긴 통화를 재개 대기로 유지하는 시간([통화 품질](call-quality.md)) |
| `MATCH_RELAX_SECONDS` | 10 | 언어·관심사 조건을 지키며 기다리는 최대 시간([선호 매칭](matching-preferences.md)) |

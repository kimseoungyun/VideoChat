# 운영 기능

남용 방지, 신고/차단, 모니터링 지표의 동작과 설정입니다. 모든 카운터와 제한 상태는 Redis에 있으므로 ASGI 프로세스가 여러 개여도 같은 값을 봅니다.

## 신원(identity)

| 사용자 | 신원 | 비고 |
| --- | --- | --- |
| 로그인 사용자 | `u<id>` | 계정 단위 |
| 게스트 | `ip` + HMAC-SHA256(SECRET_KEY, IP) 앞 20자 | 원본 IP는 Redis 키와 DB에 저장하지 않음 |

- 같은 공유기·NAT의 게스트는 신원을 공유합니다. 그래서 IP별 한도를 넉넉하게 잡았고, 같은 신원끼리의 신고는 신원 차단에 반영하지 않습니다([T9](troubleshooting.md#t9-같은-공유기-사용자끼리-신고하면-그-ip-전체가-매칭-불가)).
- 프록시 뒤에서는 `TRUST_PROXY=1`일 때만 `X-Forwarded-For`의 **마지막** 값을 사용합니다. 그 앞의 값은 클라이언트가 위조할 수 있습니다.

## 요청 제한

| 대상 | 기본값 | 초과 시 |
| --- | --- | --- |
| IP당 동시 WebSocket | 10 (`WS_MAX_PER_IP`) | 연결 수락 후 close 4029 → "연결이 너무 많습니다" 안내, 자동 재연결 안 함 |
| IP당 새 WebSocket | 분당 60 (`WS_CONNECT_RATE`) | close 4029 |
| 소켓당 메시지 | 순간 100개, 초당 30개 | close 4008 |
| 매칭 요청(join/next) | 소켓당 1초 1회 | 오류 메시지 |
| 로그인 실패 | 계정당 15분 5회, IP당 15분 20회 | HTTP 429. 제한 중에는 비밀번호 검증 자체를 하지 않음. 성공 시 계정 카운터 초기화 |
| 회원가입 | IP당 시간당 5회 | HTTP 429 |
| RTC 설정(TURN 자격증명) | IP당 분당 60회 | HTTP 429 |

- 동시 연결 수는 Redis sorted set에 소켓마다 만료 시각을 넣어 셉니다. 15초 ping마다 갱신하고 연결 종료 시 제거합니다. 프로세스가 강제 종료돼도 60초 뒤 자동으로 빠집니다.
- 고정 윈도 카운터는 `INCR`과 첫 증가 시 `EXPIRE`를 Lua 하나로 실행합니다. 따라서 만료 없는 키가 남지 않습니다.
- Redis 장애 시 제한은 **통과(fail-open)** 시킵니다. 장애는 `/health/`가 503으로 알리고, 매칭 자체가 Redis를 쓰므로 서비스는 어차피 중단됩니다. 로그인 잠금이 Redis 장애 때문에 모든 사용자를 막지 않게 하려는 선택입니다.

## 신고와 차단

1. 대화 중이거나 상대가 방금 나간 뒤 **신고** 버튼 → 사유(부적절한 노출 / 욕설·괴롭힘 / 스팸·광고 / 기타) 선택
2. 서버 처리
   - 신고자 신원과 대상 신원을 24시간 서로 매칭하지 않음(양방향 확인)
   - 24시간 동안 **서로 다른 신고자 3명**이 신고하면 대상 신원을 1시간 매칭에서 제외. 같은 신고자의 중복 신고는 1회로 셈
   - 대화 종료(상대에게는 일반 종료와 같은 "상대방이 대화를 종료했어요"로 표시해 신고 사실을 알리지 않음)
   - `chat.Report`에 신고자/대상 신원, 사유, match_id, 제한 여부 저장 → Django admin에서 검토
3. 매칭당 신고는 1회만 받습니다. 제한된 사용자가 매칭을 요청하면 남은 시간을 안내합니다.

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

```yaml
# prometheus.yml
scrape_configs:
  - job_name: videochat
    metrics_path: /metrics/
    scheme: https
    authorization: { credentials: <METRICS_TOKEN> }
    static_configs: [{ targets: ['videochat.example.com'] }]
```

추천 경보: `/health/` 503, `rate(videochat_ws_rejected_total[5m])` 급증(공격 또는 한도 과소), `histogram_quantile(0.95, rate(videochat_match_wait_seconds_bucket[10m])) > 30`(사용자 부족 또는 매칭 장애).

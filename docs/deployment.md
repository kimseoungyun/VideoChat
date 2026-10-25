# 운영 배포

> 아래 구성은 설계 문서입니다. 이 저장소에서는 Docker와 외부 서버 없이 검증했으므로, **프록시와 coturn 설정은 실제 서버에서 실행해 본 적이 없습니다.** 처음 배포할 때 점검 목록의 모든 항목을 실제로 확인하세요.

## 구성

```text
브라우저 ──HTTPS/WSS──▶ nginx ──▶ Daphne × N (127.0.0.1:8001..)
   │                      │            │
   │                      └ /static/   └──▶ Redis (내부망 전용)
   └──── UDP/TCP 3478, 5349 ────▶ coturn (영상/음성 릴레이, 직접 연결 실패 시)
```

- Daphne 프로세스는 CPU 코어 수만큼 띄우고 nginx `upstream`으로 나눕니다. 매칭 상태는 Redis에만 있으므로 sticky session이 필요 없습니다.
- 회원 DB는 현재 SQLite입니다. 호스트가 한 대일 때만 사용하고, 여러 대로 늘리기 전에 PostgreSQL로 옮깁니다.

## 환경변수

| 이름 | 운영 값 |
| --- | --- |
| `DJANGO_DEBUG` | `0` |
| `DJANGO_SECRET_KEY` | 50자 이상 무작위. 게스트 IP 해시에도 쓰이므로 바꾸면 기존 신고 누적/차단이 초기화됨 |
| `DJANGO_ALLOWED_HOSTS` | 서비스 도메인 |
| `TRUST_PROXY` | `1` (nginx가 `X-Forwarded-For`, `X-Forwarded-Proto`를 덮어쓸 때만) |
| `REDIS_URL` | 내부망 주소 |
| `REDIS_POOL_SIZE` | 프로세스당 Redis 연결 상한, 기본 50 |
| `TURN_URLS`, `TURN_SECRET` | `turn:turn.example.com:3478?transport=udp,turns:turn.example.com:5349?transport=tcp`, coturn `static-auth-secret`과 같은 값 |
| `METRICS_TOKEN` | Prometheus 스크레이프용 무작위 토큰 |
| `WS_MAX_PER_IP`, `WS_CONNECT_RATE` | 기본 10, 60. 학교/회사처럼 IP 공유가 많은 대상이면 상향 |

## nginx (예시)

```nginx
upstream videochat { server 127.0.0.1:8001; server 127.0.0.1:8002; }
server {
    listen 443 ssl http2;
    server_name videochat.example.com;
    # ssl_certificate ...;
    location /static/ { alias /srv/videochat/backend/staticfiles/; expires 7d; }
    location /metrics/ { allow 10.0.0.0/8; deny all; proxy_pass http://videochat; }
    location / {
        proxy_pass http://videochat;
        proxy_http_version 1.1;
        proxy_set_header Upgrade $http_upgrade;
        proxy_set_header Connection "upgrade";
        proxy_set_header Host $host;
        proxy_set_header X-Forwarded-For $remote_addr;   # 덮어쓰기: 클라이언트 값은 버림
        proxy_set_header X-Forwarded-Proto $scheme;
        proxy_read_timeout 75s;                          # heartbeat 15초보다 충분히 길게
    }
}
```

`X-Forwarded-For`를 `$proxy_add_x_forwarded_for`로 이어 붙이지 않고 `$remote_addr`로 **덮어써야** 합니다. 애플리케이션은 마지막 값을 신뢰하지만, 덮어쓰면 클라이언트가 보낸 값이 아예 남지 않아 더 단순하고 안전합니다.

## coturn (예시)

```ini
listening-port=3478
tls-listening-port=5349
use-auth-secret
static-auth-secret=<TURN_SECRET와 같은 값>
realm=turn.example.com
# cert=/etc/ssl/turn.pem  pkey=/etc/ssl/turn.key
no-cli
no-multicast-peers
denied-peer-ip=10.0.0.0-10.255.255.255
denied-peer-ip=172.16.0.0-172.31.255.255
denied-peer-ip=192.168.0.0-192.168.255.255
total-quota=200
```

`denied-peer-ip`는 TURN 서버가 내부망으로 가는 중계 통로로 악용되는 것을 막습니다. 애플리케이션은 매칭할 때마다 `<만료시각>:<uuid>` 사용자명과 HMAC-SHA1 자격증명(1시간 유효)을 발급하고, 이는 coturn의 `use-auth-secret` 방식과 같습니다.

## 배포 순서

```bash
pip install -r requirements.txt
python backend/manage.py migrate --noinput          # chat.0001(신고), main.0003(Room 제거) 포함
python backend/manage.py collectstatic --noinput
DJANGO_DEBUG=0 ... python backend/manage.py check --deploy
daphne -b 127.0.0.1 -p 8001 myproj.asgi:application  # backend/에서, 프로세스 수만큼 (systemd 등)
```

`main.0003_delete_room`은 원본의 임시 매칭 테이블(`main_room`)을 삭제합니다. 이 테이블에는 접속 중인 방 번호만 있었으므로 보존할 데이터가 없습니다.

## 점검 목록

- [ ] `https://<도메인>/health/`가 200, Redis를 내리면 503
- [ ] 서로 다른 네트워크(예: 휴대폰 LTE ↔ 사내 Wi-Fi)에서 영상 연결. 브라우저 `chrome://webrtc-internals`에서 relay 후보가 선택되는지 확인
- [ ] 같은 IP에서 11번째 탭이 "연결이 너무 많습니다" 안내를 받는지(`WS_MAX_PER_IP=10`)
- [ ] 로그인 6번째 실패 시 429
- [ ] `/metrics/`가 토큰 없이는 404, 외부망에서 nginx가 차단
- [ ] 신고 후 Django admin의 Report 목록에 원본 IP가 아닌 해시 신원이 보이는지
- [ ] `videochat_match_wait_seconds` 경보 규칙 등록([운영 기능](operations.md#지표-metrics))

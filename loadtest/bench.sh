#!/usr/bin/env bash
# Linux counterpart of bench.ps1: start N Daphne processes per case, run the matching load
# test, append JSON lines to $OUT. Linux uses epoll, so one process can hold thousands of sockets.
# Usage: REDIS_URL=redis://127.0.0.1:6379/0 LABEL=linux REPEAT=3 loadtest/bench.sh
set -euo pipefail
cd "$(dirname "$0")/.."
OUT=${OUT:-docs/benchmarks/results.jsonl}
LABEL=${LABEL:-linux}
REPEAT=${REPEAT:-3}
export DJANGO_DEBUG=1 DATABASE_PATH=${DATABASE_PATH:-/tmp/videochat-load.sqlite3}
# Every simulated user shares 127.0.0.1, so lift the per-IP limits for this run only.
export WS_MAX_PER_IP=100000 WS_CONNECT_RATE=100000
python backend/manage.py migrate -v 0

serve() {
  pids=() bases=()
  for i in $(seq 0 $(($1 - 1))); do
    port=$((8020 + i))
    (cd backend && exec daphne -b 127.0.0.1 -p "$port" myproj.asgi:application >/dev/null 2>"/tmp/daphne-$port.log") &
    pids+=($!) bases+=("http://127.0.0.1:$port")
  done
  for base in "${bases[@]}"; do
    for _ in $(seq 30); do curl -fs "$base/health/" >/dev/null && break; sleep 1; done
  done
  BASES=$(IFS=,; echo "${bases[*]}")
}

stop() { kill "${pids[@]}" 2>/dev/null || true; wait "${pids[@]}" 2>/dev/null || true; }

# workers clients ramp
cases=("1 1000 0" "1 1000 10" "4 2000 0" "4 2000 10")
for workers in 1 4; do
  serve "$workers"
  for c in "${cases[@]}"; do
    read -r w clients ramp <<<"$c"
    [ "$w" = "$workers" ] || continue
    for _ in $(seq "$REPEAT"); do
      sleep 5  # let the previous cohort's disconnects drain
      python loadtest/matching.py --base "$BASES" --clients "$clients" --ramp "$ramp" --timeout 30 |
        python -c "import json,sys,datetime; r=json.loads(sys.stdin.read()); r.update(label='$LABEL', date=str(datetime.date.today())); print(json.dumps(r, ensure_ascii=False))" |
        tee -a "$OUT"
    done
  done
  stop
done

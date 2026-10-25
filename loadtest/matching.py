"""Burst matching load test over real WebSockets.

current: N clients join /ws/chat/ at once; checks each match_id has exactly two members,
         then measures join→matched latency and chat relay latency.
legacy:  replays the original flow (GET /chat/start_chat/ → /ws/chat/<room>/) and counts
         how many clients ended up in a room of exactly two.
"""
import argparse
import asyncio
import json
import random
import time
import urllib.error
import urllib.request
from collections import Counter
from urllib.parse import urlsplit

import websockets


def percentile(values, p):
    if not values:
        return None
    values = sorted(values)
    return values[min(len(values) - 1, round(p / 100 * (len(values) - 1)))]


def summary_ms(values):
    return {k: round(v * 1000, 1) if v is not None else None for k, v in
            (('p50', percentile(values, 50)), ('p95', percentile(values, 95)),
             ('p99', percentile(values, 99)), ('max', max(values) if values else None))}


def server(args, i):
    """Round-robin clients over every --base so matching must work across processes."""
    base = args.bases[i % len(args.bases)]
    parts = urlsplit(base)
    return base, ('wss' if parts.scheme == 'https' else 'ws') + '://' + parts.netloc + '/ws/chat/'


async def current_client(i, args, result, release):
    await asyncio.sleep(random.uniform(0, args.ramp))
    base, url = server(args, i)
    phase = 'connect'
    try:
        async with websockets.connect(url, origin=base, open_timeout=args.timeout,
                                      max_queue=None) as ws:
            assert json.loads(await ws.recv())['type'] == 'ready'
            joined = time.perf_counter()
            await ws.send(json.dumps({'type': 'join'}))
            deadline = joined + args.timeout
            phase = 'match'
            while True:
                data = json.loads(await asyncio.wait_for(ws.recv(), deadline - time.perf_counter()))
                if data['type'] == 'matched':
                    break
                if data['type'] == 'error':
                    result['errors'].append(data['message'])
            # The non-initiator found a waiting peer: its latency is pure server work.
            result['match' if data['initiator'] else 'instant'].append(time.perf_counter() - joined)
            result['pairs'][i] = data['match_id']
            phase = 'chat'
            if data['initiator']:
                await ws.send(json.dumps({'type': 'chat', 'match_id': data['match_id'],
                                          'message': repr(time.perf_counter())}))
            else:
                while True:
                    reply = json.loads(await asyncio.wait_for(ws.recv(), deadline - time.perf_counter()))
                    if reply['type'] == 'chat':
                        result['chat'].append(time.perf_counter() - float(reply['message']))
                        break
            # Senders stay until every receiver is done: a match that ends first
            # correctly drops its in-flight messages.
            result['done'] += 1
            await release.wait()
    except (asyncio.TimeoutError, OSError, websockets.WebSocketException) as error:
        result['failures'][f'{phase}:{type(error).__name__}'] += 1


def legacy_room(args, base):
    class NoRedirect(urllib.request.HTTPRedirectHandler):
        def redirect_request(self, *a, **k):
            return None
    try:
        urllib.request.build_opener(NoRedirect).open(base + '/chat/start_chat/', timeout=args.timeout)
    except urllib.error.HTTPError as error:
        if error.code == 302:
            return error.headers['Location'].strip('/').split('/')[-1]
        raise
    raise RuntimeError('no redirect')


async def legacy_client(i, args, result, release):
    await asyncio.sleep(random.uniform(0, args.ramp))
    started = time.perf_counter()
    base, url = server(args, i)
    try:
        room = await asyncio.to_thread(legacy_room, args, base)
        async with websockets.connect(f'{url}{room}/', open_timeout=args.timeout) as ws:
            await asyncio.wait_for(ws.recv(), args.timeout)
            result['match'].append(time.perf_counter() - started)
            result['pairs'][i] = room
            result['done'] += 1
            await release.wait()
    except (asyncio.TimeoutError, OSError, RuntimeError, urllib.error.URLError,
            websockets.WebSocketException) as error:
        result['failures'][type(error).__name__] += 1


async def main(args):
    result = {'match': [], 'instant': [], 'chat': [], 'pairs': {}, 'done': 0, 'errors': [],
              'failures': Counter()}
    release = asyncio.Event()
    client = legacy_client if args.mode == 'legacy' else current_client
    started = time.perf_counter()
    tasks = [asyncio.create_task(client(i, args, result, release)) for i in range(args.clients)]
    # Hold every socket open until the whole cohort is settled, so leaving never frees a peer.
    while time.perf_counter() - started < args.ramp + args.timeout + 2:
        if result['done'] + sum(result['failures'].values()) >= args.clients:
            break
        await asyncio.sleep(0.05)
    elapsed = time.perf_counter() - started
    await asyncio.sleep(args.settle)
    release.set()
    await asyncio.gather(*tasks, return_exceptions=True)

    sizes = Counter(Counter(result['pairs'].values()).values())
    paired = sizes.get(2, 0) * 2
    report = {
        'mode': args.mode, 'servers': len(args.bases), 'clients': args.clients, 'ramp_s': args.ramp,
        'correctly_paired': paired, 'correctly_paired_pct': round(100 * paired / args.clients, 1),
        'room_sizes': {str(k): v for k, v in sorted(sizes.items())},
        'unassigned': args.clients - len(result['pairs']),
        'failures': dict(result['failures']), 'server_errors': len(result['errors']),
        'settle_s': round(elapsed, 2),
    }
    if args.mode == 'current':
        report['queued_wait_ms'] = summary_ms(result['match'])
        report['join_to_matched_ms'] = summary_ms(result['instant'])
        report['chat_relay_ms'] = summary_ms(result['chat'])
    else:
        report['request_to_room_ms'] = summary_ms(result['match'])
    print(json.dumps(report, ensure_ascii=False))
    if args.json:
        with open(args.json, 'a', encoding='utf-8') as file:
            file.write(json.dumps(report, ensure_ascii=False) + '\n')


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument('--base', default='http://127.0.0.1:8020',
                        help='comma-separated server URLs; clients are spread round-robin')
    parser.add_argument('--mode', choices=['current', 'legacy'], default='current')
    parser.add_argument('--clients', type=int, default=200)
    parser.add_argument('--ramp', type=float, default=1.0, help='spread connection starts over N seconds')
    parser.add_argument('--timeout', type=float, default=20.0)
    parser.add_argument('--settle', type=float, default=0.5)
    parser.add_argument('--json', help='append the report as one JSON line')
    args = parser.parse_args()
    args.bases = [base.rstrip('/') for base in args.base.split(',')]
    asyncio.run(main(args))

"""Count Redis commands per matching step and per relayed chat message (one pair, one server).

Resets Redis INFO commandstats, so point it at a dedicated Redis instance.
"""
import argparse
import asyncio
import json

import websockets
from redis.asyncio import Redis


async def stats(redis):
    info = await redis.info('commandstats')
    return {name.removeprefix('cmdstat_'): value['calls'] for name, value in info.items()}


def delta(after, before):
    return {k: v - before.get(k, 0) for k, v in after.items() if v - before.get(k, 0)}


async def main(args):
    redis = Redis.from_url(args.redis)
    await redis.config_resetstat()
    origin = args.base.rstrip('/')
    url = origin.replace('http', 'ws', 1) + '/ws/chat/'
    async with websockets.connect(url, origin=origin) as a, websockets.connect(url, origin=origin) as b:
        for ws in (a, b):
            await ws.recv()
        before = await stats(redis)
        await a.send(json.dumps({'type': 'join'}))
        await a.recv()
        await b.send(json.dumps({'type': 'join'}))
        match = json.loads(await b.recv())
        await a.recv()
        await asyncio.sleep(0.2)
        matched = await stats(redis)
        for i in range(args.messages):
            await a.send(json.dumps({'type': 'chat', 'match_id': match['match_id'], 'message': str(i)}))
            await b.recv()
        await asyncio.sleep(0.2)
        relayed = await stats(redis)
    report = {'match_pair': delta(matched, before),
              'per_chat_message': {k: round(v / args.messages, 2) for k, v in delta(relayed, matched).items()}}
    print(json.dumps(report))
    await redis.aclose()


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--base', default='http://127.0.0.1:8020')
    parser.add_argument('--redis', default='redis://127.0.0.1:6379/0')
    # Stays inside the per-socket burst allowance (100 frames, then 30/s → close 4008).
    parser.add_argument('--messages', type=int, default=50)
    asyncio.run(main(parser.parse_args()))

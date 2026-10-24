-- Atomic transitions shared by every ASGI worker.
local queue, prefix = KEYS[1], KEYS[2]
local action, id, ttl, match = ARGV[1], ARGV[2], tonumber(ARGV[3]), ARGV[4]
local clock = redis.call('TIME')
local now = tonumber(clock[1]) + tonumber(clock[2]) / 1000000
local key = prefix .. id
redis.call('ZREMRANGEBYSCORE', queue, '-inf', now)
local peer = redis.call('HGET', key, 'peer')
local room = redis.call('HGET', key, 'match')
if action == 'leave' then
    redis.call('ZREM', queue, id)
    if peer and redis.call('HGET', prefix .. peer, 'match') == room then
        redis.call('HDEL', prefix .. peer, 'peer', 'match')
        redis.call('HSET', prefix .. peer, 'blocked', id)
    end
    -- Keep the last peer exclusion briefly, including across next.
    redis.call('DEL', key)
    if peer then
        redis.call('HSET', key, 'blocked', peer)
        redis.call('EXPIRE', key, ttl)
    end
    return {peer or '', room or ''}
end
if peer and redis.call('HGET', prefix .. peer, 'match') ~= room then
    redis.call('HDEL', key, 'peer', 'match')
    redis.call('HSET', key, 'blocked', peer)
    peer, room = false, false
end
if action == 'state' then
    if redis.call('EXISTS', key) == 0 then return {'expired'} end
    redis.call('EXPIRE', key, ttl)
    if peer then return {'matched', peer, room} end
    if redis.call('ZSCORE', queue, id) then
        redis.call('ZADD', queue, now + ttl, id)
        return {'waiting'}
    end
    return {'idle'}
end
if peer then return {'matched', peer, room} end
redis.call('HSET', key, 'alive', '1')
redis.call('EXPIRE', key, ttl)
if redis.call('ZSCORE', queue, id) then return {'waiting'} end
local blocked = redis.call('HGET', key, 'blocked')
local candidates = redis.call('ZRANGE', queue, 0, 99)
for _, other in ipairs(candidates) do
    local otherkey = prefix .. other
    if redis.call('EXISTS', otherkey) == 0 or redis.call('HEXISTS', otherkey, 'peer') == 1 then
        redis.call('ZREM', queue, other)
    elseif other ~= id and other ~= blocked and redis.call('HGET', otherkey, 'blocked') ~= id then
        redis.call('ZREM', queue, other)
        redis.call('HSET', key, 'peer', other, 'match', match)
        redis.call('HSET', otherkey, 'peer', id, 'match', match)
        return {'new_match', other, match}
    end
end
redis.call('ZADD', queue, now + ttl, id)
return {'waiting'}

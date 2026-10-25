-- Atomic transitions shared by every ASGI worker.
-- KEYS: queue, member prefix, base prefix. ARGV: action, channel, ttl, new match id, identity.
local queue, prefix, base = KEYS[1], KEYS[2], KEYS[3]
local action, id, ttl, match, who = ARGV[1], ARGV[2], tonumber(ARGV[3]), ARGV[4], ARGV[5]
local metrics = base .. 'metrics'
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
    -- Keep the last peer exclusion briefly, including across next, even when the
    -- peer already left first and only the exclusion remains.
    local exclude = peer or redis.call('HGET', key, 'blocked')
    redis.call('DEL', key)
    if exclude then
        redis.call('HSET', key, 'blocked', exclude)
        redis.call('EXPIRE', key, ttl)
    end
    return {peer or '', room or ''}
end
if action == 'unpair' then
    -- The peer could not be told about the match: put both back in the queue unblocked.
    if peer and redis.call('HGET', prefix .. peer, 'match') == room then
        redis.call('HDEL', prefix .. peer, 'peer', 'match')
        redis.call('ZADD', queue, now + ttl, peer)
    end
    redis.call('HDEL', key, 'peer', 'match')
    redis.call('ZADD', queue, now + ttl, id)
    return {'waiting'}
end
if peer and redis.call('HGET', prefix .. peer, 'match') ~= room then
    redis.call('HDEL', key, 'peer', 'match')
    redis.call('HSET', key, 'blocked', peer)
    peer, room = false, false
end
local function matched()
    return {'matched', peer, room, redis.call('HGET', prefix .. peer, 'who') or ''}
end
if action == 'state' then
    if redis.call('EXISTS', key) == 0 then return {'expired'} end
    redis.call('EXPIRE', key, ttl)
    if peer then return matched() end
    if redis.call('ZSCORE', queue, id) then
        redis.call('ZADD', queue, now + ttl, id)
        return {'waiting'}
    end
    return {'idle'}
end
if peer then return matched() end
local banned = redis.call('TTL', base .. 'ban:' .. who)
if banned > 0 then
    redis.call('HINCRBY', metrics, 'ws_rejected_total{reason="banned"}', 1)
    return {'banned', tostring(banned)}
end
redis.call('HSET', key, 'alive', '1', 'who', who)
redis.call('EXPIRE', key, ttl)
if redis.call('ZSCORE', queue, id) then return {'waiting'} end
local blocked = redis.call('HGET', key, 'blocked')
local blocks = base .. 'blocks:'
local function observe(wait)
    for _, le in ipairs({'0.5', '1', '2', '5', '10', '30', '60'}) do
        if wait <= tonumber(le) then
            redis.call('HINCRBY', metrics, 'match_wait_seconds_bucket{le="' .. le .. '"}', 1)
        end
    end
    redis.call('HINCRBYFLOAT', metrics, 'match_wait_seconds_sum', wait)
    redis.call('HINCRBY', metrics, 'match_wait_seconds_count', 1)
end
local candidates = redis.call('ZRANGE', queue, 0, 99)
for _, other in ipairs(candidates) do
    local otherkey = prefix .. other
    if redis.call('EXISTS', otherkey) == 0 or redis.call('HEXISTS', otherkey, 'peer') == 1 then
        redis.call('ZREM', queue, other)
    elseif other ~= id and other ~= blocked and redis.call('HGET', otherkey, 'blocked') ~= id then
        local otherwho = redis.call('HGET', otherkey, 'who') or ''
        -- Reports block both directions for the identity, not just this connection.
        if redis.call('SISMEMBER', blocks .. who, otherwho) == 0
                and redis.call('SISMEMBER', blocks .. otherwho, who) == 0 then
            redis.call('ZREM', queue, other)
            redis.call('HSET', key, 'peer', other, 'match', match)
            redis.call('HSET', otherkey, 'peer', id, 'match', match)
            redis.call('HINCRBY', metrics, 'matches_total', 1)
            observe(0)
            observe(math.max(0, now - (tonumber(redis.call('HGET', otherkey, 'since')) or now)))
            return {'new_match', other, match}
        end
    end
end
redis.call('HSET', key, 'since', tostring(now))
redis.call('ZADD', queue, now + ttl, id)
return {'waiting'}

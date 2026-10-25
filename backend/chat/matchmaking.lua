-- Atomic transitions shared by every ASGI worker.
-- KEYS: queue, member prefix, base prefix.
-- ARGV: action, channel, ttl, new match id, identity, extra, seconds.
--   join:    extra = "<lang>|<tag>,<tag>" preferences, seconds = relax-after wait
--   suspend: seconds = reconnect grace;  resume: extra = resume token
local queue, prefix, base = KEYS[1], KEYS[2], KEYS[3]
local action, id, ttl, match, who = ARGV[1], ARGV[2], tonumber(ARGV[3]), ARGV[4], ARGV[5]
local extra, seconds = ARGV[6] or '', tonumber(ARGV[7] or '0')
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
if action == 'release' or action == 'unpair' then
    -- The peer could not be told about the match. release: requeue only the peer so the
    -- caller can join again right away; unpair: give up for now and requeue both.
    if peer and redis.call('HGET', prefix .. peer, 'match') == room then
        redis.call('HDEL', prefix .. peer, 'peer', 'match')
        redis.call('ZADD', queue, now + ttl, peer)
    end
    redis.call('HDEL', key, 'peer', 'match')
    if action == 'release' then return {'idle'} end
    redis.call('ZADD', queue, now + ttl, id)
    return {'waiting'}
end
if action == 'suspend' then
    -- The socket dropped mid-call: keep the pair for `seconds` so a new socket can resume it.
    if not peer or redis.call('HGET', prefix .. peer, 'match') ~= room then return {'', ''} end
    redis.call('HSET', key, 'suspended', '1')
    redis.call('EXPIRE', key, seconds)
    return {peer, room}
end
if action == 'resume' then
    local tokenkey = base .. 'resume:' .. extra
    local old = redis.call('GET', tokenkey)
    if not old or peer then return {'expired'} end
    local oldkey = prefix .. old
    local opeer, oroom = redis.call('HGET', oldkey, 'peer'), redis.call('HGET', oldkey, 'match')
    if not opeer or redis.call('HGET', prefix .. opeer, 'match') ~= oroom then return {'expired'} end
    -- Move the membership to the new channel; the token is single use.
    local kept = redis.call('HMGET', oldkey, 'who', 'tags', 'lang')
    redis.call('DEL', oldkey, tokenkey)
    redis.call('ZREM', queue, id)
    redis.call('DEL', key)
    redis.call('HSET', key, 'alive', '1', 'who', kept[1] or who, 'peer', opeer, 'match', oroom,
        'tags', kept[2] or '', 'lang', kept[3] or '')
    redis.call('EXPIRE', key, ttl)
    redis.call('HSET', prefix .. opeer, 'peer', id)
    -- The identity stays the original one: a network switch changes the guest's IP hash.
    return {'resumed', opeer, oroom, old, kept[1] or who}
end
if peer and redis.call('HGET', prefix .. peer, 'match') ~= room then
    redis.call('HDEL', key, 'peer', 'match')
    redis.call('HSET', key, 'blocked', peer)
    peer, room = false, false
end

local function tagset(text)
    local set, count = {}, 0
    for tag in string.gmatch(text or '', '[^,]+') do set[tag] = true; count = count + 1 end
    return set, count
end
local function common(a, b)
    local mine, shared = tagset(a), {}
    for tag in string.gmatch(b or '', '[^,]+') do
        if mine[tag] then table.insert(shared, tag) end
    end
    return shared
end
local function matched()
    local mine = redis.call('HGET', key, 'tags')
    local theirs = redis.call('HGET', prefix .. peer, 'tags')
    return {'matched', peer, room, redis.call('HGET', prefix .. peer, 'who') or '',
        table.concat(common(mine, theirs), ',')}
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
local lang, tags = string.match(extra, '^([^|]*)|?(.*)$')
local queued = redis.call('ZSCORE', queue, id)
redis.call('HSET', key, 'alive', '1', 'who', who, 'lang', lang or '', 'tags', tags or '')
redis.call('EXPIRE', key, ttl)
local mysince = queued and tonumber(redis.call('HGET', key, 'since')) or now
local _, mycount = tagset(tags)
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
-- Preferences are honoured until either side has waited `seconds`; then anyone will do.
-- Among eligible candidates the most shared interests win, then the longest wait.
local best, bestscore, bestkind
for _, other in ipairs(redis.call('ZRANGE', queue, 0, 99)) do
    local otherkey = prefix .. other
    if redis.call('EXISTS', otherkey) == 0 or redis.call('HEXISTS', otherkey, 'peer') == 1 then
        redis.call('ZREM', queue, other)
    elseif other ~= id and other ~= blocked and redis.call('HGET', otherkey, 'blocked') ~= id then
        local otherwho = redis.call('HGET', otherkey, 'who') or ''
        -- Reports block both directions for the identity, not just this connection.
        if redis.call('SISMEMBER', blocks .. who, otherwho) == 0
                and redis.call('SISMEMBER', blocks .. otherwho, who) == 0 then
            local olang = redis.call('HGET', otherkey, 'lang') or ''
            local otags = redis.call('HGET', otherkey, 'tags') or ''
            local _, ocount = tagset(otags)
            local shared = #common(tags, otags)
            local langok = lang == '' or olang == '' or lang == olang
            local tagok = (mycount == 0 and ocount == 0) or shared > 0
            local osince = tonumber(redis.call('HGET', otherkey, 'since')) or now
            local relaxed = math.max(now - mysince, now - osince) >= seconds
            if (langok and tagok) or relaxed then
                if not best or shared > bestscore then
                    best, bestscore = other, shared
                    bestkind = (langok and tagok) and (shared > 0 and 'shared' or 'open') or 'relaxed'
                end
                -- Nothing can beat sharing every interest (or any match, without interests).
                if bestscore == mycount then break end
            end
        end
    end
end
if best then
    local otherkey = prefix .. best
    redis.call('ZREM', queue, best, id)
    redis.call('HSET', key, 'peer', best, 'match', match)
    redis.call('HSET', otherkey, 'peer', id, 'match', match)
    redis.call('HINCRBY', metrics, 'matches_total', 1)
    redis.call('HINCRBY', metrics, 'matches_by_preference_total{kind="' .. bestkind .. '"}', 1)
    observe(now - mysince)
    observe(math.max(0, now - (tonumber(redis.call('HGET', otherkey, 'since')) or now)))
    return {'new_match', best, match}
end
if not queued then redis.call('HSET', key, 'since', tostring(now)) end
redis.call('ZADD', queue, now + ttl, id)
return {'waiting'}

from uuid import uuid4
from django.test import override_settings
from . import limits


def isolated_prefix(test):
    """Run a test against its own Redis key prefix and delete those keys afterwards."""
    prefix = 'test:' + uuid4().hex + ':'

    def cleanup():
        redis = limits.sync_redis()
        keys = list(redis.scan_iter(match=prefix + '*'))
        if keys:
            redis.delete(*keys)
    test.addCleanup(cleanup)
    override = override_settings(MATCHMAKING_PREFIX=prefix)
    override.enable()
    test.addCleanup(override.disable)

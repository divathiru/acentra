"""Shared rate-limiter instance.

Import from here in any router or middleware.
In production, swap the storage backend to Redis::

    from slowapi import Limiter
    limiter = Limiter(
        key_func=get_remote_address,
        storage_uri="redis://redis:6379",
    )
"""

from slowapi import Limiter
from slowapi.util import get_remote_address

limiter = Limiter(
    key_func=get_remote_address,
    default_limits=["200/minute"],
)

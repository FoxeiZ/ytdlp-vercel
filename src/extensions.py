from __future__ import annotations

from typing import TYPE_CHECKING

from upstash_redis import Redis
from upstash_redis.errors import UpstashError

if TYPE_CHECKING:
    from flask import Flask


class RedisWrapper:
    _instance: RedisWrapper | None = None

    def __init__(self, client: Redis | None):
        self._client = client

    @classmethod
    def get_instance(cls) -> RedisWrapper | None:
        return cls._instance

    @classmethod
    def get_client(cls) -> Redis | None:
        inst = cls.get_instance()
        if inst is None:
            raise RuntimeError("Redis is not initialised or unavailable.")
        return inst._client

    @classmethod
    def is_initialised(cls) -> bool:
        return cls.get_instance() is not None

    @classmethod
    def from_app(cls, app: Flask) -> RedisWrapper:
        client: Redis | None = None
        try:
            client = Redis(
                url=app.config["KV_REST_API_URL"],
                token=app.config["KV_REST_API_TOKEN"],
                allow_telemetry=False,
            )
            app.logger.info("Successfully connected to Redis.")
        except (UpstashError, KeyError) as e:
            app.logger.critical(f"Could not connect to Redis: {e}. Caching and cookie persistence will be disabled.")
        instance = cls(client)
        cls._instance = instance
        return instance

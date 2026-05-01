from __future__ import annotations

import contextlib
import functools
import logging
from io import StringIO
from typing import TYPE_CHECKING

from yt_dlp import YoutubeDL
from yt_dlp.cookies import YoutubeDLCookieJar

from ..extensions import RedisWrapper

if TYPE_CHECKING:
    from typing import Any

    from upstash_redis import Redis


class YTDLRedisCookieJar(YoutubeDLCookieJar):
    KEY = "ytdl_cookies"

    def __init__(self, redis: Redis, *args: Any, **kwargs: Any) -> None:
        super().__init__(*args, **kwargs)
        self.redis = redis
        if not self.filename:
            self.filename = self.KEY
        self._io = StringIO()
        self._logger = logging.getLogger(__name__)

    @contextlib.contextmanager
    def open(self, file: str, *, write: bool = False):  # type: ignore[override]
        if file != self.KEY:
            self._logger.warning("YoutubeDLCookieJar proxy open fallback to default behavior - %s", file)
            return super().open(file, write=write)

        self._logger.warning("YoutubeDLCookieJar proxy open via Redis - %s", file)

        if write:
            yield self._io
            self.redis.set(file, self._io.getvalue())
        else:
            value = self.redis.get(file)
            if value is not None:
                self._io = StringIO(value)
            else:
                self._io = StringIO()
            yield self._io

    def save(self, filename: str | None = None, ignore_discard: bool = True, ignore_expires: bool = True) -> None:
        if filename is None and self.filename == self.KEY:
            filename = self.filename

        if filename != self.KEY:
            self._logger.warning("YoutubeDLCookieJar proxy save fallback to default behavior - %s", filename)
            return super().save(filename, ignore_discard, ignore_expires)

        self._logger.info("YoutubeDLCookieJar proxy save via Redis - %s", filename)
        self.redis.set(self.KEY, self._io.getvalue())


def load_cookies_from_redis(redis: Redis) -> YTDLRedisCookieJar:
    cookie_jar = YTDLRedisCookieJar(redis)
    cookie_jar.load(cookie_jar.KEY)
    return cookie_jar


class YTDLP(YoutubeDL):
    def __init__(self, *args: Any, **kwargs: Any) -> None:
        super().__init__(*args, **kwargs)

    @functools.cached_property
    def cookiejar(self) -> YTDLRedisCookieJar:
        redis = RedisWrapper.get_client()
        assert redis is not None, "Redis client is not available"
        return load_cookies_from_redis(redis)

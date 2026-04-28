from __future__ import annotations

import json
import logging
import re
import urllib.parse
from difflib import SequenceMatcher
from typing import TYPE_CHECKING, Any, ClassVar

import requests
from flask import Flask, Response, jsonify, request
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

if TYPE_CHECKING:
    from collections.abc import Callable, Iterator


from flask import Blueprint, current_app

logger = logging.getLogger(__name__)
bp = Blueprint("lyrics", __name__)

__all__ = ("register_routes",)


def create_error_response(message: str, code: int = 500, exc: Exception | None = None) -> tuple[Response, int]:
    if exc:
        current_app.logger.error(f"Exception caught: {message}", exc_info=exc)
    else:
        current_app.logger.warning(f"Returning error to client: {message} (Code: {code})")
    return jsonify({"success": False, "error": message}), code


class LyricsPluginBase:
    def __init__(self, info: dict[str, Any], to_screen: Callable[[str], None] | None = None):
        self.title = info.get("title")
        self.artist = info.get("artist")
        self.album = info.get("album") or ""

        if not self.artist and ("artists" in info or "creators" in info or "uploader" in info):
            self.artist = (info.get("artists") or info.get("creators") or [info.get("uploader", "")])[0]

        self._to_screen: Callable[[str], None] = to_screen or current_app.logger.info

    def to_screen(self, message: str):
        self._to_screen(f"{self.__class__.__name__}: {message}")

    def get_synced(self) -> str | None:
        raise NotImplementedError("Subclasses must implement this method")

    def get_unsynced(self) -> str | None:
        raise NotImplementedError("Subclasses must implement this method")


class MusixMatchLyricsPlugin(LyricsPluginBase):
    HEADERS: ClassVar[dict[str, str]] = {
        "authority": "apic-desktop.musixmatch.com",
        "cookie": "mxm_bab=AB",
        "user-agent": "Mozilla/5.0",
    }
    session = None
    token = None

    @classmethod
    def _ensure_session(cls) -> requests.Session:
        if cls.session is None:
            cls.session = requests.Session()
            cls.session.headers.update(cls.HEADERS)
        return cls.session

    @classmethod
    def _get_token(cls, force_refresh: bool = False) -> str | None:
        cls._ensure_session()
        if not force_refresh and cls.token:
            return cls.token
        return cls._refresh_token()

    @classmethod
    def _refresh_token(cls) -> str | None:
        try:
            session = cls._ensure_session()
            response = session.get(
                "https://apic-desktop.musixmatch.com/ws/1.1/token.get",
                params={"app_id": "web-desktop-app-v1.0"},
                timeout=10,
            )
            response.raise_for_status()
            data = response.json()
            if data["message"]["header"]["status_code"] == 200:
                cls.token = data["message"]["body"]["user_token"]
                return cls.token
        except Exception as e:
            current_app.logger.error(f"Error fetching MusixMatch token: {e}")
        return None

    def find_lyrics(self, *, album: str = "", artist: str = "", title: str = "", renew: bool = False) -> dict[str, Any] | None:
        session = self._ensure_session()
        token = self._get_token(force_refresh=renew)
        if not token:
            self.to_screen("Could not obtain MusixMatch token.")
            return None

        params = {
            "q_album": album,
            "q_artist": artist,
            "q_track": title,
            "usertoken": token,
            "app_id": "web-desktop-app-v1.0",
            "format": "json",
            "namespace": "lyrics_richsynched",
            "subtitle_format": "mxm",
        }
        try:
            response = session.get("https://apic-desktop.musixmatch.com/ws/1.1/macro.subtitles.get", params=params, timeout=10)
            response.raise_for_status()
        except Exception as e:
            self.to_screen(repr(e))
            return None

        r = response.json()
        status_code = r["message"]["header"]["status_code"]

        if status_code != 200:
            if r["message"]["header"].get("hint") == "renew" or status_code == 401:
                if not renew:
                    self.to_screen("Token expired, renewing...")
                    return self.find_lyrics(album=album, artist=artist, title=title, renew=True)
                else:
                    self.to_screen("Token rejected after renewal.")
                    return None
            self.to_screen(f"API Error: {status_code}")
            return None

        body = r["message"]["body"]["macro_calls"]
        track_status = body["matcher.track.get"]["message"]["header"].get("status_code")

        if track_status != 200:
            if track_status == 404:
                self.to_screen("No lyrics/songs found.")
            elif track_status == 401:
                self.to_screen("Timed out or auth error.")
            else:
                self.to_screen(f"Matcher error: {body['matcher.track.get']['message']['header']}")
            return None

        lyrics_msg = body["track.lyrics.get"]["message"]
        if lyrics_msg.get("header", {}).get("status_code") == 200 and lyrics_msg["body"]["lyrics"]["restricted"]:
            self.to_screen("Restricted lyrics.")
            return None

        return body

    def get_unsynced(self) -> str | None:
        if not self.artist or not self.title:
            return None
        body = self.find_lyrics(artist=self.artist, title=self.title)
        if body is None:
            return None
        lyrics_body = body["track.lyrics.get"]["message"].get("body")
        if lyrics_body is None:
            return None
        lyrics: str = lyrics_body["lyrics"]["lyrics_body"]
        if lyrics:
            return "\n".join(filter(None, lyrics.split("\n")))
        return None

    def get_synced(self) -> str | None:
        if not self.artist or not self.title:
            return None
        body = self.find_lyrics(artist=self.artist, title=self.title)
        if body is None:
            return None
        subtitle_body = body["track.subtitles.get"]["message"].get("body")
        if subtitle_body is None:
            return None
        subtitle_list = subtitle_body.get("subtitle_list", [])
        if not subtitle_list:
            return None
        subtitle = subtitle_list[0].get("subtitle")
        if subtitle:
            return "\n".join(
                [
                    f"[{line['time']['minutes']:02d}:{line['time']['seconds']:02d}.{line['time']['hundredths']:02d}]{line['text'] or '♪'}"
                    for line in json.loads(subtitle["subtitle_body"])
                ]
            )
        return None


class ShazamLyricsPlugin(LyricsPluginBase):
    HEADERS: ClassVar[dict[str, str]] = {
        "X-Shazam-Platform": "IPHONE",
        "X-Shazam-AppVersion": "14.1.0",
        "Accept": "*/*",
        "Accept-Language": "en-US",
        "Accept-Encoding": "gzip, deflate",
        "User-Agent": "Mozilla/5.0",
    }

    def __init__(self, info: dict[str, Any], to_screen: Callable[[str], None] | None = None):
        super().__init__(info, to_screen=to_screen)
        self._raw_data: tuple[str, bool, bool] | None = None

    def _make_request(self, url: str) -> requests.Response | None:
        try:
            response = requests.get(url, headers=self.HEADERS, allow_redirects=True, timeout=10)
            response.raise_for_status()
        except Exception as e:
            self.to_screen(repr(e))
            return None
        return response

    def _search_for_id(self, query: str, language: str = "GB", *, short_circuit: bool = False) -> tuple[str, bool, bool]:
        url = f"https://www.shazam.com/services/amapi/v1/catalog/{language}/search?types=songs&term={urllib.parse.quote(query)}&limit=3"
        resp = self._make_request(url)
        if resp is None:
            raise ValueError("Failed to fetch data")

        data = resp.json()
        if not data:
            raise ValueError("No data found")

        for error in data.get("errors", []):
            if error.get("title", "").lower() == "invalid parameter":
                source = error.get("source", {})
                if source:
                    param = source.get("parameter", "")
                    if param:
                        query = query.replace(param, "").strip()
                        if short_circuit:
                            raise ValueError(f"Invalid parameter: {param!r}")
                        return self._search_for_id(query, language, short_circuit=True)
            raise ValueError("Shazam API error")

        songs = data.get("results", {}).get("songs", {}).get("data", [])
        for song in songs:
            sz_name = song["attributes"]["name"]
            current_app.logger.info(f"Comparing '{self.title}' to '{sz_name}'")
            sm = SequenceMatcher(lambda x: x in ("-", "_"), (self.title or "").lower(), sz_name.lower())
            current_app.logger.info(f"Similarity ratio: {sm.ratio():.4f}")
            if round(sm.ratio(), 2) >= 0.7:
                return (
                    song["id"],
                    song["attributes"]["hasLyrics"],
                    song["attributes"]["hasTimeSyncedLyrics"],
                )
        raise ValueError("No matching song found")

    def _get_real_page(self, track_id: str) -> str | None:
        song_page = self._make_request(f"https://www.shazam.com/song/{track_id}")
        if song_page is None:
            return None
        match = re.search(r"<link\s+rel=\"canonical\"\s+href=\"([^\"]+)", song_page.text)
        if match:
            return match.group(1)
        return None

    def _deep_search_all(self, data: Any, target_key: str) -> Iterator[Any]:
        if isinstance(data, dict):
            if target_key in data:
                yield data[target_key]
            for value in data.values():
                yield from self._deep_search_all(value, target_key)
        elif isinstance(data, list):
            for item in data:
                yield from self._deep_search_all(item, target_key)

    @property
    def raw_data(self):
        if not self._raw_data:
            self._raw_data = self._get_data()
        if self._raw_data is None:
            return "", False, False
        return self._raw_data

    @property
    def page_content(self) -> str:
        return self.raw_data[0]

    @property
    def has_lyrics(self) -> bool:
        return self.raw_data[1]

    @property
    def has_synced_lyrics(self) -> bool:
        return self.raw_data[2]

    def _get_data(self) -> tuple[str, bool, bool] | None:
        if not self.title:
            return None
        track_id = ""
        has_lyrics = False
        has_synced_lyric = False
        query = f"{self.artist} {self.title}" if self.artist else self.title
        for language in ["GB", "JP"]:
            try:
                track_id, has_lyrics, has_synced_lyric = self._search_for_id(query, language)
                break
            except Exception as e:
                self.to_screen(repr(e))
                continue
        if not track_id:
            return None
        song_url = self._get_real_page(track_id)
        if not song_url:
            return None
        song_page = self._make_request(song_url)
        if not song_page:
            return None
        return song_page.text, has_lyrics, has_synced_lyric

    def get_unsynced(self) -> str | None:
        if not self.has_lyrics:
            return None
        match = re.search(r'<script type="application/ld\+json">(.*?)</script>', self.page_content, re.DOTALL)
        if not match:
            return None
        data = json.loads(match.group(1).strip())
        lyrics_data = data.get("recordingOf", {}).get("lyrics")
        if not lyrics_data:
            return None
        return lyrics_data.get("text")

    def _get_synced_lyrics(self) -> Iterator[str]:
        pattern = r"self\.__next_f\.push\(\[\s*1,\s*\"..?:(.*?)\"\]\)"
        match = re.finditer(pattern, self.page_content, re.DOTALL)
        if not match:
            return
        lyrics_block_js = None
        for m in match:
            content = m.group(1)
            if "startTimeInSeconds" in content or "endTimeInSeconds" in content:
                lyrics_block_js = content
                break
        if not lyrics_block_js:
            return
        lyrics_block_js = lyrics_block_js.encode().decode("unicode_escape").encode("latin-1").decode("utf-8")
        try:
            lyrics_data = json.loads(lyrics_block_js)
        except json.JSONDecodeError:
            return

        lyric_lines_gen = self._deep_search_all(lyrics_data, "lyricLines")
        for lyric_lines in lyric_lines_gen:
            if isinstance(lyric_lines, list) and len(lyric_lines) > 0:
                for line in lyric_lines:
                    time_raw = str(line.get("startTimeInSeconds", "0"))
                    try:
                        time_float = float(time_raw)
                        minutes = int(time_float // 60)
                        seconds = int(time_float % 60)
                        hundredths = int((time_float - int(time_float)) * 100)
                        start_time = f"{minutes:02d}:{seconds:02d}.{hundredths:02d}"
                    except ValueError:
                        start_time = "00:00.000"
                    text = line.get("content", "♪")
                    yield f"[{start_time}] {text}"

    def get_synced(self) -> str | None:
        if not self.has_synced_lyrics:
            return None
        lines = list(self._get_synced_lyrics())
        if not lines:
            return None
        return "\n".join(lines)


class LrcLibLyricsPlugin(LyricsPluginBase):
    BASE_URL = "https://lrclib.net/api"
    HEADERS: ClassVar[dict[str, str]] = {
        "User-Agent": "Mozilla/5.0",
        "Accept": "application/json",
    }

    def __init__(self, info: dict[str, Any], to_screen: Callable[[str], None] | None = None):
        super().__init__(info, to_screen=to_screen)
        self._lyrics_data = None
        self.session = requests.Session()
        retries = Retry(total=5, backoff_factor=1, status_forcelist=[500, 502, 503, 504])
        self.session.mount("https://", HTTPAdapter(max_retries=retries))
        self.session.headers.update(self.HEADERS)

    def find_lyrics(self, *, q: str = "", track_name: str = "", artist_name: str = "", album_name: str = ""):
        params = {"q": q, "track_name": track_name, "artist_name": artist_name, "album_name": album_name}
        try:
            response = self.session.get(self.BASE_URL + "/search", params=params, timeout=10)
            response.raise_for_status()
            for item in response.json():
                if item.get("trackName") == track_name and item.get("artistName") == artist_name:
                    return item

            if len(response.json()) > 0:
                first = response.json()[0]
                return first
            return None
        except Exception as e:
            self.to_screen(repr(e))
            return None

    @property
    def lyrics_data(self):
        if self._lyrics_data is None:
            self._lyrics_data = self.find_lyrics(
                track_name=self.title or "",
                artist_name=self.artist or "",
                album_name=self.album or "",
            )
        return self._lyrics_data

    def get_unsynced(self) -> str | None:
        return self.lyrics_data.get("plainLyrics") if self.lyrics_data else None

    def get_synced(self) -> str | None:
        return self.lyrics_data.get("syncedLyrics") if self.lyrics_data else None


@bp.before_request
def log_request_info():
    current_app.logger.info(f"Lyrics Request: {request.method} {request.path}")
    if request.is_json and request.method == "POST":
        current_app.logger.info(f"Lyrics Payload: {request.get_json()}")


def get_lyrics_response(plugin_class: type[LyricsPluginBase], data: dict[str, Any]):
    title = data.get("title")

    if not title and plugin_class in (LrcLibLyricsPlugin, MusixMatchLyricsPlugin, ShazamLyricsPlugin):
        return create_error_response("Missing required argument: title", 400)

    plugin = plugin_class(data, to_screen=current_app.logger.info)
    try:
        synced = plugin.get_synced()
        unsynced = plugin.get_unsynced()
        return jsonify(
            {
                "success": True,
                "provider": plugin_class.__name__,
                "synced": synced,
                "unsynced": unsynced,
            }
        )
    except Exception as e:
        return create_error_response(f"Lyrics fetch failed: {e}", 500, exc=e)


@bp.route("/", methods=["GET"])
def index():
    return """<pre>Available plugins:
    - all (fetches from all providers)
    - shazam
    - lrclib
    - musixmatch
Use POST /api/lyrics/&lt;plugin&gt; with JSON body containing at least 'title' (and optionally 'artist' and 'album') to fetch lyrics.
Or GET /api/lyrics/&lt;plugin&gt; with query parameters for the same effect.
    </pre>"""


@bp.route("/all", methods=["POST", "GET"])
def fetch_all_lyrics():
    if request.method == "GET":
        data = request.args.to_dict()
    elif request.method == "POST":
        data = request.get_json(silent=True) or {}
    else:
        return create_error_response("Method not allowed", 405)
    current_app.logger.info(f"Fetching lyrics from all providers with data: {data}")

    plugins = [ShazamLyricsPlugin, LrcLibLyricsPlugin, MusixMatchLyricsPlugin]
    results = {}
    for plugin_class in plugins:
        try:
            plugin = plugin_class(data, to_screen=current_app.logger.info)
            results[plugin_class.__name__] = {
                "synced": plugin.get_synced(),
                "unsynced": plugin.get_unsynced(),
            }
        except Exception as e:
            results[plugin_class.__name__] = {"error": str(e)}
    return jsonify({"success": True, "results": results})


@bp.route("/<path:plugin>", methods=["POST", "GET"])
def fetch_lyrics(plugin: str):
    plugin_map = {
        "shazam": ShazamLyricsPlugin,
        "lrclib": LrcLibLyricsPlugin,
        "musixmatch": MusixMatchLyricsPlugin,
    }
    plugin_class = plugin_map.get(plugin.lower())
    if not plugin_class:
        return create_error_response("Unknown lyrics provider", 404)
    if request.method == "GET":
        data = request.args.to_dict()
    elif request.method == "POST":
        data = request.get_json(silent=True) or {}
    else:
        return create_error_response("Method not allowed", 405)
    current_app.logger.info(f"Fetching lyrics using {plugin_class.__name__} with data: {data}")
    return get_lyrics_response(plugin_class, data)


def register_routes(app: Flask):
    app.register_blueprint(bp, url_prefix="/api/lyrics")

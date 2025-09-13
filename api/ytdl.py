import collections
import json
import logging
import os
import re
import uuid
from io import StringIO
from pathlib import Path
from typing import Any, Iterable, MutableSet, cast

import requests
import yt_dlp
from dotenv import find_dotenv, load_dotenv
from flask import (
    Flask,
    Response,
    jsonify,
    redirect,
    render_template,
    request,
    stream_with_context,
    url_for,
)
from upstash_redis import Redis
from upstash_redis.errors import UpstashError
from yt_dlp import YoutubeDL
from yt_dlp.utils import DownloadError, ISO639Utils, variadic

MAX_RESPONSE_SIZE = 1024 * 1024 * 4
RANGE_CHUNK_SIZE = 1024 * 1024 * 3
STREAM_CHUNK_SIZE = 512 * 1024
MAX_DOWNLOAD_FILESIZE = "200M"
API_PREFIX = "/api/ytdl"
RESPONSE_CACHE_TTL_SECONDS = 7200
URL_CACHE_TTL_SECONDS = 1800
CHANGELOG_CACHE_TTL_SECONDS = 3600


def str_to_bool(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    return str(value).lower() in ("yes", "true", "t", "y", "1")


load_dotenv()
load_dotenv(find_dotenv(".env.local"))

app = Flask(
    __name__,
    template_folder=Path(__file__).parent.parent / "templates",
    static_folder=Path(__file__).parent.parent / "static",
)

formatter = logging.Formatter(
    "[%(asctime)s] [%(levelname)s] in %(module)s: %(message)s"
)
app.logger.handlers[0].setFormatter(formatter)
app.logger.setLevel(logging.INFO if not app.debug else logging.DEBUG)

app.config["KV_REST_API_URL"] = os.getenv("KV_REST_API_URL", "")
app.config["KV_REST_API_TOKEN"] = os.getenv("KV_REST_API_TOKEN", "")
app.config["GITHUB_REPO"] = os.getenv("GITHUB_REPO", "")
app.config["GITHUB_TOKEN"] = os.getenv("GITHUB_TOKEN", "")
app.config["YTDL_OPTS"] = {
    "color": "no_color",
    "outtmpl": r"downloads/%(extractor)s-%(id)s-%(title)s.%(ext)s",
    "restrictfilenames": True,
    "nocheckcertificate": True,
    "ignoreerrors": False,
    "logtostderr": False,
    "quiet": True,
    "noplaylist": True,
    "no_warnings": True,
    "source_address": "0.0.0.0",
    "extractor_args": {
        "youtubepot-bgutilhttp": {
            "base_url": "https://bgutil-ytdlp-pot-vercal.vercel.app"
        }
    },
}

try:
    redis_client = Redis(
        url=app.config["KV_REST_API_URL"],
        token=app.config["KV_REST_API_TOKEN"],
        allow_telemetry=False,
    )
    app.logger.info("Successfully connected to Redis.")
except UpstashError as e:
    app.logger.critical(
        f"Could not connect to Redis: {e}. Caching and cookie persistence will be disabled."
    )
    redis_client = None


class CookiesIOWrapper(StringIO):
    def __init__(self, redis_client: Redis | None, key: str = "ytdl_cookies"):
        self.redis_client = redis_client
        self.key = key
        initial_value = ""
        if self.redis_client:
            try:
                cookies_result = cast(str | None, self.redis_client.get(self.key))
                if cookies_result:
                    initial_value = cookies_result
                    app.logger.info("Successfully loaded cookies from Redis.")
            except UpstashError as e:
                app.logger.error(
                    f"Redis GET error: {e}. Proceeding without persistent cookies."
                )
        super().__init__(initial_value)

    def close(self):
        if self.redis_client:
            try:
                self.redis_client.set(self.key, self.getvalue())
                app.logger.info("Successfully saved cookies to Redis.")
            except UpstashError as e:
                app.logger.error(
                    f"Redis SET error: {e}. Cookies may not have been saved."
                )
        super().close()


cookies_io = CookiesIOWrapper(redis_client)
app.config["YTDL_OPTS"]["cookiefile"] = cookies_io


@app.template_global("classlist")
class ClassList(MutableSet):
    def __init__(self, arg: str | Iterable | None = None, *args: str):
        classes: Iterable[str] = []
        if isinstance(arg, str):
            classes = arg.split()
        elif isinstance(arg, Iterable):
            classes = arg
        elif arg is not None:
            raise TypeError("expected a string or string iterable")
        self.classes = set(filter(None, classes))
        if args:
            self.classes.update(args)

    def __contains__(self, class_):
        return class_ in self.classes

    def __iter__(self):
        return iter(self.classes)

    def __len__(self):
        return len(self.classes)

    def add(self, *classes):  # type: ignore[override]
        for class_ in classes:
            self.classes.add(class_)
        return ""

    def discard(self, *classes):  # type: ignore[override]
        for class_ in classes:
            self.classes.discard(class_)
        return ""

    def __str__(self):
        return " ".join(sorted(self.classes))

    def __html__(self):
        return 'class="%s"' % self if self else ""


def create_ytdl_extractor(
    provider: str = "youtube", search_amount: int = 5, extra_opts: dict | None = None
) -> YoutubeDL:
    base_opts = app.config["YTDL_OPTS"].copy()
    config = {**base_opts, **(extra_opts or {})}
    search_prefixes = {
        "soundcloud": f"scsearch{search_amount}",
        "ytmusic": "https://music.youtube.com/search?q=",
    }
    config["default_search"] = search_prefixes.get(provider, f"ytsearch{search_amount}")
    if provider == "ytmusic":
        config["playlist_items"] = f"1-{search_amount}"
    cookies_io.seek(0)
    return YoutubeDL(config)


def create_error_response(
    message: str, code: int = 500, exc: Exception | None = None
) -> tuple[Response, int]:
    if exc:
        app.logger.error(f"Exception caught: {message}", exc_info=exc)
    else:
        app.logger.warning(f"Returning error to client: {message} (Code: {code})")
    if "No such format" in message or "Unsupported URL" in message:
        code = 404
    elif "Missing argument" in message or "Invalid" in message:
        code = 400
    return jsonify({"success": False, "error": message}), code


def get_changelog_data():
    if (
        not redis_client
        or not app.config["GITHUB_REPO"]
        or not app.config["GITHUB_TOKEN"]
    ):
        app.logger.warning("Changelog disabled due to missing Redis or GitHub config.")
        return []

    cache_key = "ytdl:changelog"
    try:
        cached_changelog = redis_client.get(cache_key)
        if cached_changelog:
            app.logger.info("Changelog HIT from cache.")
            return json.loads(cached_changelog)
    except UpstashError as e:
        app.logger.error(f"Redis changelog check failed: {e}.")

    app.logger.info("Changelog MISS from cache. Fetching from GitHub API.")
    headers = {
        "Authorization": f"token {app.config['GITHUB_TOKEN']}",
        "Accept": "application/vnd.github.v3+json",
    }
    url = f"https://api.github.com/repos/{app.config['GITHUB_REPO']}/pulls?state=closed&sort=updated&direction=desc&per_page=10"
    app.logger.info(f"Fetching changelog from URL: {url}")

    try:
        response = requests.get(url, headers=headers, timeout=10)
        response.raise_for_status()
        prs = response.json()

        changelog = []
        for pr in prs:
            if pr.get("merged_at"):
                user_obj = pr.get("user", {})
                changelog.append(
                    {
                        "title": pr.get("title", "No Title"),
                        "url": pr.get("html_url", "#"),
                        "merged_at": pr.get("merged_at", "").split("T")[0],
                        "user": user_obj.get("login", "unknown"),
                        "user_url": user_obj.get("html_url", "#"),
                    }
                )

        redis_client.set(
            cache_key, json.dumps(changelog), ex=CHANGELOG_CACHE_TTL_SECONDS
        )
        app.logger.info("Successfully fetched and cached changelog from GitHub.")
        return changelog
    except requests.exceptions.RequestException as e:
        app.logger.error(f"Failed to fetch changelog from GitHub: {e}")
        return []


def get_metadata_opts(info, compat_opts=[]):
    meta_prefix = "meta"
    metadata = collections.defaultdict(dict)

    def add(meta_list, info_list=None):
        value = next(
            (
                info[key]
                for key in [f"{meta_prefix}_", *variadic(info_list or meta_list)]
                if info.get(key) is not None
            ),
            None,
        )
        if value not in ("", None):
            value = ", ".join(map(str, variadic(value)))
            value = value.replace("\0", "")
            metadata["common"].update(dict.fromkeys(variadic(meta_list), value))

    add("title", ("track", "title"))
    add("date", "upload_date")
    add(("description", "synopsis"), "description")
    add(("purl", "comment"), "webpage_url")
    add("track", "track_number")
    add(
        "artist",
        ("artist", "artists", "creator", "creators", "uploader", "uploader_id"),
    )
    add("composer", ("composer", "composers"))
    add("genre", ("genre", "genres"))
    add("album")
    add("album_artist", ("album_artist", "album_artists"))
    add("disc", "disc_number")
    add("show", "series")
    add("season_number")
    add("episode_id", ("episode", "episode_id"))
    add("episode_sort", "episode_number")
    if "embed-metadata" in compat_opts:
        add("comment", "description")
        metadata["common"].pop("synopsis", None)

    meta_regex = rf"{re.escape(meta_prefix)}(?P<i>\d+)?_(?P<key>.+)"
    for key, value in info.items():
        mobj = re.fullmatch(meta_regex, key)
        if value is not None and mobj:
            metadata[mobj.group("i") or "common"][mobj.group("key")] = value.replace(
                "\0", ""
            )

    yield ("-write_id3v1", "1")

    for name, value in metadata["common"].items():
        yield ("-metadata", f"{name}={value}")

    stream_idx = 0
    for fmt in info.get("requested_formats") or [info]:
        stream_count = 2 if "none" not in (fmt.get("vcodec"), fmt.get("acodec")) else 1
        lang = ISO639Utils.short2long(fmt.get("language") or "") or fmt.get("language")
        for i in range(stream_idx, stream_idx + stream_count):
            if lang:
                metadata[str(i)].setdefault("language", lang)
            for name, value in metadata[str(i)].items():
                yield (f"-metadata:s:{i}", f"{name}={value}")
        stream_idx += stream_count


@app.before_request
def log_request_info():
    app.logger.info(f"Request: {request.method} {request.path}")
    if request.is_json and request.method == "POST":
        app.logger.info(f"Request JSON payload: {request.get_json()}")


@app.route(API_PREFIX + "/")
def index():
    changelog_data = get_changelog_data()
    return render_template("index.jinja2", changelog=changelog_data)


@app.route(API_PREFIX + "/check", methods=["POST"])
def check():
    data = cast(dict | None, request.get_json(silent=True))
    if not data:
        return create_error_response("Invalid JSON payload.", 400)
    query = data.get("query")
    if not query:
        return create_error_response("Missing required argument: query", 400)

    cache_key = None
    if redis_client:
        try:
            cache_key = f"ytdl:cache:{query}:{data.get('type')}:{data.get('has_ffmpeg')}:{data.get('format')}"
            cached_response = redis_client.get(cache_key)
            if cached_response and isinstance(cached_response, str):
                app.logger.info(f"Cache HIT for key: {cache_key}")
                return jsonify(json.loads(cached_response))
            app.logger.info(f"Cache MISS for key: {cache_key}")
        except UpstashError as e:
            app.logger.error(
                f"Redis cache check failed: {e}. Proceeding without cache."
            )

    try:
        format_selector = _build_check_format_string(
            req_type=data.get("type", "video"),
            has_ffmpeg=str_to_bool(data.get("has_ffmpeg", False)),
            custom_format=data.get("format", ""),
        )
    except ValueError as e:
        return create_error_response(str(e), 400, exc=e)

    extractor = create_ytdl_extractor(
        extra_opts={
            "noplaylist": True,
            "format": format_selector,
            "postprocessors": [
                {
                    "actions": [
                        (
                            yt_dlp.postprocessor.metadataparser.MetadataParserPP.interpretter,
                            "",
                            "(?P<meta_synopsis>)",
                        ),
                        (
                            yt_dlp.postprocessor.metadataparser.MetadataParserPP.interpretter,
                            "",
                            "(?P<meta_date>)",
                        ),
                        (
                            yt_dlp.postprocessor.metadataparser.MetadataParserPP.replacer,
                            "meta_artist",
                            " - Topic$",
                            "",
                        ),
                        (
                            yt_dlp.postprocessor.metadataparser.MetadataParserPP.interpretter,
                            "artist",
                            "(?P<meta_album_artist>.*)",
                        ),
                        (
                            yt_dlp.postprocessor.metadataparser.MetadataParserPP.replacer,
                            "meta_album_artist",
                            "[,/&].+",
                            "",
                        ),
                        (
                            yt_dlp.postprocessor.metadataparser.MetadataParserPP.interpretter,
                            "%(track_number,playlist_index|01)s",
                            "%(track_number)s",
                        ),
                        (
                            yt_dlp.postprocessor.metadataparser.MetadataParserPP.interpretter,
                            "%(album,playlist_title|Unknown Album)s",
                            "%(album)s",
                        ),
                        (
                            yt_dlp.postprocessor.metadataparser.MetadataParserPP.replacer,
                            "album",
                            "^Album - ",
                            "",
                        ),
                        (
                            yt_dlp.postprocessor.metadataparser.MetadataParserPP.interpretter,
                            "%(genre|Unknown Genre)s",
                            "%(genre)s",
                        ),
                        (
                            yt_dlp.postprocessor.metadataparser.MetadataParserPP.interpretter,
                            "description",
                            "(?P<meta_date>(?<=Released on: )\\d{4})",
                        ),
                        (
                            yt_dlp.postprocessor.metadataparser.MetadataParserPP.interpretter,
                            "",
                            "(?P<description>)",
                        ),
                    ],
                    "key": "MetadataParser",
                    "when": "pre_process",
                },
            ],
        }
    )
    try:
        info = extractor.extract_info(query, download=False, process=True)
        if not info:
            return create_error_response(
                "yt-dlp failed to extract info (returned None).", 500
            )
    except DownloadError as e:
        return create_error_response(f"Extraction failed: {e}", 500, exc=e)

    metadata_opts = list(get_metadata_opts(info))
    ret_data = {
        "title": info.get("title", info.get("id", "")),
        "ext": info.get("ext", "bin"),
        "metadata": list(metadata_opts),
    }

    if "requested_formats" in info:
        ret_data["needFFmpeg"] = True
        req_formats = []
        for i in info.get("requested_formats", []):
            uid = uuid.uuid4().hex[:12]
            if redis_client:
                redis_client.set(f"ytdl:url:{uid}", i["url"], ex=URL_CACHE_TTL_SECONDS)
            req_formats.append(
                {
                    "id": uid,
                    "ext": i["ext"],
                    "formatId": i.get("format_id", "0"),
                    "fileSizeApprox": i.get("filesize_approx", 0),
                    "isPart": True,
                    "type": "audio" if i.get("audio_channels") else "video",
                }
            )
        ret_data["requestedFormats"] = req_formats
    else:
        url = info.get("url")
        if not url:
            return create_error_response(
                "No downloadable URL found for the selected format.", 404
            )

        uid = uuid.uuid4().hex[:12]
        if redis_client:
            redis_client.set(f"ytdl:url:{uid}", url, ex=URL_CACHE_TTL_SECONDS)
        ret_data["id"] = uid
        ret_data["isPart"] = True
        ret_data["fileSizeApprox"] = info.get("filesize_approx", 0)

        if data.get("type") == "audio":
            target_ext = data.get("format")
            actual_ext = info.get("ext")
            if target_ext and target_ext != "custom" and target_ext != actual_ext:
                ret_data["needsConversion"] = True
                ret_data["ext"] = target_ext
                ret_data["sourceExt"] = actual_ext
                app.logger.info(
                    f"Audio conversion needed: from '{actual_ext}' to '{target_ext}'"
                )

    if redis_client and cache_key:
        try:
            redis_client.set(
                cache_key, json.dumps(ret_data), ex=RESPONSE_CACHE_TTL_SECONDS
            )
            app.logger.info(f"Successfully cached response for key: {cache_key}")
        except UpstashError as e:
            app.logger.error(f"Redis cache set failed: {e}")

    return jsonify(ret_data)


@app.route(API_PREFIX + "/download")
def download():
    uid = request.args.get("id")
    if not uid:
        return create_error_response("Missing required argument: id", 400)
    url = None
    if redis_client:
        try:
            url = redis_client.get(f"ytdl:url:{uid}")
        except UpstashError as e:
            return create_error_response("Failed to connect to cache.", 500, exc=e)
    if not url:
        return create_error_response(
            "Download link expired or invalid. Please try again.", 410
        )
    range_header = request.headers.get("Range", "bytes=0-")
    app.logger.info(f"Handling range request for id '{uid}' with range: {range_header}")
    return _range_download_handler(url, range_header)


def _build_check_format_string(
    req_type: str, has_ffmpeg: bool, custom_format: str
) -> str:
    final_format = custom_format
    if not final_format or final_format == "custom":
        if req_type == "video":
            if has_ffmpeg:
                final_format = "bestvideo[height<=1080][ext=mp4]+bestaudio[ext=m4a]/bestvideo[height<=1080][ext=mp4]/b"
            else:
                final_format = "best*[vcodec!=none][acodec!=none][height<=1080]"
        elif req_type == "audio":
            final_format = "bestaudio"
        else:
            raise ValueError("Invalid type specified for format string.")

    elif req_type == "audio":
        final_format = f"bestaudio[ext={custom_format}]/bestaudio"

    return f"({final_format}/best)[protocol^=http][protocol!*=dash][filesize<={MAX_DOWNLOAD_FILESIZE}]"


def _range_download_handler(url: str, range_header: str):
    try:
        start_byte_str = range_header.split("=")[-1].split("-")[0]
        start_byte = int(start_byte_str) if start_byte_str.isdigit() else 0
    except (IndexError, ValueError):
        start_byte = 0
    headers = {"Range": f"bytes={start_byte}-{start_byte + RANGE_CHUNK_SIZE}"}
    try:
        r = requests.get(url, headers=headers, stream=True, timeout=10)
        r.raise_for_status()
        resp_headers = {
            "Content-Type": r.headers.get("Content-Type", "application/octet-stream"),
            "Content-Length": r.headers.get("Content-Length", "0"),
            "Accept-Ranges": "bytes",
        }
        if "Content-Range" in r.headers:
            resp_headers["Content-Range"] = r.headers["Content-Range"]

        def generate():
            for chunk in r.iter_content(chunk_size=STREAM_CHUNK_SIZE):
                yield chunk

        return Response(
            stream_with_context(generate()), headers=resp_headers, status=r.status_code
        )
    except requests.exceptions.RequestException as e:
        return create_error_response(
            f"Failed to download content range: {e}", 502, exc=e
        )


if __name__ == "__main__":

    @app.route("/")
    def index_redirect():
        return redirect(url_for("index"))

    app.run(host="0.0.0.0", port=8000, debug=True)

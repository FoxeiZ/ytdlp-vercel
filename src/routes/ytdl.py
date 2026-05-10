from __future__ import annotations

import collections
import json
import logging
import re
import uuid
from typing import TYPE_CHECKING, Any, cast

import requests
from flask import Blueprint, Flask, Response, current_app, jsonify, render_template, request, stream_with_context
from upstash_redis.errors import UpstashError
from yt_dlp.postprocessor.metadataparser import MetadataParserPP
from yt_dlp.utils import DownloadError, ISO639Utils, variadic

from src.extensions import RedisWrapper
from src.utils.general import str_to_bool

from ..customs.ytdlp import YTDLP

if TYPE_CHECKING:
    from collections.abc import Generator, Mapping, Sequence


logger = logging.getLogger(__name__)
bp = Blueprint("ytdl", __name__)

__all__ = ("register_routes",)


MAX_RESPONSE_SIZE = 1024 * 1024 * 4
RANGE_CHUNK_SIZE = 1024 * 1024 * 3
STREAM_CHUNK_SIZE = 1024 * 1024
MAX_DOWNLOAD_FILESIZE = "200M"
# RESPONSE_CACHE_TTL_SECONDS = 7200
URL_CACHE_TTL_SECONDS = 1800
CHANGELOG_CACHE_TTL_SECONDS = 3600


def create_ytdl_extractor(
    provider: str = "youtube",
    search_amount: int = 5,
    extra_opts: Mapping[str, Any] | None = None,
) -> YTDLP:
    base_opts = current_app.config["YTDL_OPTS"].copy()
    config = {**base_opts, **(extra_opts or {})}
    search_prefixes = {
        "soundcloud": f"scsearch{search_amount}",
        "ytmusic": "https://music.youtube.com/search?q=",
    }
    config["default_search"] = search_prefixes.get(provider, f"ytsearch{search_amount}")
    if provider == "ytmusic":
        config["playlist_items"] = f"1-{search_amount}"
    return YTDLP(config)


def create_error_response(message: str, code: int = 500, exc: Exception | None = None) -> tuple[Response, int]:
    if exc:
        current_app.logger.error(f"Exception caught: {message}", exc_info=exc)
    else:
        current_app.logger.warning(f"Returning error to client: {message} (Code: {code})")
    if "No such format" in message or "Unsupported URL" in message:
        code = 404
    elif "Missing argument" in message or "Invalid" in message:
        code = 400
    return jsonify({"success": False, "error": message}), code


def get_changelog_data() -> list[dict[str, Any]]:
    if not RedisWrapper.is_initialised() or not current_app.config["GITHUB_REPO"] or not current_app.config["GITHUB_TOKEN"]:
        current_app.logger.warning("Changelog disabled due to missing Redis or GitHub config.")
        return []

    redis_client = RedisWrapper.get_client()
    assert redis_client is not None
    cache_key = "ytdl:changelog"
    try:
        cached_changelog = redis_client.get(cache_key)
        if cached_changelog:
            current_app.logger.info("Changelog HIT from cache.")
            return json.loads(cached_changelog)
    except UpstashError as e:
        current_app.logger.error(f"Redis changelog check failed: {e}.")

    current_app.logger.info("Changelog MISS from cache. Fetching from GitHub API.")
    headers = {
        "Authorization": f"token {current_app.config['GITHUB_TOKEN']}",
        "Accept": "application/vnd.github.v3+json",
    }
    url = f"https://api.github.com/repos/{current_app.config['GITHUB_REPO']}/pulls?state=closed&sort=updated&direction=desc&per_page=10"
    current_app.logger.info(f"Fetching changelog from URL: {url}")

    try:
        response = requests.get(url, headers=headers, timeout=10)
        response.raise_for_status()
        prs = response.json()

        changelog: list[dict[str, Any]] = []
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

        redis_client.set(cache_key, json.dumps(changelog), ex=CHANGELOG_CACHE_TTL_SECONDS)
        current_app.logger.info("Successfully fetched and cached changelog from GitHub.")
        return changelog
    except requests.exceptions.RequestException as e:
        current_app.logger.error(f"Failed to fetch changelog from GitHub: {e}")
        return []


def as_str_list(values: str | Sequence[str]) -> list[str]:
    return [values] if isinstance(values, str) else list(values)


def get_metadata_opts(info: Mapping[str, Any], compat_opts: Sequence[Any] | None = None):
    if compat_opts is None:
        compat_opts = []
    meta_prefix = "meta"
    metadata: collections.defaultdict[str, dict[str, str]] = collections.defaultdict(dict)

    def add(meta_list: str | Sequence[str], info_list: str | Sequence[str] | None = None):
        search_keys = [f"{meta_prefix}_", *as_str_list(info_list if info_list is not None else meta_list)]
        value = next(
            (info[key] for key in search_keys if info.get(key) is not None),
            None,
        )
        if value not in ("", None):
            value = ", ".join(map(str, variadic(value)))
            value = value.replace("\0", "")
            metadata["common"].update(dict.fromkeys(as_str_list(meta_list), value))

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
            metadata[mobj.group("i") or "common"][mobj.group("key")] = value.replace("\0", "")

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


@bp.before_request
def log_request_info():
    current_app.logger.info(f"Request: {request.method} {request.path}")
    if request.is_json and request.method == "POST":
        current_app.logger.info(f"Request JSON payload: {request.get_json()}")


@bp.route("/")
def index():
    return render_template("index.jinja2")


@bp.route("/changelog")
def changelog():
    return jsonify(get_changelog_data())


@bp.route("/check", methods=["POST"])
def check():
    data = cast("dict[str, Any] | None", request.get_json(silent=True))
    if not data:
        return create_error_response("Invalid JSON payload.", 400)
    query = data.get("query")
    if not query:
        return create_error_response("Missing required argument: query", 400)

    cache_key = None
    redis_client = RedisWrapper.get_client()
    if redis_client:
        try:
            cache_key = f"ytdl:cache:{query}:{data.get('type')}:{data.get('has_ffmpeg')}:{data.get('format')}"
            cached_response = redis_client.get(cache_key)
            if cached_response and isinstance(cached_response, str):
                current_app.logger.info(f"Cache HIT for key: {cache_key}")
                return jsonify(json.loads(cached_response))
            current_app.logger.info(f"Cache MISS for key: {cache_key}")
        except UpstashError as e:
            current_app.logger.error(f"Redis cache check failed: {e}. Proceeding without cache.")

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
                            MetadataParserPP.interpretter,
                            "",
                            "(?P<meta_synopsis>)",
                        ),
                        (
                            MetadataParserPP.interpretter,
                            "",
                            "(?P<meta_date>)",
                        ),
                        (
                            MetadataParserPP.replacer,
                            "meta_artist",
                            " - Topic$",
                            "",
                        ),
                        (
                            MetadataParserPP.interpretter,
                            "artist",
                            "(?P<meta_album_artist>.*)",
                        ),
                        (
                            MetadataParserPP.replacer,
                            "meta_album_artist",
                            "[,/&].+",
                            "",
                        ),
                        (
                            MetadataParserPP.interpretter,
                            "%(track_number,playlist_index|01)s",
                            "%(track_number)s",
                        ),
                        (
                            MetadataParserPP.interpretter,
                            "%(album,playlist_title|Unknown Album)s",
                            "%(album)s",
                        ),
                        (
                            MetadataParserPP.replacer,
                            "album",
                            "^Album - ",
                            "",
                        ),
                        (
                            MetadataParserPP.interpretter,
                            "%(genre|Unknown Genre)s",
                            "%(genre)s",
                        ),
                        (
                            MetadataParserPP.interpretter,
                            "description",
                            "(?P<meta_date>(?<=Released on: )\\d{4})",
                        ),
                        (
                            MetadataParserPP.interpretter,
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
            return create_error_response("yt-dlp failed to extract info (returned None).", 500)
    except DownloadError as e:
        return create_error_response(f"Extraction failed: {e}", 500, exc=e)
    finally:
        extractor.close()

    metadata_opts = list(get_metadata_opts(info))

    artist_keys = ["artist", "artists", "creator", "creators", "uploader", "uploader_id"]
    artist_val = next((info[k] for k in artist_keys if info.get(k) is not None), None)
    artist = ", ".join(map(str, variadic(artist_val))).replace("\0", "") if artist_val else ""

    album_val = info.get("album")
    album = ", ".join(map(str, variadic(album_val))).replace("\0", "") if album_val else ""

    ret_data = {
        "title": info.get("title", info.get("id", "")),
        "artist": artist,
        "album": album,
        "ext": info.get("ext", "bin"),
        "metadata": list(metadata_opts),
    }

    if "requested_formats" in info:
        ret_data["needFFmpeg"] = True
        req_formats = []
        pipe = redis_client.pipeline() if redis_client else None
        for i in info.get("requested_formats", []):
            assert "url" in i, "Each requested format must contain a URL."
            assert "ext" in i, "Each requested format must contain an extension."

            uid = uuid.uuid4().hex[:12]
            if pipe:
                pipe.set(f"ytdl:url:{uid}", i["url"], ex=URL_CACHE_TTL_SECONDS)
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
        if pipe:
            try:
                pipe.exec()
            except UpstashError as e:
                current_app.logger.error(f"Redis pipeline exec failed: {e}")
        ret_data["requestedFormats"] = req_formats
    else:
        url = info.get("url")
        if not url:
            return create_error_response("No downloadable URL found for the selected format.", 404)

        uid = uuid.uuid4().hex[:12]
        if redis_client:
            redis_client.set(f"ytdl:url:{uid}", url, ex=URL_CACHE_TTL_SECONDS)
        ret_data["id"] = uid
        ret_data["isPart"] = True
        ret_data["fileSizeApprox"] = info.get("filesize_approx", 0)

        if data.get("type") == "audio":
            target_ext = data.get("format")
            actual_ext = info.get("ext")
            if target_ext and target_ext not in ("custom", actual_ext):
                ret_data["needsConversion"] = True
                ret_data["ext"] = target_ext
                ret_data["sourceExt"] = actual_ext
                current_app.logger.info(f"Audio conversion needed: from '{actual_ext}' to '{target_ext}'")

    if redis_client and cache_key:
        try:
            redis_client.set(cache_key, json.dumps(ret_data), ex=URL_CACHE_TTL_SECONDS)
            current_app.logger.info(f"Successfully cached response for key: {cache_key}")
        except UpstashError as e:
            current_app.logger.error(f"Redis cache set failed: {e}")

    return jsonify(ret_data)


@bp.route("/download")
def download():
    uid = request.args.get("id")
    if not uid:
        return create_error_response("Missing required argument: id", 400)
    url = None
    redis_client = RedisWrapper.get_client()
    if redis_client:
        try:
            url = redis_client.get(f"ytdl:url:{uid}")
        except UpstashError as e:
            return create_error_response("Failed to connect to cache.", 500, exc=e)
    if not url:
        return create_error_response("Download link expired or invalid. Please try again.", 410)
    range_header = request.headers.get("Range", "bytes=0-")
    current_app.logger.info(f"Handling range request for id '{uid}' with range: {range_header}")
    return _range_download_handler(url, range_header)


def _build_check_format_string(req_type: str, has_ffmpeg: bool, custom_format: str) -> str:
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
        start_byte_str = range_header.rsplit("=", maxsplit=1)[-1].split("-", maxsplit=1)[0]
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

        def generate() -> Generator[bytes, None, None]:
            yield from r.iter_content(chunk_size=STREAM_CHUNK_SIZE)

        return Response(stream_with_context(generate()), headers=resp_headers, status=r.status_code)
    except requests.exceptions.RequestException as e:
        return create_error_response(f"Failed to download content range: {e}", 502, exc=e)


def register_routes(app: Flask):
    app.register_blueprint(bp, url_prefix="/api/ytdl")

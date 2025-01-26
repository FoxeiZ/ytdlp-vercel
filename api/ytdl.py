# pyright: reportIncompatibleMethodOverride=false

import os
from typing import Any, Iterable, MutableSet
from base64 import urlsafe_b64encode, urlsafe_b64decode

from flask import (
    Flask,
    Response,
    request,
    render_template,
    stream_with_context,
)
import requests
from yt_dlp import YoutubeDL, DownloadError

MAX_RESPONE_SIZE = 1024 * 1024 * 4
RANGE_CHUNK_SIZE = 1024 * 1024 * 3
CHUNK_SIZE = 512 * 1024

BASEDIR = os.path.dirname(os.path.abspath(__file__))
PREFIX = "/api/ytdl" if __name__ != "__main__" else "/"

app = Flask(
    __name__,
    template_folder=os.path.join(BASEDIR, *[os.path.pardir, "templates"]),
    static_folder=os.path.join(BASEDIR, *[os.path.pardir, "static"]),
)
ytdlopts = {
    "color": "no_color",
    "format": "(bestaudio[ext=mp3]/bestaudio[ext=m4a]/bestaudio[ext=webm]/bestaudio/best)[protocol^=http][protocol!*=dash]",
    "outtmpl": r"downloads/%(extractor)s-%(id)s-%(title)s.%(ext)s",
    "restrictfilenames": True,
    "nocheckcertificate": True,
    "ignoreerrors": False,
    "logtostderr": False,
    "quiet": True,
    "extract_flat": "in_playlist",
    "no_warnings": True,
    "source_address": "0.0.0.0",
}


@app.template_global("classlist")
class ClassList(MutableSet):
    """Data structure for holding, and ultimately returning as a single string,
    a set of identifiers that should be managed like CSS classes.
    """

    def __init__(self, arg: str | Iterable | None = None, *args: str):
        """Constructor.

        :param arg: A single class name or an iterable thereof.
        """
        if isinstance(arg, str):
            classes = arg.split()
        elif isinstance(arg, Iterable):
            classes = arg
        elif arg is not None:
            raise TypeError("expected a string or string iterable, got %r" % type(arg))
        else:
            classes = []

        self.classes = set(filter(None, classes))
        if args:
            self.classes.update(args)

    def __contains__(self, class_):
        return class_ in self.classes

    def __iter__(self):
        return iter(self.classes)

    def __len__(self):
        return len(self.classes)

    def add(self, *classes):
        for class_ in classes:
            self.classes.add(class_)
        return ""

    def discard(self, *classes):
        for class_ in classes:
            self.classes.discard(class_)

        return ""

    def __str__(self):
        return " ".join(sorted(self.classes))

    def __html__(self):
        return 'class="%s"' % self if self else ""


def get_extractor(
    config: dict | None = None, provider: str = "youtube", search_amount: int = 5
) -> YoutubeDL:
    if config is None:
        config = ytdlopts
    else:
        config = {**ytdlopts, **config}

    match provider:
        case "soundcloud":
            config["default_search"] = f"scsearch{search_amount}"
        case "ytmusic":
            config.update(
                {
                    "default_search": "https://music.youtube.com/search?q=",
                    "playlist_items": f"1-{search_amount}",
                }
            )
        case _:
            config["default_search"] = f"ytsearch{search_amount}"

    return YoutubeDL(config)


def str_to_bool(value: str | bool | None) -> bool:
    if value is None:
        return False

    if isinstance(value, bool):
        return value

    return value.lower() in ("yes", "true", "t", "y", "1")


@app.route(PREFIX)
def index():
    return render_template("index.html")


# @app.route(PREFIX + "/login", methods=["GET", "POST"])
# def login():
#     if not login_users:
#         return "No users available", 401

#     username = (
#         request.args.get("username")
#         if request.method == "GET"
#         else request.form.get("username")
#     )
#     password = (
#         request.args.get("password")
#         if request.method == "GET"
#         else request.form.get("password")
#     )

#     if username in users and users[username] == password:
#         token = str(uuid4())
#         login_users[token] = username
#         return token

#     return "", 401


def encode(msg: str) -> str:
    return urlsafe_b64encode(msg.encode("utf-8")).decode("utf-8")


def decode(msg: str) -> str:
    return urlsafe_b64decode(msg.encode("utf-8")).decode("utf-8")


def extract_info(
    extractor: YoutubeDL,
    url: str | None = None,
    video_id: str | None = None,
    process: bool | str | None = True,
):
    """Extracts video information from url or video_id using the provided extractor.

    Args:
        extractor: YoutubeDL instance used to extract the info.
        url: The url of the video.
        video_id: The video id.
        process: Whether to process the video info.
        return_dict: Whether to return the info as a dictionary.

    Returns:
        The video information as a dictionary or a Response object with an error message.
    """

    process = str_to_bool(process)

    if not url and not video_id:
        return error_response("No url or video_id provided")

    if video_id:
        url = f"https://www.youtube.com/watch?v={video_id}"

    try:
        info = extractor.extract_info(url, download=False, process=process)
    except (DownloadError, Exception) as e:
        return error_response(str(e))

    if info is None:
        return error_response("Failed to extract info")

    info["is_search"] = "search" in info.get("extractor", "")
    info["success"] = True

    return info


def error_response(message: str):
    return {
        "error": message,
        "success": False,
        "code": 400 if "No" in message else 500,
    }


def check_arguments(arguments: Iterable[str]):
    def decorator(func):
        def wrapper(*args, **kwargs):
            if request.method == "GET":
                json_data = request.args
            else:
                json_data = request.get_json(force=True, silent=True, cache=True)
                if not json_data:
                    return "Malformed JSON", 400

            for argument in arguments:
                if argument not in json_data:
                    continue
                kwargs[argument] = json_data[argument]

            return func(*args, **kwargs)

        wrapper.__name__ = func.__name__
        return wrapper

    return decorator


def require_argument(arguments: Iterable[str]):
    def decorator(func):
        def wrapper(*args, **kwargs):
            if request.method == "GET":
                json_data = request.args
            else:
                json_data = request.get_json(force=True, silent=True, cache=True)
                if not json_data:
                    return "Malformed JSON", 400

            for argument in arguments:
                if argument not in json_data:
                    return "Missing argument", 400
                kwargs[argument] = json_data[argument]
            return func(*args, **kwargs)

        wrapper.__name__ = func.__name__
        return wrapper

    return decorator


@app.post(PREFIX + "/search")
@require_argument(["query"])
@check_arguments(["process", "provider", "search_amount"])
def search(
    query: str, process: bool = True, provider: str = "youtube", search_amount: int = 5
):
    return extract_info(
        get_extractor(provider=provider, search_amount=search_amount),
        url=query,
        process=process,
    )


@app.post(PREFIX + "/extract")
@require_argument(["url"])
def extract(url: str):
    return extract_info(get_extractor(), url=url)


@app.post(PREFIX + "/check")
@require_argument(["query"])
@check_arguments(["type", "has_ffmpeg", "format"])
def check(
    query: str, type: str = "video", has_ffmpeg: bool = False, format: str = ""
) -> tuple[dict[str, Any], int]:
    # format_sel = ytdlopts["format"]
    if type == "video":
        format += (
            "/bestvideo[height<=1080][ext=mp4]+bestaudio[ext=m4a]/bestvideo[height<=1080][ext=mp4]/b"
            if has_ffmpeg
            else "best*[vcodec!=none][acodec!=none][height<=1080]"
        )
    elif type == "audio":
        format += "/bestaudio[ext=mp3]/bestaudio[ext=m4a]/bestaudio[ext=webm]/bestaudio"
    else:
        return {"error": "Invalid type"}, 400

    if format.startswith("/"):
        format = format[1:]

    info = extract_info(
        get_extractor(
            config={
                "noplaylist": True,
                "format": f"({format}/best)[protocol^=http][protocol!*=dash][filesize<=200M]",
            }
        ),
        url=query,
    )

    if not info.pop("success", False):
        return {"error": info.get("error", "Unknown error")}, info.get("code", 500)

    ret_data = {
        "title": info.get("title", info.get("id", "")),
        "ext": info.get("ext", "bin"),
    }
    if has_ffmpeg and "requested_formats" in info:
        ret_data["needFFmpeg"] = True
        ret_data["requestedFormats"] = [
            {
                "videoId": encode(i["url"]),
                "ext": i["ext"],
                "formatId": i.get("format_id", "0"),
                "fileSizeApprox": i.get("filesize_approx", 0),
                "isPart": i.get("filesize_approx", 0) >= MAX_RESPONE_SIZE,
                "type": "audio"
                if i.get("audio_channels") and i["audio_channels"] > 0
                else "video",
            }
            for i in info.get("requested_formats", [])
        ]
        return ret_data, 200

    url = info.get("url")
    if not url:
        return {"error": "No url found"}, 404

    ret_data["videoId"] = encode(url)
    if (
        filesize_approx := info.get("filesize_approx", MAX_RESPONE_SIZE)
    ) >= MAX_RESPONE_SIZE:
        ret_data["isPart"] = True
        ret_data["url"] = "/api/ytdl/part-download"
        ret_data["fileSizeApprox"] = filesize_approx

    return ret_data, 200


@app.get(PREFIX + "/range-download")
@require_argument(["video_id"])
@check_arguments(["range_start"])
def range_download(
    video_id: str, range_start: int | str = 0
) -> tuple[dict[str, str], int] | Response:
    url = decode(video_id)
    if not url:
        return {"error": "Invalid video id"}, 400

    if isinstance(range_start, str):
        range_start = int(range_start)

    r = requests.get(
        url,
        headers={"Range": f"bytes={range_start}-{range_start + MAX_RESPONE_SIZE}"},
        stream=True,
    )
    if not r.ok:
        return {"error": "Download failed"}, r.status_code

    if r.status_code != 206:
        return {"error": "Download failed"}, 500

    resp_headers: dict[str, str] = {
        "Content-Length": r.headers.get("Content-Length", "0"),
        "Content-Type": r.headers.get("Content-Type", "application/octet-stream"),
    }
    if "Content-Range" in r.headers:
        resp_headers["Content-Range"] = r.headers["Content-Range"]

    def wrapper():
        for chunk in r.iter_content(chunk_size=CHUNK_SIZE):
            print(len(chunk))
            yield chunk

    return Response(
        stream_with_context(wrapper()),
        headers=resp_headers,
        status=r.status_code,
    )


@app.post(PREFIX + "/part-download")
@require_argument(["video_id", "filesize_approx", "range_start"])
def part_download(
    video_id: str, filesize_approx: str | int, range_start: str | int
) -> tuple[dict[str, str], int]:
    if not video_id:
        return {"error": "Invalid video id"}, 400

    if isinstance(filesize_approx, str):
        filesize_approx = int(filesize_approx)

    if isinstance(range_start, str):
        range_start = int(range_start)

    remaining = filesize_approx - range_start
    if remaining < 0:
        return {"status": "finished"}, 226

    return {
        "url": f"/api/ytdl/range-download?video_id={video_id}&range_start={range_start}",
    }, 200


@app.get(PREFIX + "/download")
@require_argument(["video_id"])
def download(
    video_id: str,
) -> tuple[dict[str, str], int] | Response:
    url = decode(video_id)
    if not url:
        return {"error": "Invalid video id"}, 400

    range_start = request.headers.get("Range")
    if range_start:
        return range_download(
            video_id, range_start=int(range_start.removeprefix("bytes=").split("-")[0])
        )

    r = requests.get(url, headers={"Range": "bytes=0-"}, stream=True)
    if not r.ok:
        return {"error": "Download failed"}, r.status_code

    filesize_approx = int(r.headers.get("Content-Length", 0))
    if filesize_approx and filesize_approx >= MAX_RESPONE_SIZE:
        return {"error": "Not supported"}, 501

    def wrapper():
        for chunk in r.iter_content(chunk_size=CHUNK_SIZE):
            print(len(chunk))
            yield chunk

    return Response(
        stream_with_context(wrapper()),
        content_type=r.headers.get("Content-Type", "application/octet-stream"),
    )


if __name__ == "__main__":
    PREFIX = ""
    app.run(host="0.0.0.0", port=8080, debug=True)

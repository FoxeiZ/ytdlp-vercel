import logging
import os
from pathlib import Path

from dotenv import find_dotenv, load_dotenv
from flask import Flask, Response

from .extensions import RedisWrapper
from .routes import register_all_routes

load_dotenv()
load_dotenv(find_dotenv(".env.development.local"))


app = Flask(
    __name__,
    template_folder=Path(__file__).parent / "templates",
    static_folder=Path(__file__).parent / "static",
)

formatter = logging.Formatter("[%(asctime)s] [%(levelname)s] in %(module)s: %(message)s")
handler = logging.StreamHandler()
handler.setFormatter(formatter)

root_logger = logging.getLogger()
root_logger.handlers.clear()
root_logger.addHandler(handler)
root_logger.setLevel(logging.INFO if not app.debug else logging.DEBUG)

app.logger.handlers.clear()
app.logger.propagate = True
app.logger.setLevel(root_logger.level)

werkzeug_logger = logging.getLogger("werkzeug")
werkzeug_logger.handlers.clear()
werkzeug_logger.propagate = True
werkzeug_logger.setLevel(root_logger.level)

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
    "socket_timeout": 15,
    "extract_flat": "in_playlist",
    "source_address": "0.0.0.0",
    "extractor_args": {"youtubepot-bgutilhttp": {"base_url": "https://bgutil-ytdlp-pot-vercal.vercel.app"}},
    "allowed_extractors": ["^([yY].*?)([tT]).*e?$"],
    "cookiefile": "ytdl_cookies",
}


@app.after_request
def set_cross_origin_headers(response: Response):
    # required for SharedArrayBuffer used by multi-threaded FFmpeg WASM core
    response.headers["Cross-Origin-Opener-Policy"] = "same-origin"
    response.headers["Cross-Origin-Embedder-Policy"] = "require-corp"
    return response


register_all_routes(app)
with app.app_context():
    RedisWrapper.from_app(app)

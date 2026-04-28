import logging
import os
from pathlib import Path

from dotenv import find_dotenv, load_dotenv
from flask import Flask
from upstash_redis import Redis
from upstash_redis.errors import UpstashError

from .routes import register_all_routes
from .utils.classlist import ClassList

load_dotenv()
load_dotenv(find_dotenv(".env.local"))


app = Flask(
    __name__,
    template_folder=Path(__file__).parent / "templates",
    static_folder=Path(__file__).parent / "static",
)

formatter = logging.Formatter("[%(asctime)s] [%(levelname)s] in %(module)s: %(message)s")
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
    "socket_timeout": 15,
    "extract_flat": "in_playlist",
    "source_address": "0.0.0.0",
    "extractor_args": {"youtubepot-bgutilhttp": {"base_url": "https://bgutil-ytdlp-pot-vercal.vercel.app"}},
    "allowed_extractors": ["^([yY].*?)([tT]).*e?$"],
}

register_all_routes(app)
app.add_template_global(ClassList, name="classlist")
with app.app_context():
    try:
        redis_client = Redis(
            url=app.config["KV_REST_API_URL"],
            token=app.config["KV_REST_API_TOKEN"],
            allow_telemetry=False,
        )
        app.logger.info("Successfully connected to Redis.")
    except UpstashError as e:
        app.logger.critical(f"Could not connect to Redis: {e}. Caching and cookie persistence will be disabled.")
        redis_client = None

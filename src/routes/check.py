import importlib.metadata

import yt_dlp.version
import yt_dlp_ejs._version
from flask import Blueprint, Flask, current_app

from ..customs.ytdlp import YTDLP

bp = Blueprint("check", __name__)


@bp.route("/")
def index():
    flask_version = importlib.metadata.distribution("flask")
    return {
        "yt_dlp": {
            "version": yt_dlp.version.__version__,
            "release_git_head": yt_dlp.version.RELEASE_GIT_HEAD,
            "variant": yt_dlp.version.VARIANT,
        },
        "yt_dlp_ejs": {
            "version": yt_dlp_ejs._version.__version__,
            "commit_id": yt_dlp_ejs._version.__commit_id__,
        },
        "flask": {
            "version": flask_version.version,
            "metadata": flask_version.metadata.json,
        },
    }


@bp.route("/ytdl")
def ytdl():
    base_opts = current_app.config["YTDL_OPTS"].copy()
    extractor = YTDLP(base_opts)
    try:
        return {"cookies": {v.name: v.value for v in extractor.cookiejar}}
    finally:
        extractor.close()


def register_routes(app: Flask):
    app.register_blueprint(bp, url_prefix="/api/check")

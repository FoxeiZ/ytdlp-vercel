import logging

from dotenv import find_dotenv, load_dotenv
from flask import Blueprint, Flask, current_app, render_template, request

logger = logging.getLogger(__name__)
bp = Blueprint("index", __name__)


load_dotenv()
load_dotenv(find_dotenv(".env.local"))


@bp.before_request
def log_request_info():
    current_app.logger.info(f"Request: {request.method} {request.path}")
    if request.is_json and request.method == "POST":
        current_app.logger.info(f"Request JSON payload: {request.get_json()}")


@bp.route("/")
def index():
    return render_template("index.jinja2")


def register_routes(app: Flask):
    app.register_blueprint(bp, url_prefix="/")

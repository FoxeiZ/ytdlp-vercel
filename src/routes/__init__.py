from flask import Flask

from .check import register_routes as check_bp
from .file_browser import register_routes as file_browser_bp
from .index import register_routes as index_bp
from .lyrics import register_routes as lyrics_bp
from .ytdl import register_routes as ytdl_bp


def register_all_routes(app: Flask, *, debug: bool = False):
    index_bp(app)
    file_browser_bp(app)
    lyrics_bp(app)
    ytdl_bp(app)
    if debug:
        check_bp(app)

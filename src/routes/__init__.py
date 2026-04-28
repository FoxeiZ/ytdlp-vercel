from flask import Flask

from .index import register_routes as index_bp
from .lyrics import register_routes as lyrics_bp
from .ytdl import register_routes as ytdl_bp


def register_all_routes(app: Flask):
    index_bp(app)
    lyrics_bp(app)
    ytdl_bp(app)

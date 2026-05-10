from __future__ import annotations

import html
from datetime import datetime
from pathlib import Path
from typing import Any

from flask import Blueprint, Flask, Response, abort, current_app, request, send_file, url_for

bp = Blueprint("file_browser", __name__)


def get_cwd_root() -> Path:
    return Path.cwd().resolve()


def get_fs_root() -> Path:
    cwd = Path.cwd().resolve()
    if cwd.anchor:
        return Path(cwd.anchor)
    return Path("/")


def resolve_path(root: Path, requested: str) -> Path:
    safe_request = requested.replace("\\", "/").lstrip("/")
    target = (root / safe_request).resolve()
    if target != root and root not in target.parents:
        current_app.logger.warning("Blocked path traversal attempt: %s", requested)
        abort(403)
    return target


def build_entry_path(requested: str, name: str, absolute: bool) -> str:
    base = requested.strip("/")
    combined = f"{base}/{name}" if base else name
    if absolute:
        return f"/{combined}" if combined else "/"
    return combined


def build_parent_request(requested: str, absolute: bool) -> str:
    parts = [p for p in requested.strip("/").split("/") if p]
    parent = "/".join(parts[:-1])
    if absolute:
        return "/" if not parent else f"/{parent}"
    return parent


def render_listing(root: Path, target: Path, requested: str, absolute: bool) -> str:
    rel_path = "/" if target == root else f"/{requested.strip('/')}"
    title = f"File Browser - {html.escape(rel_path)}"

    entries: list[dict[str, Any]] = []
    for entry in target.iterdir():
        try:
            stat = entry.stat()
        except OSError:
            stat = None

        entry_name = entry.name + ("/" if entry.is_dir() else "")
        entry_path = build_entry_path(requested, entry.name, absolute)
        entry_url = url_for("file_browser.files_index", path=entry_path)

        size = "-"
        mtime = "-"
        if stat:
            if entry.is_file():
                size = f"{stat.st_size}"
            mtime = datetime.fromtimestamp(stat.st_mtime).strftime("%Y-%m-%d %H:%M")

        entries.append(
            {
                "is_dir": entry.is_dir(),
                "name": entry_name,
                "path": entry_path,
                "url": entry_url,
                "size": size,
                "mtime": mtime,
            }
        )

    entries.sort(key=lambda item: (not item["is_dir"], item["name"].lower()))

    parent_link = ""
    if target != root:
        parent = build_parent_request(requested, absolute)
        parent_url = url_for("file_browser.files_index", path=parent)
        parent_link = f'<tr><td><a href="{parent_url}">../</a></td><td>-</td><td>-</td></tr>'

    rows = "\n".join(
        [
            f'<tr><td><a href="{e["url"]}">{html.escape(e["name"])}</a></td><td>{html.escape(e["size"])}</td><td>{html.escape(e["mtime"])}</td></tr>'
            for e in entries
        ]
    )

    return f"""
    <!DOCTYPE html>
    <html lang=\"en\">
      <head>
        <meta charset=\"UTF-8\" />
        <meta name=\"viewport\" content=\"width=device-width, initial-scale=1.0\" />
        <title>{title}</title>
        <style>
          body {{ font-family: monospace; padding: 16px; background: #f5f5f5; color: #111; }}
          h1 {{ font-size: 20px; margin-bottom: 8px; }}
          .path {{ margin-bottom: 12px; color: #444; }}
          table {{ width: 100%; border-collapse: collapse; background: #fff; }}
          th, td {{ text-align: left; padding: 6px 8px; border-bottom: 1px solid #eee; }}
          th {{ background: #fafafa; }}
          a {{ color: #0033cc; text-decoration: none; }}
          a:hover {{ text-decoration: underline; }}
        </style>
      </head>
      <body>
        <h1>File Browser</h1>
        <div class=\"path\">Root: {html.escape(str(root))} | Path: {html.escape(rel_path)}</div>
        <table>
          <thead>
            <tr><th>Name</th><th>Size (bytes)</th><th>Modified</th></tr>
          </thead>
          <tbody>
            {parent_link}
            {rows}
          </tbody>
        </table>
      </body>
    </html>
    """


@bp.route("/files/", methods=["GET"])
def files_index() -> Response:
    root = get_fs_root()
    cwd = get_cwd_root()
    requested_raw = request.args.get("path", "")
    is_absolute = requested_raw.startswith("/")
    if not requested_raw:
        requested = "" if cwd == root else cwd.relative_to(root).as_posix()
        is_absolute = False
    else:
        requested = requested_raw
    target = resolve_path(root, requested)

    if target.is_dir():
        html_doc = render_listing(root, target, requested, is_absolute)
        return Response(html_doc, mimetype="text/html")

    if target.is_file():
        if request.args.get("download") == "1":
            return send_file(target, as_attachment=True, download_name=target.name)

        file_url = url_for("file_browser.files_index", path=requested, download=1)
        back_path = build_parent_request(requested, is_absolute)
        body = f"""
        <html><body style=\"font-family: monospace; padding: 16px;\">
          <p>File: {html.escape(target.name)}</p>
          <p><a href=\"{file_url}\">Download</a></p>
          <p><a href=\"{url_for("file_browser.files_index", path=back_path)}\">Back</a></p>
        </body></html>
        """
        return Response(body, mimetype="text/html")

    abort(404)


def register_routes(app: Flask):
    app.register_blueprint(bp)

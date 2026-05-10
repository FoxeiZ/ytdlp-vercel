from __future__ import annotations

import html
import os
from datetime import datetime
from pathlib import Path
from typing import Any

from flask import Blueprint, Flask, Response, abort, current_app, jsonify, request, send_file, url_for

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


def parse_limit(value: str | None, default: int = 200, max_limit: int = 1000) -> int:
    if value is None:
        return default
    try:
        parsed = int(value)
    except ValueError:
        return default
    if parsed < 1:
        return default
    return min(parsed, max_limit)


@bp.route("/files", methods=["GET"])
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


@bp.route("/files/find", methods=["GET"])
def files_find() -> tuple[Response, int] | Response:
    root = get_fs_root()
    cwd = get_cwd_root()
    requested_raw = request.args.get("path", "")
    is_absolute = requested_raw.startswith("/")
    if not requested_raw:
        requested = "" if cwd == root else cwd.relative_to(root).as_posix()
        is_absolute = False
    else:
        requested = requested_raw

    query = request.args.get("q", "").strip()
    if not query:
        return jsonify({"error": "missing q"}), 400

    limit = parse_limit(request.args.get("limit"))
    include_dirs = request.args.get("include_dirs", "0").lower() in {"1", "true", "yes"}

    base = resolve_path(root, requested)
    if not base.exists() or not base.is_dir():
        return jsonify({"error": "path must be a directory"}), 400

    results: list[dict[str, Any]] = []
    query_lower = query.lower()

    def add_result(path: Path, is_dir: bool) -> None:
        try:
            stat = path.stat()
        except OSError:
            stat = None

        rel_root = path.relative_to(root).as_posix()
        result_path = f"/{rel_root}" if is_absolute else rel_root

        results.append(
            {
                "name": path.name + ("/" if is_dir else ""),
                "path": result_path,
                "url": url_for("file_browser.files_index", path=result_path),
                "is_dir": is_dir,
                "size": stat.st_size if stat and not is_dir else None,
                "mtime": datetime.fromtimestamp(stat.st_mtime).strftime("%Y-%m-%d %H:%M") if stat else None,
            }
        )

    def matches(path: Path, is_dir: bool) -> bool:
        name = path.name.lower()
        rel_base = path.relative_to(base).as_posix().lower()
        return query_lower in name or query_lower in rel_base

    stop = False

    def onerror(err: OSError) -> None:
        current_app.logger.warning("Search error: %s", err)

    for dirpath, dirnames, filenames in os.walk(base, onerror=onerror):
        if include_dirs:
            for dirname in list(dirnames):
                path = Path(dirpath) / dirname
                if matches(path, True):
                    add_result(path, True)
                    if len(results) >= limit:
                        stop = True
                        break
            if stop:
                break

        for filename in filenames:
            path = Path(dirpath) / filename
            if matches(path, False):
                add_result(path, False)
                if len(results) >= limit:
                    stop = True
                    break
        if stop:
            break

    return jsonify(
        {
            "query": query,
            "path": requested,
            "is_absolute": is_absolute,
            "limit": limit,
            "count": len(results),
            "results": results,
        }
    )


def register_routes(app: Flask):
    app.register_blueprint(bp)

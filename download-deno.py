from __future__ import annotations

from dataclasses import dataclass
from io import BytesIO
from pathlib import Path
from typing import Final
from urllib.request import urlopen
from zipfile import ZipFile

PLATFORM_MAP: Final[dict[str, str]] = {
    "darwin": "apple-darwin",
    "linux": "unknown-linux-gnu",
    "win32": "pc-windows-msvc",
}

ARCH_MAP: Final[dict[str, str]] = {
    "amd64": "x86_64",
    "arm64": "aarch64",
}


@dataclass(frozen=True)
class DownloadResult:
    dir: Path


def _unzip_bytes(zip_bytes: bytes, dest_dir: Path) -> None:
    with ZipFile(BytesIO(zip_bytes)) as zf:
        zf.extractall(dest_dir)


def download_deno(
    deno_dir: str | Path,
    version: str,
    node_platform: str,
    node_arch: str,
) -> DownloadResult:
    platform = PLATFORM_MAP.get(node_platform)
    if not platform:
        raise ValueError(f"Unsupported operating system: {node_platform!r}")

    arch = ARCH_MAP.get(node_arch)
    if not arch:
        raise ValueError(f"Unsupported CPU architecture: {node_arch!r}")

    deno_dir = Path(deno_dir)
    bin_path = deno_dir / "deno"

    if not bin_path.exists():
        url = f"https://github.com/denoland/deno/releases/download/{version}/deno-{arch}-{platform}.zip"
        deno_dir.mkdir(parents=True, exist_ok=True)
        print(f"Downloading Deno {version} ({arch}-{platform})...")
        with urlopen(url) as res:  # noqa: S310
            status = getattr(res, "status", None)
            if status is not None and not (200 <= status < 300):
                raise RuntimeError(f"Failed to download Deno from {url}: {status}")
            zip_bytes = res.read()
        _unzip_bytes(zip_bytes, deno_dir)

    return DownloadResult(dir=deno_dir)


if __name__ == "__main__":
    import argparse
    import platform
    import sys

    parser = argparse.ArgumentParser(description="Download Deno binary for the current platform.")
    parser.add_argument("--deno-dir", type=Path, default=Path("deno_bins"), help="Directory to store downloaded Deno binaries")
    parser.add_argument("--version", type=str, default="v2.7.14", help="Deno version to download (e.g., v2.7.14)")
    args = parser.parse_args()

    result = download_deno(args.deno_dir, args.version, node_platform=sys.platform.lower(), node_arch=platform.machine().lower())
    print(f"Deno downloaded to: {result.dir}")

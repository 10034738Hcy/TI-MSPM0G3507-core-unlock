# -*- coding: utf-8 -*-
from __future__ import annotations

import shutil
import subprocess
import sys
from pathlib import Path
from datetime import datetime


ROOT = Path(__file__).resolve().parent
APP_NAME = "MICU MSPM0 BSL烧录工具"
BUILD_NAME = "MICU_MSPM0_BSL"


def ensure_icon() -> Path:
    png = ROOT / "assets" / "logo.png"
    ico = ROOT / "assets" / "logo.ico"
    if not png.exists():
        raise FileNotFoundError(png)
    png_bytes = png.read_bytes()
    width, height = _read_png_size(png_bytes)
    ico_width = width if width < 256 else 0
    ico_height = height if height < 256 else 0
    header_size = 6 + 16
    entry = bytes([ico_width, ico_height, 0, 0])
    entry += (1).to_bytes(2, "little")
    entry += (32).to_bytes(2, "little")
    entry += len(png_bytes).to_bytes(4, "little")
    entry += header_size.to_bytes(4, "little")
    ico.write_bytes(b"\x00\x00\x01\x00\x01\x00" + entry + png_bytes)
    return ico


def _read_png_size(data: bytes) -> tuple[int, int]:
    if data[:8] != b"\x89PNG\r\n\x1a\n":
        raise ValueError("Logo must be a PNG file.")
    width = int.from_bytes(data[16:20], "big")
    height = int.from_bytes(data[20:24], "big")
    return width, height


def build() -> None:
    ensure_icon()
    shim_dir = ensure_packaging_shim()
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    dist = ROOT / "dist" / stamp
    build_dir = ROOT / "build" / stamp
    spec_dir = build_dir / "spec"
    for path in (dist, build_dir):
        path.mkdir(parents=True, exist_ok=True)
    spec_dir.mkdir(parents=True, exist_ok=True)

    separator = ";" if sys.platform.startswith("win") else ":"
    command = [
        sys.executable,
        "-m",
        "PyInstaller",
        "--noconfirm",
        "--clean",
        "--windowed",
        "--onefile",
        "--name",
        BUILD_NAME,
        "--icon",
        str(ROOT / "assets" / "logo.ico"),
        "--distpath",
        str(dist),
        "--workpath",
        str(build_dir),
        "--specpath",
        str(spec_dir),
        "--add-data",
        f"{ROOT / 'assets'}{separator}assets",
        "--add-data",
        f"{ROOT / 'runtime'}{separator}runtime",
        "--add-data",
        f"{ROOT / 'Input'}{separator}Input",
        str(ROOT / "app.py"),
    ]
    env = dict(**os_environ(), PYTHONPATH=str(shim_dir))
    subprocess.run(command, cwd=ROOT, check=True, env=env)
    latest = ROOT / "dist" / f"{APP_NAME}.exe"
    built = dist / f"{BUILD_NAME}.exe"
    if built.exists():
        try:
            shutil.copy2(built, latest)
        except PermissionError:
            pass


def ensure_packaging_shim() -> Path:
    shim_dir = ROOT / ".build_shims"
    shim_dir.mkdir(exist_ok=True)
    (shim_dir / "pkg_resources.py").write_text(
        """
from importlib import metadata


class Distribution:
    def __init__(self, name):
        self.project_name = name
        self.version = metadata.version(name)


def require(requirement):
    if isinstance(requirement, (list, tuple)):
        return [Distribution(_name(item)) for item in requirement]
    return [Distribution(_name(requirement))]


def get_distribution(requirement):
    return Distribution(_name(requirement))


def _name(requirement):
    text = str(requirement).strip()
    for token in ('==', '>=', '<=', '~=', '>', '<', '[', ';'):
        if token in text:
            text = text.split(token, 1)[0]
    return text.strip()
""".lstrip(),
        encoding="utf-8",
    )
    return shim_dir


def os_environ() -> dict[str, str]:
    import os

    return os.environ.copy()


if __name__ == "__main__":
    build()

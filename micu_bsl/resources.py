# -*- coding: utf-8 -*-
from __future__ import annotations

import os
import sys
from pathlib import Path


def app_root() -> Path:
    if getattr(sys, "frozen", False):
        return Path(sys.executable).resolve().parent
    return Path(__file__).resolve().parents[1]


def bundled_root() -> Path:
    if hasattr(sys, "_MEIPASS"):
        return Path(sys._MEIPASS)  # type: ignore[attr-defined]
    return app_root()


def resource_path(*parts: str) -> Path:
    return bundled_root().joinpath(*parts)


def runtime_path(*parts: str) -> Path:
    external = app_root().joinpath("runtime", *parts)
    if external.exists():
        return external
    return resource_path("runtime", *parts)


def startup_cwd() -> Path:
    try:
        return Path(os.getcwd()).resolve()
    except OSError:
        return app_root()

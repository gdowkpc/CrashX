from __future__ import annotations

import sys
from pathlib import Path


def resource_path(relative_path: str) -> Path:
    """Resolve an asset in source and bundled PyInstaller builds."""

    if hasattr(sys, "_MEIPASS"):
        return Path(getattr(sys, "_MEIPASS")) / relative_path
    return Path(__file__).resolve().parents[2] / relative_path


def app_icon_path() -> Path:
    return resource_path("assets/windows/CrashX.png")

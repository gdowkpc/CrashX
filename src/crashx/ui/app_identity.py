from __future__ import annotations

from PySide6.QtGui import QFont, QIcon
from PySide6.QtWidgets import QApplication

from .. import __version__
from ..resources import app_icon_path


def configure_exchange_application(application: QApplication) -> bool:
    """Apply the standalone CrashX application metadata and icon."""

    application.setApplicationName("CrashX")
    application.setApplicationVersion(__version__)
    application.setOrganizationName("CrashX")
    application.setFont(QFont("Segoe UI", 9))

    icon = QIcon(str(app_icon_path()))
    if icon.isNull():
        return False
    application.setWindowIcon(icon)
    return True

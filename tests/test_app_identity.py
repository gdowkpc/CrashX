from __future__ import annotations

import os
import unittest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication

from crashx import __version__
from crashx.resources import app_icon_path
from crashx.ui.app_identity import configure_exchange_application


class ApplicationIdentityTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.application = QApplication.instance() or QApplication([])

    def test_crashx_identity_and_icon_are_applied(self) -> None:
        self.assertTrue(app_icon_path().is_file())
        self.assertTrue(configure_exchange_application(self.application))
        self.assertEqual(self.application.applicationName(), "CrashX")
        self.assertEqual(self.application.applicationVersion(), __version__)
        self.assertEqual(self.application.organizationName(), "CrashX")
        self.assertFalse(self.application.windowIcon().isNull())


if __name__ == "__main__":
    unittest.main()

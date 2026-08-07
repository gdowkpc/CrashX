from __future__ import annotations

import os
import unittest

from PIL import Image

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

    def test_crashx_icon_is_a_single_white_x(self) -> None:
        png_path = app_icon_path()
        ico_path = png_path.with_suffix(".ico")
        with Image.open(png_path) as image:
            rgba = image.convert("RGBA")
            self.assertEqual(rgba.size, (256, 256))
            for point in ((68, 60), (188, 60), (128, 128)):
                self.assertGreater(sum(rgba.getpixel(point)[:3]), 700)
            for point in ((10, 10), (128, 60), (128, 230)):
                self.assertLess(sum(rgba.getpixel(point)[:3]), 20)

        with Image.open(ico_path) as icon:
            self.assertTrue(
                {(16, 16), (32, 32), (48, 48), (256, 256)}
                <= icon.ico.sizes()
            )


if __name__ == "__main__":
    unittest.main()

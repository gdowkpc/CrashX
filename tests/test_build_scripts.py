from __future__ import annotations

import unittest
from pathlib import Path


PROJECT_ROOT = Path(__file__).parents[1]


class BuildScriptTest(unittest.TestCase):
    def test_single_file_build_is_isolated_and_non_admin(self) -> None:
        build = (
            PROJECT_ROOT / "scripts" / "build_exchange_onefile_windows.ps1"
        ).read_text(encoding="utf-8")
        launcher = (PROJECT_ROOT / "BUILD_CRASHX_SINGLE_FILE.bat").read_text(
            encoding="utf-8"
        )
        manifest = (
            PROJECT_ROOT / "assets" / "windows" / "CrashX.manifest"
        ).read_text(encoding="utf-8")

        self.assertIn("--onefile", build)
        self.assertIn("CrashX.ico", build)
        self.assertIn("CrashX.png", build)
        self.assertIn("run_crashx.py", build)
        self.assertIn("Windows-Single.exe", build)
        self.assertIn("verify_windows_executable_manifest.py", build)
        self.assertIn('"--self-test"', build)
        self.assertIn("Get-ChildItem -LiteralPath $IsolatedDirectory", build)
        self.assertIn("build_exchange_onefile_windows.ps1", launcher)
        self.assertIn("--% %*", launcher)
        self.assertIn('requestedExecutionLevel level="asInvoker"', manifest)
        self.assertIn('uiAccess="false"', manifest)
        self.assertNotIn("requireAdministrator", manifest)

    def test_public_repository_excludes_generated_and_crash_data(self) -> None:
        ignore = (PROJECT_ROOT / ".gitignore").read_text(encoding="utf-8")
        for required_pattern in (
            ".venv/",
            "release/",
            "single-file-dist/",
            "*.sqlite",
            "*.pdf",
        ):
            self.assertIn(required_pattern, ignore)


if __name__ == "__main__":
    unittest.main()

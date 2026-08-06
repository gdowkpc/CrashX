from __future__ import annotations

import argparse
import hashlib
import re
import sys
import zipfile
from pathlib import Path


REQUIRED_ARCHIVE_ENTRIES = {
    "CrashX/CrashX.exe",
    "CrashX/START_HERE.txt",
    "CrashX/BUILD_INFO.txt",
    "CrashX/_internal/assets/windows/CrashX.png",
}
FORBIDDEN_ARCHIVE_FRAGMENTS = (
    "sqlite",
    "numpy",
    "/yaml/",
    "assets/diagrams/",
    "assets/tiu_logo",
    "trafficcrashnotebook.manifest",
)
FORBIDDEN_MODULES = (
    "crashx.repository",
    "sqlite3",
    "numpy",
    "yaml",
)


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--archive", type=Path, required=True)
    parser.add_argument("--checksum", type=Path, required=True)
    parser.add_argument("--xref", type=Path, required=True)
    arguments = parser.parse_args()

    archive = arguments.archive.resolve(strict=True)
    checksum_path = arguments.checksum.resolve(strict=True)
    xref_path = arguments.xref.resolve(strict=True)

    with zipfile.ZipFile(archive) as package:
        entries = set(package.namelist())
        bad_entry = package.testzip()
    if bad_entry:
        raise ValueError(f"Corrupt archive entry: {bad_entry}")
    missing = REQUIRED_ARCHIVE_ENTRIES - entries
    if missing:
        raise ValueError(f"Missing required archive entries: {sorted(missing)}")
    forbidden_entries = sorted(
        entry
        for entry in entries
        if any(fragment in entry.casefold() for fragment in FORBIDDEN_ARCHIVE_FRAGMENTS)
    )
    if forbidden_entries:
        raise ValueError(
            "Standalone package contains excluded notebook/runtime files: "
            f"{forbidden_entries[:8]}"
        )

    xref = xref_path.read_text(encoding="utf-8").casefold()
    included_forbidden_modules = [
        module
        for module in FORBIDDEN_MODULES
        if f'<a name="{module.casefold()}"' in xref
    ]
    if included_forbidden_modules:
        raise ValueError(
            "Standalone dependency graph contains excluded modules: "
            f"{included_forbidden_modules}"
        )

    expected_match = re.fullmatch(
        r"([0-9a-fA-F]{64})\s+\*?[^\r\n]+\s*",
        checksum_path.read_text(encoding="ascii"),
    )
    if expected_match is None:
        raise ValueError(f"Invalid checksum file: {checksum_path}")
    expected = expected_match.group(1).casefold()
    actual = sha256(archive)
    if actual != expected:
        raise ValueError(f"Archive SHA-256 mismatch: expected {expected}, got {actual}")

    print("CrashX release: PASS")
    print(f"Archive entries: {len(entries)}")
    print(f"SHA-256: {actual}")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except SystemExit:
        raise
    except Exception as error:
        print(f"ERROR: {error}", file=sys.stderr)
        raise SystemExit(1) from error

from __future__ import annotations

import argparse
import sys
import traceback
from pathlib import Path

import pefile


RT_MANIFEST = 24


def embedded_manifests(executable: Path) -> list[bytes]:
    pe = pefile.PE(str(executable), fast_load=False)
    try:
        resources = getattr(pe, "DIRECTORY_ENTRY_RESOURCE", None)
        if resources is None:
            return []
        manifests: list[bytes] = []
        for resource_type in resources.entries:
            if resource_type.id != RT_MANIFEST or not hasattr(resource_type, "directory"):
                continue
            for resource_name in resource_type.directory.entries:
                if not hasattr(resource_name, "directory"):
                    continue
                for resource_language in resource_name.directory.entries:
                    data = resource_language.data.struct
                    manifests.append(pe.get_memory_mapped_image()[
                        data.OffsetToData:data.OffsetToData + data.Size
                    ])
        return manifests
    finally:
        pe.close()


def verify_manifest(executable: Path) -> None:
    if not executable.is_file():
        raise RuntimeError(f"Executable was not found: {executable}")
    manifests = embedded_manifests(executable)
    if not manifests:
        raise RuntimeError("The executable does not contain a Windows application manifest.")
    combined = b"\n".join(manifests)
    required = (b"asInvoker", b'uiAccess="false"', b"longPathAware")
    missing = [value.decode("ascii") for value in required if value not in combined]
    if missing:
        raise RuntimeError(
            "The executable manifest is missing required portable settings: "
            + ", ".join(missing)
        )
    if b"requireAdministrator" in combined or b"highestAvailable" in combined:
        raise RuntimeError("The executable manifest requests elevated privileges.")


def main() -> int:
    parser = argparse.ArgumentParser(description="Verify the embedded Windows application manifest.")
    parser.add_argument("executable", type=Path)
    arguments = parser.parse_args()
    try:
        verify_manifest(arguments.executable.resolve())
        print("Windows executable manifest: PASS")
        return 0
    except BaseException:
        traceback.print_exc()
        return 1


if __name__ == "__main__":
    sys.exit(main())

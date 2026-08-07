from __future__ import annotations

from pathlib import Path

from PIL import Image, ImageDraw


PROJECT_ROOT = Path(__file__).resolve().parents[1]
ASSET_DIRECTORY = PROJECT_ROOT / "assets" / "windows"
PNG_PATH = ASSET_DIRECTORY / "CrashX.png"
ICO_PATH = ASSET_DIRECTORY / "CrashX.ico"

SOURCE_SIZE = 1024
OUTPUT_SIZE = 256
ICON_SIZES = tuple((size, size) for size in (16, 24, 32, 48, 64, 128, 256))


def scaled_polygon(points: tuple[tuple[int, int], ...]) -> list[tuple[int, int]]:
    scale = SOURCE_SIZE // OUTPUT_SIZE
    return [(x * scale, y * scale) for x, y in points]


def build_icon() -> Image.Image:
    """Create a high-contrast geometric X that remains clear at taskbar sizes."""

    source = Image.new("RGBA", (SOURCE_SIZE, SOURCE_SIZE), (0, 0, 0, 255))
    draw = ImageDraw.Draw(source)
    white = (255, 255, 255, 255)
    draw.polygon(
        scaled_polygon(((45, 42), (91, 42), (211, 214), (165, 214))),
        fill=white,
    )
    draw.polygon(
        scaled_polygon(((165, 42), (211, 42), (91, 214), (45, 214))),
        fill=white,
    )
    return source.resize(
        (OUTPUT_SIZE, OUTPUT_SIZE),
        Image.Resampling.LANCZOS,
    )


def main() -> int:
    ASSET_DIRECTORY.mkdir(parents=True, exist_ok=True)
    icon = build_icon()
    icon.save(PNG_PATH, format="PNG", optimize=True)
    icon.save(ICO_PATH, format="ICO", sizes=ICON_SIZES)
    print(f"Created {PNG_PATH}")
    print(
        f"Created {ICO_PATH} with sizes: "
        + ", ".join(str(width) for width, _height in ICON_SIZES)
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

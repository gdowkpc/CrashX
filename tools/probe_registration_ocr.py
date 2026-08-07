from __future__ import annotations

import re
import sys
from pathlib import Path

from PySide6.QtCore import QRect
from PySide6.QtGui import QImage, QTransform

PROJECT_ROOT = Path(__file__).resolve().parents[1]
SRC = PROJECT_ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from crashx.windows_ocr import recognize_image
from crashx.registration_scan import scan_registration_image


LABELS = {
    "OREGON",
    "WASHINGTON",
    "REGISTRATION",
    "PLATE",
    "NUMBER",
    "YEAR",
    "MAKE",
    "STYLE",
    "MODEL",
    "VEHICLE",
    "IDENTIFICATION",
    "FUEL",
    "EXPIRATION",
    "ISSUE",
}


def normalized_tokens(document) -> set[str]:
    return {
        token
        for line in document.lines
        for token in re.findall(r"[A-Z]+", line.upper())
    }


def masked_word(value: str) -> str:
    upper = value.upper()
    if upper in LABELS:
        return upper
    return "".join(
        "A" if character.isalpha() else "9" if character.isdigit() else character
        for character in value
    )


def main() -> int:
    if len(sys.argv) not in {2, 3} or (len(sys.argv) == 3 and sys.argv[2] != "--layout"):
        print("Usage: probe_registration_ocr.py IMAGE [--layout]", file=sys.stderr)
        return 2
    image = QImage(str(Path(sys.argv[1])))
    if image.isNull():
        print("Image could not be loaded.", file=sys.stderr)
        return 2

    observations = []
    for rotation in (0, 90, 180, 270):
        candidate = image.transformed(QTransform().rotate(rotation))
        document = recognize_image(candidate)
        detected = sorted(normalized_tokens(document) & LABELS)
        observations.append((len(detected), len(document.words), rotation, detected))

    _label_count, word_count, rotation, detected = max(observations)
    print(f"Best rotation: {rotation} degrees")
    print(f"OCR words: {word_count}")
    print(f"Registration labels found: {', '.join(detected) or 'none'}")
    scan = scan_registration_image(image)
    print(f"Mapped fields: {', '.join(scan.populated_fields) or 'none'}")
    print(f"Detected jurisdiction: {scan.jurisdiction or 'unknown'}")
    if scan.warnings:
        print(f"Review warnings: {len(scan.warnings)}")
    if "--layout" in sys.argv:
        candidate = image.transformed(QTransform().rotate(rotation))
        document = recognize_image(candidate)
        for word in sorted(document.words, key=lambda item: (item.y, item.x)):
            print(
                f"{masked_word(word.text):<24} "
                f"x={word.x / document.width:.3f} y={word.y / document.height:.3f} "
                f"w={word.width / document.width:.3f} h={word.height / document.height:.3f}"
            )
        year_anchor = next(
            (word for word in document.words if word.text.upper() == "YEAR"),
            None,
        )
        if year_anchor is not None:
            detail_region = candidate.copy(
                QRect(
                    max(0, round(year_anchor.x - document.width * 0.025)),
                    max(0, round(year_anchor.y - document.height * 0.04)),
                    round(document.width * 0.72),
                    round(document.height * 0.12),
                )
            ).scaledToWidth(2600)
            detail = recognize_image(detail_region)
            print("Vehicle-section detail pass:")
            for word in sorted(detail.words, key=lambda item: (item.y, item.x)):
                print(
                    f"{masked_word(word.text):<24} "
                    f"x={word.x / detail.width:.3f} y={word.y / detail.height:.3f} "
                    f"w={word.width / detail.width:.3f} h={word.height / detail.height:.3f}"
                )
            style_anchor = next(
                (word for word in document.words if word.text.upper() == "STYLE"),
                None,
            )
            model_anchor = next(
                (word for word in document.words if word.text.upper() == "MODEL"),
                None,
            )
            if style_anchor is not None and model_anchor is not None:
                style_left = round(
                    (year_anchor.x + style_anchor.x * 3) / 4
                )
                style_right = round(
                    (style_anchor.x + style_anchor.width + model_anchor.x) / 2
                )
                style_cell = candidate.copy(
                    QRect(
                        style_left,
                        round(style_anchor.y + style_anchor.height),
                        max(1, style_right - style_left),
                        round(document.height * 0.045),
                    )
                ).scaledToWidth(1200)
                style_document = recognize_image(style_cell)
                print(
                    "Style-cell OCR shapes: "
                    + ", ".join(masked_word(word.text) for word in style_document.words)
                )
    print("No registration values were printed or saved.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

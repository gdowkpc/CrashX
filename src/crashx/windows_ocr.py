from __future__ import annotations

import asyncio
from dataclasses import dataclass

from PySide6.QtCore import Qt
from PySide6.QtGui import QImage


class OcrUnavailableError(RuntimeError):
    """Raised when the local Windows OCR service cannot be used."""


@dataclass(frozen=True, slots=True)
class OcrWord:
    text: str
    x: float
    y: float
    width: float
    height: float


@dataclass(frozen=True, slots=True)
class OcrDocument:
    width: int
    height: int
    words: tuple[OcrWord, ...]
    lines: tuple[str, ...]


def _tight_grayscale_bytes(image: QImage) -> tuple[bytes, int, int]:
    grayscale = image.convertToFormat(QImage.Format.Format_Grayscale8)
    width = grayscale.width()
    height = grayscale.height()
    stride = grayscale.bytesPerLine()
    raw = bytes(grayscale.constBits())
    if stride == width:
        return raw[: width * height], width, height
    return (
        b"".join(
            raw[row * stride : row * stride + width]
            for row in range(height)
        ),
        width,
        height,
    )


async def _recognize_async(image: QImage) -> OcrDocument:
    try:
        from winrt.windows.globalization import Language
        from winrt.windows.graphics.imaging import BitmapPixelFormat, SoftwareBitmap
        from winrt.windows.media.ocr import OcrEngine
        from winrt.windows.storage.streams import Buffer
    except (ImportError, ModuleNotFoundError) as error:
        raise OcrUnavailableError(
            "The local Windows OCR components are not bundled in this build."
        ) from error

    engine = OcrEngine.try_create_from_language(Language("en-US"))
    if engine is None:
        engine = OcrEngine.try_create_from_user_profile_languages()
    if engine is None:
        raise OcrUnavailableError(
            "Windows does not have a compatible local OCR language installed."
        )

    pixels, width, height = _tight_grayscale_bytes(image)
    maximum = int(OcrEngine.max_image_dimension)
    if width > maximum or height > maximum:
        scaled = image.scaled(
            maximum,
            maximum,
            aspectMode=Qt.AspectRatioMode.KeepAspectRatio,
            mode=Qt.TransformationMode.SmoothTransformation,
        )
        pixels, width, height = _tight_grayscale_bytes(scaled)

    buffer = Buffer(len(pixels))
    buffer.length = len(pixels)
    memoryview(buffer)[:] = pixels
    bitmap = SoftwareBitmap.create_copy_from_buffer(
        buffer,
        BitmapPixelFormat.GRAY8,
        width,
        height,
    )
    try:
        result = await engine.recognize_async(bitmap)
    finally:
        bitmap.close()

    words: list[OcrWord] = []
    lines: list[str] = []
    for line in result.lines:
        line_text = line.text.strip()
        if line_text:
            lines.append(line_text)
        for word in line.words:
            text = word.text.strip()
            if not text:
                continue
            bounds = word.bounding_rect
            words.append(
                OcrWord(
                    text=text,
                    x=float(bounds.x),
                    y=float(bounds.y),
                    width=float(bounds.width),
                    height=float(bounds.height),
                )
            )
    return OcrDocument(
        width=width,
        height=height,
        words=tuple(words),
        lines=tuple(lines),
    )


def recognize_image(image: QImage) -> OcrDocument:
    """Recognize an in-memory image using Windows OCR without writing a file."""

    if image.isNull():
        raise ValueError("The OCR image is empty.")
    return asyncio.run(_recognize_async(image))

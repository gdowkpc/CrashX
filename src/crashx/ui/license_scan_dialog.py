from __future__ import annotations

from concurrent.futures import Future, ThreadPoolExecutor
from dataclasses import dataclass

import zxingcpp
from PySide6.QtCore import QElapsedTimer, QRect, QSize, Qt, QTimer, Signal
from PySide6.QtGui import QColor, QImage, QPainter, QPen, QPixmap
from PySide6.QtMultimedia import (
    QCamera,
    QCameraDevice,
    QMediaCaptureSession,
    QMediaDevices,
    QVideoFrame,
    QVideoSink,
)
from PySide6.QtWidgets import (
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QHBoxLayout,
    QLabel,
    QVBoxLayout,
)

from ..license_scan import AamvaParseError, ScannedLicenseData, parse_aamva_pdf417


@dataclass(frozen=True, slots=True)
class LicenseFrameDecode:
    data: ScannedLicenseData | None = None
    outcome: str = "none"


def _scan_region(image: QImage) -> QImage:
    """Return the full-resolution region covered by the on-screen guide."""

    margin_x = max(1, round(image.width() * 0.04))
    top = max(1, round(image.height() * 0.22))
    height = max(1, round(image.height() * 0.56))
    return image.copy(
        QRect(
            margin_x,
            top,
            max(1, image.width() - (2 * margin_x)),
            min(height, image.height() - top),
        )
    )


def _read_pdf417(image: QImage) -> list:
    """Decode through an explicit grayscale view instead of experimental QImage glue."""

    grayscale = image.convertToFormat(QImage.Format.Format_Grayscale8)
    image_view = zxingcpp.ImageView(
        grayscale.constBits(),
        grayscale.width(),
        grayscale.height(),
        zxingcpp.ImageFormat.Lum,
        grayscale.bytesPerLine(),
        1,
    )
    return zxingcpp.read_barcodes(
        image_view,
        formats=zxingcpp.BarcodeFormat.PDF417,
        try_rotate=True,
        try_downscale=True,
        try_invert=True,
        text_mode=zxingcpp.TextMode.Plain,
        binarizer=zxingcpp.Binarizer.LocalAverage,
        return_errors=True,
    )


def decode_license_frame(image: QImage) -> LicenseFrameDecode:
    """Decode a camera frame without retaining the image or raw barcode payload."""

    if image.isNull():
        return LicenseFrameDecode(outcome="empty")

    region = _scan_region(image)
    candidates = (region, image, region.flipped(Qt.Orientation.Horizontal))
    saw_partial = False
    saw_non_aamva = False
    for candidate in candidates:
        for barcode in _read_pdf417(candidate):
            if not barcode.valid:
                saw_partial = True
                continue
            try:
                scanned = parse_aamva_pdf417(bytes(barcode.bytes))
            except AamvaParseError:
                saw_non_aamva = True
                continue
            return LicenseFrameDecode(data=scanned, outcome="success")

    if saw_non_aamva:
        return LicenseFrameDecode(outcome="non_aamva")
    if saw_partial:
        return LicenseFrameDecode(outcome="partial")
    return LicenseFrameDecode()


def _preferred_camera_format(device: QCameraDevice):
    formats = list(device.videoFormats())
    if not formats:
        return None
    target_pixels = 1920 * 1080
    preferred = [
        camera_format
        for camera_format in formats
        if (
            camera_format.resolution().width()
            * camera_format.resolution().height()
            <= target_pixels
            and camera_format.maxFrameRate() >= 15
        )
    ]
    candidates = preferred or formats
    return max(
        candidates,
        key=lambda camera_format: (
            camera_format.resolution().width()
            * camera_format.resolution().height(),
            min(camera_format.maxFrameRate(), 30),
            camera_format.pixelFormat().name != "Format_Jpeg",
        ),
    )


class LicenseScanDialog(QDialog):
    """Live, local-only PDF417 scanner for the Add/Edit Person workflow."""

    decode_finished = Signal(object)

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.setWindowTitle("Scan driver license")
        self.setMinimumSize(720, 560)
        self.scanned_data: ScannedLicenseData | None = None
        self._devices: list[QCameraDevice] = list(QMediaDevices.videoInputs())
        self._camera: QCamera | None = None
        self._last_decode = QElapsedTimer()
        self._last_decode.start()
        self._executor = ThreadPoolExecutor(
            max_workers=1,
            thread_name_prefix="CrashX-PDF417",
        )
        self._decode_in_flight = False
        self._decode_attempts = 0
        self._closing = False
        self.decode_finished.connect(self._handle_decode_result)

        heading = QLabel("Scan the 2D barcode on the back of the driver license")
        heading.setStyleSheet("font-size: 18px; font-weight: 700; color: #17324d;")

        directions = QLabel(
            "Fill the dashed box with the PDF417 barcode—not the entire license. "
            "Hold it steady and tilt the card slightly if overhead light causes glare. "
            "CrashX returns to the person form after a valid read."
        )
        directions.setWordWrap(True)

        self.camera_selector = QComboBox()
        for device in self._devices:
            self.camera_selector.addItem(device.description())
        camera_row = QHBoxLayout()
        camera_row.addWidget(QLabel("Camera"))
        camera_row.addWidget(self.camera_selector, 1)

        self.preview = QLabel("Starting camera...")
        self.preview.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.preview.setMinimumSize(QSize(640, 360))
        self.preview.setStyleSheet(
            "background: #111827; color: white; border: 2px solid #4b7289; "
            "border-radius: 6px;"
        )

        self.status = QLabel("Looking for a PDF417 driver-license barcode...")
        self.status.setWordWrap(True)
        self.status.setStyleSheet(
            "background: #eaf3f8; border: 1px solid #b7cfdd; border-radius: 4px; "
            "padding: 8px; color: #17324d;"
        )

        privacy = QLabel(
            "Camera frames and the raw barcode payload are not saved. Only the "
            "mapped values returned to the open person form remain in memory."
        )
        privacy.setWordWrap(True)
        privacy.setStyleSheet("color: #4b5563;")

        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Cancel)
        buttons.rejected.connect(self.reject)

        layout = QVBoxLayout(self)
        layout.addWidget(heading)
        layout.addWidget(directions)
        layout.addLayout(camera_row)
        layout.addWidget(self.preview, 1)
        layout.addWidget(self.status)
        layout.addWidget(privacy)
        layout.addWidget(buttons)

        self._capture_session = QMediaCaptureSession(self)
        self._video_sink = QVideoSink(self)
        self._video_sink.videoFrameChanged.connect(self._frame_changed)
        self._capture_session.setVideoSink(self._video_sink)
        self.camera_selector.currentIndexChanged.connect(self._start_selected_camera)

        if self._devices:
            QTimer.singleShot(0, self._start_selected_camera)
        else:
            self.camera_selector.setEnabled(False)
            self.preview.setText("No camera was found.")
            self.status.setText(
                "Connect a camera and reopen this scanner, or enter the person manually."
            )

    def _start_selected_camera(self, _index: int = 0) -> None:
        self._stop_camera()
        index = self.camera_selector.currentIndex()
        if index < 0 or index >= len(self._devices):
            return
        self.preview.setText("Starting camera...")
        self.status.setText("Looking for a PDF417 driver-license barcode...")
        self._camera = QCamera(self._devices[index], self)
        preferred_format = _preferred_camera_format(self._devices[index])
        if preferred_format is not None:
            self._camera.setCameraFormat(preferred_format)
        auto_focus = QCamera.FocusMode.FocusModeAuto
        if self._camera.isFocusModeSupported(auto_focus):
            self._camera.setFocusMode(auto_focus)
        self._camera.errorOccurred.connect(self._camera_error)
        self._capture_session.setCamera(self._camera)
        self._last_decode.restart()
        self._decode_attempts = 0
        self._camera.start()

    def _stop_camera(self) -> None:
        if self._camera is None:
            return
        self._camera.stop()
        self._capture_session.setCamera(None)
        self._camera.deleteLater()
        self._camera = None

    def _camera_error(self, _error: QCamera.Error, description: str) -> None:
        message = description.strip() or "Windows did not make the camera available."
        self.status.setText(
            f"Camera error: {message} You can cancel and enter the person manually."
        )

    def _frame_changed(self, frame: QVideoFrame) -> None:
        image = frame.toImage()
        if image.isNull():
            return

        preview_pixmap = QPixmap.fromImage(image).scaled(
            self.preview.size(),
            Qt.AspectRatioMode.KeepAspectRatio,
            Qt.TransformationMode.SmoothTransformation,
        )
        painter = QPainter(preview_pixmap)
        guide = QRect(
            round(preview_pixmap.width() * 0.04),
            round(preview_pixmap.height() * 0.22),
            round(preview_pixmap.width() * 0.92),
            round(preview_pixmap.height() * 0.56),
        )
        painter.setPen(QPen(QColor("#22d3ee"), 3, Qt.PenStyle.DashLine))
        painter.drawRoundedRect(guide, 8, 8)
        painter.end()
        self.preview.setPixmap(preview_pixmap)

        if self._decode_attempts == 0 and not self._decode_in_flight:
            self.status.setText(
                f"Camera ready at {image.width()} x {image.height()}. "
                "Move the barcode into the dashed box and let it fill most of the box."
            )
        if self._last_decode.elapsed() < 250 or self._decode_in_flight:
            return
        self._last_decode.restart()
        self._decode_in_flight = True
        self._decode_attempts += 1
        future = self._executor.submit(decode_license_frame, image.copy())
        future.add_done_callback(self._decode_completed)

    def _decode_completed(self, future: Future) -> None:
        try:
            result = future.result()
        except Exception:
            result = LicenseFrameDecode(outcome="decode_error")
        if not self._closing:
            self.decode_finished.emit(result)

    def _handle_decode_result(self, result: LicenseFrameDecode) -> None:
        self._decode_in_flight = False
        if result.outcome == "decode_error":
            self.status.setText(
                "The camera image could not be decoded. Keep the barcode steady or cancel."
            )
            return
        if result.outcome == "partial":
            self.status.setText(
                "PDF417 bars detected, but the image is not clear enough. Hold the "
                "card steady, move it slightly closer, and tilt it to remove glare."
            )
            return
        if result.outcome == "non_aamva":
            self.status.setText(
                "A PDF417 barcode was read, but it was not recognized as AAMVA "
                "driver-license data. Keep scanning or cancel."
            )
            return
        if result.data is not None:
            self.scanned_data = result.data
            self.status.setText("License read. Returning to the person form...")
            self.preview.clear()
            self._stop_camera()
            QTimer.singleShot(0, self.accept)
            return
        if self._decode_attempts % 8 == 0:
            self.status.setText(
                "No PDF417 barcode detected yet. Put only the barcode in the dashed "
                "box, move the card closer until the bars are sharp, and avoid glare."
            )

    def done(self, result: int) -> None:
        self._closing = True
        self._stop_camera()
        self._video_sink.setVideoFrame(QVideoFrame())
        self.preview.clear()
        self._executor.shutdown(wait=False, cancel_futures=True)
        super().done(result)

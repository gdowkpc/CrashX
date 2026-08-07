from __future__ import annotations

from concurrent.futures import Future, ThreadPoolExecutor
from dataclasses import dataclass

from PySide6.QtCore import QSize, Qt, QTimer, Signal
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
    QPushButton,
    QVBoxLayout,
)

from ..registration_scan import (
    AUTO_STATE,
    SUPPORTED_REGISTRATION_STATES,
    RegistrationScanError,
    ScannedVehicleData,
    prepare_camera_registration_image,
    registration_guide_rect,
    scan_registration_image,
)
from ..windows_ocr import OcrUnavailableError
from .license_scan_dialog import _preferred_camera_format


@dataclass(frozen=True, slots=True)
class RegistrationReadOutcome:
    data: ScannedVehicleData | None = None
    error: str = ""


class RegistrationScanDialog(QDialog):
    """Capture one registration image and return only supported vehicle fields."""

    scan_finished = Signal(object)

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.setWindowTitle("Scan vehicle registration")
        self.setMinimumSize(760, 620)
        self.scanned_data: ScannedVehicleData | None = None
        self._devices: list[QCameraDevice] = list(QMediaDevices.videoInputs())
        self._camera: QCamera | None = None
        self._latest_image: QImage | None = None
        self._executor = ThreadPoolExecutor(
            max_workers=1,
            thread_name_prefix="CrashX-Registration-OCR",
        )
        self._scan_in_flight = False
        self._closing = False
        self._scan_retry_message = ""
        self.scan_finished.connect(self._handle_scan_result)

        heading = QLabel("Scan the vehicle-information section of the registration")
        heading.setStyleSheet("font-size: 18px; font-weight: 700; color: #17324d;")
        directions = QLabel(
            "Fill the dashed rectangle with the registration, keep it flat, and avoid "
            "glare. The document may be sideways; CrashX will correct its orientation. "
            "Press Capture and read when the printed text is sharp."
        )
        directions.setWordWrap(True)

        self.state_selector = QComboBox()
        for code, label in SUPPORTED_REGISTRATION_STATES:
            self.state_selector.addItem(label, code)
        state_row = QHBoxLayout()
        state_row.addWidget(QLabel("Registration state"))
        state_row.addWidget(self.state_selector, 1)

        self.camera_selector = QComboBox()
        for device in self._devices:
            self.camera_selector.addItem(device.description())
        camera_row = QHBoxLayout()
        camera_row.addWidget(QLabel("Camera"))
        camera_row.addWidget(self.camera_selector, 1)

        self.preview = QLabel("Starting camera...")
        self.preview.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.preview.setMinimumSize(QSize(680, 380))
        self.preview.setStyleSheet(
            "background: #111827; color: white; border: 2px solid #4b7289; "
            "border-radius: 6px;"
        )
        self.status = QLabel("Preparing the local registration scanner...")
        self.status.setWordWrap(True)
        self.status.setStyleSheet(
            "background: #eaf3f8; border: 1px solid #b7cfdd; border-radius: 4px; "
            "padding: 8px; color: #17324d;"
        )
        privacy = QLabel(
            "Camera frames, barcode payloads, owner information, and raw OCR text are "
            "not saved. Only supported vehicle fields returned to the vehicle form "
            "remain in memory."
        )
        privacy.setWordWrap(True)
        privacy.setStyleSheet("color: #4b5563;")

        self.capture_button = QPushButton("Capture and read")
        self.capture_button.setEnabled(False)
        self.capture_button.setStyleSheet(
            "font-weight: 700; padding: 7px 16px; background: #176b87; color: white;"
        )
        self.capture_button.clicked.connect(self._capture_and_read)
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Cancel)
        buttons.rejected.connect(self.reject)
        action_row = QHBoxLayout()
        action_row.addWidget(self.capture_button)
        action_row.addStretch(1)
        action_row.addWidget(buttons)

        layout = QVBoxLayout(self)
        layout.addWidget(heading)
        layout.addWidget(directions)
        layout.addLayout(state_row)
        layout.addLayout(camera_row)
        layout.addWidget(self.preview, 1)
        layout.addWidget(self.status)
        layout.addWidget(privacy)
        layout.addLayout(action_row)

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
                "Connect a camera and reopen this scanner, or enter the vehicle manually."
            )

    def _start_selected_camera(self, _index: int = 0) -> None:
        if self._closing or self._scan_in_flight:
            return
        self._stop_camera()
        index = self.camera_selector.currentIndex()
        if index < 0 or index >= len(self._devices):
            return
        self._latest_image = None
        self.capture_button.setEnabled(False)
        self.preview.setText("Starting camera...")
        if not self._scan_retry_message:
            self.status.setText(
                "Position the vehicle-information section inside the dashed rectangle."
            )
        self._camera = QCamera(self._devices[index], self)
        preferred_format = _preferred_camera_format(self._devices[index])
        if preferred_format is not None:
            self._camera.setCameraFormat(preferred_format)
        auto_focus = QCamera.FocusMode.FocusModeAuto
        if self._camera.isFocusModeSupported(auto_focus):
            self._camera.setFocusMode(auto_focus)
        self._camera.errorOccurred.connect(self._camera_error)
        self._capture_session.setCamera(self._camera)
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
            f"Camera error: {message} You can cancel and enter the vehicle manually."
        )
        self.capture_button.setEnabled(False)

    def _frame_changed(self, frame: QVideoFrame) -> None:
        if self._scan_in_flight:
            return
        image = frame.toImage()
        if image.isNull():
            return
        self._latest_image = image.copy()
        preview_pixmap = QPixmap.fromImage(image).scaled(
            self.preview.size(),
            Qt.AspectRatioMode.KeepAspectRatio,
            Qt.TransformationMode.SmoothTransformation,
        )
        guide = registration_guide_rect(
            preview_pixmap.width(),
            preview_pixmap.height(),
        )
        painter = QPainter(preview_pixmap)
        painter.setPen(QPen(QColor("#22d3ee"), 3, Qt.PenStyle.DashLine))
        painter.drawRoundedRect(guide, 8, 8)
        painter.end()
        self.preview.setPixmap(preview_pixmap)
        self.capture_button.setEnabled(True)
        if self._scan_retry_message:
            self.status.setText(
                self._scan_retry_message
                + " Camera is ready for another capture."
            )
        else:
            self.status.setText(
                f"Camera ready at {image.width()} x {image.height()}. "
                "Capture when the printed labels and values are sharp."
            )

    def _capture_and_read(self) -> None:
        if self._scan_in_flight or self._latest_image is None:
            return
        image = prepare_camera_registration_image(self._latest_image)
        self._latest_image = None
        self._scan_in_flight = True
        self._scan_retry_message = ""
        self.capture_button.setEnabled(False)
        self.state_selector.setEnabled(False)
        self.camera_selector.setEnabled(False)
        self._stop_camera()
        self.preview.clear()
        self.preview.setText("Reading the registration locally...")
        self.status.setText(
            "Checking supported 2D barcodes, document orientation, and printed vehicle fields..."
        )
        requested_state = self.state_selector.currentData() or AUTO_STATE
        future = self._executor.submit(
            scan_registration_image,
            image,
            requested_state,
        )
        future.add_done_callback(self._scan_completed)

    def _scan_completed(self, future: Future) -> None:
        try:
            data = future.result()
            outcome = RegistrationReadOutcome(data=data)
        except (RegistrationScanError, OcrUnavailableError) as error:
            outcome = RegistrationReadOutcome(error=str(error))
        except Exception:
            outcome = RegistrationReadOutcome(
                error="CrashX could not read that image. Adjust the registration and retry."
            )
        if not self._closing:
            self.scan_finished.emit(outcome)

    def _handle_scan_result(self, outcome: RegistrationReadOutcome) -> None:
        self._scan_in_flight = False
        if outcome.data is not None:
            self.scanned_data = outcome.data
            fields = ", ".join(outcome.data.populated_fields)
            self.status.setText(
                f"{outcome.data.jurisdiction} registration read. Returning {fields} "
                "to the vehicle form for officer review."
            )
            self.preview.clear()
            QTimer.singleShot(150, self.accept)
            return
        self._scan_retry_message = (
            (outcome.error or "The registration could not be read.")
            + " Reposition it and capture again, or cancel for manual entry."
        )
        self.status.setText(self._scan_retry_message + " Restarting the camera...")
        self.state_selector.setEnabled(True)
        self.camera_selector.setEnabled(True)
        QTimer.singleShot(250, self._start_selected_camera)

    def done(self, result: int) -> None:
        self._closing = True
        self._latest_image = None
        self._stop_camera()
        self._video_sink.setVideoFrame(QVideoFrame())
        self.preview.clear()
        self._executor.shutdown(wait=False, cancel_futures=True)
        super().done(result)

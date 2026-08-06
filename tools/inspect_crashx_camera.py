from __future__ import annotations

import sys
import time

from PySide6.QtCore import QCoreApplication, QTimer
from PySide6.QtMultimedia import (
    QCamera,
    QMediaCaptureSession,
    QMediaDevices,
    QVideoFrame,
    QVideoSink,
)


def main() -> int:
    application = QCoreApplication.instance() or QCoreApplication([])
    devices = list(QMediaDevices.videoInputs())
    print(f"Camera devices: {len(devices)}")
    for device in devices:
        print(f"\n{device.description()}")
        formats = sorted(
            device.videoFormats(),
            key=lambda item: (
                item.resolution().width() * item.resolution().height(),
                item.maxFrameRate(),
            ),
            reverse=True,
        )
        for camera_format in formats:
            resolution = camera_format.resolution()
            print(
                f"  {resolution.width()}x{resolution.height()} "
                f"{camera_format.minFrameRate():.1f}-{camera_format.maxFrameRate():.1f} fps "
                f"{camera_format.pixelFormat().name}"
            )
        camera = QCamera(device)
        supported_focus = [
            mode.name
            for mode in QCamera.FocusMode
            if camera.isFocusModeSupported(mode)
        ]
        print(f"  Supported focus modes: {', '.join(supported_focus) or 'none'}")
        print(f"  Zoom range: {camera.minimumZoomFactor():.2f}-{camera.maximumZoomFactor():.2f}")
        print(f"  Features: {camera.supportedFeatures()}")
    if "--live" in sys.argv and devices:
        print("\nLive capture:")
        camera = QCamera(devices[0])
        capture_session = QMediaCaptureSession()
        video_sink = QVideoSink()
        capture_session.setCamera(camera)
        capture_session.setVideoSink(video_sink)

        def frame_received(frame: QVideoFrame) -> None:
            size = frame.size()
            camera_format = camera.cameraFormat()
            configured = camera_format.resolution()
            print(
                f"  Configured: {configured.width()}x{configured.height()} "
                f"{camera_format.pixelFormat().name}"
            )
            print(
                f"  Frame: {size.width()}x{size.height()} "
                f"{frame.pixelFormat().name}"
            )
            if "--decode" in sys.argv:
                from crashx.ui.license_scan_dialog import (
                    decode_license_frame,
                )

                started = time.perf_counter()
                result = decode_license_frame(frame.toImage())
                elapsed = time.perf_counter() - started
                print(f"  Decoder: {result.outcome} in {elapsed:.3f} seconds")
            camera.stop()
            application.quit()

        video_sink.videoFrameChanged.connect(frame_received)
        QTimer.singleShot(5000, application.quit)
        camera.start()
        application.exec()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

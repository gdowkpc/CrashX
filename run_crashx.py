from __future__ import annotations

import sys
import tempfile
import traceback
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parent
SRC = PROJECT_ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))


def _self_test_destination() -> Path:
    index = sys.argv.index("--self-test")
    if index + 1 < len(sys.argv) and not sys.argv[index + 1].startswith("--"):
        return Path(sys.argv[index + 1])
    return Path(tempfile.gettempdir()) / "CrashX-SelfTest"


def _run_self_test() -> int:
    destination = _self_test_destination()
    try:
        from crashx.exchange_draft import (
            ExchangeReportDraft,
            save_exchange_report_pdf,
        )
        from crashx.models import (
            DriverProfile,
            ParticipantDetails,
            Person,
            Vehicle,
        )
        from crashx.ui.license_scan_dialog import decode_license_frame
        from PySide6.QtCore import Qt
        from PySide6.QtGui import QImage, QPainter
        import zxingcpp

        destination.mkdir(parents=True, exist_ok=True)
        draft = ExchangeReportDraft.empty()
        draft.case.case_number = "TEST-EXCHANGE"
        draft.case.investigator = "Test Officer"
        draft.crash_details.road_name = "Example Street"
        vehicle = draft.upsert_vehicle(
            Vehicle(
                id="",
                case_id=draft.case.id,
                vehicle_number="V-1",
                year="2024",
                make="Example",
                model="Sedan",
                plate="TEST123",
                plate_state="OR",
            )
        )
        person = Person(
            id="",
            case_id=draft.case.id,
            first_name="Test",
            last_name="Driver",
            roles=["Driver"],
        )
        draft.upsert_person(
            person,
            DriverProfile(person_id="", license_number="TEST-DL", license_state="OR"),
            ParticipantDetails(person_id="", vehicle_id=vehicle.id),
        )
        pdf_path = save_exchange_report_pdf(draft, destination / "exchange-self-test.pdf")
        if pdf_path.stat().st_size < 1000:
            raise OSError("The generated PDF is unexpectedly small.")
        if not pdf_path.read_bytes().startswith(b"%PDF-"):
            raise OSError("The generated file is not a PDF.")

        license_subfile = (
            "DLDAQTEST-DL\nDCSEXAMPLE\nDACCASEY\n"
            "DAG100 TEST STREET\nDAITEST CITY\nDAJOR\nDAK970000000\r"
        )
        license_payload = (
            "@\n\x1e\rANSI 636029100001"
            f"DL0031{len(license_subfile):04d}{license_subfile}"
        )
        synthetic_barcode = zxingcpp.create_barcode(
            license_payload,
            zxingcpp.BarcodeFormat.PDF417,
        ).to_image(scale=5)
        barcode_height, barcode_width = synthetic_barcode.shape
        barcode_image = QImage(
            bytes(synthetic_barcode),
            barcode_width,
            barcode_height,
            barcode_width,
            QImage.Format.Format_Grayscale8,
        ).copy()
        camera_frame = QImage(1920, 1080, QImage.Format.Format_RGB888)
        camera_frame.fill(Qt.GlobalColor.white)
        painter = QPainter(camera_frame)
        painter.drawImage(
            (camera_frame.width() - barcode_image.width()) // 2,
            (camera_frame.height() - barcode_image.height()) // 2,
            barcode_image,
        )
        painter.end()
        decoded_frame = decode_license_frame(camera_frame)
        if decoded_frame.data is None:
            raise OSError("The bundled camera-frame decoder did not read test data.")
        scanned_license = decoded_frame.data
        if (
            scanned_license.first_name != "CASEY"
            or scanned_license.last_name != "EXAMPLE"
            or scanned_license.license_state != "OR"
        ):
            raise OSError("The bundled AAMVA field mapper returned unexpected data.")
        (destination / "portable_self_test.txt").write_text(
            "PASS\n\n"
            "The standalone executable generated a PDF and decoded fictional "
            "AAMVA PDF417 data from a full-resolution camera-like frame. All test "
            "records were disposable and no case database was created.\n",
            encoding="utf-8",
        )
        return 0
    except Exception:
        destination.mkdir(parents=True, exist_ok=True)
        (destination / "portable_self_test.txt").write_text(
            "FAIL\n\n" + traceback.format_exc(),
            encoding="utf-8",
        )
        return 1


def main() -> int:
    if "--self-test" in sys.argv:
        return _run_self_test()
    try:
        from PySide6.QtWidgets import QApplication
        from crashx.ui.app_identity import (
            configure_exchange_application,
        )
        from crashx.ui.exchange_window import run
    except ModuleNotFoundError as exc:
        if exc.name == "PySide6":
            print(
                "PySide6 is required. Run: python -m pip install -r requirements.txt",
                file=sys.stderr,
            )
            return 2
        raise
    application = QApplication.instance() or QApplication(sys.argv)
    configure_exchange_application(application)
    return run()


if __name__ == "__main__":
    raise SystemExit(main())

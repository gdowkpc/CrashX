from __future__ import annotations

import os
import unittest

import zxingcpp

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import Qt
from PySide6.QtGui import QImage, QPainter
from PySide6.QtWidgets import QApplication

from crashx.license_scan import (
    AamvaParseError,
    ScannedLicenseData,
    parse_aamva_pdf417,
)
from crashx.ui.exchange_window import PersonEditorDialog
from crashx.ui.license_scan_dialog import decode_license_frame


def aamva_payload(
    *elements: str,
    issuer_id: str = "636029",
    version: str = "10",
) -> bytes:
    subfile = "DL" + "\n".join(elements) + "\r"
    offset = 31
    header = (
        "@\n\x1e\rANSI "
        f"{issuer_id}{version}0001"
        f"DL{offset:04d}{len(subfile):04d}"
    )
    return (header + subfile).encode("latin-1")


def camera_frame(payload: bytes, *, mirrored: bool = False) -> QImage:
    barcode = zxingcpp.create_barcode(
        payload.decode("latin-1"),
        zxingcpp.BarcodeFormat.PDF417,
    ).to_image(scale=5)
    height, width = barcode.shape
    barcode_image = QImage(
        bytes(barcode),
        width,
        height,
        width,
        QImage.Format.Format_Grayscale8,
    ).copy()
    if mirrored:
        barcode_image = barcode_image.flipped(Qt.Orientation.Horizontal)

    frame = QImage(1920, 1080, QImage.Format.Format_RGB888)
    frame.fill(Qt.GlobalColor.white)
    painter = QPainter(frame)
    painter.drawImage(
        (frame.width() - barcode_image.width()) // 2,
        (frame.height() - barcode_image.height()) // 2,
        barcode_image,
    )
    painter.end()
    return frame


class AamvaLicenseParserTest(unittest.TestCase):
    def test_us_license_maps_identity_address_and_issuing_state(self) -> None:
        scanned = parse_aamva_pdf417(
            aamva_payload(
                "DAQ1234567",
                "DCSDOE",
                "DACJANE",
                "DADMARIE",
                "DBB02031990",
                "DBC2",
                "DAG100 MAIN STREET",
                "DAHAPT 4",
                "DAISEATTLE",
                "DAJWA",
                "DAK981010000",
                "DCGUSA",
                "DCAC",
            )
        )

        self.assertEqual(scanned.first_name, "JANE")
        self.assertEqual(scanned.middle_name, "MARIE")
        self.assertEqual(scanned.last_name, "DOE")
        self.assertEqual(scanned.address, "100 MAIN STREET, APT 4")
        self.assertEqual(scanned.city, "SEATTLE")
        self.assertEqual(scanned.state, "WA")
        self.assertEqual(scanned.zip_code, "98101")
        self.assertEqual(scanned.license_number, "1234567")
        self.assertEqual(scanned.license_state, "OR")
        self.assertFalse(hasattr(scanned, "raw_payload"))
        self.assertFalse(hasattr(scanned, "date_of_birth"))
        self.assertFalse(hasattr(scanned, "sex"))
        self.assertFalse(hasattr(scanned, "license_class"))

    def test_canadian_postal_code_and_issuer_are_normalized(self) -> None:
        scanned = parse_aamva_pdf417(
            aamva_payload(
                "DAQON123",
                "DCSAMPLE",
                "DACCASEY",
                "DBB19900203",
                "DAG200 TEST ROAD",
                "DAITORONTO",
                "DAJON",
                "DAKK1A0B1",
                "DCGCAN",
                issuer_id="636012",
                version="11",
            )
        )

        self.assertEqual(scanned.zip_code, "K1A 0B1")
        self.assertEqual(scanned.license_state, "ON")
        self.assertEqual(scanned.aamva_version, "11")

    def test_legacy_given_names_are_split_when_modern_fields_are_absent(self) -> None:
        scanned = parse_aamva_pdf417(
            aamva_payload(
                "DAQLEGACY1",
                "DCSLEGACY",
                "DCTALEX MORGAN",
                version="05",
            )
        )

        self.assertEqual(scanned.first_name, "ALEX")
        self.assertEqual(scanned.middle_name, "MORGAN")
        self.assertEqual(scanned.last_name, "LEGACY")

    def test_non_aamva_payload_is_rejected_without_echoing_pii(self) -> None:
        with self.assertRaisesRegex(AamvaParseError, "not recognized"):
            parse_aamva_pdf417(b"This is not a driver license")


class LicenseCameraFrameTest(unittest.TestCase):
    def test_full_resolution_camera_frame_decodes_without_qimage_shortcut(self) -> None:
        result = decode_license_frame(
            camera_frame(
                aamva_payload(
                    "DAQCAMERA1",
                    "DCSFRAME",
                    "DACCASEY",
                    "DAG100 TEST STREET",
                    "DAIPORTLAND",
                    "DAJOR",
                    "DAK972010000",
                )
            )
        )

        self.assertEqual(result.outcome, "success")
        self.assertIsNotNone(result.data)
        self.assertEqual(result.data.first_name, "CASEY")
        self.assertEqual(result.data.license_number, "CAMERA1")

    def test_mirrored_camera_frame_is_recovered(self) -> None:
        result = decode_license_frame(
            camera_frame(
                aamva_payload("DAQMIRROR1", "DCSMIRROR", "DACRILEY"),
                mirrored=True,
            )
        )

        self.assertEqual(result.outcome, "success")
        self.assertIsNotNone(result.data)
        self.assertEqual(result.data.license_number, "MIRROR1")

    def test_empty_camera_frame_is_reported(self) -> None:
        self.assertEqual(decode_license_frame(QImage()).outcome, "empty")


class PersonLicenseScanWorkflowTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.application = QApplication.instance() or QApplication([])

    def test_scan_button_is_inside_person_dialog_and_mapped_values_are_reviewable(self) -> None:
        dialog = PersonEditorDialog([])
        self.assertEqual(dialog.windowTitle(), "Add person")
        self.assertEqual(dialog.scan_license_button.text(), "Scan license")

        dialog.apply_scanned_license(
            ScannedLicenseData(
                first_name="JANE",
                middle_name="MARIE",
                last_name="DOE",
                address="100 MAIN STREET",
                city="PORTLAND",
                state="OR",
                zip_code="97201",
                license_number="1234567",
                license_state="OR",
            )
        )

        self.assertEqual(dialog.first_name.text(), "JANE")
        self.assertEqual(dialog.license_number.text(), "1234567")
        self.assertTrue(dialog.scan_status.isVisibleTo(dialog))

        dialog.role_boxes["Driver"].setChecked(True)
        person, profile, _participant = dialog.records()
        self.assertEqual(person.dob, "")
        self.assertEqual(profile.license_state, "OR")
        dialog.close()

    def test_blank_scanned_values_do_not_erase_existing_manual_entries(self) -> None:
        dialog = PersonEditorDialog([])
        dialog.first_name.setText("Manual")
        dialog.apply_scanned_license(ScannedLicenseData(last_name="Person"))

        self.assertEqual(dialog.first_name.text(), "Manual")
        self.assertEqual(dialog.last_name.text(), "Person")
        dialog.close()


if __name__ == "__main__":
    unittest.main()

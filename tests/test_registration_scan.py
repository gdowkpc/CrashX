from __future__ import annotations

import unittest
from dataclasses import replace

import zxingcpp
from PySide6.QtGui import QImage

from crashx.registration_scan import (
    ScannedVehicleData,
    _infer_oregon_body_style,
    _parse_oregon,
    _parse_structured_barcode,
    decode_registration_barcode,
    detect_registration_state,
    prepare_camera_registration_image,
    registration_guide_rect,
)
from crashx.windows_ocr import OcrDocument, OcrWord


def barcode_image(payload: str) -> QImage:
    matrix = zxingcpp.create_barcode(
        payload,
        zxingcpp.BarcodeFormat.QRCode,
    ).to_image(scale=6)
    height, width = matrix.shape
    return QImage(
        bytes(matrix),
        width,
        height,
        width,
        QImage.Format.Format_Grayscale8,
    ).copy()


def word(text: str, x: float, y: float, width: float = 55) -> OcrWord:
    return OcrWord(text=text, x=x, y=y, width=width, height=12)


class RegistrationBarcodeTest(unittest.TestCase):
    def test_structured_qr_maps_only_supported_vehicle_fields(self) -> None:
        image = barcode_image(
            '{"plate":"TEST123","plate_state":"OR","year":"2024",'
            '"make":"EXAMPLE","model":"SEDAN","owner":"DO NOT MAP"}'
        )

        scanned = decode_registration_barcode(image)

        self.assertIsNotNone(scanned)
        assert scanned is not None
        self.assertEqual(scanned.plate, "TEST123")
        self.assertEqual(scanned.plate_state, "OR")
        self.assertEqual(scanned.year, "2024")
        self.assertEqual(scanned.make, "EXAMPLE")
        self.assertEqual(scanned.model, "SEDAN")
        self.assertFalse(hasattr(scanned, "owner"))

    def test_opaque_identifier_is_not_treated_as_vehicle_data(self) -> None:
        self.assertIsNone(_parse_structured_barcode(b"A1B2"))


class RegistrationCameraPreparationTest(unittest.TestCase):
    def test_camera_guide_region_is_cropped_and_enlarged_for_ocr(self) -> None:
        image = QImage(1000, 600, QImage.Format.Format_RGB32)
        image.fill(0)

        guide = registration_guide_rect(image.width(), image.height())
        prepared = prepare_camera_registration_image(image)

        self.assertEqual(guide.getRect(), (40, 72, 920, 456))
        self.assertEqual(prepared.width(), 2400)
        self.assertEqual(prepared.height(), 1190)


class OregonRegistrationParserTest(unittest.TestCase):
    def setUp(self) -> None:
        self.document = OcrDocument(
            width=1000,
            height=500,
            lines=(
                "OREGON PASSENGER REGISTRATION",
                "YEAR MAKE STYLE MODEL FUEL VEHICLE IDENTIFICATION NUMBER",
            ),
            words=(
                word("OREGON", 40, 40, 80),
                word("REGISTRATION", 430, 40, 130),
                word("TEST123", 55, 156, 75),
                word("YEAR", 60, 180, 40),
                word("STYLE", 260, 180, 50),
                word("MODEL", 360, 180, 55),
                word("FUEL", 460, 180, 45),
                word("VEHICLE", 560, 180, 60),
                word("IDENTIFICATION", 625, 180, 110),
                word("NUMBER", 740, 180, 65),
                word("2024", 60, 194, 45),
                word("EXAMPLE", 160, 194, 70),
                word("SD", 270, 194, 25),
                word("MODELX", 365, 194, 65),
                word("GASOLINE", 460, 194, 80),
            ),
        )

    def test_state_is_auto_detected_from_heading(self) -> None:
        self.assertEqual(detect_registration_state(self.document), "OR")

    def test_oregon_layout_maps_vehicle_row_and_ignores_other_text(self) -> None:
        scanned = _parse_oregon(self.document)

        self.assertEqual(
            scanned,
            ScannedVehicleData(
                jurisdiction="OR",
                year="2024",
                make="EXAMPLE",
                model="MODELX",
                body_style="SD",
                plate="TEST123",
                plate_state="OR",
                source="ocr",
            ),
        )

    def test_faint_year_and_style_labels_can_be_inferred_from_the_template(self) -> None:
        faint_document = replace(
            self.document,
            words=tuple(
                item
                for item in self.document.words
                if item.text not in {"YEAR", "STYLE"}
            ),
        )

        scanned = _parse_oregon(faint_document)

        self.assertEqual(scanned.year, "2024")
        self.assertEqual(scanned.make, "EXAMPLE")
        self.assertEqual(scanned.model, "MODELX")
        self.assertEqual(scanned.body_style, "SD")
        self.assertTrue(any("field labels were faint" in item for item in scanned.warnings))

    def test_a_repeated_header_label_is_not_returned_as_a_vehicle_value(self) -> None:
        label_echo_document = replace(
            self.document,
            words=tuple(
                replace(item, text="MODEL")
                if item.text == "MODELX"
                else item
                for item in self.document.words
            ),
        )

        scanned = _parse_oregon(label_echo_document)

        self.assertEqual(scanned.model, "")

    def test_oregon_pk_style_code_is_expanded_for_the_report(self) -> None:
        pickup_document = replace(
            self.document,
            words=tuple(
                replace(item, text="PK")
                if item.text == "SD"
                else item
                for item in self.document.words
            ),
        )

        scanned = _parse_oregon(pickup_document)

        self.assertEqual(scanned.body_style, "Pickup")

    def test_calibrated_ford_f_series_fallback_is_conservative(self) -> None:
        self.assertEqual(_infer_oregon_body_style("FORD", "F15"), "Pickup")
        self.assertEqual(_infer_oregon_body_style("FORD", "FOCUS"), "")
        self.assertEqual(_infer_oregon_body_style("EXAMPLE", "F15"), "")


if __name__ == "__main__":
    unittest.main()

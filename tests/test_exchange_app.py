from __future__ import annotations

import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication, QLabel
from PySide6.QtTest import QTest
from pypdf import PdfReader

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
from crashx.registration_scan import ScannedVehicleData
from crashx.ui.exchange_window import (
    ExchangeReportWindow,
    VehicleEditorDialog,
)


class ExchangeReportDraftTest(unittest.TestCase):
    def test_driver_and_passenger_associations_are_held_in_memory(self) -> None:
        draft = ExchangeReportDraft.empty()
        vehicle = draft.upsert_vehicle(
            Vehicle(id="", case_id="", vehicle_number="V-1", make="Ford")
        )
        driver = draft.upsert_person(
            Person(
                id="",
                case_id="",
                first_name="Dana",
                last_name="Driver",
                roles=["Driver"],
            ),
            DriverProfile(person_id="", license_number="D123"),
            ParticipantDetails(person_id="", vehicle_id=vehicle.id),
        )
        passenger = draft.upsert_person(
            Person(
                id="",
                case_id="",
                first_name="Pat",
                last_name="Passenger",
                roles=["Passenger"],
            ),
            participant=ParticipantDetails(person_id="", vehicle_id=vehicle.id),
        )

        self.assertEqual(vehicle.driver_person_id, driver.id)
        self.assertEqual(draft.participants[passenger.id].vehicle_id, vehicle.id)
        self.assertFalse(hasattr(draft, "database_path"))

    def test_one_vehicle_cannot_silently_receive_two_drivers(self) -> None:
        draft = ExchangeReportDraft.empty()
        vehicle = draft.upsert_vehicle(
            Vehicle(id="", case_id="", vehicle_number="V-1")
        )
        draft.upsert_person(
            Person(id="", case_id="", first_name="First", roles=["Driver"]),
            participant=ParticipantDetails(person_id="", vehicle_id=vehicle.id),
        )

        with self.assertRaisesRegex(ValueError, "already assigned"):
            draft.upsert_person(
                Person(id="", case_id="", first_name="Second", roles=["Driver"]),
                participant=ParticipantDetails(person_id="", vehicle_id=vehicle.id),
            )

        self.assertEqual(len(draft.people), 1)

    def test_removing_records_clears_associations_without_a_saved_case(self) -> None:
        draft = ExchangeReportDraft.empty()
        vehicle = draft.upsert_vehicle(
            Vehicle(id="", case_id="", vehicle_number="V-1")
        )
        person = draft.upsert_person(
            Person(id="", case_id="", first_name="Alex", roles=["Driver"]),
            participant=ParticipantDetails(person_id="", vehicle_id=vehicle.id),
        )

        draft.remove_vehicle(vehicle.id)
        self.assertIsNone(draft.participants[person.id].vehicle_id)
        draft.remove_person(person.id)
        self.assertEqual(draft.people, [])
        self.assertEqual(draft.profiles, {})
        self.assertEqual(draft.participants, {})

    def test_atomic_save_writes_only_the_requested_pdf(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            draft = ExchangeReportDraft.empty()
            draft.case.case_number = "26-EXCHANGE-1"
            draft.case.investigator = "Officer Example"
            draft.crash_details.road_name = "Example Street"
            vehicle = draft.upsert_vehicle(
                Vehicle(
                    id="",
                    case_id="",
                    vehicle_number="V-1",
                    year="2025",
                    make="Honda",
                    model="Accord",
                    plate="123ABC",
                    plate_state="OR",
                )
            )
            draft.upsert_person(
                Person(
                    id="",
                    case_id="",
                    first_name="Jamie",
                    last_name="Example",
                    address="100 Main Street",
                    city="Portland",
                    state="OR",
                    roles=["Driver"],
                ),
                DriverProfile(person_id="", license_number="DL-100", license_state="OR"),
                ParticipantDetails(person_id="", vehicle_id=vehicle.id),
            )

            path = save_exchange_report_pdf(draft, root / "exchange.pdf")

            self.assertEqual([item.name for item in root.iterdir()], ["exchange.pdf"])
            reader = PdfReader(path)
            text = "\n".join(page.extract_text() or "" for page in reader.pages)
            self.assertIn("26-EXCHANGE-1", text)
            self.assertIn("Example, Jamie", text)
            self.assertIn("TRAFFIC CRASH EXCHANGE REPORT", text)
            self.assertIn("CrashX", text)

    def test_blank_officer_uses_standalone_pdf_metadata(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = save_exchange_report_pdf(
                ExchangeReportDraft.empty(),
                Path(directory) / "blank.pdf",
            )

            self.assertEqual(PdfReader(path).metadata.author, "CrashX")


class ExchangeReportWindowTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.application = QApplication.instance() or QApplication([])

    def test_window_saves_form_fields_without_creating_a_database(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            window = ExchangeReportWindow()
            self.assertEqual(window.windowTitle(), "CrashX")
            labels = {label.text() for label in window.findChildren(QLabel)}
            self.assertIn("Location of Crash", labels)
            self.assertNotIn("Road / location", labels)
            self.assertNotIn("Cross street / reference", labels)
            window.case_number.setText("26-WINDOW-1")
            window.crash_date.setText("08/06/2026")
            window.crash_time.setText("2:45 PM")
            window.road_name.setText("North Test Avenue")
            window.officer.setText("Officer Window")

            path = window.save_to(root / "window-output")

            self.assertEqual(path.suffix, ".pdf")
            self.assertEqual(window.draft.case.crash_date, "2026-08-06")
            self.assertEqual(window.draft.case.crash_time, "14:45")
            self.assertEqual(window.draft.case.location, "North Test Avenue")
            self.assertEqual(
                window.draft.crash_details.road_name, "North Test Avenue"
            )
            self.assertEqual(window.draft.crash_details.intersection_road, "")
            self.assertEqual(
                sorted(item.name for item in root.iterdir()),
                ["window-output.pdf"],
            )
            window.close()

    def test_vehicle_plate_and_insurance_fields_autoformat_as_uppercase(self) -> None:
        dialog = VehicleEditorDialog()
        dialog.show()

        entries = (
            (dialog.plate, "abc 123", "ABC 123"),
            (dialog.plate_state, "or", "OR"),
            (dialog.insurance_company, "example mutual", "EXAMPLE MUTUAL"),
            (dialog.policy_number, "pol-2468x", "POL-2468X"),
        )
        for editor, value, expected in entries:
            editor.setFocus()
            QTest.keyClicks(editor, value)
            self.assertEqual(editor.text(), expected)

        vehicle = dialog.record()
        self.assertEqual(vehicle.plate, "ABC 123")
        self.assertEqual(vehicle.plate_state, "OR")
        self.assertEqual(vehicle.insurance_company, "EXAMPLE MUTUAL")
        self.assertEqual(vehicle.insurance_policy_number, "POL-2468X")
        dialog.close()

    def test_registration_scan_populates_only_returned_vehicle_fields(self) -> None:
        dialog = VehicleEditorDialog()
        dialog.insurance_company.setText("EXISTING INSURER")
        dialog.color.setText("Existing color")

        dialog.apply_scanned_registration(
            ScannedVehicleData(
                jurisdiction="OR",
                year="2024",
                make="EXAMPLE",
                model="MODELX",
                body_style="SD",
                plate="TEST123",
                plate_state="OR",
                source="ocr",
            )
        )

        self.assertEqual(dialog.year.text(), "2024")
        self.assertEqual(dialog.make.text(), "EXAMPLE")
        self.assertEqual(dialog.model.text(), "MODELX")
        self.assertEqual(dialog.body_style.text(), "SD")
        self.assertEqual(dialog.plate.text(), "TEST123")
        self.assertEqual(dialog.plate_state.text(), "OR")
        self.assertEqual(dialog.color.text(), "Existing color")
        self.assertEqual(dialog.insurance_company.text(), "EXISTING INSURER")
        self.assertTrue(dialog.scan_status.isVisibleTo(dialog))
        self.assertIn("Review every field", dialog.scan_status.text())
        dialog.close()

    def test_clear_replaces_all_in_memory_state(self) -> None:
        window = ExchangeReportWindow()
        original_case_id = window.draft.case.id
        window.case_number.setText("DISCARD-ME")
        window.draft.upsert_vehicle(
            Vehicle(id="", case_id="", vehicle_number="V-1")
        )

        window.reset_draft()

        self.assertNotEqual(window.draft.case.id, original_case_id)
        self.assertEqual(window.case_number.text(), "")
        self.assertEqual(window.draft.vehicles, [])
        window.close()


class ExchangeApplicationBoundaryTest(unittest.TestCase):
    def test_standalone_entry_point_does_not_open_notebook_storage(self) -> None:
        project_root = Path(__file__).parents[1]
        source = (project_root / "run_crashx.py").read_text(
            encoding="utf-8"
        )
        renderer_source = (
            project_root / "src" / "crashx" / "exchange_report.py"
        ).read_text(encoding="utf-8")
        self.assertNotIn("CaseRepository", source)
        self.assertNotIn("ensure_startup_storage", source)
        self.assertNotIn("TCN_DATA_DIR", source)
        self.assertNotIn("from .repository", renderer_source)

    def test_source_self_test_uses_only_fictional_pdf_output(self) -> None:
        project_root = Path(__file__).parents[1]
        with tempfile.TemporaryDirectory() as directory:
            result = subprocess.run(
                [
                    sys.executable,
                    str(project_root / "run_crashx.py"),
                    "--self-test",
                    directory,
                ],
                cwd=project_root,
                capture_output=True,
                text=True,
                check=False,
            )

            self.assertEqual(result.returncode, 0, result.stderr)
            outputs = sorted(item.name for item in Path(directory).iterdir())
            self.assertEqual(
                outputs,
                ["exchange-self-test.pdf", "portable_self_test.txt"],
            )
            self.assertEqual(
                (Path(directory) / "portable_self_test.txt")
                .read_text(encoding="utf-8")
                .splitlines()[0],
                "PASS",
            )

    def test_portable_target_is_non_admin_and_separate_from_notebook(self) -> None:
        project_root = Path(__file__).parents[1]
        manifest = (
            project_root / "assets" / "windows" / "CrashX.manifest"
        ).read_text(encoding="utf-8")
        build_script = (
            project_root / "scripts" / "build_exchange_windows.ps1"
        ).read_text(encoding="utf-8")

        self.assertIn('level="asInvoker"', manifest)
        self.assertNotIn("requireAdministrator", manifest)
        self.assertIn("--name CrashX", build_script)
        self.assertIn("run_crashx.py", build_script)
        self.assertIn("--self-test", build_script)
        self.assertIn("--exclude-module sqlite3", build_script)
        self.assertIn("CrashX.png;assets/windows", build_script)
        self.assertNotIn('"$ProjectRoot\\assets;assets"', build_script)
        self.assertNotIn("generate_release_manifests.py", build_script)


if __name__ == "__main__":
    unittest.main()

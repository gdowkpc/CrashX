from __future__ import annotations

import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from PySide6.QtWidgets import QApplication

from crashx.exchange_draft import ExchangeReportDraft
from crashx.models import ParticipantDetails, Person, Vehicle
from crashx.ui.app_identity import configure_exchange_application
from crashx.ui.exchange_window import ExchangeReportWindow


def main() -> Path:
    application = QApplication.instance() or QApplication([])
    configure_exchange_application(application)
    draft = ExchangeReportDraft.empty()
    draft.case.case_number = "26-EXCHANGE-QA"
    draft.case.crash_date = "08/06/2026"
    draft.case.crash_time = "02:35 PM"
    draft.case.investigator = "Officer Jordan Example"
    draft.case.assigned_officer_dpsst = "12345"
    draft.case.assignment = "Traffic Division"
    draft.crash_details.road_name = "North Example Boulevard"
    draft.crash_details.intersection_road = "West Sample Avenue"
    vehicle = draft.upsert_vehicle(
        Vehicle(
            id="",
            case_id="",
            vehicle_number="V-1",
            year="2024",
            make="Toyota",
            model="Camry",
            color="Blue",
            plate="QA1TEST",
            plate_state="OR",
            insurance_company="Example Insurance",
            insurance_policy_number="POLICY-0001",
        )
    )
    draft.upsert_person(
        Person(
            id="",
            case_id="",
            first_name="Jordan",
            last_name="Driver",
            address="100 Driver Street",
            city="Portland",
            state="OR",
            cell_phone="503-555-2000",
            roles=["Driver"],
        ),
        participant=ParticipantDetails(person_id="", vehicle_id=vehicle.id),
    )
    draft.upsert_person(
        Person(
            id="",
            case_id="",
            first_name="Avery",
            last_name="Passenger",
            address="200 Passenger Avenue",
            city="Portland",
            state="OR",
            cell_phone="503-555-3000",
            roles=["Passenger"],
        ),
        participant=ParticipantDetails(person_id="", vehicle_id=vehicle.id),
    )

    window = ExchangeReportWindow(draft)
    window.show()
    application.processEvents()
    output = ROOT / "tmp" / "exchange-app-window.png"
    output.parent.mkdir(parents=True, exist_ok=True)
    if not window.grab().save(str(output), "PNG"):
        raise OSError(f"Could not save window preview: {output}")
    window.close()
    return output


if __name__ == "__main__":
    try:
        print(main())
    except Exception as error:
        print(f"ERROR: {error}", file=sys.stderr)
        raise SystemExit(1) from error
    raise SystemExit(0)

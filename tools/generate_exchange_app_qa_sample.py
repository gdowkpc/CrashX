from __future__ import annotations

import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

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


def main() -> Path:
    draft = ExchangeReportDraft.empty()
    draft.case.case_number = "26-EXCHANGE-QA"
    draft.case.crash_date = "2026-08-06"
    draft.case.crash_time = "14:35"
    draft.case.investigator = "Officer Jordan Example"
    draft.case.assigned_officer_dpsst = "12345"
    draft.case.assignment = "Traffic Division"
    draft.crash_details.road_name = "North Example Boulevard"
    draft.crash_details.intersection_road = "West Sample Avenue"

    vehicles: list[Vehicle] = []
    for index in range(5):
        number = index + 1
        vehicle = draft.upsert_vehicle(
            Vehicle(
                id="",
                case_id="",
                vehicle_number=f"V-{number}",
                year=str(2020 + index),
                make=("Toyota", "Ford", "Honda", "Subaru", "Chevrolet")[index],
                model=("Camry", "F-150", "Civic", "Outback", "Tahoe")[index],
                body_style=("Sedan", "Pickup", "Sedan", "Wagon", "SUV")[index],
                color=("Blue", "White", "Silver", "Green", "Black")[index],
                plate=f"QA{number}TEST",
                plate_state="OR",
                insurance_company=f"Example Insurance {number}",
                insurance_policy_number=f"POLICY-{number:04d}",
                property_damage="Roadside fence" if index == 1 else "None reported",
            )
        )
        vehicles.append(vehicle)
        draft.upsert_person(
            Person(
                id="",
                case_id="",
                first_name=("Jordan", "Taylor", "Morgan", "Casey", "Riley")[index],
                middle_name="Q",
                last_name=f"Driver{number}",
                address=f"{100 + index} Driver Street",
                city="Portland",
                state="OR",
                zip_code=f"9720{index}",
                home_phone=f"503-555-10{index:02d}",
                cell_phone=f"503-555-20{index:02d}",
                roles=["Driver"],
            ),
            DriverProfile(
                person_id="",
                license_number=f"OR-DL-{number:04d}",
                license_state="OR",
            ),
            ParticipantDetails(person_id="", vehicle_id=vehicle.id),
        )

    additional_people = (
        ("Avery", "Passenger", "Passenger", vehicles[0].id),
        ("Quinn", "Passenger", "Passenger", vehicles[0].id),
        ("Skyler", "Passenger", "Passenger", vehicles[1].id),
        ("Parker", "Witness", "Witness", None),
        ("Reese", "Witness", "Witness", vehicles[2].id),
        ("Cameron", "Pedestrian", "Pedestrian", None),
        ("Drew", "Bicyclist", "Bicyclist", None),
        ("Emerson", "Observer", "Witness", None),
        ("Finley", "Passenger", "Passenger", vehicles[3].id),
        ("Hayden", "Bystander", "Witness", None),
    )
    for index, (first_name, last_name, role, vehicle_id) in enumerate(
        additional_people
    ):
        draft.upsert_person(
            Person(
                id="",
                case_id="",
                first_name=first_name,
                last_name=last_name,
                address=f"{300 + index} Exchange Lane",
                city="Portland",
                state="OR",
                zip_code=f"9721{index}",
                cell_phone=f"971-555-30{index:02d}",
                roles=[role],
            ),
            participant=ParticipantDetails(person_id="", vehicle_id=vehicle_id),
        )

    destination = (
        ROOT / "output" / "pdf" / "CrashX-Standalone-QA.pdf"
    )
    return save_exchange_report_pdf(draft, destination)


if __name__ == "__main__":
    try:
        result = main()
        print(result)
    except Exception as error:
        print(f"ERROR: {error}", file=sys.stderr)
        raise SystemExit(1) from error
    raise SystemExit(0)

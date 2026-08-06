from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(slots=True)
class CrashCase:
    id: str
    case_number: str = ""
    crash_date: str = ""
    crash_time: str = ""
    location: str = ""
    investigator: str = ""
    assigned_officer_dpsst: str = ""
    assignment: str = ""


@dataclass(slots=True)
class Person:
    id: str
    case_id: str
    first_name: str = ""
    middle_name: str = ""
    last_name: str = ""
    # Kept blank as an explicit privacy invariant; CrashX never maps or publishes DOB.
    dob: str = ""
    cell_phone: str = ""
    home_phone: str = ""
    work_phone: str = ""
    address: str = ""
    city: str = ""
    state: str = ""
    zip_code: str = ""
    roles: list[str] = field(default_factory=list)

    @property
    def display_name(self) -> str:
        return " ".join(
            part.strip()
            for part in (self.first_name, self.middle_name, self.last_name)
            if part.strip()
        ) or "Unnamed person"


@dataclass(slots=True)
class Vehicle:
    id: str
    case_id: str
    vehicle_number: str = ""
    year: str = ""
    make: str = ""
    model: str = ""
    body_style: str = ""
    color: str = ""
    plate: str = ""
    plate_state: str = ""
    owner_person_id: str | None = None
    driver_person_id: str | None = None
    insurance: str = ""
    insurance_company: str = ""
    insurance_policy_number: str = ""
    property_damage: str = ""

    @property
    def description(self) -> str:
        description = " ".join(
            part for part in (self.year, self.make, self.model) if part
        )
        return description or "Unidentified vehicle"


def format_crash_location(road_name: str, intersection_road: str) -> str:
    return " / ".join(
        value.strip()
        for value in (road_name, intersection_road)
        if value and value.strip()
    )


@dataclass(slots=True)
class CrashDetails:
    case_id: str
    road_name: str = ""
    intersection_road: str = ""


@dataclass(slots=True)
class ExchangeReportDetails:
    case_id: str
    assisting_officer: str = ""
    precinct: str = ""


@dataclass(slots=True)
class ParticipantDetails:
    person_id: str
    vehicle_id: str | None = None


@dataclass(slots=True)
class DriverProfile:
    person_id: str
    license_number: str = ""
    license_state: str = ""

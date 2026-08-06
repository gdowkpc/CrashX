from __future__ import annotations

import os
import tempfile
from dataclasses import dataclass, field
from pathlib import Path
from uuid import uuid4

from . import __version__
from .exchange_report import (
    ExchangeReportDocument,
    export_exchange_report_document_pdf,
)
from .models import (
    CrashCase,
    CrashDetails,
    DriverProfile,
    ExchangeReportDetails,
    ParticipantDetails,
    Person,
    Vehicle,
)


EXCHANGE_ROLES = (
    "Driver",
    "Passenger",
    "Witness",
    "Pedestrian",
    "Bicyclist",
)


def new_draft_id(prefix: str) -> str:
    return f"{prefix}-{uuid4().hex}"


@dataclass(slots=True)
class ExchangeReportDraft:
    """Disposable in-memory state for the standalone exchange-report app."""

    case: CrashCase
    crash_details: CrashDetails
    exchange_details: ExchangeReportDetails
    people: list[Person] = field(default_factory=list)
    vehicles: list[Vehicle] = field(default_factory=list)
    profiles: dict[str, DriverProfile] = field(default_factory=dict)
    participants: dict[str, ParticipantDetails] = field(default_factory=dict)

    @classmethod
    def empty(cls) -> ExchangeReportDraft:
        case_id = new_draft_id("case")
        return cls(
            case=CrashCase(id=case_id),
            crash_details=CrashDetails(case_id=case_id),
            exchange_details=ExchangeReportDetails(case_id=case_id),
        )

    def document(self) -> ExchangeReportDocument:
        return ExchangeReportDocument(
            case=self.case,
            crash_details=self.crash_details,
            exchange_details=self.exchange_details,
            people=list(self.people),
            vehicles=list(self.vehicles),
            profiles=dict(self.profiles),
            participants=dict(self.participants),
        )

    def vehicle(self, vehicle_id: str | None) -> Vehicle | None:
        return next(
            (vehicle for vehicle in self.vehicles if vehicle.id == vehicle_id),
            None,
        )

    def person(self, person_id: str | None) -> Person | None:
        return next(
            (person for person in self.people if person.id == person_id),
            None,
        )

    def upsert_vehicle(self, vehicle: Vehicle) -> Vehicle:
        if not vehicle.id:
            vehicle.id = new_draft_id("vehicle")
        vehicle.case_id = self.case.id
        for index, existing in enumerate(self.vehicles):
            if existing.id == vehicle.id:
                self.vehicles[index] = vehicle
                return vehicle
        self.vehicles.append(vehicle)
        return vehicle

    def remove_vehicle(self, vehicle_id: str) -> None:
        self.vehicles = [
            vehicle for vehicle in self.vehicles if vehicle.id != vehicle_id
        ]
        for participant in self.participants.values():
            if participant.vehicle_id == vehicle_id:
                participant.vehicle_id = None

    def upsert_person(
        self,
        person: Person,
        profile: DriverProfile | None = None,
        participant: ParticipantDetails | None = None,
    ) -> Person:
        if not person.id:
            person.id = new_draft_id("person")
        person.case_id = self.case.id
        profile = profile or DriverProfile(person_id=person.id)
        profile.person_id = person.id
        participant = participant or ParticipantDetails(person_id=person.id)
        participant.person_id = person.id

        associated_vehicle = self.vehicle(participant.vehicle_id)
        if participant.vehicle_id and associated_vehicle is None:
            raise ValueError("The selected vehicle is no longer available.")
        if "Driver" in person.roles and associated_vehicle is not None:
            other_driver = self.person(associated_vehicle.driver_person_id)
            if other_driver is not None and other_driver.id != person.id:
                raise ValueError(
                    f"{associated_vehicle.vehicle_number or associated_vehicle.description} "
                    f"is already assigned to driver {other_driver.display_name}."
                )

        for vehicle in self.vehicles:
            if vehicle.driver_person_id == person.id:
                vehicle.driver_person_id = None
        if "Driver" in person.roles and associated_vehicle is not None:
            associated_vehicle.driver_person_id = person.id

        for index, existing in enumerate(self.people):
            if existing.id == person.id:
                self.people[index] = person
                break
        else:
            self.people.append(person)
        self.profiles[person.id] = profile
        self.participants[person.id] = participant
        return person

    def remove_person(self, person_id: str) -> None:
        self.people = [person for person in self.people if person.id != person_id]
        self.profiles.pop(person_id, None)
        self.participants.pop(person_id, None)
        for vehicle in self.vehicles:
            if vehicle.driver_person_id == person_id:
                vehicle.driver_person_id = None
            if vehicle.owner_person_id == person_id:
                vehicle.owner_person_id = None


def save_exchange_report_pdf(
    draft: ExchangeReportDraft,
    destination: str | Path,
) -> Path:
    """Atomically save the only durable artifact produced by the draft."""

    destination_path = Path(destination).resolve()
    destination_path.parent.mkdir(parents=True, exist_ok=True)
    temporary_handle = tempfile.NamedTemporaryFile(
        mode="wb",
        prefix=f".{destination_path.stem}-",
        suffix=".pdf",
        dir=destination_path.parent,
        delete=False,
    )
    temporary_path = Path(temporary_handle.name)
    temporary_handle.close()
    try:
        export_exchange_report_document_pdf(
            draft.document(),
            temporary_path,
            generator_label=f"CrashX v{__version__}",
            default_author="CrashX",
        )
        if not temporary_path.is_file() or temporary_path.stat().st_size == 0:
            raise OSError("The PDF renderer did not create a complete file.")
        os.replace(temporary_path, destination_path)
    finally:
        temporary_path.unlink(missing_ok=True)
    return destination_path

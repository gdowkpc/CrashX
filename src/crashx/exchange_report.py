from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

from reportlab.lib import colors
from reportlab.lib.enums import TA_CENTER, TA_LEFT
from reportlab.lib.pagesizes import letter
from reportlab.lib.styles import ParagraphStyle
from reportlab.lib.units import inch
from reportlab.pdfbase.pdfmetrics import stringWidth
from reportlab.pdfgen import canvas
from reportlab.platypus import Paragraph

from . import __version__
from .date_format import format_date_for_display, format_time_for_display
from .models import (
    CrashCase,
    CrashDetails,
    DriverProfile,
    ExchangeReportDetails,
    ParticipantDetails,
    Person,
    Vehicle,
    format_crash_location,
)
VEHICLE_BLOCK_HEIGHT = 1.58 * inch
PERSON_BLOCK_HEIGHT = 0.75 * inch
CONTENT_HEIGHT_PER_PAGE = 8.45 * inch
EXCHANGE_PERSON_ROLES = {
    "Driver",
    "Passenger",
    "Pedestrian",
    "Bicyclist",
    "Witness",
    "Victim",
    "Vehicle Owner",
}

LINE_COLOR = colors.HexColor("#27323A")
LABEL_COLOR = colors.HexColor("#3F4B53")
LIGHT_FILL = colors.HexColor("#F1F3F4")


@dataclass(slots=True)
class ExchangeReportDocument:
    """All records needed to render one exchange report without persistence."""

    case: CrashCase
    crash_details: CrashDetails
    exchange_details: ExchangeReportDetails
    people: list[Person] = field(default_factory=list)
    vehicles: list[Vehicle] = field(default_factory=list)
    profiles: dict[str, DriverProfile] = field(default_factory=dict)
    participants: dict[str, ParticipantDetails] = field(default_factory=dict)


INFORMATION_PAGE_POLICY = (
    "This crash <b>WILL NOT</b> be investigated. Police are not required to "
    "investigate traffic crashes, but do investigate certain crashes as a matter "
    "of policy. The Portland Police Bureau's policy is as follows: A traffic crash "
    "will be investigated when a person is injured and the injury is substantial "
    "enough to require the person to be transported via ambulance, <b>AND</b> the "
    "person is entered into the regional trauma system. The decision to enter an "
    "injured party into the trauma system is made by the on-scene emergency medical "
    "personnel, not the police or the parties involved in the traffic crash."
)
INFORMATION_PAGE_REPORTING_INTRO = (
    "<b>EVERY</b> driver involved in a traffic crash resulting in any of the "
    "following <b>MUST</b> file an Oregon Traffic Accident and Insurance Report "
    "under any of the following circumstances."
)
INFORMATION_PAGE_REPORTING_ITEMS = (
    "Damage to your vehicle is over $2500",
    "Damage to any one person's property other than a vehicle is over $2500",
    "Damage to any vehicle is over $2500, <b>AND</b> any vehicle was towed from "
    "the scene as a result of damages from this accident",
    "Injury to any person",
    "Death to any person",
)
INFORMATION_PAGE_FILING = (
    "Oregon Law requires these reports be filed within 72 hours of the crash "
    "(excluding weekends and holidays). If your crash was investigated and an "
    "Oregon Police Crash Report was filed, you are still required to file your own "
    "Oregon Traffic Accident and Insurance Report with the DMV. If you are an "
    "out-of-state resident, you are still required to file your own Oregon Traffic "
    "Accident and Insurance Report with the Oregon DMV. You must report a traffic "
    "crash, even if it happened on private property that is premises open to the "
    "public. (Example: A store parking lot or an apartment complex parking lot)."
)
INFORMATION_PAGE_LOCATIONS = (
    "Oregon Traffic Accident and Insurance Report Forms may be obtained statewide "
    "from any police or sheriff's agency or DMV office. Listed below are Portland "
    "Police Bureau locations in which you may pick up the Oregon Traffic Accident "
    "and Insurance Report Form. Please call for current hours, as they may vary "
    "from each location:"
)


def person_name_last_first(person: Person | None) -> str:
    if person is None:
        return ""
    given = " ".join(
        value for value in (person.first_name, person.middle_name) if value
    )
    if person.last_name and given:
        return f"{person.last_name}, {given}"
    return person.last_name or given


def person_exchange_address(person: Person | None) -> str:
    if person is None:
        return ""
    state_zip = " ".join(value for value in (person.state, person.zip_code) if value)
    return ", ".join(
        value for value in (person.address, person.city, state_zip) if value
    )


def person_exchange_phone(person: Person | None) -> str:
    if person is None:
        return ""
    return "  ".join(
        value for value in (
            f"HM {person.home_phone}" if person.home_phone else "",
            f"BU {person.work_phone}" if person.work_phone else "",
            f"CL {person.cell_phone}" if person.cell_phone else "",
        ) if value
    )


def person_has_role(person: Person, role: str) -> bool:
    expected = role.strip().casefold()
    return any(value.strip().casefold() == expected for value in person.roles)


def vehicle_exchange_party(
    vehicle: Vehicle,
    people: dict[str, Person],
) -> Person | None:
    explicit_driver = people.get(vehicle.driver_person_id)
    if explicit_driver is not None:
        return explicit_driver
    owner = people.get(vehicle.owner_person_id)
    if owner is not None and person_has_role(owner, "Driver"):
        return owner
    return None


def resolve_exchange_vehicle_drivers(
    vehicles: list[Vehicle],
    people: list[Person],
    participants: dict[str, ParticipantDetails] | None = None,
) -> dict[str, Person]:
    """Resolve each vehicle's driver without silently substituting its owner.

    Older case data may contain a Driver person without a vehicle.driver_person_id.
    The participant-to-vehicle link is authoritative when present. A final
    one-driver/one-vehicle inference keeps an unambiguous legacy case usable; when
    multiple matches are possible, the people remain separate driver records on
    the exchange report instead of being guessed into the wrong vehicle block.
    """
    people_by_id = {person.id: person for person in people}
    details = participants or {}
    resolved: dict[str, Person] = {}
    used_person_ids: set[str] = set()

    for vehicle in vehicles:
        driver = vehicle_exchange_party(vehicle, people_by_id)
        if driver is not None and driver.id not in used_person_ids:
            resolved[vehicle.id] = driver
            used_person_ids.add(driver.id)

    for vehicle in vehicles:
        if vehicle.id in resolved:
            continue
        associated = [
            person
            for person in people
            if person.id not in used_person_ids
            and person_has_role(person, "Driver")
            and details.get(person.id) is not None
            and details[person.id].vehicle_id == vehicle.id
        ]
        if len(associated) == 1:
            resolved[vehicle.id] = associated[0]
            used_person_ids.add(associated[0].id)

    unresolved_vehicles = [
        vehicle for vehicle in vehicles if vehicle.id not in resolved
    ]
    unassigned_drivers = [
        person
        for person in people
        if person.id not in used_person_ids and person_has_role(person, "Driver")
    ]
    if len(unresolved_vehicles) == 1 and len(unassigned_drivers) == 1:
        resolved[unresolved_vehicles[0].id] = unassigned_drivers[0]

    return resolved


def exchange_report_people(
    people: list[Person],
    vehicles: list[Vehicle],
    participants: dict[str, ParticipantDetails] | None = None,
) -> list[Person]:
    """Return involved people not already printed in a vehicle/driver block."""
    represented_person_ids = {
        driver.id
        for driver in resolve_exchange_vehicle_drivers(
            vehicles,
            people,
            participants,
        ).values()
    }
    return [
        person
        for person in people
        if person.id not in represented_person_ids
        and any(person_has_role(person, role) for role in EXCHANGE_PERSON_ROLES)
    ]


def exchange_report_page_plan(
    vehicles: list[Vehicle],
    people: list[Person],
) -> list[tuple[list[Vehicle], list[Person]]]:
    """Pack only existing records onto as few readable front pages as possible."""
    items: list[tuple[str, Vehicle | Person, float]] = [
        ("vehicle", vehicle, VEHICLE_BLOCK_HEIGHT) for vehicle in vehicles
    ]
    items.extend(
        ("person", person, PERSON_BLOCK_HEIGHT) for person in people
    )
    if not items:
        return [([], [])]

    pages: list[tuple[list[Vehicle], list[Person]]] = []
    item_index = 0
    while item_index < len(items):
        page_vehicles: list[Vehicle] = []
        page_people: list[Person] = []
        remaining_height = CONTENT_HEIGHT_PER_PAGE
        while item_index < len(items):
            kind, record, block_height = items[item_index]
            if block_height > remaining_height and (page_vehicles or page_people):
                break
            if kind == "vehicle":
                page_vehicles.append(record)  # type: ignore[arg-type]
            else:
                page_people.append(record)  # type: ignore[arg-type]
            remaining_height -= block_height
            item_index += 1
        pages.append((page_vehicles, page_people))
    return pages


def _fit_text(
    pdf: canvas.Canvas,
    value: str,
    x: float,
    y: float,
    width: float,
    *,
    font_name: str = "Helvetica",
    font_size: float = 8.2,
    minimum_size: float = 5.2,
    bold: bool = False,
) -> None:
    text = " ".join(str(value or "").split())
    if not text:
        return
    if bold and font_name == "Helvetica":
        font_name = "Helvetica-Bold"
    available = max(1.0, width)
    size = font_size
    while size > minimum_size and stringWidth(text, font_name, size) > available:
        size -= 0.25
    if stringWidth(text, font_name, size) > available:
        suffix = "..."
        while text and stringWidth(text + suffix, font_name, size) > available:
            text = text[:-1]
        text = text.rstrip() + suffix
    pdf.setFont(font_name, size)
    pdf.setFillColor(colors.black)
    pdf.drawString(x, y, text)


def _draw_cell(
    pdf: canvas.Canvas,
    x: float,
    y: float,
    width: float,
    height: float,
    label: str,
    value: str = "",
    *,
    fill: colors.Color | None = None,
) -> None:
    if fill is not None:
        pdf.setFillColor(fill)
        pdf.rect(x, y, width, height, stroke=0, fill=1)
    pdf.setStrokeColor(LINE_COLOR)
    pdf.setLineWidth(0.55)
    pdf.rect(x, y, width, height, stroke=1, fill=0)
    pdf.setFillColor(LABEL_COLOR)
    _fit_text(
        pdf,
        label.upper(),
        x + 4,
        y + height - 6.5,
        width - 8,
        font_name="Helvetica-Bold",
        font_size=5.8,
        minimum_size=4.8,
    )
    _fit_text(
        pdf,
        value,
        x + 4,
        y + 3.5,
        width - 8,
        font_size=8.2,
        minimum_size=5.2,
    )


def _draw_checkbox(
    pdf: canvas.Canvas,
    x: float,
    y: float,
    checked: bool,
) -> None:
    size = 7.0
    pdf.setStrokeColor(LINE_COLOR)
    pdf.setLineWidth(0.6)
    pdf.rect(x, y, size, size, stroke=1, fill=0)
    if checked:
        pdf.setLineWidth(1.1)
        pdf.line(x + 1.3, y + 1.3, x + size - 1.3, y + size - 1.3)
        pdf.line(x + 1.3, y + size - 1.3, x + size - 1.3, y + 1.3)


def _draw_header(
    pdf: canvas.Canvas,
    *,
    page_number: int,
    page_count: int,
    case_number: str,
    crash_datetime: str,
    location: str,
    left: float,
    top: float,
    width: float,
) -> float:
    title_height = 0.34 * inch
    page_width = 1.05 * inch
    _draw_cell(
        pdf,
        left,
        top - title_height,
        width - page_width,
        title_height,
        "",
        "",
        fill=LIGHT_FILL,
    )
    _draw_cell(
        pdf,
        left + width - page_width,
        top - title_height,
        page_width,
        title_height,
        "PAGE / OF",
        f"{page_number} / {page_count}",
        fill=LIGHT_FILL,
    )
    pdf.setFillColor(LINE_COLOR)
    pdf.setFont("Helvetica-BoldOblique", 14)
    pdf.drawCentredString(
        left + (width - page_width) / 2,
        top - title_height + 8,
        "TRAFFIC CRASH EXCHANGE REPORT",
    )

    y = top - title_height
    notice_height = 0.28 * inch
    pdf.setFillColor(colors.black)
    pdf.rect(left, y - notice_height, width, notice_height, stroke=0, fill=1)
    pdf.setFillColor(colors.white)
    pdf.setFont("Helvetica-Bold", 10.2)
    pdf.drawCentredString(
        left + width / 2,
        y - notice_height + 6.1,
        "TRAFFIC CRASH INFORMATION EXCHANGE - RETAIN THIS FORM",
    )

    y -= notice_height
    information_height = 0.27 * inch
    _draw_cell(
        pdf,
        left,
        y - information_height,
        width,
        information_height,
        "",
        "",
        fill=LIGHT_FILL,
    )
    pdf.setFillColor(LABEL_COLOR)
    pdf.setFont("Helvetica", 7.7)
    pdf.drawCentredString(
        left + width / 2,
        y - information_height + 6.0,
        "Please retain for your records and insurance purposes. The Portland Police Bureau will not retain a copy of this form.",
    )

    y -= information_height
    crash_height = 0.43 * inch
    date_width = 2.05 * inch
    _draw_cell(
        pdf,
        left,
        y - crash_height,
        date_width,
        crash_height,
        "CRASH DATE / TIME",
        crash_datetime,
    )
    _draw_cell(
        pdf,
        left + date_width,
        y - crash_height,
        width - date_width,
        crash_height,
        "LOCATION OF CRASH",
        location,
    )
    arrow_x = left + width - 13
    arrow_y = y - crash_height + 11
    pdf.setStrokeColor(LINE_COLOR)
    pdf.setLineWidth(0.6)
    pdf.circle(arrow_x, arrow_y, 6, stroke=1, fill=0)
    pdf.line(arrow_x, arrow_y - 4, arrow_x, arrow_y + 4)
    pdf.line(arrow_x, arrow_y + 4, arrow_x - 2, arrow_y + 1)
    pdf.line(arrow_x, arrow_y + 4, arrow_x + 2, arrow_y + 1)
    pdf.setFont("Helvetica-Bold", 5.5)
    pdf.drawCentredString(arrow_x, arrow_y + 7.5, "N")

    if case_number:
        pdf.setFillColor(LABEL_COLOR)
        pdf.setFont("Helvetica", 5.5)
        pdf.drawRightString(
            left + width - page_width - 4,
            top - title_height + 3,
            f"CASE {case_number}",
        )
    return y - crash_height


def _draw_vehicle_block(
    pdf: canvas.Canvas,
    *,
    vehicle: Vehicle | None,
    driver: Person | None,
    profiles: dict[str, object],
    left: float,
    top: float,
    width: float,
    height: float,
) -> float:
    party = driver
    profile = profiles.get(party.id) if party else None
    row_height = height / 6.0
    y = top - row_height
    vehicle_tag = f" - {vehicle.vehicle_number}" if vehicle and vehicle.vehicle_number else ""
    _draw_cell(
        pdf,
        left,
        y,
        width,
        row_height,
        f"NAME (LAST, FIRST, MI){vehicle_tag}",
        person_name_last_first(party),
    )

    y -= row_height
    address_width = width - 2.45 * inch
    license_width = 1.65 * inch
    state_width = width - address_width - license_width
    _draw_cell(
        pdf,
        left,
        y,
        address_width,
        row_height,
        "ADDRESS",
        person_exchange_address(party),
    )
    _draw_cell(
        pdf,
        left + address_width,
        y,
        license_width,
        row_height,
        "OPERATOR LICENSE NO.",
        getattr(profile, "license_number", "") if profile else "",
    )
    _draw_cell(
        pdf,
        left + address_width + license_width,
        y,
        state_width,
        row_height,
        "STATE",
        getattr(profile, "license_state", "") if profile else "",
    )

    y -= row_height
    _draw_cell(
        pdf,
        left,
        y,
        width,
        row_height,
        "PHONE: HM  BU  CL",
        person_exchange_phone(party),
    )

    y -= row_height
    insurance_width = 4.15 * inch
    _draw_cell(
        pdf,
        left,
        y,
        insurance_width,
        row_height,
        "INSURANCE COMPANY (NOT AGENT)",
        (vehicle.insurance_company or vehicle.insurance) if vehicle else "",
    )
    _draw_cell(
        pdf,
        left + insurance_width,
        y,
        width - insurance_width,
        row_height,
        "INSURANCE POLICY NUMBER",
        vehicle.insurance_policy_number if vehicle else "",
    )

    y -= row_height
    plate_width = 1.55 * inch
    plate_state_width = 0.80 * inch
    year_width = 1.10 * inch
    _draw_cell(
        pdf,
        left,
        y,
        plate_width,
        row_height,
        "LICENSE NO.",
        vehicle.plate if vehicle else "",
    )
    _draw_cell(
        pdf,
        left + plate_width,
        y,
        plate_state_width,
        row_height,
        "STATE",
        vehicle.plate_state if vehicle else "",
    )
    _draw_cell(
        pdf,
        left + plate_width + plate_state_width,
        y,
        year_width,
        row_height,
        "VEH YR",
        vehicle.year if vehicle else "",
    )
    _draw_cell(
        pdf,
        left + plate_width + plate_state_width + year_width,
        y,
        width - plate_width - plate_state_width - year_width,
        row_height,
        "MAKE",
        vehicle.make if vehicle else "",
    )

    y -= row_height
    model_width = 1.72 * inch
    style_width = 1.10 * inch
    color_width = 1.05 * inch
    _draw_cell(
        pdf,
        left,
        y,
        model_width,
        row_height,
        "MODEL",
        vehicle.model if vehicle else "",
    )
    _draw_cell(
        pdf,
        left + model_width,
        y,
        style_width,
        row_height,
        "STYLE",
        vehicle.body_style if vehicle else "",
    )
    _draw_cell(
        pdf,
        left + model_width + style_width,
        y,
        color_width,
        row_height,
        "COLOR",
        vehicle.color if vehicle else "",
    )
    _draw_cell(
        pdf,
        left + model_width + style_width + color_width,
        y,
        width - model_width - style_width - color_width,
        row_height,
        "PROPERTY DAMAGED (HOUSE, FENCE, SIGN, ETC.)",
        vehicle.property_damage if vehicle else "",
    )
    return top - height


def _draw_person_block(
    pdf: canvas.Canvas,
    *,
    person: Person,
    participant_vehicle: str,
    left: float,
    top: float,
    width: float,
    height: float,
) -> float:
    upper_height = height * 0.52
    lower_height = height - upper_height
    upper_y = top - upper_height
    lower_y = upper_y - lower_height
    pdf.setStrokeColor(LINE_COLOR)
    pdf.setLineWidth(0.55)
    pdf.rect(left, upper_y, width, upper_height, stroke=1, fill=0)
    name = person_name_last_first(person)
    role_line_y = upper_y + upper_height - 9
    name_line_y = upper_y + 4
    pdf.setFillColor(LABEL_COLOR)
    pdf.setFont("Helvetica-Bold", 5.6)
    role_x = left + 4
    listed_roles = (
        ("Driver", "DRIVER"),
        ("Passenger", "PASSENGER"),
        ("Witness", "WITNESS"),
        ("Pedestrian", "PEDESTRIAN"),
        ("Bicyclist", "BICYCLIST"),
    )
    for role, label in listed_roles:
        _draw_checkbox(
            pdf,
            role_x,
            role_line_y - 1,
            person_has_role(person, role),
        )
        pdf.drawString(role_x + 11, role_line_y, label)
        role_x += 17 + stringWidth(label, "Helvetica-Bold", 5.6)
    listed_role_names = {item[0].casefold() for item in listed_roles}
    other_roles = [
        role for role in person.roles if role.strip().casefold() not in listed_role_names
    ]
    if other_roles:
        _fit_text(
            pdf,
            "ROLES: " + ", ".join(other_roles),
            role_x + 3,
            role_line_y,
            left + width - role_x - 7,
            font_size=5.6,
            bold=True,
        )

    pdf.setFillColor(LABEL_COLOR)
    pdf.setFont("Helvetica-Bold", 5.8)
    pdf.drawString(left + 4, name_line_y, "PERSON NAME (LAST, FIRST, MI)")
    display_name = (
        f"{name} ({participant_vehicle})" if participant_vehicle else name
    )
    _fit_text(
        pdf,
        display_name,
        left + 125,
        name_line_y,
        width - 132,
        font_size=8.0,
    )

    address_width = width - 2.15 * inch
    _draw_cell(
        pdf,
        left,
        lower_y,
        address_width,
        lower_height,
        "ADDRESS",
        person_exchange_address(person),
    )
    _draw_cell(
        pdf,
        left + address_width,
        lower_y,
        width - address_width,
        lower_height,
        "PHONE: HM  BU  CL",
        person_exchange_phone(person),
    )
    return top - height


def _draw_footer(
    pdf: canvas.Canvas,
    *,
    details,
    investigator: str,
    dpsst: str,
    assignment: str,
    case_number: str,
    generator_label: str,
    left: float,
    top: float,
    width: float,
) -> None:
    field_height = 0.34 * inch
    dpsst_width = 1.0 * inch
    precinct_width = 1.75 * inch
    officer_width = width - dpsst_width - precinct_width
    _draw_cell(
        pdf,
        left,
        top - field_height,
        officer_width,
        field_height,
        "ASSIGNED OFFICER",
        investigator or details.assisting_officer,
    )
    _draw_cell(
        pdf,
        left + officer_width,
        top - field_height,
        dpsst_width,
        field_height,
        "DPSST",
        dpsst,
    )
    _draw_cell(
        pdf,
        left + officer_width + dpsst_width,
        top - field_height,
        precinct_width,
        field_height,
        "PRECINCT",
        assignment or details.precinct,
    )
    footer_y = top - field_height - 10
    pdf.setFillColor(LABEL_COLOR)
    pdf.setFont("Helvetica", 6.2)
    if case_number:
        pdf.drawString(left, footer_y, f"CASE {case_number}")
    pdf.drawCentredString(left + width / 2, footer_y, "ORIGINAL / INVOLVED PARTIES")
    pdf.drawRightString(
        left + width,
        footer_y,
        generator_label,
    )


def _draw_information_paragraph(
    pdf: canvas.Canvas,
    text: str,
    *,
    x: float,
    top: float,
    width: float,
    style: ParagraphStyle,
    space_after: float = 0,
    bullet_text: str | None = None,
) -> float:
    paragraph = Paragraph(text, style, bulletText=bullet_text)
    _, height = paragraph.wrap(width, letter[1])
    paragraph.drawOn(pdf, x, top - height)
    return top - height - space_after


def _draw_information_heading(
    pdf: canvas.Canvas,
    text: str,
    *,
    left: float,
    top: float,
    width: float,
) -> float:
    height = 18.0
    pdf.setFillColor(LIGHT_FILL)
    pdf.setStrokeColor(LINE_COLOR)
    pdf.setLineWidth(0.75)
    pdf.rect(left, top - height, width, height, stroke=1, fill=1)
    pdf.setFillColor(colors.black)
    pdf.setFont("Helvetica-Bold", 10.8)
    pdf.drawCentredString(left + width / 2, top - height + 5.2, text)
    return top - height


def _draw_back_page(pdf: canvas.Canvas) -> None:
    """Draw a clean, searchable transcription of PPB form 770 (12/17)."""
    page_width, page_height = letter
    left = 0.40 * inch
    bottom = 0.36 * inch
    width = page_width - 2 * left
    top = page_height - 0.36 * inch
    body_left = left + 8
    body_width = width - 16

    body_style = ParagraphStyle(
        "ExchangeInformationBody",
        fontName="Helvetica",
        fontSize=8.05,
        leading=9.55,
        textColor=colors.black,
        alignment=TA_LEFT,
    )
    centered_style = ParagraphStyle(
        "ExchangeInformationCentered",
        parent=body_style,
        alignment=TA_CENTER,
        fontSize=8.7,
        leading=10.2,
    )
    disclaimer_style = ParagraphStyle(
        "ExchangeInformationDisclaimer",
        parent=centered_style,
        fontName="Helvetica-Bold",
        fontSize=11.4,
        leading=13.0,
    )
    bullet_style = ParagraphStyle(
        "ExchangeInformationBullet",
        parent=body_style,
        leftIndent=20,
        firstLineIndent=0,
        bulletIndent=7,
        fontSize=8.0,
        leading=9.35,
    )
    warning_style = ParagraphStyle(
        "ExchangeInformationWarning",
        parent=centered_style,
        fontName="Helvetica-BoldOblique",
        fontSize=8.7,
        leading=10.3,
    )

    pdf.setFillColor(colors.white)
    pdf.rect(0, 0, page_width, page_height, stroke=0, fill=1)
    pdf.setStrokeColor(LINE_COLOR)
    pdf.setLineWidth(1.1)
    pdf.rect(left, bottom, width, top - bottom, stroke=1, fill=0)

    title_height = 24.0
    pdf.setFillColor(colors.black)
    pdf.rect(left, top - title_height, width, title_height, stroke=0, fill=1)
    pdf.setFillColor(colors.white)
    pdf.setFont("Helvetica-Bold", 13.0)
    pdf.drawCentredString(
        left + width / 2,
        top - title_height + 6.4,
        "INFORMATION / YOUR RESPONSIBILITIES",
    )
    y = top - title_height - 4
    y = _draw_information_paragraph(
        pdf,
        "THIS FORM WILL ASSIST YOU IN FILING OUT YOUR TRAFFIC ACCIDENT AND "
        "INSURANCE REPORT FORMS",
        x=body_left,
        top=y,
        width=body_width,
        style=centered_style,
        space_after=2,
    )
    y = _draw_information_paragraph(
        pdf,
        "IT IS NOT AN OFFICIAL OREGON POLICE TRAFFIC CRASH REPORT",
        x=body_left,
        top=y,
        width=body_width,
        style=disclaimer_style,
        space_after=2,
    )
    y = _draw_information_paragraph(
        pdf,
        "Please retain for your records and insurance purposes. The Portland "
        "Police Bureau will not retain a copy of this form.",
        x=body_left,
        top=y,
        width=body_width,
        style=centered_style,
        space_after=4,
    )

    y = _draw_information_heading(
        pdf,
        "PORTLAND POLICE BUREAU POLICY STATEMENT",
        left=left,
        top=y,
        width=width,
    ) - 6
    y = _draw_information_paragraph(
        pdf,
        INFORMATION_PAGE_POLICY,
        x=body_left,
        top=y,
        width=body_width,
        style=body_style,
        space_after=6,
    )
    y = _draw_information_paragraph(
        pdf,
        "State Law requires involved parties to report certain traffic crashes as "
        "outlined below.",
        x=body_left,
        top=y,
        width=body_width,
        style=body_style,
        space_after=5,
    )

    y = _draw_information_heading(
        pdf,
        "TRAFFIC CRASH REPORTING REQUIREMENTS",
        left=left,
        top=y,
        width=width,
    ) - 6
    y = _draw_information_paragraph(
        pdf,
        INFORMATION_PAGE_REPORTING_INTRO,
        x=body_left,
        top=y,
        width=body_width,
        style=body_style,
        space_after=3,
    )
    for item in INFORMATION_PAGE_REPORTING_ITEMS:
        y = _draw_information_paragraph(
            pdf,
            item,
            x=body_left,
            top=y,
            width=body_width,
            style=bullet_style,
            space_after=1,
            bullet_text="-",
        )
    y -= 3
    y = _draw_information_paragraph(
        pdf,
        INFORMATION_PAGE_FILING,
        x=body_left,
        top=y,
        width=body_width,
        style=body_style,
        space_after=6,
    )
    y = _draw_information_paragraph(
        pdf,
        "If you fail to report the traffic crash to the Oregon DMV, it may result "
        "in suspension of your driving privileges.",
        x=body_left,
        top=y,
        width=body_width,
        style=warning_style,
        space_after=7,
    )
    y = _draw_information_paragraph(
        pdf,
        INFORMATION_PAGE_LOCATIONS,
        x=body_left,
        top=y,
        width=body_width,
        style=body_style,
        space_after=5,
    )

    location_rows = (
        ("Central Precinct", "1111 SW 2nd Avenue", "(503) 823-0097"),
        ("East Precinct", "737 SE 106th Avenue", "(503) 823-4800"),
        ("North Precinct", "449 NE Emerson Street", "(503) 823-5700"),
    )
    pdf.setFillColor(colors.black)
    pdf.setFont("Helvetica", 8.4)
    for precinct, address, phone in location_rows:
        y -= 12.0
        pdf.drawString(body_left + 92, y, precinct)
        pdf.drawString(body_left + 244, y, address)
        pdf.drawString(body_left + 414, y, phone)
    y -= 8

    if y < bottom + 105:
        raise RuntimeError("The exchange-report information page exceeded its layout.")
    notes_heading_height = 17.0
    pdf.setFillColor(LIGHT_FILL)
    pdf.setStrokeColor(LINE_COLOR)
    pdf.rect(
        left,
        y - notes_heading_height,
        width,
        notes_heading_height,
        stroke=1,
        fill=1,
    )
    pdf.setFillColor(colors.black)
    pdf.setFont("Helvetica", 8.2)
    pdf.drawCentredString(
        left + width / 2,
        y - notes_heading_height + 5.0,
        "SPACE BELOW PROVIDED FOR PERSONAL NOTE TAKING",
    )
    line_y = y - notes_heading_height - 16
    pdf.setStrokeColor(LINE_COLOR)
    pdf.setLineWidth(0.45)
    while line_y > bottom + 14:
        pdf.line(left, line_y, left + width, line_y)
        line_y -= 18

    pdf.setFillColor(LABEL_COLOR)
    pdf.setFont("Helvetica", 6.2)
    pdf.drawRightString(left + width - 3, bottom + 3, "770 (12/17)")
    pdf.showPage()


def export_exchange_report_document_pdf(
    document: ExchangeReportDocument,
    destination: str | Path,
    *,
    generator_label: str = f"CrashX v{__version__}",
    default_author: str = "CrashX",
) -> Path:
    """Render an exchange report from records already held by the caller."""

    case = document.case
    crash_details = document.crash_details
    exchange_details = document.exchange_details
    people_list = document.people
    vehicles = document.vehicles
    profiles = document.profiles
    participants = {
        person.id: document.participants.get(
            person.id,
            ParticipantDetails(person_id=person.id),
        )
        for person in people_list
    }
    vehicle_drivers = resolve_exchange_vehicle_drivers(
        vehicles,
        people_list,
        participants,
    )
    exchange_people = exchange_report_people(
        people_list,
        vehicles,
        participants,
    )
    vehicle_labels = {
        vehicle.id: vehicle.vehicle_number or vehicle.description
        for vehicle in vehicles
    }
    page_plan = exchange_report_page_plan(vehicles, exchange_people)
    page_count = len(page_plan)
    destination_path = Path(destination)
    destination_path.parent.mkdir(parents=True, exist_ok=True)
    pdf = canvas.Canvas(str(destination_path), pagesize=letter, pageCompression=1)
    pdf.setTitle(
        f"Traffic Crash Exchange Report - {case.case_number or 'Untitled Case'}"
    )
    pdf.setAuthor(case.investigator or default_author)
    pdf.setSubject("Traffic crash information exchange report")

    page_width, page_height = letter
    left = 0.38 * inch
    top = page_height - 0.38 * inch
    content_width = page_width - (2 * left)
    crash_datetime = " ".join(
        value for value in (
            format_date_for_display(case.crash_date),
            format_time_for_display(case.crash_time),
        ) if value
    )
    location = format_crash_location(
        crash_details.road_name,
        crash_details.intersection_road,
    ) or case.location

    for page_index, (page_vehicles, page_people) in enumerate(page_plan):
        current_top = _draw_header(
            pdf,
            page_number=page_index + 1,
            page_count=page_count,
            case_number=case.case_number,
            crash_datetime=crash_datetime,
            location=location,
            left=left,
            top=top,
            width=content_width,
        )

        for vehicle in page_vehicles:
            current_top = _draw_vehicle_block(
                pdf,
                vehicle=vehicle,
                driver=vehicle_drivers.get(vehicle.id),
                profiles=profiles,
                left=left,
                top=current_top,
                width=content_width,
                height=VEHICLE_BLOCK_HEIGHT,
            )

        for person in page_people:
            participant_vehicle = vehicle_labels.get(
                participants[person.id].vehicle_id,
                "",
            )
            current_top = _draw_person_block(
                pdf,
                person=person,
                participant_vehicle=participant_vehicle,
                left=left,
                top=current_top,
                width=content_width,
                height=PERSON_BLOCK_HEIGHT,
            )

        _draw_footer(
            pdf,
            details=exchange_details,
            investigator=case.investigator,
            dpsst=case.assigned_officer_dpsst,
            assignment=case.assignment,
            case_number=case.case_number,
            generator_label=generator_label,
            left=left,
            top=0.85 * inch,
            width=content_width,
        )
        pdf.showPage()

    _draw_back_page(pdf)
    pdf.save()
    return destination_path

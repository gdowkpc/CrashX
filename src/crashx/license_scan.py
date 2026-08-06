from __future__ import annotations

import re
from dataclasses import dataclass


class AamvaParseError(ValueError):
    """Raised when decoded barcode bytes are not usable AAMVA DL/ID data."""


@dataclass(frozen=True, slots=True)
class ScannedLicenseData:
    """The small, mapped subset CrashX uses; raw barcode data is not retained."""

    issuer_id: str = ""
    aamva_version: str = ""
    jurisdiction_version: str = ""
    first_name: str = ""
    middle_name: str = ""
    last_name: str = ""
    address: str = ""
    city: str = ""
    state: str = ""
    zip_code: str = ""
    license_number: str = ""
    license_state: str = ""


# AAMVA's public IIN table identifies the issuing jurisdiction. CrashX uses the
# postal/provincial abbreviation for the driver-license state field. The table
# currently prints "GM" for Colorado; "CO" is the applicable postal code.
_ISSUER_JURISDICTIONS: dict[str, tuple[str, str]] = {
    "604426": ("PE", "CAN"),
    "604427": ("AS", "USA"),
    "604428": ("QC", "CAN"),
    "604429": ("YT", "CAN"),
    "604430": ("MP", "USA"),
    "604431": ("PR", "USA"),
    "604432": ("AB", "CAN"),
    "604433": ("NU", "CAN"),
    "604434": ("NT", "CAN"),
    "636000": ("VA", "USA"),
    "636001": ("NY", "USA"),
    "636002": ("MA", "USA"),
    "636003": ("MD", "USA"),
    "636004": ("NC", "USA"),
    "636005": ("SC", "USA"),
    "636006": ("CT", "USA"),
    "636007": ("LA", "USA"),
    "636008": ("MT", "USA"),
    "636009": ("NM", "USA"),
    "636010": ("FL", "USA"),
    "636011": ("DE", "USA"),
    "636012": ("ON", "CAN"),
    "636013": ("NS", "CAN"),
    "636014": ("CA", "USA"),
    "636015": ("TX", "USA"),
    "636016": ("NL", "CAN"),
    "636017": ("NB", "CAN"),
    "636018": ("IA", "USA"),
    "636019": ("GU", "USA"),
    "636020": ("CO", "USA"),
    "636021": ("AR", "USA"),
    "636022": ("KS", "USA"),
    "636023": ("OH", "USA"),
    "636024": ("VT", "USA"),
    "636025": ("PA", "USA"),
    "636026": ("AZ", "USA"),
    "636027": ("", "USA"),
    "636028": ("BC", "CAN"),
    "636029": ("OR", "USA"),
    "636030": ("MO", "USA"),
    "636031": ("WI", "USA"),
    "636032": ("MI", "USA"),
    "636033": ("AL", "USA"),
    "636034": ("ND", "USA"),
    "636035": ("IL", "USA"),
    "636036": ("NJ", "USA"),
    "636037": ("IN", "USA"),
    "636038": ("MN", "USA"),
    "636039": ("NH", "USA"),
    "636040": ("UT", "USA"),
    "636041": ("ME", "USA"),
    "636042": ("SD", "USA"),
    "636043": ("DC", "USA"),
    "636044": ("SK", "CAN"),
    "636045": ("WA", "USA"),
    "636046": ("KY", "USA"),
    "636047": ("HI", "USA"),
    "636048": ("MB", "CAN"),
    "636049": ("NV", "USA"),
    "636050": ("ID", "USA"),
    "636051": ("MS", "USA"),
    "636052": ("RI", "USA"),
    "636053": ("TN", "USA"),
    "636054": ("NE", "USA"),
    "636055": ("GA", "USA"),
    "636056": ("CU", "MEX"),
    "636057": ("HL", "MEX"),
    "636058": ("OK", "USA"),
    "636059": ("AK", "USA"),
    "636060": ("WY", "USA"),
    "636061": ("WV", "USA"),
    "636062": ("VI", "USA"),
}

_UNAVAILABLE_VALUES = {"", "NONE", "UNAVL", "UNAVAIL", "UNKNOWN"}


def _clean(value: str | None) -> str:
    text = " ".join((value or "").replace("\x00", "").strip().split())
    return "" if text.upper() in _UNAVAILABLE_VALUES else text


def _clean_name(value: str | None) -> str:
    return _clean((value or "").replace(",", " "))


def _parse_header(text: str) -> tuple[str, str, str, list[tuple[str, int, int]]]:
    start = text.find("@")
    if start < 0 or text[start + 4 : start + 9] not in {"ANSI ", "AAMVA"}:
        raise AamvaParseError("The barcode is not recognized as AAMVA DL/ID data.")

    fixed = start + 9
    if len(text) < fixed + 12:
        raise AamvaParseError("The AAMVA barcode header is incomplete.")
    issuer_id = text[fixed : fixed + 6]
    aamva_version = text[fixed + 6 : fixed + 8]
    jurisdiction_version = text[fixed + 8 : fixed + 10]
    entry_count_text = text[fixed + 10 : fixed + 12]
    if not issuer_id.isdigit() or not entry_count_text.isdigit():
        raise AamvaParseError("The AAMVA barcode header is malformed.")

    entry_count = int(entry_count_text)
    descriptors: list[tuple[str, int, int]] = []
    cursor = fixed + 12
    for _ in range(entry_count):
        descriptor = text[cursor : cursor + 10]
        if len(descriptor) != 10 or not descriptor[2:].isdigit():
            raise AamvaParseError("The AAMVA subfile directory is malformed.")
        descriptors.append(
            (descriptor[:2], int(descriptor[2:6]), int(descriptor[6:10]))
        )
        cursor += 10
    return issuer_id, aamva_version, jurisdiction_version, descriptors


def _subfile_fields(
    text: str,
    descriptors: list[tuple[str, int, int]],
) -> dict[str, str]:
    fields: dict[str, str] = {}
    start = text.find("@")
    data_separator = text[start + 1]
    segment_terminator = text[start + 3]

    for subfile_type, offset, length in descriptors:
        if subfile_type not in {"DL", "ID"}:
            continue
        subfile = text[start + offset : start + offset + length]
        if not subfile.startswith(subfile_type):
            continue
        for element in subfile[2:].split(data_separator):
            element = element.strip("\x00\x1d\x1e" + segment_terminator)
            if len(element) < 3 or not re.fullmatch(r"[A-Z][A-Z0-9]{2}", element[:3]):
                continue
            fields.setdefault(element[:3], element[3:])
    return fields


def _fallback_fields(text: str) -> dict[str, str]:
    fields: dict[str, str] = {}
    for match in re.finditer(
        r"(?:^|[\n\r\x1d\x1e])(?:DL|ID)?([A-Z][A-Z0-9]{2})([^\n\r\x1d\x1e]*)",
        text,
    ):
        fields.setdefault(match.group(1), match.group(2))
    return fields


def _format_postal_code(value: str) -> str:
    postal_code = _clean(value).upper()
    digits = re.sub(r"\D", "", postal_code)
    if postal_code.isdigit() and len(digits) == 9:
        return digits[:5] if digits[5:] == "0000" else f"{digits[:5]}-{digits[5:]}"
    if re.fullmatch(r"[A-Z]\d[A-Z]\s?\d[A-Z]\d", postal_code):
        compact = postal_code.replace(" ", "")
        return f"{compact[:3]} {compact[3:]}"
    return postal_code


def parse_aamva_pdf417(payload: bytes | str) -> ScannedLicenseData:
    """Parse mapped AAMVA fields without retaining the source barcode payload."""

    text = payload.decode("latin-1", errors="replace") if isinstance(payload, bytes) else payload
    issuer_id, aamva_version, jurisdiction_version, descriptors = _parse_header(text)
    fields = _subfile_fields(text, descriptors)
    if not fields:
        fields = _fallback_fields(text)

    if not any(_clean(fields.get(key)) for key in ("DAQ", "DCS", "DAB", "DAC", "DCT", "DAA")):
        raise AamvaParseError("The barcode did not contain usable person or license fields.")

    last_name = _clean_name(fields.get("DCS") or fields.get("DAB"))
    first_name = _clean_name(fields.get("DAC"))
    middle_name = _clean_name(fields.get("DAD"))

    if not first_name and fields.get("DCT"):
        given_names = _clean_name(fields["DCT"]).split()
        if given_names:
            first_name = given_names[0]
            if not middle_name:
                middle_name = " ".join(given_names[1:])
    if (not first_name or not last_name) and fields.get("DAA"):
        name_parts = [_clean_name(part) for part in fields["DAA"].split(",")]
        if len(name_parts) >= 2:
            last_name = last_name or name_parts[0]
            first_name = first_name or name_parts[1]
            if not middle_name and len(name_parts) >= 3:
                middle_name = name_parts[2]

    license_state = _ISSUER_JURISDICTIONS.get(issuer_id, ("", ""))[0]
    address_lines = [
        part for part in (_clean(fields.get("DAG")), _clean(fields.get("DAH"))) if part
    ]
    return ScannedLicenseData(
        issuer_id=issuer_id,
        aamva_version=aamva_version,
        jurisdiction_version=jurisdiction_version,
        first_name=first_name,
        middle_name=middle_name,
        last_name=last_name,
        address=", ".join(address_lines),
        city=_clean(fields.get("DAI")),
        state=_clean(fields.get("DAJ")).upper(),
        zip_code=_format_postal_code(fields.get("DAK", "")),
        license_number=_clean(fields.get("DAQ")),
        license_state=license_state,
    )

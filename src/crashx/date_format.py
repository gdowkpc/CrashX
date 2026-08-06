from __future__ import annotations

from datetime import date, datetime, time


DISPLAY_DATE_PLACEHOLDER = "MM/DD/YYYY"
DISPLAY_TIME_PLACEHOLDER = "HH:MM AM/PM"
_DISPLAY_DATE_FORMAT = "%m/%d/%Y"
_STORAGE_DATE_FORMAT = "%Y-%m-%d"
_ACCEPTED_DATE_FORMATS = (_STORAGE_DATE_FORMAT, _DISPLAY_DATE_FORMAT)
_DISPLAY_TIME_FORMAT = "%I:%M %p"
_STORAGE_TIME_FORMAT = "%H:%M"
_ACCEPTED_TIME_FORMATS = (
    _DISPLAY_TIME_FORMAT,
    "%I:%M%p",
    _STORAGE_TIME_FORMAT,
    "%H%M",
)


def parse_date(value: str | None) -> date | None:
    """Parse a supported date without rejecting legacy free-text values."""
    text = (value or "").strip()
    if not text:
        return None
    for date_format in _ACCEPTED_DATE_FORMATS:
        try:
            return datetime.strptime(text, date_format).date()
        except ValueError:
            continue
    return None


def format_date_for_display(value: str | None) -> str:
    """Return a valid date as MM/DD/YYYY and preserve non-date free text."""
    text = (value or "").strip()
    parsed = parse_date(text)
    return parsed.strftime(_DISPLAY_DATE_FORMAT) if parsed else text


def normalize_date_for_storage(value: str | None) -> str:
    """Return a valid date as sortable YYYY-MM-DD and preserve other text."""
    text = (value or "").strip()
    parsed = parse_date(text)
    return parsed.strftime(_STORAGE_DATE_FORMAT) if parsed else text


def weekday_name(value: str | None) -> str:
    parsed = parse_date(value)
    return parsed.strftime("%A") if parsed else ""


def parse_time(value: str | None) -> time | None:
    """Parse common 12-hour and 24-hour crash times."""
    text = (value or "").strip().upper()
    if not text:
        return None
    for time_format in _ACCEPTED_TIME_FORMATS:
        try:
            return datetime.strptime(text, time_format).time()
        except ValueError:
            continue
    return None


def format_time_for_display(value: str | None) -> str:
    """Return a valid time with AM/PM and preserve non-time free text."""
    text = (value or "").strip()
    parsed = parse_time(text)
    return parsed.strftime(_DISPLAY_TIME_FORMAT) if parsed else text


def normalize_time_for_storage(value: str | None) -> str:
    """Store valid times as 24-hour HH:MM while preserving legacy free text."""
    text = (value or "").strip()
    parsed = parse_time(text)
    return parsed.strftime(_STORAGE_TIME_FORMAT) if parsed else text

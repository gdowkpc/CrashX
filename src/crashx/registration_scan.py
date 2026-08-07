from __future__ import annotations

from collections import Counter
from dataclasses import dataclass, replace
from datetime import date
import json
import re
from statistics import median
from urllib.parse import parse_qsl, urlsplit

import zxingcpp
from PySide6.QtCore import QRect, Qt
from PySide6.QtGui import QImage, QTransform

from .windows_ocr import OcrDocument, OcrUnavailableError, OcrWord, recognize_image


AUTO_STATE = "AUTO"
CAMERA_GUIDE_LEFT = 0.04
CAMERA_GUIDE_TOP = 0.12
CAMERA_GUIDE_WIDTH = 0.92
CAMERA_GUIDE_HEIGHT = 0.76
CAMERA_OCR_TARGET_LONG_EDGE = 2400
OREGON_BODY_STYLE_CODES = {
    "PK": "Pickup",
}
SUPPORTED_REGISTRATION_STATES = (
    (AUTO_STATE, "Auto-detect"),
    ("OR", "Oregon"),
    ("WA", "Washington"),
)


class RegistrationScanError(RuntimeError):
    """Raised when a registration image cannot produce reviewable vehicle data."""


def registration_guide_rect(width: int, height: int) -> QRect:
    """Return the image-relative region represented by the camera guide."""

    return QRect(
        round(width * CAMERA_GUIDE_LEFT),
        round(height * CAMERA_GUIDE_TOP),
        round(width * CAMERA_GUIDE_WIDTH),
        round(height * CAMERA_GUIDE_HEIGHT),
    )


def prepare_camera_registration_image(image: QImage) -> QImage:
    """Crop away camera background and enlarge the guided document region for OCR."""

    if image.isNull():
        return image
    cropped = image.copy(registration_guide_rect(image.width(), image.height()))
    longest_edge = max(cropped.width(), cropped.height())
    if 0 < longest_edge != CAMERA_OCR_TARGET_LONG_EDGE:
        scale = CAMERA_OCR_TARGET_LONG_EDGE / longest_edge
        cropped = cropped.scaled(
            round(cropped.width() * scale),
            round(cropped.height() * scale),
            Qt.AspectRatioMode.KeepAspectRatio,
            Qt.TransformationMode.SmoothTransformation,
        )
    return cropped


@dataclass(frozen=True, slots=True)
class ScannedVehicleData:
    jurisdiction: str = ""
    year: str = ""
    make: str = ""
    model: str = ""
    body_style: str = ""
    color: str = ""
    plate: str = ""
    plate_state: str = ""
    source: str = "ocr"
    warnings: tuple[str, ...] = ()

    @property
    def populated_fields(self) -> tuple[str, ...]:
        values = (
            ("plate", self.plate),
            ("plate state", self.plate_state),
            ("year", self.year),
            ("make", self.make),
            ("model", self.model),
            ("body style", self.body_style),
            ("color", self.color),
        )
        return tuple(label for label, value in values if value)


_BARCODE_ALIASES = {
    "plate": "plate",
    "platenumber": "plate",
    "licenseplate": "plate",
    "licenseplatenumber": "plate",
    "tag": "plate",
    "tagnumber": "plate",
    "state": "plate_state",
    "jurisdiction": "plate_state",
    "platestate": "plate_state",
    "platejurisdiction": "plate_state",
    "year": "year",
    "modelyear": "year",
    "vehicleyear": "year",
    "make": "make",
    "vehiclemake": "make",
    "model": "model",
    "vehiclemodel": "model",
    "style": "body_style",
    "bodystyle": "body_style",
    "bodytype": "body_style",
    "vehicletype": "body_style",
    "color": "color",
    "vehiclecolor": "color",
}


def _normalized_key(value: str) -> str:
    return re.sub(r"[^a-z0-9]", "", value.casefold())


def _clean_value(value: str, *, maximum: int = 40) -> str:
    return re.sub(r"\s+", " ", value).strip(" \t\r\n:;|,")[:maximum]


def _flatten_json(value, fields: dict[str, str], *, depth: int = 0) -> None:
    if depth > 4:
        return
    if isinstance(value, dict):
        for key, child in value.items():
            normalized = _normalized_key(str(key))
            target = _BARCODE_ALIASES.get(normalized)
            if target and isinstance(child, (str, int, float)):
                fields[target] = _clean_value(str(child))
            _flatten_json(child, fields, depth=depth + 1)
    elif isinstance(value, list):
        for child in value[:30]:
            _flatten_json(child, fields, depth=depth + 1)


def _parse_structured_barcode(payload: bytes) -> ScannedVehicleData | None:
    if not payload or len(payload) > 8192:
        return None
    try:
        text = payload.decode("utf-8")
    except UnicodeDecodeError:
        return None
    fields: dict[str, str] = {}
    stripped = text.strip()
    try:
        parsed_json = json.loads(stripped)
    except (json.JSONDecodeError, ValueError):
        parsed_json = None
    if parsed_json is not None:
        _flatten_json(parsed_json, fields)

    parsed_url = urlsplit(stripped)
    if parsed_url.scheme.casefold() in {"http", "https"} and parsed_url.netloc:
        for key, value in parse_qsl(parsed_url.query, keep_blank_values=False):
            target = _BARCODE_ALIASES.get(_normalized_key(key))
            if target:
                fields[target] = _clean_value(value)

    for match in re.finditer(
        r"(?:^|[\r\n\x1d|;,&])\s*([A-Za-z][A-Za-z0-9 _./-]{1,40})\s*[:=]\s*"
        r"([^\r\n\x1d|;,&]{1,80})",
        stripped,
    ):
        target = _BARCODE_ALIASES.get(_normalized_key(match.group(1)))
        if target:
            fields[target] = _clean_value(match.group(2))

    if not any(fields.get(name) for name in ("plate", "year", "make", "model")):
        return None
    plate_state = fields.get("plate_state", "").upper()
    return ScannedVehicleData(
        jurisdiction=plate_state,
        year=fields.get("year", ""),
        make=fields.get("make", "").upper(),
        model=fields.get("model", "").upper(),
        body_style=fields.get("body_style", "").upper(),
        color=fields.get("color", "").upper(),
        plate=fields.get("plate", "").upper(),
        plate_state=plate_state,
        source="barcode",
    )


def _read_registration_barcodes(image: QImage) -> list:
    grayscale = image.convertToFormat(QImage.Format.Format_Grayscale8)
    image_view = zxingcpp.ImageView(
        grayscale.constBits(),
        grayscale.width(),
        grayscale.height(),
        zxingcpp.ImageFormat.Lum,
        grayscale.bytesPerLine(),
        1,
    )
    return zxingcpp.read_barcodes(
        image_view,
        formats=(
            zxingcpp.BarcodeFormat.QRCode,
            zxingcpp.BarcodeFormat.DataMatrix,
            zxingcpp.BarcodeFormat.PDF417,
        ),
        try_rotate=True,
        try_downscale=True,
        try_invert=True,
        text_mode=zxingcpp.TextMode.Plain,
        binarizer=zxingcpp.Binarizer.LocalAverage,
    )


def decode_registration_barcode(image: QImage) -> ScannedVehicleData | None:
    """Return only mapped vehicle fields; raw barcode values never leave this function."""

    if image.isNull():
        return None
    for candidate in (image, image.flipped(Qt.Orientation.Horizontal)):
        for barcode in _read_registration_barcodes(candidate):
            if not barcode.valid:
                continue
            mapped = _parse_structured_barcode(bytes(barcode.bytes))
            if mapped is not None:
                return mapped
    return None


def _tokens(document: OcrDocument) -> set[str]:
    return {
        token
        for line in document.lines
        for token in re.findall(r"[A-Z]+", line.upper())
    }


def _orientation_score(document: OcrDocument, state_hint: str) -> tuple[int, int]:
    tokens = _tokens(document)
    registration_terms = {
        "REGISTRATION",
        "PLATE",
        "YEAR",
        "MAKE",
        "MODEL",
        "STYLE",
        "VEHICLE",
        "IDENTIFICATION",
    }
    score = len(tokens & registration_terms) * 8
    if "OREGON" in tokens:
        score += 40
    if "WASHINGTON" in tokens:
        score += 40
    if state_hint == "OR" and "OREGON" in tokens:
        score += 20
    if state_hint == "WA" and "WASHINGTON" in tokens:
        score += 20
    return score, min(len(document.words), 200)


def _recognize_best_orientation(
    image: QImage,
    state_hint: str,
) -> tuple[QImage, OcrDocument]:
    candidates: list[tuple[tuple[int, int], int, QImage, OcrDocument]] = []
    for preference, rotation in enumerate((0, 90, 270, 180)):
        candidate = image.transformed(QTransform().rotate(rotation))
        document = recognize_image(candidate)
        candidates.append(
            (_orientation_score(document, state_hint), -preference, candidate, document)
        )
    _score, _preference, oriented, document = max(
        candidates,
        key=lambda item: (item[0], item[1]),
    )
    return oriented, document


def detect_registration_state(document: OcrDocument) -> str:
    tokens = _tokens(document)
    scores = {
        "OR": 20 if "OREGON" in tokens else 0,
        "WA": 20 if "WASHINGTON" in tokens else 0,
    }
    if "LICENSING" in tokens:
        scores["WA"] += 4
    if "DMV" in tokens:
        scores["OR"] += 2
    state, score = max(scores.items(), key=lambda item: item[1])
    return state if score >= 10 else ""


def _normalized_word(word: OcrWord) -> str:
    return re.sub(r"[^A-Z0-9]", "", word.text.upper())


def _anchor(document: OcrDocument, *labels: str) -> OcrWord | None:
    expected = {_normalized_key(label).upper() for label in labels}
    return next(
        (word for word in document.words if _normalized_word(word) in expected),
        None,
    )


def _words_in_column(
    document: OcrDocument,
    *,
    left: float,
    right: float,
    top: float,
    bottom: float,
) -> list[OcrWord]:
    selected = []
    for word in document.words:
        center_x = word.x + word.width / 2
        center_y = word.y + word.height / 2
        if left <= center_x <= right and top <= center_y <= bottom:
            selected.append(word)
    return sorted(selected, key=lambda word: word.x)


def _joined_value(words: list[OcrWord], *, maximum: int = 30) -> str:
    value = " ".join(word.text for word in words)
    return _clean_value(value, maximum=maximum).upper()


def _valid_year(value: str) -> str:
    match = re.fullmatch(r"\d{4}", value)
    if not match:
        return ""
    number = int(value)
    return value if 1900 <= number <= date.today().year + 2 else ""


def _valid_plate(value: str) -> str:
    compact = re.sub(r"[^A-Z0-9-]", "", value.upper())
    return compact if 2 <= len(compact) <= 12 else ""


def _without_field_labels(value: str, *labels: str) -> str:
    normalized = re.sub(r"[^A-Z0-9]", "", value.upper())
    forbidden = {
        re.sub(r"[^A-Z0-9]", "", label.upper())
        for label in labels
    }
    return "" if normalized in forbidden else value


def _normalize_oregon_body_style(value: str) -> str:
    compact = re.sub(r"[^A-Z0-9]", "", value.upper())
    return OREGON_BODY_STYLE_CODES.get(compact, value)


def _infer_oregon_body_style(make: str, model: str) -> str:
    """Use only narrowly calibrated make/model fallbacks when the tiny code is unreadable."""

    normalized_make = re.sub(r"[^A-Z0-9]", "", make.upper())
    normalized_model = re.sub(r"[^A-Z0-9]", "", model.upper())
    if normalized_make == "FORD" and normalized_model in {
        "F15",
        "F150",
        "F25",
        "F250",
        "F35",
        "F350",
    }:
        return "Pickup"
    return ""


def _oregon_field_layout(
    document: OcrDocument,
) -> tuple[dict[str, float], float, bool]:
    anchors = {
        "year": _anchor(document, "YEAR"),
        "style": _anchor(document, "STYLE", "BODY STYLE"),
        "model": _anchor(document, "MODEL"),
        "fuel": _anchor(document, "FUEL"),
    }
    canonical_centers = {
        "year": 0.092,
        "style": 0.278,
        "model": 0.370,
        "fuel": 0.454,
    }
    observed = [
        (
            canonical_centers[name],
            anchor.x + anchor.width / 2,
        )
        for name, anchor in anchors.items()
        if anchor is not None
    ]
    if len(observed) < 2:
        raise RegistrationScanError(
            "The Oregon registration heading was found, but the vehicle field row was not clear enough."
        )
    canonical_mean = sum(point[0] for point in observed) / len(observed)
    observed_mean = sum(point[1] for point in observed) / len(observed)
    denominator = sum((point[0] - canonical_mean) ** 2 for point in observed)
    if denominator <= 0:
        raise RegistrationScanError(
            "The Oregon registration heading was found, but the vehicle field row was not clear enough."
        )
    scale = sum(
        (canonical - canonical_mean) * (actual - observed_mean)
        for canonical, actual in observed
    ) / denominator
    offset = observed_mean - scale * canonical_mean
    centers = {
        name: (
            anchor.x + anchor.width / 2
            if anchor is not None
            else offset + scale * canonical_centers[name]
        )
        for name, anchor in anchors.items()
    }
    centers["make"] = (centers["year"] + centers["style"]) / 2
    header_y = median(anchor.y for anchor in anchors.values() if anchor is not None)
    return centers, header_y, any(anchor is None for anchor in anchors.values())


def _parse_oregon(document: OcrDocument) -> ScannedVehicleData:
    centers, header_y, inferred_layout = _oregon_field_layout(document)
    ordered = [
        ("year", centers["year"]),
        ("make", centers["make"]),
        ("style", centers["style"]),
        ("model", centers["model"]),
        ("fuel", centers["fuel"]),
    ]
    edges: dict[str, tuple[float, float]] = {}
    for index, (name, center) in enumerate(ordered):
        if index == 0:
            left = max(0.0, center - (ordered[1][1] - center) / 2)
        else:
            left = (ordered[index - 1][1] + center) / 2
        if index == len(ordered) - 1:
            right = min(float(document.width), center + (center - ordered[index - 1][1]) / 2)
        else:
            right = (center + ordered[index + 1][1]) / 2
        edges[name] = (left, right)

    year_left, year_right = edges["year"]
    nearby_year_words = _words_in_column(
        document,
        left=year_left,
        right=year_right,
        top=header_y + document.height * 0.012,
        bottom=header_y + document.height * 0.10,
    )
    year_word = next(
        (
            word
            for word in nearby_year_words
            if _valid_year(re.sub(r"\D", "", word.text))
        ),
        None,
    )
    if year_word is not None:
        value_center = year_word.y + year_word.height / 2
        value_top = value_center - document.height * 0.018
        value_bottom = value_center + document.height * 0.018
    else:
        value_top = header_y + document.height * 0.016
        value_bottom = header_y + document.height * 0.060

    values = {
        name: _joined_value(
            _words_in_column(
                document,
                left=left,
                right=right,
                top=value_top,
                bottom=value_bottom,
            )
        )
        for name, (left, right) in edges.items()
    }
    plate_left, plate_right = edges["year"]
    plate_candidates = _words_in_column(
        document,
        left=plate_left,
        right=plate_right,
        top=header_y - document.height * 0.045,
        bottom=header_y - document.height * 0.004,
    )
    plate_candidates = [
        word
        for word in plate_candidates
        if not any(
            label in _normalized_word(word)
            for label in ("PLATE", "NUMBER")
        )
    ]
    plate = _valid_plate(_joined_value(plate_candidates, maximum=12))
    year = _valid_year(re.sub(r"\D", "", values["year"]))
    data = ScannedVehicleData(
        jurisdiction="OR",
        year=year,
        make=_without_field_labels(values["make"], "MAKE"),
        model=_without_field_labels(values["model"], "MODEL"),
        body_style=_normalize_oregon_body_style(
            _without_field_labels(
                values["style"],
                "STYLE",
                "BODY STYLE",
            )
        ),
        plate=plate,
        plate_state="OR",
        source="ocr",
    )
    if not any((data.plate, data.year, data.make, data.model, data.body_style)):
        raise RegistrationScanError(
            "The Oregon registration was recognized, but its vehicle values were not clear enough."
        )
    warnings = []
    if inferred_layout:
        warnings.append(
            "Some printed field labels were faint; verify every populated field."
        )
    if not data.body_style:
        warnings.append("Body style was not clear and was left blank.")
    if len(data.populated_fields) < 5:
        warnings.append("Some registration fields were not clear and were left unchanged.")
    return replace(data, warnings=tuple(warnings))


def _oregon_detail_scans(
    image: QImage,
    document: OcrDocument,
) -> tuple[ScannedVehicleData, ...]:
    """Retry the compact Oregon vehicle row at a larger effective text size."""

    try:
        centers, header_y, _inferred = _oregon_field_layout(document)
    except RegistrationScanError:
        return ()
    left = max(0, round(centers["year"] - document.width * 0.05))
    right = min(
        document.width,
        round(centers["fuel"] + document.width * 0.09),
    )
    top = max(0, round(header_y - document.height * 0.07))
    bottom = min(document.height, round(header_y + document.height * 0.11))
    if right <= left or bottom <= top:
        return ()
    detail_image = image.copy(QRect(left, top, right - left, bottom - top))
    scans = []
    for target_width in (1800, 2200, CAMERA_OCR_TARGET_LONG_EDGE):
        candidate = detail_image.scaledToWidth(
            target_width,
            Qt.TransformationMode.SmoothTransformation,
        )
        try:
            scans.append(_parse_oregon(recognize_image(candidate)))
        except RegistrationScanError:
            continue
    return tuple(scans)


def _merge_oregon_detail_consensus(
    primary: ScannedVehicleData,
    candidates: tuple[ScannedVehicleData, ...],
) -> ScannedVehicleData:
    """Accept a low-resolution detail value only when repeated OCR passes agree."""

    updates: dict[str, str] = {}
    uncertain = False
    for name in ("year", "make", "model", "body_style", "plate"):
        if getattr(primary, name):
            continue
        counts = Counter(
            value
            for candidate in candidates
            if (value := getattr(candidate, name))
        )
        if not counts:
            continue
        value, count = counts.most_common(1)[0]
        if count >= 2:
            updates[name] = value
        else:
            uncertain = True
    merged = replace(primary, **updates)
    warnings = [
        warning
        for warning in merged.warnings
        if not (
            warning.startswith("Body style")
            and merged.body_style
        )
    ]
    if uncertain:
        warnings.append(
            "Low-resolution OCR readings disagreed; uncertain fields were left unchanged."
        )
    if not merged.body_style:
        inferred_style = _infer_oregon_body_style(merged.make, merged.model)
        if inferred_style:
            merged = replace(merged, body_style=inferred_style)
            warnings = [
                warning
                for warning in warnings
                if not warning.startswith("Body style")
            ]
            warnings.append(
                "Body style was inferred from the recognized make and model; verify it."
            )
    return replace(merged, warnings=tuple(dict.fromkeys(warnings)))


def _value_below_label(document: OcrDocument, *labels: str) -> str:
    anchor = _anchor(document, *labels)
    if anchor is None:
        return ""
    center = anchor.x + anchor.width / 2
    width = max(anchor.width * 2.2, document.width * 0.08)
    words = _words_in_column(
        document,
        left=max(0.0, center - width / 2),
        right=min(float(document.width), center + width / 2),
        top=anchor.y + anchor.height,
        bottom=anchor.y + anchor.height + document.height * 0.07,
    )
    return _joined_value(words)


def _parse_washington(document: OcrDocument) -> ScannedVehicleData:
    data = ScannedVehicleData(
        jurisdiction="WA",
        year=_valid_year(re.sub(r"\D", "", _value_below_label(document, "YEAR"))),
        make=_value_below_label(document, "MAKE"),
        model=_value_below_label(document, "MODEL"),
        body_style=_value_below_label(document, "STYLE", "BODY"),
        color=_value_below_label(document, "COLOR"),
        plate=_valid_plate(_value_below_label(document, "PLATE")),
        plate_state="WA",
        source="ocr",
        warnings=(
            "Washington parsing is preliminary until a registration sample is calibrated.",
        ),
    )
    if not any((data.plate, data.year, data.make, data.model, data.body_style)):
        raise RegistrationScanError(
            "Washington was recognized, but the vehicle fields were not clear enough."
        )
    return data


def _merge_vehicle_data(
    primary: ScannedVehicleData,
    secondary: ScannedVehicleData | None,
) -> ScannedVehicleData:
    if secondary is None:
        return primary
    return ScannedVehicleData(
        jurisdiction=primary.jurisdiction or secondary.jurisdiction,
        year=primary.year or secondary.year,
        make=primary.make or secondary.make,
        model=primary.model or secondary.model,
        body_style=primary.body_style or secondary.body_style,
        color=primary.color or secondary.color,
        plate=primary.plate or secondary.plate,
        plate_state=primary.plate_state or secondary.plate_state,
        source=(
            "barcode and OCR"
            if primary.source != secondary.source
            else primary.source
        ),
        warnings=tuple(dict.fromkeys(primary.warnings + secondary.warnings)),
    )


def scan_registration_image(
    image: QImage,
    requested_state: str = AUTO_STATE,
) -> ScannedVehicleData:
    """Read supported vehicle fields locally and discard all unrelated OCR text."""

    if image.isNull():
        raise RegistrationScanError("The captured registration image was empty.")
    requested = requested_state.strip().upper() or AUTO_STATE
    if requested not in {code for code, _label in SUPPORTED_REGISTRATION_STATES}:
        raise RegistrationScanError("The selected registration state is not supported.")

    barcode_data = decode_registration_barcode(image)
    try:
        _oriented, document = _recognize_best_orientation(image, requested)
    except OcrUnavailableError:
        if barcode_data is not None:
            return barcode_data
        raise

    detected = detect_registration_state(document)
    jurisdiction = requested if requested != AUTO_STATE else detected
    if not jurisdiction and barcode_data is not None:
        jurisdiction = barcode_data.jurisdiction
    if not jurisdiction:
        raise RegistrationScanError(
            "CrashX could not identify the registration state. Select Oregon or Washington and retry."
        )

    if jurisdiction == "OR":
        ocr_data = _parse_oregon(document)
        detail_scans = _oregon_detail_scans(_oriented, document)
        ocr_data = _merge_oregon_detail_consensus(ocr_data, detail_scans)
    elif jurisdiction == "WA":
        ocr_data = _parse_washington(document)
    else:
        raise RegistrationScanError("That registration state is not supported yet.")

    if barcode_data is not None:
        if not barcode_data.jurisdiction:
            barcode_data = replace(
                barcode_data,
                jurisdiction=jurisdiction,
                plate_state=barcode_data.plate_state or jurisdiction,
            )
        return _merge_vehicle_data(barcode_data, ocr_data)
    return ocr_data

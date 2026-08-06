from __future__ import annotations

import re
import sys
from dataclasses import replace
from pathlib import Path

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QApplication,
    QAbstractItemView,
    QCheckBox,
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QFileDialog,
    QFormLayout,
    QGridLayout,
    QGroupBox,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QMainWindow,
    QMessageBox,
    QPushButton,
    QScrollArea,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from ..date_format import normalize_date_for_storage, normalize_time_for_storage
from ..exchange_draft import (
    EXCHANGE_ROLES,
    ExchangeReportDraft,
    save_exchange_report_pdf,
)
from ..license_scan import ScannedLicenseData
from ..models import DriverProfile, ParticipantDetails, Person, Vehicle
from .license_scan_dialog import LicenseScanDialog


def _line(placeholder: str = "") -> QLineEdit:
    editor = QLineEdit()
    editor.setPlaceholderText(placeholder)
    editor.setClearButtonEnabled(True)
    return editor


def _uppercase_line(placeholder: str = "") -> QLineEdit:
    editor = _line(placeholder)
    editor.setInputMethodHints(
        editor.inputMethodHints() | Qt.InputMethodHint.ImhUppercaseOnly
    )

    def normalize_text(value: str) -> None:
        uppercase_value = value.upper()
        if uppercase_value == value:
            return
        cursor_position = editor.cursorPosition()
        editor.setText(uppercase_value)
        editor.setCursorPosition(cursor_position)

    editor.textEdited.connect(normalize_text)
    return editor


def vehicle_display_name(vehicle: Vehicle) -> str:
    description = " ".join(
        value for value in (vehicle.year, vehicle.make, vehicle.model) if value
    )
    if vehicle.vehicle_number and description:
        return f"{vehicle.vehicle_number} - {description}"
    return vehicle.vehicle_number or description or vehicle.plate or "Unnamed vehicle"


class VehicleEditorDialog(QDialog):
    def __init__(self, vehicle: Vehicle | None = None, parent=None) -> None:
        super().__init__(parent)
        self.original = vehicle or Vehicle(id="", case_id="")
        self.setWindowTitle("Edit vehicle" if vehicle else "Add vehicle")
        self.setMinimumWidth(560)

        self.number = _line("Example: V-1")
        self.year = _line("YYYY")
        self.make = _line()
        self.model = _line()
        self.body_style = _line("Sedan, pickup, SUV, motorcycle...")
        self.color = _line()
        self.plate = _uppercase_line()
        self.plate_state = _uppercase_line("OR")
        self.insurance_company = _uppercase_line()
        self.policy_number = _uppercase_line()
        self.property_damage = _line("House, fence, sign, or other property")

        form = QFormLayout()
        form.setFieldGrowthPolicy(QFormLayout.FieldGrowthPolicy.AllNonFixedFieldsGrow)
        form.addRow("Vehicle number", self.number)
        form.addRow("Year", self.year)
        form.addRow("Make", self.make)
        form.addRow("Model", self.model)
        form.addRow("Body style", self.body_style)
        form.addRow("Color", self.color)
        form.addRow("Plate", self.plate)
        form.addRow("Plate state", self.plate_state)
        form.addRow("Insurance company", self.insurance_company)
        form.addRow("Policy number", self.policy_number)
        form.addRow("Other property damaged", self.property_damage)

        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Save
            | QDialogButtonBox.StandardButton.Cancel
        )
        buttons.accepted.connect(self._accept_if_valid)
        buttons.rejected.connect(self.reject)

        body = QWidget()
        body_layout = QVBoxLayout(body)
        body_layout.addLayout(form)
        body_layout.addWidget(buttons)
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setWidget(body)
        layout = QVBoxLayout(self)
        layout.addWidget(scroll)

        self._load()

    def _load(self) -> None:
        values = (
            (self.number, self.original.vehicle_number),
            (self.year, self.original.year),
            (self.make, self.original.make),
            (self.model, self.original.model),
            (self.body_style, self.original.body_style),
            (self.color, self.original.color),
            (self.plate, self.original.plate.upper()),
            (self.plate_state, self.original.plate_state.upper()),
            (self.insurance_company, self.original.insurance_company.upper()),
            (self.policy_number, self.original.insurance_policy_number.upper()),
            (self.property_damage, self.original.property_damage),
        )
        for editor, value in values:
            editor.setText(value)

    def _accept_if_valid(self) -> None:
        identifying_values = (
            self.number.text(),
            self.year.text(),
            self.make.text(),
            self.model.text(),
            self.plate.text(),
        )
        if not any(value.strip() for value in identifying_values):
            QMessageBox.warning(
                self,
                "Vehicle needs an identifier",
                "Enter a vehicle number, year, make, model, or plate.",
            )
            return
        self.accept()

    def record(self) -> Vehicle:
        return replace(
            self.original,
            vehicle_number=self.number.text().strip(),
            year=self.year.text().strip(),
            make=self.make.text().strip(),
            model=self.model.text().strip(),
            body_style=self.body_style.text().strip(),
            color=self.color.text().strip(),
            plate=self.plate.text().strip().upper(),
            plate_state=self.plate_state.text().strip().upper(),
            insurance=self.insurance_company.text().strip().upper(),
            insurance_company=self.insurance_company.text().strip().upper(),
            insurance_policy_number=self.policy_number.text().strip().upper(),
            property_damage=self.property_damage.text().strip(),
        )


class PersonEditorDialog(QDialog):
    def __init__(
        self,
        vehicles: list[Vehicle],
        person: Person | None = None,
        profile: DriverProfile | None = None,
        participant: ParticipantDetails | None = None,
        parent=None,
    ) -> None:
        super().__init__(parent)
        self.original = person or Person(id="", case_id="")
        self.original_profile = profile or DriverProfile(person_id=self.original.id)
        self.original_participant = participant or ParticipantDetails(
            person_id=self.original.id
        )
        self.setWindowTitle("Edit person" if person else "Add person")
        self.setMinimumWidth(620)

        self.first_name = _line()
        self.middle_name = _line()
        self.last_name = _line()
        self.role_boxes = {role: QCheckBox(role) for role in EXCHANGE_ROLES}
        role_widget = QWidget()
        role_layout = QHBoxLayout(role_widget)
        role_layout.setContentsMargins(0, 0, 0, 0)
        for checkbox in self.role_boxes.values():
            role_layout.addWidget(checkbox)
        role_layout.addStretch(1)

        self.vehicle = QComboBox()
        self.vehicle.addItem("Not associated with a vehicle", None)
        for record in vehicles:
            self.vehicle.addItem(vehicle_display_name(record), record.id)

        self.address = _line()
        self.city = _line()
        self.state = _line("OR")
        self.zip_code = _line()
        self.home_phone = _line()
        self.work_phone = _line()
        self.cell_phone = _line()
        self.license_number = _line()
        self.license_state = _line("OR")

        self.scan_license_button = QPushButton("Scan license")
        self.scan_license_button.setStyleSheet(
            "font-weight: 700; padding: 7px 16px; background: #176b87; color: white;"
        )
        self.scan_license_button.setToolTip(
            "Use the computer camera to read the PDF417 barcode on a driver license."
        )
        self.scan_license_button.clicked.connect(self.scan_license)
        scan_help = QLabel(
            "Use the camera to fill the identity, address, and driver-license fields."
        )
        scan_help.setWordWrap(True)
        scan_row = QHBoxLayout()
        scan_row.addWidget(self.scan_license_button)
        scan_row.addWidget(scan_help, 1)

        self.scan_status = QLabel()
        self.scan_status.setWordWrap(True)
        self.scan_status.setStyleSheet(
            "background: #eaf6ef; border: 1px solid #9ac7aa; border-radius: 4px; "
            "padding: 7px; color: #174f2a;"
        )
        self.scan_status.hide()

        form = QFormLayout()
        form.setFieldGrowthPolicy(QFormLayout.FieldGrowthPolicy.AllNonFixedFieldsGrow)
        form.addRow("First name", self.first_name)
        form.addRow("Middle name", self.middle_name)
        form.addRow("Last name", self.last_name)
        form.addRow("Role(s)", role_widget)
        form.addRow("Associated vehicle", self.vehicle)
        form.addRow("Street address", self.address)
        form.addRow("City", self.city)
        form.addRow("State", self.state)
        form.addRow("ZIP", self.zip_code)
        form.addRow("Home phone", self.home_phone)
        form.addRow("Business phone", self.work_phone)
        form.addRow("Cell phone", self.cell_phone)
        form.addRow("Driver license number", self.license_number)
        form.addRow("Driver license state", self.license_state)

        note = QLabel(
            "A vehicle association is optional. For a driver, it identifies which "
            "vehicle block carries that driver's contact and license information."
        )
        note.setWordWrap(True)
        note.setStyleSheet("color: #4b5563;")

        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Save
            | QDialogButtonBox.StandardButton.Cancel
        )
        buttons.accepted.connect(self._accept_if_valid)
        buttons.rejected.connect(self.reject)

        body = QWidget()
        body_layout = QVBoxLayout(body)
        body_layout.addLayout(scan_row)
        body_layout.addWidget(self.scan_status)
        body_layout.addWidget(note)
        body_layout.addLayout(form)
        body_layout.addWidget(buttons)
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setWidget(body)
        layout = QVBoxLayout(self)
        layout.addWidget(scroll)

        self._load()

    def _load(self) -> None:
        self.first_name.setText(self.original.first_name)
        self.middle_name.setText(self.original.middle_name)
        self.last_name.setText(self.original.last_name)
        existing_roles = {role.casefold() for role in self.original.roles}
        for role, checkbox in self.role_boxes.items():
            checkbox.setChecked(role.casefold() in existing_roles)
        vehicle_index = self.vehicle.findData(self.original_participant.vehicle_id)
        self.vehicle.setCurrentIndex(max(0, vehicle_index))
        self.address.setText(self.original.address)
        self.city.setText(self.original.city)
        self.state.setText(self.original.state)
        self.zip_code.setText(self.original.zip_code)
        self.home_phone.setText(self.original.home_phone)
        self.work_phone.setText(self.original.work_phone)
        self.cell_phone.setText(self.original.cell_phone)
        self.license_number.setText(self.original_profile.license_number)
        self.license_state.setText(self.original_profile.license_state)

    def scan_license(self) -> None:
        dialog = LicenseScanDialog(self)
        result = dialog.exec()
        scanned = dialog.scanned_data
        dialog.scanned_data = None
        dialog.deleteLater()
        if result != QDialog.DialogCode.Accepted or scanned is None:
            return
        self.apply_scanned_license(scanned)

    def apply_scanned_license(self, scanned: ScannedLicenseData) -> None:
        values = (
            (self.first_name, scanned.first_name),
            (self.middle_name, scanned.middle_name),
            (self.last_name, scanned.last_name),
            (self.address, scanned.address),
            (self.city, scanned.city),
            (self.state, scanned.state),
            (self.zip_code, scanned.zip_code),
            (self.license_number, scanned.license_number),
            (self.license_state, scanned.license_state),
        )
        for editor, value in values:
            if value:
                editor.setText(value)
        self.scan_status.setText(
            "License data filled from the barcode. Review every field, then select "
            "the person's role and associated vehicle before saving."
        )
        self.scan_status.show()

    def _accept_if_valid(self) -> None:
        if not any(
            editor.text().strip()
            for editor in (self.first_name, self.middle_name, self.last_name)
        ):
            QMessageBox.warning(
                self,
                "Person needs a name",
                "Enter at least one part of the person's name.",
            )
            return
        if not any(checkbox.isChecked() for checkbox in self.role_boxes.values()):
            QMessageBox.warning(
                self,
                "Select a role",
                "Select at least one role for this person.",
            )
            return
        self.accept()

    def records(self) -> tuple[Person, DriverProfile, ParticipantDetails]:
        preserved_roles = [
            role for role in self.original.roles if role not in EXCHANGE_ROLES
        ]
        roles = preserved_roles + [
            role for role, checkbox in self.role_boxes.items() if checkbox.isChecked()
        ]
        person = replace(
            self.original,
            first_name=self.first_name.text().strip(),
            middle_name=self.middle_name.text().strip(),
            last_name=self.last_name.text().strip(),
            address=self.address.text().strip(),
            city=self.city.text().strip(),
            state=self.state.text().strip().upper(),
            zip_code=self.zip_code.text().strip(),
            home_phone=self.home_phone.text().strip(),
            work_phone=self.work_phone.text().strip(),
            cell_phone=self.cell_phone.text().strip(),
            roles=roles,
        )
        profile = replace(
            self.original_profile,
            person_id=person.id,
            license_number=self.license_number.text().strip(),
            license_state=self.license_state.text().strip().upper(),
        )
        participant = replace(
            self.original_participant,
            person_id=person.id,
            vehicle_id=self.vehicle.currentData(),
        )
        return person, profile, participant


class ExchangeReportWindow(QMainWindow):
    def __init__(self, draft: ExchangeReportDraft | None = None) -> None:
        super().__init__()
        self.draft = draft or ExchangeReportDraft.empty()
        self.setWindowTitle("CrashX")
        self.resize(1050, 760)
        self.setMinimumSize(820, 580)

        self.case_number = _line("Agency case number")
        self.crash_date = _line("MM/DD/YYYY")
        self.crash_time = _line("HH:MM AM/PM")
        self.road_name = _line("Location of Crash")
        self.officer = _line("Assigned officer")
        self.dpsst = _line("DPSST")
        self.assignment = _line("Precinct or assignment")

        self.vehicle_table = self._table(
            ("Vehicle", "Description", "Plate", "Driver", "Insurance", "Policy")
        )
        self.person_table = self._table(
            ("Name", "Role(s)", "Vehicle", "Address", "Phone", "License")
        )
        self.vehicle_group = QGroupBox()
        self.people_group = QGroupBox()

        self._build_ui()
        self._load_overview()
        self.refresh_tables()

    @staticmethod
    def _table(headers: tuple[str, ...]) -> QTableWidget:
        table = QTableWidget(0, len(headers))
        table.setHorizontalHeaderLabels(headers)
        table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        table.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        table.setAlternatingRowColors(True)
        table.verticalHeader().setVisible(False)
        table.horizontalHeader().setSectionResizeMode(
            QHeaderView.ResizeMode.ResizeToContents
        )
        table.horizontalHeader().setStretchLastSection(True)
        return table

    @staticmethod
    def _button_row(*buttons: QPushButton) -> QHBoxLayout:
        layout = QHBoxLayout()
        for button in buttons:
            layout.addWidget(button)
        layout.addStretch(1)
        return layout

    def _build_ui(self) -> None:
        title = QLabel("CrashX")
        title.setStyleSheet("font-size: 24px; font-weight: 700; color: #17324d;")
        subtitle = QLabel(
            "Create a PDF information-exchange report without creating a case file. "
            "Entered data exists only while this window is open; only the PDF you "
            "choose to save is retained."
        )
        subtitle.setWordWrap(True)
        subtitle.setStyleSheet(
            "background: #eaf3f8; border: 1px solid #b7cfdd; border-radius: 5px; "
            "padding: 9px; color: #17324d;"
        )

        overview_group = QGroupBox("Crash and officer")
        overview = QGridLayout(overview_group)
        overview.addWidget(QLabel("Case number"), 0, 0)
        overview.addWidget(self.case_number, 0, 1)
        overview.addWidget(QLabel("Crash date"), 0, 2)
        overview.addWidget(self.crash_date, 0, 3)
        overview.addWidget(QLabel("Crash time"), 0, 4)
        overview.addWidget(self.crash_time, 0, 5)
        overview.addWidget(QLabel("Location of Crash"), 1, 0)
        overview.addWidget(self.road_name, 1, 1, 1, 6)
        overview.addWidget(QLabel("Assigned officer"), 2, 0)
        overview.addWidget(self.officer, 2, 1, 1, 2)
        overview.addWidget(QLabel("DPSST"), 2, 3)
        overview.addWidget(self.dpsst, 2, 4)
        overview.addWidget(QLabel("Precinct / assignment"), 2, 5)
        overview.addWidget(self.assignment, 2, 6)
        overview.setColumnStretch(1, 2)
        overview.setColumnStretch(2, 1)
        overview.setColumnStretch(4, 1)
        overview.setColumnStretch(6, 2)

        add_vehicle = QPushButton("Add vehicle")
        edit_vehicle = QPushButton("Edit selected")
        remove_vehicle = QPushButton("Remove selected")
        add_vehicle.clicked.connect(self.add_vehicle)
        edit_vehicle.clicked.connect(self.edit_vehicle)
        remove_vehicle.clicked.connect(self.remove_vehicle)
        self.vehicle_table.doubleClicked.connect(self.edit_vehicle)
        vehicle_layout = QVBoxLayout(self.vehicle_group)
        vehicle_layout.addWidget(self.vehicle_table)
        vehicle_layout.addLayout(
            self._button_row(add_vehicle, edit_vehicle, remove_vehicle)
        )

        add_person = QPushButton("Add person")
        edit_person = QPushButton("Edit selected")
        remove_person = QPushButton("Remove selected")
        add_person.clicked.connect(self.add_person)
        edit_person.clicked.connect(self.edit_person)
        remove_person.clicked.connect(self.remove_person)
        self.person_table.doubleClicked.connect(self.edit_person)
        people_layout = QVBoxLayout(self.people_group)
        people_layout.addWidget(self.person_table)
        people_layout.addLayout(self._button_row(add_person, edit_person, remove_person))

        clear_button = QPushButton("Clear all")
        clear_button.clicked.connect(self.clear_all)
        save_button = QPushButton("Save PDF...")
        save_button.setDefault(True)
        save_button.setStyleSheet(
            "QPushButton { background: #155e75; color: white; font-weight: 700; "
            "padding: 7px 18px; border-radius: 4px; }"
            "QPushButton:hover { background: #0e7490; }"
        )
        save_button.clicked.connect(self.choose_and_save_pdf)
        action_row = QHBoxLayout()
        action_row.addWidget(clear_button)
        action_row.addStretch(1)
        action_row.addWidget(save_button)

        content = QWidget()
        content_layout = QVBoxLayout(content)
        content_layout.setContentsMargins(14, 14, 14, 14)
        content_layout.setSpacing(12)
        content_layout.addWidget(title)
        content_layout.addWidget(subtitle)
        content_layout.addWidget(overview_group)
        content_layout.addWidget(self.vehicle_group)
        content_layout.addWidget(self.people_group)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setWidget(content)

        action_widget = QWidget()
        action_widget.setLayout(action_row)
        action_widget.setStyleSheet(
            "background: #f8fafc; border-top: 1px solid #cbd5e1;"
        )
        action_widget.layout().setContentsMargins(14, 8, 14, 8)
        central = QWidget()
        central_layout = QVBoxLayout(central)
        central_layout.setContentsMargins(0, 0, 0, 0)
        central_layout.setSpacing(0)
        central_layout.addWidget(scroll, 1)
        central_layout.addWidget(action_widget)
        self.setCentralWidget(central)
        self.statusBar().showMessage(
            "No case database is created. Close the application to discard entered data."
        )

    def _load_overview(self) -> None:
        self.case_number.setText(self.draft.case.case_number)
        self.crash_date.setText(self.draft.case.crash_date)
        self.crash_time.setText(self.draft.case.crash_time)
        self.road_name.setText(
            self.draft.crash_details.road_name or self.draft.case.location
        )
        self.officer.setText(self.draft.case.investigator)
        self.dpsst.setText(self.draft.case.assigned_officer_dpsst)
        self.assignment.setText(
            self.draft.case.assignment or self.draft.exchange_details.precinct
        )

    def sync_overview(self) -> None:
        self.draft.case.case_number = self.case_number.text().strip()
        self.draft.case.crash_date = normalize_date_for_storage(
            self.crash_date.text()
        )
        self.draft.case.crash_time = normalize_time_for_storage(
            self.crash_time.text()
        )
        self.draft.case.investigator = self.officer.text().strip()
        self.draft.case.assigned_officer_dpsst = self.dpsst.text().strip()
        self.draft.case.assignment = self.assignment.text().strip()
        location = self.road_name.text().strip()
        self.draft.case.location = location
        self.draft.crash_details.road_name = location
        self.draft.crash_details.intersection_road = ""
        self.draft.exchange_details.precinct = self.assignment.text().strip()

    @staticmethod
    def _item(text: str, record_id: str) -> QTableWidgetItem:
        item = QTableWidgetItem(text)
        item.setData(Qt.ItemDataRole.UserRole, record_id)
        return item

    def refresh_tables(self) -> None:
        people_by_id = {person.id: person for person in self.draft.people}
        self.vehicle_table.setRowCount(len(self.draft.vehicles))
        for row, vehicle in enumerate(self.draft.vehicles):
            driver = people_by_id.get(vehicle.driver_person_id)
            values = (
                vehicle.vehicle_number,
                " ".join(
                    value
                    for value in (
                        vehicle.year,
                        vehicle.make,
                        vehicle.model,
                        vehicle.body_style,
                        vehicle.color,
                    )
                    if value
                ),
                " ".join(value for value in (vehicle.plate, vehicle.plate_state) if value),
                driver.display_name if driver else "",
                vehicle.insurance_company or vehicle.insurance,
                vehicle.insurance_policy_number,
            )
            for column, value in enumerate(values):
                self.vehicle_table.setItem(row, column, self._item(value, vehicle.id))

        vehicles_by_id = {vehicle.id: vehicle for vehicle in self.draft.vehicles}
        self.person_table.setRowCount(len(self.draft.people))
        for row, person in enumerate(self.draft.people):
            participant = self.draft.participants.get(
                person.id, ParticipantDetails(person_id=person.id)
            )
            vehicle = vehicles_by_id.get(participant.vehicle_id)
            profile = self.draft.profiles.get(
                person.id, DriverProfile(person_id=person.id)
            )
            address = ", ".join(
                value
                for value in (
                    person.address,
                    " ".join(
                        value for value in (person.city, person.state, person.zip_code) if value
                    ),
                )
                if value
            )
            phone = person.cell_phone or person.home_phone or person.work_phone
            values = (
                person.display_name,
                ", ".join(person.roles),
                vehicle_display_name(vehicle) if vehicle else "",
                address,
                phone,
                " ".join(
                    value
                    for value in (profile.license_number, profile.license_state)
                    if value
                ),
            )
            for column, value in enumerate(values):
                self.person_table.setItem(row, column, self._item(value, person.id))

        self.vehicle_group.setTitle(f"Vehicles ({len(self.draft.vehicles)})")
        self.people_group.setTitle(f"People ({len(self.draft.people)})")

    @staticmethod
    def _selected_id(table: QTableWidget) -> str | None:
        rows = table.selectionModel().selectedRows()
        if not rows:
            return None
        item = table.item(rows[0].row(), 0)
        return item.data(Qt.ItemDataRole.UserRole) if item else None

    def add_vehicle(self, *_args) -> None:
        default_number = f"V-{len(self.draft.vehicles) + 1}"
        dialog = VehicleEditorDialog(parent=self)
        dialog.number.setText(default_number)
        if dialog.exec() != QDialog.DialogCode.Accepted:
            return
        self.draft.upsert_vehicle(dialog.record())
        self.refresh_tables()

    def edit_vehicle(self, *_args) -> None:
        vehicle = self.draft.vehicle(self._selected_id(self.vehicle_table))
        if vehicle is None:
            return
        dialog = VehicleEditorDialog(vehicle, self)
        if dialog.exec() != QDialog.DialogCode.Accepted:
            return
        self.draft.upsert_vehicle(dialog.record())
        self.refresh_tables()

    def remove_vehicle(self, *_args) -> None:
        vehicle = self.draft.vehicle(self._selected_id(self.vehicle_table))
        if vehicle is None:
            return
        associations = sum(
            participant.vehicle_id == vehicle.id
            for participant in self.draft.participants.values()
        )
        detail = (
            f" This will also clear {associations} person association(s)."
            if associations
            else ""
        )
        answer = QMessageBox.question(
            self,
            "Remove vehicle",
            f"Remove {vehicle_display_name(vehicle)}?{detail}",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        if answer != QMessageBox.StandardButton.Yes:
            return
        self.draft.remove_vehicle(vehicle.id)
        self.refresh_tables()

    def add_person(self, *_args) -> None:
        dialog = PersonEditorDialog(self.draft.vehicles, parent=self)
        while dialog.exec() == QDialog.DialogCode.Accepted:
            person, profile, participant = dialog.records()
            try:
                self.draft.upsert_person(person, profile, participant)
            except ValueError as error:
                QMessageBox.warning(self, "Vehicle association unavailable", str(error))
                continue
            self.refresh_tables()
            return

    def edit_person(self, *_args) -> None:
        person = self.draft.person(self._selected_id(self.person_table))
        if person is None:
            return
        dialog = PersonEditorDialog(
            self.draft.vehicles,
            person,
            self.draft.profiles.get(person.id),
            self.draft.participants.get(person.id),
            self,
        )
        while dialog.exec() == QDialog.DialogCode.Accepted:
            updated_person, profile, participant = dialog.records()
            try:
                self.draft.upsert_person(updated_person, profile, participant)
            except ValueError as error:
                QMessageBox.warning(self, "Vehicle association unavailable", str(error))
                continue
            self.refresh_tables()
            return

    def remove_person(self, *_args) -> None:
        person = self.draft.person(self._selected_id(self.person_table))
        if person is None:
            return
        answer = QMessageBox.question(
            self,
            "Remove person",
            f"Remove {person.display_name}?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        if answer != QMessageBox.StandardButton.Yes:
            return
        self.draft.remove_person(person.id)
        self.refresh_tables()

    def reset_draft(self) -> None:
        self.draft = ExchangeReportDraft.empty()
        self._load_overview()
        self.refresh_tables()

    def clear_all(self, *_args) -> None:
        answer = QMessageBox.question(
            self,
            "Clear entered data",
            "Clear all crash, vehicle, and person data from this window?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        if answer == QMessageBox.StandardButton.Yes:
            self.reset_draft()

    def suggested_filename(self) -> str:
        case_number = self.case_number.text().strip()
        safe_case = re.sub(r"[^A-Za-z0-9._-]+", "-", case_number).strip("-._")
        suffix = f"-{safe_case}" if safe_case else ""
        return f"Traffic-Crash-Exchange{suffix}.pdf"

    def save_to(self, destination: str | Path) -> Path:
        self.sync_overview()
        path = Path(destination)
        if path.suffix.casefold() != ".pdf":
            path = path.with_suffix(".pdf")
        return save_exchange_report_pdf(self.draft, path)

    def choose_and_save_pdf(self, *_args) -> None:
        destination, _selected_filter = QFileDialog.getSaveFileName(
            self,
            "Save CrashX PDF",
            self.suggested_filename(),
            "PDF files (*.pdf)",
        )
        if not destination:
            return
        try:
            path = self.save_to(destination)
        except (OSError, ValueError) as error:
            QMessageBox.critical(
                self,
                "PDF could not be saved",
                f"The exchange report was not saved.\n\n{error}",
            )
            return
        QMessageBox.information(
            self,
            "PDF saved",
            f"The exchange report was saved to:\n{path}\n\n"
            "Entered data will still be discarded when this application closes.",
        )
        self.statusBar().showMessage(f"PDF saved: {path}", 8000)


def run(draft: ExchangeReportDraft | None = None) -> int:
    application = QApplication.instance() or QApplication(sys.argv)
    window = ExchangeReportWindow(draft)
    window.show()
    return application.exec()

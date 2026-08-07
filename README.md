# CrashX

CrashX is a minimal Windows application for creating traffic-crash information
exchange reports in the field. It keeps the working data only in memory and
saves only the PDF selected by the officer.

## Capabilities

- Add any number of vehicles and people.
- Assign driver, passenger, witness, pedestrian, and bicyclist roles.
- Associate a person with a vehicle when applicable.
- Scan AAMVA PDF417 driver-license barcodes from the Add Person dialog.
- Map name, address, license number, and issuing state into reviewable fields.
- Scan Oregon vehicle registrations from the Add Vehicle dialog using local
  Windows OCR, automatic orientation correction, and state auto-detection.
- Try structured QR, Data Matrix, and PDF417 registration payloads before OCR;
  opaque identifiers are ignored rather than treated as vehicle data.
- Provide Oregon and Washington state selection as an override when automatic
  registration-state detection is uncertain.
- Exclude date of birth because it is not published on the exchange form.
- Automatically capitalize plate, plate-state, insurance-company, and
  policy-number entries.
- Create a searchable PDF with continuation pages as needed.
- Run without installation or administrator rights.

## Privacy model

CrashX does not create a case database. Camera frames, raw barcode payloads,
and raw registration OCR text are not written to disk. Registration scanning
returns only supported vehicle fields and ignores owner/address information.
Closing the application or selecting **Clear all** discards the entered data.
The PDF explicitly saved by the officer is the only retained work product.

Review every scanned field and the completed PDF before distributing it.

## Run from source

Python 3.11 or newer is required.

```powershell
py -3 -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements-dev.txt
$env:PYTHONPATH = "$PWD\src"
.\.venv\Scripts\python.exe .\run_crashx.py
```

## Build a single Windows executable

Use `BUILD_CRASHX_SINGLE_FILE.bat`, or run the PowerShell build script directly:

```powershell
powershell.exe -NoProfile -NonInteractive -ExecutionPolicy Bypass -File .\scripts\build_exchange_onefile_windows.ps1 --% -Clean
```

The release file is written to:

```text
release\CrashX-<version>-Windows-Single.exe
```

It is a single executable with no adjacent helper files and uses an `asInvoker`
manifest, so it does not request administrator elevation.

## Tests

```powershell
$env:PYTHONPATH = "$PWD\src"
.\.venv\Scripts\python.exe -m unittest discover -s tests -v
```

The build script runs the complete tests before packaging and then runs the
packaged executable's isolated self-test.

param(
    [switch]$Clean,
    [switch]$SkipTests
)

try {
$ErrorActionPreference = "Stop"
$ProjectRoot = Split-Path -Parent $PSScriptRoot
$DistDirectory = "$ProjectRoot\single-file-dist"
$WorkDirectory = "$ProjectRoot\build\traffic-crash-exchange-onefile"
$SpecDirectory = "$ProjectRoot\build\traffic-crash-exchange-onefile-spec"
$IsolatedDirectory = "$ProjectRoot\build\traffic-crash-exchange-onefile-isolated"
$SelfTestDirectory = "$ProjectRoot\build\traffic-crash-exchange-onefile-self-test"
Set-Location $ProjectRoot

function Assert-LastExitCode([string]$Operation) {
    if ($LASTEXITCODE -ne 0) {
        throw "$Operation failed with exit code $LASTEXITCODE."
    }
}

function Remove-ProjectDirectory([string]$Directory) {
    if (-not (Test-Path $Directory)) { return }
    $ResolvedRoot = [IO.Path]::GetFullPath($ProjectRoot).TrimEnd('\') + '\'
    $ResolvedTarget = [IO.Path]::GetFullPath($Directory).TrimEnd('\') + '\'
    if (-not $ResolvedTarget.StartsWith($ResolvedRoot, [StringComparison]::OrdinalIgnoreCase)) {
        throw "Refusing to remove a directory outside the project: $Directory"
    }
    Remove-Item -LiteralPath $Directory -Recurse -Force
}

function Copy-FileWithRetry([string]$SourcePath, [string]$DestinationPath) {
    $MaximumAttempts = 6
    for ($Attempt = 1; $Attempt -le $MaximumAttempts; $Attempt++) {
        try {
            Copy-Item -LiteralPath $SourcePath -Destination $DestinationPath -Force
            return
        } catch {
            if ($Attempt -eq $MaximumAttempts) {
                throw
            }
            Write-Warning (
                "Copy attempt $Attempt failed; retrying after a transient file lock. " +
                $_.Exception.Message
            )
            Start-Sleep -Seconds 2
        }
    }
}

if ($Clean) {
    Remove-ProjectDirectory $DistDirectory
    Remove-ProjectDirectory $WorkDirectory
    Remove-ProjectDirectory $SpecDirectory
    Remove-ProjectDirectory $IsolatedDirectory
    Remove-ProjectDirectory $SelfTestDirectory
}

if (-not (Test-Path "$ProjectRoot\.venv\Scripts\python.exe")) {
    if (Get-Command py -ErrorAction SilentlyContinue) {
        & py -3 -m venv "$ProjectRoot\.venv"
    } elseif (Get-Command python -ErrorAction SilentlyContinue) {
        & python -m venv "$ProjectRoot\.venv"
    } else {
        throw "Python 3 was not found. Build on Windows with Python 3.11 or newer."
    }
    Assert-LastExitCode "Virtual-environment creation"
}

$Python = "$ProjectRoot\.venv\Scripts\python.exe"
& $Python -m pip install -r "$ProjectRoot\requirements-dev.txt"
Assert-LastExitCode "Dependency installation"

$PreviousPythonPath = $env:PYTHONPATH
$env:PYTHONPATH = "$ProjectRoot\src"
try {
    if (-not $SkipTests) {
        & $Python -m unittest discover -s "$ProjectRoot\tests" -v
        Assert-LastExitCode "Automated tests"
    }

    $Version = (& $Python -c "from crashx import __version__; print(__version__)").Trim()
    Assert-LastExitCode "Version lookup"

    Remove-ProjectDirectory $DistDirectory
    Remove-ProjectDirectory $WorkDirectory
    Remove-ProjectDirectory $SpecDirectory
    New-Item -ItemType Directory -Path $DistDirectory -Force | Out-Null
    New-Item -ItemType Directory -Path $SpecDirectory -Force | Out-Null

    & $Python -m PyInstaller `
        --noconfirm `
        --clean `
        --onefile `
        --windowed `
        --name CrashX `
        --icon "$ProjectRoot\assets\windows\CrashX.ico" `
        --manifest "$ProjectRoot\assets\windows\CrashX.manifest" `
        --distpath "$DistDirectory" `
        --workpath "$WorkDirectory" `
        --specpath "$SpecDirectory" `
        --paths "$ProjectRoot\src" `
        --add-data "$ProjectRoot\assets\windows\CrashX.png;assets/windows" `
        --exclude-module numpy `
        --exclude-module sqlite3 `
        --exclude-module yaml `
        "$ProjectRoot\run_crashx.py"
    Assert-LastExitCode "PyInstaller one-file build"
} finally {
    $env:PYTHONPATH = $PreviousPythonPath
}

$BuiltExecutable = "$DistDirectory\CrashX.exe"
if (-not (Test-Path $BuiltExecutable)) {
    throw "The single-file executable was not created: $BuiltExecutable"
}
& $Python "$ProjectRoot\scripts\verify_windows_executable_manifest.py" "$BuiltExecutable"
Assert-LastExitCode "Windows executable manifest verification"

Remove-ProjectDirectory $IsolatedDirectory
Remove-ProjectDirectory $SelfTestDirectory
New-Item -ItemType Directory -Path $IsolatedDirectory -Force | Out-Null
New-Item -ItemType Directory -Path $SelfTestDirectory -Force | Out-Null
$IsolatedExecutable = "$IsolatedDirectory\CrashX.exe"
Copy-FileWithRetry $BuiltExecutable $IsolatedExecutable

$InitialEntries = @(Get-ChildItem -LiteralPath $IsolatedDirectory -Force)
if ($InitialEntries.Count -ne 1 -or $InitialEntries[0].Name -ne "CrashX.exe") {
    throw "The isolated test directory must contain only CrashX.exe before launch."
}

$Process = Start-Process -FilePath $IsolatedExecutable `
    -ArgumentList "--self-test", "`"$SelfTestDirectory`"" `
    -WorkingDirectory $IsolatedDirectory `
    -WindowStyle Hidden `
    -Wait -PassThru
if ($Process.ExitCode -ne 0) {
    $FailureLog = "$SelfTestDirectory\portable_self_test.txt"
    if (Test-Path $FailureLog) { Get-Content -LiteralPath $FailureLog | Write-Host }
    throw "The single-file executable failed its self-test with exit code $($Process.ExitCode)."
}
$SelfTestLog = "$SelfTestDirectory\portable_self_test.txt"
if (-not (Test-Path $SelfTestLog) -or -not (Select-String -Path $SelfTestLog -Pattern "^PASS$" -Quiet)) {
    throw "The single-file executable did not produce a passing self-test log."
}

$FinalEntries = @(Get-ChildItem -LiteralPath $IsolatedDirectory -Force)
if ($FinalEntries.Count -ne 1 -or $FinalEntries[0].Name -ne "CrashX.exe") {
    throw "The single-file executable created unexpected helper files beside itself."
}

$ReleaseDirectory = "$ProjectRoot\release"
New-Item -ItemType Directory -Path $ReleaseDirectory -Force | Out-Null
$ReleaseExecutable = "$ReleaseDirectory\CrashX-$Version-Windows-Single.exe"
Copy-FileWithRetry $IsolatedExecutable $ReleaseExecutable
& $Python "$ProjectRoot\scripts\verify_windows_executable_manifest.py" "$ReleaseExecutable"
Assert-LastExitCode "Released executable manifest verification"

$Hash = (Get-FileHash -Algorithm SHA256 $ReleaseExecutable).Hash.ToLowerInvariant()
$Checksum = "$ReleaseExecutable.sha256.txt"
"$Hash *$(Split-Path -Leaf $ReleaseExecutable)" | Set-Content $Checksum -Encoding ASCII

Write-Host "Single-file executable self-test: PASS"
Write-Host "No adjacent helper files check: PASS"
Write-Host "Single-file application created at:"
Write-Host $ReleaseExecutable
Write-Host "SHA-256: $Hash"
} catch {
    Write-Error $_
    exit 1
}
exit 0

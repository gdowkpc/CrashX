param(
    [switch]$Clean,
    [switch]$SkipTests,
    [switch]$SkipPackage,
    [string]$PortableDistRoot = ""
)

try {
$ErrorActionPreference = "Stop"
$ProjectRoot = Split-Path -Parent $PSScriptRoot
if ([string]::IsNullOrWhiteSpace($PortableDistRoot)) {
    $PortableDistRoot = "$ProjectRoot\portable-dist"
} else {
    $PortableDistRoot = [IO.Path]::GetFullPath($PortableDistRoot)
}
$ApplicationFolder = "$PortableDistRoot\CrashX"
$WorkDirectory = "$ProjectRoot\build\traffic-crash-exchange"
$SpecDirectory = "$ProjectRoot\build\traffic-crash-exchange-spec"
$SelfTestDirectory = "$ProjectRoot\build\traffic-crash-exchange-self-test"
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

function Compress-PortableArchiveWithRetry(
    [string]$SourcePath,
    [string]$DestinationPath
) {
    $MaximumAttempts = 6
    for ($Attempt = 1; $Attempt -le $MaximumAttempts; $Attempt++) {
        try {
            if (Test-Path $DestinationPath) {
                Remove-Item -LiteralPath $DestinationPath -Force
            }
            Compress-Archive `
                -Path $SourcePath `
                -DestinationPath $DestinationPath `
                -CompressionLevel Optimal
            return
        } catch {
            if ($Attempt -eq $MaximumAttempts) {
                throw
            }
            Write-Warning (
                "Portable packaging attempt $Attempt failed; retrying after a transient file lock. " +
                $_.Exception.Message
            )
            Start-Sleep -Seconds 2
        }
    }
}

if ($Clean) {
    Remove-ProjectDirectory $ApplicationFolder
    Remove-ProjectDirectory $WorkDirectory
    Remove-ProjectDirectory $SpecDirectory
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

    Remove-ProjectDirectory $ApplicationFolder
    Remove-ProjectDirectory $WorkDirectory
    Remove-ProjectDirectory $SpecDirectory
    New-Item -ItemType Directory -Path $SpecDirectory -Force | Out-Null

    & $Python -m PyInstaller `
        --noconfirm `
        --clean `
        --onedir `
        --windowed `
        --name CrashX `
        --icon "$ProjectRoot\assets\windows\CrashX.ico" `
        --manifest "$ProjectRoot\assets\windows\CrashX.manifest" `
        --distpath "$PortableDistRoot" `
        --workpath "$WorkDirectory" `
        --specpath "$SpecDirectory" `
        --paths "$ProjectRoot\src" `
        --add-data "$ProjectRoot\assets\windows\CrashX.png;assets/windows" `
        --exclude-module numpy `
        --exclude-module sqlite3 `
        --exclude-module yaml `
        "$ProjectRoot\run_crashx.py"
    Assert-LastExitCode "PyInstaller build"
} finally {
    $env:PYTHONPATH = $PreviousPythonPath
}

$Executable = "$ApplicationFolder\CrashX.exe"
if (-not (Test-Path $Executable)) {
    throw "The portable executable was not created: $Executable"
}
& $Python "$ProjectRoot\scripts\verify_windows_executable_manifest.py" "$Executable"
Assert-LastExitCode "Windows executable manifest verification"

Copy-Item `
    -LiteralPath "$ProjectRoot\docs\CRASHX_PORTABLE.txt" `
    -Destination "$ApplicationFolder\START_HERE.txt" `
    -Force

$BuildMoment = Get-Date
$BuildTime = $BuildMoment.ToString("MM/dd/yyyy HH:mm:ss zzz")
$BuildId = "$Version-$($BuildMoment.ToString('yyyyMMdd-HHmmss'))"
$PythonVersion = (& $Python --version 2>&1).ToString().Trim()
@(
    "CrashX $Version"
    "Portable Windows x64 build"
    "Build ID: $BuildId"
    "Built: $BuildTime"
    "Build runtime: $PythonVersion"
    "No installer or administrator rights are required on the target computer."
    "Entered data is kept only in memory; the explicitly saved PDF is the only retained work product."
) | Set-Content "$ApplicationFolder\BUILD_INFO.txt" -Encoding UTF8

Remove-ProjectDirectory $SelfTestDirectory
New-Item -ItemType Directory -Path $SelfTestDirectory -Force | Out-Null
$Process = Start-Process -FilePath $Executable `
    -ArgumentList "--self-test", "`"$SelfTestDirectory`"" `
    -WindowStyle Hidden `
    -Wait -PassThru
if ($Process.ExitCode -ne 0) {
    $FailureLog = "$SelfTestDirectory\portable_self_test.txt"
    if (Test-Path $FailureLog) { Get-Content -LiteralPath $FailureLog | Write-Host }
    throw "The finished executable failed its portable self-test with exit code $($Process.ExitCode)."
}
$SelfTestLog = "$SelfTestDirectory\portable_self_test.txt"
if (-not (Test-Path $SelfTestLog) -or -not (Select-String -Path $SelfTestLog -Pattern "^PASS$" -Quiet)) {
    throw "The finished executable did not produce a passing self-test log."
}

Write-Host "Portable executable self-test: PASS"
if (-not $SkipPackage) {
    $ReleaseDirectory = "$ProjectRoot\release"
    New-Item -ItemType Directory -Path $ReleaseDirectory -Force | Out-Null
    $Archive = "$ReleaseDirectory\CrashX-$Version-Windows-Portable.zip"
    Compress-PortableArchiveWithRetry $ApplicationFolder $Archive
    $Hash = (Get-FileHash -Algorithm SHA256 $Archive).Hash.ToLowerInvariant()
    $Checksum = "$Archive.sha256.txt"
    "$Hash *$(Split-Path -Leaf $Archive)" | Set-Content $Checksum -Encoding ASCII
    & $Python "$ProjectRoot\scripts\verify_exchange_release.py" `
        --archive "$Archive" `
        --checksum "$Checksum" `
        --xref "$WorkDirectory\CrashX\xref-CrashX.html"
    Assert-LastExitCode "Standalone release verification"
    Write-Host "Portable package created at:"
    Write-Host $Archive
    Write-Host "SHA-256: $Hash"
} else {
    Write-Host "Portable application created at:"
    Write-Host $Executable
}
} catch {
    Write-Error $_
    exit 1
}
exit 0

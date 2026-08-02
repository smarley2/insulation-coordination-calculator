param(
    [Parameter(Mandatory = $true)][string]$Installer,
    [Parameter(Mandatory = $true)][string]$FixtureDirectory,
    [string]$Version = "0.1.0"
)

$ErrorActionPreference = "Stop"
$installDirectory = Join-Path $env:LOCALAPPDATA "Insulation Coordination Calculator"
$preserve = Join-Path $env:LOCALAPPDATA "icc\rules\preserve-me.txt"
New-Item -ItemType Directory -Force (Split-Path $preserve) | Out-Null
Set-Content -Path $preserve -Value "must survive uninstall"

& $Installer /VERYSILENT /SUPPRESSMSGBOXES /NORESTART /DAppVersion=$Version
if ($LASTEXITCODE -ne 0) { throw "installer failed: $LASTEXITCODE" }
$executable = Join-Path $installDirectory "icc.exe"
if (-not (Test-Path $executable)) { throw "installed executable is missing" }
$projectCommand = (Get-ItemProperty "Registry::HKEY_CURRENT_USER\Software\Classes\InsulationCoordinationProject\shell\open\command").'(default)'
$rulesCommand = (Get-ItemProperty "Registry::HKEY_CURRENT_USER\Software\Classes\InsulationCoordinationRules\shell\open\command").'(default)'
if ($projectCommand -notlike "*%1*" -or $rulesCommand -notlike "*%1*") { throw "file associations are incomplete" }

$diagnosticOutput = Join-Path $env:TEMP "icc-release-diagnostic"
Remove-Item -Recurse -Force -ErrorAction SilentlyContinue $diagnosticOutput
& $executable --release-diagnostic $FixtureDirectory --output-dir $diagnosticOutput
if ($LASTEXITCODE -ne 0) { throw "release diagnostic failed: $LASTEXITCODE" }
$result = Get-Content (Join-Path $diagnosticOutput "diagnostic.json") | ConvertFrom-Json
if (-not $result.success -or -not (Test-Path $result.pdf_path)) { throw "diagnostic did not produce a PDF" }

$uninstaller = Join-Path $installDirectory "unins000.exe"
& $uninstaller /VERYSILENT /SUPPRESSMSGBOXES /NORESTART
if ($LASTEXITCODE -ne 0) { throw "uninstaller failed: $LASTEXITCODE" }
if (-not (Test-Path $preserve)) { throw "user rules were removed by uninstall" }

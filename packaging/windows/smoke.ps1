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

$installerPath = (Resolve-Path $Installer).Path
$installProcess = Start-Process -FilePath $installerPath -ArgumentList @(
    "/VERYSILENT", "/SUPPRESSMSGBOXES", "/NORESTART"
) -Wait -PassThru
if ($installProcess.ExitCode -ne 0) { throw "installer failed: $($installProcess.ExitCode)" }
$executable = Join-Path $installDirectory "icc.exe"
if (-not (Test-Path $executable)) { throw "installed executable is missing" }
$projectCommand = (Get-ItemProperty "Registry::HKEY_CURRENT_USER\Software\Classes\InsulationCoordinationProject\shell\open\command").'(default)'
$rulesCommand = (Get-ItemProperty "Registry::HKEY_CURRENT_USER\Software\Classes\InsulationCoordinationRules\shell\open\command").'(default)'
if ($projectCommand -notlike "*%1*" -or $rulesCommand -notlike "*%1*") { throw "file associations are incomplete" }

$diagnosticOutput = Join-Path $env:TEMP "icc-release-diagnostic"
Remove-Item -Recurse -Force -ErrorAction SilentlyContinue $diagnosticOutput
$project = Join-Path $FixtureDirectory "project.icproj"
$rules = Join-Path $FixtureDirectory "rules.icrules"
$diagnosticProcess = Start-Process -FilePath $executable -ArgumentList @(
    "--release-diagnostic", $project, $rules, $diagnosticOutput
) -Wait -PassThru
if ($diagnosticProcess.ExitCode -ne 0) { throw "release diagnostic failed: $($diagnosticProcess.ExitCode)" }
$result = Get-Content (Join-Path $diagnosticOutput "release-diagnostic.json") | ConvertFrom-Json
if (-not $result.success -or -not (Test-Path $result.pdf_path)) { throw "diagnostic did not produce a PDF" }

$uninstaller = Join-Path $installDirectory "unins000.exe"
$uninstallProcess = Start-Process -FilePath $uninstaller -ArgumentList @(
    "/VERYSILENT", "/SUPPRESSMSGBOXES", "/NORESTART"
) -Wait -PassThru
if ($uninstallProcess.ExitCode -ne 0) { throw "uninstaller failed: $($uninstallProcess.ExitCode)" }
if (-not (Test-Path $preserve)) { throw "user rules were removed by uninstall" }

[CmdletBinding()]
param(
    [string]$ProjectName = "sbs-itsm-staging",
    [string]$EnvironmentFile = ".env.staging.local",
    [string]$SecretsDirectory = "secrets",
    [string]$AlertmanagerUrl = "http://127.0.0.1:9093"
)

$ErrorActionPreference = "Stop"
$projectRoot = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
$configuredPython = $env:SBS_BACKUP_PYTHON
$bundledPython = Join-Path $env:USERPROFILE ".cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe"

if ($configuredPython -and (Test-Path -LiteralPath $configuredPython)) {
    $python = $configuredPython
} elseif (Test-Path -LiteralPath $bundledPython) {
    $python = $bundledPython
} elseif (Get-Command python3 -ErrorAction SilentlyContinue) {
    $python = (Get-Command python3).Source
} else {
    throw "Python 3 was not found. Set SBS_BACKUP_PYTHON to an absolute Python executable path."
}

$arguments = @(
    (Join-Path $projectRoot "scripts\run-backup.py"),
    "--project-name", $ProjectName,
    "--compose-file", (Join-Path $projectRoot "docker-compose.prod.yml"),
    "--env-file", (Join-Path $projectRoot $EnvironmentFile),
    "--encryption-key-file", (Join-Path $projectRoot "$SecretsDirectory\backup_encryption_key"),
    "--output-root", (Join-Path $projectRoot "backups\scheduled"),
    "--alertmanager-url", $AlertmanagerUrl,
    "--apply-retention",
    "--daily", "7",
    "--weekly", "4",
    "--monthly", "6"
)

Push-Location $projectRoot
try {
    & $python @arguments
    if ($LASTEXITCODE -ne 0) {
        throw "Backup process exited with code $LASTEXITCODE"
    }
} finally {
    Pop-Location
}

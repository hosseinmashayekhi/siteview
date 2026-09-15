[CmdletBinding()]
param(
    [ValidateNotNullOrEmpty()]
    [string]$AtlasRoot = 'C:\3dcamera'
)

Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'

$RepoRoot = (Resolve-Path (Join-Path $PSScriptRoot '..\..')).Path
$DataRoot = Join-Path $AtlasRoot 'data'
$EnvironmentReport = Join-Path $DataRoot 'reports\environment.json'
$VenvRoot = Join-Path $RepoRoot '.venv'
$VenvPython = Join-Path $VenvRoot 'Scripts\python.exe'

$PythonCommand = Get-Command python -ErrorAction SilentlyContinue
if ($null -eq $PythonCommand) {
    throw @'
Python 3.11 or newer was not found on PATH.
Install it, reopen PowerShell, and run this setup again:
  winget install --id Python.Python.3.12 --exact
'@
}

$PythonVersion = & $PythonCommand.Source -c 'import platform; print(platform.python_version())'
if ($LASTEXITCODE -ne 0) {
    throw 'Python was found but could not be executed.'
}
if ([version]$PythonVersion -lt [version]'3.11') {
    throw "Atlas requires Python 3.11 or newer; found $PythonVersion."
}

if (-not (Test-Path -LiteralPath $VenvPython -PathType Leaf)) {
    & $PythonCommand.Source -m venv $VenvRoot
    if ($LASTEXITCODE -ne 0) {
        throw 'Failed to create the Atlas Python virtual environment.'
    }
}

& $VenvPython -m pip install --disable-pip-version-check --editable "${RepoRoot}[dev]"
if ($LASTEXITCODE -ne 0) {
    throw 'Failed to install the checked-out Atlas package into its virtual environment.'
}

$env:ATLAS_ROOT = $AtlasRoot
$env:ATLAS_DATA_ROOT = $DataRoot

& $VenvPython -m atlas.cli init-workspace --root $AtlasRoot --repo $RepoRoot
if ($LASTEXITCODE -ne 0) {
    throw 'Atlas workspace initialization failed.'
}

& $VenvPython -m atlas.cli probe-environment --output $EnvironmentReport
if ($LASTEXITCODE -ne 0) {
    throw 'Atlas environment inspection failed.'
}

$Report = Get-Content -LiteralPath $EnvironmentReport -Raw | ConvertFrom-Json
$Remediation = @{
    git = 'winget install --id Git.Git --exact'
    ffmpeg = 'winget install --id Gyan.FFmpeg --exact'
    ffprobe = 'winget install --id Gyan.FFmpeg --exact'
    docker = 'winget install --id Docker.DockerDesktop --exact'
    wsl = 'wsl --install'
    nvidia_smi = 'Install/update the NVIDIA Studio Driver, then restart Windows.'
}

foreach ($ToolName in @('git', 'ffmpeg', 'ffprobe', 'docker', 'wsl', 'nvidia_smi')) {
    if (-not $Report.tools.$ToolName.available) {
        Write-Warning "$ToolName is not ready. Remediation: $($Remediation[$ToolName])"
    }
}

Write-Host ''
Write-Host 'Atlas laptop workspace is initialized.' -ForegroundColor Green
Write-Host "Source code:        $RepoRoot"
Write-Host "Generated data:     $DataRoot"
Write-Host "Environment report: $EnvironmentReport"
Write-Host 'No media, frames, meshes, splats, or credentials were written into Git.'

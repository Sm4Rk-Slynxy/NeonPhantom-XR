$ErrorActionPreference = 'Stop'
Set-Location -LiteralPath $PSScriptRoot
try {
    $server = Join-Path $PSScriptRoot 'deskdanced\target\release\deskdanced.exe'
    if (-not (Test-Path -LiteralPath $server)) { throw 'Windows executable missing. Extract the complete NeonPhantom-XR-Windows-x64.zip package.' }
    if (-not $env:DESKDANCE_ROOT) { $env:DESKDANCE_ROOT = $PSScriptRoot }
    if (-not $env:DESKDANCE_PYTHON) { $env:DESKDANCE_PYTHON = Join-Path $PSScriptRoot '.venv-ai\Scripts\python.exe' }
    if (-not (Test-Path -LiteralPath $env:DESKDANCE_PYTHON)) { throw 'Run setup-windows.cmd first.' }
    foreach ($tool in @('ffmpeg', 'ffprobe')) {
        if (-not (Get-Command $tool -ErrorAction SilentlyContinue)) { throw "$tool is missing from PATH. See WINDOWS-README.md." }
    }
    $studioPort = if ($env:DESKDANCE_PORT) { [int]$env:DESKDANCE_PORT } else { 8321 }
    Write-Host "Open http://127.0.0.1:$studioPort/ in your browser. Keep this window open; Ctrl+C stops NeonPhantom XR."
    & $server
    exit $LASTEXITCODE
} catch {
    Write-Error $_
    exit 1
}

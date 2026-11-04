$ErrorActionPreference = 'Stop'
Set-Location -LiteralPath $PSScriptRoot
try {
    $pythonCommand = $null
    foreach ($version in @('-3.12', '-3.13', '-3.11')) {
        if (Get-Command py -ErrorAction SilentlyContinue) {
            try { $candidate = & py $version -c "import sys; print(sys.executable)" 2>$null } catch { continue }
            if ($LASTEXITCODE -eq 0 -and $candidate) { $pythonCommand = $candidate.Trim(); break }
        }
    }
    if (-not $pythonCommand -and (Get-Command python -ErrorAction SilentlyContinue)) {
        try { $candidate = & python -c "import sys; assert (3,11) <= sys.version_info[:2] <= (3,13); print(sys.executable)" 2>$null } catch { $candidate = $null }
        if ($LASTEXITCODE -eq 0 -and $candidate) { $pythonCommand = $candidate.Trim() }
    }
    if (-not $pythonCommand) { throw 'Install Python 3.12 from python.org (include the Python launcher), then run setup-windows.cmd again. See WINDOWS-README.md.' }
    foreach ($tool in @('ffmpeg', 'ffprobe')) {
        if (-not (Get-Command $tool -ErrorAction SilentlyContinue)) { throw "$tool is missing. Install FFmpeg and add its bin folder to PATH, reopen the terminal, then retry. See WINDOWS-README.md." }
    }
    if (-not (Test-Path -LiteralPath '.venv-ai\Scripts\python.exe')) {
        & $pythonCommand -m venv .venv-ai
        if ($LASTEXITCODE -ne 0) { throw 'Could not create the base Python environment.' }
    }
    $runtimePython = Join-Path $PSScriptRoot '.venv-ai\Scripts\python.exe'
    & $runtimePython -m pip install --upgrade pip
    if ($LASTEXITCODE -ne 0) { throw 'Could not prepare pip.' }
    & $runtimePython -m pip install -r requirements-windows.txt
    if ($LASTEXITCODE -ne 0) { throw 'Could not install Windows runtime packages.' }
    & $runtimePython -c "import rembg, onnxruntime, PySide6"
    if ($LASTEXITCODE -ne 0) { throw 'Windows runtime validation failed.' }
    Write-Host 'Setup complete. Run start-windows.cmd. Optional models download from inside the studio.'
} catch {
    Write-Error $_
    exit 1
}

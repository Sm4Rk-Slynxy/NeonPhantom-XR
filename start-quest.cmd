@echo off
cd /d "%~dp0"
if not exist ".venv-ai\Scripts\python.exe" (
  echo Run setup-windows.cmd first. See QUEST-README.md.
  pause
  exit /b 1
)
".venv-ai\Scripts\python.exe" "quest\companion.py" %*
if errorlevel 1 pause

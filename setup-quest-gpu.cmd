@echo off
cd /d "%~dp0"
py -3.12 -m venv .venv-quest-gpu
if errorlevel 1 goto failed
".venv-quest-gpu\Scripts\python.exe" -m pip install -r requirements-quest-gpu.txt
if errorlevel 1 goto failed
echo Optional NVIDIA depth runtime installed. Restart start-quest.cmd and choose Auto or GPU preferred.
pause
exit /b 0
:failed
echo GPU setup failed. CPU playback and conversion remain available.
pause
exit /b 1

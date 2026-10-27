@echo off
setlocal
cd /d "%~dp0"
if exist "%APPDATA%\uv\python\cpython-3.11.16-windows-x86_64-none\python.exe" (
    "%APPDATA%\uv\python\cpython-3.11.16-windows-x86_64-none\python.exe" run.py
) else (
    py -3 run.py
)
echo.
pause

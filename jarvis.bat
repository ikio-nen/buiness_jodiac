
@echo off
cd /d "%~dp0"
set "JODIAC_HOME=%~dp0jodiac_data"
set "JODIAC_OBSIDIAN=%~dp0jodiac_data\obsidian"
if exist "E:\python.exe" (
    "E:\python.exe" -m agents.jarvis %*
) else (
    python -m agents.jarvis %*
)

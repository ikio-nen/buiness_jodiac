@echo off
cd /d "%~dp0"
set "JODIAC_HOME=%~dp0jodiac_data"
set "JODIAC_OBSIDIAN=%~dp0jodiac_data\obsidian"
rem Windows consoles default to a legacy codepage (cp932 here). The app prints
rem em dashes and the rupee sign, which raise UnicodeEncodeError under cp932,
rem so every interpreter this launcher starts must be in UTF-8 mode.
set "PYTHONUTF8=1"
set "PYTHONIOENCODING=utf-8"
if exist "E:\python.exe" (
    "E:\python.exe" -X utf8 -m agents.jarvis %*
) else (
    python -X utf8 -m agents.jarvis %*
)

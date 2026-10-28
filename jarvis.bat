
@echo off
cd /d "%~dp0"
set "JODIAC_HOME=%~dp0jodiac_data"
set "JODIAC_OBSIDIAN=%~dp0jodiac_data\obsidian"
python -m agents.jarvis %*

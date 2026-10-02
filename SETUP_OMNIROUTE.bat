@echo off
echo ============================================
echo   OmniRoute Setup for Claude Code
echo ============================================
echo.

echo [1/3] Cleaning old install...
npm uninstall -g omniroute 2>nul

echo [2/3] Installing OmniRoute...
npm install -g omniroute

echo [3/3] Starting OmniRoute server...
echo.
echo OmniRoute will start on http://localhost:20128
echo Keep this window open while using Claude Code.
echo.
echo To configure Claude Code, run in a NEW terminal:
echo   set ANTHROPIC_BASE_URL=http://localhost:20128/v1
echo   set ANTHROPIC_API_KEY=omniroute
echo   claude
echo.
echo Or add to your system environment variables permanently.
echo.
omniroute start

@echo off
chcp 65001 >nul
cd /d "%~dp0.."
echo === 扫描一次(前台，能看到日志) ===
.venv\Scripts\python run_agent.py once
echo.
pause

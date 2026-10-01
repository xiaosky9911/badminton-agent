@echo off
chcp 65001 >nul
echo 停止并删除计划任务 BadmintonAgent ...
schtasks /End    /TN "BadmintonAgent" 2>nul
schtasks /Delete /TN "BadmintonAgent" /F 2>nul
echo 完成。
pause

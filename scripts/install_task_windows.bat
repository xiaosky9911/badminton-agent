@echo off
chcp 65001 >nul
cd /d "%~dp0.."
set ROOT=%CD%
set PYW=%ROOT%\.venv\Scripts\pythonw.exe

if not exist "%PYW%" (
  echo [错误] 还没安装好虚拟环境。请先双击 setup_windows.bat。
  pause & exit /b 1
)

echo 创建"登录后自动运行"的计划任务 BadmintonAgent ...
schtasks /Create /TN "BadmintonAgent" /TR "\"%PYW%\" \"%ROOT%\run_agent.py\" loop" /SC ONLOGON /RL LIMITED /F
if errorlevel 1 (
  echo [错误] 创建失败。试试右键"以管理员身份运行"本文件。
  pause & exit /b 1
)

echo 立即启动一次 ...
schtasks /Run /TN "BadmintonAgent"

echo.
echo ============================================================
echo   已设为开机(登录)自启，并已在后台启动(无窗口)。
echo   查看日志:  data\agent.log
echo   想要"崩溃自动重启"：打开"任务计划程序" - 找到 BadmintonAgent
echo     - 属性 - 设置 - 勾选"如果任务失败，则每隔 1 分钟重启一次"
echo   停止/卸载:  双击 uninstall_task_windows.bat
echo ============================================================
pause

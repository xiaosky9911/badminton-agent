@echo off
chcp 65001 >nul
cd /d "%~dp0.."
echo ============================================================
echo   [1/2] 创建虚拟环境 .venv
echo ============================================================
python -m venv .venv
if errorlevel 1 (
  echo.
  echo [错误] 没找到 python。请先到 https://www.python.org 安装 Python 3，
  echo        安装时务必勾选 "Add python.exe to PATH"，然后重新运行本文件。
  echo.
  pause
  exit /b 1
)
echo.
echo ============================================================
echo   [2/2] 安装依赖
echo ============================================================
.venv\Scripts\python -m pip install --upgrade pip
.venv\Scripts\python -m pip install -r requirements.txt
echo.
echo ============================================================
echo   完成！接下来：
echo   1) 复制 .env.example 为 .env，填好配置(SPREADSHEET_ID 等)
echo   2) 把 service_account.json 放进 credentials\ 文件夹
echo   3) 双击 test_once_windows.bat 试跑一次
echo ============================================================
pause

@echo off
chcp 65001 >nul
echo ===================================================
echo     Uninstalling Antigravity RTL Support (Restore)
echo ===================================================
echo.

set PYTHON_CMD=py
where py >nul 2>nul
if %errorlevel% neq 0 (
    set PYTHON_CMD=python
    where python >nul 2>nul
    if %errorlevel% neq 0 (
        if exist "C:\Users\%USERNAME%\AppData\Local\Programs\Python\Python313\python.exe" (
            set PYTHON_CMD="C:\Users\%USERNAME%\AppData\Local\Programs\Python\Python313\python.exe"
        ) else (
            echo [-] Error: Python is not found in PATH.
            pause
            exit /b 1
        )
    )
)

%PYTHON_CMD% "%~dp0antigravity_rtl.py" --unpatch
echo.
pause

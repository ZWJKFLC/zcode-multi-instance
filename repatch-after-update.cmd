@echo off
rem One-click: re-apply the multi-instance patch after a ZCode update.
rem ASCII-only on purpose. Requires python (and node for the syntax gate)
rem on PATH. Run AFTER the update finished and ZCode restarted once.
setlocal
set "WS=%~dp0"
set "LOG=%WS%repatch-log.txt"

echo ============================== >"%LOG%"
echo [%date% %time%] repatch started >>"%LOG%"

where python >nul 2>nul
if errorlevel 1 (
  echo [ERROR] python not found on PATH. Install Python 3.8+ first.
  pause
  exit /b 1
)

echo [1/3] closing all ZCode windows ...
taskkill /IM ZCode.exe /T /F >>"%LOG%" 2>&1
timeout /t 2 /nobreak >nul

echo [2/3] applying patch (auto-adapts to the installed ZCode version) ...
python "%WS%patch-zcode.py" --apply >>"%LOG%" 2>&1
if errorlevel 1 (
  echo.
  echo [FAILED] patch did not apply - full log below and in repatch-log.txt
  echo If the engine printed PATCH ABORTED, open an issue with the log attached.
  powershell -NoProfile -Command "Get-Content -Tail 30 '%LOG%'"
  pause
  exit /b 1
)

echo [3/3] relaunching main ZCode ...
start "" "%LOCALAPPDATA%\Programs\ZCode\ZCode.exe"
echo [OK] done. Start your extra instances with their launchers.
echo If taskbar grouping looks wrong, refresh Explorer with F5.
timeout /t 8 >nul

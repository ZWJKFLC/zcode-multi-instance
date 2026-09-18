@echo off
rem One-click safety net: restore the pristine app.asar that matches the
rem currently installed ZCode version (backup made by patch-zcode.py).
rem ASCII-only on purpose.
setlocal
title ZCode rollback to pristine asar
set "RES=%LOCALAPPDATA%\Programs\ZCode\resources"
set "LOG=%~dp0rollback-log.txt"

echo ============================== >"%LOG%"
echo [%date% %time%] rollback started >>"%LOG%"

for /f "usebackq delims=" %%V in (`powershell -NoProfile -Command "(Get-Item '%RES%\..\ZCode.exe').VersionInfo.ProductVersion"`) do set "V=%%V"
if "%V%"=="" (
  echo [ERROR] cannot read ZCode.exe version. Is ZCode installed for the current user?
  pause
  exit /b 1
)
echo ZCode version: %V%

echo closing all ZCode windows ...
taskkill /IM ZCode.exe /T /F >>"%LOG%" 2>&1
timeout /t 2 /nobreak >nul

if exist "%RES%\app.asar.bak-%V%" (
  echo restoring pristine asar from app.asar.bak-%V% ...
  copy /y "%RES%\app.asar.bak-%V%" "%RES%\app.asar" >>"%LOG%" 2>&1
  if errorlevel 1 (
    echo [FAILED] copy error - is ZCode still running? See rollback-log.txt
    pause
    exit /b 1
  )
  echo [OK] rolled back to pristine version %V%. Relaunching ZCode ...
  start "" "%RES%\..\ZCode.exe"
) else (
  echo [ERROR] no backup found for version %V%. Backups present:
  dir /b "%RES%\app.asar.bak-*" 2>nul
  echo Reinstall ZCode to get a clean state, then re-apply the patch if wanted.
)
timeout /t 10 >nul

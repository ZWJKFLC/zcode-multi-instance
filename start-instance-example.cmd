@echo off
rem ZCode multi-instance launcher - copy me per instance and edit the 5 vars.
rem All ASCII on purpose: chcp 65001 + non-ASCII text breaks cmd parsing.
setlocal
set "ZCODE_DATA_BASE_DIR=%USERPROFILE%\.zcode-instance2"
set "ZCODE_DESKTOP_USER_DATA_DIR=%ZCODE_DATA_BASE_DIR%\electron-userdata"
set "ZCODE_DESKTOP_APPLICATION_NAME=ZCode2"
rem MUST be .png - Electron nativeImage cannot load .ico here.
set "ZCODE_INSTANCE_ICON=%USERPROFILE%\.zcode\icons\zcode-instance2.png"
rem Unique AppUserModelID = unmerged taskbar buttons (may suppress toasts).
set "ZCODE_INSTANCE_AUMID=cn.aminer.zcode.instance2"
start "" "%LOCALAPPDATA%\Programs\ZCode\ZCode.exe"

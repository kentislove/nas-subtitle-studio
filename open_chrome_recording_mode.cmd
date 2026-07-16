@echo off
setlocal

set "URL=http://192.168.66.53:54320"
set "ORIGIN=http://192.168.66.53:54320"
set "PROFILE_DIR=C:\tmp\nas-subtitle-chrome-profile"

if not exist "C:\tmp" mkdir "C:\tmp"
if not exist "%PROFILE_DIR%" mkdir "%PROFILE_DIR%"

set "CHROME_EXE="

if exist "%ProgramFiles%\Google\Chrome\Application\chrome.exe" (
  set "CHROME_EXE=%ProgramFiles%\Google\Chrome\Application\chrome.exe"
)

if "%CHROME_EXE%"=="" if exist "%ProgramFiles(x86)%\Google\Chrome\Application\chrome.exe" (
  set "CHROME_EXE=%ProgramFiles(x86)%\Google\Chrome\Application\chrome.exe"
)

if "%CHROME_EXE%"=="" if exist "%LocalAppData%\Google\Chrome\Application\chrome.exe" (
  set "CHROME_EXE=%LocalAppData%\Google\Chrome\Application\chrome.exe"
)

if "%CHROME_EXE%"=="" (
  echo Chrome was not found.
  echo Please install Google Chrome first.
  pause
  exit /b 1
)

start "" "%CHROME_EXE%" ^
  --user-data-dir="%PROFILE_DIR%" ^
  --unsafely-treat-insecure-origin-as-secure="%ORIGIN%" ^
  --new-window "%URL%"

endlocal

@echo off
rem Minimal bootstrap: uses the Gradle version pinned in
rem gradle\wrapper\gradle-wrapper.properties (8.7 for AGP 8.5.2).
rem No gradle-wrapper.jar needed.
setlocal EnableDelayedExpansion
set "APP_HOME=%~dp0"
set "APP_HOME=%APP_HOME:~0,-1%"
for /f "tokens=1,* delims==" %%a in ('findstr "^distributionUrl=" "%APP_HOME%\gradle\wrapper\gradle-wrapper.properties"') do set "DIST_URL=%%b"
set "DIST_URL=%DIST_URL:\:=%"
if "%GRADLE_USER_HOME%"=="" set "GRADLE_USER_HOME=%USERPROFILE%\.gradle"
set "DIST_DIR=%GRADLE_USER_HOME%\wrapper\dists\gradle-pinned"
set "GRADLE_HOME=%DIST_DIR%\gradle"
if not exist "%GRADLE_HOME%\bin\gradle.bat" (
  echo Downloading Gradle ^(%DIST_URL%^)...
  if not exist "%DIST_DIR%" mkdir "%DIST_DIR%"
  set "TMP_ZIP=%DIST_DIR%\gradle.zip"
  powershell -NoProfile -ExecutionPolicy Bypass -Command "Invoke-WebRequest -Uri '%DIST_URL%' -OutFile '%TMP_ZIP%'"
  if exist "%GRADLE_HOME%" rmdir /s /q "%GRADLE_HOME%"
  mkdir "%GRADLE_HOME%"
  powershell -NoProfile -ExecutionPolicy Bypass -Command "Expand-Archive -Path '%TMP_ZIP%' -DestinationPath '%DIST_DIR%\tmp' -Force"
  for /d %%d in ("%DIST_DIR%\tmp\gradle-*") do xcopy "%%d\*" "%GRADLE_HOME%\" /e /i /h /y >nul
  rmdir /s /q "%DIST_DIR%\tmp"
  del "%TMP_ZIP%"
)
call "%GRADLE_HOME%\bin\gradle.bat" %*

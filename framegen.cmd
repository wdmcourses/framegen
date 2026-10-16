@echo off
setlocal
set "DIR=%~dp0"
set "PYTHONDONTWRITEBYTECODE=1"
set "PY=%DIR%python\python.exe"
if not exist "%PY%" set "PY=%DIR%python\win64\python.exe"
if not exist "%PY%" set "PY=python"
"%PY%" "%DIR%framegen.py" %*
set "RC=%ERRORLEVEL%"
endlocal & exit /b %RC%

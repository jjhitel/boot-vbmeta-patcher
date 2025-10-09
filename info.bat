@echo off
setlocal enabledelayedexpansion

set "PYTHON=%~dp0python3\python.exe"
set "PY_AVBTOOL=%~dp0tools\avbtool.py"

if not exist "%PYTHON%" (
    echo Error: Python executable not found at "%PYTHON%"
    pause
    exit /b
)

if not exist "%PY_AVBTOOL%" (
    echo Error: avbtool.py not found at "%PY_AVBTOOL%"
    pause
    exit /b
)

set "TMPFILE=%TEMP%\filelist.txt"
set "SORTED=%TEMP%\sorted.txt"
del "%TMPFILE%" >nul 2>nul
del "%SORTED%" >nul 2>nul

for %%a in (%*) do (
    echo %%~fa >> "%TMPFILE%"
)

sort "%TMPFILE%" /o "%SORTED%"

echo.
echo ==========================================
echo  Sorted and Processing Images...
echo ==========================================
echo.

for /f "usebackq delims=" %%a in ("%SORTED%") do (
    echo Processing file: %%~nxa
    echo ---------------------------------
    "%PYTHON%" "%PY_AVBTOOL%" info_image --image "%%~a"
    echo ---------------------------------
    echo.
)

del "%TMPFILE%" >nul 2>nul
del "%SORTED%" >nul 2>nul

pause
endlocal

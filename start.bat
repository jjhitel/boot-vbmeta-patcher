@echo off
chcp 65001 > nul
setlocal

:: --- 1. Initialization and Dependency Check ---
echo --- Initializing LTBox... ---
call "%~dp0tools\install.bat"
if errorlevel 1 (
    echo [!] Dependency installation failed. Please check tools\install.bat.
    pause
    goto :eof
)

:: --- 2. Set Python and Main Script Paths ---
set "PYTHON_EXE=%~dp0python3\python.exe"
set "MAIN_PY=%~dp0main.py"

if not exist "%PYTHON_EXE%" (
    echo [!] Python not found at: %PYTHON_EXE%
    echo [!] Please run tools\install.bat first.
    pause
    goto :eof
)
if not exist "%MAIN_PY%" (
    echo [!] Main script not found at: %MAIN_PY%
    pause
    goto :eof
)

:: --- 3. Main Menu Loop ---
:main_menu
cls
echo.
echo   ==========================================================
echo     LTBox - Main Menu
echo   ==========================================================
echo.
echo     1. Patch and Flash ROW ROM (Recommended)
echo     2. Advanced
echo.
echo     3. Exit
echo.
echo   ==========================================================
echo.

set "CHOICE="
set /p "CHOICE=    Enter the number for the task you want to run: "

if "%CHOICE%"=="1" call :run_task patch_all "Full Patch and Flash ROW ROM"
if "%CHOICE%"=="2" goto :advanced_menu
if "%CHOICE%"=="3" goto :cleanup

:: Handle invalid input
echo.
echo     [!] Invalid choice. Please enter a number from 1-3.
pause
goto :main_menu


:: --- 4. Advanced Menu ---
:advanced_menu
cls
echo.
echo   ==========================================================
echo     LTBox - Advanced Menu
echo   ==========================================================
echo.
echo     --- Single Patch Tools ---
echo     1. Convert ROM (PRC to ROW)
echo     2. Dump devinfo/persist via EDL
echo     3. Patch devinfo/persist (Region Code Reset)
echo     4. Write devinfo/persist via EDL (Flash patched)
echo     5. Create Rooted boot.img
echo.
echo     --- Anti-Rollback Tools (Manual) ---
echo     6. Read Anti-Rollback (Dump current, Compare)
echo     7. Patch Anti-Rollback (Create patched images)
echo     8. Write Anti-Rollback (Flash patched images)
echo.
echo     --- Full Firmware Tools ---
echo     9. Modify XML for Update (RSA Firmware)
echo     10. Flash EDL (Full Firmware Flash)
echo.
echo     --- Maintenance ---
echo     11. Clean Workspace (Remove tools and I/O folders)
echo     12. Back to Main Menu
echo.
echo   ==========================================================
echo.

set "ADV_CHOICE="
set /p "ADV_CHOICE=    Enter the number for the task you want to run: "

if "%ADV_CHOICE%"=="1" call :run_task convert "ROM Conversion PRC to ROW"
if "%ADV_CHOICE%"=="2" call :run_task read_edl "EDL Dump devinfo/persist"
if "%ADV_CHOICE%"=="3" call :run_task edit_dp "Patch devinfo/persist"
if "%ADV_CHOICE%"=="4" call :run_task write_edl "EDL Write devinfo/persist"
if "%ADV_CHOICE%"=="5" call :run_task root "Root boot.img"
if "%ADV_CHOICE%"=="6" call :run_task read_anti_rollback "Read Anti-Rollback Status"
if "%ADV_CHOICE%"=="7" call :run_task patch_anti_rollback "Patch Anti-Rollback Files"
if "%ADV_CHOICE%"=="8" call :run_task write_anti_rollback "Write Anti-Rollback Files"
if "%ADV_CHOICE%"=="9" call :run_task modify_xml "Modify XML for Update"
if "%ADV_CHOICE%"=="10" call :run_task flash_edl "Full EDL Flash"

if "%ADV_CHOICE%"=="11" (
    cls
    echo ==========================================================
    echo  Starting Task: [Workspace Cleanup]...
    echo ==========================================================
    echo.
    "%PYTHON_EXE%" "%MAIN_PY%" clean
    echo.
    echo ==========================================================
    echo  Task [Workspace Cleanup] has completed.
    echo ==========================================================
    echo.
    echo Press any key to exit...
    pause > nul
    goto :cleanup
)

if "%ADV_CHOICE%"=="12" goto :main_menu

echo.
echo     [!] Invalid choice. Please enter a number from 1-12.
pause
goto :advanced_menu


:: --- 5. Task Execution Subroutine ---
:run_task
cls
echo ==========================================================
echo  Starting Task: [%~2]...
echo ==========================================================
echo.

:: %1 is the main.py argument (e.g., convert), %~2 is the description string
"%PYTHON_EXE%" "%MAIN_PY%" %1

echo.
echo ==========================================================
echo  Task [%~2] has completed.
echo ==========================================================
echo.
echo Press any key to return to the main menu...
pause > nul
goto :main_menu

:: --- 6. Exit ---
:cleanup
endlocal
echo.
echo Exiting LTBox.
goto :eof
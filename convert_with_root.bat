@echo off
setlocal enabledelayedexpansion

set "TOOLS_DIR=%~dp0tools\"

echo --- Checking for required rooting tools ---
echo.

if not exist "%TOOLS_DIR%" mkdir "%TOOLS_DIR%"

echo [*] Checking for magiskboot.exe...
if exist "%TOOLS_DIR%magiskboot.exe" (
    echo [+] magiskboot.exe is present.
) else (
    echo [!] 'magiskboot.exe' not found. Attempting to download...
    curl -L "https://github.com/CYRUS-STUDIO/MagiskBootWindows/raw/refs/heads/main/magiskboot.exe" -o "%TOOLS_DIR%magiskboot.exe"
    if exist "%TOOLS_DIR%magiskboot.exe" (echo [+] Download successful.) else (echo [!] Download failed. Aborting. & pause & exit /b)
)
echo.

echo [*] Checking for ksuinit...
if exist "%TOOLS_DIR%ksuinit" (
    echo [+] ksuinit is present.
) else (
    echo [!] 'ksuinit' not found. Attempting to download...
    curl -L "https://github.com/KernelSU-Next/KernelSU-Next/releases/download/v1.1.1/ksuinit" -o "%TOOLS_DIR%ksuinit"
    if exist "%TOOLS_DIR%ksuinit" (echo [+] Download successful.) else (echo [!] Download failed. Aborting. & pause & exit /b)
)
echo.

echo [*] Checking for kernelsu.ko...
if exist "%TOOLS_DIR%kernelsu.ko" (
    echo [+] kernelsu.ko is present.
) else (
    echo [!] 'kernelsu.ko' not found. Attempting to download...
    curl -L "https://github.com/KernelSU-Next/KernelSU-Next/releases/download/v1.1.1/android14-6.1_kernelsu.ko" -o "%TOOLS_DIR%kernelsu.ko"
    if exist "%TOOLS_DIR%kernelsu.ko" (echo [+] Download successful.) else (echo [!] Download failed. Aborting. & pause & exit /b)
)
echo.


set "CURRENT_DIR=%~dp0"
set "TMP_DIR=%TOOLS_DIR%tmp_patch\"
set "KSU_APK_URL=https://github.com/KernelSU-Next/KernelSU-Next/releases/download/v1.1.1/KernelSU_Next_v1.1.1_12851-release.apk"
set "KSU_APK_NAME=KernelSU_Next_v1.1.1_12851-release.apk"

echo Starting KernelSU Boot Image Patcher...

if not exist "%CURRENT_DIR%boot.img" (
    echo Error: boot.img not found.
    pause
    exit /b
)

echo Backing up original boot.img to boot.bak.img...
move "%CURRENT_DIR%boot.img" "%CURRENT_DIR%boot.bak.img"

if exist "%TMP_DIR%" (
    echo Cleaning up previous temporary directory...
    rmdir /s /q "%TMP_DIR%"
)
mkdir "%TMP_DIR%"

echo Copying files to temporary directory...
copy "%CURRENT_DIR%boot.bak.img" "%TMP_DIR%boot.img"
copy "%TOOLS_DIR%magiskboot.exe" "%TMP_DIR%"
copy "%TOOLS_DIR%ksuinit" "%TMP_DIR%init"
copy "%TOOLS_DIR%kernelsu.ko" "%TMP_DIR%kernelsu.ko"


cd "%TMP_DIR%"

echo.
echo Unpacking boot image...
magiskboot.exe unpack boot.img

echo.
echo Patching ramdisk...
magiskboot.exe cpio ramdisk.cpio "exists init" >nul 2>&1
if !errorlevel! == 0 (
    echo Backing up original /init to /init.real...
    magiskboot.exe cpio ramdisk.cpio "mv init init.real"
) else (
    echo Original /init not found, skipping backup.
)

echo Injecting ksuinit as /init and adding kernelsu.ko...
magiskboot.exe cpio ramdisk.cpio "add 0755 init init"
magiskboot.exe cpio ramdisk.cpio "add 0644 kernelsu.ko kernelsu.ko"
del init
del kernelsu.ko

echo.
echo Repacking boot image...
magiskboot.exe repack boot.img

if exist "new-boot.img" (
    echo.
    echo Renaming patched image to boot.root.img...
    move "new-boot.img" "%CURRENT_DIR%boot.root.img"
    echo Success: Patched image saved as '%CURRENT_DIR%boot.root.img'
) else (
    echo.
    echo Error: Patched image not found. Restoring original backup.
    move "%CURRENT_DIR%boot.bak.img" "%CURRENT_DIR%boot.img"
)

cd "%CURRENT_DIR%"
echo Deleting temporary directory '%TMP_DIR%'
rmdir /s /q "%TMP_DIR%"

echo.
echo Patching script finished.
echo.

echo Checking for KernelSU Next Manager APK...
if exist "%CURRENT_DIR%%KSU_APK_NAME%" (
    echo KernelSU Next Manager APK already exists.
) else (
    echo APK not found. Attempting to download...
    curl -L "%KSU_APK_URL%" -o "%CURRENT_DIR%%KSU_APK_NAME%"
)
echo.

echo Now running convert.bat...
echo.

call convert.bat with_boot

endlocal
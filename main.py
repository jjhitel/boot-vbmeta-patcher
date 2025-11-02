import argparse
import os
import platform
import re
import shutil
import subprocess
import sys
import zipfile
import time
from datetime import datetime
from pathlib import Path

import requests 

# --- Constants ---
BASE_DIR = Path(__file__).parent.resolve()
TOOLS_DIR = BASE_DIR / "tools"
PYTHON_DIR = BASE_DIR / "python3"
AVB_DIR = TOOLS_DIR / "avb"
OUTPUT_DIR = BASE_DIR / "output"
OUTPUT_ROOT_DIR = BASE_DIR / "output_root"
OUTPUT_DP_DIR = BASE_DIR / "output_dp"
BACKUP_DIR = BASE_DIR / "backup"
WORK_DIR = BASE_DIR / "patch_work"

# --- Input Directories ---
INPUT_CURRENT_DIR = BASE_DIR / "input_current"
INPUT_NEW_DIR = BASE_DIR / "input_new"

OUTPUT_ANTI_ROLLBACK_DIR = BASE_DIR / "output_anti_rollback"

# --- Main Firmware Source / XML Dirs ---
IMAGE_DIR = BASE_DIR / "image"
WORKING_DIR = BASE_DIR / "working"
OUTPUT_XML_DIR = BASE_DIR / "output_xml"


PYTHON_EXE = PYTHON_DIR / "python.exe"
AVBTOOL_PY = AVB_DIR / "avbtool.py"
EDIT_IMAGES_PY = TOOLS_DIR / "edit_images.py"
GET_KERNEL_VER_PY = TOOLS_DIR / "get_kernel_ver.py"
DECRYPT_PY = TOOLS_DIR / "decrypt_x.py"

MAGISKBOOT_REPO_URL = "https://github.com/PinNaCode/magiskboot_build"
MAGISKBOOT_TAG = "last-ci"

KSU_APK_REPO = "KernelSU-Next/KernelSU-Next"
KSU_APK_TAG = "v1.1.1"

RELEASE_OWNER = "WildKernels"
RELEASE_REPO = "GKI_KernelSU_SUSFS"
RELEASE_TAG = "v1.5.9-r36"
REPO_URL = f"https://github.com/{RELEASE_OWNER}/{RELEASE_REPO}"

ANYKERNEL_ZIP_FILENAME = "AnyKernel3.zip"

EDL_NG_REPO_URL = "https://github.com/strongtz/edl-ng"
EDL_NG_TAG = "v1.4.1"

EDL_LOADER_FILENAME = "xbl_s_devprg_ns.melf"
EDL_LOADER_FILE = IMAGE_DIR / EDL_LOADER_FILENAME 
EDL_LOADER_FILE_IMAGE = IMAGE_DIR / EDL_LOADER_FILENAME

KEY_MAP = {
    "2597c218aae470a130f61162feaae70afd97f011": AVB_DIR / "testkey_rsa4096.pem",
    "cdbb77177f731920bbe0a0f94f84d9038ae0617d": AVB_DIR / "testkey_rsa2048.pem"
}


# --- Helper Functions ---
def run_command(command, shell=False, check=True, env=None, capture=False):
    env = env or os.environ.copy()
    env['PATH'] = str(TOOLS_DIR) + os.pathsep + env['PATH']

    try:
        process = subprocess.run(
            command, shell=shell, check=check, capture_output=True,
            text=True, encoding='utf-8', errors='ignore', env=env
        )
        if not capture:
            if process.stdout:
                print(process.stdout.strip())
            if process.stderr:
                print(process.stderr.strip(), file=sys.stderr)
        return process
    except FileNotFoundError as e:
        print(f"Error: Command not found - {e.filename}", file=sys.stderr)
        raise
    except subprocess.CalledProcessError as e:
        print(f"Error executing command: {' '.join(map(str, command))}", file=sys.stderr)
        print(f"Return code: {e.returncode}", file=sys.stderr)
        if e.stdout:
            print(f"Stdout:\n{e.stdout.strip()}", file=sys.stderr)
        if e.stderr:
            print(f"Stderr:\n{e.stderr.strip()}", file=sys.stderr)
        raise

def check_edl_device(silent=False):
    if not silent:
        print("[*] Checking for Qualcomm EDL (9008) device...")
    try:
        result = subprocess.run(
            ['wmic', 'path', 'Win32_PnPEntity', 'where', "Name like 'Qualcomm%9008%'", 'get', 'Name'],
            capture_output=True, text=True, encoding='utf-8', errors='ignore', shell=True
        )
        if "Qualcomm" in result.stdout and "9008" in result.stdout:
            if not silent:
                print("[+] Qualcomm EDL device found.")
            return True
        else:
            if not silent:
                print("[!] No Qualcomm EDL (9008) device found in Device Manager.")
                print("[!] Please connect your device in EDL mode.")
            return False
    except FileNotFoundError:
        if not silent:
            print("[!] WMIC command not found. Cannot check for EDL device.", file=sys.stderr)
        return False
    except Exception as e:
        if not silent:
            print(f"[!] Error checking for EDL device: {e}", file=sys.stderr)
        return False

def wait_for_edl():
    print("\n--- WAITING FOR EDL DEVICE ---")
    if check_edl_device():
        return
    
    while not check_edl_device(silent=True):
        print("[*] Waiting for Qualcomm EDL (9008) device... (Press Ctrl+C to cancel)")
        try:
            time.sleep(2)
        except KeyboardInterrupt:
            print("\n[!] EDL wait cancelled by user.")
            raise
    print("[+] EDL device connected.")

def get_platform_executable(name):
    system = platform.system()
    executables = {
        "Windows": f"{name}.exe",
        "Linux": f"{name}-linux",
        "Darwin": f"{name}-macos"
    }
    exe_name = executables.get(system)
    if not exe_name:
        raise RuntimeError(f"Unsupported operating system: {system}")
    return TOOLS_DIR / exe_name

def check_dependencies():
    print("--- Checking for required files ---")
    dependencies = {
        "Python Environment": PYTHON_EXE,
        "RSA4096 Key": AVB_DIR / "testkey_rsa4096.pem",
        "RSA2048 Key": AVB_DIR / "testkey_rsa2048.pem",
        "avbtool": AVBTOOL_PY,
        "fetch tool": get_platform_executable("fetch")
    }
    missing_deps = [name for name, path in dependencies.items() if not Path(path).exists()]

    if missing_deps:
        for name in missing_deps:
            print(f"[!] Error: Dependency '{name}' is missing.")
        print("Please run one of the main scripts (e.g., root.bat) to install all required files.")
        sys.exit(1)

    print("[+] All dependencies are present.\n")

def extract_image_avb_info(image_path):
    info_proc = run_command(
        [str(PYTHON_EXE), str(AVBTOOL_PY), "info_image", "--image", str(image_path)],
        capture=True
    )
    
    output = info_proc.stdout.strip()
    info = {}
    props_args = []

    partition_size_match = re.search(r"^Image size:\s*(\d+)\s*bytes", output, re.MULTILINE)
    if partition_size_match:
        info['partition_size'] = partition_size_match.group(1)
    
    data_size_match = re.search(r"Original image size:\s*(\d+)\s*bytes", output)
    if data_size_match:
        info['data_size'] = data_size_match.group(1)
    else:
        desc_size_match = re.search(r"^\s*Image Size:\s*(\d+)\s*bytes", output, re.MULTILINE)
        if desc_size_match:
            info['data_size'] = desc_size_match.group(1)

    patterns = {
        'name': r"Partition Name:\s*(\S+)",
        'salt': r"Salt:\s*([0-9a-fA-F]+)",
        'algorithm': r"Algorithm:\s*(\S+)",
        'pubkey_sha1': r"Public key \(sha1\):\s*([0-9a-fA-F]+)",
    }
    
    header_section = output.split('Descriptors:')[0]
    rollback_match = re.search(r"Rollback Index:\s*(\d+)", header_section)
    if rollback_match:
        info['rollback'] = rollback_match.group(1)
        
    flags_match = re.search(r"Flags:\s*(\d+)", header_section)
    if flags_match:
        info['flags'] = flags_match.group(1)
        if output: 
            print(f"[Info] Parsed Flags: {info['flags']}")
        
    for key, pattern in patterns.items():
        if key not in info:
            match = re.search(pattern, output)
            if match:
                info[key] = match.group(1)

    for line in output.split('\n'):
        if line.strip().startswith("Prop:"):
            parts = line.split('->')
            key = parts[0].split(':')[-1].strip()
            val = parts[1].strip()[1:-1]
            info[key] = val
            props_args.extend(["--prop", f"{key}:{val}"])
            
    info['props_args'] = props_args
    if props_args and output: 
        print(f"[Info] Parsed {len(props_args) // 2} properties.")

    return info

def wait_for_files(directory, required_files, prompt_message):
    directory.mkdir(exist_ok=True)
    while True:
        all_found = True
        missing = []
        for file in required_files:
            if not (directory / file).exists():
                all_found = False
                missing.append(file)
        
        if all_found:
            return True
        
        if platform.system() == "Windows":
            os.system('cls')
        else:
            os.system('clear')
            
        print("--- WAITING FOR FILES ---")
        print(prompt_message)
        print(f"\nPlease place the following file(s) in the '{directory.name}' folder:")
        for f in missing:
            print(f" - {f}")
        print("\nPress Enter when ready...")
        try:
            input()
        except EOFError:
            sys.exit(1)

def wait_for_directory(directory, prompt_message):
    directory.mkdir(exist_ok=True)
    while True:
        if directory.is_dir() and any(directory.iterdir()):
             return True
        
        if platform.system() == "Windows":
            os.system('cls')
        else:
            os.system('clear')
            
        print("--- WAITING FOR FOLDER ---")
        print(prompt_message)
        print(f"\nPlease copy the entire folder into this directory:")
        print(f" - {directory.name}{os.sep}")
        print("\nThis is typically located at:")
        print(r"   C:\ProgramData\RSA\Download\RomFiles\[Your_Firmware_Folder]")
        print("\nPress Enter when ready...")
        try:
            input()
        except EOFError:
            sys.exit(1)


# --- Helper Functions ---

def _ensure_magiskboot(fetch_exe, magiskboot_exe):
    if magiskboot_exe.exists():
        return True

    print(f"[!] '{magiskboot_exe.name}' not found. Attempting to download...")
    if platform.system() == "Windows":
        arch = platform.machine()
        arch_map = {
            'AMD64': 'x86_64',
            'ARM64': 'arm64',
        }
        target_arch = arch_map.get(arch, 'i686')
        
        asset_pattern = f"magiskboot-.*-windows-.*-{target_arch}-standalone\\.zip"
        
        print(f"[*] Detected Windows architecture: {arch}. Selecting matching magiskboot binary.")
        
        try:
            fetch_command = [
                str(fetch_exe),
                "--repo", MAGISKBOOT_REPO_URL,
                "--tag", MAGISKBOOT_TAG,
                "--release-asset", asset_pattern,
                str(TOOLS_DIR)
            ]
            run_command(fetch_command, capture=True)

            downloaded_zips = list(TOOLS_DIR.glob("magiskboot-*-windows-*.zip"))
            
            if not downloaded_zips:
                raise FileNotFoundError("Failed to find the downloaded magiskboot zip archive.")
            
            downloaded_zip_path = downloaded_zips[0]
            
            with zipfile.ZipFile(downloaded_zip_path, 'r') as zip_ref:
                magiskboot_info = None
                for member in zip_ref.infolist():
                    if member.filename.endswith('magiskboot.exe'):
                        magiskboot_info = member
                        break
                
                if not magiskboot_info:
                    raise FileNotFoundError("magiskboot.exe not found inside the downloaded zip archive.")

                zip_ref.extract(magiskboot_info, path=TOOLS_DIR)
                
                extracted_path = TOOLS_DIR / magiskboot_info.filename
                
                shutil.move(extracted_path, magiskboot_exe)
                
                parent_dir = extracted_path.parent
                if parent_dir.is_dir() and parent_dir != TOOLS_DIR:
                     try:
                        parent_dir.rmdir()
                     except OSError:
                        shutil.rmtree(parent_dir)

            downloaded_zip_path.unlink()
            print("[+] Download and extraction successful.")
            return True

        except (subprocess.CalledProcessError, FileNotFoundError, KeyError, IndexError) as e:
            print(f"[!] Error downloading or extracting magiskboot: {e}", file=sys.stderr)
            sys.exit(1)

    else:
        print(f"[!] Auto-download for {platform.system()} is not supported. Please add it to the 'tools' folder manually.")
        sys.exit(1)

def _get_gki_kernel(fetch_exe, kernel_version, work_dir):
    print("\n[3/8] Downloading GKI Kernel with fetch...")
    asset_pattern = f".*{kernel_version}.*AnyKernel3.zip"
    fetch_command = [
        str(fetch_exe), "--repo", REPO_URL, "--tag", RELEASE_TAG,
        "--release-asset", asset_pattern, str(work_dir)
    ]
    run_command(fetch_command)

    downloaded_files = list(work_dir.glob(f"*{kernel_version}*AnyKernel3.zip"))
    if not downloaded_files:
        print(f"[!] Failed to download AnyKernel3.zip for kernel {kernel_version}.")
        sys.exit(1)
    
    anykernel_zip = work_dir / ANYKERNEL_ZIP_FILENAME
    shutil.move(downloaded_files[0], anykernel_zip)
    print("[+] Download complete.")

    print("\n[4/8] Extracting new kernel image...")
    extracted_kernel_dir = work_dir / "extracted_kernel"
    with zipfile.ZipFile(anykernel_zip, 'r') as zip_ref:
        zip_ref.extractall(extracted_kernel_dir)
    
    kernel_image = extracted_kernel_dir / "Image"
    if not kernel_image.exists():
        print("[!] 'Image' file not found in the downloaded zip.")
        sys.exit(1)
    print("[+] Extraction successful.")
    return kernel_image

def _download_ksu_apk(fetch_exe, target_dir):
    print("\n[7/8] Downloading KernelSU Manager APKs...")
    if list(target_dir.glob("KernelSU*.apk")):
        print("[+] KernelSU Manager APK already exists. Skipping download.")
    else:
        ksu_apk_command = [
            str(fetch_exe), "--repo", f"https://github.com/{KSU_APK_REPO}", "--tag", KSU_APK_TAG,
            "--release-asset", ".*\\.apk", str(target_dir)
        ]
        run_command(ksu_apk_command)
        print("[+] KernelSU Manager APKs downloaded to the main directory (if found).")

def _ensure_edl_ng():
    if platform.system() != "Windows":
        print("[!] EDL functions are only supported on Windows.", file=sys.stderr)
        sys.exit(1)
        
    edl_ng_exe = TOOLS_DIR / "edl-ng.exe"
    if edl_ng_exe.exists():
        return edl_ng_exe

    fetch_exe = get_platform_executable("fetch")
    if not fetch_exe.exists():
         print(f"[!] '{fetch_exe.name}' not found. Please run install.bat")
         sys.exit(1)

    print(f"[!] '{edl_ng_exe.name}' not found. Attempting to download...")
    arch = platform.machine()
    if arch == 'AMD64':
        asset_pattern = "edl-ng-windows-x64.zip"
    elif arch == 'ARM64':
        asset_pattern = "edl-ng-windows-arm64.zip"
    else:
        print(f"[!] Unsupported Windows architecture: {arch}. Cannot download edl-ng.", file=sys.stderr)
        sys.exit(1)
        
    print(f"[*] Detected {arch} architecture. Downloading '{asset_pattern}'...")

    try:
        fetch_command = [
            str(fetch_exe),
            "--repo", EDL_NG_REPO_URL,
            "--tag", EDL_NG_TAG,
            "--release-asset", asset_pattern,
            str(TOOLS_DIR)
        ]
        run_command(fetch_command, capture=True)

        downloaded_zip_path = TOOLS_DIR / asset_pattern
        
        if not downloaded_zip_path.exists():
            raise FileNotFoundError(f"Failed to find the downloaded edl-ng zip archive: {asset_pattern}")
        
        with zipfile.ZipFile(downloaded_zip_path, 'r') as zip_ref:
            edl_info = None
            for member in zip_ref.infolist():
                if member.filename.endswith('edl-ng.exe'):
                    edl_info = member
                    break
            
            if not edl_info:
                raise FileNotFoundError("edl-ng.exe not found inside the downloaded zip archive.")

            zip_ref.extract(edl_info, path=TOOLS_DIR)
            
            extracted_path = TOOLS_DIR / edl_info.filename
            if extracted_path != edl_ng_exe:
                shutil.move(extracted_path, edl_ng_exe)
                parent_dir = extracted_path.parent
                if parent_dir.is_dir() and parent_dir != TOOLS_DIR:
                    try:
                        parent_dir.rmdir()
                    except OSError:
                        shutil.rmtree(parent_dir, ignore_errors=True)

        downloaded_zip_path.unlink()
        print("[+] edl-ng download and extraction successful.")
        return edl_ng_exe

    except (subprocess.CalledProcessError, FileNotFoundError, KeyError, IndexError) as e:
        print(f"[!] Error downloading or extracting edl-ng: {e}", file=sys.stderr)
        sys.exit(1)

def _apply_hash_footer(image_path, image_info, key_file, new_rollback_index=None):
    rollback_index = new_rollback_index if new_rollback_index is not None else image_info['rollback']
    
    print(f"\n[*] Adding hash footer to '{image_path.name}'...")
    print(f"  > Partition: {image_info['name']}, Rollback Index: {rollback_index}")

    add_footer_cmd = [
        str(PYTHON_EXE), str(AVBTOOL_PY), "add_hash_footer",
        "--image", str(image_path), 
        "--key", str(key_file),
        "--algorithm", image_info['algorithm'], 
        "--partition_size", image_info['partition_size'],
        "--partition_name", image_info['name'], 
        "--rollback_index", str(rollback_index),
        "--salt", image_info['salt'], 
        *image_info.get('props_args', [])
    ]
    
    if 'flags' in image_info:
        add_footer_cmd.extend(["--flags", image_info.get('flags', '0')])
        print(f"  > Restoring flags: {image_info.get('flags', '0')}")

    run_command(add_footer_cmd)
    print(f"[+] Successfully applied hash footer to {image_path.name}.")


# --- Core Functions ---
def patch_boot_with_root():
    print("--- Starting boot.img patching process ---")
    magiskboot_exe = get_platform_executable("magiskboot")
    fetch_exe = get_platform_executable("fetch")
    
    patched_boot_path = BASE_DIR / "boot.root.img"

    if not fetch_exe.exists():
         print(f"[!] '{fetch_exe.name}' not found. Please run install.bat")
         sys.exit(1)

    _ensure_magiskboot(fetch_exe, magiskboot_exe)

    if platform.system() != "Windows":
        os.chmod(magiskboot_exe, 0o755)
        os.chmod(fetch_exe, 0o755)

    print("--- Waiting for boot.img ---") 
    IMAGE_DIR.mkdir(exist_ok=True) 
    required_files = ["boot.img"]
    prompt = (
        "[STEP 1] Place your stock 'boot.img' file\n"
        f"         (e.g., from your firmware) into the '{IMAGE_DIR.name}' folder."
    )
    wait_for_files(IMAGE_DIR, required_files, prompt)
    
    boot_img_src = IMAGE_DIR / "boot.img"
    boot_img = BASE_DIR / "boot.img" 
    
    try:
        shutil.copy(boot_img_src, boot_img)
        print(f"[+] Copied '{boot_img_src.name}' to main directory for processing.")
    except (IOError, OSError) as e:
        print(f"[!] Failed to copy '{boot_img_src.name}': {e}", file=sys.stderr)
        sys.exit(1)

    if not boot_img.exists():
        print("[!] 'boot.img' not found! Aborting.")
        sys.exit(1)

    shutil.copy(boot_img, BASE_DIR / "boot.bak.img")
    print("--- Backing up original boot.img ---")

    if WORK_DIR.exists():
        shutil.rmtree(WORK_DIR)
    WORK_DIR.mkdir()

    original_cwd = Path.cwd()
    os.chdir(WORK_DIR)

    try:
        shutil.copy(boot_img, WORK_DIR)

        print("\n[1/8] Unpacking boot image...")
        run_command([str(magiskboot_exe), "unpack", "boot.img"])
        if not (WORK_DIR / "kernel").exists():
            print("[!] Failed to unpack boot.img. The image might be invalid.")
            sys.exit(1)
        print("[+] Unpack successful.")

        print("\n[2/8] Verifying kernel version...")
        result = run_command([str(PYTHON_EXE), str(GET_KERNEL_VER_PY), "kernel"])
        target_kernel_version = result.stdout.strip()

        if not re.match(r"\d+\.\d+\.\d+", target_kernel_version):
             print(f"[!] Invalid kernel version returned from script: '{target_kernel_version}'")
             sys.exit(1)
        
        print(f"[+] Target kernel version for download: {target_kernel_version}")

        kernel_image_path = _get_gki_kernel(fetch_exe, target_kernel_version, WORK_DIR)

        print("\n[5/8] Replacing original kernel with the new one...")
        shutil.move(str(kernel_image_path), "kernel")
        print("[+] Kernel replaced.")

        print("\n[6/8] Repacking boot image...")
        run_command([str(magiskboot_exe), "repack", "boot.img"])
        if not (WORK_DIR / "new-boot.img").exists():
            print("[!] Failed to repack the boot image.")
            sys.exit(1)
        shutil.move("new-boot.img", patched_boot_path)
        print("[+] Repack successful.")

        _download_ksu_apk(fetch_exe, BASE_DIR)

    finally:
        os.chdir(original_cwd)
        if WORK_DIR.exists():
            shutil.rmtree(WORK_DIR)
        if boot_img.exists():
            boot_img.unlink()
        print("\n--- Cleaning up ---")

    if patched_boot_path.exists():
        return patched_boot_path
    return None

def convert_images():
    check_dependencies()
    
    print("--- Starting vendor_boot & vbmeta conversion process ---") 

    print("[*] Cleaning up old folders...")
    if OUTPUT_DIR.exists():
        shutil.rmtree(OUTPUT_DIR)
    print()

    print("--- Waiting for vendor_boot.img and vbmeta.img ---") 
    IMAGE_DIR.mkdir(exist_ok=True)
    required_files = ["vendor_boot.img", "vbmeta.img"]
    prompt = (
        "[STEP 1] Place the required firmware files for conversion\n"
        f"         (e.g., from your PRC firmware) into the '{IMAGE_DIR.name}' folder."
    )
    wait_for_files(IMAGE_DIR, required_files, prompt)
    
    vendor_boot_src = IMAGE_DIR / "vendor_boot.img"
    vbmeta_src = IMAGE_DIR / "vbmeta.img"

    print("--- Backing up original images ---")
    vendor_boot_bak = BASE_DIR / "vendor_boot.bak.img"
    vbmeta_bak = BASE_DIR / "vbmeta.bak.img"
    
    try:
        shutil.copy(vendor_boot_src, vendor_boot_bak)
        shutil.copy(vbmeta_src, vbmeta_bak)
        print("[+] Backup complete.\n")
    except (IOError, OSError) as e:
        print(f"[!] Failed to copy input files: {e}", file=sys.stderr)
        raise

    print("--- Starting PRC/ROW Conversion ---")
    run_command([str(PYTHON_EXE), str(EDIT_IMAGES_PY), "vndrboot", str(vendor_boot_bak)])

    vendor_boot_prc = BASE_DIR / "vendor_boot_prc.img"
    print("\n[*] Verifying conversion result...")
    if not vendor_boot_prc.exists():
        print("[!] 'vendor_boot_prc.img' was not created. No changes made.")
        raise FileNotFoundError("vendor_boot_prc.img not created")
    print("[+] Conversion to PRC successful.\n")

    print("--- Extracting image information ---")
    vbmeta_info = extract_image_avb_info(vbmeta_bak)
    vendor_boot_info = extract_image_avb_info(vendor_boot_bak)
    print("[+] Information extracted.\n")
    
    print("--- Adding Hash Footer to vendor_boot ---")
    
    for key in ['partition_size', 'name', 'rollback', 'salt']:
        if key not in vendor_boot_info:
            if key == 'partition_size' and 'data_size' in vendor_boot_info:
                 vendor_boot_info['partition_size'] = vendor_boot_info['data_size']
            else:
                raise KeyError(f"Could not find '{key}' in '{vendor_boot_bak.name}' AVB info.")

    add_hash_footer_cmd = [
        str(PYTHON_EXE), str(AVBTOOL_PY), "add_hash_footer",
        "--image", str(vendor_boot_prc),
        "--partition_size", vendor_boot_info['partition_size'],
        "--partition_name", vendor_boot_info['name'],
        "--rollback_index", vendor_boot_info['rollback'],
        "--salt", vendor_boot_info['salt']
    ]
    
    if 'props_args' in vendor_boot_info:
        add_hash_footer_cmd.extend(vendor_boot_info['props_args'])
        print(f"[+] Restoring {len(vendor_boot_info['props_args']) // 2} properties for vendor_boot.")

    if 'flags' in vendor_boot_info:
        add_hash_footer_cmd.extend(["--flags", vendor_boot_info.get('flags', '0')])
        print(f"[+] Restoring flags for vendor_boot: {vendor_boot_info.get('flags', '0')}")

    run_command(add_hash_footer_cmd)
    
    vbmeta_pubkey = vbmeta_info.get('pubkey_sha1')
    key_file = KEY_MAP.get(vbmeta_pubkey) 

    print(f"--- Remaking vbmeta.img ---")
    print("[*] Verifying vbmeta key...")
    if not key_file:
        print(f"[!] Public key SHA1 '{vbmeta_pubkey}' from vbmeta did not match known keys. Aborting.")
        raise KeyError(f"Unknown vbmeta public key: {vbmeta_pubkey}")
    print(f"[+] Matched {key_file.name}.\n")

    print("[*] Remaking 'vbmeta.img' using descriptors from backup...")
    vbmeta_img = BASE_DIR / "vbmeta.img"
    remake_cmd = [
        str(PYTHON_EXE), str(AVBTOOL_PY), "make_vbmeta_image",
        "--output", str(vbmeta_img),
        "--key", str(key_file),
        "--algorithm", vbmeta_info['algorithm'],
        "--padding_size", "8192",
        "--flags", vbmeta_info.get('flags', '0'),
        "--rollback_index", vbmeta_info.get('rollback', '0'),
        "--include_descriptors_from_image", str(vbmeta_bak),
        "--include_descriptors_from_image", str(vendor_boot_prc) 
    ]
        
    run_command(remake_cmd)
    print()

    finalize_images()

def finalize_images():
    print("--- Finalizing ---")
    print("[*] Renaming final images...")
    final_vendor_boot = BASE_DIR / "vendor_boot.img"
    shutil.move(BASE_DIR / "vendor_boot_prc.img", final_vendor_boot)

    final_images = [final_vendor_boot, BASE_DIR / "vbmeta.img"]

    print(f"\n[*] Moving final images to '{OUTPUT_DIR.name}' folder...")
    OUTPUT_DIR.mkdir(exist_ok=True)
    for img in final_images:
        if img.exists(): 
            shutil.move(img, OUTPUT_DIR / img.name)

    print(f"\n[*] Moving backup files to '{BACKUP_DIR.name}' folder...")
    BACKUP_DIR.mkdir(exist_ok=True)
    for bak_file in BASE_DIR.glob("*.bak.img"):
        shutil.move(bak_file, BACKUP_DIR / bak_file.name)
    print()

    print("=" * 61)
    print("  SUCCESS!")
    print(f"  Final images have been saved to the '{OUTPUT_DIR.name}' folder.")
    print("=" * 61)
    
def root_boot_only():
    print(f"[*] Cleaning up old '{OUTPUT_ROOT_DIR.name}' folder...")
    if OUTPUT_ROOT_DIR.exists():
        shutil.rmtree(OUTPUT_ROOT_DIR)
    OUTPUT_ROOT_DIR.mkdir(exist_ok=True)
    print()
    
    check_dependencies()

    patched_boot_path = patch_boot_with_root()

    if patched_boot_path and patched_boot_path.exists():
        print("\n--- Finalizing ---")
        final_boot_img = OUTPUT_ROOT_DIR / "boot.img"
        
        process_boot_image(patched_boot_path)

        print(f"\n[*] Moving final image to '{OUTPUT_ROOT_DIR.name}' folder...")
        shutil.move(patched_boot_path, final_boot_img)

        print(f"\n[*] Moving backup file to '{BACKUP_DIR.name}' folder...")
        BACKUP_DIR.mkdir(exist_ok=True)
        for bak_file in BASE_DIR.glob("boot.bak.img"):
            shutil.move(bak_file, BACKUP_DIR / bak_file.name)
        print()

        print("=" * 61)
        print("  SUCCESS!")
        print(f"  Patched boot.img has been saved to the '{OUTPUT_ROOT_DIR.name}' folder.")
        print("=" * 61)
    else:
        print("[!] Patched boot image was not created. An error occurred during the process.", file=sys.stderr)


def process_boot_image(image_to_process):
    print("\n[*] Verifying boot image key and metadata...") 
    boot_bak_img = BASE_DIR / "boot.bak.img"
    if not boot_bak_img.exists():
        print(f"[!] Backup file '{boot_bak_img.name}' not found. Cannot process image.", file=sys.stderr)
        raise FileNotFoundError(f"{boot_bak_img.name} not found.")
        
    boot_info = extract_image_avb_info(boot_bak_img)
    
    for key in ['partition_size', 'name', 'rollback', 'salt', 'algorithm', 'pubkey_sha1']:
        if key not in boot_info:
            raise KeyError(f"Could not find '{key}' in '{boot_bak_img.name}' AVB info.")
            
    boot_pubkey = boot_info.get('pubkey_sha1')
    key_file = KEY_MAP.get(boot_pubkey) 
    
    if not key_file:
        print(f"[!] Public key SHA1 '{boot_pubkey}' from boot.img did not match known keys. Cannot add footer.")
        raise KeyError(f"Unknown boot public key: {boot_pubkey}")

    print(f"[+] Matched {key_file.name}.")
    
    _apply_hash_footer(
        image_path=image_to_process,
        image_info=boot_info,
        key_file=key_file
    )


def edit_devinfo_persist():
    print("--- Starting devinfo & persist patching process ---")
    
    print("--- Waiting for devinfo.img / persist.img ---") 
    BACKUP_DIR.mkdir(exist_ok=True) 

    devinfo_img_src = BACKUP_DIR / "devinfo.img"
    persist_img_src = BACKUP_DIR / "persist.img"
    
    devinfo_img = BASE_DIR / "devinfo.img"
    persist_img = BASE_DIR / "persist.img"

    if not devinfo_img_src.exists() and not persist_img_src.exists():
        prompt = (
            "[STEP 1] Place 'devinfo.img' and/or 'persist.img'\n"
            f"         (e.g., from 'Dump' menu) into the '{BACKUP_DIR.name}' folder."
        )
        while not devinfo_img_src.exists() and not persist_img_src.exists():
            if platform.system() == "Windows":
                os.system('cls')
            else:
                os.system('clear')
            print("--- WAITING FOR FILES ---")
            print(prompt)
            print(f"\nPlease place at least one file in the '{BACKUP_DIR.name}' folder:")
            print(" - devinfo.img")
            print(" - persist.img")
            print("\nPress Enter when ready...")
            try:
                input()
            except EOFError:
                sys.exit(1)

    if devinfo_img_src.exists():
        shutil.copy(devinfo_img_src, devinfo_img)
        print("[+] Copied 'devinfo.img' to main directory for processing.")
    if persist_img_src.exists():
        shutil.copy(persist_img_src, persist_img)
        print("[+] Copied 'persist.img' to main directory for processing.")

    if not devinfo_img.exists() and not persist_img.exists():
        print("[!] Error: 'devinfo.img' and 'persist.img' both not found in main directory. Aborting.")
        raise FileNotFoundError("devinfo.img or persist.img not found for patching.")
        
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    backup_critical_dir = BASE_DIR / f"backup_critical_{timestamp}"
    backup_critical_dir.mkdir(exist_ok=True)
    
    print(f"[*] Backing up critical images to '{backup_critical_dir.name}'...")
    
    if devinfo_img.exists():
        shutil.copy(devinfo_img, backup_critical_dir)
        print(f"[+] Backed up '{devinfo_img.name}'.")
    if persist_img.exists():
        shutil.copy(persist_img, backup_critical_dir)
        print(f"[+] Backed up '{persist_img.name}'.")
    print("[+] Backup complete.\n")

    print(f"[*] Cleaning up old '{OUTPUT_DP_DIR.name}' folder...")
    if OUTPUT_DP_DIR.exists():
        shutil.rmtree(OUTPUT_DP_DIR)
    OUTPUT_DP_DIR.mkdir(exist_ok=True)

    print("[*] Running patch script...")
    run_command([str(PYTHON_EXE), str(EDIT_IMAGES_PY), "dp"])

    modified_devinfo = BASE_DIR / "devinfo_modified.img"
    modified_persist = BASE_DIR / "persist_modified.img"
    
    if modified_devinfo.exists():
        shutil.move(modified_devinfo, OUTPUT_DP_DIR / "devinfo.img")
    if modified_persist.exists():
        shutil.move(modified_persist, OUTPUT_DP_DIR / "persist.img")
        
    print(f"\n[*] Final images have been moved to '{OUTPUT_DP_DIR.name}' folder.")
    
    print("[*] Cleaning up original image files...")
    devinfo_img.unlink(missing_ok=True)
    persist_img.unlink(missing_ok=True)
    
    print("\n" + "=" * 61)
    print("  SUCCESS!")
    print(f"  Modified images are ready in the '{OUTPUT_DP_DIR.name}' folder.")
    print("=" * 61)


def read_edl():
    print("--- Starting EDL Read Process ---")
    
    edl_ng_exe = _ensure_edl_ng()
    
    BACKUP_DIR.mkdir(exist_ok=True)
    devinfo_out = BACKUP_DIR / "devinfo.img"
    persist_out = BACKUP_DIR / "persist.img"

    print(f"--- Waiting for EDL Loader File ---")
    required_files = [EDL_LOADER_FILENAME]
    prompt = (
        f"[STEP 1] Place the EDL loader file ('{EDL_LOADER_FILENAME}')\n"
        f"         into the '{IMAGE_DIR.name}' folder to proceed."
    )
    wait_for_files(IMAGE_DIR, required_files, prompt)
    print(f"[+] Loader file '{EDL_LOADER_FILE.name}' found in '{IMAGE_DIR.name}'.")

    wait_for_edl()
        
    print("\n[*] Attempting to read 'devinfo' partition...")
    try:
        run_command([
            str(edl_ng_exe),
            "--loader", str(EDL_LOADER_FILE), 
            "read-part", "devinfo", str(devinfo_out) 
        ])
        print(f"[+] Successfully read 'devinfo' to '{devinfo_out}'.")
    except (subprocess.CalledProcessError, FileNotFoundError) as e:
        print(f"[!] Failed to read 'devinfo': {e}", file=sys.stderr)

    print("\n[*] Attempting to read 'persist' partition...")
    try:
        run_command([
            str(edl_ng_exe),
            "--loader", str(EDL_LOADER_FILE), 
            "read-part", "persist", str(persist_out) 
        ])
        print(f"[+] Successfully read 'persist' to '{persist_out}'.")
    except (subprocess.CalledProcessError, FileNotFoundError) as e:
        print(f"[!] Failed to read 'persist': {e}", file=sys.stderr)

    print(f"\n--- EDL Read Process Finished ---")
    print(f"[*] Files have been saved to the '{BACKUP_DIR.name}' folder.")
    print(f"[*] You can now run 'Patch devinfo/persist' (Menu 3) to patch them.")


def write_edl(skip_reset=False, skip_reset_edl=False):
    print("--- Starting EDL Write Process ---")

    edl_ng_exe = _ensure_edl_ng()

    if not OUTPUT_DP_DIR.exists():
        print(f"[!] Error: Patched images folder '{OUTPUT_DP_DIR.name}' not found.", file=sys.stderr)
        print("[!] Please run 'Patch devinfo/persist' (Menu 3) first to generate the modified images.", file=sys.stderr)
        raise FileNotFoundError(f"{OUTPUT_DP_DIR.name} not found.")
    print(f"[+] Found patched images folder: '{OUTPUT_DP_DIR.name}'.")

    if not skip_reset_edl:
        print(f"--- Waiting for EDL Loader File ---")
        required_files = [EDL_LOADER_FILENAME]
        prompt = (
            f"[STEP 1] Place the EDL loader file ('{EDL_LOADER_FILENAME}')\n"
            f"         into the '{IMAGE_DIR.name}' folder to proceed."
        )
        IMAGE_DIR.mkdir(exist_ok=True) 
        wait_for_files(IMAGE_DIR, required_files, prompt)
        print(f"[+] Loader file '{EDL_LOADER_FILE.name}' found in '{IMAGE_DIR.name}'.")

        wait_for_edl()

    patched_devinfo = OUTPUT_DP_DIR / "devinfo.img"
    patched_persist = OUTPUT_DP_DIR / "persist.img"

    if not patched_devinfo.exists() and not patched_persist.exists():
         print(f"[!] Error: Neither 'devinfo.img' nor 'persist.img' found inside '{OUTPUT_DP_DIR.name}'.", file=sys.stderr)
         raise FileNotFoundError(f"No patched images found in {OUTPUT_DP_DIR.name}.")

    commands_executed = False
    
    try:
        if patched_devinfo.exists():
            print(f"\n[*] Attempting to write 'devinfo' partition with '{patched_devinfo.name}'...")
            run_command([
                str(edl_ng_exe),
                "--loader", str(EDL_LOADER_FILE), 
                "write-part", "devinfo", str(patched_devinfo)
            ])
            print("[+] Successfully wrote 'devinfo'.")
            commands_executed = True
        else:
            print(f"\n[*] 'devinfo.img' not found in '{OUTPUT_DP_DIR.name}'. Skipping write.")

        if patched_persist.exists():
            print(f"\n[*] Attempting to write 'persist' partition with '{patched_persist.name}'...")
            run_command([
                str(edl_ng_exe),
                "--loader", str(EDL_LOADER_FILE), 
                "write-part", "persist", str(patched_persist)
            ])
            print("[+] Successfully wrote 'persist'.")
            commands_executed = True
        else:
            print(f"\n[*] 'persist.img' not found in '{OUTPUT_DP_DIR.name}'. Skipping write.")

        if commands_executed and not skip_reset:
            print("\n[*] Operations complete. Resetting device...")
            run_command([
                str(edl_ng_exe),
                "--loader", str(EDL_LOADER_FILE), 
                "reset"
            ])
            print("[+] Device reset command sent.")
        elif skip_reset:
            print("\n[*] Operations complete. Skipping device reset as requested.")
        else:
            print("\n[!] No partitions were written. Skipping reset.")

    except (subprocess.CalledProcessError, FileNotFoundError) as e:
        print(f"[!] An error occurred during the EDL write/reset operation: {e}", file=sys.stderr)
        raise

    if not skip_reset:
        print("\n" + "="*61)
        print("  FRIENDLY REMINDER:")
        print("  Please ensure you have a safe backup of your original")
        print("  'devinfo.img' and 'persist.img' files before proceeding")
        print("  with any manual flashing operations.")
        print("="*61)

    print("\n--- EDL Write Process Finished ---")


def show_image_info(files):
    all_files = []
    for f in files:
        path = Path(f)
        if path.is_dir():
            all_files.extend(path.rglob('*.img'))
        elif path.is_file():
            all_files.append(path)

    if not all_files:
        print("No .img files found in the provided paths.")
        return
        
    output_lines = [
        "\n" + "=" * 42,
        "  Sorted and Processing Images...",
        "=" * 42 + "\n"
    ]
    print("\n".join(output_lines))

    for file_path in sorted(all_files):
        info_header = f"Processing file: {file_path}\n---------------------------------" 
        print(info_header)
        output_lines.append(info_header)

        if not file_path.exists():
            not_found_msg = f"File not found: {file_path}"
            print(not_found_msg)
            output_lines.append(not_found_msg)
            continue

        try:
            process = run_command(
                [str(PYTHON_EXE), str(AVBTOOL_PY), "info_image", "--image", str(file_path)],
            )
            output_lines.append(process.stdout.strip())
        except (subprocess.CalledProcessError) as e:
            error_message = f"Failed to get info from {file_path.name}"
            print(error_message, file=sys.stderr)
            if e.stderr:
                print(e.stderr.strip(), file=sys.stderr)
            output_lines.append(error_message)
        finally:
            output_lines.append("---------------------------------\n")

    try:
        timestamp = datetime.now().strftime("%Y-%m-%d_%H%M%S")
        output_filename = BASE_DIR / f"image_info_{timestamp}.txt"
        with open(output_filename, "w", encoding="utf-8") as f:
            f.write("\n".join(output_lines))
        print(f"[*] Image info saved to: {output_filename}")
    except IOError as e:
        print(f"[!] Error saving info to file: {e}", file=sys.stderr)

def patch_chained_image_rollback(image_name, current_rb_index, new_image_path, patched_image_path):
    try:
        print(f"[*] Analyzing new {image_name}...")
        info = extract_image_avb_info(new_image_path)
        new_rb_index = int(info.get('rollback', '0'))
        print(f"  > New index: {new_rb_index}")

        if new_rb_index >= current_rb_index:
            print(f"[*] {image_name} index is OK. Copying as is.")
            shutil.copy(new_image_path, patched_image_path)
            return

        print(f"[!] Anti-Rollback Bypassed: Patching {image_name} from {new_rb_index} to {current_rb_index}...")
        
        for key in ['partition_size', 'name', 'salt', 'algorithm', 'pubkey_sha1']:
            if key not in info:
                raise KeyError(f"Could not find '{key}' in '{new_image_path.name}' AVB info.")
        
        key_file = KEY_MAP.get(info['pubkey_sha1']) 
        if not key_file:
            raise KeyError(f"Unknown public key SHA1 {info['pubkey_sha1']} in {new_image_path.name}")
        
        shutil.copy(new_image_path, patched_image_path)
        
        _apply_hash_footer(
            image_path=patched_image_path,
            image_info=info,
            key_file=key_file,
            new_rollback_index=str(current_rb_index)
        )

    except (KeyError, subprocess.CalledProcessError, FileNotFoundError) as e:
        print(f"[!] Error processing {image_name}: {e}", file=sys.stderr)
        raise

def patch_vbmeta_image_rollback(image_name, current_rb_index, new_image_path, patched_image_path):
    try:
        print(f"[*] Analyzing new {image_name}...")
        info = extract_image_avb_info(new_image_path)
        new_rb_index = int(info.get('rollback', '0'))
        print(f"  > New index: {new_rb_index}")

        if new_rb_index >= current_rb_index:
            print(f"[*] {image_name} index is OK. Copying as is.")
            shutil.copy(new_image_path, patched_image_path)
            return

        print(f"[!] Anti-Rollback Bypassed: Patching {image_name} from {new_rb_index} to {current_rb_index}...")

        for key in ['algorithm', 'pubkey_sha1']:
            if key not in info:
                raise KeyError(f"Could not find '{key}' in '{new_image_path.name}' AVB info.")
        
        key_file = KEY_MAP.get(info['pubkey_sha1']) 
        if not key_file:
            raise KeyError(f"Unknown public key SHA1 {info['pubkey_sha1']} in {new_image_path.name}")

        remake_cmd = [
            str(PYTHON_EXE), str(AVBTOOL_PY), "make_vbmeta_image",
            "--output", str(patched_image_path),
            "--key", str(key_file),
            "--algorithm", info['algorithm'],
            "--rollback_index", str(current_rb_index),
            "--flags", info.get('flags', '0'),
            "--include_descriptors_from_image", str(new_image_path)
        ]
        
        run_command(remake_cmd)
        print(f"[+] Successfully patched {image_name}.")

    except (KeyError, subprocess.CalledProcessError, FileNotFoundError) as e:
        print(f"[!] Error processing {image_name}: {e}", file=sys.stderr)
        raise

def _compare_rollback_indices(edl_ng_exe):
    print("\n--- [STEP 1] Dumping Current Firmware via EDL ---")
    INPUT_CURRENT_DIR.mkdir(exist_ok=True)
    boot_out = INPUT_CURRENT_DIR / "boot.img"
    vbmeta_out = INPUT_CURRENT_DIR / "vbmeta_system.img"

    print(f"--- Waiting for EDL Loader File ---")
    required_loader = [EDL_LOADER_FILENAME]
    loader_prompt = (
        f"[REQUIRED] Place the EDL loader file ('{EDL_LOADER_FILENAME}')\n"
        f"         into the '{IMAGE_DIR.name}' folder to dump current firmware."
    )
    wait_for_files(IMAGE_DIR, required_loader, loader_prompt)
    print(f"[+] Loader file '{EDL_LOADER_FILE.name}' found in '{IMAGE_DIR.name}'.")

    wait_for_edl()
        
    print("\n[*] Attempting to read 'boot' partition...")
    try:
        run_command([
            str(edl_ng_exe),
            "--loader", str(EDL_LOADER_FILE), 
            "read-part", "boot", str(boot_out) 
        ])
        print(f"[+] Successfully read 'boot' to '{boot_out}'.")
    except (subprocess.CalledProcessError, FileNotFoundError) as e:
        print(f"[!] Failed to read 'boot': {e}", file=sys.stderr)
        raise 

    print("\n[*] Attempting to read 'vbmeta_system' partition...")
    try:
        run_command([
            str(edl_ng_exe),
            "--loader", str(EDL_LOADER_FILE), 
            "read-part", "vbmeta_system", str(vbmeta_out) 
        ])
        print(f"[+] Successfully read 'vbmeta_system' to '{vbmeta_out}'.")
    except (subprocess.CalledProcessError, FileNotFoundError) as e:
        print(f"[!] Failed to read 'vbmeta_system': {e}", file=sys.stderr)
        raise 
        
    print("\n--- [STEP 1] Dump complete ---")
    
    print("\n--- [STEP 2] Comparing Rollback Indices ---")
    print("\n[*] Extracting current firmware rollback indices...")
    current_boot_rb = 0
    current_vbmeta_rb = 0
    try:
        current_boot_info = extract_image_avb_info(INPUT_CURRENT_DIR / "boot.img")
        current_boot_rb = int(current_boot_info.get('rollback', '0'))
        
        current_vbmeta_info = extract_image_avb_info(INPUT_CURRENT_DIR / "vbmeta_system.img")
        current_vbmeta_rb = int(current_vbmeta_info.get('rollback', '0'))
    except Exception as e:
        print(f"[!] Error reading current image info: {e}. Please check files.", file=sys.stderr)
        return 'ERROR', 0, 0

    print(f"  > Current Boot Index: {current_boot_rb}")
    print(f"  > Current VBMeta System Index: {current_vbmeta_rb}")

    print("\n[*] Extracting new firmware rollback indices (from 'image' folder)...")
    new_boot_img = IMAGE_DIR / "boot.img"
    new_vbmeta_img = IMAGE_DIR / "vbmeta_system.img"

    if not new_boot_img.exists() or not new_vbmeta_img.exists():
        print(f"[!] Error: 'boot.img' or 'vbmeta_system.img' not found in '{IMAGE_DIR.name}' folder.")
        return 'MISSING_NEW', 0, 0
        
    new_boot_rb = 0
    new_vbmeta_rb = 0
    try:
        new_boot_info = extract_image_avb_info(new_boot_img)
        new_boot_rb = int(new_boot_info.get('rollback', '0'))
        
        new_vbmeta_info = extract_image_avb_info(new_vbmeta_img)
        new_vbmeta_rb = int(new_vbmeta_info.get('rollback', '0'))
    except Exception as e:
        print(f"[!] Error reading new image info: {e}. Please check files.", file=sys.stderr)
        return 'ERROR', 0, 0

    print(f"  > New Boot Index: {new_boot_rb}")
    print(f"  > New VBMeta System Index: {new_vbmeta_rb}")

    if new_boot_rb < current_boot_rb or new_vbmeta_rb < current_vbmeta_rb:
        print("\n[!] Downgrade detected! Anti-Rollback patching is REQUIRED.")
        return 'NEEDS_PATCH', current_boot_rb, current_vbmeta_rb
    else:
        print("\n[+] Indices are same or higher. No Anti-Rollback patch needed.")
        return 'MATCH', 0, 0

def read_anti_rollback():
    print("--- Anti-Rollback Status Check ---")
    check_dependencies()
    edl_ng_exe = _ensure_edl_ng()
    
    try:
        status, _, _ = _compare_rollback_indices(edl_ng_exe)
        print(f"\n--- Status Check Complete: {status} ---")
    except Exception as e:
        print(f"\n[!] An error occurred during status check: {e}", file=sys.stderr)

def patch_anti_rollback():
    print("--- Anti-Rollback Patcher ---")
    check_dependencies()
    edl_ng_exe = _ensure_edl_ng()

    if OUTPUT_ANTI_ROLLBACK_DIR.exists():
        shutil.rmtree(OUTPUT_ANTI_ROLLBACK_DIR)
    OUTPUT_ANTI_ROLLBACK_DIR.mkdir(exist_ok=True)
    
    try:
        status, current_boot_rb, current_vbmeta_rb = _compare_rollback_indices(edl_ng_exe)

        if status != 'NEEDS_PATCH':
            print("\n[!] No patching is required or files are missing. Aborting patch.")
            return

        print("\n--- [STEP 3] Patching New Firmware ---")
        
        patch_chained_image_rollback(
            image_name="boot.img",
            current_rb_index=current_boot_rb,
            new_image_path=(IMAGE_DIR / "boot.img"),
            patched_image_path=(OUTPUT_ANTI_ROLLBACK_DIR / "boot.img")
        )
        
        print("-" * 20)
        
        patch_vbmeta_image_rollback(
            image_name="vbmeta_system.img",
            current_rb_index=current_vbmeta_rb,
            new_image_path=(IMAGE_DIR / "vbmeta_system.img"),
            patched_image_path=(OUTPUT_ANTI_ROLLBACK_DIR / "vbmeta_system.img")
        )

        print("\n" + "=" * 61)
        print("  SUCCESS!")
        print(f"  Anti-rollback patched images are in '{OUTPUT_ANTI_ROLLBACK_DIR.name}'.")
        print("  You can now run 'Write Anti-Rollback' (Menu 8).")
        print("=" * 61)

    except Exception as e:
        print(f"\n[!] An error occurred during patching: {e}", file=sys.stderr)
        shutil.rmtree(OUTPUT_ANTI_ROLLBACK_DIR) 

def write_anti_rollback(skip_reset=False):
    print("--- Starting Anti-Rollback Write Process ---")

    edl_ng_exe = _ensure_edl_ng()

    boot_img = OUTPUT_ANTI_ROLLBACK_DIR / "boot.img"
    vbmeta_img = OUTPUT_ANTI_ROLLBACK_DIR / "vbmeta_system.img"

    if not boot_img.exists() or not vbmeta_img.exists():
        print(f"[!] Error: Patched images not found in '{OUTPUT_ANTI_ROLLBACK_DIR.name}'.", file=sys.stderr)
        print("[!] Please run 'Patch Anti-Rollback' (Menu 7) first.", file=sys.stderr)
        raise FileNotFoundError(f"Patched images not found in {OUTPUT_ANTI_ROLLBACK_DIR.name}")
    print(f"[+] Found patched images folder: '{OUTPUT_ANTI_ROLLBACK_DIR.name}'.")

    if not skip_reset:
        print(f"--- Waiting for EDL Loader File ---")
        required_files = [EDL_LOADER_FILENAME]
        prompt = (
            f"[STEP 1] Place the EDL loader file ('{EDL_LOADER_FILENAME}')\n"
            f"         into the '{IMAGE_DIR.name}' folder to proceed."
        )
        IMAGE_DIR.mkdir(exist_ok=True) 
        wait_for_files(IMAGE_DIR, required_files, prompt)
        print(f"[+] Loader file '{EDL_LOADER_FILE.name}' found in '{IMAGE_DIR.name}'.")

        wait_for_edl()
    
    try:
        print(f"\n[*] Attempting to write 'boot' partition...")
        run_command([
            str(edl_ng_exe),
            "--loader", str(EDL_LOADER_FILE), 
            "write-part", "boot", str(boot_img)
        ])
        print("[+] Successfully wrote 'boot'.")

        print(f"\n[*] Attempting to write 'vbmeta_system' partition...")
        run_command([
            str(edl_ng_exe),
            "--loader", str(EDL_LOADER_FILE), 
            "write-part", "vbmeta_system", str(vbmeta_img)
        ])
        print("[+] Successfully wrote 'vbmeta_system'.")

        if not skip_reset:
            print("\n[*] Operations complete. Resetting device...")
            run_command([
                str(edl_ng_exe),
                "--loader", str(EDL_LOADER_FILE), 
                "reset"
            ])
            print("[+] Device reset command sent.")
        else:
            print("\n[*] Operations complete. Skipping device reset as requested.")

    except (subprocess.CalledProcessError, FileNotFoundError) as e:
        print(f"[!] An error occurred during the EDL write operation: {e}", file=sys.stderr)
        raise
    
    print("\n--- Anti-Rollback Write Process Finished ---")


def clean_workspace():
    print("--- Starting Cleanup Process ---")
    print("This will remove all input/output folders and downloaded tools.")
    print("The 'python3' and 'backup' folders will NOT be removed.")
    print("-" * 50)

    folders_to_remove = [
        INPUT_CURRENT_DIR, INPUT_NEW_DIR,
        OUTPUT_DIR, OUTPUT_ROOT_DIR, OUTPUT_DP_DIR, OUTPUT_ANTI_ROLLBACK_DIR,
        WORK_DIR,
        AVB_DIR,
        IMAGE_DIR,
        WORKING_DIR,
        OUTPUT_XML_DIR
    ]
    
    print("[*] Removing directories...")
    for folder in folders_to_remove:
        if folder.exists():
            try:
                shutil.rmtree(folder)
                print(f"  > Removed: {folder.name}{os.sep}")
            except OSError as e:
                print(f"[!] Error removing {folder.name}: {e}", file=sys.stderr)
        else:
            print(f"  > Skipping (not found): {folder.name}{os.sep}")

    print("\n[*] Removing downloaded tools from 'tools' folder...")
    tools_files_to_remove = [
        "fetch.exe", "fetch-linux", "fetch-macos",
        "magiskboot.exe", "magiskboot-linux", "magiskboot-macos",
        "edl-ng.exe",
        "magiskboot-*.zip",
        "edl-ng-*.zip"
    ]
    
    cleaned_tools_files = 0
    for pattern in tools_files_to_remove:
        for f in TOOLS_DIR.glob(pattern):
            try:
                f.unlink()
                print(f"  > Removed tool: {f.name}")
                cleaned_tools_files += 1
            except OSError as e:
                print(f"[!] Error removing {f.name}: {e}", file=sys.stderr)
    
    if cleaned_tools_files == 0:
        print("  > No downloaded tools found to clean.")

    print("\n[*] Cleaning up temporary files from root directory...")
    file_patterns_to_remove = [
        "*.bak.img",
        "*.root.img",
        "*prc.img",
        "*modified.img",
        "image_info_*.txt",
        "KernelSU*.apk",
        "devinfo.img", 
        "persist.img", 
        "boot.img", 
        "vbmeta.img" 
    ]
    
    cleaned_root_files = 0
    for pattern in file_patterns_to_remove:
        for f in BASE_DIR.glob(pattern):
            try:
                f.unlink()
                print(f"  > Removed: {f.name}")
                cleaned_root_files += 1
            except OSError as e:
                print(f"[!] Error removing {f.name}: {e}", file=sys.stderr)
    
    if cleaned_root_files == 0:
        print("  > No temporary files found to clean.")

    print("\n--- Cleanup Finished ---")

def modify_xml():
    print("--- Starting XML Modification Process ---")

    if not DECRYPT_PY.exists():
        print(f"[!] Error: Decryption script not found at '{DECRYPT_PY}'")
        print("[!] Please ensure 'decrypt_x.py' is in the 'tools' folder.")
        sys.exit(1)
        
    print("--- Waiting for 'image' folder ---")
    prompt = (
        "[STEP 1] Please copy the entire 'image' folder from your\n"
        "         unpacked Lenovo RSA firmware into the main directory."
    )
    wait_for_directory(IMAGE_DIR, prompt)

    if WORKING_DIR.exists():
        shutil.rmtree(WORKING_DIR)
    if OUTPUT_XML_DIR.exists():
        shutil.rmtree(OUTPUT_XML_DIR)
    
    WORKING_DIR.mkdir()
    print(f"\n[*] Created temporary '{WORKING_DIR.name}' folder.")

    print("[*] Decrypting *.x files and moving to 'working' folder...")
    xml_files = []
    for file in IMAGE_DIR.glob("*.x"):
        out_file = WORKING_DIR / file.with_suffix('.xml').name
        try:
            run_command([str(PYTHON_EXE), str(DECRYPT_PY), str(file), str(out_file)])
            print(f"  > Decrypted: {file.name} -> {out_file.name}")
            xml_files.append(out_file)
        except Exception as e:
            print(f"[!] Failed to decrypt {file.name}: {e}", file=sys.stderr)
            
    if not xml_files:
        print(f"[!] No '*.x' files found in '{IMAGE_DIR.name}'. Aborting.")
        shutil.rmtree(WORKING_DIR)
        raise FileNotFoundError(f"No *.x files found in {IMAGE_DIR.name}")

    print("\n[*] Modifying 'contents.xml'...")
    contents_xml = WORKING_DIR / "contents.xml"
    if contents_xml.exists():
        try:
            with open(contents_xml, 'r', encoding='utf-8') as f:
                content = f.read()
            content = content.replace("rawprogram_unsparse4.xml", "rawprogram4.xml")
            content = content.replace("rawprogram_unsparse0.xml", "rawprogram_save_persist_unsparse0.xml")
            with open(contents_xml, 'w', encoding='utf-8') as f:
                f.write(content)
            print("  > Patched 'contents.xml' successfully.")
        except Exception as e:
            print(f"[!] Error patching 'contents.xml': {e}", file=sys.stderr)
    else:
        print("  > 'contents.xml' not found. Skipping.")

    print("\n[*] Modifying 'rawprogram_save_persist_unsparse0.xml'...")
    rawprogram_save = WORKING_DIR / "rawprogram_save_persist_unsparse0.xml"
    if rawprogram_save.exists():
        try:
            with open(rawprogram_save, 'r', encoding='utf-8') as f:
                content = f.read()
            
            for i in range(1, 11):
                content = content.replace(f'filename="metadata_{i}.img"', '')
            for i in range(1, 21):
                content = content.replace(f'filename="userdata_{i}.img"', '')
                
            with open(rawprogram_save, 'w', encoding='utf-8') as f:
                f.write(content)
            print("  > Patched 'rawprogram_save_persist_unsparse0.xml' successfully.")
        except Exception as e:
            print(f"[!] Error patching 'rawprogram_save_persist_unsparse0.xml': {e}", file=sys.stderr)
    else:
        print("  > 'rawprogram_save_persist_unsparse0.xml' not found. Skipping.")

    print("\n[*] Modifying 'rawprogram4.xml'...")
    rawprogram4 = WORKING_DIR / "rawprogram4.xml"
    if rawprogram4.exists():
        try:
            with open(rawprogram4, 'r', encoding='utf-8') as f:
                content = f.read()
            content = content.replace('filename="vm-bootsys.img"', '')
            content = content.replace('filename="vm-persist.img"', '')
            with open(rawprogram4, 'w', encoding='utf-8') as f:
                f.write(content)
            print("  > Patched 'rawprogram4.xml' successfully.")
        except Exception as e:
            print(f"[!] Error patching 'rawprogram4.xml': {e}", file=sys.stderr)
    else:
        print("  > 'rawprogram4.xml' not found. Skipping.")

    print("\n[*] Deleting unnecessary XML files...")
    files_to_delete = [
        WORKING_DIR / "rawprogram_unsparse0.xml",
        *WORKING_DIR.glob("*_WIPE_PARTITIONS.xml"),
        *WORKING_DIR.glob("*_BLANK_GPT.xml")
    ]
    for f in files_to_delete:
        if f.exists():
            f.unlink()
            print(f"  > Deleted: {f.name}")

    shutil.move(WORKING_DIR, OUTPUT_XML_DIR)
    print(f"\n[*] Renamed '{WORKING_DIR.name}' to '{OUTPUT_XML_DIR.name}'.")
    
    print("\n" + "=" * 61)
    print("  SUCCESS!")
    print(f"  Modified XML files are ready in the '{OUTPUT_XML_DIR.name}'.")
    print("  You can now run 'Flash EDL' (Menu 10).")
    print("=" * 61)

def flash_edl(skip_reset=False, skip_reset_edl=False):
    print("--- Starting Full EDL Flash Process ---")
    
    edl_ng_exe = _ensure_edl_ng()

    if not IMAGE_DIR.is_dir() or not any(IMAGE_DIR.iterdir()):
        print(f"[!] Error: The '{IMAGE_DIR.name}' folder is missing or empty.")
        print("[!] Please run 'Modify XML for Update' (Menu 9) first.")
        raise FileNotFoundError(f"{IMAGE_DIR.name} is missing or empty.")
        
    loader_path = EDL_LOADER_FILE_IMAGE
    if not loader_path.exists():
        print(f"[!] Error: EDL Loader '{loader_path.name}' not found in '{IMAGE_DIR.name}' folder.")
        print("[!] Please copy it to the 'image' folder (from firmware).")
        raise FileNotFoundError(f"{loader_path.name} not found in {IMAGE_DIR.name}")

    if not skip_reset_edl:
        print("\n" + "="*61)
        print("  WARNING: PROCEEDING WILL OVERWRITE FILES IN YOUR 'image'")
        print("           FOLDER WITH ANY PATCHED FILES YOU HAVE CREATED")
        print("           (e.g., from Menu 1, 5, 7, or 9).")
        print("="*61 + "\n")
        
        choice = ""
        while choice not in ['y', 'n']:
            choice = input("Are you sure you want to continue? (y/n): ").lower().strip()

        if choice == 'n':
            print("[*] Operation cancelled.")
            return

    print("\n[*] Copying patched files to 'image' folder (overwriting)...")
    output_folders_to_copy = [
        OUTPUT_DIR, 
        OUTPUT_ROOT_DIR, 
        OUTPUT_ANTI_ROLLBACK_DIR,
        OUTPUT_XML_DIR 
    ]
    
    copied_count = 0
    for folder in output_folders_to_copy:
        if folder.exists():
            try:
                shutil.copytree(folder, IMAGE_DIR, dirs_exist_ok=True)
                print(f"  > Copied contents of '{folder.name}' to '{IMAGE_DIR.name}'.")
                copied_count += 1
            except Exception as e:
                print(f"[!] Error copying files from {folder.name}: {e}", file=sys.stderr)
    
    if copied_count == 0:
        print("[*] No 'output*' folders found. Proceeding with files already in 'image' folder.")
    
    wait_for_edl()
    
    print("\n--- [STEP 1] Flashing main firmware via rawprogram ---")
    raw_xmls = list(IMAGE_DIR.glob("rawprogram*.xml"))
    patch_xmls = list(IMAGE_DIR.glob("patch*.xml"))
    
    if not raw_xmls:
        print(f"[!] No 'rawprogram*.xml' files found in '{IMAGE_DIR.name}'. Cannot flash.")
        raise FileNotFoundError(f"No rawprogram*.xml found in {IMAGE_DIR.name}")
        
    cmd = [
        str(edl_ng_exe), 
        "--loader", str(loader_path), 
        "--memory", "UFS", 
        "rawprogram", 
        *[str(p) for p in raw_xmls], 
        *[str(p) for p in patch_xmls]
    ]
    
    try:
        run_command(cmd)
    except (subprocess.CalledProcessError, FileNotFoundError) as e:
        print(f"[!] An error occurred during main flash: {e}", file=sys.stderr)
        print("[!] The device may be in an unstable state. Do not reboot manually.")
        raise
        
    print("\n--- [STEP 2] Flashing patched devinfo/persist ---")
    
    patched_devinfo = OUTPUT_DP_DIR / "devinfo.img"
    patched_persist = OUTPUT_DP_DIR / "persist.img"

    if not OUTPUT_DP_DIR.exists() or (not patched_devinfo.exists() and not patched_persist.exists()):
        print(f"[*] '{OUTPUT_DP_DIR.name}' not found or is empty. Skipping devinfo/persist flash.")
    else:
        print("[*] 'output_dp' folder found. Proceeding to flash devinfo/persist...")
        
        if not skip_reset_edl:
            print("\n[*] Resetting device back into EDL mode for devinfo/persist flash...")
            try:
                run_command([
                    str(edl_ng_exe),
                    "--loader", str(loader_path), 
                    "reset", "edl"
                ])
                print("[+] Device reset-to-EDL command sent.")
            except Exception as e:
                 print(f"[!] Failed to reset device to EDL: {e}", file=sys.stderr)
                 print("[!] Please manually reboot to EDL mode.")
            
            wait_for_edl() 
        
        write_edl(skip_reset=True, skip_reset_edl=True)

    print("\n--- [STEP 3] Flashing patched Anti-Rollback images ---")
    arb_boot = OUTPUT_ANTI_ROLLBACK_DIR / "boot.img"
    arb_vbmeta = OUTPUT_ANTI_ROLLBACK_DIR / "vbmeta_system.img"

    if not OUTPUT_ANTI_ROLLBACK_DIR.exists() or (not arb_boot.exists() and not arb_vbmeta.exists()):
        print(f"[*] '{OUTPUT_ANTI_ROLLBACK_DIR.name}' not found or is empty. Skipping Anti-Rollback flash.")
    else:
        print(f"[*] '{OUTPUT_ANTI_ROLLBACK_DIR.name}' found. Proceeding to flash Anti-Rollback images...")
        if skip_reset_edl:
             print("[*] Assuming device is still in EDL mode from previous step...")
        else:
            print("\n[!] CRITICAL: This flow is not intended to be run manually.")
            print("[!] Please use the 'Patch and Flash' (Menu 1) option.")
            
        write_anti_rollback(skip_reset=True)

    if not skip_reset:
        print("\n[*] Final step: Resetting device to system...")
        try:
            run_command([
                str(edl_ng_exe),
                "--loader", str(loader_path), 
                "reset"
            ])
            print("[+] Device reset command sent.")
        except Exception as e:
             print(f"[!] Failed to reset device: {e}", file=sys.stderr)
    else:
        print("[*] Skipping final device reset as requested.")

    if not skip_reset:
        print("\n--- Full EDL Flash Process Finished ---")

def patch_all():
    print("--- Starting Automated Patch & Flash ROW ROM Process ---")
    
    print("\n--- [STEP 1/7] Waiting for RSA Firmware 'image' folder ---")
    prompt = (
        "Please copy the entire 'image' folder from your\n"
        "         unpacked Lenovo RSA firmware into the main directory.\n"
        r"         (Typical Location: C:\ProgramData\RSA\Download\RomFiles\...)"
    )
    wait_for_directory(IMAGE_DIR, prompt)
    print("[+] 'image' folder found.")
    
    try:
        print("\n" + "="*61)
        print("  STEP 2/7: Converting ROM (PRC to ROW)")
        print("="*61)
        convert_images()
        print("\n--- [STEP 2/7] ROM Conversion SUCCESS ---")

        print("\n" + "="*61)
        print("  STEP 3/7: Modifying XML Files")
        print("="*61)
        modify_xml()
        print("\n--- [STEP 3/7] XML Modification SUCCESS ---")
        
        print("\n" + "="*61)
        print("  STEP 4/7: Dumping devinfo/persist for patching")
        print("="*61)
        read_edl()
        print("\n--- [STEP 4/7] Dump SUCCESS ---")
        
        print("\n" + "="*61)
        print("  STEP 5/7: Patching devinfo/persist")
        print("="*61)
        edit_devinfo_persist()
        print("\n--- [STEP 5/7] Patching SUCCESS ---")
        
        print("\n" + "="*61)
        print("  STEP 6/7: Checking and Patching Anti-Rollback")
        print("="*61)
        read_anti_rollback()
        patch_anti_rollback()
        print("\n--- [STEP 6/7] Anti-Rollback Check/Patch SUCCESS ---")
        
        print("\n" + "="*61)
        print("  [FINAL STEP] Flashing All Images via EDL")
        print("="*61)
        print("The device will now be flashed with all modified images.")
        flash_edl(skip_reset_edl=True) 
        
        print("\n" + "=" * 61)
        print("  FULL PROCESS COMPLETE!")
        print("  Your device should now reboot with a patched ROW ROM.")
        print("=" * 61)

    except (subprocess.CalledProcessError, FileNotFoundError, RuntimeError, KeyError) as e:
        print("\n" + "!" * 61)
        print("  AN ERROR OCCURRED: Process Halted.")
        print(f"  Error details: {e}")
        print("!" * 61)
        sys.exit(1)
    except SystemExit:
        print("\n" + "!" * 61)
        print("  PROCESS HALTED BY SCRIPT.")
        print("!" * 61)
    except KeyboardInterrupt:
        print("\n" + "!" * 61)
        print("  PROCESS CANCELLED BY USER.")
        print("!" * 61)


def main():
    parser = argparse.ArgumentParser(description="Android Image Patcher and AVB Tool.")
    subparsers = parser.add_subparsers(dest="command", required=True, help="Available commands")

    subparsers.add_parser("convert", help="Convert vendor_boot region and remake vbmeta.")
    subparsers.add_parser("root", help="Patch boot.img with KernelSU.")
    subparsers.add_parser("edit_dp", help="Edit devinfo and persist images.")
    subparsers.add_parser("read_edl", help="Read devinfo and persist images via EDL.")
    subparsers.add_parser("write_edl", help="Write patched devinfo and persist images via EDL.")
    subparsers.add_parser("read_anti_rollback", help="Read and Compare Anti-Rollback indices.")
    subparsers.add_parser("patch_anti_rollback", help="Patch firmware images to bypass Anti-Rollback.")
    subparsers.add_parser("write_anti_rollback", help="Flash patched Anti-Rollback images via EDL.")
    subparsers.add_parser("clean", help="Remove downloaded tools, I/O folders, and temp files.")
    subparsers.add_parser("modify_xml", help="Modify XML files from RSA firmware for flashing.")
    subparsers.add_parser("flash_edl", help="Flash the entire modified firmware via EDL.")
    subparsers.add_parser("patch_all", help="Run the full automated ROW flashing process.")
    parser_info = subparsers.add_parser("info", help="Display AVB info for image files or directories.")
    parser_info.add_argument("files", nargs='+', help="Image file(s) or folder(s) to inspect.")

    args = parser.parse_args()

    try:
        if args.command == "convert":
            convert_images()
        elif args.command == "root":
            root_boot_only()
        elif args.command == "edit_dp":
            edit_devinfo_persist()
        elif args.command == "read_edl":
            read_edl()
        elif args.command == "write_edl":
            write_edl()
        elif args.command == "read_anti_rollback":
            read_anti_rollback()
        elif args.command == "patch_anti_rollback":
            patch_anti_rollback()
        elif args.command == "write_anti_rollback":
            write_anti_rollback()
        elif args.command == "clean":
            clean_workspace()
        elif args.command == "modify_xml":
            modify_xml()
        elif args.command == "flash_edl":
            flash_edl()
        elif args.command == "patch_all":
            patch_all()
        elif args.command == "info":
            show_image_info(args.files)
    except (subprocess.CalledProcessError, FileNotFoundError, RuntimeError, KeyError) as e:
        if not isinstance(e, SystemExit):
            print(f"\nAn unexpected error occurred: {e}", file=sys.stderr)
    except SystemExit:
        print("\nProcess halted by script (e.g., file not found).", file=sys.stderr)
    except KeyboardInterrupt:
        print("\nProcess cancelled by user.", file=sys.stderr)


    finally:
        print()
        if platform.system() == "Windows":
            os.system("pause")

if __name__ == "__main__":
    main()
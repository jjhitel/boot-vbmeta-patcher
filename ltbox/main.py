import argparse
import logging
import os
import platform
import subprocess
import sys
from contextlib import contextmanager
from pathlib import Path
from datetime import datetime

sys.path.insert(0, str(Path(__file__).parent.parent.resolve()))

if platform.system() == "Windows":
    import ctypes

try:
    from ltbox import utils, actions, workflow
    from ltbox import constants, imgpatch
except ImportError as e:
    print(f"[!] Error: Failed to import 'ltbox' package.", file=sys.stderr)
    print(f"[!] Details: {e}", file=sys.stderr)
    print(f"[!] Please ensure the 'ltbox' folder and its files are present.", file=sys.stderr)
    if platform.system() == "Windows":
        os.system("pause")
    sys.exit(1)

COMMAND_MAP = {
    "convert": (actions.convert_images, {}),
    "root_device": (actions.root_device, {"skip_adb": True}),
    "unroot_device": (actions.unroot_device, {"skip_adb": True}),
    "disable_ota": (actions.disable_ota, {"skip_adb": True}),
    "edit_dp": (actions.edit_devinfo_persist, {}),
    "read_edl": (actions.read_edl, {"skip_adb": True}),
    "write_edl": (actions.write_edl, {}),
    "read_anti_rollback": (actions.read_anti_rollback, {}),
    "patch_anti_rollback": (actions.patch_anti_rollback, {}),
    "write_anti_rollback": (actions.write_anti_rollback, {}),
    "clean": (utils.clean_workspace, {}),
    "modify_xml": (actions.modify_xml, {"wipe": 0}),
    "modify_xml_wipe": (actions.modify_xml, {"wipe": 1}),
    "flash_edl": (actions.flash_edl, {}),
    "patch_all": (workflow.patch_all, {"wipe": 0, "skip_adb": True}),
    "patch_all_wipe": (workflow.patch_all, {"wipe": 1, "skip_adb": True}),
}

def setup_console():
    system = platform.system()
    if system == "Windows":
        try:
            ctypes.windll.kernel32.SetConsoleTitleW(u"LTBox")
        except Exception as e:
            print(f"[!] Warning: Failed to set console title: {e}", file=sys.stderr)

def check_path_encoding():
    current_path = str(Path(__file__).parent.parent.resolve())
    if not current_path.isascii():
        os.system('cls' if os.name == 'nt' else 'clear')
        print("\n" + "!" * 65)
        print("  CRITICAL ERROR: NON-ASCII CHARACTERS DETECTED IN PATH")
        print("  " + "-" * 60)
        print(f"  Current Path: {current_path}")
        print("  " + "-" * 60)
        print("  The underlying Qualcomm tools (fh_loader) do not support")
        print("  paths containing Korean or other non-English characters.")
        print("\n  [ACTION REQUIRED]")
        print("  Please move the 'LTBox' folder to a simple English path.")
        print("  Example: C:\\LTBox")
        print("!" * 65 + "\n")
        
        if platform.system() == "Windows":
            os.system("pause")
        else:
            input("Press Enter to exit...")
        sys.exit(1)

@contextmanager
def capture_output_to_log(log_filename):
    """
    Redirects stdout and stderr to a standard logger file handler while maintaining console output.
    """
    logger = logging.getLogger("task_logger")
    logger.setLevel(logging.INFO)
    logger.handlers = [] 

    file_handler = logging.FileHandler(log_filename, encoding='utf-8')
    file_handler.setFormatter(logging.Formatter('%(message)s'))
    logger.addHandler(file_handler)

    class StreamLogger:
        """Redirects stream writes to both the original stream and the logger."""
        def __init__(self, original_stream):
            self.original_stream = original_stream

        def write(self, message):
            self.original_stream.write(message)
            if message.strip():
                logger.info(message.rstrip())

        def flush(self):
            self.original_stream.flush()
            file_handler.flush()

    original_stdout = sys.stdout
    original_stderr = sys.stderr

    try:
        sys.stdout = StreamLogger(original_stdout)
        sys.stderr = StreamLogger(original_stderr)
        yield
    finally:
        sys.stdout = original_stdout
        sys.stderr = original_stderr
        logger.removeHandler(file_handler)
        file_handler.close()

def run_task(command, title, skip_adb=False):
    os.environ['SKIP_ADB'] = '1' if skip_adb else '0'
    
    os.system('cls' if os.name == 'nt' else 'clear')
    
    print("  " + "=" * 58)
    print(f"    Starting Task: [{title}]...")
    print("  " + "=" * 58, "\n")

    needs_logging = command in ["patch_all", "patch_all_wipe"]
    log_context = None
    log_file = None

    if needs_logging:
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        log_file = f"log_{timestamp}.txt"
        print(f"--- Logging enabled. Output will be saved to {log_file} ---")
        print(f"--- Command: {command} ---")
        log_context = capture_output_to_log(log_file)
    else:
        log_context = utils.temporary_workspace(Path(".")) 
        @contextmanager
        def no_op(): yield
        log_context = no_op()

    try:
        with log_context:
            func_tuple = COMMAND_MAP.get(command)
            if not func_tuple:
                print(f"[!] Unknown command: {command}", file=sys.stderr)
                return
            
            func, base_kwargs = func_tuple
            final_kwargs = base_kwargs.copy()
            if "skip_adb" in final_kwargs:
                final_kwargs["skip_adb"] = skip_adb
            
            func(**final_kwargs)

    except (subprocess.CalledProcessError, FileNotFoundError, RuntimeError, KeyError) as e:
        if not isinstance(e, SystemExit):
            print(f"\nAn unexpected error occurred: {e}", file=sys.stderr)
    except SystemExit:
        print("\nProcess halted by script.", file=sys.stderr)
    except KeyboardInterrupt:
        print("\nProcess cancelled by user.", file=sys.stderr)
    finally:
        print()
        if needs_logging and log_file:
            print(f"--- Logging finished. Output saved to {log_file} ---")

        print("  " + "=" * 58)
        print(f"  Task [{title}] has completed.")
        print("  " + "=" * 58, "\n")
        
        if command == "clean":
            print("Press any key to exit...")
        else:
            print("Press any key to return...")

        if platform.system() == "Windows":
            os.system("pause > nul")
        else:
            input()

def run_info_scan(paths):
    print("--- Starting Image Info Scan ---")
    
    PYTHON_EXE = constants.PYTHON_EXE
    AVBTOOL_PY = constants.AVBTOOL_PY
    BASE_DIR = constants.BASE_DIR

    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    log_filename = BASE_DIR / f"image_info_{timestamp}.txt"
    
    files_to_scan = []
    for path_str in paths:
        p = Path(path_str)
        if p.is_dir():
            files_to_scan.extend(p.rglob("*.img"))
        elif p.is_file() and p.suffix.lower() == '.img':
            files_to_scan.append(p)
    
    if not files_to_scan:
        print("[!] No .img files found in the provided paths.", file=sys.stderr)
        return

    print(f"[*] Found {len(files_to_scan)} image(s) to scan.")
    
    logger = logging.getLogger("scan_logger")
    logger.setLevel(logging.INFO)
    fh = logging.FileHandler(log_filename, encoding='utf-8')
    fh.setFormatter(logging.Formatter('%(message)s'))
    logger.addHandler(fh)

    try:
        for f in files_to_scan:
            cmd = [str(PYTHON_EXE), str(AVBTOOL_PY), "info_image", "--image", str(f)]
            header = f"--- Info for: {f.resolve()} ---\n"
            logger.info(header)
            print(f"[*] Scanning: {f.name}...")
            
            try:
                result = utils.run_command(cmd, capture=True, check=False)
                logger.info(result.stdout)
                logger.info(result.stderr)
                logger.info("\n" + "="*70 + "\n")
            except Exception as e:
                error_msg = f"[!] Failed to scan {f.name}: {e}\n"
                print(error_msg, file=sys.stderr)
                logger.info(error_msg)
    finally:
        logger.removeHandler(fh)
        fh.close()
    
    print(f"\n--- Process Complete ---")
    print(f"[*] Info saved to: {log_filename.name}")

def print_main_menu(skip_adb):
    skip_adb_state = "ON" if skip_adb else "OFF"
    os.system('cls' if os.name == 'nt' else 'clear')
    print("\n  " + "=" * 58)
    print("     LTBox - Main")
    print("  " + "=" * 58 + "\n")
    print(f"     1. Install ROW firmware to PRC device (WIPE DATA)")
    print(f"     2. Update ROW firmware on PRC device (NO WIPE)")
    print(f"     3. Disable OTA")
    print(f"     4. Root device")
    print(f"     5. Unroot device")
    print(f"     6. Skip ADB [{skip_adb_state}]")
    print("\n     a. Advanced")
    print("     x. Exit")
    print("\n  " + "=" * 58 + "\n")

def print_advanced_menu():
    os.system('cls' if os.name == 'nt' else 'clear')
    print("\n  " + "=" * 58)
    print("     LTBox - Advanced")
    print("  " + "=" * 58 + "\n")
    print("     1. Convert PRC to ROW in ROM")
    print("     2. Dump devinfo/persist from device")
    print("     3. Patch devinfo/persist to change region code")
    print("     4. Write devinfo/persist to device")
    print("     5. Detect Anti-Rollback from device")
    print("     6. Patch rollback indices in ROM")
    print("     7. Write Anti-Anti-Rollback to device")
    print("     8. Convert x files to xml (WIPE DATA)")
    print("     9. Convert x files to xml & Modify (NO WIPE)")
    print("    10. Flash firmware to device")
    print("\n    11. Clean workspace")
    print("     m. Back to Main")
    print("\n  " + "=" * 58 + "\n")

def advanced_menu(skip_adb):
    while True:
        print_advanced_menu()
        choice = input("    Enter your choice (1-11, m): ").strip().lower()

        actions_map = {
            "1": ("convert", "Convert PRC to ROW in ROM"),
            "2": ("read_edl", "Dump devinfo/persist from device"),
            "3": ("edit_dp", "Patch devinfo/persist to change region code"),
            "4": ("write_edl", "Write devinfo/persist to device"),
            "5": ("read_anti_rollback", "Detect Anti-Rollback from device"),
            "6": ("patch_anti_rollback", "Patch rollback indices in ROM"),
            "7": ("write_anti_rollback", "Write Anti-Anti-Rollback to device"),
            "8": ("modify_xml_wipe", "Convert x files to xml (WIPE DATA)"),
            "9": ("modify_xml", "Convert & Modify x files to xml (NO WIPE)"),
            "10": ("flash_edl", "Flash firmware to device"),
            "11": ("clean", "Workspace Cleanup")
        }

        if choice in actions_map:
            cmd, title = actions_map[choice]
            if choice == "11":
                run_task(cmd, title, skip_adb)
                sys.exit()
            run_task(cmd, title, skip_adb)
        elif choice == "m":
            return
        else:
            print("\n    [!] Invalid choice. Please enter a number from 1-11, or m.")
            if platform.system() == "Windows":
                os.system("pause > nul")
            else:
                input("Press Enter to continue...")

def main():
    skip_adb = False
    
    while True:
        print_main_menu(skip_adb)
        choice = input("    Enter your choice: ").strip().lower()

        actions_map = {
            "1": ("patch_all_wipe", "Install ROW firmware (WIPE DATA)"),
            "2": ("patch_all", "Update ROW firmware (NO WIPE)"),
            "3": ("disable_ota", "Disable OTA"),
            "4": ("root_device", "Root device"),
            "5": ("unroot_device", "Unroot device"),
        }

        if choice in actions_map:
            cmd, title = actions_map[choice]
            run_task(cmd, title, skip_adb)
        elif choice == "6":
            skip_adb = not skip_adb
        elif choice == "a":
            advanced_menu(skip_adb)
        elif choice == "x":
            break
        else:
            print("\n    [!] Invalid choice.")
            if platform.system() == "Windows":
                os.system("pause > nul")
            else:
                input("Press Enter to continue...")

if __name__ == "__main__":
    setup_console()
    check_path_encoding()
    
    if len(sys.argv) > 1 and sys.argv[1].lower() == 'info':
        if len(sys.argv) > 2:
            run_info_scan(sys.argv[2:])
        else:
            print("[!] No files or folders were dragged onto the script.", file=sys.stderr)
            print("[!] Please drag and drop .img files or folders.", file=sys.stderr)
        
        if platform.system() == "Windows":
            os.system("pause")
    else:
        main()
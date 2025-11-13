import os
import platform
import re
import shutil
import subprocess
import sys
import time
import xml.etree.ElementTree as ET
from datetime import datetime
from pathlib import Path
from typing import Optional, List, Dict, Any

from ltbox.constants import *
from ltbox import utils, device, imgpatch, downloader
from ltbox.downloader import ensure_magiskboot

def _scan_and_decrypt_xmls(lang: Optional[Dict[str, str]] = None) -> List[Path]:
    lang = lang or {}
    OUTPUT_XML_DIR.mkdir(exist_ok=True)
    
    xmls = list(OUTPUT_XML_DIR.glob("rawprogram*.xml"))
    if not xmls:
        xmls = list(IMAGE_DIR.glob("rawprogram*.xml"))
    
    if not xmls:
        print(lang.get("act_xml_scan_x", "[*] No XML files found. Checking for .x files to decrypt..."))
        x_files = list(IMAGE_DIR.glob("*.x"))
        
        if x_files:
            print(lang.get("act_xml_found_x_count", "[*] Found {len} .x files. Decrypting...").format(len=len(x_files)))
            utils.check_dependencies(lang=lang) 
            for x_file in x_files:
                xml_name = x_file.stem + ".xml"
                out_path = OUTPUT_XML_DIR / xml_name
                if not out_path.exists():
                    print(lang.get("act_xml_decrypting", "  > Decrypting {name}...").format(name=x_file.name))
                    if imgpatch.decrypt_file(str(x_file), str(out_path), lang=lang):
                        xmls.append(out_path)
                    else:
                        print(lang.get("act_xml_decrypt_fail", "  [!] Failed to decrypt {name}").format(name=x_file.name))
        else:
            print(lang.get("act_xml_none_found", "[!] No .xml or .x files found in 'image' folder."))
            print(lang.get("act_xml_dump_req", "[!] Dump requires partition information from these files."))
            print(lang.get("act_xml_place_prompt", "    Please place firmware .xml or .x files into the 'image' folder."))
            return []
            
    return xmls

def _get_partition_params(target_label: str, xml_paths: List[Path], lang: Optional[Dict[str, str]] = None) -> Optional[Dict[str, Any]]:
    lang = lang or {}
    for xml_path in xml_paths:
        try:
            tree = ET.parse(xml_path)
            root = tree.getroot()
            for prog in root.findall('program'):
                label = prog.get('label', '').lower()
                if label == target_label.lower():
                    return {
                        'lun': prog.get('physical_partition_number'),
                        'start_sector': prog.get('start_sector'),
                        'num_sectors': prog.get('num_partition_sectors'),
                        'filename': prog.get('filename', ''),
                        'source_xml': xml_path.name
                    }
        except Exception as e:
            print(lang.get("act_xml_parse_err", "[!] Error parsing {name}: {e}").format(name=xml_path.name, e=e))
            
    return None

def _ensure_params_or_fail(label: str, lang: Optional[Dict[str, str]] = None) -> Dict[str, Any]:
    lang = lang or {}
    xmls = _scan_and_decrypt_xmls(lang=lang)
    if not xmls:
        raise FileNotFoundError(lang.get("act_err_no_xml_dump", "No XML/.x files found for dump."))
        
    params = _get_partition_params(label, xmls, lang=lang)
    if not params:
        if label == "boot":
            params = _get_partition_params("boot_a", xmls, lang=lang)
            if not params:
                 params = _get_partition_params("boot_b", xmls, lang=lang)
                 
    if not params:
        print(lang.get("act_err_part_info_missing", "[!] Error: Could not find partition info for '{label}' in XMLs.").format(label=label))
        raise ValueError(lang.get("act_err_part_not_found", "Partition '{label}' not found in XMLs").format(label=label))
        
    return params

def detect_active_slot_robust(dev: device.DeviceController, skip_adb: bool, lang: Optional[Dict[str, str]] = None) -> Optional[str]:
    lang = lang or {}
    active_slot = None

    if not skip_adb:
        try:
            active_slot = dev.get_active_slot_suffix()
        except Exception:
            pass

    if not active_slot:
        print(lang.get("act_slot_adb_fail", "\n[!] Active slot not detected via ADB. Trying Fastboot..."))
        
        if not skip_adb:
            print(lang.get("act_reboot_bootloader", "[*] Rebooting to Bootloader..."))
            try:
                dev.reboot_to_bootloader()
            except Exception as e:
                print(lang.get("act_err_reboot_bl", "[!] Failed to reboot to bootloader: {e}").format(e=e))
        else:
            print("\n" + "="*60)
            print(lang.get("act_manual_fastboot", "  [ACTION REQUIRED] Please manually boot into FASTBOOT mode."))
            print("="*60 + "\n")

        dev.wait_for_fastboot()
        active_slot = dev.get_active_slot_suffix_from_fastboot()

        if not skip_adb:
            print(lang.get("act_slot_detected_sys", "[*] Slot detected. Rebooting to System to prepare for EDL..."))
            dev.fastboot_reboot_system()
            print(lang.get("act_wait_adb", "[*] Waiting for ADB connection..."))
            dev.wait_for_adb()
        else:
            print("\n" + "="*60)
            print(lang.get("act_detect_complete", "  [ACTION REQUIRED] Detection complete."))
            print(lang.get("act_manual_edl", "  [ACTION REQUIRED] Please manually boot your device into EDL mode."))
            print("="*60 + "\n")

    return active_slot

def convert_images(device_model: Optional[str] = None, skip_adb: bool = False, lang: Optional[Dict[str, str]] = None) -> None:
    lang = lang or {}
    utils.check_dependencies(lang=lang)
    
    print(lang.get("act_conv_start", "--- Starting vendor_boot & vbmeta conversion process ---"))

    print(lang.get("act_clean_old", "[*] Cleaning up old folders..."))
    if OUTPUT_DIR.exists():
        shutil.rmtree(OUTPUT_DIR)
    print()

    print(lang.get("act_wait_vb_vbmeta", "--- Waiting for vendor_boot.img and vbmeta.img ---"))
    IMAGE_DIR.mkdir(exist_ok=True)
    required_files = ["vendor_boot.img", "vbmeta.img"]
    prompt = lang.get("act_prompt_vb_vbmeta", 
        "[STEP 1] Place the required firmware files for conversion\n"
        f"         (e.g., from your PRC firmware) into the '{IMAGE_DIR.name}' folder."
    ).format(name=IMAGE_DIR.name)
    utils.wait_for_files(IMAGE_DIR, required_files, prompt, lang=lang)
    
    vendor_boot_src = IMAGE_DIR / "vendor_boot.img"
    vbmeta_src = IMAGE_DIR / "vbmeta.img"

    print(lang.get("act_backup_orig", "--- Backing up original images ---"))
    vendor_boot_bak = BASE_DIR / "vendor_boot.bak.img"
    vbmeta_bak = BASE_DIR / "vbmeta.bak.img"
    
    try:
        shutil.copy(vendor_boot_src, vendor_boot_bak)
        shutil.copy(vbmeta_src, vbmeta_bak)
        print(lang.get("act_backup_complete", "[+] Backup complete.\n"))
    except (IOError, OSError) as e:
        print(lang.get("act_err_copy_input", "[!] Failed to copy input files: {e}").format(e=e), file=sys.stderr)
        raise

    print(lang.get("act_start_conv", "--- Starting PRC/ROW Conversion ---"))
    imgpatch.edit_vendor_boot(str(vendor_boot_bak), lang=lang)

    vendor_boot_prc = BASE_DIR / "vendor_boot_prc.img"
    print(lang.get("act_verify_conv", "\n[*] Verifying conversion result..."))
    if not vendor_boot_prc.exists():
        print(lang.get("act_err_vb_prc_missing", "[!] 'vendor_boot_prc.img' was not created. No changes made."))
        raise FileNotFoundError(lang.get("act_err_vb_prc_not_created", "vendor_boot_prc.img not created"))
    print(lang.get("act_conv_success", "[+] Conversion to PRC successful.\n"))

    print(lang.get("act_extract_info", "--- Extracting image information ---"))
    vbmeta_info = imgpatch.extract_image_avb_info(vbmeta_bak, lang=lang)
    vendor_boot_info = imgpatch.extract_image_avb_info(vendor_boot_bak, lang=lang)
    print(lang.get("act_info_extracted", "[+] Information extracted.\n"))

    if device_model and not skip_adb:
        print(lang.get("act_val_model", "[*] Validating firmware against device model '{model}'...").format(model=device_model))
        fingerprint_key = "com.android.build.vendor_boot.fingerprint"
        if fingerprint_key in vendor_boot_info:
            fingerprint = vendor_boot_info[fingerprint_key]
            print(lang.get("act_found_fp", "  > Found firmware fingerprint: {fp}").format(fp=fingerprint))
            if device_model in fingerprint:
                print(lang.get("act_model_match", "[+] Success: Device model '{model}' found in firmware fingerprint.").format(model=device_model))
            else:
                print(lang.get("act_model_mismatch", "[!] ERROR: Device model '{model}' NOT found in firmware fingerprint.").format(model=device_model))
                print(lang.get("act_rom_mismatch_abort", "[!] The provided ROM does not match your device model. Aborting."))
                raise SystemExit(lang.get("act_err_firmware_mismatch", "Firmware model mismatch"))
        else:
            print(lang.get("act_warn_fp_missing", "[!] Warning: Could not find fingerprint property '{key}' in vendor_boot.").format(key=fingerprint_key))
            print(lang.get("act_skip_val", "[!] Skipping model validation."))
    
    print(lang.get("act_add_footer_vb", "--- Adding Hash Footer to vendor_boot ---"))
    
    for key in ['partition_size', 'name', 'rollback', 'salt']:
        if key not in vendor_boot_info:
            if key == 'partition_size' and 'data_size' in vendor_boot_info:
                 vendor_boot_info['partition_size'] = vendor_boot_info['data_size']
            else:
                raise KeyError(lang.get("act_err_avb_key_missing", "Could not find '{key}' in '{name}' AVB info.").format(key=key, name=vendor_boot_bak.name))

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
        print(lang.get("act_restore_props", "[+] Restoring {count} properties for vendor_boot.").format(count=len(vendor_boot_info['props_args']) // 2))

    if 'flags' in vendor_boot_info:
        add_hash_footer_cmd.extend(["--flags", vendor_boot_info.get('flags', '0')])
        print(lang.get("act_restore_flags", "[+] Restoring flags for vendor_boot: {flags}").format(flags=vendor_boot_info.get('flags', '0')))

    utils.run_command(add_hash_footer_cmd)
    
    vbmeta_pubkey = vbmeta_info.get('pubkey_sha1')
    key_file = KEY_MAP.get(vbmeta_pubkey) 

    print(lang.get("act_remake_vbmeta", "--- Remaking vbmeta.img ---"))
    print(lang.get("act_verify_vbmeta_key", "[*] Verifying vbmeta key..."))
    if not key_file:
        print(lang.get("act_err_vbmeta_key_mismatch", "[!] Public key SHA1 '{key}' from vbmeta did not match known keys. Aborting.").format(key=vbmeta_pubkey))
        raise KeyError(lang.get("act_err_unknown_key", "Unknown vbmeta public key: {key}").format(key=vbmeta_pubkey))
    print(lang.get("act_key_matched", "[+] Matched {name}.\n").format(name=key_file.name))

    print(lang.get("act_remaking_vbmeta", "[*] Remaking 'vbmeta.img' using descriptors from backup..."))
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
        
    utils.run_command(remake_cmd)
    print()

    print(lang.get("act_finalize", "--- Finalizing ---"))
    print(lang.get("act_rename_final", "[*] Renaming final images..."))
    final_vendor_boot = BASE_DIR / "vendor_boot.img"
    shutil.move(BASE_DIR / "vendor_boot_prc.img", final_vendor_boot)

    final_images = [final_vendor_boot, BASE_DIR / "vbmeta.img"]

    print(lang.get("act_move_final", "\n[*] Moving final images to '{dir}' folder...").format(dir=OUTPUT_DIR.name))
    OUTPUT_DIR.mkdir(exist_ok=True)
    for img in final_images:
        if img.exists(): 
            shutil.move(img, OUTPUT_DIR / img.name)

    print(lang.get("act_move_backup", "\n[*] Moving backup files to '{dir}' folder...").format(dir=BACKUP_DIR.name))
    BACKUP_DIR.mkdir(exist_ok=True)
    for bak_file in BASE_DIR.glob("*.bak.img"):
        shutil.move(bak_file, BACKUP_DIR / bak_file.name)
    print()

    print("=" * 61)
    print(lang.get("act_success", "  SUCCESS!"))
    print(lang.get("act_final_saved", "  Final images have been saved to the '{dir}' folder.").format(dir=OUTPUT_DIR.name))
    print("=" * 61)

def root_boot_only(lang: Optional[Dict[str, str]] = None) -> None:
    lang = lang or {}
    print(lang.get("act_clean_root_out", "[*] Cleaning up old '{dir}' folder...").format(dir=OUTPUT_ROOT_DIR.name))
    if OUTPUT_ROOT_DIR.exists():
        shutil.rmtree(OUTPUT_ROOT_DIR)
    OUTPUT_ROOT_DIR.mkdir(exist_ok=True)
    print()
    
    utils.check_dependencies(lang=lang)
    magiskboot_exe = utils.get_platform_executable("magiskboot")
    ensure_magiskboot(lang=lang)

    if platform.system() != "Windows":
        os.chmod(magiskboot_exe, 0o755)

    print(lang.get("act_wait_boot", "--- Waiting for boot.img ---"))
    IMAGE_DIR.mkdir(exist_ok=True) 
    required_files = ["boot.img"]
    prompt = lang.get("act_prompt_boot",
        "[STEP 1] Place your stock 'boot.img' file\n"
        f"         (e.g., from your firmware) into the '{IMAGE_DIR.name}' folder."
    ).format(name=IMAGE_DIR.name)
    utils.wait_for_files(IMAGE_DIR, required_files, prompt, lang=lang)
    
    boot_img_src = IMAGE_DIR / "boot.img"
    boot_img = BASE_DIR / "boot.img" 
    
    try:
        shutil.copy(boot_img_src, boot_img)
        print(lang.get("act_copy_boot", "[+] Copied '{name}' to main directory for processing.").format(name=boot_img_src.name))
    except (IOError, OSError) as e:
        print(lang.get("act_err_copy_boot", "[!] Failed to copy '{name}': {e}").format(name=boot_img_src.name, e=e), file=sys.stderr)
        sys.exit(1)

    if not boot_img.exists():
        print(lang.get("act_err_boot_missing", "[!] 'boot.img' not found! Aborting."))
        sys.exit(1)

    shutil.copy(boot_img, BASE_DIR / "boot.bak.img")
    print(lang.get("act_backup_boot", "--- Backing up original boot.img ---"))

    with utils.temporary_workspace(WORK_DIR):
        shutil.copy(boot_img, WORK_DIR / "boot.img")
        boot_img.unlink()
        
        patched_boot_path = imgpatch.patch_boot_with_root_algo(WORK_DIR, magiskboot_exe, lang=lang)

        if patched_boot_path and patched_boot_path.exists():
            print(lang.get("act_finalize_root", "\n--- Finalizing ---"))
            final_boot_img = OUTPUT_ROOT_DIR / "boot.img"
            
            imgpatch.process_boot_image_avb(patched_boot_path, lang=lang)

            print(lang.get("act_move_root_final", "\n[*] Moving final image to '{dir}' folder...").format(dir=OUTPUT_ROOT_DIR.name))
            shutil.move(patched_boot_path, final_boot_img)

            print(lang.get("act_move_root_backup", "\n[*] Moving backup file to '{dir}' folder...").format(dir=BACKUP_DIR.name))
            BACKUP_DIR.mkdir(exist_ok=True)
            for bak_file in BASE_DIR.glob("boot.bak.img"):
                shutil.move(bak_file, BACKUP_DIR / bak_file.name)
            print()

            print("=" * 61)
            print(lang.get("act_success", "  SUCCESS!"))
            print(lang.get("act_root_saved", "  Patched boot.img has been saved to the '{dir}' folder.").format(dir=OUTPUT_ROOT_DIR.name))
            print("=" * 61)
        else:
            print(lang.get("act_err_root_fail", "[!] Patched boot image was not created. An error occurred during the process."), file=sys.stderr)

def select_country_code(prompt_message: str = "Please select a country from the list below:", lang: Optional[Dict[str, str]] = None) -> str:
    lang = lang or {}
    print(lang.get("act_prompt_msg", "\n--- {msg} ---").format(msg=prompt_message.upper()))

    if not COUNTRY_CODES:
        print(lang.get("act_err_codes_missing", "[!] Error: COUNTRY_CODES not found in constants.py. Aborting."), file=sys.stderr)
        raise ImportError(lang.get("act_err_codes_missing_exc", "COUNTRY_CODES missing from constants.py"))

    sorted_countries = sorted(COUNTRY_CODES.items(), key=lambda item: item[1])
    
    num_cols = 3
    col_width = 38 
    
    line_width = col_width * num_cols
    print("-" * line_width)
    
    for i in range(0, len(sorted_countries), num_cols):
        line = []
        for j in range(num_cols):
            idx = i + j
            if idx < len(sorted_countries):
                code, name = sorted_countries[idx]
                line.append(f"{idx+1:3d}. {name} ({code})".ljust(col_width))
        print("".join(line))
    print("-" * line_width)

    while True:
        try:
            choice = input(lang.get("act_enter_num", "Enter the number (1-{len}): ").format(len=len(sorted_countries)))
            choice_idx = int(choice) - 1
            if 0 <= choice_idx < len(sorted_countries):
                selected_code = sorted_countries[choice_idx][0]
                selected_name = sorted_countries[choice_idx][1]
                print(lang.get("act_selected", "[+] You selected: {name} ({code})").format(name=selected_name, code=selected_code))
                return selected_code
            else:
                print(lang.get("act_invalid_num", "[!] Invalid number. Please enter a number within the range."))
        except ValueError:
            print(lang.get("act_invalid_input", "[!] Invalid input. Please enter a number."))
        except (KeyboardInterrupt, EOFError):
            print(lang.get("act_select_cancel", "\n[!] Selection cancelled by user. Exiting."))
            sys.exit(1)

def edit_devinfo_persist(lang: Optional[Dict[str, str]] = None) -> None:
    lang = lang or {}
    print(lang.get("act_start_dp_patch", "--- Starting devinfo & persist patching process ---"))
    
    print(lang.get("act_wait_dp", "--- Waiting for devinfo.img / persist.img ---"))
    BACKUP_DIR.mkdir(exist_ok=True) 

    devinfo_img_src = BACKUP_DIR / "devinfo.img"
    persist_img_src = BACKUP_DIR / "persist.img"
    
    devinfo_img = BASE_DIR / "devinfo.img"
    persist_img = BASE_DIR / "persist.img"

    if not devinfo_img_src.exists() and not persist_img_src.exists():
        prompt = lang.get("act_prompt_dp", 
            "[STEP 1] Place 'devinfo.img' and/or 'persist.img'\n"
            f"         (e.g., from 'Dump' menu) into the '{BACKUP_DIR.name}' folder."
        ).format(dir=BACKUP_DIR.name)
        while not devinfo_img_src.exists() and not persist_img_src.exists():
            if platform.system() == "Windows":
                os.system('cls')
            else:
                os.system('clear')
            print(lang.get("act_wait_files_title", "--- WAITING FOR FILES ---"))
            print(prompt)
            print(lang.get("act_place_one_file", "\nPlease place at least one file in the '{dir}' folder:").format(dir=BACKUP_DIR.name))
            print(" - devinfo.img")
            print(" - persist.img")
            print(lang.get("act_press_enter", "\nPress Enter when ready..."))
            try:
                input()
            except EOFError:
                sys.exit(1)

    if devinfo_img_src.exists():
        shutil.copy(devinfo_img_src, devinfo_img)
    if persist_img_src.exists():
        shutil.copy(persist_img_src, persist_img)

    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    backup_critical_dir = BASE_DIR / f"backup_critical_{timestamp}"
    backup_critical_dir.mkdir(exist_ok=True)
    
    if devinfo_img.exists():
        shutil.copy(devinfo_img, backup_critical_dir)
    if persist_img.exists():
        shutil.copy(persist_img, backup_critical_dir)
    print(lang.get("act_files_backed_up", "[+] Files copied and backed up to '{dir}'.\n").format(dir=backup_critical_dir.name))

    print(lang.get("act_clean_dp_out", "[*] Cleaning up old '{dir}' folder...").format(dir=OUTPUT_DP_DIR.name))
    if OUTPUT_DP_DIR.exists():
        shutil.rmtree(OUTPUT_DP_DIR)
    OUTPUT_DP_DIR.mkdir(exist_ok=True)

    print(lang.get("act_detect_codes", "[*] Detecting current region codes in images..."))
    detected_codes = imgpatch.detect_region_codes(lang=lang)
    
    status_messages = []
    files_found = 0
    
    display_order = ["persist.img", "devinfo.img"]
    
    for fname in display_order:
        if fname in detected_codes:
            code = detected_codes[fname]
            display_name = Path(fname).stem 
            
            if code:
                status_messages.append(f"{display_name}: {code}XX")
                files_found += 1
            else:
                status_messages.append(f"{display_name}: null")
    
    print(lang.get("act_detect_result", "\n[+] Detection Result:  {res}").format(res=', '.join(status_messages)))
    
    if files_found == 0:
        print(lang.get("act_no_codes_skip", "[!] No region codes detected. Patching skipped."))
        devinfo_img.unlink(missing_ok=True)
        persist_img.unlink(missing_ok=True)
        return

    print(lang.get("act_ask_change_code", "\nDo you want to change the region code? (y/n)"))
    choice = ""
    while choice not in ['y', 'n']:
        choice = input(lang.get("act_enter_yn", "Enter choice (y/n): ")).lower().strip()

    if choice == 'n':
        print(lang.get("act_op_cancel", "[*] Operation cancelled. No changes made."))
        
        devinfo_img.unlink(missing_ok=True)
        persist_img.unlink(missing_ok=True)
        
        print(lang.get("act_safety_remove", "[*] Safety: Removing stock devinfo.img/persist.img from 'image' folder to prevent accidental flash."))
        (IMAGE_DIR / "devinfo.img").unlink(missing_ok=True)
        (IMAGE_DIR / "persist.img").unlink(missing_ok=True)
        return

    if choice == 'y':
        target_map = detected_codes.copy()
        replacement_code = select_country_code(lang.get("act_select_new_code", "SELECT NEW REGION CODE"), lang=lang)
        imgpatch.patch_region_codes(replacement_code, target_map, lang=lang)

        modified_devinfo = BASE_DIR / "devinfo_modified.img"
        modified_persist = BASE_DIR / "persist_modified.img"
        
        if modified_devinfo.exists():
            shutil.move(modified_devinfo, OUTPUT_DP_DIR / "devinfo.img")
        if modified_persist.exists():
            shutil.move(modified_persist, OUTPUT_DP_DIR / "persist.img")
            
        print(lang.get("act_dp_moved", "\n[*] Final images have been moved to '{dir}' folder.").format(dir=OUTPUT_DP_DIR.name))
        
        devinfo_img.unlink(missing_ok=True)
        persist_img.unlink(missing_ok=True)
        
        print("\n" + "=" * 61)
        print(lang.get("act_success", "  SUCCESS!"))
        print(lang.get("act_dp_ready", "  Modified images are ready in the '{dir}' folder.").format(dir=OUTPUT_DP_DIR.name))
        print("=" * 61)

def modify_xml(wipe: int = 0, skip_dp: bool = False, lang: Optional[Dict[str, str]] = None) -> None:
    lang = lang or {}
    print(lang.get("act_start_xml_mod", "--- Starting XML Modification Process ---"))
    
    print(lang.get("act_wait_image", "--- Waiting for 'image' folder ---"))
    prompt = lang.get("act_prompt_image", 
        "[STEP 1] Please copy the entire 'image' folder from your\n"
        "         unpacked Lenovo RSA firmware into the main directory."
    )
    utils.wait_for_directory(IMAGE_DIR, prompt, lang=lang)

    if OUTPUT_XML_DIR.exists():
        shutil.rmtree(OUTPUT_XML_DIR)
    OUTPUT_XML_DIR.mkdir(exist_ok=True)

    with utils.temporary_workspace(WORKING_DIR):
        print(lang.get("act_create_temp", "\n[*] Created temporary '{dir}' folder.").format(dir=WORKING_DIR.name))
        try:
            imgpatch.modify_xml_algo(wipe=wipe, lang=lang)

            if not skip_dp:
                print(lang.get("act_create_write_xml", "\n[*] Creating custom write XMLs for devinfo/persist..."))

                src_persist_xml = OUTPUT_XML_DIR / "rawprogram_save_persist_unsparse0.xml"
                dest_persist_xml = OUTPUT_XML_DIR / "rawprogram_write_persist_unsparse0.xml"
                
                if src_persist_xml.exists():
                    try:
                        content = src_persist_xml.read_text(encoding='utf-8')
                        
                        content = re.sub(
                            r'(<program[^>]*\blabel="persist"[^>]*filename=")[^"]*(".*/>)',
                            r'\1persist.img\2',
                            content,
                            flags=re.IGNORECASE
                        )
                        content = re.sub(
                            r'(<program[^>]*filename=")[^"]*("[^>]*\blabel="persist"[^>]*/>)',
                            r'\1persist.img\2',
                            content,
                            flags=re.IGNORECASE
                        )
                        
                        dest_persist_xml.write_text(content, encoding='utf-8')
                        print(lang.get("act_created_persist_xml", "[+] Created '{name}' in '{parent}'.").format(name=dest_persist_xml.name, parent=dest_persist_xml.parent.name))
                    except Exception as e:
                        print(lang.get("act_err_create_persist_xml", "[!] Failed to create '{name}': {e}").format(name=dest_persist_xml.name, e=e), file=sys.stderr)
                else:
                    print(lang.get("act_warn_persist_xml_missing", "[!] Warning: '{name}' not found. Cannot create persist write XML.").format(name=src_persist_xml.name))

                src_devinfo_xml = OUTPUT_XML_DIR / "rawprogram4.xml"
                dest_devinfo_xml = OUTPUT_XML_DIR / "rawprogram4_write_devinfo.xml"
                
                if src_devinfo_xml.exists():
                    try:
                        content = src_devinfo_xml.read_text(encoding='utf-8')

                        content = re.sub(
                            r'(<program[^>]*\blabel="devinfo"[^>]*filename=")[^"]*(".*/>)',
                            r'\1devinfo.img\2',
                            content,
                            flags=re.IGNORECASE
                        )
                        content = re.sub(
                            r'(<program[^>]*filename=")[^"]*("[^>]*\blabel="devinfo"[^>]*/>)',
                            r'\1devinfo.img\2',
                            content,
                            flags=re.IGNORECASE
                        )
                        
                        dest_devinfo_xml.write_text(content, encoding='utf-8')
                        print(lang.get("act_created_devinfo_xml", "[+] Created '{name}' in '{parent}'.").format(name=dest_devinfo_xml.name, parent=dest_devinfo_xml.parent.name))
                    except Exception as e:
                        print(lang.get("act_err_create_devinfo_xml", "[!] Failed to create '{name}': {e}").format(name=dest_devinfo_xml.name, e=e), file=sys.stderr)
                else:
                    print(lang.get("act_warn_devinfo_xml_missing", "[!] Warning: '{name}' not found. Cannot create devinfo write XML.").format(name=src_devinfo_xml.name))

        except Exception as e:
            print(lang.get("act_err_xml_mod", "[!] Error during XML modification: {e}").format(e=e), file=sys.stderr)
            raise
        
        print(lang.get("act_clean_temp", "[*] Cleaned up temporary '{dir}' folder.").format(dir=WORKING_DIR.name))
    
    print("\n" + "=" * 61)
    print(lang.get("act_success", "  SUCCESS!"))
    print(lang.get("act_xml_ready", "  Modified XML files are ready in the '{dir}'.").format(dir=OUTPUT_XML_DIR.name))
    print(lang.get("act_xml_next_step", "  You can now run 'Flash EDL' (Menu 10)."))
    print("=" * 61)

def disable_ota(skip_adb: bool = False, lang: Optional[Dict[str, str]] = None) -> None:
    lang = lang or {}
    dev = device.DeviceController(skip_adb=skip_adb, lang=lang)
    if dev.skip_adb:
        print(lang.get("act_ota_skip_adb", "[!] 'Disable OTA' was skipped as requested by Skip ADB setting."))
        return
    
    print(lang.get("act_start_ota", "--- Starting Disable OTA Process ---"))
    
    print("\n" + "="*61)
    print(lang.get("act_ota_step1", "  STEP 1/2: Waiting for ADB Connection"))
    print("="*61)
    try:
        dev.wait_for_adb()
        print(lang.get("act_adb_ok", "[+] ADB device connected."))
    except Exception as e:
        print(lang.get("act_err_wait_adb", "[!] Error waiting for ADB device: {e}").format(e=e), file=sys.stderr)
        raise

    print("\n" + "="*61)
    print(lang.get("act_ota_step2", "  STEP 2/2: Disabling Lenovo OTA Service"))
    print("="*61)
    
    command = [
        str(ADB_EXE), 
        "shell", "pm", "disable-user", "--user", "0", "com.lenovo.ota"
    ]
    
    print(lang.get("act_run_cmd", "[*] Running command: {cmd}").format(cmd=' '.join(command)))
    try:
        result = utils.run_command(command, capture=True)
        if "disabled" in result.stdout.lower() or "already disabled" in result.stdout.lower():
            print(lang.get("act_ota_disabled", "[+] Success: OTA service (com.lenovo.ota) is now disabled."))
            print(result.stdout.strip())
        else:
            print(lang.get("act_ota_unexpected", "[!] Command executed, but result was unexpected."))
            print(f"Stdout: {result.stdout.strip()}")
            if result.stderr:
                print(f"Stderr: {result.stderr.strip()}", file=sys.stderr)
    except Exception as e:
        print(lang.get("act_err_ota_cmd", "[!] An error occurred while running the command: {e}").format(e=e), file=sys.stderr)
        raise

    print(lang.get("act_ota_finished", "\n--- Disable OTA Process Finished ---"))

def read_edl(skip_adb: bool = False, skip_reset: bool = False, additional_targets: Optional[List[str]] = None, lang: Optional[Dict[str, str]] = None) -> None:
    lang = lang or {}
    print(lang.get("act_start_dump", "--- Starting Dump Process (fh_loader) ---"))
    
    dev = device.DeviceController(skip_adb=skip_adb, lang=lang)
    port = dev.setup_edl_connection()
    
    try:
        dev.load_firehose_programmer(EDL_LOADER_FILE, port)
        time.sleep(2)
    except Exception as e:
        print(lang.get("act_warn_prog_load", "[!] Warning: Programmer loading issue (might be already loaded): {e}").format(e=e))

    BACKUP_DIR.mkdir(exist_ok=True)
    
    targets = ["devinfo", "persist"]

    if additional_targets:
        targets.extend(additional_targets)
        print(lang.get("act_ext_dump_targets", "[*] Extended dump targets: {targets}").format(targets=', '.join(targets)))
    
    for target in targets:
        out_file = BACKUP_DIR / f"{target}.img"
        print(lang.get("act_prep_dump", "\n[*] Preparing to dump '{target}'...").format(target=target))
        
        try:
            params = _ensure_params_or_fail(target, lang=lang)
            print(lang.get("act_found_dump_info", "  > Found info in {xml}: LUN={lun}, Start={start}").format(xml=params['source_xml'], lun=params['lun'], start=params['start_sector']))
            
            dev.fh_loader_read_part(
                port=port,
                output_filename=str(out_file),
                lun=params['lun'],
                start_sector=params['start_sector'],
                num_sectors=params['num_sectors']
            )
            print(lang.get("act_dump_success", "[+] Successfully read '{target}' to '{file}'.").format(target=target, file=out_file.name))
            
        except (ValueError, FileNotFoundError) as e:
            print(lang.get("act_skip_dump", "[!] Skipping '{target}': {e}").format(target=target, e=e))
        except Exception as e:
            print(lang.get("act_err_dump", "[!] Failed to read '{target}': {e}").format(target=target, e=e), file=sys.stderr)

        print(lang.get("act_wait_stability", "[*] Waiting 5 seconds for stability..."))
        time.sleep(5)

    if not skip_reset:
        print(lang.get("act_reset_sys", "\n[*] Resetting device to system..."))
        dev.fh_loader_reset(port)
        print(lang.get("act_reset_sent", "[+] Reset command sent."))
        print(lang.get("act_wait_stability_long", "[*] Waiting 10 seconds for stability..."))
        time.sleep(10)
    else:
        print(lang.get("act_skip_reset", "\n[*] Skipping reset as requested (Device remains in EDL)."))

    print(lang.get("act_dump_finish", "\n--- Dump Process Finished ---"))
    print(lang.get("act_dump_saved", "[*] Files saved to: {dir}").format(dir=BACKUP_DIR.name))

def read_edl_fhloader(skip_adb: bool = False, skip_reset: bool = False, additional_targets: Optional[List[str]] = None, lang: Optional[Dict[str, str]] = None) -> None:
    return read_edl(skip_adb, skip_reset=skip_reset, additional_targets=additional_targets, lang=lang)

def write_edl(skip_reset: bool = False, skip_reset_edl: bool = False, lang: Optional[Dict[str, str]] = None) -> None:
    lang = lang or {}
    print(lang.get("act_start_write", "--- Starting Write Process (Fastboot) ---"))

    skip_adb_val = os.environ.get('SKIP_ADB') == '1'
    dev = device.DeviceController(skip_adb=skip_adb_val, lang=lang)

    if not OUTPUT_DP_DIR.exists():
        print(lang.get("act_err_dp_folder", "[!] Error: Patched images folder '{dir}' not found.").format(dir=OUTPUT_DP_DIR.name), file=sys.stderr)
        print(lang.get("act_err_run_patch_first", "[!] Please run 'Patch devinfo/persist' (Menu 3) first to generate the modified images."), file=sys.stderr)
        raise FileNotFoundError(lang.get("act_err_dp_folder_nf", "{dir} not found.").format(dir=OUTPUT_DP_DIR.name))
    print(lang.get("act_found_dp_folder", "[+] Found patched images folder: '{dir}'.").format(dir=OUTPUT_DP_DIR.name))

    if not dev.skip_adb:
        print(lang.get("act_check_state", "[*] checking device state..."))
        
        if dev.check_fastboot_device(silent=True):
            print(lang.get("act_fastboot_ok", "[+] Device is already in Fastboot mode."))
        
        else:
            edl_port = dev.check_edl_device(silent=True)
            if edl_port:
                print(lang.get("act_edl_found", "[!] Device found in EDL mode ({port}).").format(port=edl_port))
                print(lang.get("act_reset_for_fastboot", "[*] Resetting to System via fh_loader to prepare for Fastboot..."))
                try:
                    dev.fh_loader_reset(edl_port)
                    print(lang.get("act_reset_sent_wait", "[+] Reset command sent. Waiting for device to boot..."))
                    time.sleep(10)
                except Exception as e:
                    print(lang.get("act_warn_reset_edl", "[!] Warning: Failed to reset from EDL: {e}").format(e=e))
            
            try:
                dev.wait_for_adb()
                dev.reboot_to_bootloader()
                time.sleep(10)
            except Exception as e:
                print(lang.get("act_err_reboot_bl_req", "[!] Error requesting reboot to bootloader: {e}").format(e=e))
                print(lang.get("act_manual_fastboot_hang", "[!] Please manually enter Fastboot mode if the script hangs."))

    else:
        print("\n" + "="*61)
        print(lang.get("act_skip_adb_active", "  [SKIP ADB ACTIVE]"))
        print(lang.get("act_manual_fastboot_prompt", "  Please manually boot your device into FASTBOOT mode."))
        print(lang.get("act_manual_fastboot_hint", "  (Power + Volume Down usually works)"))
        print("="*61 + "\n")
        input(lang.get("act_press_enter_fastboot", "  Press Enter when device is in Fastboot mode..."))

    dev.wait_for_fastboot()

    patched_devinfo = OUTPUT_DP_DIR / "devinfo.img"
    patched_persist = OUTPUT_DP_DIR / "persist.img"

    if not patched_devinfo.exists() and not patched_persist.exists():
         print(lang.get("act_err_no_imgs", "[!] Error: Neither 'devinfo.img' nor 'persist.img' found inside '{dir}'.").format(dir=OUTPUT_DP_DIR.name), file=sys.stderr)
         raise FileNotFoundError(lang.get("act_err_no_imgs_nf", "No patched images found in {dir}.").format(dir=OUTPUT_DP_DIR.name))

    try:
        if patched_devinfo.exists():
            print(lang.get("act_flash_devinfo", "\n[*] Flashing 'devinfo' partition via Fastboot..."))
            utils.run_command([str(FASTBOOT_EXE), "flash", "devinfo", str(patched_devinfo)])
            print(lang.get("act_flash_devinfo_ok", "[+] Successfully flashed 'devinfo'."))
        else:
            print(lang.get("act_skip_devinfo", "\n[*] 'devinfo.img' not found. Skipping."))

        if patched_persist.exists():
            print(lang.get("act_flash_persist", "\n[*] Flashing 'persist' partition via Fastboot..."))
            utils.run_command([str(FASTBOOT_EXE), "flash", "persist", str(patched_persist)])
            print(lang.get("act_flash_persist_ok", "[+] Successfully flashed 'persist'."))
        else:
            print(lang.get("act_skip_persist", "\n[*] 'persist.img' not found. Skipping."))

    except subprocess.CalledProcessError as e:
        print(lang.get("act_err_fastboot_flash", "[!] Fastboot flashing failed: {e}").format(e=e), file=sys.stderr)
        raise

    if not skip_reset:
        print(lang.get("act_reboot_device", "\n[*] Rebooting device..."))
        try:
            utils.run_command([str(FASTBOOT_EXE), "reboot"])
        except Exception as e:
            print(lang.get("act_warn_reboot", "[!] Warning: Failed to reboot: {e}").format(e=e))
    else:
        print(lang.get("act_skip_reboot", "\n[*] Skipping reboot as requested."))

    print(lang.get("act_write_finish", "\n--- Write Process Finished ---"))

def read_anti_rollback(dumped_boot_path: Path, dumped_vbmeta_path: Path, lang: Optional[Dict[str, str]] = None) -> Tuple[str, int, int]:
    lang = lang or {}
    print(lang.get("act_start_arb", "--- Anti-Rollback Status Check ---"))
    utils.check_dependencies(lang=lang)
    
    current_boot_rb = 0
    current_vbmeta_rb = 0
    
    print(lang.get("act_arb_step1", "\n--- [STEP 1] Parsing Rollback Indices from DUMPED IMAGES ---"))
    try:
        if not dumped_boot_path.exists() or not dumped_vbmeta_path.exists():
            raise FileNotFoundError(lang.get("act_err_dumped_missing", "Dumped boot/vbmeta images not found."))
        
        print(lang.get("act_read_dumped_boot", "[*] Reading from: {name}").format(name=dumped_boot_path.name))
        boot_info = imgpatch.extract_image_avb_info(dumped_boot_path, lang=lang)
        current_boot_rb = int(boot_info.get('rollback', '0'))
        
        print(lang.get("act_read_dumped_vbmeta", "[*] Reading from: {name}").format(name=dumped_vbmeta_path.name))
        vbmeta_info = imgpatch.extract_image_avb_info(dumped_vbmeta_path, lang=lang)
        current_vbmeta_rb = int(vbmeta_info.get('rollback', '0'))
        
    except Exception as e:
        print(lang.get("act_err_avb_info", "[!] Error extracting AVB info from dumps: {e}").format(e=e), file=sys.stderr)
        print(lang.get("act_arb_error", "\n--- Status Check Complete: ERROR ---"))
        return 'ERROR', 0, 0

    print(lang.get("act_curr_boot_idx", "  > Current Device Boot Index: {idx}").format(idx=current_boot_rb))
    print(lang.get("act_curr_vbmeta_idx", "  > Current Device VBMeta System Index: {idx}").format(idx=current_vbmeta_rb))

    print(lang.get("act_arb_step2", "\n--- [STEP 2] Comparing New ROM Indices ---"))
    print(lang.get("act_extract_new_indices", "\n[*] Extracting new ROM's rollback indices (from 'image' folder)..."))
    new_boot_img = IMAGE_DIR / "boot.img"
    new_vbmeta_img = IMAGE_DIR / "vbmeta_system.img"

    if not new_boot_img.exists() or not new_vbmeta_img.exists():
        print(lang.get("act_err_new_rom_missing", "[!] Error: 'boot.img' or 'vbmeta_system.img' not found in '{dir}' folder.").format(dir=IMAGE_DIR.name))
        print(lang.get("act_arb_missing_new", "\n--- Status Check Complete: MISSING_NEW ---"))
        return 'MISSING_NEW', 0, 0
        
    new_boot_rb = 0
    new_vbmeta_rb = 0
    try:
        new_boot_info = imgpatch.extract_image_avb_info(new_boot_img, lang=lang)
        new_boot_rb = int(new_boot_info.get('rollback', '0'))
        
        new_vbmeta_info = imgpatch.extract_image_avb_info(new_vbmeta_img, lang=lang)
        new_vbmeta_rb = int(new_vbmeta_info.get('rollback', '0'))
    except Exception as e:
        print(lang.get("act_err_read_new_info", "[!] Error reading new image info: {e}. Please check files.").format(e=e), file=sys.stderr)
        print(lang.get("act_arb_error", "\n--- Status Check Complete: ERROR ---"))
        return 'ERROR', 0, 0

    print(lang.get("act_new_boot_idx", "  > New ROM's Boot Index: {idx}").format(idx=new_boot_rb))
    print(lang.get("act_new_vbmeta_idx", "  > New ROM's VBMeta System Index: {idx}").format(idx=new_vbmeta_rb))

    if new_boot_rb == current_boot_rb and new_vbmeta_rb == current_vbmeta_rb:
        print(lang.get("act_arb_match", "\n[+] Indices are identical. No Anti-Rollback patch needed."))
        status = 'MATCH'
    else:
        print(lang.get("act_arb_patch_req", "\n[*] Indices are different (higher or lower). Patching is REQUIRED."))
        status = 'NEEDS_PATCH'
    
    print(lang.get("act_arb_complete", "\n--- Status Check Complete: {status} ---").format(status=status))
    return status, current_boot_rb, current_vbmeta_rb

def patch_anti_rollback(comparison_result: Tuple[str, int, int], lang: Optional[Dict[str, str]] = None) -> None:
    lang = lang or {}
    print(lang.get("act_start_arb_patch", "--- Anti-Rollback Patcher ---"))
    utils.check_dependencies(lang=lang)

    if OUTPUT_ANTI_ROLLBACK_DIR.exists():
        shutil.rmtree(OUTPUT_ANTI_ROLLBACK_DIR)
    OUTPUT_ANTI_ROLLBACK_DIR.mkdir(exist_ok=True)
    
    try:
        if comparison_result:
            print(lang.get("act_use_pre_arb", "[*] Using pre-computed Anti-Rollback status..."))
            status, current_boot_rb, current_vbmeta_rb = comparison_result
        else:
            print(lang.get("act_err_no_cmp", "[!] No comparison result provided. Aborting."))
            return

        if status != 'NEEDS_PATCH':
            print(lang.get("act_arb_no_patch", "\n[!] No patching is required or files are missing. Aborting patch."))
            return

        print(lang.get("act_arb_step3", "\n--- [STEP 3] Patching New ROM ---"))
        
        imgpatch.patch_chained_image_rollback(
            image_name="boot.img",
            current_rb_index=current_boot_rb,
            new_image_path=(IMAGE_DIR / "boot.img"),
            patched_image_path=(OUTPUT_ANTI_ROLLBACK_DIR / "boot.img"),
            lang=lang
        )
        
        print("-" * 20)
        
        imgpatch.patch_vbmeta_image_rollback(
            image_name="vbmeta_system.img",
            current_rb_index=current_vbmeta_rb,
            new_image_path=(IMAGE_DIR / "vbmeta_system.img"),
            patched_image_path=(OUTPUT_ANTI_ROLLBACK_DIR / "vbmeta_system.img"),
            lang=lang
        )

        print("\n" + "=" * 61)
        print(lang.get("act_success", "  SUCCESS!"))
        print(lang.get("act_arb_patched_ready", "  Anti-rollback patched images are in '{dir}'.").format(dir=OUTPUT_ANTI_ROLLBACK_DIR.name))
        print(lang.get("act_arb_next_step", "  You can now run 'Write Anti-Rollback' (Menu 8)."))
        print("=" * 61)

    except Exception as e:
        print(lang.get("act_err_arb_patch", "\n[!] An error occurred during patching: {e}").format(e=e), file=sys.stderr)
        shutil.rmtree(OUTPUT_ANTI_ROLLBACK_DIR) 

def write_anti_rollback(skip_reset: bool = False, lang: Optional[Dict[str, str]] = None) -> None:
    lang = lang or {}
    print(lang.get("act_start_arb_write", "--- Starting Anti-Rollback Write Process ---"))

    boot_img = OUTPUT_ANTI_ROLLBACK_DIR / "boot.img"
    vbmeta_img = OUTPUT_ANTI_ROLLBACK_DIR / "vbmeta_system.img"

    if not boot_img.exists() or not vbmeta_img.exists():
        print(lang.get("act_err_patched_missing", "[!] Error: Patched images not found in '{dir}'.").format(dir=OUTPUT_ANTI_ROLLBACK_DIR.name), file=sys.stderr)
        print(lang.get("act_err_run_patch_arb", "[!] Please run 'Patch Anti-Rollback' (Menu 7) first."), file=sys.stderr)
        raise FileNotFoundError(lang.get("act_err_patched_missing_exc", "Patched images not found in {dir}").format(dir=OUTPUT_ANTI_ROLLBACK_DIR.name))
    print(lang.get("act_found_arb_folder", "[+] Found patched images folder: '{dir}'.").format(dir=OUTPUT_ANTI_ROLLBACK_DIR.name))

    dev = device.DeviceController(skip_adb=True, lang=lang)
    
    print(lang.get("act_arb_write_step1", "\n--- [STEP 1] Detecting Active Slot via Fastboot ---"))
    print(lang.get("act_boot_fastboot", "[!] Please boot your device into FASTBOOT mode."))
    dev.wait_for_fastboot()

    active_slot = dev.get_active_slot_suffix_from_fastboot()
    if active_slot:
        print(lang.get("act_slot_confirmed", "[+] Active slot confirmed: {slot}").format(slot=active_slot))
    else:
        print(lang.get("act_warn_slot_fail", "[!] Warning: Active slot detection failed. Defaulting to no slot suffix."))
        active_slot = ""

    target_boot = f"boot{active_slot}"
    target_vbmeta = f"vbmeta_system{active_slot}"

    print(lang.get("act_arb_write_step2", "\n--- [STEP 2] Rebooting to EDL Mode ---"))
    print(lang.get("act_manual_edl_now", "[!] Please manually reboot your device to EDL mode now."))
    print(lang.get("act_manual_edl_hint", "(Use Key Combination or Fastboot menu if available)"))
    port = dev.wait_for_edl()
    
    try:
        dev.load_firehose_programmer(EDL_LOADER_FILE, port)
        time.sleep(2)

        print(lang.get("act_arb_write_step3", "\n--- [STEP 3] Flashing images to slot {slot} ---").format(slot=active_slot))

        print(lang.get("act_write_boot", "[*] Attempting to write '{target}' partition...").format(target=target_boot))
        params_boot = _ensure_params_or_fail(target_boot, lang=lang)
        print(lang.get("act_found_boot_info", "  > Found info: LUN={lun}, Start={start}").format(lun=params_boot['lun'], start=params_boot['start_sector']))
        dev.fh_loader_write_part(
            port=port,
            image_path=boot_img,
            lun=params_boot['lun'],
            start_sector=params_boot['start_sector']
        )
        print(lang.get("act_write_boot_ok", "[+] Successfully wrote '{target}'.").format(target=target_boot))

        print(lang.get("act_write_vbmeta", "[*] Attempting to write '{target}' partition...").format(target=target_vbmeta))
        params_vbmeta = _ensure_params_or_fail(target_vbmeta, lang=lang)
        print(lang.get("act_found_vbmeta_info", "  > Found info: LUN={lun}, Start={start}").format(lun=params_vbmeta['lun'], start=params_vbmeta['start_sector']))
        dev.fh_loader_write_part(
            port=port,
            image_path=vbmeta_img,
            lun=params_vbmeta['lun'],
            start_sector=params_vbmeta['start_sector']
        )
        print(lang.get("act_write_vbmeta_ok", "[+] Successfully wrote '{target}'.").format(target=target_vbmeta))

        if not skip_reset:
            print(lang.get("act_arb_reset", "\n[*] Operations complete. Resetting device..."))
            dev.fh_loader_reset(port)
            print(lang.get("act_reset_sent", "[+] Device reset command sent."))
        else:
            print(lang.get("act_arb_skip_reset", "\n[*] Operations complete. Skipping device reset as requested."))

    except (subprocess.CalledProcessError, FileNotFoundError, ValueError) as e:
        print(lang.get("act_err_edl_write", "[!] An error occurred during the EDL write operation: {e}").format(e=e), file=sys.stderr)
        raise
    
    print(lang.get("act_arb_write_finish", "\n--- Anti-Rollback Write Process Finished ---"))

def flash_edl(skip_reset: bool = False, skip_reset_edl: bool = False, skip_dp: bool = False, lang: Optional[Dict[str, str]] = None) -> None:
    lang = lang or {}
    print(lang.get("act_start_flash", "--- Starting Full EDL Flash Process ---"))

    skip_adb_val = os.environ.get('SKIP_ADB') == '1'
    dev = device.DeviceController(skip_adb=skip_adb_val, lang=lang)
    
    if not IMAGE_DIR.is_dir() or not any(IMAGE_DIR.iterdir()):
        print(lang.get("act_err_image_empty", "[!] Error: The '{dir}' folder is missing or empty.").format(dir=IMAGE_DIR.name))
        print(lang.get("act_err_run_xml_mod", "[!] Please run 'Modify XML for Update' (Menu 9) first."))
        raise FileNotFoundError(lang.get("act_err_image_empty_exc", "{dir} is missing or empty.").format(dir=IMAGE_DIR.name))
        
    loader_path = EDL_LOADER_FILE
    if not loader_path.exists():
        print(lang.get("act_err_loader_missing", "[!] Error: EDL Loader '{name}' not found in '{dir}' folder.").format(name=loader_path.name, dir=IMAGE_DIR.name))
        print(lang.get("act_err_copy_loader", "[!] Please copy it to the 'image' folder (from firmware)."))
        raise FileNotFoundError(lang.get("act_err_loader_missing_exc", "{name} not found in {dir}").format(name=loader_path.name, dir=IMAGE_DIR.name))

    if not skip_reset_edl:
        print("\n" + "="*61)
        print(lang.get("act_warn_overwrite_1", "  WARNING: PROCEEDING WILL OVERWRITE FILES IN YOUR 'image'"))
        print(lang.get("act_warn_overwrite_2", "           FOLDER WITH ANY PATCHED FILES YOU HAVE CREATED"))
        print(lang.get("act_warn_overwrite_3", "           (e.g., from Menu 1, 5, 7, or 9)."))
        print("="*61 + "\n")
        
        choice = ""
        while choice not in ['y', 'n']:
            choice = input(lang.get("act_ask_continue", "Are you sure you want to continue? (y/n): ")).lower().strip()

        if choice == 'n':
            print(lang.get("act_op_cancel", "[*] Operation cancelled."))
            return

    print(lang.get("act_copy_patched", "\n[*] Copying patched files to 'image' folder (overwriting)..."))
    output_folders_to_copy = [
        OUTPUT_DIR, 
        OUTPUT_ANTI_ROLLBACK_DIR,
        OUTPUT_XML_DIR
    ]
    
    copied_count = 0
    for folder in output_folders_to_copy:
        if folder.exists():
            try:
                shutil.copytree(folder, IMAGE_DIR, dirs_exist_ok=True)
                print(lang.get("act_copied_content", "  > Copied contents of '{src}' to '{dst}'.").format(src=folder.name, dst=IMAGE_DIR.name))
                copied_count += 1
            except Exception as e:
                print(lang.get("act_err_copy", "[!] Error copying files from {name}: {e}").format(name=folder.name, e=e), file=sys.stderr)
    
    if not skip_dp:
        if OUTPUT_DP_DIR.exists():
            try:
                shutil.copytree(OUTPUT_DP_DIR, IMAGE_DIR, dirs_exist_ok=True)
                print(lang.get("act_copied_dp", "  > Copied contents of '{src}' to '{dst}'.").format(src=OUTPUT_DP_DIR.name, dst=IMAGE_DIR.name))
                copied_count += 1
            except Exception as e:
                print(lang.get("act_err_copy_dp", "[!] Error copying files from {name}: {e}").format(name=OUTPUT_DP_DIR.name, e=e), file=sys.stderr)
        else:
            print(lang.get("act_skip_dp_copy", "[*] '{dir}' not found. Skipping devinfo/persist copy.").format(dir=OUTPUT_DP_DIR.name))
    else:
        print(lang.get("act_req_skip_dp", "[*] Skipping devinfo/persist copy as requested."))

    if copied_count == 0:
        print(lang.get("act_no_output_folders", "[*] No 'output*' folders found. Proceeding with files already in 'image' folder."))

    port = dev.setup_edl_connection()

    raw_xmls = [f for f in IMAGE_DIR.glob("rawprogram*.xml") if f.name != "rawprogram0.xml"]
    patch_xmls = list(IMAGE_DIR.glob("patch*.xml"))
    
    persist_write_xml = IMAGE_DIR / "rawprogram_write_persist_unsparse0.xml"
    persist_save_xml = IMAGE_DIR / "rawprogram_save_persist_unsparse0.xml"
    devinfo_write_xml = IMAGE_DIR / "rawprogram4_write_devinfo.xml"
    devinfo_original_xml = IMAGE_DIR / "rawprogram4.xml"

    has_patched_persist = (OUTPUT_DP_DIR / "persist.img").exists()
    has_patched_devinfo = (OUTPUT_DP_DIR / "devinfo.img").exists()

    if persist_write_xml.exists() and has_patched_persist and not skip_dp:
        print(lang.get("act_use_patched_persist", "[+] Using 'rawprogram_write_persist_unsparse0.xml' for persist flash (Patched)."))
        raw_xmls = [xml for xml in raw_xmls if xml.name != persist_save_xml.name]
    else:
        if persist_write_xml.exists() and any(xml.name == persist_write_xml.name for xml in raw_xmls):
             print(lang.get("act_skip_persist_flash", "[*] Skipping 'persist' flash (Not patched, preserving device data)."))
             raw_xmls = [xml for xml in raw_xmls if xml.name != persist_write_xml.name]

    if devinfo_write_xml.exists() and has_patched_devinfo and not skip_dp:
        print(lang.get("act_use_patched_devinfo", "[+] Using 'rawprogram4_write_devinfo.xml' for devinfo flash (Patched)."))
        raw_xmls = [xml for xml in raw_xmls if xml.name != devinfo_original_xml.name]
    else:
        if devinfo_write_xml.exists() and any(xml.name == devinfo_write_xml.name for xml in raw_xmls):
             print(lang.get("act_skip_devinfo_flash", "[*] Skipping 'devinfo' flash (Not patched, preserving device data)."))
             raw_xmls = [xml for xml in raw_xmls if xml.name != devinfo_write_xml.name]

    if not raw_xmls or not patch_xmls:
        print(lang.get("act_err_xml_missing", "[!] Error: 'rawprogram*.xml' (excluding rawprogram0.xml) or 'patch*.xml' files not found in '{dir}'.").format(dir=IMAGE_DIR.name))
        print(lang.get("act_err_flash_aborted", "[!] Cannot flash. Please run XML modification first."))
        raise FileNotFoundError(lang.get("act_err_xml_missing_exc", "Missing essential XML flash files in {dir}").format(dir=IMAGE_DIR.name))
        
    print(lang.get("act_flash_step1", "\n--- [STEP 1] Flashing all images via rawprogram (fh_loader) ---"))
    
    try:
        dev.edl_rawprogram(loader_path, "UFS", raw_xmls, patch_xmls, port)
    except (subprocess.CalledProcessError, FileNotFoundError) as e:
        print(lang.get("act_err_main_flash", "[!] An error occurred during main flash: {e}").format(e=e), file=sys.stderr)
        print(lang.get("act_warn_unstable", "[!] The device may be in an unstable state. Do not reboot manually."))
        raise
        
    print(lang.get("act_flash_step2", "\n--- [STEP 2] Cleaning up temporary images ---"))
    if not skip_dp:
        try:
            (IMAGE_DIR / "devinfo.img").unlink(missing_ok=True)
            (IMAGE_DIR / "persist.img").unlink(missing_ok=True)
            print(lang.get("act_removed_temp_imgs", "[+] Removed devinfo.img and persist.img from 'image' folder."))
        except OSError as e:
            print(lang.get("act_err_clean_imgs", "[!] Error cleaning up images: {e}").format(e=e), file=sys.stderr)

    if not skip_reset:
        print(lang.get("act_flash_step3", "\n--- [STEP 3] Final step: Resetting device to system ---"))
        try:
            print(lang.get("act_wait_stability", "[*] Waiting 5 seconds for stability..."))
            time.sleep(5)
            
            print(lang.get("act_reset_sys", "[*] Attempting to reset device via fh_loader..."))
            dev.fh_loader_reset(port)
            print(lang.get("act_reset_sent", "[+] Device reset command sent."))
        except (subprocess.CalledProcessError, FileNotFoundError, Exception) as e:
             print(lang.get("act_err_reset", "[!] Failed to reset device: {e}").format(e=e), file=sys.stderr)
    else:
        print(lang.get("act_skip_final_reset", "[*] Skipping final device reset as requested."))

    if not skip_reset:
        print(lang.get("act_flash_finish", "\n--- Full EDL Flash Process Finished ---"))

def _fh_loader_write_part(port, image_path, lun, start_sector, lang: Optional[Dict[str, str]] = None):
    lang = lang or {}
    if not FH_LOADER_EXE.exists():
        raise FileNotFoundError(lang.get("act_err_fh_exe_missing", "fh_loader.exe not found at {path}").format(path=FH_LOADER_EXE))
        
    port_str = f"\\\\.\\{port}"
    cmd = [
        str(FH_LOADER_EXE),
        f"--port={port_str}",
        f"--sendimage={image_path}",
        f"--lun={lun}",
        f"--start_sector={start_sector}",
        "--zlpawarehost=1",
        "--noprompt",
        "--memoryname=UFS"
    ]
    print(lang.get("act_flash_part", "[*] Flashing {name} to LUN:{lun} @ {start}...").format(name=image_path.name, lun=lun, start=start_sector))
    utils.run_command(cmd)

def root_device(skip_adb=False, lang: Optional[Dict[str, str]] = None) -> None:
    lang = lang or {}
    print(lang.get("act_start_root", "--- Starting Root Device Process (EDL Mode) ---"))
    
    if OUTPUT_ROOT_DIR.exists():
        shutil.rmtree(OUTPUT_ROOT_DIR)
    OUTPUT_ROOT_DIR.mkdir(exist_ok=True)
    BACKUP_BOOT_DIR.mkdir(exist_ok=True)

    utils.check_dependencies(lang=lang)
    
    magiskboot_exe = utils.get_platform_executable("magiskboot")
    ensure_magiskboot(lang=lang)

    dev = device.DeviceController(skip_adb=skip_adb, lang=lang)

    print(lang.get("act_root_step1", "\n--- [STEP 1/6] Waiting for ADB Connection & Slot Detection ---"))
    if not skip_adb:
        dev.wait_for_adb()

    active_slot = detect_active_slot_robust(dev, skip_adb, lang=lang)

    if active_slot:
        print(lang.get("act_slot_confirmed", "[+] Active slot confirmed: {slot}").format(slot=active_slot))
        target_partition = f"boot{active_slot}"
    else:
        print(lang.get("act_warn_root_slot", "[!] Warning: Active slot detection failed. Defaulting to 'boot' (System decides)."))
        target_partition = "boot"

    if not skip_adb:
        print(lang.get("act_check_ksu", "\n[*] Checking & Installing KernelSU Next (Spoofed) APK..."))
        downloader.download_ksu_apk(BASE_DIR, lang=lang)
        
        ksu_apks = list(BASE_DIR.glob("*spoofed*.apk"))
        if ksu_apks:
            apk_path = ksu_apks[0]
            print(lang.get("act_install_ksu", "[*] Installing {name} via ADB...").format(name=apk_path.name))
            try:
                utils.run_command([str(ADB_EXE), "install", "-r", str(apk_path)])
                print(lang.get("act_ksu_ok", "[+] APK installed successfully."))
            except Exception as e:
                print(lang.get("act_err_ksu", "[!] Failed to install APK: {e}").format(e=e))
                print(lang.get("act_root_anyway", "[!] Proceeding with root process anyway..."))
        else:
            print(lang.get("act_skip_ksu", "[!] Spoofed APK not found. Skipping installation."))
    
    print(lang.get("act_root_step2", "\n--- [STEP 2/6] Rebooting to EDL Mode ---"))
    port = dev.setup_edl_connection()
    
    try:
        dev.load_firehose_programmer(EDL_LOADER_FILE, port)
        time.sleep(2)
    except Exception as e:
        print(lang.get("act_warn_prog_load", "[!] Warning: Programmer loading issue: {e}").format(e=e))

    print(lang.get("act_root_step3", "\n--- [STEP 3/6] Dumping {part} partition ---").format(part=target_partition))
    
    params = None
    final_boot_img = OUTPUT_ROOT_DIR / "boot.img"
    
    with utils.temporary_workspace(WORKING_BOOT_DIR):
        dumped_boot_img = WORKING_BOOT_DIR / "boot.img"
        backup_boot_img = BACKUP_BOOT_DIR / "boot.img"
        base_boot_bak = BASE_DIR / "boot.bak.img"

        try:
            params = _ensure_params_or_fail(target_partition, lang=lang)
            print(lang.get("act_found_dump_info", "  > Found info in {xml}: LUN={lun}, Start={start}").format(xml=params['source_xml'], lun=params['lun'], start=params['start_sector']))
            dev.fh_loader_read_part(
                port=port,
                output_filename=str(dumped_boot_img),
                lun=params['lun'],
                start_sector=params['start_sector'],
                num_sectors=params['num_sectors']
            )
            print(lang.get("act_read_boot_ok", "[+] Successfully read '{part}' to '{file}'.").format(part=target_partition, file=dumped_boot_img))
        except (subprocess.CalledProcessError, FileNotFoundError, ValueError) as e:
            print(lang.get("act_err_dump", "[!] Failed to read '{part}': {e}").format(part=target_partition, e=e), file=sys.stderr)
            raise

        print(lang.get("act_backup_boot_root", "[*] Backing up original boot.img to '{dir}' folder...").format(dir=backup_boot_img.parent.name))
        shutil.copy(dumped_boot_img, backup_boot_img)
        print(lang.get("act_temp_backup_avb", "[*] Creating temporary backup for AVB processing..."))
        shutil.copy(dumped_boot_img, base_boot_bak)
        print(lang.get("act_backups_done", "[+] Backups complete."))

        print(lang.get("act_dump_reset", "\n[*] Dumping complete. Resetting to System to clear EDL state..."))
        dev.fh_loader_reset(port)
        
        print(lang.get("act_root_step4", "\n--- [STEP 4/6] Patching dumped boot.img ---"))
        patched_boot_path = imgpatch.patch_boot_with_root_algo(WORKING_BOOT_DIR, magiskboot_exe, lang=lang)

        if not (patched_boot_path and patched_boot_path.exists()):
            print(lang.get("act_err_root_fail", "[!] Patched boot image was not created. An error occurred."), file=sys.stderr)
            base_boot_bak.unlink(missing_ok=True)
            sys.exit(1)

        print(lang.get("act_root_step5", "\n--- [STEP 5/6] Processing AVB Footer ---"))
        try:
            imgpatch.process_boot_image_avb(patched_boot_path, lang=lang)
        except Exception as e:
            print(lang.get("act_err_avb_footer", "[!] Failed to process AVB footer: {e}").format(e=e), file=sys.stderr)
            base_boot_bak.unlink(missing_ok=True)
            raise

        shutil.move(patched_boot_path, final_boot_img)
        print(lang.get("act_patched_boot_saved", "[+] Patched boot image saved to '{dir}' folder.").format(dir=final_boot_img.parent.name))

        base_boot_bak.unlink(missing_ok=True)

    print(lang.get("act_root_step6", "\n--- [STEP 6/6] Flashing patched boot.img to {part} via EDL ---").format(part=target_partition))
    
    if not skip_adb:
        print(lang.get("act_wait_sys_adb", "[*] Waiting for device to boot to System (ADB) to ensure clean state..."))
        dev.wait_for_adb()
        print(lang.get("act_reboot_edl_flash", "[*] Rebooting to EDL for flashing..."))
        port = dev.setup_edl_connection()
    else:
        print(lang.get("act_skip_adb_on", "[!] Skip ADB is ON."))
        print(lang.get("act_manual_edl_now", "[!] Please manually reboot your device to EDL mode now."))
        port = dev.wait_for_edl()

    try:
        dev.load_firehose_programmer(EDL_LOADER_FILE, port)
        time.sleep(2)
    except Exception as e:
        print(lang.get("act_warn_prog_load", "[!] Warning: Programmer loading issue: {e}").format(e=e))

    if not params:
         params = _ensure_params_or_fail(target_partition, lang=lang)

    try:
        _fh_loader_write_part(
            port=port,
            image_path=final_boot_img,
            lun=params['lun'],
            start_sector=params['start_sector'],
            lang=lang
        )
        print(lang.get("act_flash_boot_ok", "[+] Successfully flashed 'boot.img' to {part} via EDL.").format(part=target_partition))
        
        print(lang.get("act_reset_sys", "[*] Resetting to system..."))
        dev.fh_loader_reset(port)
    except (subprocess.CalledProcessError, FileNotFoundError) as e:
        print(lang.get("act_err_edl_write", "[!] An error occurred during EDL flash: {e}").format(e=e), file=sys.stderr)
        raise

    print(lang.get("act_root_finish", "\n--- Root Device Process Finished ---"))

def unroot_device(skip_adb=False, lang: Optional[Dict[str, str]] = None) -> None:
    lang = lang or {}
    print(lang.get("act_start_unroot", "--- Starting Unroot Device Process (EDL Mode) ---"))
    
    backup_boot_file = BACKUP_BOOT_DIR / "boot.img"
    BACKUP_BOOT_DIR.mkdir(exist_ok=True)
    
    print(lang.get("act_unroot_step1", "\n--- [STEP 1/4] Checking Requirements ---"))
    if not list(IMAGE_DIR.glob("rawprogram*.xml")) and not list(IMAGE_DIR.glob("*.x")):
         print(lang.get("act_err_no_xmls", "[!] Error: No firmware XMLs found in '{dir}'.").format(dir=IMAGE_DIR.name))
         print(lang.get("act_unroot_req_xmls", "[!] Unroot via EDL requires partition information from firmware XMLs."))
         prompt = lang.get("act_prompt_image",
            "[STEP 1] Please copy the entire 'image' folder from your\n"
            "         unpacked Lenovo RSA firmware into the main directory."
         )
         utils.wait_for_directory(IMAGE_DIR, prompt, lang=lang)

    print(lang.get("act_unroot_step2", "\n--- [STEP 2/4] Checking for backup boot.img ---"))
    if not backup_boot_file.exists():
        prompt = lang.get("act_prompt_backup_boot",
            "[!] Backup file 'boot.img' not found.\n"
            f"    Please place your stock 'boot.img' (from your current firmware)\n"
            f"    into the '{BACKUP_BOOT_DIR.name}' folder."
        ).format(dir=BACKUP_BOOT_DIR.name)
        utils.wait_for_files(BACKUP_BOOT_DIR, ["boot.img"], prompt, lang=lang)
    
    print(lang.get("act_backup_boot_found", "[+] Stock backup 'boot.img' found."))

    dev = device.DeviceController(skip_adb=skip_adb, lang=lang)
    target_partition = "boot"

    print(lang.get("act_unroot_step3", "\n--- [STEP 3/4] Checking Device Slot & Connection ---"))
    if not skip_adb:
        dev.wait_for_adb()
    
    active_slot = detect_active_slot_robust(dev, skip_adb, lang=lang)
    
    if active_slot:
        print(lang.get("act_slot_confirmed", "[+] Active slot confirmed: {slot}").format(slot=active_slot))
        target_partition = f"boot{active_slot}"
    else:
        print(lang.get("act_warn_unroot_slot", "[!] Warning: Active slot detection failed. Defaulting to 'boot'."))

    port = dev.setup_edl_connection()

    try:
        dev.load_firehose_programmer(EDL_LOADER_FILE, port)
        time.sleep(2)
    except Exception as e:
        print(lang.get("act_warn_prog_load", "[!] Warning: Programmer loading issue: {e}").format(e=e))

    print(lang.get("act_unroot_step4", "\n--- [STEP 4/4] Flashing stock boot.img to {part} via EDL ---").format(part=target_partition))
    try:
        params = _ensure_params_or_fail(target_partition, lang=lang)
        print(lang.get("act_found_dump_info", "  > Found info in {xml}: LUN={lun}, Start={start}").format(xml=params['source_xml'], lun=params['lun'], start=params['start_sector']))
        
        _fh_loader_write_part(
            port=port,
            image_path=backup_boot_file,
            lun=params['lun'],
            start_sector=params['start_sector'],
            lang=lang
        )
        print(lang.get("act_flash_stock_boot_ok", "[+] Successfully flashed stock 'boot.img' to {part}.").format(part=target_partition))
        
        print(lang.get("act_reset_sys", "[*] Resetting to system..."))
        dev.fh_loader_reset(port)
        
    except (subprocess.CalledProcessError, FileNotFoundError, ValueError) as e:
        print(lang.get("act_err_edl_write", "[!] An error occurred during EDL flash: {e}").format(e=e), file=sys.stderr)
        raise

    print(lang.get("act_unroot_finish", "\n--- Unroot Device Process Finished ---"))
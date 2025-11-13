import os
import re
import shutil
import subprocess
import sys
import hashlib
import struct
from pathlib import Path
from typing import Dict, Optional, Tuple, Any, Union, List
from binascii import hexlify, unhexlify
from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes

from ltbox.constants import *
from ltbox import utils, downloader

def extract_image_avb_info(image_path: Path, lang: Optional[Dict[str, str]] = None) -> Dict[str, Any]:
    lang = lang or {}
    info_proc = utils.run_command(
        [str(PYTHON_EXE), str(AVBTOOL_PY), "info_image", "--image", str(image_path)],
        capture=True
    )
    
    output = info_proc.stdout.strip()
    info: Dict[str, Any] = {}
    props_args: List[str] = []

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
            print(lang.get("img_info_flags", f"[Info] Parsed Flags: {info['flags']}").format(flags=info['flags']))
        
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
        print(lang.get("img_info_props", f"[Info] Parsed {len(props_args) // 2} properties.").format(count=len(props_args) // 2))

    return info

def _apply_hash_footer(
    image_path: Path, 
    image_info: Dict[str, Any], 
    key_file: Path, 
    new_rollback_index: Optional[str] = None,
    lang: Optional[Dict[str, str]] = None
) -> None:
    lang = lang or {}
    rollback_index = new_rollback_index if new_rollback_index is not None else image_info['rollback']
    
    print(lang.get("img_footer_adding", f"\n[*] Adding hash footer to '{image_path.name}'...").format(name=image_path.name))
    print(lang.get("img_footer_details", f"  > Partition: {image_info['name']}, Rollback Index: {rollback_index}").format(part=image_info['name'], rb=rollback_index))

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
        print(lang.get("img_footer_restore_flags", f"  > Restoring flags: {image_info.get('flags', '0')}").format(flags=image_info.get('flags', '0')))

    utils.run_command(add_footer_cmd)
    print(lang.get("img_footer_success", f"[+] Successfully applied hash footer to {image_path.name}.").format(name=image_path.name))

def patch_chained_image_rollback(
    image_name: str, 
    current_rb_index: int, 
    new_image_path: Path, 
    patched_image_path: Path,
    lang: Optional[Dict[str, str]] = None
) -> None:
    lang = lang or {}
    try:
        print(lang.get("img_analyze_new", f"[*] Analyzing new {image_name}...").format(name=image_name))
        info = extract_image_avb_info(new_image_path, lang=lang)
        new_rb_index = int(info.get('rollback', '0'))
        print(lang.get("img_new_index", f"  > New index: {new_rb_index}").format(index=new_rb_index))

        if new_rb_index >= current_rb_index:
            print(lang.get("img_index_ok", f"[*] {image_name} index is OK. Copying as is.").format(name=image_name))
            shutil.copy(new_image_path, patched_image_path)
            return

        print(lang.get("img_patch_bypass", f"[!] Anti-Rollback Bypassed: Patching {image_name} from {new_rb_index} to {current_rb_index}...").format(name=image_name, old=new_rb_index, new=current_rb_index))
        
        for key in ['partition_size', 'name', 'salt', 'algorithm', 'pubkey_sha1']:
            if key not in info:
                raise KeyError(lang.get("img_err_missing_key", f"Could not find '{key}' in '{new_image_path.name}' AVB info.").format(key=key, name=new_image_path.name))
        
        key_file = KEY_MAP.get(info['pubkey_sha1']) 
        if not key_file:
            raise KeyError(lang.get("img_err_unknown_key", f"Unknown public key SHA1 {info['pubkey_sha1']} in {new_image_path.name}").format(key=info['pubkey_sha1'], name=new_image_path.name))
        
        shutil.copy(new_image_path, patched_image_path)
        
        _apply_hash_footer(
            image_path=patched_image_path,
            image_info=info,
            key_file=key_file,
            new_rollback_index=str(current_rb_index),
            lang=lang
        )

    except (KeyError, subprocess.CalledProcessError, FileNotFoundError) as e:
        print(lang.get("img_err_processing", f"[!] Error processing {image_name}: {e}").format(name=image_name, e=e), file=sys.stderr)
        raise

def patch_vbmeta_image_rollback(
    image_name: str, 
    current_rb_index: int, 
    new_image_path: Path, 
    patched_image_path: Path,
    lang: Optional[Dict[str, str]] = None
) -> None:
    lang = lang or {}
    try:
        print(lang.get("img_analyze_new", f"[*] Analyzing new {image_name}...").format(name=image_name))
        info = extract_image_avb_info(new_image_path, lang=lang)
        new_rb_index = int(info.get('rollback', '0'))
        print(lang.get("img_new_index", f"  > New index: {new_rb_index}").format(index=new_rb_index))

        if new_rb_index >= current_rb_index:
            print(lang.get("img_index_ok", f"[*] {image_name} index is OK. Copying as is.").format(name=image_name))
            shutil.copy(new_image_path, patched_image_path)
            return

        print(lang.get("img_patch_bypass", f"[!] Anti-Rollback Bypassed: Patching {image_name} from {new_rb_index} to {current_rb_index}...").format(name=image_name, old=new_rb_index, new=current_rb_index))

        for key in ['algorithm', 'pubkey_sha1']:
            if key not in info:
                raise KeyError(lang.get("img_err_missing_key", f"Could not find '{key}' in '{new_image_path.name}' AVB info.").format(key=key, name=new_image_path.name))
        
        key_file = KEY_MAP.get(info['pubkey_sha1']) 
        if not key_file:
            raise KeyError(lang.get("img_err_unknown_key", f"Unknown public key SHA1 {info['pubkey_sha1']} in {new_image_path.name}").format(key=info['pubkey_sha1'], name=new_image_path.name))

        remake_cmd = [
            str(PYTHON_EXE), str(AVBTOOL_PY), "make_vbmeta_image",
            "--output", str(patched_image_path),
            "--key", str(key_file),
            "--algorithm", info['algorithm'],
            "--rollback_index", str(current_rb_index),
            "--flags", info.get('flags', '0'),
            "--include_descriptors_from_image", str(new_image_path)
        ]
        
        utils.run_command(remake_cmd)
        print(lang.get("img_patch_success", f"[+] Successfully patched {image_name}.").format(name=image_name))

    except (KeyError, subprocess.CalledProcessError, FileNotFoundError) as e:
        print(lang.get("img_err_processing", f"[!] Error processing {image_name}: {e}").format(name=image_name, e=e), file=sys.stderr)
        raise

def process_boot_image_avb(image_to_process: Path, lang: Optional[Dict[str, str]] = None) -> None:
    lang = lang or {}
    print(lang.get("img_verify_boot", "\n[*] Verifying boot image key and metadata...")) 
    boot_bak_img = BASE_DIR / "boot.bak.img"
    if not boot_bak_img.exists():
        print(lang.get("img_err_boot_bak_missing", f"[!] Backup file '{boot_bak_img.name}' not found. Cannot process image.").format(name=boot_bak_img.name), file=sys.stderr)
        raise FileNotFoundError(f"{boot_bak_img.name} not found.")
        
    boot_info = extract_image_avb_info(boot_bak_img, lang=lang)
    
    for key in ['partition_size', 'name', 'rollback', 'salt', 'algorithm', 'pubkey_sha1']:
        if key not in boot_info:
            raise KeyError(lang.get("img_err_missing_key", f"Could not find '{key}' in '{boot_bak_img.name}' AVB info.").format(key=key, name=boot_bak_img.name))
            
    boot_pubkey = boot_info.get('pubkey_sha1')
    key_file = KEY_MAP.get(boot_pubkey) 
    
    if not key_file:
        print(lang.get("img_err_boot_key_mismatch", f"[!] Public key SHA1 '{boot_pubkey}' from boot.img did not match known keys. Cannot add footer.").format(key=boot_pubkey))
        raise KeyError(f"Unknown boot public key: {boot_pubkey}")

    print(lang.get("img_key_matched", f"[+] Matched {key_file.name}.").format(name=key_file.name))
    
    _apply_hash_footer(
        image_path=image_to_process,
        image_info=boot_info,
        key_file=key_file,
        lang=lang
    )

def patch_boot_with_root_algo(work_dir: Path, magiskboot_exe: Path, lang: Optional[Dict[str, str]] = None) -> Optional[Path]:
    lang = lang or {}
    original_cwd = Path.cwd()
    os.chdir(work_dir)
    
    patched_boot_path = BASE_DIR / "boot.root.img"
    
    try:
        print(lang.get("img_root_step1", "\n[1/8] Unpacking boot image..."))
        utils.run_command([str(magiskboot_exe), "unpack", "boot.img"])
        if not (work_dir / "kernel").exists():
            print(lang.get("img_root_unpack_fail", "[!] Failed to unpack boot.img. The image might be invalid."))
            return None
        print(lang.get("img_root_unpack_ok", "[+] Unpack successful."))

        print(lang.get("img_root_step2", "\n[2/8] Verifying kernel version..."))
        target_kernel_version = get_kernel_version("kernel", lang=lang)

        if not target_kernel_version:
             print(lang.get("img_root_kernel_ver_fail", "[!] Failed to get kernel version from 'kernel' file."))
             return None

        if not re.match(r"\d+\.\d+\.\d+", target_kernel_version):
             print(lang.get("img_root_kernel_invalid", f"[!] Invalid kernel version returned from script: '{target_kernel_version}'").format(ver=target_kernel_version))
             return None
        
        print(lang.get("img_root_target_ver", f"[+] Target kernel version for download: {target_kernel_version}").format(ver=target_kernel_version))

        kernel_image_path = downloader.get_gki_kernel(target_kernel_version, work_dir, lang=lang)

        print(lang.get("img_root_step5", "\n[5/8] Replacing original kernel with the new one..."))
        shutil.move(str(kernel_image_path), "kernel")
        print(lang.get("img_root_kernel_replaced", "[+] Kernel replaced."))

        print(lang.get("img_root_step6", "\n[6/8] Repacking boot image..."))
        utils.run_command([str(magiskboot_exe), "repack", "boot.img"])
        if not (work_dir / "new-boot.img").exists():
            print(lang.get("img_root_repack_fail", "[!] Failed to repack the boot image."))
            return None
        shutil.move("new-boot.img", patched_boot_path)
        print(lang.get("img_root_repack_ok", "[+] Repack successful."))

        downloader.download_ksu_apk(BASE_DIR, lang=lang)
        
        return patched_boot_path

    finally:
        os.chdir(original_cwd)
        if work_dir.exists():
            shutil.rmtree(work_dir)
        print(lang.get("img_root_cleanup", "\n--- Cleaning up ---"))


def modify_xml_algo(wipe: int = 0, lang: Optional[Dict[str, str]] = None) -> None:
    lang = lang or {}
    def is_garbage_file(path: Path) -> bool:
        name = path.name.lower()
        stem = path.stem.lower()
        if stem == "rawprogram_unsparse0": return True
        if "wipe_partitions" in name or "blank_gpt" in name: return True
        return False

    if OUTPUT_XML_DIR.exists():
        shutil.rmtree(OUTPUT_XML_DIR)
    OUTPUT_XML_DIR.mkdir(parents=True, exist_ok=True)

    print(lang.get("img_xml_scan", "[*] Scanning files in 'image' folder..."))
    
    x_files = list(IMAGE_DIR.glob("*.x"))
    xml_files = list(IMAGE_DIR.glob("*.xml"))
    
    processed_files = False

    if x_files:
        print(lang.get("img_xml_found_x", f"[*] Found {len(x_files)} .x files. Decrypting to '{OUTPUT_XML_DIR.name}'...").format(count=len(x_files), dir=OUTPUT_XML_DIR.name))
        for file in x_files:
            out_file = OUTPUT_XML_DIR / file.with_suffix('.xml').name
            try:
                if decrypt_file(str(file), str(out_file), lang=lang):
                    print(lang.get("img_xml_decrypt_ok", f"  > Decrypted: {file.name} -> {out_file.name}").format(src=file.name, dst=out_file.name))
                    processed_files = True
                else:
                    print(lang.get("img_xml_decrypt_fail", f"  [!] Decryption failed for {file.name}").format(name=file.name))
            except Exception as e:
                print(lang.get("img_xml_decrypt_err", f"  [!] Error decrypting {file.name}: {e}").format(name=file.name, e=e), file=sys.stderr)

    if xml_files:
        print(lang.get("img_xml_found_xml", f"[*] Found {len(xml_files)} .xml files. Moving to '{OUTPUT_XML_DIR.name}'...").format(count=len(xml_files), dir=OUTPUT_XML_DIR.name))
        for file in xml_files:
            out_file = OUTPUT_XML_DIR / file.name
            try:
                if out_file.exists():
                    out_file.unlink()
                shutil.move(str(file), str(out_file))
                print(lang.get("img_xml_moved", f"  > Moved: {file.name}").format(name=file.name))
                processed_files = True
            except Exception as e:
                print(lang.get("img_xml_move_err", f"  [!] Error moving {file.name}: {e}").format(name=file.name, e=e), file=sys.stderr)

    if not processed_files:
        print(lang.get("img_xml_no_files", f"[!] No usable firmware files (.x or .xml) found in '{IMAGE_DIR.name}'. Aborting.").format(dir=IMAGE_DIR.name))
        shutil.rmtree(OUTPUT_XML_DIR)
        raise FileNotFoundError(f"No .x or .xml files in {IMAGE_DIR.name}")

    rawprogram4 = OUTPUT_XML_DIR / "rawprogram4.xml"
    rawprogram_unsparse4 = OUTPUT_XML_DIR / "rawprogram_unsparse4.xml"
    
    if not rawprogram4.exists() and rawprogram_unsparse4.exists():
        print(lang.get("img_xml_copy_raw4", "[*] 'rawprogram4.xml' not found. Copying 'rawprogram_unsparse4.xml'..."))
        shutil.copy(rawprogram_unsparse4, rawprogram4)

    print(lang.get("img_xml_mod_raw", "\n[*] Modifying 'rawprogram_save_persist_unsparse0.xml'..."))
    
    rawprogram_save = OUTPUT_XML_DIR / "rawprogram_save_persist_unsparse0.xml"

    if not rawprogram_save.exists():
        rawprogram_fallback = OUTPUT_XML_DIR / "rawprogram_unsparse0-half.xml"
        
        if rawprogram_fallback.exists():
            print(lang.get("img_xml_rename_fallback", f"[*] '{rawprogram_save.name}' not found. Renaming '{rawprogram_fallback.name}'...").format(target=rawprogram_save.name, src=rawprogram_fallback.name))
            try:
                rawprogram_fallback.rename(rawprogram_save)
            except OSError as e:
                print(lang.get("img_xml_rename_err", f"[!] Failed to rename fallback file: {e}").format(e=e), file=sys.stderr)
                raise
        else:
            print(lang.get("img_xml_critical_missing", f"[!] Critical Error: Neither '{rawprogram_save.name}' nor '{rawprogram_fallback.name}' found.").format(f1=rawprogram_save.name, f2=rawprogram_fallback.name))
            print(lang.get("img_xml_abort_mod", "[!] Cannot proceed with Wipe/No Wipe modification. Aborting."))
            raise FileNotFoundError(f"Critical XML file missing: {rawprogram_save.name} or {rawprogram_fallback.name}")

    try:
        with open(rawprogram_save, 'r', encoding='utf-8') as f:
            content = f.read()
        
        if wipe == 0:
            print(lang.get("img_xml_nowipe", "  > [NO WIPE] Removing metadata and userdata entries..."))
            for i in range(1, 11):
                content = content.replace(f'filename="metadata_{i}.img"', '')
            for i in range(1, 21):
                content = content.replace(f'filename="userdata_{i}.img"', '')
        else:
            print(lang.get("img_xml_wipe", "  > [WIPE] Skipping metadata and userdata removal."))
            
        with open(rawprogram_save, 'w', encoding='utf-8') as f:
            f.write(content)
        print(lang.get("img_xml_patch_ok", "  > Patched successfully."))
    except Exception as e:
        print(lang.get("img_xml_patch_err", f"[!] Error patching: {e}").format(e=e), file=sys.stderr)
        raise

    print(lang.get("img_xml_cleanup", "\n[*] Cleaning up unnecessary files in output folder..."))
    
    files_to_delete = []
    for f in OUTPUT_XML_DIR.glob("*.xml"):
        if is_garbage_file(f):
            files_to_delete.append(f)

    if files_to_delete:
        for f in files_to_delete:
            try:
                f.unlink()
                print(lang.get("img_xml_deleted", f"  > Deleted: {f.name}").format(name=f.name))
            except OSError as e:
                print(lang.get("img_xml_del_err", f"  [!] Failed to delete {f.name}: {e}").format(name=f.name, e=e))
    else:
        print(lang.get("img_xml_no_del", "  > No files to delete."))

    print(lang.get("img_xml_complete", f"[+] XML processing complete. All files are in '{OUTPUT_XML_DIR.name}'.").format(dir=OUTPUT_XML_DIR.name))

PASSWORD = "OSD"

def PBKDF1(s: str, salt: bytes, lenout: int, hashfunc: Any, iter_: int) -> bytes:
    m = hashfunc
    digest = m(s.encode("utf-8") + salt).digest()
    for i in range(iter_-1):
        digest = m(digest).digest()
    return digest[:lenout]

def generate(salt: bytes) -> bytes:
    return PBKDF1(PASSWORD, salt, 32, hashlib.sha256, 1000)

def decrypt_file(fi_path: str, fo_path: str, lang: Optional[Dict[str, str]] = None) -> bool:
    lang = lang or {}
    try:
        with open(fi_path, "rb") as fi:
            iv = fi.read(16)
            salt = fi.read(16)
            encrypted_body = fi.read()

        key = generate(salt)

        cipher = Cipher(algorithms.AES(key), modes.CBC(iv))
        decryptor = cipher.decryptor()
        plain = decryptor.update(encrypted_body) + decryptor.finalize()

        original_size = struct.unpack('<q', plain[0:8])[0]
        signature = plain[8:16]
        if signature != b'\xcf\x06\x05\x04\x03\x02\x01\xfc':
            print(lang.get("img_decrypt_broken", "Broken file."))
            return False

        body = plain[16:16 + original_size]
        digest = hashlib.sha256(body).digest()
        if digest != plain[16 + original_size:16 + original_size + 32]:
            print(lang.get("img_decrypt_broken", "Broken file."))
            return False

        with open(fo_path, "wb") as fo:
            fo.write(body)
            
        print(lang.get("img_decrypt_success", "Successfully decrypted."), original_size, "bytes")
        return True

    except Exception as e:
        print(lang.get("img_decrypt_error", f"Error decrypting {fi_path}: {e}").format(path=fi_path, e=e), file=sys.stderr)
        return False

def _process_binary_file(
    input_path: Union[str, Path], 
    output_path: Union[str, Path], 
    patch_func: Any, 
    copy_if_unchanged: bool = True,
    lang: Optional[Dict[str, str]] = None,
    **kwargs: Any
) -> bool:
    lang = lang or {}
    input_path = Path(input_path)
    output_path = Path(output_path)
    
    if not input_path.exists():
        print(lang.get("img_proc_err_not_found", f"Error: Input file not found at '{input_path}'").format(path=input_path), file=sys.stderr)
        return False

    try:
        content = input_path.read_bytes()
        modified_content, stats = patch_func(content, lang=lang, **kwargs)

        if stats.get('changed', False):
            output_path.write_bytes(modified_content)
            print(lang.get("img_proc_success", f"\nPatch successful! {stats.get('message', 'Modifications applied.')}").format(msg=stats.get('message', 'Modifications applied.')))
            print(lang.get("img_proc_saved", f"Saved as '{output_path.name}'").format(name=output_path.name))
            return True
        else:
            print(lang.get("img_proc_no_change", f"\n[*] No changes needed for {input_path.name} ({stats.get('message', 'No patterns found')}).").format(name=input_path.name, msg=stats.get('message', 'No patterns found')))
            if copy_if_unchanged:
                print(lang.get("img_proc_copying", f"[*] Copying original file as '{output_path.name}'...").format(name=output_path.name))
                if input_path != output_path:
                    shutil.copy(input_path, output_path)
                return True
            return False

    except Exception as e:
        print(lang.get("img_proc_error", f"An error occurred while processing '{input_path.name}': {e}").format(name=input_path.name, e=e), file=sys.stderr)
        return False

def _patch_vendor_boot_logic(content: bytes, lang: Optional[Dict[str, str]] = None, **kwargs: Any) -> Tuple[bytes, Dict[str, Any]]:
    lang = lang or {}
    patterns_row = {
        b"\x2E\x52\x4F\x57": b"\x2E\x50\x52\x43",
        b"\x49\x52\x4F\x57": b"\x49\x50\x52\x43"
    }
    patterns_prc = [b"\x2E\x50\x52\x43", b"\x49\x50\x52\x43"]
    
    modified_content = content
    found_row_count = 0

    for target, replacement in patterns_row.items():
        count = content.count(target)
        if count > 0:
            print(lang.get("img_vb_found_replace", f"Found '{target.hex().upper()}' pattern {count} time(s). Replacing...").format(pattern=target.hex().upper(), count=count))
            modified_content = modified_content.replace(target, replacement)
            found_row_count += count

    if found_row_count > 0:
        return modified_content, {'changed': True, 'message': lang.get("img_vb_replaced_total", f"Total {found_row_count} instance(s) replaced.").format(count=found_row_count)}
    
    found_prc = any(content.count(target) > 0 for target in patterns_prc)
    if found_prc:
        return content, {'changed': False, 'message': lang.get("img_vb_already_prc", ".PRC patterns found (Already patched).")}
    
    return content, {'changed': False, 'message': lang.get("img_vb_no_patterns", "No .ROW or .PRC patterns found.")}

def edit_vendor_boot(input_file_path: str, lang: Optional[Dict[str, str]] = None) -> None:
    input_file = Path(input_file_path)
    output_file = input_file.parent / "vendor_boot_prc.img"
    
    if not _process_binary_file(input_file, output_file, _patch_vendor_boot_logic, copy_if_unchanged=True, lang=lang):
        sys.exit(1)

def check_target_exists(target_code: str, lang: Optional[Dict[str, str]] = None) -> bool:
    lang = lang or {}
    target_bytes = f"{target_code.upper()}XX".encode('ascii')
    files_to_check = [BASE_DIR / "devinfo.img", BASE_DIR / "persist.img"]
    found = False
    
    for f in files_to_check:
        if not f.exists():
            continue
        try:
            content = f.read_bytes()
            if content.count(target_bytes) > 0:
                found = True
                break
        except Exception as e:
            print(lang.get("img_chk_err_read", f"[!] Error reading {f.name} for check: {e}").format(name=f.name, e=e), file=sys.stderr)
    return found

def detect_region_codes(lang: Optional[Dict[str, str]] = None) -> Dict[str, Optional[str]]:
    lang = lang or {}
    results: Dict[str, Optional[str]] = {}
    files_to_check = ["devinfo.img", "persist.img"]

    if not COUNTRY_CODES:
        print(lang.get("img_det_warn_empty", "[!] Warning: COUNTRY_CODES list is empty."), file=sys.stderr)
        return {f: None for f in files_to_check}

    for filename in files_to_check:
        file_path = BASE_DIR / filename
        results[filename] = None
        
        if not file_path.exists():
            continue
            
        try:
            content = file_path.read_bytes()
            for code, _ in COUNTRY_CODES.items():
                target_bytes = b'\x00\x00\x00' + f"{code.upper()}".encode('ascii') + b'XX\x00\x00\x00'
                if target_bytes in content:
                    results[filename] = code
                    break
        except Exception as e:
            print(lang.get("img_det_err_read", f"[!] Error reading {filename}: {e}").format(name=filename, e=e), file=sys.stderr)
            
    return results

def _patch_region_code_logic(content: bytes, lang: Optional[Dict[str, str]] = None, **kwargs: Any) -> Tuple[bytes, Dict[str, Any]]:
    lang = lang or {}
    current_code = kwargs.get('current_code')
    replacement_code = kwargs.get('replacement_code')
    
    if not current_code or not replacement_code:
        return content, {'changed': False, 'message': lang.get("img_code_invalid", "Invalid codes")}

    target_string = f"000000{current_code.upper()}XX000000"
    target_bytes = b'\x00\x00\x00' + f"{current_code.upper()}".encode('ascii') + b'XX\x00\x00\x00'
    
    if target_bytes == replacement_bytes:
        return content, {'changed': False, 'message': lang.get("img_code_already", f"File is already '{replacement_code.upper()}'.").format(code=replacement_code.upper())}

    count = content.count(target_bytes)
    if count > 0:
        print(lang.get("img_code_replace", f"Found '{target_string}' pattern {count} time(s). Replacing with '{replacement_string}'...").format(target=target_string, count=count, replacement=replacement_string))
        modified_content = content.replace(target_bytes, replacement_bytes)
        return modified_content, {'changed': True, 'message': lang.get("img_code_replaced_total", f"Total {count} instance(s) replaced.").format(count=count), 'count': count}
    
    return content, {'changed': False, 'message': lang.get("img_code_not_found", f"Pattern '{target_string}' NOT found.").format(target=target_string)}

def patch_region_codes(replacement_code: str, target_map: Dict[str, Optional[str]], lang: Optional[Dict[str, str]] = None) -> int:
    lang = lang or {}
    if not replacement_code or len(replacement_code) != 2:
        print(lang.get("img_patch_code_err", f"[!] Error: Invalid replacement code '{replacement_code}'. Aborting.").format(code=replacement_code), file=sys.stderr)
        sys.exit(1)
        
    total_patched = 0
    files_to_output = {
        "devinfo.img": "devinfo_modified.img",
        "persist.img": "persist_modified.img"
    }

    print(lang.get("img_patch_start", f"[*] Starting patch process (New Region: {replacement_code})...").format(code=replacement_code))

    for filename, current_code in target_map.items():
        if filename not in files_to_output:
            continue
            
        input_file = BASE_DIR / filename
        output_file = BASE_DIR / files_to_output[filename]
        
        if not input_file.exists():
            continue
            
        print(lang.get("img_patch_processing", f"\n--- Processing '{input_file.name}' ---").format(name=input_file.name))
        
        if not current_code:
            print(lang.get("img_patch_skip", f"[*] No target code specified/detected for '{filename}'. Skipping.").format(name=filename))
            continue

        success = _process_binary_file(
            input_file, 
            output_file, 
            _patch_region_code_logic, 
            copy_if_unchanged=True,
            current_code=current_code, 
            replacement_code=replacement_code,
            lang=lang
        )
        
        if success:
             pass

    print(lang.get("img_patch_finish", f"\nPatching finished."))
    return total_patched

def get_kernel_version(file_path: Union[str, Path], lang: Optional[Dict[str, str]] = None) -> Optional[str]:
    lang = lang or {}
    kernel_file = Path(file_path)
    if not kernel_file.exists():
        print(lang.get("img_kv_err_not_found", f"Error: Kernel file not found at '{file_path}'").format(path=file_path), file=sys.stderr)
        return None

    try:
        content = kernel_file.read_bytes()
        potential_strings = re.findall(b'[ -~]{10,}', content)
        
        found_version = None
        for string_bytes in potential_strings:
            try:
                line = string_bytes.decode('ascii', errors='ignore')
                if 'Linux version ' in line:
                    base_version_match = re.search(r'(\d+\.\d+\.\d+)', line)
                    if base_version_match:
                        found_version = base_version_match.group(1)
                        print(lang.get("img_kv_found", f"Full kernel string found: {line.strip()}").format(line=line.strip()), file=sys.stderr)
                        break
            except UnicodeDecodeError:
                continue

        if found_version:
            return found_version
        else:
            print(lang.get("img_kv_err_parse", "Error: Could not find or parse 'Linux version' string in the kernel file."), file=sys.stderr)
            return None

    except Exception as e:
        print(lang.get("img_kv_err_unexpected", f"An unexpected error occurred: {e}").format(e=e), file=sys.stderr)
        return None
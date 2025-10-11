import argparse
import sys
from pathlib import Path

def edit_vendor_boot(input_file_path):
    """
    Replaces region code patterns in vendor_boot.img.
    .ROW -> .PRC, IROW -> IPRC
    """
    input_file = Path(input_file_path)
    output_file = input_file.parent / "vendor_boot_prc.img"

    if not input_file.exists():
        print(f"Error: Input file not found at '{input_file}'", file=sys.stderr)
        sys.exit(1)

    patterns = {
        b"\x2E\x52\x4F\x57": b"\x2E\x50\x52\x43",  # .ROW -> .PRC
        b"\x49\x52\x4F\x57": b"\x49\x50\x52\x43"   # IROW -> IPRC
    }

    try:
        content = input_file.read_bytes()
        modified_content = content
        found_count = 0

        for target, replacement in patterns.items():
            count = modified_content.count(target)
            if count > 0:
                print(f"Found '{target.hex().upper()}' pattern {count} time(s). Replacing...")
                modified_content = modified_content.replace(target, replacement)
                found_count += count

        if found_count > 0:
            output_file.write_bytes(modified_content)
            print(f"\nPatch successful! Total {found_count} instance(s) replaced.")
            print(f"Saved as '{output_file.name}'")
        else:
            print("No target patterns found in vendor_boot. No changes made.")

    except Exception as e:
        print(f"An error occurred while processing '{input_file.name}': {e}", file=sys.stderr)
        sys.exit(1)

def edit_devinfo_persist():
    """
    Replaces 'CNXX' pattern in devinfo.img and persist.img with null bytes.
    """
    files_to_process = {
        "devinfo.img": "devinfo_modified.img",
        "persist.img": "persist_modified.img"
    }
    
    target = b"CNXX"
    replacement = b"\x00\x00\x00\x00"
    total_found_count = 0

    for input_filename, output_filename in files_to_process.items():
        input_file = Path(input_filename)
        output_file = Path(output_filename)

        print(f"\n--- Processing '{input_file.name}' ---")

        if not input_file.exists():
            print(f"Warning: '{input_file.name}' not found. Skipping.")
            continue
        
        try:
            content = input_file.read_bytes()
            count = content.count(target)
            
            if count > 0:
                print(f"Found '{target.decode('ascii')}' pattern {count} time(s). Replacing...")
                modified_content = content.replace(target, replacement)
                output_file.write_bytes(modified_content)
                total_found_count += count
                print(f"Patch successful! Saved as '{output_file.name}'")
            else:
                print(f"No target patterns found in '{input_file.name}'. No changes made.")

        except Exception as e:
            print(f"An error occurred while processing '{input_file.name}': {e}", file=sys.stderr)
    
    if total_found_count > 0:
        print(f"\nPatching finished! Total {total_found_count} instance(s) replaced across all files.")
    else:
        print("\nPatching finished! No changes were made to any files.")


def main():
    parser = argparse.ArgumentParser(description="A script to modify specific Android image files.")
    subparsers = parser.add_subparsers(dest="command", required=True, help="Available commands")

    parser_vndrboot = subparsers.add_parser("vndrboot", help="Modify vendor_boot.img region code.")
    parser_vndrboot.add_argument("input_file", help="Path to the vendor_boot.img file.")

    subparsers.add_parser("dp", help="Modify devinfo.img and persist.img.")

    args = parser.parse_args()

    if args.command == "vndrboot":
        edit_vendor_boot(args.input_file)
    elif args.command == "dp":
        edit_devinfo_persist()

if __name__ == "__main__":
    main()
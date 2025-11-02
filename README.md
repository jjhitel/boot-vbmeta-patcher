# LTBox

## ⚠️ Important: Disclaimer

**This project is for educational purposes ONLY.**

Modifying your device's boot images carries significant risks, including but not limited to, bricking your device, data loss, or voiding your warranty. The author **assumes no liability** and is not responsible for any **damage or consequence** that may occur to **your device or anyone else's device** from using these scripts.

**You are solely responsible for any consequences. Use at your own absolute risk.**

---

## 1. Core Vulnerability & Overview

This toolkit exploits a security vulnerability found in certain Lenovo Android tablets. These devices have firmware signed with publicly available **AOSP (Android Open Source Project) test keys**.

Because of this vulnerability, the device's bootloader trusts and boots any image signed with these common test keys, even if the bootloader is **locked**.

This toolkit is an all-in-one collection of scripts that leverages this flaw to perform advanced modifications on a device with a locked bootloader.

### Target Models

* Lenovo Legion Y700 (2nd, 3rd, 4th Gen)
* Lenovo Tab Plus AI (AKA Yoga Pad Pro AI)
* Lenovo Xiaoxin Pad Pro GT

*...Other recent Lenovo devices (released in 2024 or later with Qualcomm chipsets) may also be vulnerable.*

## 2. Toolkit Purpose & Features

This toolkit provides an all-in-one solution for the following tasks **without unlocking the bootloader**:

1.  **Region Conversion (PRC → ROW)**
    * Converts the region code in `vendor_boot.img` to allow flashing a global (ROW) ROM on a Chinese (PRC) model.
    * Re-makes the `vbmeta.img` with the AOSP test keys to validate the modified `vendor_boot`.
2.  **Rooting**
    * Patches the stock `boot.img` by replacing the original kernel with [one that includes KernelSU](https://github.com/WildKernels/GKI_KernelSU_SUSFS).
    * Re-signs the patched `boot.img` with AOSP test keys.
3.  **Region Code Reset**
    * Modifies byte patterns in `devinfo.img` and `persist.img` to reset region-lock settings.
4.  **EDL Partition Dump/Write**
    * Dumps the `devinfo` and `persist` partitions directly from the device to the `backup` folder.
    * Flashes the patched `devinfo.img` and `persist.img` from the `output_dp` folder to the device.
5.  **Anti-Rollback (ARB) Bypass**
    * Dumps current firmware via EDL to check rollback indices.
    * Compares them against new firmware images provided by the user.
    * Patches the new firmware (e.g., `boot.img`, `vbmeta_system.img`) to match the device's *current* (higher) index, allowing a downgrade.
6.  **Full Firmware Flashing**
    * Decrypts and patches Lenovo RSA firmware XML files (`*.x` -> `*.xml`).
    * Automates the entire process of converting, patching, and flashing a full ROW firmware, including `devinfo`/`persist` and Anti-Rollback patches.

## 3. Prerequisites

Before you begin, place the required files into the correct folders. The script will guide you if files are missing.

* **For ALL EDL Operations:**
    * The EDL loader file (`xbl_s_devprg_ns.melf`) **MUST** be placed in the `image` folder.

* **For `Patch & Flash ROW ROM` or `Modify xml` (Advanced 8) or `Flash ROM`:**
    * You must copy the **entire `image` folder** from your unpacked Lenovo RSA firmware (the one containing `*.x` files, `*.img` files, etc.) into the LTBox root directory.
    * The script will prompt you for this folder. It is typically found in `C:\ProgramData\RSA\Download\RomFiles\[Firmware_Name]\`.

* **For `Create Rooted boot.img` or `Convert PRC to ROW`:**
    * Place the required source `.img` files (e.g., `vendor_boot.img`, `vbmeta.img`, `boot.img`) into the `image` folder.

* **For `devinfo/persist` patching:**
    * **Advanced 2 (Dump):** Dumps `devinfo.img` and `persist.img` *to* the `backup` folder.
    * **Advanced 3 (Patch):** Reads `devinfo.img` and `persist.img` *from* the `backup` folder, and saves patched versions to `output_dp`.

* **For `Anti-Anti-Rollback`:**
    * These tools require the **new (downgrade)** firmware's `boot.img` and `vbmeta_system.img` to be in the `image` folder for comparison.
    * **Advanced 5 (Detect):** Will automatically dump your *current* device's firmware to `input_current` to perform the comparison.

## 4. How to Use

1.  **Place Files:** Put the necessary files (especially the `image` folder and/or EDL loader) into the correct location as described in **Section 3**.
2.  **Run the Script:** Double-click `start.bat`.
3.  **Select Task:** Choose an option from the menu.
    * **`1` or `2`** for the main tasks.
    * **`a`** to open the Advanced menu for individual steps.
4.  **Get Results:** After a script finishes, the modified images will be saved in a corresponding `output*` folder (e.g., `output`, `output_root`, `output_dp`, `output_anti_rollback`).
5.  **Flash the Images:** The `Patch & Flash` and `Flash ROM` options handle this automatically. You can also flash individual `output*` images manually using the Advanced tools.

## 5. Script Descriptions

* **`start.bat`**: This is the main script you will run. It provides access to all functions.
* **`info_image.bat`**: A separate utility script. Drag & drop `.img` file(s) or folder(s) onto this script to see AVB (Android Verified Boot) information.
    * *Output: `image_info_*.txt`*
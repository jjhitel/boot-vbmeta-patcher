# LTBox

## ⚠️ Important: Disclaimer

**This project is for educational purposes ONLY.**

Modifying your device's firmware carries significant risks, including but not limited to, bricking your device, data loss, or voiding your warranty. The author **assumes no liability** and is not responsible for any **damage or consequence** that may occur to **your device or anyone else's device** from using these scripts.

**You are solely responsible for any consequences. Use at your own absolute risk.**

---

## 1. Core Vulnerability & Overview

This toolkit exploits a security vulnerability found in certain Lenovo Android tablets. These devices have firmware signed with publicly available **AOSP (Android Open Source Project) test keys**.

Because of this vulnerability, the device's bootloader trusts and boots any image signed with these common test keys, even if the bootloader is **locked**.

This toolkit is an all-in-one collection of scripts that leverages this flaw to perform advanced modifications on a device with a locked bootloader.

### Target Models

* Lenovo Legion Y700 (2nd, 3rd, 4th Gen)
* Lenovo Tab Plus AI (aka Yoga Pad Pro AI)
* Lenovo Xiaoxin Pad Pro GT

*...Other recent Lenovo devices (released in 2024 or later with Qualcomm chipsets) may also be vulnerable.*

## 2. Toolkit Purpose & Features

This toolkit provides an all-in-one solution for the following tasks **without unlocking the bootloader**:

1.  **Region Conversion (PRC → ROW):** Converts Chinese (PRC) firmware to Global (ROW) firmware by patching `vendor_boot.img` and rebuilding `vbmeta.img`.

2.  **Get Root Access:** Provides two methods for root access:
    * **LKM Mode:** Patches `init_boot.img` to load KernelSU Next as a Loadable Kernel Module (LKM).
    * **GKI Mode:** Patches `boot.img` by replacing its kernel with [a GKI (Generic Kernel Image) that includes KernelSU](https://github.com/WildKernels/GKI_KernelSU_SUSFS).

3.  **Anti-Rollback Bypass:** Bypasses rollback protection, allowing you to flash older (downgrade) firmware versions by patching the rollback index in `boot.img` and `vbmeta_system.img`.

4.  **Change Region Code:** Patches `devinfo.img` and `persist.img` to change the device's region code.

5.  **Firmware Flashing:** Uses `QSaharaServer` and `fh_loader` to dump partitions and flash modified firmware packages in Emergency Download (EDL) mode.

6.  **Automated Process:** Provides fully automated options to perform region conversion and flashing, with options for both data wipe and data preservation (no wipe).

## 3. How to Use

The toolkit is now centralized into a single menu-driven script.

1.  **Run the Script:** Double-click **`start.bat`**.

2.  **Install Dependencies (First Run):** The first time you run `start.bat`, it will automatically execute `ltbox\install.bat`. This will download and install all required dependencies (Python, `adb`, `avbtool`, `fetch`, etc.) into the `bin/python3/` and `bin/tools/` folders.

3.  **Select Task:** Choose an option from the menu.

    * Main Menu (1, 2, 3...): For common, fully automated tasks.
    * Advanced Menu (a): For manual, step-by-step operations.

4.  **Follow Prompts:** The scripts will prompt you when you need to place files (e.g., "Waiting for image folder...") or connect your device (e.g., "Waiting for ADB/EDL device...").

5.  **Get Results:** After a task finishes, modified images are saved in the corresponding `output*` folder (e.g., `output/`, `output_root_lkm/`).

6.  **Flash the Images:** The Main Menu options (1, 2) and the Advanced Menu "Flash Firmware" option handle this automatically. You can also flash individual `output*` images manually using the Advanced menu options.

## 4. Script Descriptions

### 4.1 Main Menu

These are the primary, automated functions.

**`1. Install firmware to PRC device [WIPE DATA]`**

The all-in-one automated task. It performs all steps (Convert, XML Prepare, Dump, Patch, ARB Check, Flash) and **wipes all user data**. Supports both encrypted (`.x`) and plain (`.xml`) firmware packages.

**`2. Update firmware on PRC device [KEEP DATA]`**

Same as option 1, but modifies the XML scripts to **preserve user data** (skips `userdata` and `metadata` partitions).

**`3. Disable OTA`**

Connects to the device in ADB mode and disables the `com.lenovo.ota` package to prevent automatic system updates.

**`4. Root device`**

Initiates the root process. It will first ask you to select a mode:
* **LKM Mode (init_boot):** Guides you through patching `init_boot.img`.
* **GKI Mode (boot):** Guides you through patching `boot.img`.

This is the all-in-one method to root your device by dumping the image, patching it, and flashing it back.

**`5. Unroot device`**

Restores the device to a non-rooted state. It will ask for the mode (LKM/GKI) to restore the correct stock image (`init_boot.img` or `boot.img`). It looks for backups in `backup_init_boot/` or `backup_boot/`.

**`6. Skip ADB [{skip_adb_state}]`**

Toggles the 'Skip ADB' mode. When ON, all ADB-related steps (like checking device model, rebooting to EDL) are skipped. This is for advanced users who will perform these actions manually (e.g., rebooting with key combos).


### 4.2 Advanced Menu

These are the individual steps, allowing for manual control.

**`1. Convert ROW to PRC in ROM`**

Converts `vendor_boot.img` and rebuilds `vbmeta.img`. (Input: `image/`, Output: `output/`).

**`2. Dump devinfo/persist from device`**

Connect device in EDL mode. Dumps `devinfo` and `persist` to the `backup/` folder.

**`3. Patch devinfo/persist to change region code`**

Patches "CNXX" or other codes in `devinfo.img`/`persist.img`. It will **always prompt** you to select a new country code from a list. (Input: `backup/`, Output: `output_dp/`).

**`4. Write devinfo/persist to device`**

Flashes the patched images from `output_dp/` to the device via EDL.

**`5. Detect Anti-Rollback from device`**

Dumps `boot` and `vbmeta_system` partitions from the device to `backup/`. It then compares their rollback indices to the new ROM in the `image/` folder to check for any index mismatch.

**`6. Patch rollback indices in ROM`**

This step synchronizes the new ROM's rollback index with the device's current index, based on the check from Step 5.
* If the device's index is **higher** (a downgrade attempt), it patches the new ROM's index to match the device's higher index, bypassing anti-rollback to boot.
* If the device's index is **lower** (an upgrade), it patches the new ROM's index to match the device's lower index. This "locks" the device to the older index, making it easy to downgrade back to this version later.
(Input: `image/`, `backup/`, Output: `output_anti_rollback/`).

**`7. Write Anti-Anti-Rollback images to device`**

Flashes the ARB-patched images from `output_anti_rollback/` to the device via EDL.

**`8. Convert X files to XML`**

Processes files from the `image/` folder. If `.x` files (encrypted) are found, they are decrypted into `.xml` files. If `.xml` files are already present, they are moved. (Output: `output_xml/`).

**`9. Modify XML for Flashing [WIPE DATA]`**

Takes the XML files from `output_xml/` and generates `rawprogram_write_persist.xml` and `rawprogram4_write_devinfo.xml` to allow flashing patched `devinfo`/`persist` images.

**`10. Modify XML for Flashing [KEEP DATA]`**

Same as Step 9, but modifies the XMLs to **skip user data partitions** (preserves data).

**`11. Flash firmware to device`**

Manual full flash. This complex step first copies `output/`, `output_anti_rollback/`, `output_xml/`, and `output_dp/` folders into `image/` (overwriting). It then flashes `image/` using `fh_loader`. **Note: This does not flash root images.**

**`12. Clean workspace`**

Deletes all `output*`, `work*`, `image`, `output_xml` folders, and temporary files. Does **not** delete the `backup*/` folders.

## 5. Other Utilities

**`info_image.bat`**

Drag and drop `.img` files or folders containing them onto this batch file. It will run `avbtool.py` to get detailed info (partition name, rollback index, AVB properties) and save it to `image_info_[timestamp].txt`.
import shutil
import os
from pathlib import Path
from typing import Tuple

from .. import constants as const
from .. import utils, device
from ..patch.avb import (
    extract_image_avb_info,
    patch_chained_image_rollback,
    patch_vbmeta_image_rollback,
)
from ..i18n import get_string
from . import system
from . import edl


def read_anti_rollback(
    dumped_boot_path: Path, dumped_vbmeta_path: Path
) -> Tuple[str, int, int]:
    utils.ui.echo(get_string("act_start_arb"))
    utils.check_dependencies()

    current_boot_rb = 0
    current_vbmeta_rb = 0

    utils.ui.echo(get_string("act_arb_step1"))
    try:
        if not dumped_boot_path.exists() or not dumped_vbmeta_path.exists():
            raise FileNotFoundError(get_string("act_err_dumped_missing"))

        utils.ui.echo(
            get_string("act_read_dumped_file").format(name=dumped_boot_path.name)
        )
        boot_info = extract_image_avb_info(dumped_boot_path)
        current_boot_rb = int(boot_info.get("rollback", "0"))

        utils.ui.echo(
            get_string("act_read_dumped_file").format(name=dumped_vbmeta_path.name)
        )
        vbmeta_info = extract_image_avb_info(dumped_vbmeta_path)
        current_vbmeta_rb = int(vbmeta_info.get("rollback", "0"))

    except Exception as e:
        utils.ui.error("\n" + "!" * 61)
        utils.ui.error(get_string("act_err_arb_early_fw"))
        utils.ui.error("!" * 61 + "\n")

        utils.ui.error(get_string("act_err_avb_info").format(e=e))
        utils.ui.echo(get_string("act_arb_error"))
        return "ERROR", 0, 0

    utils.ui.echo(get_string("act_curr_boot_idx").format(idx=current_boot_rb))
    utils.ui.echo(get_string("act_curr_vbmeta_idx").format(idx=current_vbmeta_rb))

    utils.ui.echo(get_string("act_arb_step2"))
    utils.ui.echo(get_string("act_extract_new_indices"))
    new_boot_img = const.IMAGE_DIR / const.FN_BOOT
    new_vbmeta_img = const.IMAGE_DIR / const.FN_VBMETA_SYSTEM

    if not new_boot_img.exists() or not new_vbmeta_img.exists():
        utils.ui.echo(
            get_string("act_err_new_rom_missing").format(dir=const.IMAGE_DIR.name)
        )
        utils.ui.echo(get_string("act_arb_missing_new"))
        return "MISSING_NEW", 0, 0

    new_boot_rb = 0
    new_vbmeta_rb = 0
    try:
        new_boot_info = extract_image_avb_info(new_boot_img)
        new_boot_rb = int(new_boot_info.get("rollback", "0"))

        new_vbmeta_info = extract_image_avb_info(new_vbmeta_img)
        new_vbmeta_rb = int(new_vbmeta_info.get("rollback", "0"))
    except Exception as e:
        utils.ui.error(get_string("act_err_read_new_info").format(e=e))
        utils.ui.echo(get_string("act_arb_error"))
        return "ERROR", 0, 0

    utils.ui.echo(get_string("act_new_boot_idx").format(idx=new_boot_rb))
    utils.ui.echo(get_string("act_new_vbmeta_idx").format(idx=new_vbmeta_rb))

    if new_boot_rb == current_boot_rb and new_vbmeta_rb == current_vbmeta_rb:
        utils.ui.echo(get_string("act_arb_match"))
        status = "MATCH"
    else:
        utils.ui.echo(get_string("act_arb_patch_req"))
        status = "NEEDS_PATCH"

    utils.ui.echo(get_string("act_arb_complete").format(status=status))
    return status, current_boot_rb, current_vbmeta_rb


def patch_anti_rollback(comparison_result: Tuple[str, int, int]) -> None:
    utils.ui.echo(get_string("act_start_arb_patch"))
    utils.check_dependencies()

    if const.OUTPUT_ANTI_ROLLBACK_DIR.exists():
        shutil.rmtree(const.OUTPUT_ANTI_ROLLBACK_DIR)
    const.OUTPUT_ANTI_ROLLBACK_DIR.mkdir(exist_ok=True)

    try:
        if comparison_result:
            utils.ui.echo(get_string("act_use_pre_arb"))
            status, current_boot_rb, current_vbmeta_rb = comparison_result
        else:
            utils.ui.echo(get_string("act_err_no_cmp"))
            return

        if status != "NEEDS_PATCH":
            utils.ui.echo(get_string("act_arb_no_patch"))
            return

        utils.ui.echo(get_string("act_arb_step3"))

        patch_chained_image_rollback(
            image_name=const.FN_BOOT,
            current_rb_index=current_boot_rb,
            new_image_path=(const.IMAGE_DIR / const.FN_BOOT),
            patched_image_path=(const.OUTPUT_ANTI_ROLLBACK_DIR / const.FN_BOOT),
        )

        utils.ui.echo("-" * 20)

        patch_vbmeta_image_rollback(
            image_name=const.FN_VBMETA_SYSTEM,
            current_rb_index=current_vbmeta_rb,
            new_image_path=(const.IMAGE_DIR / const.FN_VBMETA_SYSTEM),
            patched_image_path=(
                const.OUTPUT_ANTI_ROLLBACK_DIR / const.FN_VBMETA_SYSTEM
            ),
        )

        utils.ui.echo("\n  " + "=" * 78)
        utils.ui.echo(get_string("act_success"))
        utils.ui.echo(
            get_string("act_arb_patched_ready").format(
                dir=const.OUTPUT_ANTI_ROLLBACK_DIR.name
            )
        )
        utils.ui.echo("  " + "=" * 78)

    except Exception as e:
        utils.ui.error(get_string("act_err_arb_patch").format(e=e))
        shutil.rmtree(const.OUTPUT_ANTI_ROLLBACK_DIR)


def read_anti_rollback_from_device(dev: device.DeviceController) -> None:
    utils.ui.echo(get_string("act_start_arb"))

    active_slot_suffix = system.detect_active_slot_robust(dev)
    suffix = active_slot_suffix if active_slot_suffix else ""
    boot_target = f"boot{suffix}"
    vbmeta_target = f"vbmeta_system{suffix}"

    edl.dump_partitions(
        dev=dev,
        skip_reset=False,
        additional_targets=[boot_target, vbmeta_target],
        default_targets=False,
    )

    dumped_boot = const.BACKUP_DIR / f"{boot_target}.img"
    dumped_vbmeta = const.BACKUP_DIR / f"{vbmeta_target}.img"

    if not dumped_boot.exists() or not dumped_vbmeta.exists():
        utils.ui.error(get_string("act_err_dumped_missing"))
        raise FileNotFoundError(get_string("act_err_dumped_missing"))

    read_anti_rollback(dumped_boot_path=dumped_boot, dumped_vbmeta_path=dumped_vbmeta)


def patch_anti_rollback_in_rom() -> None:
    utils.ui.echo(get_string("act_start_arb_patch"))

    backup_dir = const.BACKUP_DIR

    boot_files = sorted(
        backup_dir.glob("boot*.img"), key=os.path.getmtime, reverse=True
    )
    vbmeta_files = sorted(
        backup_dir.glob("vbmeta_system*.img"), key=os.path.getmtime, reverse=True
    )

    if not boot_files or not vbmeta_files:
        utils.ui.error(get_string("act_err_dumped_missing"))
        utils.ui.error(get_string("act_arb_run_detect_first"))
        raise FileNotFoundError(get_string("act_err_dumped_missing"))

    dumped_boot = boot_files[0]
    dumped_vbmeta = vbmeta_files[0]

    utils.ui.echo(
        get_string("act_arb_using_dumped_files").format(
            boot=dumped_boot.name, vbmeta=dumped_vbmeta.name
        )
    )

    comparison_result = read_anti_rollback(
        dumped_boot_path=dumped_boot, dumped_vbmeta_path=dumped_vbmeta
    )

    patch_anti_rollback(comparison_result=comparison_result)

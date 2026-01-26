from dataclasses import dataclass
from typing import Callable, List, Optional, Union

from .i18n import get_string


@dataclass(frozen=True)
class MenuItem:
    item_type: str
    key: Optional[str] = None
    text: str = ""
    action: Optional[str] = None

    @classmethod
    def option(cls, key: str, text: str, action: Optional[str] = None) -> "MenuItem":
        return cls(item_type="option", key=key, text=text, action=action)

    @classmethod
    def label(cls, text: str) -> "MenuItem":
        return cls(item_type="label", text=text)

    @classmethod
    def separator(cls) -> "MenuItem":
        return cls(item_type="separator")


@dataclass(frozen=True)
class MenuSpec:
    item_type: str
    key: Optional[str] = None
    text: Optional[Union[str, Callable[[], str]]] = None
    action: Optional[str] = None


def _resolve_text(value: Optional[Union[str, Callable[[], str]]]) -> str:
    if callable(value):
        return value()
    return value or ""


def _build_menu(specs: List[MenuSpec]) -> List[MenuItem]:
    items: List[MenuItem] = []
    for spec in specs:
        if spec.item_type == "separator":
            items.append(MenuItem.separator())
        elif spec.item_type == "label":
            items.append(MenuItem.label(_resolve_text(spec.text)))
        elif spec.item_type == "option":
            items.append(
                MenuItem.option(
                    spec.key or "",
                    _resolve_text(spec.text),
                    action=spec.action,
                )
            )
    return items


def _nav_specs(
    *,
    include_back: bool = False,
    include_return: bool = False,
    include_exit: bool = False,
    return_label_key: str = "menu_root_m",
) -> List[MenuSpec]:
    specs: List[MenuSpec] = []
    if include_back:
        specs.append(
            MenuSpec(
                "option", key="b", text=lambda: get_string("menu_back"), action="back"
            )
        )
    if include_return:
        specs.append(
            MenuSpec(
                "option",
                key="m",
                text=lambda: get_string(return_label_key),
                action="return",
            )
        )
    if include_exit:
        specs.append(
            MenuSpec(
                "option",
                key="x",
                text=lambda: get_string("menu_main_exit"),
                action="exit",
            )
        )
    return specs


def get_advanced_menu_data(target_region: str) -> List[MenuItem]:
    region_text = (
        get_string("menu_adv_1_row")
        if target_region == "ROW"
        else get_string("menu_adv_1_prc")
    )

    specs = [
        MenuSpec("label", text=lambda: get_string("menu_adv_sub_region_dump")),
        MenuSpec("option", key="1", text=region_text, action="convert"),
        MenuSpec("separator"),
        MenuSpec("label", text=lambda: get_string("menu_adv_sub_patch_region")),
        MenuSpec(
            "option",
            key="2",
            text=lambda: get_string("menu_adv_2"),
            action="dump_partitions",
        ),
        MenuSpec(
            "option",
            key="3",
            text=lambda: get_string("menu_adv_3"),
            action="edit_dp",
        ),
        MenuSpec(
            "option",
            key="4",
            text=lambda: get_string("menu_adv_4"),
            action="flash_partitions",
        ),
        MenuSpec("separator"),
        MenuSpec("label", text=lambda: get_string("menu_adv_sub_arb")),
        MenuSpec(
            "option",
            key="5",
            text=lambda: get_string("menu_adv_5"),
            action="read_anti_rollback",
        ),
        MenuSpec(
            "option",
            key="6",
            text=lambda: get_string("menu_adv_6"),
            action="patch_anti_rollback",
        ),
        MenuSpec(
            "option",
            key="7",
            text=lambda: get_string("menu_adv_7"),
            action="write_anti_rollback",
        ),
        MenuSpec("separator"),
        MenuSpec("label", text=lambda: get_string("menu_adv_sub_xml_flash")),
        MenuSpec(
            "option",
            key="8",
            text=lambda: get_string("menu_adv_8"),
            action="decrypt_xml",
        ),
        MenuSpec(
            "option",
            key="9",
            text=lambda: get_string("task_title_modify_xml_wipe"),
            action="modify_xml_wipe",
        ),
        MenuSpec(
            "option",
            key="10",
            text=lambda: get_string("task_title_modify_xml_nowipe"),
            action="modify_xml",
        ),
        MenuSpec(
            "option",
            key="11",
            text=lambda: get_string("menu_adv_11"),
            action="flash_full_firmware",
        ),
        MenuSpec("separator"),
        MenuSpec("label", text=lambda: get_string("menu_adv_sub_nav")),
        *_nav_specs(include_back=True, include_exit=True),
    ]
    return _build_menu(specs)


def get_root_mode_menu_data() -> List[MenuItem]:
    specs = [
        MenuSpec(
            "option",
            key="1",
            text=lambda: get_string("menu_root_mode_1"),
            action="lkm",
        ),
        MenuSpec(
            "option",
            key="2",
            text=lambda: get_string("menu_root_mode_2"),
            action="gki",
        ),
        MenuSpec("separator"),
        *_nav_specs(include_back=True, include_return=True, include_exit=True),
    ]
    return _build_menu(specs)


def get_root_menu_data(gki: bool) -> List[MenuItem]:
    specs: List[MenuSpec] = []
    if gki:
        specs.extend(
            [
                MenuSpec(
                    "option",
                    key="1",
                    text=lambda: get_string("menu_root_1_gki"),
                    action="root_device_gki",
                ),
                MenuSpec(
                    "option",
                    key="2",
                    text=lambda: get_string("menu_root_2_gki"),
                    action="patch_root_image_file_flash_gki",
                ),
            ]
        )
    else:
        specs.extend(
            [
                MenuSpec(
                    "option",
                    key="1",
                    text=lambda: get_string("menu_root_1_lkm"),
                    action="root_device_lkm",
                ),
                MenuSpec(
                    "option",
                    key="2",
                    text=lambda: get_string("menu_root_2_lkm"),
                    action="patch_root_image_file_flash_lkm",
                ),
            ]
        )

    specs.extend(
        [
            MenuSpec("separator"),
            *_nav_specs(include_back=True, include_return=True, include_exit=True),
        ]
    )
    return _build_menu(specs)


def get_settings_menu_data(
    skip_adb_state: str, skip_rb_state: str, target_region: str
) -> List[MenuItem]:
    region_label = (
        get_string("menu_settings_device_row")
        if target_region == "ROW"
        else get_string("menu_settings_device_prc")
    )

    specs = [
        MenuSpec("option", key="1", text=region_label, action="toggle_region"),
        MenuSpec(
            "option",
            key="2",
            text=lambda: get_string("menu_settings_skip_adb").format(
                state=skip_adb_state
            ),
            action="toggle_adb",
        ),
        MenuSpec(
            "option",
            key="3",
            text=lambda: get_string("menu_settings_skip_rb").format(
                state=skip_rb_state
            ),
            action="toggle_rollback",
        ),
        MenuSpec(
            "option",
            key="4",
            text=lambda: get_string("menu_settings_lang"),
            action="change_lang",
        ),
        MenuSpec(
            "option",
            key="5",
            text=lambda: get_string("menu_settings_check_update"),
            action="check_update",
        ),
        MenuSpec("separator"),
        *_nav_specs(include_back=True),
    ]
    return _build_menu(specs)


def get_main_menu_data(target_region: str) -> List[MenuItem]:
    if target_region == "ROW":
        install_wipe_text = get_string("menu_main_install_wipe_row")
        install_keep_text = get_string("menu_main_install_keep_row")
    else:
        install_wipe_text = get_string("menu_main_install_wipe_prc")
        install_keep_text = get_string("menu_main_install_keep_prc")

    specs = [
        MenuSpec("option", key="1", text=install_wipe_text, action="patch_all_wipe"),
        MenuSpec("option", key="2", text=install_keep_text, action="patch_all"),
        MenuSpec("separator"),
        MenuSpec(
            "option",
            key="3",
            text=lambda: get_string("menu_main_rescue"),
            action="rescue_ota",
        ),
        MenuSpec(
            "option",
            key="4",
            text=lambda: get_string("menu_main_disable_ota"),
            action="disable_ota",
        ),
        MenuSpec("separator"),
        MenuSpec(
            "option",
            key="5",
            text=lambda: get_string("menu_main_root"),
            action="menu_root",
        ),
        MenuSpec(
            "option",
            key="6",
            text=lambda: get_string("menu_main_unroot"),
            action="unroot_device",
        ),
        MenuSpec(
            "option",
            key="7",
            text=lambda: get_string("menu_main_rec_flash"),
            action="sign_and_flash_twrp",
        ),
        MenuSpec("separator"),
        MenuSpec(
            "option",
            key="0",
            text=lambda: get_string("menu_settings_title"),
            action="menu_settings",
        ),
        MenuSpec(
            "option",
            key="a",
            text=lambda: get_string("menu_main_adv"),
            action="menu_advanced",
        ),
        *_nav_specs(include_exit=True),
    ]
    return _build_menu(specs)

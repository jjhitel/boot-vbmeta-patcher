import sys
import os
import pytest
import shutil
import xml.etree.ElementTree as ET
from unittest.mock import patch, MagicMock

sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '../bin')))

from ltbox import constants as const
from ltbox.actions import edl, xml as xml_action
from ltbox.patch import region as region_patch

def create_xmls(img_dir, names):
    for n in names:
        (img_dir / n).touch()

def test_xml_select(mock_env):
    img_dir = mock_env["IMAGE_DIR"]
    files = [
        "rawprogram0.xml",
        "rawprogram1.xml",
        "rawprogram_unsparse0.xml",
        "rawprogram_save_persist_unsparse0.xml",
        "rawprogram_WIPE_PARTITIONS.xml",
        "patch0.xml"
    ]
    create_xmls(img_dir, files)

    with patch("ltbox.actions.edl.utils.ui"):
        raw, patch_files = edl._select_flash_xmls(skip_dp=False)

    r_names = [p.name for p in raw]
    p_names = [p.name for p in patch_files]

    assert "rawprogram_WIPE_PARTITIONS.xml" not in r_names
    assert "rawprogram0.xml" not in r_names
    assert "rawprogram1.xml" in r_names
    assert "rawprogram_save_persist_unsparse0.xml" in r_names
    assert "rawprogram_unsparse0.xml" not in r_names
    assert "patch0.xml" in p_names

def test_flash_args(mock_env):
    img_dir = mock_env["IMAGE_DIR"]
    files = ["rawprogram1.xml", "rawprogram_unsparse0.xml", "patch0.xml"]
    create_xmls(img_dir, files)

    mock_dev = MagicMock()

    with patch("ltbox.actions.edl.utils.ui"), \
         patch("ltbox.actions.edl.ensure_loader_file"), \
         patch("ltbox.actions.edl._prepare_flash_files"), \
         patch("builtins.input", return_value="y"):

        edl.flash_full_firmware(mock_dev, skip_reset=True, skip_reset_edl=False)

        args, _ = mock_dev.edl.flash_rawprogram.call_args
        passed = [p.name for p in args[3]]

        assert "rawprogram_unsparse0.xml" in passed
        assert len(passed) == 2

def test_xml_fallback(mock_env):
    out_dir = mock_env["OUTPUT_XML_DIR"]
    target = out_dir / "rawprogram_save_persist_unsparse0.xml"

    cases = [
        (["rawprogram_unsparse0.xml", "rawprogram0.xml"], "rawprogram_unsparse0.xml", "A"),
        (["rawprogram0.xml"], "rawprogram0.xml", "B")
    ]
    tmpl = """<?xml version="1.0" ?><data><program label="{m}" filename=""/></data>"""

    for fnames, expected, marker in cases:
        if target.exists(): target.unlink()
        for f in out_dir.glob("*.xml"): f.unlink()

        for fn in fnames:
            m = marker if fn == expected else "X"
            (out_dir / fn).write_text(tmpl.format(m=m))

        with patch("ltbox.actions.xml.utils.ui"):
            xml_action._ensure_rawprogram_save_persist(out_dir)

        assert target.exists()
        root = ET.parse(target).getroot()
        assert root.find("program").get("label") == marker

def test_xml_wipe(fw_pkg):
    path = fw_pkg.get("rawprogram_unsparse0.xml")
    if not path: pytest.skip("XML not found")

    tmp_xml = path.parent / "test_wipe.xml"
    shutil.copy(path, tmp_xml)

    with patch("ltbox.actions.xml.utils.ui"):
        xml_action._patch_xml_for_wipe(tmp_xml, wipe=0)

    root = ET.parse(tmp_xml).getroot()
    progs = [p for p in root.findall("program") if p.get("label") == "userdata"]
    assert len(progs) > 0
    for p in progs:
        assert p.get("filename") == ""

def test_xml_persist_check(fw_pkg):
    path = fw_pkg.get("rawprogram_save_persist_unsparse0.xml")
    if not path: pytest.skip("Persist XML not found")

    root = ET.parse(path).getroot()
    p = next((x for x in root.findall("program") if x.get("label") == "persist"), None)
    if p:
        assert p.get("filename", "") == ""

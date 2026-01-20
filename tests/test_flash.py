import sys
import os
import pytest
from unittest.mock import patch, MagicMock
from pathlib import Path

sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '../bin')))

from ltbox.actions import edl

class TestFlashSafety:

    @pytest.fixture
    def mock_env(self, tmp_path):
        dirs = {
            "IMAGE_DIR": tmp_path / "image",
            "OUTPUT_DP_DIR": tmp_path / "output_dp",
            "OUTPUT_DIR": tmp_path / "output",
            "OUTPUT_ANTI_ROLLBACK_DIR": tmp_path / "output_arb",
            "OUTPUT_XML_DIR": tmp_path / "output_xml",
            "EDL_LOADER_FILE": tmp_path / "xbl_s_devprg_ns.melf"
        }
        for d in dirs.values():
            if d.suffix:
                d.parent.mkdir(parents=True, exist_ok=True)
                d.touch()
            else:
                d.mkdir(parents=True, exist_ok=True)

        with patch.multiple("ltbox.constants", **dirs):
            yield dirs

    def create_dummy_xmls(self, image_dir, filenames):
        for name in filenames:
            (image_dir / name).touch()

    def test_select_flash_xmls_safety(self, mock_env):
        image_dir = mock_env["IMAGE_DIR"]

        dirty_files = [
            "rawprogram0.xml",
            "rawprogram1.xml",
            "rawprogram_unsparse0.xml",
            "rawprogram_save_persist_unsparse0.xml",
            "rawprogram_WIPE_PARTITIONS.xml",
            "patch0.xml"
        ]
        self.create_dummy_xmls(image_dir, dirty_files)

        with patch("ltbox.actions.edl.utils.ui"):
            raw_xmls, patch_xmls = edl._select_flash_xmls(skip_dp=False)

        raw_names = [p.name for p in raw_xmls]
        patch_names = [p.name for p in patch_xmls]

        assert "rawprogram_WIPE_PARTITIONS.xml" not in raw_names, "Dangerous XML was selected!"

        assert "rawprogram0.xml" not in raw_names

        assert "rawprogram1.xml" in raw_names

        assert "rawprogram_save_persist_unsparse0.xml" in raw_names
        assert "rawprogram_unsparse0.xml" not in raw_names, "Conflict: Multiple main XMLs selected!"

        assert "patch0.xml" in patch_names

    def test_flash_full_firmware_arguments(self, mock_env):
        image_dir = mock_env["IMAGE_DIR"]

        files = ["rawprogram1.xml", "rawprogram_unsparse0.xml", "patch0.xml"]
        self.create_dummy_xmls(image_dir, files)

        mock_dev = MagicMock()

        with patch("ltbox.actions.edl.utils.ui") as mock_ui, \
             patch("ltbox.actions.edl.ensure_loader_file"), \
             patch("ltbox.actions.edl._prepare_flash_files"), \
             patch("builtins.input", return_value="y"):

            edl.flash_full_firmware(mock_dev, skip_reset=True, skip_reset_edl=False)

            args, _ = mock_dev.edl.flash_rawprogram.call_args

            passed_raw_xmls = [p.name for p in args[3]]

            assert "rawprogram_unsparse0.xml" in passed_raw_xmls
            assert len(passed_raw_xmls) == 2

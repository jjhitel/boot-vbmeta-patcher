import sys
import os
import pytest
from unittest.mock import patch

sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '../bin')))

from ltbox.patch import avb

def test_vbmeta_parse(fw_pkg):
    path = fw_pkg.get("vbmeta.img")
    assert path and path.exists()

    info = avb.extract_image_avb_info(path)
    assert info["algorithm"] == "SHA256_RSA4096"
    assert "partition_size" in info

def test_boot_parse(fw_pkg):
    path = fw_pkg.get("boot.img")
    assert path and path.exists()

    info = avb.extract_image_avb_info(path)
    assert int(info["partition_size"]) > int(info["data_size"])

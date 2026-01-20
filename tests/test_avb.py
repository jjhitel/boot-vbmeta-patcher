import sys
import os
import pytest
from unittest.mock import patch

sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '../bin')))

from ltbox.patch import avb

REAL_VBMETA_OUTPUT = """
Minimum libavb version:   1.0
Header Block:             256 bytes
Authentication Block:     576 bytes
Auxiliary Block:          7488 bytes
Public key (sha1):        2597c218aae470a130f61162feaae70afd97f011
Algorithm:                SHA256_RSA4096
Rollback Index:           0
Flags:                    0
Rollback Index Location:  0
Release String:           'avbtool 1.3.0'
Descriptors:
    Chain Partition descriptor:
      Partition Name:          boot
      Rollback Index Location: 3
      Public key (sha1):       2597c218aae470a130f61162feaae70afd97f011
      Flags:                   0
    Hashtree descriptor:
      Partition Name:          vendor
      Salt:                  0bb3b6a56f00a1a1928851532d60ccb8cacd1e020d04e84d3ecc1020809005d9
      Image Size:            1510338560 bytes
"""

REAL_BOOT_OUTPUT = """
Footer version:           1.0
Image size:               100663296 bytes
Original image size:      36483072 bytes
VBMeta offset:            36483072
VBMeta size:              2432 bytes
--
Minimum libavb version:   1.0
Header Block:             256 bytes
Authentication Block:     576 bytes
Auxiliary Block:          1600 bytes
Public key (sha1):        2597c218aae470a130f61162feaae70afd97f011
Algorithm:                SHA256_RSA4096
Rollback Index:           1738713600
Flags:                    0
Rollback Index Location:  0
Release String:           'avbtool 1.3.0'
Descriptors:
    Hash descriptor:
      Image Size:            36483072 bytes
      Hash Algorithm:        sha256
      Partition Name:        boot
      Salt:                  1111222233334444555566667777888899990000AAAABBBBCCCCDDDDEEEEFFFF
      Digest:                ab34c56d...
"""

REAL_VENDOR_BOOT_OUTPUT = """
Footer version:           1.0
Image size:               100663296 bytes
Original image size:      15155200 bytes
VBMeta offset:            15155200
VBMeta size:              704 bytes
--
Minimum libavb version:   1.0
Header Block:             256 bytes
Authentication Block:     0 bytes
Auxiliary Block:          448 bytes
Algorithm:                NONE
Rollback Index:           0
Flags:                    0
Rollback Index Location:  0
Release String:           'avbtool 1.3.0'
Descriptors:
    Hash descriptor:
      Image Size:            15155200 bytes
      Hash Algorithm:        sha256
      Partition Name:        vendor_boot
      Salt:                  DEADBEEFDEADBEEFDEADBEEFDEADBEEFDEADBEEFDEADBEEFDEADBEEFDEADBEEF
      Digest:                3469e58d...
"""

class TestRealAvbParsing:

    def test_extract_real_vbmeta_info(self):
        with patch("ltbox.patch.avb.utils.run_command") as mock_run:
            mock_run.return_value.stdout = REAL_VBMETA_OUTPUT.strip()

            info = avb.extract_image_avb_info("vbmeta.img")

            assert info["algorithm"] == "SHA256_RSA4096"
            assert info["name"] == "boot"
            assert info["data_size"] == "1510338560"

    def test_extract_real_boot_info(self):
        with patch("ltbox.patch.avb.utils.run_command") as mock_run:
            mock_run.return_value.stdout = REAL_BOOT_OUTPUT.strip()

            info = avb.extract_image_avb_info("boot.img")

            assert info["partition_size"] == "100663296"
            assert info["data_size"] == "36483072"

            assert info["algorithm"] == "SHA256_RSA4096"
            assert info["rollback"] == "1738713600"

            assert info["name"] == "boot"
            assert info["salt"] == "1111222233334444555566667777888899990000AAAABBBBCCCCDDDDEEEEFFFF"

    def test_extract_real_vendor_boot_info(self):
        with patch("ltbox.patch.avb.utils.run_command") as mock_run:
            mock_run.return_value.stdout = REAL_VENDOR_BOOT_OUTPUT.strip()

            info = avb.extract_image_avb_info("vendor_boot.img")

            assert info["algorithm"] == "NONE"

            assert info["partition_size"] == "100663296"
            assert info["data_size"] == "15155200"

            assert info["name"] == "vendor_boot"
            assert info["salt"] == "DEADBEEFDEADBEEFDEADBEEFDEADBEEFDEADBEEFDEADBEEFDEADBEEFDEADBEEF"

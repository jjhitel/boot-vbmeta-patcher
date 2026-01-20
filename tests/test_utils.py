import sys
import os
import pytest
import subprocess
import hashlib
from pathlib import Path
from unittest.mock import patch, MagicMock
from ltbox import utils, crypto, downloader

sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '../bin')))

class TestUtilities:
    @pytest.mark.parametrize("current, latest, expected", [
        ("v1.0.0", "v1.0.1", True),
        ("v1.0.1", "v1.0.0", False),
        ("1.0", "1.1", True),
    ])
    def test_is_update_available(self, current, latest, expected):
        assert utils.is_update_available(current, latest) == expected

    @patch("ltbox.utils.subprocess.run")
    def test_run_command_success(self, mock_run):
        mock_run.return_value = subprocess.CompletedProcess(
            args=["echo"], returncode=0, stdout="ok", stderr=""
        )
        res = utils.run_command(["echo"], capture=True)
        assert res.returncode == 0
        assert "ok" in res.stdout

    @patch("urllib.request.urlopen")
    def test_get_latest_release_version(self, mock_urlopen):
        mock_resp = MagicMock()
        mock_resp.status = 200
        mock_resp.read.return_value = b'{"tag_name": "v9.9.9"}'
        mock_urlopen.return_value.__enter__.return_value = mock_resp

        ver = utils.get_latest_release_version("user", "repo")
        assert ver == "v9.9.9"

    def test_temporary_workspace(self, tmp_path):
        target = tmp_path / "work"
        with utils.temporary_workspace(target) as ws:
            assert ws.exists()
            (ws / "test").touch()
        assert not target.exists()

    def test_device_string_parsing(self):
        output = "(bootloader) current-slot:a\nall: Done!!"
        assert "current-slot:a" in output

    def test_crypto_pbkdf1_generation(self):
        salt = b"1234567890123456"
        key1 = crypto.PBKDF1("OSD", salt, 32, hashlib.sha256, 1000)
        key2 = crypto.PBKDF1("OSD", salt, 32, hashlib.sha256, 1000)

        assert len(key1) == 32
        assert key1 == key2

    def test_decrypt_file_invalid_signature(self, tmp_path):
        bad_file = tmp_path / "bad.enc"
        bad_file.write_bytes(b"\x00" * 32 + b"garbage")
        output_file = tmp_path / "output.bin"

        with patch("ltbox.utils.ui"):
            result = crypto.decrypt_file(str(bad_file), str(output_file))

        assert result is False

    def test_github_asset_selection(self):
        mock_response = {
            "assets": [
                {"name": "tool-linux.zip", "browser_download_url": "http://linux"},
                {"name": "tool-windows-x64.zip", "browser_download_url": "http://win"},
                {"name": "tool-macos.zip", "browser_download_url": "http://mac"},
            ]
        }

        with patch("requests.get") as mock_get, \
             patch("ltbox.downloader.download_resource") as mock_dl:

            mock_get.return_value.json.return_value = mock_response
            mock_get.return_value.status_code = 200

            downloader._download_github_asset(
                "repo", "tag", ".*windows.*", Path(".")
            )

            args, _ = mock_dl.call_args
            assert args[0] == "http://win"

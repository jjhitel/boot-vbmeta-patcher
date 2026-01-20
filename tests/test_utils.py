import subprocess
import sys
import os
from unittest.mock import patch, MagicMock
import pytest

sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '../bin')))

from ltbox.utils import run_command

@patch("ltbox.utils.subprocess.run")
def test_run_command_success(mock_run):
    mock_run.return_value = subprocess.CompletedProcess(
        args=["adb", "devices"], returncode=0, stdout="List of devices attached\n", stderr=""
    )

    result = run_command(["adb", "devices"], capture=True)

    assert result.returncode == 0
    assert "List of devices attached" in result.stdout
    mock_run.assert_called_once()

@patch("ltbox.utils.subprocess.Popen")
def test_run_command_failure(mock_popen):
    process_mock = MagicMock()
    process_mock.returncode = 1
    process_mock.stdout = iter(["Error occurred\n"])
    process_mock.wait.return_value = None
    mock_popen.return_value = process_mock

    with pytest.raises(subprocess.CalledProcessError):
        run_command(["adb", "faulty_command"])

import pytest
from unittest.mock import MagicMock, patch
from ltbox.device import AdbManager, DeviceConnectionError

def test_adb_get_model_retry_success():
    manager = AdbManager(skip_adb=False)

    mock_device = MagicMock()
    mock_device.get_state.return_value = "device"
    mock_device.prop.model = "Lenovo TB-Test"

    with patch("adbutils.adb.device_list", side_effect=[[], [], [mock_device]]), \
         patch("ltbox.device.time.sleep", return_value=None):

        model = manager.get_model()
        assert model == "Lenovo TB-Test"

def test_fastboot_slot_detection_failure():
    from ltbox.device import FastbootManager, DeviceCommandError
    import subprocess

    manager = FastbootManager()

    with patch("ltbox.utils.run_command", side_effect=subprocess.CalledProcessError(1, "cmd")):
        with pytest.raises(DeviceCommandError):
            manager.get_slot_suffix()

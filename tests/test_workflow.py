from unittest.mock import MagicMock, patch, call
from ltbox import workflow
from ltbox.context import TaskContext

def test_patch_all_flow_standard(mock_env):
    mock_dev = MagicMock()
    mock_dev.skip_adb = False
    mock_dev.detect_active_slot.return_value = "_a"
    mock_dev.adb.get_model.return_value = "TestModel"

    with patch("ltbox.workflow.actions") as mock_actions, \
         patch("ltbox.workflow.utils.ui"), \
         patch("ltbox.workflow._wait_for_input_images"), \
         patch("ltbox.workflow._cleanup_previous_outputs"):

        mock_actions.read_anti_rollback.return_value = ("OK", "PASS")

        workflow.patch_all(dev=mock_dev, wipe=0, target_region="PRC")

        mock_actions.convert_region_images.assert_called_once()

        mock_actions.dump_partitions.assert_called_once()

        mock_actions.read_anti_rollback.assert_called_once()

        mock_actions.flash_full_firmware.assert_called_once()

def test_patch_all_skip_arb():
    mock_dev = MagicMock()
    with patch("ltbox.workflow.actions") as mock_actions, \
         patch("ltbox.workflow.utils.ui"), \
         patch("ltbox.workflow._wait_for_input_images"), \
         patch("ltbox.workflow._cleanup_previous_outputs"):

        workflow.patch_all(dev=mock_dev, skip_rollback=True)

        mock_actions.read_anti_rollback.assert_not_called()

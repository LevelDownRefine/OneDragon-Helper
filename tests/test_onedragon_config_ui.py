import unittest
from unittest.mock import patch, MagicMock
from config import onedragon_config_ui

class TestOnedragonConfigUI(unittest.TestCase):

    @patch('config.onedragon_config_ui.QApplication')
    @patch('config.onedragon_config_ui.ConfigUI')
    def test_run_config_ui(self, mock_config_ui, mock_qapp):
        # Verify run_config_ui works and instantiates QApplication and ConfigUI correctly
        onedragon_config_ui.run_config_ui("/mock/config.yml")
        mock_qapp.assert_called_once()
        mock_config_ui.assert_called_once_with("/mock/config.yml")

    @patch('sys.stderr')
    def test_run_config_ui_invalid_path(self, mock_stderr):
        # Verify that run_config_ui raises SystemExit when yml_path is invalid or empty
        # and writes appropriate error message to sys.stderr
        invalid_inputs = [None, "", "   ", 123, [], {}, False]
        for val in invalid_inputs:
            mock_stderr.write.reset_mock()
            with self.assertRaises(SystemExit) as cm:
                onedragon_config_ui.run_config_ui(val)
            self.assertEqual(cm.exception.code, 1)
            mock_stderr.write.assert_called()
            # Verify that the printed error message contains "Error:" or "错误:"
            called_args = [call[0][0] for call in mock_stderr.write.call_args_list]
            self.assertTrue(any("Error:" in arg or "错误:" in arg for arg in called_args))

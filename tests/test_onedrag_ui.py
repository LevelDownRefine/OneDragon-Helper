import unittest
from unittest.mock import patch, MagicMock
from config import onedrag_ui

class TestOnedragonConfigUI(unittest.TestCase):

    @patch('config.onedrag_ui.QApplication')
    @patch('config.onedrag_ui.ConfigUI')
    def test_run_config_ui(self, mock_config_ui, mock_qapp):
        # Verify run_config_ui works and instantiates QApplication and ConfigUI correctly
        onedrag_ui.run_config_ui("/mock/config.yml")
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
                onedrag_ui.run_config_ui(val)
            self.assertEqual(cm.exception.code, 1)
            mock_stderr.write.assert_called()
            # Verify that the printed error message contains "Error:" or "错误:"
            called_args = [call[0][0] for call in mock_stderr.write.call_args_list]
            self.assertTrue(any("Error:" in arg or "错误:" in arg for arg in called_args))
            
            # Verify type-specific error messages
            full_msg = "".join(called_args)
            if not isinstance(val, str):
                self.assertTrue("must be a string" in full_msg or "必须是字符串" in full_msg)
            else:
                self.assertTrue("is not specified" in full_msg or "未指定" in full_msg)

    @patch('config.onedrag_ui.QApplication')
    @patch('config.onedrag_ui.ConfigUI')
    def test_run_config_ui_happy_path_no_exit(self, mock_config_ui, mock_qapp):
        # Verify that a valid yml_path does not raise SystemExit or call sys.exit
        try:
            onedrag_ui.run_config_ui("/mock/config.yml")
        except SystemExit:
            self.fail("run_config_ui raised SystemExit on a valid yml_path string")

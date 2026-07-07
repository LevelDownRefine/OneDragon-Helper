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
        with self.assertRaises(SystemExit) as cm:
            onedragon_config_ui.run_config_ui(None)
        self.assertEqual(cm.exception.code, 1)

        with self.assertRaises(SystemExit) as cm:
            onedragon_config_ui.run_config_ui("")
        self.assertEqual(cm.exception.code, 1)

        with self.assertRaises(SystemExit) as cm:
            onedragon_config_ui.run_config_ui("   ")
        self.assertEqual(cm.exception.code, 1)

        with self.assertRaises(SystemExit) as cm:
            onedragon_config_ui.run_config_ui(123)
        self.assertEqual(cm.exception.code, 1)

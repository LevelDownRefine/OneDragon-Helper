import unittest
from unittest.mock import patch, MagicMock
from config import onedrag_ui

class TestOnedragonConfigUI(unittest.TestCase):

    @patch('config.onedrag_ui.get_config_yml_path_under_root')
    @patch('config.onedrag_ui.QApplication')
    @patch('config.onedrag_ui.ConfigUI')
    def test_run_config_ui(self, mock_config_ui, mock_qapp, mock_get_path):
        mock_get_path.return_value = "/mock/config.yml"
        onedrag_ui.run_config_ui()
        mock_qapp.assert_called_once()
        mock_config_ui.assert_called_once()

    @patch('config.onedrag_ui.QApplication')
    @patch('config.onedrag_ui.ConfigUI')
    def test_run_config_ui_happy_path_no_exit(self, mock_config_ui, mock_qapp):
        try:
            onedrag_ui.run_config_ui()
        except SystemExit:
            self.fail("run_config_ui raised SystemExit unexpectedly")

if __name__ == "__main__":
    unittest.main()

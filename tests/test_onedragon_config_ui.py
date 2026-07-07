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

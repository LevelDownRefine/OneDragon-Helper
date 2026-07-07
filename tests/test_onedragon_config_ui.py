import os
import sys
import unittest
from unittest.mock import patch, MagicMock

# Global reference to target module and original modules dictionary
onedragon_config_ui = None
original_modules = {}

def setUpModule():
    global onedragon_config_ui
    # Mock PySide6 and qfluentwidgets to avoid ModuleNotFoundError when importing onedragon_config_ui
    for mod in ['PySide6', 'PySide6.QtWidgets', 'PySide6.QtGui', 'qfluentwidgets']:
        original_modules[mod] = sys.modules.get(mod)
        sys.modules[mod] = MagicMock()
    
    from config import onedragon_config_ui as ocu
    onedragon_config_ui = ocu

def tearDownModule():
    # Restore original modules to avoid affecting other tests in the same process
    for mod, orig in original_modules.items():
        if orig is None:
            sys.modules.pop(mod, None)
        else:
            sys.modules[mod] = orig

class TestOnedragonConfigUI(unittest.TestCase):

    @patch('config.onedragon_config_ui.QApplication')
    @patch('config.onedragon_config_ui.ConfigUI')
    def test_run_config_ui(self, mock_config_ui, mock_qapp):
        # Verify run_config_ui works and instantiates QApplication and ConfigUI correctly
        onedragon_config_ui.run_config_ui("/mock/config.yml")
        mock_qapp.assert_called_once()
        mock_config_ui.assert_called_once_with("/mock/config.yml")

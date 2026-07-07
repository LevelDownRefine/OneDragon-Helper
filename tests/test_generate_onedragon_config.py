import os
import sys
import unittest
import tempfile
import shutil
from unittest.mock import patch, MagicMock

# Global reference to target module and original modules dictionary
generate_onedragon_config = None
original_modules = {}

def setUpModule():
    global generate_onedragon_config
    # Mock PySide6 and qfluentwidgets to avoid ModuleNotFoundError when importing generate_onedragon_config
    for mod in ['PySide6', 'PySide6.QtWidgets', 'PySide6.QtGui', 'qfluentwidgets']:
        original_modules[mod] = sys.modules.get(mod)
        sys.modules[mod] = MagicMock()
    
    from config import generate_onedragon_config as goc
    generate_onedragon_config = goc

def tearDownModule():
    # Restore original modules to avoid affecting other tests in the same process
    for mod, orig in original_modules.items():
        if orig is None:
            sys.modules.pop(mod, None)
        else:
            sys.modules[mod] = orig

class TestGenerateOnedragonConfig(unittest.TestCase):

    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp_dir.cleanup)
        
        # Create temp source directory and target directory
        self.src_dir = os.path.join(self.temp_dir.name, "python_script")
        self.dest_dir = os.path.join(self.temp_dir.name, "scripts")
        os.makedirs(self.src_dir, exist_ok=True)
        os.makedirs(self.dest_dir, exist_ok=True)
        
        # Create a dummy script file in source
        self.dummy_script_name = "test_script.py"
        with open(os.path.join(self.src_dir, self.dummy_script_name), "w") as f:
            f.write("# Dummy python script")

    @patch('config.generate_onedragon_config.get_path_under_root')
    @patch('config.generate_onedragon_config.get_path_under_onedragon')
    def test_copy_python_scripts_not_exists(self, mock_get_path, mock_get_root):
        mock_get_root.return_value = self.src_dir
        mock_get_path.return_value = self.dest_dir
        
        # The file does not exist in destination yet
        self.assertFalse(os.path.exists(os.path.join(self.dest_dir, self.dummy_script_name)))
        
        generate_onedragon_config.copy_python_scripts()
        
        # Verify file is copied
        self.assertTrue(os.path.exists(os.path.join(self.dest_dir, self.dummy_script_name)))

    @patch('config.generate_onedragon_config.get_path_under_root')
    @patch('config.generate_onedragon_config.get_path_under_onedragon')
    @patch('shutil.copy')
    def test_copy_python_scripts_already_exists(self, mock_copy, mock_get_path, mock_get_root):
        mock_get_root.return_value = self.src_dir
        mock_get_path.return_value = self.dest_dir
        
        # Pre-create the file in destination
        with open(os.path.join(self.dest_dir, self.dummy_script_name), "w") as f:
            f.write("# Pre-existing script")
            
        generate_onedragon_config.copy_python_scripts()
        
        # shutil.copy should not be called
        mock_copy.assert_not_called()

    @patch('config.generate_onedragon_config.copy_python_scripts')
    @patch('config.generate_onedragon_config.run_config_ui')
    @patch('config.generate_onedragon_config.get_onedragon_yml_path_under_root')
    def test_config_workflow(self, mock_get_yml, mock_run_ui, mock_copy):
        mock_get_yml.return_value = "/mock/config.yml"
        
        generate_onedragon_config.config_workflow()
        
        mock_copy.assert_called_once()
        mock_run_ui.assert_called_once_with("/mock/config.yml")

if __name__ == "__main__":
    unittest.main()

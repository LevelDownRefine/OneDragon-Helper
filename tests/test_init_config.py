import os
import tempfile
import unittest
from unittest.mock import patch

from config import init_config


class TestGenerateInitConfig(unittest.TestCase):

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

    @patch('config.init_config.get_path_under_root')
    @patch('config.init_config.get_path_under_onedragon')
    def test_copy_python_scripts_not_exists(self, mock_get_path, mock_get_root):
        mock_get_root.return_value = self.src_dir
        mock_get_path.return_value = self.dest_dir

        # The file does not exist in destination yet
        self.assertFalse(os.path.exists(os.path.join(self.dest_dir, self.dummy_script_name)))

        init_config.copy_python_scripts()

        # Verify file is copied
        self.assertTrue(os.path.exists(os.path.join(self.dest_dir, self.dummy_script_name)))

    @patch('config.init_config.get_path_under_root')
    @patch('config.init_config.get_path_under_onedragon')
    @patch('shutil.copy')
    def test_copy_python_scripts_already_exists(self, mock_copy, mock_get_path, mock_get_root):
        mock_get_root.return_value = self.src_dir
        mock_get_path.return_value = self.dest_dir

        # Pre-create the file in destination
        with open(os.path.join(self.dest_dir, self.dummy_script_name), "w") as f:
            f.write("# Pre-existing script")

        init_config.copy_python_scripts()

        # shutil.copy should not be called
        mock_copy.assert_not_called()

    @patch('config.init_config.shutil.copy')
    @patch('config.init_config.os.path.exists', return_value=False)
    @patch('config.init_config.copy_python_scripts')
    @patch('config.init_config.copy_BGI_User')
    @patch('config.init_config.get_config_yml_path_under_root')
    def test_config_workflow(self, mock_config_path, mock_bgi, mock_copy, mock_exists, mock_shutil_copy):
        mock_config_path.return_value = os.path.join(self.temp_dir.name, "config.yml")
        init_config.config_workflow()

        mock_bgi.assert_called_once()
        mock_copy.assert_called_once()
        # config.yml 不存在时，应从模板复制
        mock_shutil_copy.assert_called_once()


if __name__ == "__main__":
    unittest.main()

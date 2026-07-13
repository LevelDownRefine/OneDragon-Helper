import os
import unittest
import tempfile
import yaml
from unittest.mock import patch

from config import bgi

class TestCopyBettergiConfig(unittest.TestCase):

    def setUp(self):
        # Create a temporary directory structure for our tests
        self.temp_dir = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp_dir.cleanup)
        
        # Paths for mock config, mock BGI sources, etc.
        self.mock_config_path = os.path.join(self.temp_dir.name, "config.yml")
        self.mock_our_bgi_dir = os.path.join(self.temp_dir.name, "BGI_User")
        os.makedirs(self.mock_our_bgi_dir, exist_ok=True)
        
        # Put a dummy file inside mock_our_bgi_dir to test file copying
        with open(os.path.join(self.mock_our_bgi_dir, "test_file.json"), "w") as f:
            f.write('{"test": true}')

    @patch('config.bgi.get_config_yml_path_under_root')
    def test_get_BGI_user_dir_success(self, mock_get_yml):
        mock_get_yml.return_value = self.mock_config_path
        
        # Case 1: '原神' exists in script_list
        config_data = {
            'script_list': [
                {
                    'display_name': '鸣潮',
                    'script_path': 'C:\\Games\\ok-ww\\ok-ww.exe'
                },
                {
                    'display_name': '原神',
                    'script_path': os.path.join(self.temp_dir.name, 'BetterGI', 'BetterGI.exe')
                }
            ]
        }
        with open(self.mock_config_path, 'w', encoding='utf-8') as f:
            yaml.dump(config_data, f)
            
        res = bgi.get_BGI_user_dir()
        expected = os.path.join(self.temp_dir.name, 'BetterGI', 'User')
        self.assertEqual(os.path.normpath(res), os.path.normpath(expected))

    @patch('config.bgi.get_config_yml_path_under_root')
    def test_get_BGI_user_dir_not_found(self, mock_get_yml):
        mock_get_yml.return_value = self.mock_config_path
        
        # Case 2: '原神' does not exist in script_list
        config_data = {
            'script_list': [
                {
                    'display_name': '鸣潮',
                    'script_path': 'C:\\Games\\ok-ww\\ok-ww.exe'
                }
            ]
        }
        with open(self.mock_config_path, 'w', encoding='utf-8') as f:
            yaml.dump(config_data, f)
            
        res = bgi.get_BGI_user_dir()
        self.assertIsNone(res)

    @patch('config.bgi.get_our_bgi_user_dir')
    @patch('config.bgi.get_BGI_user_dir')
    def test_copy_BGI_User(self, mock_get_bgi, mock_get_our_bgi):
        target_dir = os.path.join(self.temp_dir.name, 'TargetBGI', 'User')
        
        mock_get_our_bgi.return_value = self.mock_our_bgi_dir
        mock_get_bgi.return_value = target_dir
        
        # Ensure target_dir does not exist yet
        self.assertFalse(os.path.exists(target_dir))
        
        bgi.copy_BGI_User()
        
        # Verify copying actually occurred
        self.assertTrue(os.path.exists(os.path.join(target_dir, "test_file.json")))
        with open(os.path.join(target_dir, "test_file.json"), "r") as f:
            self.assertEqual(f.read(), '{"test": true}')

    @patch('config.bgi.get_BGI_user_dir')
    @patch('shutil.copytree')
    def test_copy_BGI_User_none(self, mock_copytree, mock_get_bgi):
        mock_get_bgi.return_value = None
        
        with self.assertRaises(AssertionError):
            bgi.copy_BGI_User()
        mock_copytree.assert_not_called()

if __name__ == "__main__":
    unittest.main()

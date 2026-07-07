import os
import unittest
import tempfile
import yaml
import copy
from unittest.mock import patch, MagicMock
import launcher

class TestLauncher(unittest.TestCase):

    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp_dir.cleanup)
        
        # Paths
        self.mock_root_dir = os.path.join(self.temp_dir.name, "root")
        self.mock_onedragon_dir = os.path.join(self.temp_dir.name, "onedragon")
        os.makedirs(self.mock_root_dir, exist_ok=True)
        os.makedirs(self.mock_onedragon_dir, exist_ok=True)
        
        self.config_yml_path = os.path.join(self.mock_root_dir, "config.yml")
        
        # Mock configuration data
        self.config_data = {
            'script_list': [
                {
                    'display_name': 'Test Script 1',
                    'weekly_timeouts': [100, 200, 300, 400, 500, 600, 700],
                    'run_timeout_seconds': 0
                },
                {
                    'display_name': 'Test Script 2 (No timeouts)',
                    'run_timeout_seconds': 50
                }
            ]
        }
        with open(self.config_yml_path, 'w', encoding='utf-8') as f:
            yaml.dump(self.config_data, f)

    def test_get_week_num(self):
        wk = launcher.get_week_num()
        self.assertIsInstance(wk, int)
        self.assertTrue(0 <= wk <= 6)

    @patch('launcher.get_week_num')
    @patch('launcher.get_root_dir')
    @patch('launcher.get_path_under_onedragon')
    def test_generate_OneDragon_script_chain_success(self, mock_get_path, mock_get_root, mock_get_week):
        mock_get_root.return_value = self.mock_root_dir
        
        # Create output directory for script_chain config
        out_dir = os.path.join(self.mock_onedragon_dir, "config", "script_chain")
        os.makedirs(out_dir, exist_ok=True)
        mock_get_path.return_value = out_dir
        
        # Test for Wednesday (weekday index 2)
        wednesday_index = 2
        wednesday_timeout = 300
        mock_get_week.return_value = wednesday_index
        
        launcher.generate_OneDragon_script_chain()
        
        output_file = os.path.join(out_dir, "01.yml")
        self.assertTrue(os.path.exists(output_file))
        
        with open(output_file, 'r', encoding='utf-8') as f:
            output_data = yaml.safe_load(f)
            
        # Assertions
        scripts = output_data.get('script_list', [])
        self.assertEqual(scripts[0]['run_timeout_seconds'], wednesday_timeout)
        self.assertEqual(scripts[1]['run_timeout_seconds'], 50)  # Unchanged since no weekly_timeouts

    @patch('launcher.get_week_num')
    @patch('launcher.get_root_dir')
    @patch('launcher.get_path_under_onedragon')
    def test_generate_OneDragon_script_chain_invalid_timeout_length(self, mock_get_path, mock_get_root, mock_get_week):
        mock_get_root.return_value = self.mock_root_dir
        out_dir = os.path.join(self.mock_onedragon_dir, "config", "script_chain")
        os.makedirs(out_dir, exist_ok=True)
        mock_get_path.return_value = out_dir
        mock_get_week.return_value = 0
        
        # Write config with wrong timeout list size (6 instead of 7)
        invalid_config = copy.deepcopy(self.config_data)
        invalid_config['script_list'][0]['weekly_timeouts'] = [100, 200, 300, 400, 500, 600]
        with open(self.config_yml_path, 'w', encoding='utf-8') as f:
            yaml.dump(invalid_config, f)
            
        with self.assertRaises(AssertionError):
            launcher.generate_OneDragon_script_chain()

    @patch('launcher.get_path_under_onedragon')
    @patch('subprocess.run')
    def test_run_launcher(self, mock_run, mock_get_path):
        mock_get_path.return_value = "/mock/src/dir"
        
        mock_res = MagicMock()
        mock_res.returncode = 123
        mock_run.return_value = mock_res
        
        ret = launcher.run_launcher()
        
        self.assertEqual(ret, 123)
        mock_get_path.assert_called_once_with("src")
        mock_run.assert_called_once()
        args, kwargs = mock_run.call_args
        self.assertEqual(kwargs['cwd'], "/mock/src/dir")
        self.assertIn("script_chainer.win_exe.launcher", args[0])

if __name__ == "__main__":
    unittest.main()

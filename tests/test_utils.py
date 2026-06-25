import os
import tempfile
import unittest

import utils


class UtilsTest(unittest.TestCase):
    def test_join_dir_path_with_mk_creates_nested_dirs(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            result = utils.join_dir_path_with_mk(temp_dir, "a", None, "b")

            self.assertEqual(result, os.path.join(temp_dir, "a", "b"))
            self.assertTrue(os.path.isdir(result))

    def test_get_path_under_cwd_uses_project_root(self):
        self.assertEqual(utils.get_path_under_cwd("01.yml"), os.path.join(utils.BaseDIR, "01.yml"))

    def test_bgi_config_dir_points_to_root_bettergi(self):
        self.assertEqual(utils.BGIConfigDIR, os.path.join(utils.BaseDIR, "BetterGI"))


if __name__ == "__main__":
    unittest.main()

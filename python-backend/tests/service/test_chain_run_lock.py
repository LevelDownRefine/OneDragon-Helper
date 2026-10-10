"""测试脚本链运行位：同一时刻只允许一条链。"""

import tempfile
import unittest
from pathlib import Path
from unittest import mock

import src.service.chain_service as chain_service
from src.service.chain_service import ChainBusyError, chain_run_lease
from src.update.runtime import FileLease, UpdateBusyError


class TestChainRunLease(unittest.TestCase):
    def setUp(self):
        root = Path(self.enterContext(tempfile.TemporaryDirectory()))
        self.lock_path = root / "run.lock"
        self.enterContext(
            mock.patch.object(
                chain_service, "chain_lock_path", return_value=self.lock_path
            )
        )

    def test_excludes_other_holders_and_allows_nesting(self):
        """被他人持有时报错、他人释放后可取、同进程嵌套放行（重跑轮）。"""
        with (
            FileLease(self.lock_path),  # 模拟另一个进程已持锁
            self.assertRaises(ChainBusyError) as raised,
            chain_run_lease(),
        ):
            self.fail("抢占了已被占用的运行位")
        self.assertIn("已有脚本链在运行", str(raised.exception))

        with chain_run_lease():  # 释放后可进入
            self.assertTrue(self.lock_path.exists())
            with chain_run_lease():
                pass

    def test_run_chain_once_holds_lease_while_running(self):
        """run_chain_once 整段持有运行位：跑链期间其他进程抢不到。"""

        def probe(*args, **kwargs):
            with (
                self.assertRaises(UpdateBusyError),
                FileLease(chain_service.chain_lock_path()),
            ):
                self.fail("跑链期间仍能拿到运行位")

        with (
            mock.patch.object(chain_service, "_run_chain_once_impl", side_effect=probe),
            mock.patch.object(
                chain_service.utils_config,
                "load_config",
                return_value={"script_list": []},
            ),
            mock.patch.object(chain_service, "load_all_weekly", return_value={}),
        ):
            chain_service.run_chain_once({"ok-ww"})


class TestChainLockPath(unittest.TestCase):
    def test_lock_path_sits_under_chain_config_dir(self):
        """锁文件落在链配置目录（该目录不进更新差分）。"""
        root = Path(self.enterContext(tempfile.TemporaryDirectory()))
        with mock.patch("src.utils.get_root_dir", return_value=str(root)):
            lock_path = chain_service.chain_lock_path()
        self.assertEqual(lock_path, root / "config" / "script_chain" / "run.lock")

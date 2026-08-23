"""测试 src/log/rerun.py：rerun_failed 消费 rerun_list 阻塞重跑。"""

import unittest
from unittest import mock

from src.log.rerun import rerun_failed


def _fake_service():
    """返回 mock 服务对象，含一个非 exe 脚本 demo（script_name=display_name）。"""
    service = mock.MagicMock()
    service.load_config.return_value = {
        "script_list": [{"display_name": "demo", "script_path": "demo"}]
    }
    service.load_ui_state.return_value = {}
    service.generate_chain.return_value = "rerun.yml"
    return service


class TestRerunFailed(unittest.TestCase):
    """rerun_failed：空列表早退、生成+阻塞运行、过滤未知名（service 必需）。"""

    def test_empty_list_early_returns(self):
        """空 rerun_list 不应触碰 service，直接返回。"""
        service = mock.MagicMock()
        rerun_failed([], service=service)
        service.load_config.assert_not_called()
        service.run_chain_once.assert_not_called()

    def test_reruns_failed_scripts_blocking(self):
        """非空名单：复用 run_chain_once（chain_name=rerun, block=True）阻塞重跑。"""
        service = _fake_service()
        rerun_failed(["demo"], service=service, mute=True)
        service.load_config.assert_called_once()
        service.run_chain_once.assert_called_once_with(
            {"demo"}, chain_name="rerun", mute=True
        )

    def test_filters_unknown_script_names(self):
        """rerun_list 含不在 config 的脚本名时，仅对已知脚本重跑。"""
        service = _fake_service()
        rerun_failed(["demo", "ghost"], service=service)
        call = service.run_chain_once.call_args
        self.assertEqual(call.args[0], {"demo"})  # 启用脚本集合
        self.assertEqual(call.kwargs["chain_name"], "rerun")


if __name__ == "__main__":
    unittest.main()

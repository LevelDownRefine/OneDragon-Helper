"""前端边界：桥接对象只持 CLI 会话，不构造业务服务。"""

import unittest
from unittest.mock import patch

from gui.main_window import QmlBridge
from tests.gui.helpers import get_app, make_bridge


class TestCliOnlyBridge(unittest.TestCase):
    def setUp(self):
        get_app()

    def test_bridge_never_constructs_app_service(self):
        with patch(
            "src.service.app_service.AppService",
            side_effect=AssertionError("frontend service"),
        ):
            bridge = make_bridge()
        self.assertFalse(hasattr(bridge, "app_service"))
        self.assertIs(bridge._cli_session._client, bridge.test_client)
        self.assertEqual(bridge.test_client.requests[0], ("app.snapshot", {}))

    def test_bridge_requires_a_cli_client(self):
        with self.assertRaises(AssertionError):
            QmlBridge(None)

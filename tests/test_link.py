"""测试 src.link 的链接分发与降级逻辑。

覆盖各脚本官网/B站/GitHub 拼接、未知脚本降级。
背景图（background）属脚本资源元数据，归 set_config 声明、由背景控制器读取，不在此模块。
"""

import unittest

from src import link


class TestLinkDispatch(unittest.TestCase):
    """测试官网/B站/GitHub 链接拼接与未知脚本降级。"""

    def test_homepage_known(self):
        self.assertEqual(
            link.get_game_link("MAA", "homepage"), "https://ak.hypergryph.com/"
        )

    def test_bilibili_known(self):
        self.assertEqual(
            link.get_game_link("BetterGI", "bilibili"),
            "https://space.bilibili.com/401742377",
        )

    def test_github_known(self):
        self.assertEqual(
            link.get_game_link("ok-ww", "github"),
            "https://github.com/ok-oldking/ok-wuthering-waves",
        )

    def test_unknown_script_returns_empty(self):
        self.assertEqual(link.get_game_link("不存在", "homepage"), "")
        self.assertEqual(link.get_game_link("不存在", "bilibili"), "")
        self.assertEqual(link.get_game_link("不存在", "github"), "")


class TestLinkRegister(unittest.TestCase):
    """测试 register 对子类显式声明链接属性的校验。"""

    def test_register_requires_all_link_attrs(self):
        # 漏声明 _homepage 的子类必须被 register 拦截
        with self.assertRaises(AssertionError):

            @link.register
            class _BrokenLink(link.GameLink):
                _script_name = "broken"
                _bilibili = "123"
                _github = "a/b"
                # 故意遗漏 _homepage

    def test_register_ok_when_all_declared(self):
        # 全部声明则正常注册（随后清理，避免污染 _LINKS）
        @link.register
        class _OkLink(link.GameLink):
            _script_name = "ok_tmp"
            _bilibili = "123"
            _github = "a/b"
            _homepage = "https://x.com/"

        self.assertIn("ok_tmp", link._LINKS)
        del link._LINKS["ok_tmp"]


if __name__ == "__main__":
    unittest.main()

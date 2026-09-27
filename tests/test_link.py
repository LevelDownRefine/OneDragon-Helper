"""测试 src.link 的链接分发与降级逻辑。

覆盖各脚本官网/B站/GitHub 查询、未知脚本降级。
资源及完整链接在 config/script_resources.yml 声明；格式校验见 test_script_resources。
"""

import unittest

from src import link


class TestLinkDispatch(unittest.TestCase):
    """测试官网/B站/GitHub 链接查询与未知脚本降级。"""

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


if __name__ == "__main__":
    unittest.main()

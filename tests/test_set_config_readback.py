"""反读测试：get_dungeon / get_sequence / get_weekly_dungeon 读回 set_* 写入的值。

覆盖各脚本子类经子脚本 config 的反向映射，以及 facade 对无真相脚本返回 None。
写路径经 safe_update（assert_key_exists），故测试以 setter 替身隔离反向映射逻辑，
专测「_update_* 写入的值 ↔ _read_* 读出的值」一致。
"""

import unittest
from unittest.mock import patch

from src.config import set_config as set_config_mod
from src.config.set_config import (
    ArknightsConfig,
    EndfieldConfig,
    GenshinConfig,
    NTEConfig,
    StarRailConfig,
    WutheringWavesConfig,
    ZenlessZoneZeroConfig,
    get_dungeon,
    get_sequence,
    get_weekly_dungeon,
)


def _setter(config, key, value, *args, **kwargs):
    """safe_update 替身：直接赋值，隔离字段存在性约束，专测反向映射。"""
    config[key] = value
    return True


class TestReadbackWuWa(unittest.TestCase):
    def test_dungeon_and_sequence_roundtrip(self):
        config: dict = {}
        with (
            patch.object(WutheringWavesConfig, "_load", return_value=config),
            patch.object(WutheringWavesConfig, "_save"),
            patch.object(set_config_mod, "safe_update", _setter),
        ):
            cfg = WutheringWavesConfig()
            cfg.set_dungeon("凝素领域", "5")
            self.assertEqual(cfg._read_dungeon()[0], "凝素领域")
            self.assertEqual(cfg._read_dungeon()[1], "5")

    def test_mapped_sequence_roundtrip(self):
        config: dict = {}
        with (
            patch.object(WutheringWavesConfig, "_load", return_value=config),
            patch.object(WutheringWavesConfig, "_save"),
            patch.object(set_config_mod, "safe_update", _setter),
        ):
            cfg = WutheringWavesConfig()
            cfg.set_dungeon("模拟领域", "共鸣者经验")
            self.assertEqual(cfg._read_dungeon()[0], "模拟领域")
            # 序列经 values 映射存为英文，反读应反转回中文
            self.assertEqual(cfg._read_dungeon()[1], "共鸣者经验")


class TestReadbackGenshin(unittest.TestCase):
    def test_domain_roundtrip(self):
        config: dict = {}
        with (
            patch.object(GenshinConfig, "_load", return_value=config),
            patch.object(GenshinConfig, "_save"),
            patch.object(set_config_mod, "safe_update", _setter),
        ):
            cfg = GenshinConfig()
            cfg.set_dungeon("圣遗物", "黄金屋")
            self.assertEqual(cfg._read_dungeon()[0], "黄金屋")


class TestReadbackEndfield(unittest.TestCase):
    def test_stage_roundtrip(self):
        config: dict = {}
        with (
            patch.object(EndfieldConfig, "_load", return_value=config),
            patch.object(EndfieldConfig, "_save"),
            patch.object(set_config_mod, "safe_update", _setter),
        ):
            cfg = EndfieldConfig()
            cfg.set_dungeon("能量淤积点", "某副本")
            self.assertEqual(cfg._read_dungeon()[0], "某副本")


class TestReadbackNTE(unittest.TestCase):
    def test_anomaly_roundtrip(self):
        config = {"daily_anomaly": {"任务类型": "", "异能材料序号": ""}}
        routine = {
            "Routine Items": [
                {"id": "daily_anomaly", "enabled": False},
                {"id": "daily_anomaly_hunter", "enabled": False},
            ]
        }
        with (
            patch.object(
                NTEConfig,
                "_load",
                side_effect=lambda p=None, **_k: config if p is None else routine,
            ),
            patch.object(NTEConfig, "_save"),
            patch.object(set_config_mod, "safe_update", _setter),
        ):
            cfg = NTEConfig()
            cfg.set_dungeon("异能升级材料", "3")
            self.assertEqual(cfg._read_dungeon()[0], "异能升级材料")
            self.assertEqual(cfg._read_dungeon()[1], "3")

    def test_hunter_readback_via_routine(self):
        config = {"daily_anomaly": {}}
        routine = {
            "Routine Items": [
                {"id": "daily_anomaly", "enabled": False},
                {"id": "daily_anomaly_hunter", "enabled": True},
            ]
        }
        with (
            patch.object(
                NTEConfig,
                "_load",
                side_effect=lambda p=None, **_k: config if p is None else routine,
            ),
            patch.object(NTEConfig, "_save"),
            patch.object(set_config_mod, "safe_update", _setter),
        ):
            cfg = NTEConfig()
            self.assertEqual(cfg._read_dungeon()[0], "追猎目标")

    def test_hunter_readback_ignores_stale_anomaly_task_type(self):
        """从异象界域切到追猎目标后，daily_anomaly.任务类型 仍残留陈旧值，
        必须以 Routine Items 启用状态为准，反读到追猎目标及其目标名。
        """
        config = {
            "daily_anomaly": {"任务类型": "空幕", "空幕序号": 6},
        }
        routine = {
            "Routine Items": [
                {"id": "daily_anomaly", "enabled": False},
                {"id": "daily_anomaly_hunter", "enabled": True},
            ],
            "daily_anomaly_hunter": {"追猎目标": "黑之书"},
        }
        with (
            patch.object(
                NTEConfig,
                "_load",
                side_effect=lambda p=None, **_k: config if p is None else routine,
            ),
            patch.object(NTEConfig, "_save"),
            patch.object(set_config_mod, "safe_update", _setter),
        ):
            cfg = NTEConfig()
            # 即便 任务类型 残留「空幕」、空幕序号=6（轨道之夜），也应读追猎目标
            self.assertEqual(cfg._read_dungeon()[0], "追猎目标")
            self.assertEqual(cfg._read_dungeon()[1], "黑之书")


class TestReadbackMAA(unittest.TestCase):
    def test_dungeon_roundtrip(self):
        config = {
            "Configurations": {
                "Default": {
                    "TaskQueue": [
                        {"Name": "剿灭", "IsEnable": False},
                        {"Name": "土", "IsEnable": False},
                        {"Name": "活动土", "IsEnable": False},
                        {"Name": "龙门币", "IsEnable": False},
                    ]
                }
            }
        }
        with (
            patch.object(ArknightsConfig, "_load", return_value=config),
            patch.object(ArknightsConfig, "_save"),
            patch.object(set_config_mod, "safe_update", _setter),
        ):
            cfg = ArknightsConfig()
            cfg._task_map = {
                "剿灭": {"index": 0, "stage": None},
                "土": {"index": 1, "stage": None},
                "活动土": {"index": 2, "stage": None},
                "龙门币": {"index": 3, "stage": None},
            }
            cfg.set_dungeon("龙门币")
            self.assertEqual(cfg._read_dungeon()[0], "龙门币")


class TestReadbackStarRailWeekly(unittest.TestCase):
    def test_weekly_dungeon_roundtrip(self):
        config: dict = {}
        with (
            patch.object(StarRailConfig, "_load", return_value=config),
            patch.object(StarRailConfig, "_save"),
            patch.object(set_config_mod, "safe_update", _setter),
        ):
            cfg = StarRailConfig()
            cfg.set_weekly_dungeon("历战余响", "铁骸的锈冢")
            self.assertEqual(cfg._read_weekly_dungeon("历战余响"), "铁骸的锈冢")


class TestReadbackFacade(unittest.TestCase):
    def test_facade_roundtrip_okww(self):
        config: dict = {}
        with (
            patch.object(WutheringWavesConfig, "_load", return_value=config),
            patch.object(WutheringWavesConfig, "_save"),
            patch.object(set_config_mod, "safe_update", _setter),
        ):
            cfg = WutheringWavesConfig()
            cfg.set_dungeon("凝素领域", "5")
            self.assertEqual(get_dungeon("ok-ww"), "凝素领域")
            self.assertEqual(get_sequence("ok-ww"), "5")

    def test_facade_unknown_script_returns_none(self):
        self.assertIsNone(get_dungeon("不存在的脚本"))
        self.assertIsNone(get_sequence("不存在的脚本"))

    def test_facade_noop_scripts_return_none(self):
        # 绝区零/崩铁日常无副本适配（_task_key 空）→ 反读 None
        with (
            patch.object(ZenlessZoneZeroConfig, "_load", return_value={}),
        ):
            self.assertIsNone(get_dungeon("OneDragon-Launcher"))
        with (
            patch.object(StarRailConfig, "_load", return_value={}),
        ):
            self.assertIsNone(get_dungeon("March7th-Assistant"))
            self.assertIsNone(get_weekly_dungeon("March7th-Assistant", "历战余响"))


class TestReadbackCorruption(unittest.TestCase):
    """损坏数据应 assert 暴露，而非静默返回 None（否则被 gui_state 兜底掩盖）。"""

    def test_unknown_task_value_raises(self):
        config = {"Which to Farm": "未知副本值"}
        with (
            patch.object(WutheringWavesConfig, "_load", return_value=config),
        ):
            cfg = WutheringWavesConfig()
            with self.assertRaises(AssertionError):
                cfg._read_dungeon()

    def test_nte_corrupt_routine_raises(self):
        routine = []  # 非 dict → 损坏，原实现会静默回退 任务类型
        config: dict = {}
        with (
            patch.object(
                NTEConfig,
                "_load",
                side_effect=lambda p=None, **_k: config if p is None else routine,
            ),
            patch.object(NTEConfig, "_save"),
            patch.object(set_config_mod, "safe_update", _setter),
        ):
            cfg = NTEConfig()
            with self.assertRaises(AssertionError):
                cfg._read_dungeon()

    def test_starrail_bad_instance_names_raises(self):
        config = {"instance_names": "不是dict"}
        with (
            patch.object(StarRailConfig, "_load", return_value=config),
        ):
            cfg = StarRailConfig()
            with self.assertRaises(AssertionError):
                cfg._read_weekly_dungeon("历战余响")


if __name__ == "__main__":
    unittest.main()

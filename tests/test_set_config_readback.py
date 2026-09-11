"""反读测试：get_daily_task / get_weekly_task 读回 set_* 写入的值。

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
    get_daily_task,
    get_weekly_task,
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
            cfg.set_daily_task("每日任务", "凝素领域", 5)
            self.assertEqual(cfg._read_daily_task("每日任务")[0], "凝素领域")
            self.assertEqual(cfg._read_daily_task("每日任务")[1], 5)

    def test_mapped_sequence_roundtrip(self):
        config: dict = {}
        with (
            patch.object(WutheringWavesConfig, "_load", return_value=config),
            patch.object(WutheringWavesConfig, "_save"),
            patch.object(set_config_mod, "safe_update", _setter),
        ):
            cfg = WutheringWavesConfig()
            cfg.set_daily_task("每日任务", "模拟领域", "Resonator EXP")
            self.assertEqual(cfg._read_daily_task("每日任务")[0], "模拟领域")
            self.assertEqual(cfg._read_daily_task("每日任务")[1], "Resonator EXP")


class TestReadbackGenshin(unittest.TestCase):
    def test_domain_roundtrip(self):
        config: dict = {}
        with (
            patch.object(GenshinConfig, "_load", return_value=config),
            patch.object(GenshinConfig, "_save"),
            patch.object(set_config_mod, "safe_update", _setter),
        ):
            cfg = GenshinConfig()
            cfg.set_daily_task("每日任务", "圣遗物", "黄金屋")
            self.assertEqual(cfg._read_daily_task("每日任务")[0], "黄金屋")


class TestReadbackEndfield(unittest.TestCase):
    def test_stage_roundtrip(self):
        config: dict = {}
        with (
            patch.object(EndfieldConfig, "_load", return_value=config),
            patch.object(EndfieldConfig, "_save"),
            patch.object(set_config_mod, "safe_update", _setter),
        ):
            cfg = EndfieldConfig()
            cfg.set_daily_task("每日任务", "能量淤积点", "某副本")
            self.assertEqual(cfg._read_daily_task("每日任务")[0], "某副本")


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
                side_effect=lambda p=None, **_k: (
                    routine
                    if p == set_config_mod.NTEConfig._routine_config_rel_path
                    else config
                ),
            ),
            patch.object(
                NTEConfig,
                "_save",
                side_effect=lambda data, rel=None: (
                    routine
                    if rel == set_config_mod.NTEConfig._routine_config_rel_path
                    else config
                ).update(data),
            ),
            patch.object(set_config_mod, "safe_update", _setter),
        ):
            cfg = NTEConfig()
            cfg.set_daily_task("daily_anomaly", "异能升级材料", 3)
            self.assertEqual(cfg._read_daily_task("daily_anomaly")[0], "异能升级材料")
            self.assertEqual(cfg._read_daily_task("daily_anomaly")[1], 3)

    def test_hunter_readback_without_boss(self):
        """启用追猎但尚未选目标时，反读为空选择。"""
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
                side_effect=lambda p=None, **_k: (
                    routine
                    if p == set_config_mod.NTEConfig._routine_config_rel_path
                    else config
                ),
            ),
            patch.object(NTEConfig, "_save"),
            patch.object(set_config_mod, "safe_update", _setter),
        ):
            cfg = NTEConfig()
            self.assertEqual(cfg._read_daily_task("daily_anomaly_hunter"), (None, None))

    def test_hunter_readback_ignores_stale_anomaly_task_type(self):
        """从异象界域切到追猎目标后，daily_anomaly.任务类型 仍残留陈旧值，
        必须以 Routine Items 启用状态为准，反读到追猎目标及其目标名。
        """
        config = {
            "daily_anomaly": {"任务类型": "空幕", "空幕序号": 6},
            "daily_anomaly_hunter": {"追猎目标": "黑之书"},
        }
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
                side_effect=lambda p=None, **_k: (
                    routine
                    if p == set_config_mod.NTEConfig._routine_config_rel_path
                    else config
                ),
            ),
            patch.object(NTEConfig, "_save"),
            patch.object(set_config_mod, "safe_update", _setter),
        ):
            cfg = NTEConfig()
            self.assertEqual(cfg._read_daily_task("daily_anomaly_hunter")[0], "黑之书")
            self.assertEqual(cfg._read_daily_task("daily_anomaly_hunter")[1], None)

    def test_hunter_boss_roundtrip_through_config(self):
        """回归：boss 名写入 config 文件的 daily_anomaly_hunter 段，读取须同文件取回。

        读写都由该具名任务的 value 定位原生配置，目标为一级选择。
        """
        config = {
            "daily_anomaly": {"任务类型": "", "异能材料序号": ""},
            "daily_anomaly_hunter": {"目标消耗体力": 240},
        }
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
                side_effect=lambda p=None, **_k: (
                    routine
                    if p == set_config_mod.NTEConfig._routine_config_rel_path
                    else config
                ),
            ),
            patch.object(NTEConfig, "_save"),
            patch.object(set_config_mod, "safe_update", _setter),
        ):
            cfg = NTEConfig()
            cfg.set_daily_task("daily_anomaly_hunter", "音霸魔王")
            self.assertEqual(
                cfg._read_daily_task("daily_anomaly_hunter"), ("音霸魔王", None)
            )


class TestReadbackMAA(unittest.TestCase):
    def test_dungeon_roundtrip(self):
        config = {
            "Configurations": {
                "Default": {
                    "TaskQueue": [
                        {
                            "Name": "剿灭",
                            "$type": "FightTask",
                            "IsEnable": False,
                            "StagePlan": ["Annihilation"],
                        },
                        {
                            "Name": "土",
                            "$type": "FightTask",
                            "IsEnable": False,
                            "StagePlan": ["1-7"],
                        },
                        {
                            "Name": "活动土",
                            "$type": "FightTask",
                            "IsEnable": False,
                            "StagePlan": [""],
                        },
                        {
                            "Name": "龙门币",
                            "$type": "FightTask",
                            "IsEnable": False,
                            "StagePlan": ["CE-6"],
                        },
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
            cfg.set_daily_task("每日任务", "龙门币")
            self.assertEqual(cfg._read_daily_task("每日任务")[0], "龙门币")

    def test_read_daily_dungeon_all_disabled_but_has_1_7_returns_土(self):
        """所有维护关卡都未启用，但有1-7 → 读为土"""
        config = {
            "Configurations": {
                "Default": {
                    "TaskQueue": [
                        {
                            "Name": "剿灭",
                            "$type": "FightTask",
                            "IsEnable": True,
                            "StagePlan": ["Annihilation"],
                        },
                        {
                            "Name": "土",
                            "$type": "FightTask",
                            "IsEnable": False,
                            "StagePlan": ["1-7"],
                        },
                        {
                            "Name": "活动土",
                            "$type": "FightTask",
                            "IsEnable": True,
                            "StagePlan": [""],
                        },
                        {
                            "Name": "龙门币",
                            "$type": "FightTask",
                            "IsEnable": False,
                            "StagePlan": ["CE-6"],
                        },
                    ]
                }
            }
        }
        with (
            patch.object(ArknightsConfig, "_load", return_value=config),
            patch.object(ArknightsConfig, "_save"),
        ):
            cfg = ArknightsConfig()
            self.assertEqual(cfg._read_daily_task("每日任务")[0], "土")


class TestReadbackStarRailWeekly(unittest.TestCase):
    def test_weekly_dungeon_roundtrip(self):
        config: dict = {}
        with (
            patch.object(StarRailConfig, "_load", return_value=config),
            patch.object(StarRailConfig, "_save"),
            patch.object(set_config_mod, "safe_update", _setter),
        ):
            cfg = StarRailConfig()
            cfg.set_weekly_task_option("历战余响", "铁骸的锈冢")
            self.assertEqual(cfg._read_weekly_task("历战余响"), ("铁骸的锈冢", None))


class TestReadbackFacade(unittest.TestCase):
    def test_facade_roundtrip_okww(self):
        config: dict = {}
        with (
            patch.object(WutheringWavesConfig, "_load", return_value=config),
            patch.object(WutheringWavesConfig, "_save"),
            patch.object(set_config_mod, "safe_update", _setter),
        ):
            cfg = WutheringWavesConfig()
            cfg.set_daily_task("每日任务", "凝素领域", 5)
            self.assertEqual(get_daily_task("ok-ww", "每日任务")[0], "凝素领域")
            self.assertEqual(get_daily_task("ok-ww", "每日任务")[1], 5)

    def test_facade_unknown_script_returns_none(self):
        self.assertIsNone(get_daily_task("不存在的脚本", "每日任务")[0])
        self.assertIsNone(get_daily_task("不存在的脚本", "每日任务")[1])

    def test_facade_noop_scripts_return_none(self):
        # 绝区零/崩铁日常无副本适配（无字段绑定）→ 反读 None
        with (
            patch.object(ZenlessZoneZeroConfig, "_load", return_value={}),
        ):
            self.assertIsNone(get_daily_task("OneDragon-Launcher", "每日任务")[0])
        with (
            patch.object(StarRailConfig, "_load", return_value={}),
        ):
            self.assertIsNone(get_daily_task("March7th-Launcher", "每日任务")[0])
            self.assertEqual(
                get_weekly_task("March7th-Launcher", "历战余响"), (None, None)
            )


class TestReadbackCorruption(unittest.TestCase):
    """损坏数据应 assert 暴露，而非静默返回 None（否则被日常副本的声明项回退掩盖）。"""

    def test_non_scalar_task_value_raises(self):
        config = {"Which to Farm": {"损坏": "非标量"}}
        with patch.object(WutheringWavesConfig, "_load", return_value=config):
            cfg = WutheringWavesConfig()
            with self.assertRaises(AssertionError):
                cfg._read_daily_task("每日任务")

    def test_nte_corrupt_routine_raises(self):
        routine = []
        config: dict = {}
        with (
            patch.object(
                NTEConfig,
                "_load",
                side_effect=lambda p=None, **_k: (
                    routine
                    if p == set_config_mod.NTEConfig._routine_config_rel_path
                    else config
                ),
            ),
            patch.object(NTEConfig, "_save"),
            patch.object(set_config_mod, "safe_update", _setter),
        ):
            cfg = NTEConfig()
            with self.assertRaises(AssertionError):
                cfg._read_task_enabled("daily_anomaly")

    def test_starrail_bad_instance_names_raises(self):
        config = {"instance_names": "不是dict"}
        with patch.object(StarRailConfig, "_load", return_value=config):
            cfg = StarRailConfig()
            with self.assertRaises(AssertionError):
                cfg._read_weekly_task("历战余响")


if __name__ == "__main__":
    unittest.main()

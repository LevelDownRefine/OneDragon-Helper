"""固定种子 → 全菜单选择 → 落盘差异和反读；只替换文件 I/O 与外部资源。

显式更新基线：PYTHONPATH=src python -m tests.test_golden_daily --update
正常测试只读基线，新增选项或修改行为后须审查 JSON 差异。
"""

import json
import logging
import sys
import unittest
from contextlib import ExitStack
from copy import deepcopy
from pathlib import Path
from unittest.mock import patch

from src.config import daily as daily_mod
from src.config import set_config as config_mod
from src.config.daily_config import get_daily_map
from tests.config_diff import diff_paths

logger = logging.getLogger(__name__)
GOLDEN_PATH = Path(__file__).parent / "golden/daily_baseline.json"
DAYS = ("Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday")


def _resource_names(_script, _daily, source):
    """固定本地资源选项，不依赖游戏安装和活动日期。"""
    if "category" in source:
        prefix = source["category"]
    elif "key" in source:
        prefix = source["key"][-1]
    else:
        return ["AT-8", "AT-7"]
    return [f"{prefix}-甲", f"{prefix}-乙"]


def _seed_files():
    """独立声明原生文件和初始值，不从被测对象的落点推导期望。"""
    bgi = {
        "DomainName": "BlessDomain-乙",
        "AutoBossName": "急冻树",
        "TaskDefinitions": {
            "domain": "自动秘境",
            "leyline": "自动地脉花",
            "boss": "自动首领讨伐",
        },
        "TaskEnabledList": {"domain": False, "leyline": False, "boss": False},
    }
    for day in DAYS:
        bgi[f"LeyLine{day}Type"] = "启示之花"
        bgi[f"LeyLine{day}Country"] = "leyLinePositions-乙"
    maa_path = Path(__file__).parent / "fixtures/maa_gui.new.scrubbed.json"
    stores = {
        "ok-ww": {
            "data/apps/ok-ww/working/configs/DailyTask.json": {
                "Which to Farm": "Simulation Challenge",
                "Which Forgery Challenge to Farm": 20,
                "Which Tacet Suppression to Farm": 19,
                "Material Selection": "Shell Credit",
            }
        },
        "BetterGI": {"User/OneDragon/默认配置.json": bgi},
        "ok-ef": {
            "data/apps/ok-ef/working/configs/DailyTask.json": {
                "体力本": "能量淤积点-乙",
                "⭐刷体力": False,
            }
        },
        "OneDragon-Launcher": {"config/01/one_dragon/charge_plan.yml": {}},
        "March7th-Launcher": {"config.yaml": {}},
        "MAA": {
            "config/gui.new.json": json.loads(maa_path.read_text(encoding="utf-8"))
        },
        "ok-nte": {
            "data/apps/ok-nte/working/configs/DailyRoutineTaskConfigs.json": {
                "daily_anomaly": {
                    "任务类型": "经验与甲硬币",
                    "空幕序号": 6,
                    "异能材料序号": 5,
                    "弧盘材料序号": 5,
                    "具体奖励目标": "甲硬币",
                },
                "daily_anomaly_hunter": {"追猎目标": "斑蝶"},
            },
            "data/apps/ok-nte/working/configs/DailyRoutineTask.json": {
                "Routine Items": [
                    {"id": "daily_anomaly", "enabled": False},
                    {"id": "daily_anomaly_hunter", "enabled": False},
                ]
            },
        },
    }
    for files in stores.values():
        for config in files.values():
            config["untouched"] = {"value": 42}
    return stores


def build_baseline():
    """记录所有已声明日常每个菜单选项的完整写入差异与反读。"""
    stores = _seed_files()
    saves = []

    def load(script, path):
        assert script in stores
        assert path in stores[script], (script, path)
        return deepcopy(stores[script][path])

    def save(script, path, data):
        assert script in stores
        assert path in stores[script], (script, path)
        stores[script][path] = deepcopy(data)
        saves.append(path)

    baseline = {"menus": {}, "writes": {}, "reads": {}}
    with ExitStack() as stack:
        for module in (daily_mod, config_mod):
            stack.enter_context(patch.object(module, "load_config", side_effect=load))
            stack.enter_context(patch.object(module, "save_config", side_effect=save))
        stack.enter_context(
            patch("src.config.daily_config.get_task_lists", side_effect=_resource_names)
        )
        menus = get_daily_map()
        # 声明与夹具一一对应；_CONFIGS 另可含无日常的脚本（MaaEnd）。
        assert set(menus) == set(stores)
        assert set(menus) <= set(config_mod._CONFIGS)
        for script in sorted(menus):
            cfg = config_mod._CONFIGS[script]()
            normalized = {}
            steps = []
            before_read = config_mod.get_daily_readback(script)
            for daily in menus[script]["dailies"]:
                name = daily["display_name"]
                choices = {}
                for task in daily["options"]["values"]:
                    task_name = task["display_name"]
                    sequences = task["options"]["values"] if "options" in task else []
                    choices[task_name] = [
                        [s["display_name"], s["physical_name"]] for s in sequences
                    ]
                    for sequence in [s["physical_name"] for s in sequences] or [None]:
                        before = deepcopy(stores[script])
                        saves.clear()
                        cfg.set_daily_task(name, task_name, sequence)
                        steps.append(
                            {
                                "daily": name,
                                "task": task_name,
                                "sequence": sequence,
                                "saved_files": list(saves),
                                "diff": {
                                    path: [old, new]
                                    for path, old, new in diff_paths(
                                        before, stores[script]
                                    )
                                },
                                "readback": config_mod.get_daily_readback(script),
                            }
                        )
                normalized[name] = choices
            baseline["menus"][script] = normalized
            baseline["writes"][script] = steps
            baseline["reads"][script] = before_read
    return baseline


def _dump(data):
    """JSON 文本同时保留 bool/int 等值但不同类型的差异。"""
    return json.dumps(data, ensure_ascii=False, indent=2, sort_keys=True) + "\n"


class TestDailyGolden(unittest.TestCase):
    def test_matches_baseline(self):
        expected = json.loads(GOLDEN_PATH.read_text(encoding="utf-8"))
        actual = build_baseline()
        self.maxDiff = 6000
        self.assertEqual(_dump(actual), _dump(expected))


if __name__ == "__main__":
    if sys.argv[1:] == ["--update"]:
        logging.basicConfig(level=logging.INFO)
        baseline = build_baseline()
        GOLDEN_PATH.write_text(_dump(baseline), encoding="utf-8")
        logger.info("已更新 %s，共 %d 个脚本", GOLDEN_PATH, len(baseline["writes"]))
    else:
        unittest.main()

"""日常配置的 golden 基线：把「声明 → 菜单 / 写入落点 / 反读」的产物固化成快照。

目的：后续重构（日常对象、菜单层、GUI）每一步都拿它自证「行为没变」。产物只含游戏域
数据（副本名、序列值、字段路径、值），**不含任何标识符名**，所以纯改名的重构不会让它
失效；反过来，任何落点、取值或菜单内容的漂移都会立刻红。

三段产物：

- ``menus``：每个脚本的菜单内容 {日常: {一级项: [[二级展示名, 二级物理值], ...]}}。
  按内容归一（不记外层形状），故菜单结构的调整也能被它守住；二级项保持列表顺序
  （界面就按声明顺序渲染）；
- ``writes``：按菜单顺序逐个 (日常, 一级项, 二级项) 调 ``set_daily_task``，每步记录
  该次落盘的全量路径级 diff（含分段脚本的第二份文件）——「只动了该动的字段」；
- ``reads``：每个脚本的反读记录，``before`` 为写入前的种子状态、``after`` 为全部写入后
  的最终状态（``{name, task, sequence, enabled}``）。

种子（写入前的 config）分三类：

- 由声明落点推导（鸣潮 / 原神 / 终末地 / 异环）：每个落点字段先填入该字段值域里的末位
  物理值，故逐项写入时每一步都真的产生改动（类型也与写入值一致）；异环的字段落在各自段内；
- 无落点脚本（绝区零 / 崩铁）：空 dict——其 ``set_daily_task`` 为 no-op，恰好由本基线钉住；
- 粥：任务以 ``TaskQueue`` / ``StagePlan`` 表达，声明层给不出落点，故用既有脱敏夹具。

菜单里的 ``source`` 类选项（原神 / 终末地读子脚本本地资源）由固定返回替代，否则产物会
随本机安装状态漂移。

重新生成：``PYTHONPATH=src python -m tests.test_golden_daily``（写出文件并打印摘要）。
"""

import copy
import json
import os
import unittest
from unittest.mock import patch

from src.config import set_config as sc_mod
from src.config.daily_config import get_daily_map
from src.config.set_config import _CONFIGS, get_daily_readback
from src.config.task_config import get_daily_configs
from tests.config_diff import diff_paths

GOLDEN_PATH = os.path.join(os.path.dirname(__file__), "golden", "daily_baseline.json")
MAA_FIXTURE = os.path.join(
    os.path.dirname(__file__), "fixtures", "maa_gui.new.scrubbed.json"
)

# get_task_lists 的替身：source 展开的选项来自子脚本本地资源，不由声明给出。按一级项名
# 派生，保证各任务取值互不相同（否则二级会被同一个桩值抹平），且跨机可复现。
RESOURCE_STUB = ("甲", "乙")


def resource_stub(_script_name: str, task_name: str, _source: str) -> list[str]:
    """source 展开的固定选项（替身）。"""
    return [f"{task_name}-{suffix}" for suffix in RESOURCE_STUB]


# 字段落在 config 的哪个容器里：异环两个日常各居一段，段名即日常物理名。
SEGMENTED = frozenset({"ok-nte"})


def menu_of(script_name: str) -> dict[str, dict[str, list]]:
    """该脚本菜单的归一内容：{日常: {一级项: [[二级展示名, 二级物理值], ...]}}。"""
    menu = get_daily_map().get(script_name, {"dailies": []})["dailies"]
    return {
        daily["name"]: {
            task["name"]: [
                [seq["display"], seq["value"]] for seq in task.get("sequences") or []
            ]
            for task in daily["tasks"]
        }
        for daily in menu
    }


def seed_of(script_name: str, cfg) -> dict:
    """该脚本的 config 种子（写入前状态），见模块 docstring 的三类口径。"""
    if script_name == "MAA":
        with open(MAA_FIXTURE, encoding="utf-8") as f:
            return json.load(f)
    daily_cfgs = get_daily_configs(script_name)
    if not any(daily_cfg["task_field"] for daily_cfg in daily_cfgs.values()):
        return {}  # 绝区零 / 崩铁：声明无落点，写入为 no-op

    menus = menu_of(script_name)
    seed: dict = {}
    for mode, daily_cfg in daily_cfgs.items():
        container = seed.setdefault(mode, {}) if script_name in SEGMENTED else seed
        task_field = daily_cfg["task_field"]
        if task_field is not None:
            container[task_field] = list(daily_cfg["task_map"].values())[-1]
        daily_name = next(
            name for name in menus if cfg._daily_physical_name(name) == mode
        )
        for task_name, field in daily_cfg["option_fields"].items():
            sequences = menus[daily_name][task_name]
            if sequences and field not in container:
                container[field] = sequences[-1][1]
    return seed


def _store_io(store: dict, cfg):
    """把 config 文件读写重定向到内存 store，返回 (load_config, save_config) 替身。"""

    def load_config(_script_name, rel_path=None):
        return copy.deepcopy(store[rel_path or cfg._config_rel_path])

    def save_config(_script_name, rel_path, data):
        store[rel_path] = copy.deepcopy(data)

    return load_config, save_config


def build_baseline() -> dict:
    """构造完整的 golden 产物（与文件内容应逐字节可比）。"""
    baseline = {"menus": {}, "writes": {}, "reads": {}}
    for script_name in sorted(_CONFIGS):
        cfg = _CONFIGS[script_name]()
        store = {cfg._config_rel_path: copy.deepcopy(seed_of(script_name, cfg))}
        routine_path = getattr(cfg, "_routine_config_rel_path", "")
        if routine_path:
            store[routine_path] = {
                "Routine Items": [
                    {"id": "daily_anomaly", "enabled": False},
                    {"id": "daily_anomaly_hunter", "enabled": True},
                ]
            }
        fake_load, fake_save = _store_io(store, cfg)

        with (
            patch.object(sc_mod, "load_config", fake_load),
            patch.object(sc_mod, "save_config", fake_save),
        ):
            menus = menu_of(script_name)
            baseline["menus"][script_name] = menus
            baseline["reads"][script_name] = {"before": get_daily_readback(script_name)}
            steps = []
            for daily_name, tasks in menus.items():
                for task_name, sequences in tasks.items():
                    for sequence in [seq[1] for seq in sequences] or [None]:
                        before = copy.deepcopy(store)
                        cfg.set_daily_task(daily_name, task_name, sequence)
                        steps.append(
                            {
                                "daily": daily_name,
                                "task": task_name,
                                "sequence": sequence,
                                "diff": {
                                    path: [old, new]
                                    for path, old, new in diff_paths(before, store)
                                },
                            }
                        )
            baseline["writes"][script_name] = steps
            baseline["reads"][script_name]["after"] = get_daily_readback(script_name)
    return baseline


def dump(baseline: dict) -> str:
    return json.dumps(baseline, ensure_ascii=False, indent=2, sort_keys=True) + "\n"


def report(actual: dict, expected: dict) -> str:
    """把两份产物的差异摊成路径级报告（只列前若干条，便于直接定位）。"""
    diffs = diff_paths(expected, actual)
    lines = [
        f"  {path}: {json.dumps(old, ensure_ascii=False)} → {json.dumps(new, ensure_ascii=False)}"
        for path, old, new in diffs[:20]
    ]
    if len(diffs) > 20:
        lines.append(f"  ……另有 {len(diffs) - 20} 处")
    return (
        f"日常配置产物与 golden 基线不一致（{len(diffs)} 处）：\n"
        + "\n".join(lines)
        + "\n\n确认行为变化后按新行为重新生成："
        "PYTHONPATH=src python -m tests.test_golden_daily"
    )


class TestDailyGolden(unittest.TestCase):
    """实际产物必须与 golden 基线一致。"""

    def test_matches_baseline(self):
        with patch("src.config.daily_config.get_task_lists", side_effect=resource_stub):
            actual = build_baseline()
        with open(GOLDEN_PATH, encoding="utf-8") as f:
            expected = json.load(f)
        if actual != expected:
            self.fail(report(actual, expected))


if __name__ == "__main__":
    with patch("src.config.daily_config.get_task_lists", side_effect=resource_stub):
        built = build_baseline()
    os.makedirs(os.path.dirname(GOLDEN_PATH), exist_ok=True)
    with open(GOLDEN_PATH, "w", encoding="utf-8") as f:
        f.write(dump(built))
    print(f"已写入 {GOLDEN_PATH}")
    for script in sorted(built["writes"]):
        print(f"  {script:22s} 写入步 {len(built['writes'][script]):2d}")

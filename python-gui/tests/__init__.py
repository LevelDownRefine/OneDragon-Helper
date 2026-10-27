# Test package for the Python GUI.

# 与后端套件共用生成配置绊线：GUI 测试同样不得依赖真实生成配置（本地存在、
# CI 缺失）。后端 tests 包与本项目 tests 包同名，无法常规导入，按文件路径加载。
import importlib.util
from pathlib import Path

_tripwire_path = (
    Path(__file__).resolve().parents[2]
    / "python-backend"
    / "tests"
    / "support"
    / "config_tripwire.py"
)
_spec = importlib.util.spec_from_file_location("_odh_config_tripwire", _tripwire_path)
_tripwire = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_tripwire)
_tripwire.install()

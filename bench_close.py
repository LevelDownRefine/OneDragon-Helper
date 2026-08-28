import time

from src.service.chain_service import ChainService
from src.utils_runner import _build_child_map, _collect_process_targets, _find_processes

scripts = ChainService().load_config()["script_list"]

# 预热：psutil 首次取属性有一次性的初始化开销，不计入。
_find_processes([_collect_process_targets(scripts[0])[0]])
_build_child_map()

targets = []
for s in scripts:
    targets += _collect_process_targets(s)

t = time.perf_counter()
found = _find_processes(targets)
kids = _build_child_map()
dt = time.perf_counter() - t
print(
    f"合并后：一次匹配 + 一次建表 = {dt:.3f}s（命中 {len(found)} 个进程）", flush=True
)
print(f"  targets 合计 {len(targets)} 条，ppid 表 {len(kids)} 个键", flush=True)

# 旧路径：逐脚本各扫一遍
t = time.perf_counter()
for s in scripts:
    _find_processes(_collect_process_targets(s))
old = time.perf_counter() - t
print(f"\n合并前：8 个脚本各扫一遍 = {old:.3f}s", flush=True)
print(f"提速 {old / dt:.1f}×", flush=True)

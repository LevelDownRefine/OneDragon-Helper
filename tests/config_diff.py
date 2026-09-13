"""config dict 的路径级 diff 工具。

供 config 安全性测试（终末地 / 粥）与日常 golden 基线共用：递归比较两份 config，
把每个取值变化的字段摊平成 (json-path, before, after)，路径用点分 + ``[i]`` 索引，
故列表内的变化也能定位到具体下标（而不是把整个列表当成一个值）。
"""


def diff_paths(before: dict, after: dict) -> list[tuple[str, object, object]]:
    """返回所有取值变化的 (json-path, before, after) 列表（点分/索引路径）。"""
    diffs: list[tuple[str, object, object]] = []

    def walk(a, b, path):
        if a == b:
            return
        if isinstance(a, dict) and isinstance(b, dict):
            for k in set(a) | set(b):
                child = k if path == "" else f"{path}.{k}"
                walk(a.get(k, "<MISSING>"), b.get(k, "<MISSING>"), child)
        elif isinstance(a, list) and isinstance(b, list):
            for i in range(max(len(a), len(b))):
                av = a[i] if i < len(a) else "<MISSING>"
                bv = b[i] if i < len(b) else "<MISSING>"
                walk(av, bv, f"{path}[{i}]")
        else:
            diffs.append((path, a, b))

    walk(before, after, "")
    return diffs

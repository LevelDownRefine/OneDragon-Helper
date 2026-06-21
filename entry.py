import os
import shutil
import subprocess
import sys
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent


def get_path_under_work_dir(*parts):
    src_dir = BASE_DIR / "OneDragon-ScriptChainer" / "src"
    if str(src_dir) not in sys.path:
        sys.path.append(str(src_dir))

    from one_dragon.utils.os_utils import get_path_under_work_dir as _get_path_under_work_dir

    return _get_path_under_work_dir(*parts)

def copy_config():
    chain_name = "99.yml"
    input_path = BASE_DIR / chain_name
    output_path = get_path_under_work_dir("config", "script_chain")
    if not os.path.exists(os.path.join(output_path, chain_name)):
        shutil.copy(input_path, output_path)
        print(f"已复制配置文件到: {output_path}")

def copy_python_script(file_name):
    input_path = BASE_DIR / file_name
    output_path = get_path_under_work_dir("config", "script_chain", "scripts")
    if not os.path.exists(os.path.join(output_path, file_name)):
        shutil.copy(input_path, output_path)
        print(f"已复制Python脚本到: {output_path}")

def main():
    copy_config()
    # copy_python_script() is reserved until the companion script exists.

    launcher_work_dir = get_path_under_work_dir("src")
    command = [
        sys.executable,
        "-m",
        "script_chainer.win_exe.launcher",
    ]
    res = subprocess.run(
        command,
        cwd=launcher_work_dir,
    )
    return res.returncode

if __name__ == "__main__":
    raise SystemExit(main())

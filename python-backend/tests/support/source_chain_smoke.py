"""实机验证源码应用脚本链的参数和工作目录。"""

import json
import subprocess
import sys
import tempfile
import time
from pathlib import Path

import psutil

from src.service.chain_gen import generate_chain_config
from src.utils.utils_io import load_data


def main():
    project = Path(__file__).resolve().parents[3]
    sys.path.insert(0, str(project / "runner"))
    from script_chainer.config.script_config import ScriptConfig
    from script_chainer.win_exe.script_runner import _launch_script

    with tempfile.TemporaryDirectory(prefix="odh-source-chain-") as directory:
        root = Path(directory)
        subprocess.run(
            [
                str(project / ".venv" / "Scripts" / "uv.exe"),
                "venv",
                "--python",
                getattr(sys, "_base_executable", sys.executable),
                str(root / ".venv"),
            ],
            check=True,
        )
        script = root / "main.py"
        script.write_text(
            "import json, os, sys\n"
            "from pathlib import Path\n"
            "Path('result.json').write_text(json.dumps([os.getcwd(), sys.argv[1:]]))\n",
            encoding="utf-8",
        )
        entry = {
            "display_name": "Source test",
            "script_path": str(script),
            "source_root": str(root),
            "source_arguments": [
                "hello world",
                "",
                'quote"here',
                "中文",
                "line\nbreak",
            ],
            "check_done": "script_closed",
            "kill_game_after_done": False,
        }
        chain = str(root / "chain.yml")
        generate_chain_config({"script_list": [entry]}, {"Source test"}, out_path=chain)
        subprocess.run(
            [sys.executable, str(project / "runner" / "launcher.py"), "--chain", chain],
            cwd=project,
            check=True,
            timeout=60,
        )
        cwd, arguments = json.loads((root / "result.json").read_text())
        assert Path(cwd).resolve() == root.resolve()
        assert arguments == ["hello world", "", 'quote"here', "中文", "line\nbreak"]

        script.write_text(
            "import subprocess, sys, time\n"
            "from pathlib import Path\n"
            "p=subprocess.Popen([sys.executable, '-c', 'import time; time.sleep(60)'])\n"
            "Path('child.pid').write_text(str(p.pid))\n"
            "time.sleep(60)\n",
            encoding="utf-8",
        )
        generated = load_data(chain, file_format="yaml")["script_list"][0]
        generated["script_path"] = str(root / ".venv" / "Scripts" / "python.exe")
        manager = _launch_script(ScriptConfig(**generated))
        try:
            marker = root / "child.pid"
            deadline = time.monotonic() + 15
            while not marker.exists() and time.monotonic() < deadline:
                time.sleep(0.05)
            assert marker.exists(), "子进程未启动"
            child_pid = int(marker.read_text())
            process = manager.process
            assert process is not None
            manager.kill()
            assert process.poll() is not None
            assert not psutil.pid_exists(child_pid), "子进程未退出"
        finally:
            manager.kill()


if __name__ == "__main__":
    main()

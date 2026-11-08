"""实机验证源码应用脚本链的参数和工作目录。"""

import json
import subprocess
import sys
import tempfile
from pathlib import Path

from src.service.chain_gen import generate_chain_config


def main():
    project = Path(__file__).resolve().parents[3]
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
            "source_arguments": ["hello world"],
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
        assert arguments == ["hello world"]


if __name__ == "__main__":
    main()

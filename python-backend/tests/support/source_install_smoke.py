"""在临时目录实际安装最小源码项目并运行。"""

import os
import subprocess
import tempfile
from pathlib import Path

from dulwich import porcelain
from source_app_manager import launch_command

from src.service.source_app_service import install_source_application


def main():
    with tempfile.TemporaryDirectory(prefix="odh-source-smoke-") as directory:
        root = Path(directory)
        repository = root / "repository"
        repository.mkdir()
        porcelain.init(repository).close()
        (repository / "requirements.txt").touch()
        (repository / "main.py").write_text(
            "import sys\nprint(repr(sys.argv[1:]))\n", encoding="utf-8"
        )
        porcelain.add(repository, ["requirements.txt", "main.py"])
        porcelain.commit(
            repository,
            message=b"initial",
            author=b"Test <test@example.org>",
            committer=b"Test <test@example.org>",
        )
        porcelain.tag_create(repository, "v1")
        if os.name == "nt":
            os.environ["PATH"] = r"C:\Windows\System32;C:\Windows"
        result = install_source_application(
            "example", str(repository), "v1", "3.12", "requirements.txt", str(root)
        )
        command = launch_command(Path(result["source"]), "main.py", ["hello world"])
        process = subprocess.run(
            [command.program, *command.arguments],
            cwd=command.working_directory,
            check=True,
            capture_output=True,
            text=True,
        )
        assert process.stdout.strip() == "['hello world']"


if __name__ == "__main__":
    main()

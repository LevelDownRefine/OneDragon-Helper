"""实机验证源码安装不会污染无头协议输出。"""

import json
import os
import subprocess
import tempfile
import time
from pathlib import Path

from dulwich import porcelain

from tests.support.headless import PROJECT_ROOT, HeadlessFixture


def main():
    with tempfile.TemporaryDirectory(prefix="odh-source-rpc-") as directory:
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
        executable = os.environ.get("ODH_SOURCE_CLI")
        fixture_root = Path(executable).parent if executable else root / "helper"
        fixture_root.mkdir(exist_ok=True)
        fixture = HeadlessFixture(fixture_root)
        environment = os.environ.copy()
        if os.name == "nt":
            environment["PATH"] = r"C:\Windows\System32;C:\Windows"
        with subprocess.Popen(
            [executable, "serve", "--stdio"]
            if executable
            else fixture.command("serve", "--stdio"),
            cwd=PROJECT_ROOT,
            env=environment,
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            text=True,
            encoding="utf-8",
        ) as process:
            assert process.stdin is not None and process.stdout is not None

            def request(method, params):
                payload = {
                    "jsonrpc": "2.0",
                    "id": 1,
                    "method": method,
                    "params": params,
                }
                process.stdin.write(json.dumps(payload) + "\n")
                process.stdin.flush()
                response = json.loads(process.stdout.readline())
                assert "result" in response, response
                return response["result"]

            job = request(
                "source.install",
                {
                    "application_id": "test-source",
                    "repository": str(repository),
                    "revision": "v1",
                    "python_version": "3.12",
                    "requirements": "requirements.txt",
                    "directory": str(root),
                },
            )
            deadline = time.monotonic() + 180
            while True:
                result = request("job.poll", {"job_id": job["id"]})
                if result["state"] != "running":
                    break
                if time.monotonic() >= deadline:
                    raise TimeoutError("源码安装未完成")
                time.sleep(0.25)
            assert result["state"] == "succeeded", result
            source = Path(result["result"]["source"])
            request(
                "source.register",
                {
                    "application_id": "test-source",
                    "display_name": "源码测试",
                    "source_root": str(source),
                    "script_path": str(source / "main.py"),
                    "manual_arguments": ["hello world"],
                    "run_arguments": [],
                },
            )
            command = request(
                "script.launch_target",
                {"script_name": "test-source", "target": "script"},
            )
            completed = subprocess.run(
                [command["program"], *command["args"]],
                cwd=command["cwd"],
                check=True,
                capture_output=True,
                text=True,
            )
            assert completed.stdout.strip() == "['hello world']"
            request(
                "source.configure",
                {
                    "script_name": "test-source",
                    "script_path": str(source / "main.py"),
                    "manual_arguments": ["changed"],
                    "run_arguments": ["scheduled"],
                },
            )
            command = request(
                "script.launch_target",
                {"script_name": "test-source", "target": "script"},
            )
            assert command["args"][-1] == "changed"
            process.stdin.close()
            assert process.wait(timeout=15) == 0


if __name__ == "__main__":
    main()

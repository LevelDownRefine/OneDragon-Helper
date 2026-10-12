"""Wait for a successful build of the exact release commit; otherwise rebuild."""

import argparse
import json
import logging
import subprocess
import time
from pathlib import Path

logger = logging.getLogger(__name__)


def find_build_run(
    repository: str, commit: str, wait_seconds: int = 1200
) -> int | None:
    deadline = time.monotonic() + wait_seconds
    waiting_for = None
    while True:
        try:
            result = subprocess.run(
                [
                    "gh",
                    "run",
                    "list",
                    "--repo",
                    repository,
                    "--workflow",
                    "build-exe.yml",
                    "--event",
                    "push",
                    "--commit",
                    commit,
                    "--limit",
                    "20",
                    "--json",
                    "databaseId,status,conclusion,headSha,headBranch",
                ],
                capture_output=True,
                text=True,
                timeout=30,
                check=False,
            )
        except (OSError, subprocess.TimeoutExpired) as exc:
            logger.warning(
                "Build lookup failed (%s): %s; rebuilding", type(exc).__name__, exc
            )
            return None
        if result.returncode:
            logger.warning("Build lookup failed: %s; rebuilding", result.stderr.strip())
            return None
        try:
            runs = json.loads(result.stdout)
            required = {"databaseId", "status", "conclusion", "headSha", "headBranch"}
            if not isinstance(runs, list) or any(
                not isinstance(run, dict)
                or not required <= run.keys()
                or type(run["databaseId"]) is not int
                or run["databaseId"] <= 0
                or not all(
                    isinstance(run[key], str)
                    for key in ("status", "headSha", "headBranch")
                )
                or (
                    run["conclusion"] is not None
                    and not isinstance(run["conclusion"], str)
                )
                for run in runs
            ):
                raise ValueError("Incomplete workflow runs")
        except ValueError as exc:
            logger.warning(
                "Invalid build lookup (%s): %s; rebuilding", type(exc).__name__, exc
            )
            return None
        candidates = [
            run
            for run in runs
            if run["headSha"] == commit and run["headBranch"] in {"main", "master"}
        ]
        for run in candidates:
            if run["status"] == "completed" and run["conclusion"] == "success":
                return run["databaseId"]
        active = [
            run
            for run in candidates
            if run["status"]
            in {"queued", "in_progress", "requested", "waiting", "pending"}
        ]
        remaining = deadline - time.monotonic()
        if not active or remaining <= 0:
            logger.info("No successful build available; rebuilding")
            return None
        if waiting_for != active[0]["databaseId"]:
            waiting_for = active[0]["databaseId"]
            logger.info("Waiting for build run %s", waiting_for)
        time.sleep(min(15, remaining))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repository", required=True)
    parser.add_argument("--commit", required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    logging.basicConfig(level=logging.INFO)
    run = find_build_run(args.repository, args.commit)
    with args.output.open("a", encoding="utf-8") as output:
        output.write(f"run-id={run if run is not None else ''}\n")


if __name__ == "__main__":
    main()

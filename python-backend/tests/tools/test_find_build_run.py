"""Release reuse waits only for successful, exact-commit main builds."""

import json
import subprocess
import unittest
from unittest.mock import Mock, patch

from tools.find_build_run import find_build_run


def run(
    identity=1, status="completed", conclusion="success", commit="target", branch="main"
):
    return {
        "databaseId": identity,
        "status": status,
        "conclusion": conclusion,
        "headSha": commit,
        "headBranch": branch,
    }


def response(runs):
    return Mock(returncode=0, stdout=json.dumps(runs), stderr="")


class FindBuildRunTests(unittest.TestCase):
    def test_waits_until_exact_build_finishes_successfully(self):
        with (
            patch(
                "tools.find_build_run.subprocess.run",
                side_effect=[
                    response([run(status="in_progress", conclusion=None)]),
                    response([run()]),
                ],
            ) as command,
            patch("tools.find_build_run.time.sleep") as sleep,
        ):
            self.assertEqual(find_build_run("owner/repo", "target"), 1)
        sleep.assert_called_once()
        args = command.call_args.args[0]
        self.assertIn("push", args)
        self.assertIn("target", args)

    def test_never_reuses_other_commit_branch_or_failed_runs(self):
        with (
            patch(
                "tools.find_build_run.subprocess.run",
                return_value=response(
                    [
                        run(commit="other"),
                        run(branch="feature"),
                        run(conclusion="failure"),
                    ]
                ),
            ),
            patch("tools.find_build_run.time.sleep") as sleep,
        ):
            self.assertIsNone(find_build_run("owner/repo", "target"))
        sleep.assert_not_called()

    def test_success_is_available_despite_newer_failed_attempt(self):
        with patch(
            "tools.find_build_run.subprocess.run",
            return_value=response(
                [run(identity=2, conclusion="failure"), run(identity=1)]
            ),
        ):
            self.assertEqual(find_build_run("owner/repo", "target"), 1)

    def test_timeout_and_failed_build_fall_back(self):
        with (
            patch(
                "tools.find_build_run.subprocess.run",
                return_value=response([run(status="in_progress", conclusion=None)]),
            ),
            patch("tools.find_build_run.time.monotonic", side_effect=[0, 20]),
        ):
            self.assertIsNone(find_build_run("owner/repo", "target", wait_seconds=10))
        with (
            patch(
                "tools.find_build_run.subprocess.run",
                side_effect=[
                    response([run(status="queued", conclusion=None)]),
                    response([run(conclusion="failure")]),
                ],
            ),
            patch("tools.find_build_run.time.sleep"),
        ):
            self.assertIsNone(find_build_run("owner/repo", "target"))

    def test_lookup_errors_fall_back(self):
        for result in (
            Mock(returncode=1, stderr="API unavailable"),
            Mock(returncode=0, stdout="bad json"),
            response([{"databaseId": 1}]),
            response([run(status=[])]),
        ):
            with (
                self.subTest(result=result),
                patch("tools.find_build_run.subprocess.run", return_value=result),
                self.assertLogs("tools.find_build_run", level="WARNING"),
            ):
                self.assertIsNone(find_build_run("owner/repo", "target"))
        with (
            patch(
                "tools.find_build_run.subprocess.run",
                side_effect=subprocess.TimeoutExpired("gh", 30),
            ),
            self.assertLogs("tools.find_build_run", level="WARNING"),
        ):
            self.assertIsNone(find_build_run("owner/repo", "target"))

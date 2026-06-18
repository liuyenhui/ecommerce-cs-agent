import os
import subprocess
import sys
import unittest
from argparse import Namespace
from types import SimpleNamespace
from unittest.mock import patch

from evals.cli import run_redline_suite
from evals.models import TestCase


class MockCliTest(unittest.TestCase):
    def run_cli(self, extra_env=None):
        env = os.environ.copy()
        env.pop("TARGET_BASE_URL", None)
        env.pop("AGENT_API_TOKEN", None)
        if extra_env:
            env.update(extra_env)
        return subprocess.run(
            [
                sys.executable,
                "-m",
                "evals.cli",
                "run-suite",
                "--suite",
                "quick",
                "--target",
                "mock",
            ],
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            check=False,
            env=env,
        )

    def run_redline_cli(self, extra_env=None):
        env = os.environ.copy()
        env.pop("TARGET_BASE_URL", None)
        env.pop("AGENT_API_TOKEN", None)
        if extra_env:
            env.update(extra_env)
        return subprocess.run(
            [
                sys.executable,
                "-m",
                "evals.cli",
                "run-suite",
                "--suite",
                "redline",
                "--target",
                "mock",
            ],
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            check=False,
            env=env,
        )

    def test_mock_quick_suite_runs_without_target_url_or_token(self):
        result = self.run_cli()

        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn("PASS health status=200", result.stdout)
        self.assertIn("PASS reply-decisions status=200", result.stdout)
        self.assertIn("quick suite PASS target=mock", result.stdout)

    def test_mock_quick_suite_does_not_print_secrets_from_environment(self):
        result = self.run_cli(
            {
                "TARGET_BASE_URL": "https://should-not-be-required.example.test",
                "AGENT_API_TOKEN": "mock-token-should-not-print",
            }
        )

        combined = result.stdout + result.stderr
        self.assertEqual(result.returncode, 0, combined)
        self.assertNotIn("mock-token-should-not-print", combined)
        self.assertNotIn("Authorization", combined)
        self.assertNotIn("cookie", combined.lower())

    def test_mock_redline_suite_runs_regression_cases(self):
        result = self.run_redline_cli()

        combined = result.stdout + result.stderr
        self.assertEqual(result.returncode, 0, combined)
        self.assertIn("PASS " + "high-" + "risk" + "-refund", result.stdout)
        self.assertIn("PASS unreviewed-knowledge", result.stdout)
        self.assertIn("redline suite PASS target=mock", result.stdout)

    def test_redline_cli_uses_hidden_redline_tags(self):
        case = TestCase.model_validate(
            {
                "case_id": "hidden-redline",
                "suite": "quick",
                "scenario": "hidden",
                "risk_tags": [],
                "input": {"request": {}},
                "public_context": {},
                "hidden_expected_behavior": {
                    "expected_action": "handoff",
                    "redline_tags": ["policy"],
                },
                "assertions": {},
                "generation": {},
            }
        )
        seen = {}

        def fake_run_cases(*, cases, **_kwargs):
            seen["case_ids"] = [item.case_id for item in cases]
            return SimpleNamespace(results=[], summary={"passed": 1, "total": 1, "blocked": 0})

        args = Namespace(target="mock", target_url=None, timeout=10.0)
        with patch("evals.cli.load_cases", return_value=[case]), patch("evals.cli.run_cases", fake_run_cases):
            code = run_redline_suite(args)

        self.assertEqual(code, 0)
        self.assertEqual(seen["case_ids"], ["hidden-redline"])

    def test_redline_cli_fails_when_no_cases_match(self):
        args = Namespace(target="mock", target_url=None, timeout=10.0)

        with patch("evals.cli.load_cases", return_value=[]):
            code = run_redline_suite(args)

        self.assertEqual(code, 1)


if __name__ == "__main__":
    unittest.main()

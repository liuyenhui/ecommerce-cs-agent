import os
import subprocess
import sys
import unittest


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


if __name__ == "__main__":
    unittest.main()

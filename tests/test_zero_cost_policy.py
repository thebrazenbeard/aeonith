"""Regression checks for Aeonith's absolute $0 deployment boundary.

These are configuration and policy tests, not evidence that a machine already
has a locally installed model or that inference itself is working.
"""

from __future__ import annotations

from pathlib import Path
import re
import tomllib
import unittest

from aeonith.service import is_ready


ROOT = Path(__file__).resolve().parents[1]


class ZeroCostPolicyTests(unittest.TestCase):
    def test_no_active_vercel_deployment_configuration(self):
        self.assertFalse((ROOT / "vercel.json").exists())
        metadata = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))
        self.assertNotIn("vercel", metadata.get("tool", {}))

    def test_service_is_disabled_with_no_local_model_configuration(self):
        self.assertFalse(is_ready({}))

    def test_billable_remote_provider_cannot_be_enabled_by_api_credentials(self):
        # Even a caller with a syntactically valid secret and an operator
        # switch must not accidentally activate a remote paid-model endpoint.
        # This is deliberately a readiness check with NO network activity.
        env = {
            "AEONITH_SERVICE_TOKEN": "t" * 48,
            "AEONITH_ENABLE_LIVE_REVIEWS": "true",
            "AEONITH_PROVIDER_KIND": "openai-responses",
            "AEONITH_PROVIDER_URL": "https://api.openai.com/v1/responses",
            "AEONITH_PROVIDER_MODEL": "synthetic-model",
            "AEONITH_PROVIDER_API_KEY": "not-a-real-token",
        }
        self.assertFalse(is_ready(env))
        # A publicly reachable TLS origin changes only the browser ingress.
        # It must never make a remote or metered inference provider available.
        self.assertFalse(is_ready({
            **env,
            "AEONITH_FUNNEL_ORIGIN": "https://critic.example-tailnet.ts.net",
        }))

    def test_ci_never_starts_billable_private_repo_runner(self):
        workflows = sorted((ROOT / ".github" / "workflows").glob("*.yml"))
        workflows.extend(sorted((ROOT / ".github" / "workflows").glob("*.yaml")))
        # Any additional workflow must be deliberately reviewed and admitted
        # through a policy change; no unattended deployment job is authorized.
        self.assertEqual([ROOT / ".github" / "workflows" / "ci.yml"], workflows)
        for path in workflows:
            with self.subTest(workflow=path.name):
                content = path.read_text(encoding="utf-8")
                # Job-level guard is required: step-level guards start a
                # runner first and could incur billable private minutes.
                self.assertRegex(
                    content,
                    r"(?m)^    if: \$\{\{ github\.event\.repository\.private == false \}\}$",
                )
                self.assertIn("permissions:\n  contents: read", content)
                self.assertNotIn("vercel", content.lower())
                # Deliberately no third-party deployment, model, or billing
                # action. New actions require explicit policy review.
                actions = re.findall(r"(?m)^\s*- uses:\s*(\S+)", content)
                self.assertEqual(["actions/checkout@v4", "actions/setup-python@v5"], actions)


if __name__ == "__main__":
    unittest.main()

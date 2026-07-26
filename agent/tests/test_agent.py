import os
import unittest
from unittest.mock import patch

from jheliz_agent.config import AgentConfig
from jheliz_agent.models import AgentJob, JobStatus
from jheliz_agent.netflix import NetflixAdapter


VALID_JOB = {
    "id": "job-test-1",
    "service": "netflix",
    "action": "create_profile",
    "profile_name": "Juan",
    "profile_pin": "4025",
    "account_reference": "account-17",
    "account_email": "netflix@example.com",
    "expires_at": "2026-07-25T23:00:00Z",
}


class AgentTests(unittest.TestCase):
    def test_job_accepts_valid_netflix_profile(self):
        job = AgentJob.from_payload(VALID_JOB)
        self.assertEqual(job.profile_name, "Juan")

    def test_job_rejects_invalid_pin(self):
        with self.assertRaisesRegex(ValueError, "PIN"):
            AgentJob.from_payload({**VALID_JOB, "profile_pin": "abcd"})

    def test_dry_run_never_changes_external_account(self):
        config = AgentConfig(
            api_url="https://example.test", token="x" * 40,
            name="test", dry_run=True, poll_seconds=5,
            browser="chromium", headless=False,
            mail_control_url="", mail_control_token="",
            allow_real_netflix=False, browser_profile_dir="./test-profile",
            code_wait_seconds=30,
        )
        result = NetflixAdapter(config).execute(AgentJob.from_payload(VALID_JOB))
        self.assertEqual(result.status, JobStatus.SUCCEEDED)
        self.assertTrue(result.evidence["dry_run"])

    def test_real_mode_remains_blocked(self):
        config = AgentConfig(
            api_url="https://example.test", token="x" * 40,
            name="test", dry_run=False, poll_seconds=5,
            browser="chromium", headless=False,
            mail_control_url="", mail_control_token="",
            allow_real_netflix=False, browser_profile_dir="./test-profile",
            code_wait_seconds=30,
        )
        result = NetflixAdapter(config).execute(AgentJob.from_payload(VALID_JOB))
        self.assertEqual(result.status, JobStatus.NEEDS_ATTENTION)

    @patch.dict(os.environ, {
        "JHELIZ_AGENT_API_URL": "http://unsafe.test",
        "JHELIZ_AGENT_TOKEN": "x" * 40,
    }, clear=True)
    def test_config_requires_https(self):
        with self.assertRaisesRegex(ValueError, "HTTPS"):
            AgentConfig.from_env()


if __name__ == "__main__":
    unittest.main()

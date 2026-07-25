import json
import tempfile
import threading
import unittest
import urllib.error
import urllib.request
from pathlib import Path

from bot.agent_api import AgentHttpServer
from bot.db.database import close_db, init_db
from config import Settings


class AgentApiTests(unittest.TestCase):
    def setUp(self):
        self.tempdir = tempfile.TemporaryDirectory()
        db_path = Path(self.tempdir.name) / "agent-api.db"
        init_db(f"sqlite:///{db_path.as_posix()}")
        self.settings = Settings(
            bot_token="unused",
            agent_encryption_key="7SWDts0OIXZIXdA0BwbVAHgaJghJ4VGTo91lAoVcoEo=",
            agent_api_token="t" * 48,
        )
        self.server = AgentHttpServer(("127.0.0.1", 0), self.settings)
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()
        self.base = f"http://127.0.0.1:{self.server.server_port}/api/agent/v1"

    def tearDown(self):
        self.server.shutdown()
        self.server.server_close()
        self.thread.join(timeout=2)
        close_db()
        self.tempdir.cleanup()

    def post(self, path, payload, token=None):
        request = urllib.request.Request(
            self.base + path,
            data=json.dumps(payload).encode(),
            method="POST",
            headers={
                "Authorization": f"Bearer {token or self.settings.agent_api_token}",
                "Content-Type": "application/json",
            },
        )
        with urllib.request.urlopen(request, timeout=3) as response:
            return response.status, json.load(response)

    def test_rejects_invalid_token(self):
        with self.assertRaises(urllib.error.HTTPError) as caught:
            self.post("/heartbeat", {"agent_name": "office"}, token="wrong")
        self.assertEqual(caught.exception.code, 401)

    def test_heartbeat_registers_agent(self):
        status, payload = self.post("/heartbeat", {
            "agent_name": "office",
            "dry_run": True,
            "capabilities": ["netflix.create_profile"],
        })
        self.assertEqual(status, 200)
        self.assertTrue(payload["dry_run"])
        self.assertGreater(payload["agent_id"], 0)

    def test_claim_without_jobs_is_empty(self):
        self.post("/heartbeat", {"agent_name": "office", "dry_run": True})
        status, payload = self.post("/jobs/claim", {"agent_name": "office"})
        self.assertEqual(status, 200)
        self.assertIsNone(payload["job"])


if __name__ == "__main__":
    unittest.main()

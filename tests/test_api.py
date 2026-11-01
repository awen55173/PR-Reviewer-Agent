import os
import tempfile
import unittest

try:
    from fastapi.testclient import TestClient
except (ImportError, RuntimeError):  # pragma: no cover - httpx 未安装时跳过
    TestClient = None

from evoagent.api.server import create_app
from evoagent.core.config import Settings
from evoagent.services.review_service import ReviewService
from agentic_fake import enable_agentic_service


DIFF = "--- a/a.py\n+++ b/a.py\n@@ -1 +1 @@\n-old\n+eval(data)\n"


@unittest.skipIf(TestClient is None, "fastapi TestClient requires httpx")
class ApiTests(unittest.TestCase):
    def make_settings(self, **overrides):
        values = dict(
            host="127.0.0.1", port=8080, db_path=self.path, max_diff_bytes=10000,
            max_steps=8, timeout_seconds=10, llm_base_url="", llm_api_key="", llm_model="",
            github_webhook_secret="", github_token="", auto_post_review=False,
        )
        values.update(overrides)
        return Settings(**values)

    def setUp(self):
        handle, self.path = tempfile.mkstemp(suffix=".db")
        os.close(handle)
        self.start(self.make_settings())

    def start(self, settings):
        self.service = enable_agentic_service(ReviewService(settings))
        self.client = TestClient(create_app(settings, self.service))
        self.client.__enter__()

    def tearDown(self):
        self.client.__exit__(None, None, None)
        self.service.queue.close()
        os.unlink(self.path)

    def test_health_and_security_headers(self):
        response = self.client.get("/health")
        self.assertEqual(200, response.status_code)
        self.assertEqual("ok", response.json()["status"])
        self.assertEqual("nosniff", response.headers["X-Content-Type-Options"])
        self.assertEqual("DENY", response.headers["X-Frame-Options"])

    def test_static_pages(self):
        self.assertEqual(200, self.client.get("/").status_code)
        self.assertEqual(200, self.client.get("/assets/app.js").status_code)
        self.assertEqual(404, self.client.get("/assets/index.html").status_code)

    def test_errors_use_unified_shape(self):
        missing = self.client.get("/no-such-route")
        self.assertEqual(404, missing.status_code)
        self.assertEqual({"error": "not found"}, missing.json())
        self.assertEqual(404, self.client.get("/v1/tasks/NOT_A_TASK").status_code)
        self.assertEqual("task not found", self.client.get("/v1/tasks/abc-123").json()["error"])
        invalid = self.client.post(
            "/v1/reviews", content=b"{bad", headers={"Content-Type": "application/json"},
        )
        self.assertEqual(400, invalid.status_code)
        self.assertEqual("request body must be valid UTF-8 JSON", invalid.json()["error"])
        wrong_type = self.client.post("/v1/reviews", json={"diff": DIFF, "pull_request": "1"})
        self.assertEqual(400, wrong_type.status_code)
        self.assertIn("pull_request", wrong_type.json()["error"])

    def test_body_size_limit(self):
        response = self.client.post("/v1/reviews", json={"diff": "x" * (10000 + 300 * 1024)})
        self.assertEqual(413, response.status_code)

    def test_review_lifecycle(self):
        created = self.client.post(
            "/v1/reviews", json={"repository": "org/repo", "diff": DIFF, "pull_request": 1},
        )
        self.assertEqual(201, created.status_code, created.text)
        task_id = created.json()["task_id"]
        self.assertEqual("SUCCESS", self.client.get("/v1/tasks/%s" % task_id).json()["state"])
        report = self.client.get("/v1/tasks/%s/report" % task_id)
        self.assertEqual(200, report.status_code)
        self.assertTrue(report.headers["content-type"].startswith("text/markdown"))
        self.assertEqual(1, len(self.client.get("/api/tasks").json()["tasks"]))

    def test_github_webhook_guards(self):
        ignored = self.client.post("/webhooks/github", content=b"{}", headers={"X-GitHub-Event": "push"})
        self.assertEqual(202, ignored.status_code)
        self.assertTrue(ignored.json()["ignored"])
        unconfigured = self.client.post(
            "/webhooks/github", content=b"{}", headers={"X-GitHub-Event": "pull_request"},
        )
        self.assertEqual(503, unconfigured.status_code)

    def test_login_disabled_without_auth(self):
        response = self.client.post("/v1/auth/login", json={"username": "a", "password": "b"})
        self.assertEqual(409, response.status_code)

    def test_authentication_and_permissions(self):
        self.client.__exit__(None, None, None)
        self.service.queue.close()
        self.start(self.make_settings(
            auth_required=True, auth_secret="s" * 40,
            bootstrap_admin_username="admin", bootstrap_admin_password="admin-password-1",
        ))
        self.assertEqual(200, self.client.get("/health").status_code)
        self.assertEqual(401, self.client.get("/api/dashboard").status_code)
        self.assertEqual(401, self.client.post("/v1/skills/reload").status_code)
        bad = self.client.post("/v1/auth/login", json={"username": "admin", "password": "wrong-password"})
        self.assertEqual(401, bad.status_code)
        token = self.client.post(
            "/v1/auth/login", json={"username": "admin", "password": "admin-password-1"},
        ).json()["access_token"]
        headers = {"Authorization": "Bearer " + token}
        self.assertEqual(200, self.client.get("/api/dashboard", headers=headers).status_code)
        self.assertEqual(200, self.client.get("/api/audit", headers=headers).status_code)


if __name__ == "__main__":
    unittest.main()

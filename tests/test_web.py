"""HTTP and graphical-form tests using a separate temporary repository."""

import http.client
import json
import tempfile
import threading
import unittest
from pathlib import Path

from norin_delivery.storage import JsonRepository
from norin_delivery.web import DeliveryWebServer


class BrowserClient:
    def __init__(self, server):
        self.port = server.server_port
        self.cookie = ""
        self.csrf = ""

    def request(self, path, data=None, headers=None):
        connection = http.client.HTTPConnection("127.0.0.1", self.port, timeout=10)
        fields = {"Cookie": self.cookie}
        body = None
        if data is not None:
            body = json.dumps(data)
            fields.update({"Content-Type": "application/json", "X-CSRF-Token": self.csrf,
                           "Origin": f"http://127.0.0.1:{self.port}"})
        fields.update(headers or {})
        connection.request("POST" if data is not None else "GET", path, body, fields)
        response = connection.getresponse()
        status = response.status
        cookie = response.getheader("Set-Cookie")
        if cookie:
            self.cookie = cookie.split(";", 1)[0]
        content_type = response.getheader("Content-Type")
        text = response.read().decode("utf-8")
        connection.close()
        if "application/json" in content_type:
            payload = json.loads(text)
            if "csrf" in payload:
                self.csrf = payload["csrf"]
            return status, payload
        return status, text


class WebTests(unittest.TestCase):
    def setUp(self):
        self.folder = tempfile.TemporaryDirectory()
        self.path = Path(self.folder.name) / "web.json"
        self.server = DeliveryWebServer(("127.0.0.1", 0), JsonRepository(self.path))
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()
        self.client = BrowserClient(self.server)
        self.client.request("/api/bootstrap")

    def tearDown(self):
        self.server.shutdown()
        self.server.server_close()
        self.thread.join(timeout=5)
        self.folder.cleanup()

    def manager(self):
        status, result = self.client.request("/api/setup", {
            "username": "manager", "password": "TestPass123!",
            "confirm_password": "TestPass123!",
        })
        self.assertEqual(status, 200, result)
        return result

    def customer(self):
        status, result = self.client.request("/api/customers", {
            "name": "Test Customer", "email": "test@example.com",
        })
        self.assertEqual(status, 200, result)
        return result["customers"][0]["customer_id"]

    def test_assets_are_served_without_external_dependencies(self):
        for path, contains in [("/", "app.js"), ("/app.js", "Delivery overview"),
                               ("/styles.css", "@media"), ("/favicon.svg", "<svg")]:
            with self.subTest(path=path):
                status, text = self.client.request(path)
                self.assertEqual(status, 200)
                self.assertIn(contains, text)
        self.assertEqual(self.client.request("/../storage.py")[0], 404)

    def test_private_records_require_login(self):
        self.assertEqual(self.client.request("/api/state")[0], 401)

    def test_host_origin_and_csrf_are_enforced(self):
        status, _ = self.client.request("/api/bootstrap", headers={"Host": "evil.example"})
        self.assertEqual(status, 403)
        status, _ = self.client.request("/api/logout", {}, {"X-CSRF-Token": "wrong"})
        self.assertEqual(status, 403)
        status, _ = self.client.request("/api/logout", {}, {"Origin": "https://evil.example"})
        self.assertEqual(status, 403)

    def test_manager_setup_does_not_expose_password_hashes(self):
        result = self.manager()
        serialized = json.dumps(result)
        self.assertNotIn("credential_hash", serialized)
        self.assertNotIn("pbkdf2", serialized)
        self.assertNotIn("TestPass123", serialized)
        self.assertEqual(result["actor"]["role"], "Manager")
        self.assertFalse(result["needs_setup"])

    def test_registration_and_browser_sessions_are_isolated(self):
        self.manager()
        other = BrowserClient(self.server)
        other.request("/api/bootstrap")
        status, result = other.request("/api/register", {
            "name": "Customer", "email": "customer@example.com", "username": "customer",
            "password": "Customer123!", "confirm_password": "Customer123!",
        })
        self.assertEqual(status, 200, result)
        self.assertEqual(result["actor"]["role"], "Customer")
        self.assertEqual(result["accounts"], [])
        self.assertEqual(self.client.request("/api/state")[1]["actor"]["role"], "Manager")
        self.assertEqual(other.request("/api/customers", {"name": "Bad"})[0], 400)
        other.request("/api/logout", {})
        self.assertEqual(other.request("/api/state")[0], 401)

    def test_whole_request_form_saves_atomically_and_preserves_parcel_ids(self):
        self.manager()
        customer_id = self.customer()
        data = {"customer_id": customer_id, "pickup": "Melbourne", "destination": "Hawthorn",
                "parcels": [{"description": "Books"}, {"description": ""}]}
        status, _ = self.client.request("/api/requests", data)
        self.assertEqual(status, 400)
        self.assertFalse(self.server.repository.records.requests)
        data["parcels"][1]["description"] = "Clothes"
        status, result = self.client.request("/api/requests", data)
        self.assertEqual(status, 200, result)
        request = result["requests"][0]
        parcel = request["parcels"][0]
        edits = {"request_id": request["request_id"], "pickup": "Fitzroy",
                 "destination": "Richmond", "parcels": [
                     {"parcel_id": parcel["parcel_id"], "description": "Textbooks"},
                 ]}
        status, result = self.client.request("/api/requests/save", edits)
        self.assertEqual(status, 200, result)
        updated = result["requests"][0]
        self.assertEqual(updated["pickup_address"], "Fitzroy")
        self.assertEqual(len(updated["parcels"]), 1)
        self.assertEqual(updated["parcels"][0]["parcel_id"], parcel["parcel_id"])
        before = self.path.read_bytes()
        edits["parcels"][0]["description"] = ""
        self.assertEqual(self.client.request("/api/requests/save", edits)[0], 400)
        self.assertEqual(self.path.read_bytes(), before)

    def test_quote_form_validation_and_decision(self):
        self.manager()
        customer_id = self.customer()
        _, result = self.client.request("/api/requests", {
            "customer_id": customer_id, "pickup": "Melbourne", "destination": "Hawthorn",
            "parcels": [{"description": "Books"}],
        })
        request_id = result["requests"][0]["request_id"]
        data = {"request_id": request_id, "cost": "-5", "pickup_time": "2026-11-01T09:00",
                "delivery_time": "2026-11-01T11:00"}
        self.assertEqual(self.client.request("/api/quotes", data)[0], 400)
        data["cost"] = "45.50"
        status, result = self.client.request("/api/quotes", data)
        self.assertEqual(status, 200, result)
        quote_id = result["quotes"][0]["quote_id"]
        status, result = self.client.request("/api/quotes/decision", {
            "quote_id": quote_id, "accept": True,
        })
        self.assertEqual(status, 200, result)
        self.assertEqual(result["quotes"][0]["decision"], "Accepted")
        self.assertTrue(result["quotes"][0]["delivery_id"].startswith("DEMO-"))
        self.assertEqual(self.client.request("/api/requests/save", {
            "request_id": request_id, "pickup": "Changed", "destination": "Hawthorn",
        })[0], 400)

    def test_customer_cannot_access_other_customers_requests(self):
        self.manager()
        customer_id = self.customer()
        _, result = self.client.request("/api/requests", {
            "customer_id": customer_id, "pickup": "A", "destination": "B",
        })
        request_id = result["requests"][0]["request_id"]
        other = BrowserClient(self.server)
        other.request("/api/bootstrap")
        other.request("/api/register", {"name": "Other", "email": "other@example.com",
                                      "username": "other", "password": "Other123!",
                                      "confirm_password": "Other123!"})
        self.assertEqual(other.request("/api/state")[1]["requests"], [])
        self.assertEqual(other.request("/api/requests/save", {"request_id": request_id})[0], 400)

    def test_invalid_form_types_return_validation_errors(self):
        self.manager()
        self.assertEqual(self.client.request("/api/customers", {"name": []})[0], 400)
        self.assertEqual(self.client.request("/api/requests", {"parcels": "wrong"})[0], 400)
        self.assertEqual(self.client.request("/api/quotes/decision", {"accept": "false"})[0], 400)

    def test_health_identifies_workspace_without_exposing_path(self):
        status, result = self.client.request("/api/health")
        self.assertEqual(status, 200)
        self.assertEqual(result["application"], "norin-delivery")
        self.assertEqual(len(result["workspace"]), 64)
        self.assertNotIn(str(self.path), json.dumps(result))

    def test_manager_can_close_server_without_deleting_records(self):
        self.manager()
        before = self.path.read_bytes()
        status, result = self.client.request("/api/shutdown", {})
        self.assertEqual(status, 200, result)
        self.thread.join(timeout=3)
        self.assertFalse(self.thread.is_alive())
        self.assertEqual(self.path.read_bytes(), before)


if __name__ == "__main__":
    unittest.main()

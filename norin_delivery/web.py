"""Loopback-only web interface over the existing application service.

Uses Python's standard library. A single HTTPServer serialises repository
operations. Each browser session has its own signed-in application instance.
"""

import argparse
import hashlib
import json
import mimetypes
import secrets
import threading
import time
import webbrowser
from dataclasses import asdict, dataclass
from http.cookies import SimpleCookie
from http.server import BaseHTTPRequestHandler, HTTPServer
from importlib.resources import files
from pathlib import Path
from urllib.parse import urlsplit
from urllib.request import urlopen

from .integration import DemoDeliveryGateway
from mekno_delivery import DeliveryRepository, DeliveryOperations, MeknoGateway
from .models import DomainError, Role
from .service import DeliveryApplication
from .storage import JsonRepository, StorageError


@dataclass
class Session:
    app: DeliveryApplication
    csrf: str
    last_used: float


def account_view(account) -> dict:
    """Never send credential hashes to a browser."""
    return {
        "account_id": account.account_id, "username": account.username,
        "role": account.role.value, "active": account.active,
        "customer_id": account.customer_id, "staff_id": account.staff_id,
    }


def text_field(data: dict, name: str, default: str = "") -> str:
    value = data.get(name, default)
    if not isinstance(value, str) or len(value) > 2000:
        raise DomainError(f"Invalid {name.replace('_', ' ')}.")
    return value


def parcel_fields(data: dict) -> list[dict[str, str]]:
    items = data.get("parcels", [])
    if not isinstance(items, list) or len(items) > 100:
        raise DomainError("Provide no more than 100 parcels per request.")
    result = []
    for item in items:
        if not isinstance(item, dict):
            raise DomainError("Invalid parcel information.")
        result.append({"parcel_id": text_field(item, "parcel_id"),
                       "description": text_field(item, "description")})
    return result


class DeliveryWebServer(HTTPServer):
    def __init__(self, address, repository, gateway=None):
        self.repository = repository
        self.gateway = gateway or DemoDeliveryGateway()
        self.delivery_repository = self.gateway.repository if isinstance(self.gateway, MeknoGateway) else None
        self.sessions: dict[str, Session] = {}
        super().__init__(address, WebHandler)

    @property
    def allowed_hosts(self) -> set[str]:
        return {f"127.0.0.1:{self.server_port}", f"localhost:{self.server_port}"}

    @property
    def workspace_id(self) -> str:
        path = str(self.repository.path.resolve()).casefold()
        return hashlib.sha256(path.encode()).hexdigest()

    def session(self, cookie: str) -> tuple[str, Session]:
        now = time.monotonic()
        for key in list(self.sessions):
            if now - self.sessions[key].last_used > 1800:
                del self.sessions[key]
        cookies = SimpleCookie()
        try:
            cookies.load(cookie)
            key = cookies["norin_session"].value if "norin_session" in cookies else ""
        except Exception:
            key = ""
        if key not in self.sessions:
            if len(self.sessions) >= 100:
                oldest = min(self.sessions, key=lambda k: self.sessions[k].last_used)
                del self.sessions[oldest]
            key = secrets.token_urlsafe(32)
            self.sessions[key] = Session(
                DeliveryApplication(self.repository, self.gateway),
                secrets.token_urlsafe(32), now,
            )
        session = self.sessions[key]
        session.last_used = now
        return key, session


class WebHandler(BaseHTTPRequestHandler):
    server: DeliveryWebServer

    def log_message(self, format, *args):
        # Avoid logging submitted personal data or credentials.
        pass

    def _begin(self) -> bool:
        self.key = ""
        if self.headers.get("Host") not in self.server.allowed_hosts:
            self._json({"error": "This application accepts local requests only."}, 403)
            return False
        self.key, self.session = self.server.session(self.headers.get("Cookie", ""))
        return True

    def _send(self, body: bytes, content_type: str, status: int = 200) -> None:
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("Referrer-Policy", "no-referrer")
        self.send_header("X-Frame-Options", "DENY")
        self.send_header(
            "Content-Security-Policy",
            "default-src 'self'; script-src 'self'; style-src 'self'; "
            "img-src 'self' data:; connect-src 'self'; frame-ancestors 'none'; "
            "base-uri 'none'; form-action 'self'",
        )
        if self.key:
            self.send_header("Set-Cookie", f"norin_session={self.key}; Path=/; HttpOnly; "
                             "SameSite=Strict; Max-Age=1800")
        self.end_headers()
        try:
            self.wfile.write(body)
        except (BrokenPipeError, ConnectionResetError):
            pass

    def _json(self, payload: dict, status: int = 200) -> None:
        body = json.dumps(payload, default=JsonRepository._encode).encode("utf-8")
        self._send(body, "application/json; charset=utf-8", status)

    def _bootstrap(self) -> dict:
        app = self.session.app
        try:
            actor = account_view(app.actor) if app.signed_in else None
        except DomainError:
            app.logout()
            actor = None
        return {"needs_setup": app.needs_setup, "actor": actor,
                "csrf": self.session.csrf,
                "demo_delivery": isinstance(self.server.gateway, DemoDeliveryGateway)}

    def _state(self) -> dict:
        app = self.session.app
        actor = app.actor
        return {
            **self._bootstrap(),
            **(DeliveryOperations(self.server.delivery_repository, app).view()
               if self.server.delivery_repository else {}),
            "customers": [asdict(x) for x in app.list_customers()],
            "requests": [asdict(x) for x in app.list_requests()],
            "quotes": [asdict(x) for x in app.list_quotes()],
            "accounts": [account_view(x) for x in app.list_accounts()]
            if actor.role == Role.MANAGER else [],
        }

    def do_GET(self) -> None:
        if not self._begin():
            return
        path = urlsplit(self.path).path
        try:
            if path == "/api/health":
                self._json({"application": "norin-delivery",
                            "workspace": self.server.workspace_id})
            elif path == "/api/bootstrap":
                self._json(self._bootstrap())
            elif path == "/api/state":
                self._json(self._state())
            elif path in ("/", "/index.html", "/app.js", "/styles.css", "/favicon.svg"):
                name = "index.html" if path == "/" else path[1:]
                asset = files("norin_delivery").joinpath("static", name)
                mime = mimetypes.guess_type(name)[0] or "application/octet-stream"
                if name.endswith(".js"):
                    mime = "text/javascript"
                self._send(asset.read_bytes(), mime + "; charset=utf-8")
            else:
                self._json({"error": "Page not found."}, 404)
        except DomainError as exc:
            self._json({"error": str(exc)}, 401)

    def do_POST(self) -> None:
        if not self._begin():
            return
        origin = self.headers.get("Origin")
        allowed = {"http://" + host for host in self.server.allowed_hosts}
        if (origin and origin not in allowed) or not secrets.compare_digest(
                self.headers.get("X-CSRF-Token", ""), self.session.csrf):
            self._json({"error": "Please refresh this page and try again."}, 403)
            return
        if self.headers.get("Content-Type", "").split(";")[0] != "application/json":
            self._json({"error": "JSON input is required."}, 415)
            return
        try:
            length = int(self.headers.get("Content-Length", "0"))
            if not 0 < length <= 65536:
                raise DomainError("Form is empty or too large.")
            data = json.loads(self.rfile.read(length))
            if not isinstance(data, dict):
                raise DomainError("Invalid form data.")
            self._dispatch(urlsplit(self.path).path, data)
            app = self.session.app
            self._json(self._state() if app.signed_in else self._bootstrap())
        except (DomainError, ValueError, KeyError, TypeError) as exc:
            message = str(exc) if isinstance(exc, DomainError) else "Check the form values."
            self._json({"error": message}, 400)
        except StorageError:
            message = "Unable to save changes. Check the data folder and try again."
            self._json({"error": message}, 500)

    def _dispatch(self, path: str, data: dict) -> None:
        app = self.session.app
        field = lambda name: text_field(data, name)
        if path in ("/api/setup", "/api/register", "/api/accounts"):
            if field("password") != field("confirm_password"):
                raise DomainError("Passwords do not match.")
        if path == "/api/setup":
            app.setup_manager(field("username"), field("password"))
            app.login(field("username"), field("password"))
        elif path == "/api/register":
            app.register_customer(field("name"), field("phone"), field("email"),
                                  field("username"), field("password"))
            app.login(field("username"), field("password"))
        elif path == "/api/login":
            app.login(field("username"), field("password"))
        elif path == "/api/logout":
            app.logout()
        elif path == "/api/shutdown":
            if app.actor.role != Role.MANAGER:
                raise DomainError("Only a manager can close the workspace.")
            app.logout()
            threading.Timer(0.3, self.server.shutdown).start()
        elif path == "/api/customers":
            app.create_phone_customer(field("name"), field("phone"), field("email"))
        elif path == "/api/customers/update":
            app.update_customer(field("customer_id"), field("name"),
                                field("phone"), field("email"))
        elif path == "/api/requests":
            app.create_request(field("customer_id"), field("pickup"), field("destination"),
                               [p["description"] for p in parcel_fields(data)])
        elif path == "/api/requests/save":
            app.save_draft(field("request_id"), field("pickup"), field("destination"),
                           parcel_fields(data))
        elif path == "/api/requests/submit":
            app.submit_request(field("request_id"))
        elif path == "/api/quotes":
            app.create_quote(field("request_id"), field("cost"),
                             field("pickup_time").replace("T", " "),
                             field("delivery_time").replace("T", " "))
        elif path == "/api/quotes/decision":
            if not isinstance(data.get("accept"), bool):
                raise DomainError("Choose accept or reject.")
            app.decide_quote(field("quote_id"), data["accept"])
        elif path.startswith('/api/delivery/'):
            if not self.server.delivery_repository:
                raise DomainError('Start the integrated workspace to use delivery operations.')
            ops = DeliveryOperations(self.server.delivery_repository, app)
            action = path.removeprefix('/api/delivery/')
            if action == 'staff':
                ops.create_staff(field('name'), field('phone'))
            elif action == 'availability':
                periods = data.get('periods')
                if not isinstance(periods, list) or len(periods) > 100 or any(
                    not isinstance(x, list) or len(x) != 2 or
                    any(not isinstance(v, str) for v in x) for x in periods):
                    raise DomainError('Provide start and end pairs for availability.')
                ops.set_availability(field('staff_id'), periods)
            elif action == 'active':
                ops.set_active(field('staff_id'), data.get('active'))
            elif action == 'allocate':
                ops.allocate(field('delivery_id'), field('staff_id'), field('reason'))
            elif action == 'release':
                ops.release(field('delivery_id'), field('reason'))
            elif action == 'pickup':
                ops.pickup(field('delivery_id'))
            elif action == 'payment':
                ops.collect_payment(field('delivery_id'), field('amount'))
            elif action == 'complete':
                ops.complete(field('delivery_id'))
            else:
                raise DomainError('Unknown delivery action.')
        elif path == "/api/accounts":
            if self.server.delivery_repository and Role(field('role')) == Role.DELIVERY:
                DeliveryOperations(self.server.delivery_repository, app).validate_staff(field('staff_id'))
            app.register_staff_account(field("username"), field("password"),
                                       Role(field("role")), field("staff_id") or None)
        elif path == "/api/accounts/deactivate":
            app.deactivate_account(field("account_id"))
        else:
            raise DomainError("Unknown action.")


def main() -> int:
    parser = argparse.ArgumentParser(description="Your Order We Deliver graphical workspace")
    root = Path(__file__).resolve().parents[1]
    if root.is_file():
        root = root.parent
    parser.add_argument("--data", type=Path, default=root / "data" / "records.json")
    parser.add_argument("--port", type=int, default=8787)
    parser.add_argument("--no-browser", action="store_true")
    args = parser.parse_args()
    try:
        repository = JsonRepository(args.data)
        gateway = MeknoGateway(DeliveryRepository(args.data.with_suffix('.delivery.sqlite3')))
        try:
            server = DeliveryWebServer(("127.0.0.1", args.port), repository, gateway)
        except OSError:
            # Reopening the desktop launcher should reuse its running server.
            url = f"http://127.0.0.1:{args.port}"
            try:
                with urlopen(url + "/api/health", timeout=2) as response:
                    health = json.load(response)
                identity = hashlib.sha256(str(args.data.resolve()).casefold().encode()).hexdigest()
                if health != {"application": "norin-delivery", "workspace": identity}:
                    raise ValueError("Port is being used by another workspace")
            except Exception:
                raise OSError(f"Port {args.port} is in use. Choose another --port.") from None
            if not args.no_browser:
                webbrowser.open(url)
            print(f"Existing workspace: {url}", flush=True)
            return 0
        url = f"http://127.0.0.1:{server.server_port}"
        print(f"Your Order We Deliver: {url}", flush=True)
        if not args.no_browser:
            threading.Timer(0.4, webbrowser.open, args=(url,)).start()
        try:
            server.serve_forever()
        except KeyboardInterrupt:
            pass
        finally:
            server.server_close()
        return 0
    except (StorageError, OSError) as exc:
        print(f"Unable to start: {exc}")
        return 1

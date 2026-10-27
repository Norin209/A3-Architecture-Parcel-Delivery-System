"""Compile, test and package the module using only Python's standard library."""

import compileall
import http.client
import json
import os
import platform
import queue
import subprocess
import sys
import tempfile
import threading
import zipfile
from datetime import datetime, timezone
from pathlib import Path


def verify_ui_archive(archive, folder, env):
    """Smoke-test the packaged HTTP application without browser automation."""
    process = subprocess.Popen(
        [sys.executable, str(archive), "--no-browser", "--port", "0",
         "--data", str(Path(folder) / "gui-test.json")],
        cwd=folder, env=env, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
        text=True, encoding="utf-8",
    )
    output = queue.Queue()
    threading.Thread(target=lambda: output.put(process.stdout.readline()), daemon=True).start()
    try:
        line = output.get(timeout=10)
        port = int(line.strip().rsplit(":", 1)[1])
        connection = http.client.HTTPConnection("127.0.0.1", port, timeout=10)
        connection.request("GET", "/api/bootstrap")
        response = connection.getresponse()
        cookie = response.getheader("Set-Cookie").split(";", 1)[0]
        csrf = json.loads(response.read())["csrf"]
        connection.close()
        for path in ("/", "/styles.css", "/app.js", "/favicon.svg"):
            connection = http.client.HTTPConnection("127.0.0.1", port, timeout=10)
            connection.request("GET", path)
            response = connection.getresponse()
            if response.status != 200 or not response.read():
                raise RuntimeError(f"Missing UI asset: {path}")
            connection.close()
        for path, body in [
            ("/api/setup", {"username": "manager", "password": "PackageTest123!",
                            "confirm_password": "PackageTest123!"}),
            ("/api/shutdown", {}),
        ]:
            connection = http.client.HTTPConnection("127.0.0.1", port, timeout=10)
            connection.request("POST", path, json.dumps(body), {
                "Cookie": cookie, "Content-Type": "application/json", "X-CSRF-Token": csrf,
            })
            response = connection.getresponse()
            result = response.read()
            if response.status != 200:
                raise RuntimeError(result.decode())
            connection.close()
        if process.wait(timeout=10) != 0:
            raise RuntimeError("UI archive did not exit cleanly")
    finally:
        if process.poll() is None:
            process.terminate()
            process.wait(timeout=10)
        process.stdout.close()


def main() -> None:
    root = Path(__file__).resolve().parents[1]
    evidence = root / "evidence"
    evidence.mkdir(exist_ok=True)
    env = {**os.environ, "PYTHONIOENCODING": "utf-8"}
    if not compileall.compile_dir(root / "norin_delivery", quiet=1):
        raise SystemExit("Compilation failed")
    if not compileall.compile_file(root / "run.py", quiet=1):
        raise SystemExit("Launcher compilation failed")
    if not compileall.compile_file(root / "run_ui.py", quiet=1):
        raise SystemExit("UI launcher compilation failed")
    tests = subprocess.run(
        [sys.executable, "-m", "unittest", "discover", "-s", "tests", "-v"],
        cwd=root, env=env, capture_output=True, text=True, encoding="utf-8",
        timeout=90,
    )
    header = (
        f"Verified at {datetime.now(timezone.utc).isoformat()}\n"
        f"Python {platform.python_version()} on {platform.platform()}\n"
        "compileall: PASS (Python bytecode compilation)\n"
    )
    (evidence / "verification.txt").write_text(
        header + tests.stdout + tests.stderr, encoding="utf-8",
    )
    if tests.returncode:
        raise SystemExit(tests.stdout + tests.stderr)
    demo = subprocess.run(
        [sys.executable, "scripts/demo_console.py"], cwd=root, env=env,
        capture_output=True, text=True, encoding="utf-8", timeout=30,
    )
    (evidence / "automated-console-walkthrough.txt").write_text(
        demo.stdout + demo.stderr, encoding="utf-8",
    )
    if demo.returncode:
        raise SystemExit(demo.stdout + demo.stderr)
    archive = root / "Norin-Module.pyz"
    with zipfile.ZipFile(archive, "w", zipfile.ZIP_DEFLATED) as bundle:
        bundle.writestr(
            "__main__.py",
            "from norin_delivery.console import main\nraise SystemExit(main())\n",
        )
        for source in sorted((root / "norin_delivery").rglob("*")):
            if source.suffix in (".py", ".html", ".css", ".js", ".svg"):
                bundle.write(source, source.relative_to(root).as_posix())
    ui_archive = root / "Your-Order-UI.pyz"
    with zipfile.ZipFile(ui_archive, "w", zipfile.ZIP_DEFLATED) as bundle:
        bundle.writestr("__main__.py",
                        "from norin_delivery.web import main\nraise SystemExit(main())\n")
        for source in sorted((root / "norin_delivery").rglob("*")):
            if source.suffix in (".py", ".html", ".css", ".js", ".svg"):
                bundle.write(source, source.relative_to(root).as_posix())
    with tempfile.TemporaryDirectory() as folder:
        data_path = Path(folder) / "packaged-test.json"
        command = [sys.executable, str(archive), "--data", str(data_path)]
        first = subprocess.run(
            command, cwd=folder, env=env,
            input="manager\nDemoPass123!\nDemoPass123!\n0\n",
            capture_output=True, text=True, encoding="utf-8", timeout=30,
        )
        if first.returncode or "Manager created" not in first.stdout:
            raise SystemExit(first.stdout + first.stderr)
        second = subprocess.run(
            command, cwd=folder, env=env, input="0\n",
            capture_output=True, text=True, encoding="utf-8", timeout=30,
        )
        if second.returncode or "First run:" in second.stdout:
            raise SystemExit(second.stdout + second.stderr)
        verify_ui_archive(ui_archive, folder, env)
    with (evidence / "verification.txt").open("a", encoding="utf-8") as handle:
        handle.write("\nAutomated console walkthrough: PASS\n")
        handle.write("Packaged .pyz first-run and restart smoke tests: PASS\n")
        handle.write("Packaged GUI HTTP assets, setup and shutdown smoke test: PASS\n")
        handle.write("Rendered browser review: NOT COMPLETED (computer-use URL check blocked).\n")
        handle.write("No real user data was used or modified in these checks.\n")
    separator = "-" * 70
    print(header + tests.stderr.split(separator)[-1])
    print("Console walkthrough and packaged archive startup/restart: PASS")
    print(f"Archive: {archive}")


if __name__ == "__main__":
    main()

"""Qualify the installed Garak CLI/wrapper using one synthetic loopback generation.

Run in a separate Garak environment. This is scanner compatibility evidence,
not a vulnerability assessment or dependency security qualification.
"""

import argparse
import importlib.metadata
import json
import os
import shutil
import subprocess
import sys
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

MARKER = "GARAK-CLI-FIXTURE-OUTPUT"
KEY = "synthetic-garak-fixture-key"
CHILD = """
import json, sys
from pathlib import Path
root, port = Path(sys.argv[1]), int(sys.argv[2])
from interplay.red_teaming.garak_runner import run_garak
result = run_garak(
    target_url=f"http://127.0.0.1:{port}/v1", target_model="fixture-model",
    probe_file="test.Blank", config_file=str(root / "config.json"),
    api_key_env="GARAK_FIXTURE_KEY", output_dir=str(root / "scan"), campaign_seconds=90,
)
print(json.dumps(result))
"""
NETWORK_GUARD = """
import os
import sys
from pathlib import Path
root = Path(os.environ["GARAK_FIXTURE_ROOT"])
port = int(os.environ["GARAK_FIXTURE_PORT"])
def guard(event, args):
    if event == "socket.connect":
        address = args[1]
        if not isinstance(address, tuple) or address[:2] != ("127.0.0.1", port):
            with (root / "unexpected-network.txt").open("a") as stream:
                stream.write(event + "\\n")
            raise RuntimeError("unexpected-scanner-network")
sys.addaudithook(guard)
"""


def require(condition, reason):
    if not condition:
        raise RuntimeError(reason)


def save(path, value):
    path.write_text(json.dumps(value, indent=2) + "\n")
    path.chmod(0o600)


class Handler(BaseHTTPRequestHandler):
    def log_message(self, *args):
        pass

    def do_GET(self):
        # The real OpenAICompatible generator checks URI connectivity first.
        self.send_response(200)
        self.send_header("Content-Length", "2")
        self.end_headers()
        self.wfile.write(b"{}")

    def do_POST(self):
        if (
            self.path != "/v1/chat/completions"
            or self.headers.get("Authorization") != f"Bearer {KEY}"
        ):
            self.server.errors.append("routing-or-authentication-mismatch")
            self.send_error(403)
            return
        request = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
        self.server.requests.append(request)
        body = json.dumps(
            {
                "id": "garak-fixture",
                "object": "chat.completion",
                "created": 0,
                "model": "fixture-model",
                "choices": [
                    {
                        "index": 0,
                        "finish_reason": "stop",
                        "message": {"role": "assistant", "content": MARKER},
                    }
                ],
                "usage": {"prompt_tokens": 1, "completion_tokens": 1, "total_tokens": 2},
            }
        ).encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True, help="new private directory")
    args = parser.parse_args()
    scanner = shutil.which("garak")
    if scanner is None or Path(scanner).parent != Path(sys.executable).parent:
        parser.error("run with an isolated interpreter whose bin directory contains garak on PATH")
    os.umask(0o077)
    root = args.output.resolve()
    root.mkdir(mode=0o700, parents=True, exist_ok=False)
    home = root / "home"
    home.mkdir(mode=0o700)
    guard_dir = root / "network-guard"
    guard_dir.mkdir(mode=0o700)
    (guard_dir / "sitecustomize.py").write_text(NETWORK_GUARD)
    save(
        root / "config.json",
        {
            "run": {"generations": 1, "seed": 42},
            "system": {"parallel_requests": False, "parallel_attempts": False},
            "reporting": {"confidence_interval_method": "none"},
            "plugins": {
                "generators": {"openai": {"OpenAICompatible": {"max_tokens": 16, "stop": []}}}
            },
        },
    )
    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    server.daemon_threads = True
    server.requests, server.errors = [], []
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    receipt = {
        "passed": False,
        "fixture_only": True,
        "live_model_calls": 0,
        "garak_version": importlib.metadata.version("garak"),
        "interplay_version": importlib.metadata.version("interplay-adversarial"),
    }
    try:
        env = {
            "PATH": str(Path(sys.executable).parent) + os.pathsep + os.defpath,
            "HOME": str(home),
            "XDG_CACHE_HOME": str(home / "cache"),
            "GARAK_FIXTURE_KEY": KEY,
            "HF_HUB_OFFLINE": "1",
            "TRANSFORMERS_OFFLINE": "1",
            "PYTHONPATH": str(guard_dir),
            "GARAK_FIXTURE_ROOT": str(root),
            "GARAK_FIXTURE_PORT": str(server.server_port),
        }
        result = subprocess.run(
            [sys.executable, "-c", CHILD, str(root), str(server.server_port)],
            cwd=root,
            env=env,
            capture_output=True,
            timeout=120,
        )
        (root / "console.txt").write_bytes(
            (result.stdout + result.stderr).replace(KEY.encode(), b"[REDACTED]")
        )
        require(result.returncode == 0, "wrapper-child-failed; see private console.txt")
        scanned = json.loads(result.stdout.decode().splitlines()[-1])
        save(root / "scanner-result.json", scanned)
        require(
            scanned["success"] and scanned["returncode"] == 0,
            "scanner-failed; see scanner-result.json",
        )
        report = scanned["report"]
        require(report is not None and report["status"] == "complete", "native-report-incomplete")
        require(
            report["attempt_count"] == 1 and len(report["evaluations"]) == 1, "native-report-counts"
        )
        attempt = report["attempts"][0]
        require(attempt["status"] == 2, "native-attempt-not-evaluated")
        require(
            [output["text"] for output in attempt["outputs"]] == [MARKER], "native-output-mismatch"
        )
        require(attempt["detector_results"] == {"any.AnyOutput": [1.0]}, "native-detector-mismatch")
        require(
            len(server.requests) == 1 and server.requests[0]["model"] == "fixture-model",
            "fixture-call-count-or-model",
        )
        require(
            not server.errors and not (root / "unexpected-network.txt").exists(),
            "unexpected-routing-or-network",
        )
        for path in (root / "scan").iterdir():
            if path.is_file():
                require(path.stat().st_mode & 0o777 == 0o600, "report-permissions")
                require(KEY.encode() not in path.read_bytes(), "fixture-key-in-report")
        receipt.update(
            passed=True,
            fixture_chat_calls=1,
            native_attempts=1,
            native_evaluations=1,
            native_detector="any.AnyOutput",
            scope="installed scanner/generator/report compatibility; no robustness or dependency security claim",
        )
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)
        save(root / "fixture-requests.json", server.requests)
        save(root / "receipt.json", receipt)
    print(json.dumps(receipt))


if __name__ == "__main__":
    main()

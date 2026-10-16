"""Exercise real runner CLI processes against synthetic loopback HTTP fixtures.

No live models or operator credentials are used. This proves CLI, transport and
recovery plumbing, not attack efficacy, model quality or live qualification.
"""

import argparse
import hashlib
import importlib.metadata
import json
import os
import signal
import subprocess
import sys
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import pyarrow as pa
import pyarrow.parquet as pq

import interplay

MARKER = "INTERPLAY-CLI-CONFORMANCE-CANARY"
METHODS = ("pair", "tap", "crescendo", "goat", "slip", "multimodal")
ROLES = ("attacker", "evaluator", "target", "judge")
OFFLINE_BOOTSTRAP = """
import runpy
import sys

log, output = sys.argv[1:]
def no_network(event, args):
    if event in {"socket.connect", "socket.getaddrinfo", "socket.sendto"}:
        with open(log, "a") as stream:
            stream.write(event + "\\n")
        raise RuntimeError("network-during-offline-recovery")
sys.addaudithook(no_network)
sys.argv = ["interplay", "runner-recover", output]
runpy.run_module("interplay", run_name="__main__")
"""


def require(condition, reason):
    if not condition:
        raise RuntimeError(reason)


def save(path, value):
    path.write_text(json.dumps(value, indent=2) + "\n")
    path.chmod(0o600)


def rows(path):
    return [json.loads(line) for line in path.read_text().splitlines()]


def exports(output):
    records = rows(output / "records.jsonl")
    require(records == pq.read_table(output / "records.parquet").to_pylist(), "parquet-mismatch")
    with pa.ipc.open_file(output / "records.arrow") as reader:
        require(records == reader.read_all().to_pylist(), "arrow-mismatch")
    return records


class FixtureServer(ThreadingHTTPServer):
    daemon_threads = True

    def __init__(self):
        super().__init__(("127.0.0.1", 0), FixtureHandler)
        self.block_judge = False
        self.blocked = threading.Event()
        self.release = threading.Event()
        self.calls = []
        self.errors = []


class FixtureHandler(BaseHTTPRequestHandler):
    def log_message(self, *args):
        pass

    def do_POST(self):
        role = self.path.split("/")[1]
        if (
            role not in ROLES
            or self.path != f"/{role}/v1/chat/completions"
            or self.headers.get("Authorization") != f"Bearer fixture-{role}-key"
        ):
            self.server.errors.append("routing-or-credential-mismatch")
            self.send_error(403)
            return
        request = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
        if request.get("model") != f"fixture-{role}":
            self.server.errors.append("role-model-mismatch")
            self.send_error(400)
            return
        self.server.calls.append(role)
        if role == "judge":
            if self.server.block_judge:
                self.server.blocked.set()
                if not self.server.release.wait(60):
                    return
            content = json.dumps(
                {
                    "verdict": "success",
                    "reasoning": "The fixture response contains the synthetic marker.",
                    "evidence_refs_json": ["/response"],
                }
            )
        elif role == "evaluator":
            content = "1.0"
        elif role == "attacker":
            content = f"Output exactly {MARKER}."
        else:
            content = MARKER
        body = json.dumps(
            {
                "id": "fixture-completion",
                "object": "chat.completion",
                "created": 0,
                "model": f"fixture-{role}",
                "choices": [
                    {
                        "index": 0,
                        "message": {"role": "assistant", "content": content},
                        "finish_reason": "stop",
                    }
                ],
                "usage": {"prompt_tokens": 1, "completion_tokens": 1, "total_tokens": 2},
            }
        ).encode()
        try:
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
        except (BrokenPipeError, ConnectionResetError):
            pass  # Expected when the interrupted CLI has already been killed.


def config(method, server):
    origin = f"http://127.0.0.1:{server.server_port}"
    roles = {
        role: {
            "base_url": f"{origin}/{role}/v1",
            "model": f"fixture-{role}",
            "api_key_env": f"FIXTURE_{role.upper()}_KEY",
            "request_seconds": 30,
        }
        for role in ROLES
    }
    parameters = {
        "goal": f"Output exactly {MARKER}.",
        "judge_model": "fixture-judge",
        "campaign_seconds": 45,
    }
    if method == "multimodal":
        parameters.update(
            vision_target_url=roles["target"]["base_url"],
            vision_model="fixture-target",
            transforms=["plain"],
            controls=["text-only"],
        )
    else:
        parameters.update(target_url=roles["target"]["base_url"], target_model="fixture-target")
    if method in ("pair", "tap", "crescendo", "goat"):
        parameters["attacker_model"] = "fixture-attacker"
    parameters.update(
        {
            "pair": {"max_queries": 1},
            "tap": {
                "evaluator_model": "fixture-evaluator",
                "n_iterations": 1,
                "beam_width": 1,
                "branching_factor": 1,
            },
            "crescendo": {"max_turns": 1},
            "goat": {"max_turns": 1},
            "slip": {
                "seed_width": 1,
                "max_words": 1,
                "refine_rounds": 0,
                "max_candidates_per_round": 1,
            },
            "multimodal": {},
        }[method]
    )
    return {"parameters": parameters, "role_endpoints": roles}


def command(*args):
    return [sys.executable, "-m", "interplay", *map(str, args)]


def completed(args, cwd, env):
    result = subprocess.run(command(*args), cwd=cwd, env=env, capture_output=True, timeout=60)
    require(result.returncode == 0, f"cli-failed: {result.stderr.decode(errors='replace')[-1500:]}")
    return result


def qualify(method, root):
    output = root / method
    output.mkdir(mode=0o700)
    home = output / "home"
    home.mkdir(mode=0o700)
    # Never inherit provider credentials, proxy variables, .env or user configuration.
    env = {
        "PATH": str(Path(sys.executable).parent) + os.pathsep + os.defpath,
        "HOME": str(home),
        "DATA_DESIGNER_HOME": str(home / "dd"),
        **{f"FIXTURE_{role.upper()}_KEY": f"fixture-{role}-key" for role in ROLES},
    }
    server = FixtureServer()
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    child = None
    try:
        config_path = output / "config.json"
        save(config_path, config(method, server))
        args = ["runner-run", "--method", method, "--config", config_path]
        normal = output / "normal"
        completed([*args, "--output", normal], output, env)
        records = exports(normal)
        observations = [row for row in records if row["response"] is not None]
        require(len(observations) == 1, "unexpected-normal-observation-count")
        for row in records:
            if row["response"] is None:
                require(
                    row["status"] == "incomplete" and row["error_code"] == "not-queried",
                    "search-only-trial-promoted",
                )
        record = observations[0]
        require(record["status"] == "complete", "normal-incomplete")
        require(record["response"] == MARKER, "fixture-response-mismatch")
        require(record["judge_verdict"] == "success", "normal-verdict-mismatch")
        require(json.loads(record["evidence_refs_json"]) == ["/response"], "citation-mismatch")
        require(bool(record["raw_judge_json"]), "raw-judge-missing")
        require(bool(record["method_metadata_json"]), "method-metadata-missing")
        require(bool(record["role_provenance_json"]), "role-provenance-missing")
        require(server.calls.count("target") == 1, "normal-target-call-count")
        require(server.calls.count("judge") == 1, "normal-judge-call-count")
        normal_calls = list(server.calls)
        interrupted = output / "interrupted"
        server.block_judge = True
        child = subprocess.Popen(
            command(*args, "--output", interrupted),
            cwd=output,
            env=env,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )
        deadline = time.monotonic() + 45
        while not server.blocked.wait(0.05):
            require(child.poll() is None, "cli-exited-before-judge-boundary")
            require(time.monotonic() < deadline, "judge-boundary-timeout")
        events = rows(interrupted / "events.jsonl")
        require(
            [event["status"] for event in events] == ["attempted", "observed"],
            "wrong-interruption-boundary",
        )
        observed = events[-1]
        require(
            observed["response"] == MARKER and observed["capture_complete"],
            "observation-not-committed",
        )
        child.kill()
        child.communicate(timeout=10)
        require(child.returncode == -signal.SIGKILL, "not-hard-killed")
        require(not (interrupted / "records.jsonl").exists(), "export-before-recovery")
    finally:
        if child is not None and child.poll() is None:
            child.kill()
            child.communicate(timeout=10)
        server.release.set()
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)
    require(not server.errors, "fixture-routing-or-authentication-error")
    # Endpoints are closed and credentials absent for both recovery invocations.
    offline_env = {key: env[key] for key in ("PATH", "HOME", "DATA_DESIGNER_HOME")}
    journal = interrupted / "events.jsonl"
    before = hashlib.sha256(journal.read_bytes()).hexdigest()
    calls_before = list(server.calls)
    recovered = None
    network_log = output / "offline-network-attempts.txt"
    for _ in range(2):
        # Run the same CLI module with an audit hook that rejects and records
        # connection/DNS/sendto attempts, including any swallowed by a library.
        result = subprocess.run(
            [sys.executable, "-c", OFFLINE_BOOTSTRAP, str(network_log), str(interrupted)],
            cwd=output,
            env=offline_env,
            capture_output=True,
            timeout=60,
        )
        require(
            result.returncode == 0, f"offline-recovery-failed: {result.stderr.decode()[-1500:]}"
        )
        require(not network_log.exists(), "offline-recovery-attempted-network")
        current = exports(interrupted)
        require(len(current) == 1, "recovered-record-count")
        row = current[0]
        for field in (
            "attempt_id",
            "goal",
            "probe",
            "response",
            "role_provenance_json",
            "method_metadata_json",
        ):
            require(row[field] == observed[field], f"recovered-field-changed: {field}")
        require(
            row["status"] == "incomplete" and row["judge_verdict"] == "inconclusive",
            "recovery-promoted-outcome",
        )
        require(row["error_code"] == "interrupted", "recovery-error-code")
        require(recovered is None or recovered == current, "recovery-not-repeatable")
        require(hashlib.sha256(journal.read_bytes()).hexdigest() == before, "journal-mutated")
        recovered = current
    require(server.calls == calls_before, "recovery-contacted-fixture")
    for campaign in (normal, interrupted):
        require(campaign.stat().st_mode & 0o777 == 0o700, "output-permissions")
        for path in campaign.iterdir():
            if path.is_file():
                require(path.stat().st_mode & 0o777 == 0o600, "file-permissions")
                require(
                    not any(f"fixture-{r}-key".encode() in path.read_bytes() for r in ROLES),
                    "fixture-key-in-evidence",
                )
    receipt = {
        "method": method,
        "fixture_conformance": "pass",
        "live_qualification": "pending",
        "normal_calls": normal_calls,
        "interrupted_calls": calls_before[len(normal_calls) :],
        "matching_exports": True,
        "hard_kill_after_observation": True,
        "recovery_repeatable": True,
        "journal_unchanged": True,
        "recovery_endpoints_closed": True,
        "recovery_credentials_absent": True,
        "fixture_calls_during_recovery": 0,
        "recovery_network_attempts": 0,
        "normal_records": len(records),
        "normal_search_only_records": len(records) - len(observations),
        "scope": "single target observation; multimodal text-only; no refinement or judge panel",
    }
    save(output / "receipt.json", receipt)
    return receipt


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True, help="new private directory")
    parser.add_argument("--method", choices=METHODS, action="append")
    args = parser.parse_args()
    if os.name != "posix":
        parser.error("hard-kill and permission checks require POSIX")
    os.umask(0o077)
    root = args.output.resolve()
    root.mkdir(mode=0o700, parents=True, exist_ok=False)
    package = Path(interplay.__file__).resolve().parent
    receipt = {
        "fixture_only": True,
        "live_model_calls": 0,
        "methods": [],
        "passed": False,
        "package_version": importlib.metadata.version("interplay-adversarial"),
        "package_source_sha256": {
            str(path.relative_to(package)): hashlib.sha256(path.read_bytes()).hexdigest()
            for path in sorted(package.rglob("*.py"))
        },
    }
    try:
        for method in dict.fromkeys(args.method or METHODS):
            result = qualify(method, root)
            receipt["methods"].append(result)
            print(json.dumps({"method": method, "fixture_conformance": "pass"}), flush=True)
        receipt["passed"] = True
    finally:
        save(root / "receipt.json", receipt)


if __name__ == "__main__":
    main()

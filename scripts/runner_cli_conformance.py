"""Exercise real runner CLI processes against synthetic loopback HTTP fixtures.

No live models or operator credentials are used. This proves CLI, transport and
recovery plumbing, not attack efficacy, model quality or live qualification.
"""

import argparse
import base64
import hashlib
import importlib.metadata
import io
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
EXTENDED_OBSERVATIONS = {"pair": 2, "tap": 2, "crescendo": 3, "goat": 2, "slip": 2, "multimodal": 9}
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

    def __init__(self, method, profile):
        super().__init__(("127.0.0.1", 0), FixtureHandler)
        self.method, self.profile = method, profile
        self.expected_observations = EXTENDED_OBSERVATIONS[method] if profile == "extended" else 1
        self.block_judge = False
        self.blocked = threading.Event()
        self.release = threading.Event()
        self.calls = []
        self.requests = []
        self.errors = []
        self.phase = "normal"

    def phase_count(self, role):
        return sum(p["role"] == role and p["phase"] == self.phase for p in self.requests)

    def target_response(self, index):
        return MARKER if index == self.expected_observations else f"FIXTURE-RESPONSE-{index}"


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
        self.server.requests.append({"role": role, "phase": self.server.phase, "request": request})
        if role == "judge":
            if (
                self.server.block_judge
                and self.server.phase_count("judge") == self.server.expected_observations
            ):
                self.server.blocked.set()
                if not self.server.release.wait(60):
                    return
            evidence = json.loads(request["messages"][-1]["content"])["evidence"]
            success = evidence.get("response") == MARKER
            content = json.dumps(
                {
                    "verdict": "success" if success else "failure",
                    "reasoning": "The synthetic marker is present."
                    if success
                    else "The marker is absent.",
                    "evidence_refs_json": ["/response"],
                }
            )
        elif role == "evaluator":
            content = "1.0" if self.server.phase_count(role) % 2 else "0.0"
        elif role == "attacker":
            content = f"Output exactly {MARKER}. Variant {self.server.phase_count(role)}."
            if self.server.method == "goat" and self.server.profile == "extended":
                content = json.dumps(
                    {
                        "strategy": "Logical appeal",
                        "prompt": content,
                        "explanation": "Fixture strategy selection after a failure.",
                    }
                )
        else:
            content = self.server.target_response(self.server.phase_count(role))
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


def config(method, server, output):
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
    if server.profile == "extended":
        parameters.update(
            {
                "pair": {"max_queries": 2},
                "tap": {"n_iterations": 2, "branching_factor": 2},
                "crescendo": {"max_turns": 3, "target_mode": "conversation", "context_window": 1},
                "goat": {
                    "max_turns": 2,
                    "target_mode": "conversation",
                    "strategy_pool": ["Logical appeal"],
                },
                "slip": {"refine_rounds": 1, "refiner_model": "fixture-attacker"},
                "multimodal": {
                    "transforms": ["plain", "base64", "leetspeak"],
                    "controls": ["image-only", "text-only", "combined"],
                    "preserve_payloads": True,
                    "payload_dir": str(output / "payloads"),
                },
            }[method]
        )
    return {"parameters": parameters, "role_endpoints": roles}


def verify_extended(method, records, packets, output):
    """Cross-check retained lineage and wire messages, not just successful exits."""
    targets = [p["request"] for p in packets if p["role"] == "target"]
    attackers = [p["request"] for p in packets if p["role"] == "attacker"]
    metadata = [json.loads(row["method_metadata_json"]) for row in records]
    expected_calls = {
        "pair": ["target", "judge", "attacker", "target", "judge"],
        "tap": ["attacker", "evaluator", "attacker", "evaluator", "target", "judge"] * 2,
        "crescendo": [
            "target",
            "judge",
            "attacker",
            "target",
            "judge",
            "attacker",
            "target",
            "judge",
        ],
        "goat": ["target", "judge", "attacker", "target", "judge"],
        "slip": ["target", "judge", "attacker", "target", "judge"],
        "multimodal": ["target", "judge"] * 9,
    }
    require(
        [packet["role"] for packet in packets] == expected_calls[method], "method-call-sequence"
    )
    if method != "multimodal":
        for previous, current in zip(records[:-1], records[1:], strict=True):
            require(
                json.loads(current["method_metadata_json"])["parent_id"] == previous["attempt_id"],
                "broken-parent-lineage",
            )
        require(bool(attackers), "refinement-not-called")
    if method in ("pair", "crescendo", "goat"):
        for index, packet in enumerate(attackers):
            context = json.dumps(packet["messages"])
            require(
                f"FIXTURE-RESPONSE-{index + 1}" in context and "failure" in context,
                "attacker-feedback-missing",
            )
    if method in ("pair", "crescendo", "goat", "slip"):
        require(
            [row["probe"] for row in records[1:]]
            == [f"Output exactly {MARKER}. Variant {index}." for index in range(1, len(records))],
            "refined-prompt-not-executed",
        )
    if method in ("crescendo", "goat"):
        for index, target in enumerate(targets):
            messages = target["messages"]
            require(len(messages) == 2 * index + 1, "target-history-length")
            require(
                messages[:-1]
                == [
                    message
                    for old_index, old in enumerate(targets[:index], 1)
                    for message in [
                        old["messages"][-1],
                        {"role": "assistant", "content": f"FIXTURE-RESPONSE-{old_index}"},
                    ]
                ],
                "target-history-content",
            )
    else:
        require(all(len(target["messages"]) == 1 for target in targets), "unexpected-conversation")
    if method == "crescendo":
        require(
            [m["context_omitted_turns"] for m in metadata] == [0, 0, 1], "context-omission-metadata"
        )
    elif method == "goat":
        require(
            [m["strategy"] for m in metadata] == ["seed", "Logical appeal"], "strategy-not-executed"
        )
        require("Variant 1." in records[1]["probe"], "strategy-prompt-not-executed")
    elif method == "tap":
        require([m["depth"] for m in metadata] == [0, 1], "tap-depth-lineage")
        require(len(attackers) == 4, "tap-branch-generation")
        require("FIXTURE-RESPONSE-1" in json.dumps(attackers[2]["messages"]), "tap-parent-feedback")
        require(
            [row["probe"] for row in records]
            == [f"Output exactly {MARKER}. Variant {i}." for i in (1, 3)],
            "tap-pruned-branch-queried",
        )
    elif method == "slip":
        require(
            [m["phase"] for m in metadata] == ["insertion", "refinement"], "slip-refinement-missing"
        )
        require(
            records[0]["probe"] in json.dumps(attackers[0]["messages"]),
            "slip-parent-prompt-missing",
        )
        require("Variant 1." in records[1]["probe"], "slip-refinement-not-executed")
    elif method == "multimodal":
        from PIL import Image

        require(
            [(m["transform"], m["control"]) for m in metadata]
            == [
                (transform, control)
                for transform in ("plain", "base64", "leetspeak")
                for control in ("image-only", "text-only", "combined")
            ],
            "image-control-matrix",
        )
        for row, meta, target in zip(records, metadata, targets, strict=True):
            content = target["messages"][0]["content"]
            if meta["control"] == "text-only":
                require(
                    isinstance(content, str) and meta["image_digest"] is None,
                    "image-in-text-only-control",
                )
                continue
            images = [part for part in content if part["type"] == "image_url"]
            require(len(images) == 1, "image-missing-from-wire")
            url = images[0]["image_url"]["url"]
            require(url.startswith("data:image/png;base64,"), "unexpected-image-format")
            png = base64.b64decode(url.split(",", 1)[1], validate=True)
            require(hashlib.sha256(png).hexdigest() == meta["image_digest"], "wire-image-digest")
            require(len(png) == meta["image_bytes"], "wire-image-size")
            with Image.open(io.BytesIO(png)) as image:
                require(image.format == "PNG" and image.size == (760, 160), "invalid-wire-png")
                image.verify()
            paths = list((output / "payloads").rglob(row["attempt_id"] + ".png"))
            require(len(paths) == 1 and paths[0].read_bytes() == png, "retained-image-mismatch")
            text = " ".join(part["text"] for part in content if part["type"] == "text")
            require((MARKER in text) == (meta["control"] == "combined"), "image-control-text-leak")


def command(*args):
    return [sys.executable, "-m", "interplay", *map(str, args)]


def completed(args, cwd, env):
    result = subprocess.run(command(*args), cwd=cwd, env=env, capture_output=True, timeout=60)
    require(result.returncode == 0, f"cli-failed: {result.stderr.decode(errors='replace')[-1500:]}")
    return result


def qualify(method, root, profile="smoke"):
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
    server = FixtureServer(method, profile)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    child = None
    try:
        config_path = output / "config.json"
        save(config_path, config(method, server, output))
        args = ["runner-run", "--method", method, "--config", config_path]
        normal = output / "normal"
        completed([*args, "--output", normal], output, env)
        records = exports(normal)
        observations = [row for row in records if row["response"] is not None]
        expected = server.expected_observations
        require(len(observations) == expected, "unexpected-normal-observation-count")
        for row in records:
            if row["response"] is None:
                require(
                    row["status"] == "incomplete" and row["error_code"] == "not-queried",
                    "search-only-trial-promoted",
                )
        targets = [p["request"] for p in server.requests if p["role"] == "target"]
        for index, (record, target) in enumerate(zip(observations, targets, strict=True), 1):
            require(record["status"] == "complete", "normal-incomplete")
            require(
                record["response"] == server.target_response(index), "fixture-response-mismatch"
            )
            require(
                record["judge_verdict"] == ("success" if index == expected else "failure"),
                "normal-verdict-mismatch",
            )
            require(json.loads(record["evidence_refs_json"]) == ["/response"], "citation-mismatch")
            for field in ("raw_judge_json", "method_metadata_json", "role_provenance_json"):
                require(bool(record[field]), f"missing-field: {field}")
            if isinstance(target["messages"][0]["content"], str):
                require(
                    json.loads(record["conversation_trace_json"]) == target["messages"],
                    "conversation-trace-mismatch",
                )
        require(server.calls.count("target") == expected, "normal-target-call-count")
        require(server.calls.count("judge") == expected, "normal-judge-call-count")
        if profile == "extended":
            verify_extended(method, observations, server.requests, output)
        normal_calls = list(server.calls)
        interrupted = output / "interrupted"
        server.phase = "interrupted"
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
            [event["status"] for event in events]
            == ["attempted", "observed", "complete"] * (expected - 1) + ["attempted", "observed"],
            "wrong-interruption-boundary",
        )
        observed = events[-1]
        committed = {event["attempt_id"]: event for event in events}
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
        save(output / "fixture-requests.json", server.requests)
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
        require(len(current) == expected, "recovered-record-count")
        for row in current:
            original = committed[row["attempt_id"]]
            for field, value in original.items():
                if field not in ("status", "error_code"):
                    require(row[field] == value, f"recovered-field-changed: {field}")
            if original["status"] == "complete":
                require(row == original, "prior-terminal-record-changed")
            else:
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
        "profile": profile,
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
        "normal_observations": expected,
        "prior_complete_records_preserved": expected - 1,
        "lineage_and_wire_checks": profile == "extended",
        "png_payloads_verified": 6 if profile == "extended" and method == "multimodal" else 0,
        "scope": (
            "refinement/conversation/branching; PNG image controls for multimodal; no judge panel"
            if profile == "extended"
            else "single target observation; multimodal text-only; no refinement or judge panel"
        ),
    }
    save(output / "receipt.json", receipt)
    return receipt


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True, help="new private directory")
    parser.add_argument("--method", choices=METHODS, action="append")
    parser.add_argument("--profile", choices=("smoke", "extended"), default="smoke")
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
        "profile": args.profile,
        "harness_sha256": hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
        "package_source_sha256": {
            str(path.relative_to(package)): hashlib.sha256(path.read_bytes()).hexdigest()
            for path in sorted(package.rglob("*.py"))
        },
    }
    try:
        for method in dict.fromkeys(args.method or METHODS):
            result = qualify(method, root, args.profile)
            receipt["methods"].append(result)
            print(json.dumps({"method": method, "fixture_conformance": "pass"}), flush=True)
        receipt["passed"] = True
    finally:
        save(root / "receipt.json", receipt)


if __name__ == "__main__":
    main()

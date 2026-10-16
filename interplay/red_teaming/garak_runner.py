"""Supervised Garak CLI with explicit endpoint routing and native JSONL parsing.

Contract: https://reference.garak.ai/en/stable/cliref.html and reporting.html.
Garak owns its generator retries and detectors; their verdicts are not Interplay
JudgeOutput judgments or evidence of independently verified boundary effects.
"""

import contextlib
import json
import os
import re
import signal
import subprocess
import tempfile
import time
from pathlib import Path

from ..assessment.models import ModelEndpoint
from ..assessment.runner import redact


def run_garak(
    target_url: str,
    probe_file: str,
    config_file: str | None = None,
    output_dir: str | None = None,
    *,
    target_model: str = "target-model",
    api_key_env: str = "OPENAICOMPATIBLE_API_KEY",
    api_key: str | None = None,
    campaign_seconds: int = 600,
) -> dict:
    """Run a Garak probe selector (``probe_file`` is a legacy parameter name).

    ``probe_file`` is a comma-separated Garak plugin selector, e.g. ``test.Test``;
    arbitrary JSONL probe files are not supported by Garak's --probes option.
    A private output directory is created, never reused. Scanner exit success
    describes execution only. Native detector assessments stay in ``report``.
    """
    endpoint = ModelEndpoint(base_url=target_url, model=target_model)
    if not re.fullmatch(r"[A-Za-z0-9_.,]+", probe_file) or probe_file.lower().endswith(
        (".json", ".jsonl", ".yaml")
    ):
        raise ValueError("garak-probe-selector-invalid")
    if not re.fullmatch(r"[A-Z][A-Z0-9_]{0,80}", api_key_env):
        raise ValueError("garak-key-env-invalid")
    if type(campaign_seconds) is not int or not 1 <= campaign_seconds <= 3600:
        raise ValueError("garak-campaign-seconds-invalid")
    if output_dir is None:
        root = Path(tempfile.mkdtemp(prefix="interplay-garak-"))
    else:
        root = Path(output_dir).absolute()
        root.mkdir(mode=0o700, parents=True, exist_ok=False)
    root.chmod(0o700)
    prefix = root / "scan"
    cmd = [
        "garak",
        "--model_type",
        "openai.OpenAICompatible",
        "--model_name",
        target_model,
        "--generator_options",
        json.dumps({"openai": {"OpenAICompatible": {"uri": endpoint.base_url}}}),
        "--report_prefix",
        str(prefix),
        "--probes",
        probe_file,
    ]
    if config_file:
        cmd.extend(["--config", str(Path(config_file).absolute())])
    env = dict(os.environ)
    key = api_key if api_key is not None else env.get(api_key_env)
    if not key:
        raise ValueError("garak-api-key-missing")
    env["OPENAICOMPATIBLE_API_KEY"] = key
    error = None
    interrupted = None
    with tempfile.TemporaryFile(dir=root) as stdout, tempfile.TemporaryFile(dir=root) as stderr:
        try:
            process = subprocess.Popen(
                cmd, stdout=stdout, stderr=stderr, env=env, start_new_session=True, cwd=root
            )
        except FileNotFoundError as exc:
            raise RuntimeError(
                "Install scanner in an isolated environment: pip install 'interplay-adversarial[red-teaming,garak]'"
            ) from exc
        deadline = time.monotonic() + campaign_seconds
        try:
            while process.poll() is None:
                if time.monotonic() >= deadline:
                    error = "garak-deadline"
                    break
                if (
                    os.fstat(stdout.fileno()).st_size + os.fstat(stderr.fileno()).st_size
                    > 8 * 1024 * 1024
                ):
                    error = "garak-output-limit"
                    break
                if (
                    sum(
                        p.stat().st_size
                        for p in root.iterdir()
                        if p.is_file() and not p.is_symlink()
                    )
                    > 64 * 1024 * 1024
                ):
                    error = "garak-report-limit"
                    break
                time.sleep(0.05)
        except BaseException as exc:
            interrupted = exc
        finally:
            # A scanner may spawn workers; terminate the process group, including
            # workers left behind after the leader exits. Never retry the scan.
            with contextlib.suppress(ProcessLookupError):
                os.killpg(process.pid, signal.SIGKILL)
            process.wait()
        if os.fstat(stdout.fileno()).st_size + os.fstat(stderr.fileno()).st_size > 8 * 1024 * 1024:
            error = error or "garak-output-limit"
        stdout.seek(0)
        stderr.seek(0)
        out = redact(stdout.read(1024 * 1024).decode(errors="replace"), (key,))
        err = redact(stderr.read(1024 * 1024).decode(errors="replace"), (key,))
    report_path = prefix.with_suffix(".report.jsonl")
    report = None
    # Sanitize even interrupted scans and scans with no final report. Only
    # files generated inside this new private run directory are touched.
    variants = {
        key.encode(),
        json.dumps(key)[1:-1].encode(),
        json.dumps(key, ensure_ascii=False)[1:-1].encode(),
    }
    for path in root.iterdir():
        if path.is_file() and not path.is_symlink():
            path.chmod(0o600)
            if path.stat().st_size > 64 * 1024 * 1024:
                error = error or "garak-report-limit"
                path.unlink()  # oversized untrusted capture cannot be safely retained
                continue
            raw = path.read_bytes()
            for variant in sorted(variants, key=len, reverse=True):
                raw = raw.replace(variant, b"[REDACTED]")
            path.write_bytes(raw)
    if report_path.exists():
        report = parse_garak_results(str(report_path))
    if interrupted is not None:
        raise interrupted
    return {
        "success": process.returncode == 0 and error is None,
        "stdout": out,
        "stderr": err,
        "returncode": process.returncode,
        "error_code": error,
        "output_dir": str(root),
        "report": report,
    }


def create_custom_config(target_url: str, output_path: str) -> str:
    """Write a private Garak run config for the OpenAICompatible generator.

    Credentials come from OPENAICOMPATIBLE_API_KEY, never this file.
    """
    endpoint = ModelEndpoint(base_url=target_url, model="target-model")
    config = {
        "plugins": {"generators": {"openai": {"OpenAICompatible": {"uri": endpoint.base_url}}}}
    }
    path = Path(output_path)
    with open(path, "x", opener=lambda p, flags: os.open(p, flags, 0o600)) as stream:
        json.dump(config, stream, indent=2)
    return str(path)


def parse_garak_results(report_file: str) -> dict:
    """Read native JSONL stages, keeping latest attempts and all detector summaries.

    A valid final JSON object needs no trailing newline (Garak's native digest
    uses this form). An incomplete final line is reported and ignored. Malformed committed lines,
    regressed attempt stages and unsupported attempt statuses fail explicitly.
    No HTML scraping, keyword verdicts or assumed detector pass thresholds.
    """
    path = Path(report_file)
    if path.stat().st_size > 64 * 1024 * 1024:
        raise ValueError("garak-report-limit")
    raw = path.read_bytes()
    lines = raw.splitlines()
    truncated = False
    if raw and not raw.endswith(b"\n"):
        try:
            json.loads(lines[-1])
        except (json.JSONDecodeError, UnicodeDecodeError):
            truncated = True
            lines = lines[:-1]
    attempts, evaluations = {}, []
    completed = False
    for line in lines:
        entry = json.loads(line)
        if not isinstance(entry, dict):
            raise ValueError("garak-report-entry-invalid")
        if entry.get("entry_type") == "attempt":
            identity, status = entry.get("uuid"), entry.get("status")
            if (
                not isinstance(identity, str)
                or not identity
                or type(status) is not int
                or status not in (0, 1, 2)
            ):
                raise ValueError("garak-attempt-invalid")
            if identity in attempts and status < attempts[identity]["status"]:
                raise ValueError("garak-attempt-regressed")
            attempts[identity] = entry
        elif entry.get("entry_type") == "eval":
            evaluations.append(entry)
        elif entry.get("entry_type") == "completion":
            completed = True
    return {
        "report_file": str(path),
        "status": "complete" if completed and not truncated else "incomplete",
        "truncated_tail": truncated,
        "attempts": list(attempts.values()),
        "evaluations": evaluations,
        "attempt_count": len(attempts),
    }

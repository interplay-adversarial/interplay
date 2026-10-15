"""Garak wrapper contract with a fake CLI; never contacts a hosted model."""

import json
import os
import sys
from pathlib import Path

import pytest

from interplay.red_teaming.garak_runner import parse_garak_results, run_garak


def scanner(tmp_path, monkeypatch, source):
    executable = tmp_path / "garak"
    executable.write_text(f"#!{sys.executable}\n" + source)
    executable.chmod(0o700)
    monkeypatch.setenv("PATH", str(tmp_path) + os.pathsep + os.environ["PATH"])
    monkeypatch.setenv("SCANNER_FIXTURE_KEY", "synthetic-scanner-secret")


def test_routes_endpoint_model_and_output_and_parses_native_report(tmp_path, monkeypatch):
    scanner(
        tmp_path,
        monkeypatch,
        """
import json, os, pathlib, sys
args = sys.argv[1:]
assert args[args.index("--model_type")+1] == "openai.OpenAICompatible"
assert args[args.index("--model_name")+1] == "fixture-target"
options = json.loads(args[args.index("--generator_options")+1])
assert options["openai"]["OpenAICompatible"]["uri"] == "https://target.example/v1"
assert "synthetic-scanner-secret" not in " ".join(args)
assert args[args.index("--probes")+1] == "test.Test"
prefix = args[args.index("--report_prefix")+1]
key = os.environ["OPENAICOMPATIBLE_API_KEY"]
rows = [
 {"entry_type":"attempt", "uuid":"fixture", "status":0, "prompt":"probe"},
 {"entry_type":"attempt", "uuid":"fixture", "status":2, "prompt":"probe", "outputs":[key], "detector_results":{"fixture":[1.0]}},
 {"entry_type":"eval", "probe":"test.Test", "detector":"fixture", "passed":0, "total":1},
 {"entry_type":"completion"}]
pathlib.Path(prefix + ".report.jsonl").write_text("".join(json.dumps(r)+"\\n" for r in rows))
print(key)
""",
    )
    result = run_garak(
        "https://target.example/v1",
        "test.Test",
        output_dir=str(tmp_path / "output"),
        target_model="fixture-target",
        api_key_env="SCANNER_FIXTURE_KEY",
    )
    assert result["success"] and result["report"]["status"] == "complete"
    assert result["report"]["attempt_count"] == 1
    assert result["report"]["attempts"][0]["outputs"] == ["[REDACTED]"]
    assert result["report"]["evaluations"][0]["passed"] == 0
    assert "synthetic-scanner-secret" not in json.dumps(result)
    assert (Path(result["output_dir"]).stat().st_mode & 0o777) == 0o700
    assert all((p.stat().st_mode & 0o777) == 0o600 for p in Path(result["output_dir"]).iterdir())


def test_deadline_stops_scanner_without_retry(tmp_path, monkeypatch):
    scanner(tmp_path, monkeypatch, "import time\ntime.sleep(10)\n")
    result = run_garak(
        "https://target.example/v1",
        "test.Test",
        output_dir=str(tmp_path / "output"),
        api_key_env="SCANNER_FIXTURE_KEY",
        campaign_seconds=1,
    )
    assert not result["success"] and result["error_code"] == "garak-deadline"
    assert result["returncode"] != 0


def test_nonzero_exit_is_execution_failure(tmp_path, monkeypatch):
    scanner(tmp_path, monkeypatch, "import sys\nsys.exit(3)\n")
    result = run_garak(
        "https://target.example/v1",
        "test.Test",
        output_dir=str(tmp_path / "output"),
        api_key_env="SCANNER_FIXTURE_KEY",
    )
    assert not result["success"] and result["returncode"] == 3


def test_truncated_native_report_is_explicitly_incomplete(tmp_path):
    path = tmp_path / "report.jsonl"
    path.write_text(
        '{"entry_type":"attempt","uuid":"a","status":1,"outputs":["captured"]}\n{"partial"'
    )
    result = parse_garak_results(str(path))
    assert result["truncated_tail"] and result["status"] == "incomplete"
    assert result["attempts"][0]["outputs"] == ["captured"]


def test_malformed_committed_report_is_rejected(tmp_path):
    path = tmp_path / "report.jsonl"
    path.write_text("{not-json}\n")
    with pytest.raises(ValueError):
        parse_garak_results(str(path))


def test_arbitrary_probe_files_are_not_misrepresented_as_supported(tmp_path):
    with pytest.raises(ValueError, match="selector-invalid"):
        run_garak("https://target.example/v1", str(tmp_path / "probes.jsonl"))

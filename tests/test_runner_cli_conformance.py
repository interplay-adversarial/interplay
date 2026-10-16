"""The offline verifier must notice network attempts swallowed by a CLI dependency."""

import copy
import json
import os
import runpy
import subprocess
import sys
from pathlib import Path

import pytest

CONFORMANCE = runpy.run_path(
    str(Path(__file__).resolve().parents[1] / "scripts/runner_cli_conformance.py")
)
BOOTSTRAP = CONFORMANCE["OFFLINE_BOOTSTRAP"]


@pytest.mark.parametrize(
    "operation,event",
    [
        ('socket.socket().connect(("127.0.0.1", 9))', "socket.connect"),
        ('socket.getaddrinfo("localhost", 9)', "socket.getaddrinfo"),
        (
            'socket.socket(type=socket.SOCK_DGRAM).sendto(b"fixture", ("127.0.0.1", 9))',
            "socket.sendto",
        ),
    ],
)
def test_offline_guard_records_swallowed_network_attempts(tmp_path, operation, event):
    # Substitute a CLI that attempts network access and deliberately hides the
    # failure. The verifier must detect the attempt even with a zero exit code.
    (tmp_path / "interplay.py").write_text(
        f"import socket\ntry:\n    {operation}\nexcept RuntimeError:\n    pass\n"
    )
    log = tmp_path / "network-attempts.txt"
    result = subprocess.run(
        [sys.executable, "-c", BOOTSTRAP, str(log), str(tmp_path / "unused-output")],
        cwd=tmp_path,
        env={"PATH": os.defpath},
        capture_output=True,
        timeout=10,
    )
    assert result.returncode == 0, result.stderr.decode()
    assert log.read_text().splitlines() == [event]


@pytest.mark.parametrize(
    "corruption,reason",
    [
        ("parent", "broken-parent-lineage"),
        ("feedback", "attacker-feedback-missing"),
        ("history", "target-history-content"),
        ("strategy", "strategy-not-executed"),
    ],
)
def test_extended_verifier_rejects_corrupted_lineage_feedback_and_history(
    tmp_path, corruption, reason
):
    first = {"role": "user", "content": "fixture-goal"}
    reply = {"role": "assistant", "content": "FIXTURE-RESPONSE-1"}
    second = {"role": "user", "content": f"Output exactly {CONFORMANCE['MARKER']}. Variant 1."}
    records = [
        {
            "attempt_id": "first",
            "probe": first["content"],
            "method_metadata_json": json.dumps({"parent_id": None, "strategy": "seed"}),
        },
        {
            "attempt_id": "second",
            "probe": second["content"],
            "method_metadata_json": json.dumps(
                {"parent_id": "first", "strategy": "Logical appeal"}
            ),
        },
    ]
    packets = [
        {"role": "target", "request": {"messages": [first]}},
        {"role": "judge", "request": {}},
        {
            "role": "attacker",
            "request": {
                "messages": [
                    {"role": "system", "content": "Previous FIXTURE-RESPONSE-1; verdict failure."}
                ]
            },
        },
        {"role": "target", "request": {"messages": [first, reply, second]}},
        {"role": "judge", "request": {}},
    ]
    verify = CONFORMANCE["verify_extended"]
    verify("goat", records, packets, tmp_path)
    packets = copy.deepcopy(packets)
    if corruption == "parent":
        records[1]["method_metadata_json"] = json.dumps(
            {"parent_id": "unrelated", "strategy": "Logical appeal"}
        )
    elif corruption == "feedback":
        packets[2]["request"]["messages"][0]["content"] = "No captured outcome."
    elif corruption == "history":
        packets[3]["request"]["messages"][1]["content"] = "A fabricated prior response."
    else:
        records[1]["method_metadata_json"] = json.dumps(
            {"parent_id": "first", "strategy": "not-executed"}
        )
    with pytest.raises(RuntimeError, match=reason):
        verify("goat", records, packets, tmp_path)

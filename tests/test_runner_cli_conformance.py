"""The offline verifier must notice network attempts swallowed by a CLI dependency."""

import os
import runpy
import subprocess
import sys
from pathlib import Path

import pytest

BOOTSTRAP = runpy.run_path(
    str(Path(__file__).resolve().parents[1] / "scripts/runner_cli_conformance.py")
)["OFFLINE_BOOTSTRAP"]


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

"""The real scanner is a subprocess; its network guard must survive exec."""

import os
import runpy
import subprocess
import sys
from pathlib import Path

import pytest

GUARD = runpy.run_path(
    str(Path(__file__).resolve().parents[1] / "scripts/garak_cli_conformance.py")
)["NETWORK_GUARD"]


@pytest.mark.parametrize(
    "operation,event",
    [
        ('socket.socket().connect(("127.0.0.1", 9))', "socket.connect"),
        ('socket.getaddrinfo("example.com", 9)', "socket.getaddrinfo"),
        (
            'socket.socket(type=socket.SOCK_DGRAM).sendto(b"fixture", ("127.0.0.1", 9))',
            "socket.sendto",
        ),
    ],
)
def test_network_guard_is_inherited_by_grandchild_and_records_swallowed_attempt(
    tmp_path, operation, event
):
    guard = tmp_path / "guard"
    guard.mkdir()
    (guard / "sitecustomize.py").write_text(GUARD)
    # The grandchild hides the error and exits successfully, as a third-party
    # scanner might. Its audit record must still make conformance fail.
    operation = f"import socket\ntry:\n {operation}\nexcept RuntimeError:\n pass\n"
    child = "import subprocess,sys; subprocess.run([sys.executable, '-c', sys.argv[1]], check=True)"
    result = subprocess.run(
        [sys.executable, "-c", child, operation],
        cwd=tmp_path,
        env={
            "PATH": os.defpath,
            "PYTHONPATH": str(guard),
            "GARAK_FIXTURE_ROOT": str(tmp_path),
            "GARAK_FIXTURE_PORT": "1",
        },
        capture_output=True,
        timeout=10,
    )
    assert result.returncode == 0, result.stderr.decode()
    assert (tmp_path / "unexpected-network.txt").read_text().splitlines() == [event]

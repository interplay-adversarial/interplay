"""End-to-end: setup -> create against a local fake OpenAI endpoint (no model, no key, isolated config)."""

import subprocess
import sys
import threading
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent / "scripts"))
import mock_openai  # noqa: E402

from interplay import cli  # noqa: E402


@pytest.fixture
def endpoint():
    server = mock_openai.serve(0)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    yield f"http://127.0.0.1:{server.server_address[1]}/v1"
    server.shutdown()


@pytest.mark.skipif(cli._data_designer() is None, reason="data-designer CLI not installed")
@pytest.mark.parametrize("mode", ["singapore", "sdg-hub-harm", "combined"])
def test_first_run_setup_then_create_writes_a_dataset(endpoint, tmp_path, mode):
    env = {
        "PATH": str(Path(sys.executable).parent) + ":/usr/bin:/bin",
        "HOME": str(tmp_path / "home"),
        "DATA_DESIGNER_HOME": str(tmp_path / "dd"),
        "E2E_KEY": "not-a-real-key",
    }

    def run(*args: str, timeout: int = 300) -> subprocess.CompletedProcess:
        return subprocess.run(
            [sys.executable, "-m", "interplay", *args],
            cwd=tmp_path,
            env=env,
            capture_output=True,
            text=True,
            timeout=timeout,
        )

    before = run("probes", "create", "--mode", mode, "--num-records", "1")
    assert before.returncode == 2 and "interplay probes setup" in before.stderr

    assert (
        run(
            "probes",
            "setup",
            "--base-url",
            endpoint,
            "--model",
            "mock-model",
            "--api-key-env",
            "E2E_KEY",
        ).returncode
        == 0
    )
    result = run("probes", "create", "--mode", mode, "--num-records", "4")
    assert result.returncode == 0, result.stdout[-800:] + result.stderr[-800:]
    parquet = sorted(
        (tmp_path / "artifacts").glob("*/parquet-files/*.parquet")
    )  # final set, not the dropped-columns copy
    assert parquet, "create produced no dataset"
    import pandas as pd

    frame = pd.concat(pd.read_parquet(p) for p in parquet)
    assert len(frame) == 4, (
        f"expected 4 records, got {len(frame)} (rows are dropped when a column generator fails)"
    )
    assert frame["probe_quality_score"].notna().all(), (
        "every record, adversarial or benign, must carry a quality score"
    )

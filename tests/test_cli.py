"""Tests for the interplay command line."""

import subprocess
import sys
from pathlib import Path
from unittest.mock import patch

import pytest

from interplay import cli


def test_modes_lists_builtin_and_spec_modes(capsys):
    assert cli.main(["modes"]) == 0
    modes = capsys.readouterr().out.split()
    assert {"singapore", "sdg-hub-harm", "combined", "us-mexico"} <= set(modes)


def test_pipeline_path_points_at_packaged_pipeline(capsys):
    assert cli.main(["pipeline-path"]) == 0
    path = Path(capsys.readouterr().out.strip())
    assert path.name == "pipeline.py" and path.parent.name == "interplay"
    assert "def load_config_builder" in path.read_text()


def test_unknown_mode_is_rejected_with_the_list(capsys):
    assert cli.main(["probes", "validate", "--mode", "nope"]) == 2
    err = capsys.readouterr().err
    assert "unknown mode 'nope'" in err and "singapore" in err


def test_probes_sets_bias_spec_and_forwards_extra_args():
    with (
        patch.object(cli, "_data_designer", return_value="/x/data-designer"),
        patch("subprocess.run") as run,
    ):
        run.return_value.returncode = 0
        rc = cli.main(["probes", "create", "--mode", "us-mexico", "--num-records", "200"])
    assert rc == 0
    cmd = run.call_args.args[0]
    assert cmd[:2] == ["/x/data-designer", "create"]
    assert cmd[2].endswith("interplay/pipeline.py") and cmd[3:] == ["--num-records", "200"]
    assert run.call_args.kwargs["env"]["BIAS_SPEC"] == "us-mexico"


def test_missing_data_designer_gives_a_clear_error(capsys):
    with patch.object(cli, "_data_designer", return_value=None):
        assert cli.main(["probes", "validate"]) == 127
    assert "data-designer" in capsys.readouterr().err


@pytest.mark.parametrize("mode", ["singapore", "combined", "us-mexico"])
def test_probes_validate_runs_the_real_pipeline_validation(mode):
    if cli._data_designer() is None:
        pytest.skip("data-designer CLI not installed")
    result = subprocess.run(
        [sys.executable, "-m", "interplay", "probes", "validate", "--mode", mode],
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, result.stdout + result.stderr

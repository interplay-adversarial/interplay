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


def test_probes_sets_bias_spec_and_forwards_extra_args(tmp_path, monkeypatch):
    monkeypatch.setenv("DATA_DESIGNER_HOME", str(tmp_path))
    cli.setup_model("https://h/v1", "m", "K", "interplay-target")
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


def test_setup_writes_provider_and_alias_without_the_key(tmp_path, monkeypatch, capsys):
    monkeypatch.setenv("DATA_DESIGNER_HOME", str(tmp_path))
    monkeypatch.setenv("MY_KEY", "do-not-store-this-value")
    rc = cli.main(
        [
            "probes",
            "setup",
            "--base-url",
            "https://h/v1",
            "--model",
            "m1",
            "--api-key-env",
            "MY_KEY",
        ]
    )
    assert rc == 0 and cli.model_is_configured()
    text = (tmp_path / "model_providers.yaml").read_text() + (
        tmp_path / "model_configs.yaml"
    ).read_text()
    assert "do-not-store-this-value" not in text
    assert (
        "api_key: MY_KEY" in text
        and "alias: cultural-bias-model" in text
        and "https://h/v1" in text
    )


def test_setup_replaces_instead_of_duplicating_and_keeps_other_entries(tmp_path, monkeypatch):
    monkeypatch.setenv("DATA_DESIGNER_HOME", str(tmp_path))
    (tmp_path / "model_configs.yaml").write_text(
        "model_configs:\n- alias: other\n  model: x\n  provider: p\n"
    )
    cli.setup_model("https://a/v1", "m1", "K", "interplay-target")
    cli.setup_model("https://b/v1", "m2", "K", "interplay-target")
    models = cli._load_yaml(tmp_path / "model_configs.yaml", "model_configs")
    assert sorted(m["alias"] for m in models) == ["cultural-bias-model", "other"]
    assert next(m for m in models if m["alias"] == "cultural-bias-model")["model"] == "m2"
    providers = cli._load_yaml(tmp_path / "model_providers.yaml", "providers")
    assert len(providers) == 1 and providers[0]["endpoint"] == "https://b/v1"


def test_setup_requires_base_url_and_model(tmp_path, monkeypatch, capsys):
    monkeypatch.setenv("DATA_DESIGNER_HOME", str(tmp_path))
    assert cli.main(["probes", "setup"]) == 2
    assert "--base-url and --model" in capsys.readouterr().err


@pytest.mark.parametrize("action", ["preview", "create"])
def test_model_calling_actions_explain_missing_model_config(action, tmp_path, monkeypatch, capsys):
    monkeypatch.setenv("DATA_DESIGNER_HOME", str(tmp_path))
    with (
        patch.object(cli, "_data_designer", return_value="/x/data-designer"),
        patch("subprocess.run") as run,
    ):
        assert cli.main(["probes", action]) == 2
        run.assert_not_called()
    err = capsys.readouterr().err
    assert "cultural-bias-model" in err and "interplay probes setup" in err


def test_validate_does_not_need_a_model(tmp_path, monkeypatch):
    monkeypatch.setenv("DATA_DESIGNER_HOME", str(tmp_path))
    with (
        patch.object(cli, "_data_designer", return_value="/x/data-designer"),
        patch("subprocess.run") as run,
    ):
        run.return_value.returncode = 0
        assert cli.main(["probes", "validate"]) == 0

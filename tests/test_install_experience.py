"""Install-experience checks: clear errors when optional dependencies are missing."""

import subprocess
import sys
from unittest.mock import patch

import pytest


def test_red_teaming_import_without_extra_gives_install_hint():
    code = "import sys; sys.modules['any_llm'] = None; import interplay.red_teaming"
    result = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True)
    assert result.returncode != 0
    assert "interplay-adversarial[red-teaming]" in result.stderr


def test_run_garak_without_garak_installed_gives_install_hint():
    from interplay.red_teaming.garak_runner import run_garak

    with (
        patch("subprocess.run", side_effect=FileNotFoundError("garak")),
        pytest.raises(RuntimeError, match=r"interplay-adversarial\[garak\]"),
    ):
        run_garak("http://localhost/v1", "probes.jsonl")

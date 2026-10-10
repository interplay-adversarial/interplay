"""Pipeline validation tests."""

import subprocess
import sys
from pathlib import Path


def test_pipeline_validate():
    """Validate pipeline.py schema using data-designer CLI."""
    repo_root = Path(__file__).parent.parent
    pipeline_path = repo_root / "pipeline.py"

    assert pipeline_path.exists(), f"pipeline.py not found at {pipeline_path}"

    result = subprocess.run(
        [sys.executable, "-m", "data_designer", "validate", str(pipeline_path)],
        capture_output=True,
        text=True,
        cwd=repo_root,
    )

    # Check for validation errors (not API key warnings)
    output = result.stdout + result.stderr
    
    # Should not contain configuration errors
    assert "Configuration is invalid" not in output, f"Pipeline validation failed:\n{output}"
    assert "INVALID_REFERENCE" not in output, f"Pipeline has invalid template references:\n{output}"
    assert "Field required" not in output, f"Pipeline has missing required fields:\n{output}"
    
    # Should contain success indicator or at least not fail
    assert result.returncode == 0, f"Pipeline validation failed with code {result.returncode}:\n{output}"


def test_pipeline_imports():
    """Verify pipeline.py can be imported without errors."""
    repo_root = Path(__file__).parent.parent
    
    # Add repo to path
    import sys
    sys.path.insert(0, str(repo_root))
    
    try:
        import pipeline  # noqa: F401
    except ImportError as e:
        pytest.fail(f"pipeline.py failed to import: {e}")

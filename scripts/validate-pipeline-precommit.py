#!/usr/bin/env python3
"""Pre-commit hook: validate pipeline.py schema changes."""
import subprocess
import sys
from pathlib import Path


def main():
    """Run pipeline validation before commit."""
    repo_root = Path(__file__).parent.parent
    pipeline_path = repo_root / "pipeline.py"

    if not pipeline_path.exists():
        print("ERROR: pipeline.py not found")
        return 1

    print(f"Validating {pipeline_path}...")
    result = subprocess.run(
        ["data-designer", "validate", str(pipeline_path)],
        capture_output=True,
        text=True,
        cwd=repo_root,
    )

    output = result.stdout + result.stderr

    # Check for validation errors
    if "Configuration is invalid" in output:
        print("\n❌ Pipeline validation FAILED:")
        print(output)
        print("\nFix the configuration errors before committing.")
        return 1

    if "INVALID_REFERENCE" in output:
        print("\n❌ Pipeline has invalid template references:")
        print(output)
        print("\nCheck that all template variables ({{ variable_name }}) reference existing columns.")
        return 1

    if "Field required" in output:
        print("\n❌ Pipeline has missing required fields:")
        print(output)
        print("\nCheck the data-designer config schema for required fields.")
        return 1

    if result.returncode != 0:
        print(f"\n❌ Pipeline validation failed with code {result.returncode}:")
        print(output)
        return 1

    print("✅ Pipeline validation passed")
    return 0


if __name__ == "__main__":
    sys.exit(main())

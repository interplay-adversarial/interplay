"""
Spec loader for Interplay.

Convention: every .py file in this directory (except __init__.py, models.py,
singapore.py) exports a module-level `SPEC: BiasComparisonSpec` variable.

Adding a new spec:
    1. Create interplay/specs/my_spec.py with SPEC = BiasComparisonSpec(...)
    2. Use it: BIAS_SPEC=my-spec data-designer create pipeline.py --num-records 200
    No other files need to change.
"""

from __future__ import annotations

import importlib
import importlib.util
from pathlib import Path

from interplay.specs.models import BiasComparisonSpec  # noqa: F401 — re-export

_SPECS_DIR = Path(__file__).parent
_EXCLUDED = {"__init__", "models", "singapore", "sdg_hub_harm"}


def _slug_to_filename(slug: str) -> str:
    """'us-mexico' → 'us_mexico', 'us_mexico' → 'us_mexico'."""
    return slug.replace("-", "_")


def list_specs() -> list[str]:
    """Return slugs for all available specs (kebab-case)."""
    slugs = []
    for path in sorted(_SPECS_DIR.glob("*.py")):
        stem = path.stem
        if stem not in _EXCLUDED:
            slugs.append(stem.replace("_", "-"))
    return slugs


def load_spec(slug: str) -> BiasComparisonSpec:
    """
    Load a spec by slug (kebab-case or snake_case).

    Example:
        spec = load_spec("us-mexico")
        spec = load_spec("us_mexico")   # same result
    """
    filename = _slug_to_filename(slug)
    module_name = f"interplay.specs.{filename}"

    # Try as installed module first, then as file path
    try:
        module = importlib.import_module(module_name)
    except ModuleNotFoundError:
        spec_file = _SPECS_DIR / f"{filename}.py"
        if not spec_file.exists():
            available = ", ".join(list_specs()) or "(none)"
            raise ValueError(
                f"No spec found for '{slug}'. Available: {available}\n"
                f"Add a new spec by creating {_SPECS_DIR}/{filename}.py"
            ) from None
        mod_spec = importlib.util.spec_from_file_location(module_name, spec_file)
        module = importlib.util.module_from_spec(mod_spec)  # type: ignore[arg-type]
        mod_spec.loader.exec_module(module)  # type: ignore[union-attr]

    if not hasattr(module, "SPEC"):
        raise AttributeError(
            f"interplay/specs/{filename}.py must define a module-level 'SPEC' variable "
            f"of type BiasComparisonSpec."
        )
    return module.SPEC

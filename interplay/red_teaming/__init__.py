"""Red teaming attack runners for Interplay Adversarial."""

try:
    import any_llm  # noqa: F401
    import httpx  # noqa: F401
    import judge_kappa  # noqa: F401
except ModuleNotFoundError as exc:  # pragma: no cover - exercised through a subprocess test
    raise ImportError(
        f"interplay.red_teaming needs the 'red-teaming' extra (missing module: {exc.name}). "
        "Install it with: pip install 'interplay-adversarial[red-teaming]'"
    ) from exc

from .base import (
    create_completion_kwargs,
    get_attacker_config,
    get_env_var,
    get_judge_config,
    get_target_config,
    load_env_file,
)
from .crescendo_runner import CrescendoConfig, CrescendoResult, crescendo_attack
from .garak_runner import create_custom_config, parse_garak_results, run_garak
from .goat_runner import GoatConfig, GOATResult, goat_attack
from .multimodal_runner import MultimodalResult, multimodal_attack
from .pair_runner import PairResult, pair_attack
from .slip_runner import SLIPResult, slip_attack
from .tap_runner import TapResult, tap_attack
from .transport import (
    AuthenticatedTarget,
    BudgetExceeded,
    CallBudget,
    JudgeScorer,
    RoleCredentialError,
    RunBudget,
    RunnerRecord,
    RunnerResultSink,
    UnsupportedCapabilityError,
    recover_runner_records,
    resolve_role,
)

__all__ = [
    # Base utilities
    "get_env_var",
    "load_env_file",
    "get_target_config",
    "get_judge_config",
    "get_attacker_config",
    "create_completion_kwargs",
    # Shared transport, scoring and result retention (see transport.py)
    "AuthenticatedTarget",
    "BudgetExceeded",
    "CallBudget",
    "JudgeScorer",
    "RoleCredentialError",
    "RunBudget",
    "RunnerRecord",
    "RunnerResultSink",
    "UnsupportedCapabilityError",
    "recover_runner_records",
    "resolve_role",
    # Runners
    "run_garak",
    "create_custom_config",
    "parse_garak_results",
    "tap_attack",
    "TapResult",
    "pair_attack",
    "PairResult",
    "crescendo_attack",
    "CrescendoResult",
    "CrescendoConfig",
    "goat_attack",
    "GOATResult",
    "GoatConfig",
    "slip_attack",
    "SLIPResult",
    "multimodal_attack",
    "MultimodalResult",
]

"""Shared utilities for red teaming runners."""

import os
from pathlib import Path
from typing import Any


def get_env_var(name: str, required: bool = True) -> str:
    """Get environment variable or raise."""
    value = os.getenv(name)
    if required and not value:
        raise ValueError(f"Environment variable {name} is required")
    return value


def load_env_file(env_path: str | None = None) -> None:
    """Load .env file if it exists."""
    if env_path is None:
        # Default to .env in repo root
        env_path = Path(__file__).parent.parent / ".env"

    env_path = Path(env_path)
    if not env_path.exists():
        return

    with open(env_path) as f:
        for line in f:
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                key, value = line.split("=", 1)
                key = key.strip()
                value = value.strip().strip('"').strip("'")
                os.environ[key] = value


def get_target_config() -> dict[str, Any]:
    """Get target endpoint configuration from env vars."""
    return {
        "url": get_env_var("TARGET_URL"),
        "api_key": os.getenv("TARGET_API_KEY"),
        "model": os.getenv("TARGET_MODEL"),
    }


def get_judge_config() -> dict[str, Any]:
    """Get judge endpoint configuration from env vars."""
    return {
        "url": os.getenv("JUDGE_URL", os.getenv("TARGET_URL")),
        "api_key": os.getenv("JUDGE_API_KEY", os.getenv("TARGET_API_KEY")),
        "model": os.getenv("JUDGE_MODEL", os.getenv("TARGET_MODEL")),
    }


def get_attacker_config() -> dict[str, Any]:
    """Get attacker model configuration from env vars."""
    return {
        "url": os.getenv("ATTACKER_URL", os.getenv("TARGET_URL")),
        "api_key": os.getenv("ATTACKER_API_KEY", os.getenv("TARGET_API_KEY")),
        "model": os.getenv("ATTACKER_MODEL", os.getenv("TARGET_MODEL")),
    }


def create_completion_kwargs(provider: str | None = None, **kwargs) -> dict[str, Any]:
    """Create completion kwargs with env-based configuration.

    Returns kwargs dict to pass to any_llm.completion() or any_llm.acompletion().
    """
    # Load .env file if it exists
    load_env_file()

    # Default provider if not specified
    if provider is None:
        provider = os.getenv("LLM_PROVIDER", "openai")

    # Build kwargs
    config = {
        "provider": provider,
        **kwargs,
    }

    # Add API key if available
    api_key = os.getenv(f"{provider.upper()}_API_KEY", os.getenv("API_KEY"))
    if api_key:
        config["api_key"] = api_key

    # Add api_base (not base_url) for any_llm - check for OPENAI_API_BASE specifically for OpenAI provider
    if provider == "openai":
        api_base = os.getenv("OPENAI_API_BASE", os.getenv("API_BASE"))
        if api_base:
            config["api_base"] = api_base
    else:
        api_base = os.getenv(f"{provider.upper()}_API_BASE", os.getenv("API_BASE"))
        if api_base:
            config["api_base"] = api_base

    return config

"""Garak runner for cultural-bias-red-team integration."""

import json
import subprocess
from pathlib import Path


def run_garak(
    target_url: str,
    probe_file: str,
    config_file: str | None = None,
    output_dir: str | None = None,
) -> dict:
    """Run Garak against target model with custom probes.

    Args:
        target_url: HTTP endpoint URL (OpenAI-compatible API)
        probe_file: Path to probe file in Garak-compatible format
        config_file: Optional custom Garak config file
        output_dir: Directory for output files

    Returns:
        Dict with Garak results summary
    """
    # Ensure output directory exists
    if output_dir:
        Path(output_dir).mkdir(parents=True, exist_ok=True)

    # Build Garak command
    cmd = [
        "garak",
        "--model",
        "custom",
        "--model_type",
        "http",
        "--config",
        "custom_http",  # Use built-in custom HTTP config
    ]

    # Add custom config if provided
    if config_file:
        cmd.extend(["--config", config_file])

    # Add probe file if provided
    if probe_file:
        cmd.extend(["--probes", probe_file])

    # Run Garak
    print(f"Running Garak: {' '.join(cmd)}")
    result = subprocess.run(cmd, capture_output=True, text=True)

    # Parse results
    return {
        "success": result.returncode == 0,
        "stdout": result.stdout,
        "stderr": result.stderr,
        "returncode": result.returncode,
    }


def create_custom_config(target_url: str, output_path: str) -> str:
    """Create custom Garak config file for target endpoint.

    Args:
        target_url: HTTP endpoint URL
        output_path: Path to write config file

    Returns:
        Path to created config file
    """
    config = {
        "plugin": "http",
        "url": target_url,
        "method": "POST",
        "headers": {"Content-Type": "application/json"},
        "body_template": {
            "model": "target-model",
            "messages": [{"role": "user", "content": "{prompt}"}],
            "max_tokens": 512,
        },
        "response_parser": "choices[0].message.content",
    }

    config_path = Path(output_path)
    with open(config_path, "w") as f:
        json.dump(config, f, indent=2)

    return str(config_path)


def parse_garak_results(report_file: str) -> dict:
    """Parse Garak HTML/JSON report into structured results.

    Args:
        report_file: Path to Garak report file

    Returns:
        Dict with parsed results
    """
    # Garak typically outputs HTML reports; JSON if --report_format json
    # This is a placeholder - actual parsing depends on Garak output format
    return {
        "report_file": report_file,
        "status": "pending",
    }

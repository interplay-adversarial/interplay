"""Command line for Interplay Adversarial.

    interplay modes                              list pipeline modes
    interplay pipeline-path                      print the path of the packaged pipeline file
    interplay probes setup --base-url U --model M   define the model the pipeline uses (once)
    interplay probes validate|preview|create     run the packaged probe pipeline with data-designer

`probes` selects the mode with --mode (default singapore) and forwards every other argument to
data-designer, for example:

    interplay probes create --mode us-mexico --num-records 200
"""

from __future__ import annotations

import argparse
import os
import shutil
import subprocess
import sys
from pathlib import Path

import yaml

from interplay import __version__

BUILTIN_MODES = ("singapore", "sdg-hub-harm", "combined")
PIPELINE = Path(__file__).with_name("pipeline.py")
ACTIONS = ("validate", "preview", "create")
MODEL_ALIAS = "cultural-bias-model"  # the alias interplay/pipeline.py asks data-designer for
MODEL_CALLING_ACTIONS = ("preview", "create")


def available_modes() -> list[str]:
    from interplay.specs import list_specs

    return [*BUILTIN_MODES, *list_specs()]


def _data_designer() -> str | None:
    """The data-designer command next to this interpreter (virtualenv not activated), else on PATH."""
    local = Path(sys.executable).parent / "data-designer"
    return str(local) if local.exists() else shutil.which("data-designer")


def config_dir() -> Path:
    """data-designer's configuration directory (same rule as data-designer: DATA_DESIGNER_HOME)."""
    return Path(os.getenv("DATA_DESIGNER_HOME", Path.home() / ".data-designer"))


def _load_yaml(path: Path, key: str) -> list[dict]:
    if not path.exists():
        return []
    return (yaml.safe_load(path.read_text()) or {}).get(key) or []


def model_is_configured(alias: str = MODEL_ALIAS) -> bool:
    items = _load_yaml(config_dir() / "model_configs.yaml", "model_configs")
    return any(item.get("alias") == alias for item in items)


def setup_model(
    base_url: str, model: str, api_key_env: str, provider_name: str, alias: str = MODEL_ALIAS
) -> Path:
    """Add or replace one OpenAI-compatible provider and the pipeline's model alias in data-designer's config.

    Only the NAME of the environment variable that holds the API key is stored, never the key.
    """
    home = config_dir()
    home.mkdir(parents=True, exist_ok=True)
    providers_file, models_file = home / "model_providers.yaml", home / "model_configs.yaml"
    providers = [
        p for p in _load_yaml(providers_file, "providers") if p.get("name") != provider_name
    ]
    providers.append(
        {
            "name": provider_name,
            "endpoint": base_url,
            "provider_type": "openai",
            "api_key": api_key_env,
            "extra_body": None,
            "extra_headers": None,
        }
    )
    models = [m for m in _load_yaml(models_file, "model_configs") if m.get("alias") != alias]
    models.append(
        {
            "alias": alias,
            "model": model,
            "inference_parameters": {
                "generation_type": "chat-completion",
                "max_parallel_requests": 4,
                "timeout": None,
                "extra_body": None,
                "temperature": 1.0,
                "top_p": 0.95,
                "max_tokens": None,
            },
            "provider": provider_name,
            "skip_health_check": False,
        }
    )
    providers_file.write_text(yaml.safe_dump({"providers": providers}, sort_keys=False))
    models_file.write_text(yaml.safe_dump({"model_configs": models}, sort_keys=False))
    return home


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="interplay",
        description="Interplay Adversarial: probe generation and red-teaming toolkit.",
    )
    parser.add_argument(
        "--version", action="version", version=f"interplay-adversarial {__version__}"
    )
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("modes", help="list the available pipeline modes")
    sub.add_parser("pipeline-path", help="print the path of the packaged pipeline file")
    sub.add_parser(
        "assess", help="description-driven probe/target/judge campaign; private datasets"
    )
    sub.add_parser(
        "assessment-recover", help="export interrupted campaign stages without model calls"
    )
    sub.add_parser("runner-run", help="execute a method runner with durable private datasets")
    sub.add_parser("runner-recover", help="export runner journal without model calls")
    probes = sub.add_parser(
        "probes",
        help="run the probe pipeline through data-designer",
        description="Other arguments are passed to data-designer (for example --num-records 200).",
    )
    probes.add_argument("action", choices=(*ACTIONS, "setup"))
    probes.add_argument("--mode", default="singapore", help="pipeline mode (see `interplay modes`)")
    probes.add_argument(
        "--base-url", help="setup: OpenAI-compatible endpoint, for example https://host/v1"
    )
    probes.add_argument("--model", help="setup: model name served by that endpoint")
    probes.add_argument(
        "--api-key-env",
        default="OPENAI_API_KEY",
        help="setup: name of the environment variable holding the API key",
    )
    probes.add_argument(
        "--provider-name", default="interplay-target", help="setup: provider name to store"
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    values = sys.argv[1:] if argv is None else argv
    if values and values[0] in ("runner-run", "runner-recover"):
        from interplay.red_teaming.cli import main as runner_main

        return runner_main(values)
    if values and values[0] in ("assess", "assessment-recover"):
        from interplay.assessment.cli import main as assessment_main

        return assessment_main(values)
    args, extra = build_parser().parse_known_args(argv)
    if args.command == "modes":
        print("\n".join(available_modes()))
        return 0
    if args.command == "pipeline-path":
        print(PIPELINE)
        return 0

    if args.action == "setup":
        if not args.base_url or not args.model:
            print("interplay: probes setup needs --base-url and --model.", file=sys.stderr)
            return 2
        home = setup_model(args.base_url, args.model, args.api_key_env, args.provider_name)
        print(
            f"Configured model alias '{MODEL_ALIAS}' -> {args.model} at {args.base_url} (config in {home})."
        )
        print(f"Export the API key before running preview or create: export {args.api_key_env}=...")
        return 0

    modes = available_modes()
    if args.mode not in modes:
        print(
            f"interplay: unknown mode '{args.mode}'. Available: {', '.join(modes)}", file=sys.stderr
        )
        return 2
    if args.action in MODEL_CALLING_ACTIONS and not model_is_configured():
        print(
            f"interplay: no model is configured for the pipeline (alias '{MODEL_ALIAS}'). Set one up once with:\n"
            "  interplay probes setup --base-url https://your-endpoint/v1 --model your-model "
            "--api-key-env OPENAI_API_KEY\n"
            f"or with `data-designer config models` (alias must be '{MODEL_ALIAS}'). `validate` needs no model.",
            file=sys.stderr,
        )
        return 2
    exe = _data_designer()
    if exe is None:
        print(
            "interplay: the 'data-designer' command was not found; reinstall interplay-adversarial.",
            file=sys.stderr,
        )
        return 127
    env = {**os.environ, "BIAS_SPEC": args.mode}
    return subprocess.run([exe, args.action, str(PIPELINE), *extra], env=env).returncode


if __name__ == "__main__":
    sys.exit(main())

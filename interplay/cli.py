"""Command line for Interplay Adversarial.

    interplay modes                              list pipeline modes
    interplay pipeline-path                      print the path of the packaged pipeline file
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

from interplay import __version__

BUILTIN_MODES = ("singapore", "sdg-hub-harm", "combined")
PIPELINE = Path(__file__).with_name("pipeline.py")
ACTIONS = ("validate", "preview", "create")


def available_modes() -> list[str]:
    from interplay.specs import list_specs

    return [*BUILTIN_MODES, *list_specs()]


def _data_designer() -> str | None:
    """The data-designer command next to this interpreter (virtualenv not activated), else on PATH."""
    local = Path(sys.executable).parent / "data-designer"
    return str(local) if local.exists() else shutil.which("data-designer")


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
    probes = sub.add_parser(
        "probes",
        help="run the probe pipeline through data-designer",
        description="Other arguments are passed to data-designer (for example --num-records 200).",
    )
    probes.add_argument("action", choices=ACTIONS)
    probes.add_argument("--mode", default="singapore", help="pipeline mode (see `interplay modes`)")
    return parser


def main(argv: list[str] | None = None) -> int:
    args, extra = build_parser().parse_known_args(argv)
    if args.command == "modes":
        print("\n".join(available_modes()))
        return 0
    if args.command == "pipeline-path":
        print(PIPELINE)
        return 0

    modes = available_modes()
    if args.mode not in modes:
        print(
            f"interplay: unknown mode '{args.mode}'. Available: {', '.join(modes)}", file=sys.stderr
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

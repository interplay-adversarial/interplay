"""Private method-runner execution and offline recovery commands."""

import argparse
import asyncio
import json
from pathlib import Path

from pydantic import TypeAdapter

from ..assessment.models import ModelEndpoint
from .session import JudgeMember
from .transport import recover_runner_records

METHODS = ("pair", "tap", "crescendo", "goat", "slip", "multimodal")


def main(argv):
    parser = argparse.ArgumentParser(prog="interplay")
    sub = parser.add_subparsers(dest="command", required=True)
    run = sub.add_parser("runner-run")
    run.add_argument("--method", choices=METHODS, required=True)
    run.add_argument(
        "--config", type=Path, required=True, help="JSON: parameters, role_endpoints, judge_members"
    )
    run.add_argument("--output", type=Path, required=True, help="new private output directory")
    recover = sub.add_parser("runner-recover")
    recover.add_argument("output", type=Path)
    args = parser.parse_args(argv)
    if args.command == "runner-recover":
        records = recover_runner_records(args.output)
        print(
            json.dumps(
                {
                    "records": len(records),
                    "output": str(args.output),
                    "truncated_tail": records.truncated_tail,
                }
            )
        )
        return 0
    from importlib import import_module

    config = json.loads(args.config.read_text())
    if set(config) - {"parameters", "role_endpoints", "judge_members"}:
        parser.error("unknown runner config fields")
    # Model configuration includes env names only; literal credentials are not accepted.
    roles = {
        role: ModelEndpoint.model_validate(value)
        for role, value in config.get("role_endpoints", {}).items()
    }
    members = TypeAdapter(list[JudgeMember]).validate_python(config.get("judge_members", []))
    parameters = config.get("parameters", {})
    if "api_key" in parameters:
        parser.error("use role_endpoints with api_key_env, never literal api_key")
    module = import_module(f"interplay.red_teaming.{args.method}_runner")
    result = asyncio.run(
        getattr(module, f"{args.method}_attack")(
            **parameters, role_endpoints=roles, judge_members=members, output_dir=args.output
        )
    )
    print(
        json.dumps(
            {
                "method": args.method,
                "records": len(result.records),
                "stop_reason": result.stop_reason,
                "output": str(args.output),
            }
        )
    )
    return 0

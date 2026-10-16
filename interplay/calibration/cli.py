"""Offline calibration workflow; labels must come from independent human reviewers."""

import argparse
import json
import sys
from pathlib import Path

from .collect import collect
from .metrics import evaluate
from .workflow import compile_gold, prediction_templates, prepare


class Parser(argparse.ArgumentParser):
    def error(self, message):
        self.exit(2, '{"error":"invalid-calibration-input"}\n')


def main(argv):
    parser = Parser(prog="interplay calibration")
    sub = parser.add_subparsers(dest="action", required=True, parser_class=Parser)
    setup = sub.add_parser(
        "prepare", help="create 60 synthetic cases and two independent review packets"
    )
    setup.add_argument("--output", type=Path, required=True)
    collector = sub.add_parser(
        "collect", help="explicit bounded inference; requires configured judge credentials"
    )
    collector.add_argument("--cases", type=Path, required=True)
    collector.add_argument("--config", type=Path, required=True)
    collector.add_argument("--output", type=Path, required=True)
    collector.add_argument("--max-cases", type=int, default=5)
    collector.add_argument("--campaign-seconds", type=int, default=600)
    for action in ("gold", "predictions", "evaluate"):
        command = sub.add_parser(action)
        command.add_argument("--cases", type=Path, required=True)
        command.add_argument("--output", type=Path, required=True)
        if action == "gold":
            command.add_argument("--labels", type=Path, action="append", required=True)
            command.add_argument("--adjudications", type=Path)
        else:
            command.add_argument("--judges", type=Path, required=True)
        if action == "evaluate":
            command.add_argument("--gold", type=Path, required=True)
            command.add_argument("--predictions", type=Path, action="append", required=True)
    args = parser.parse_args(argv[1:])
    print(
        "Private calibration artifacts: review before sharing. Human label provenance requires external verification.",
        file=sys.stderr,
    )
    try:
        if args.action == "prepare":
            result = prepare(args.output)
        elif args.action == "collect":
            result = collect(
                args.cases,
                args.config,
                args.output,
                max_cases=args.max_cases,
                campaign_seconds=args.campaign_seconds,
            )
        elif args.action == "gold":
            result = compile_gold(args.cases, args.labels, args.adjudications, args.output)
        elif args.action == "predictions":
            result = prediction_templates(args.cases, args.judges, args.output)
        else:
            result = evaluate(args.cases, args.gold, args.judges, args.predictions, args.output)
        print(
            json.dumps(
                {
                    k: result[k]
                    for k in ("cases", "reference_ready", "metrics_generated", "resolved_cases")
                    if k in result
                },
                sort_keys=True,
            )
        )
        return 0
    except Exception:
        print('{"error":"calibration-failed","release_eligible":false}', file=sys.stderr)
        return 2

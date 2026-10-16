"""Private benchmark CLI; only 'run' makes explicitly configured model calls."""

import argparse
import json
import sys
from pathlib import Path

from .core import compare, import_records, prepare, recover
from .run import run


class Parser(argparse.ArgumentParser):
    def error(self, message):
        self.exit(2, '{"error":"invalid-benchmark-input"}\n')


def main(argv):
    parser = Parser(prog="interplay benchmark")
    sub = parser.add_subparsers(dest="action", required=True, parser_class=Parser)
    for action in ("prepare", "run", "import", "compare", "recover"):
        command = sub.add_parser(action)
        command.add_argument("--cases", type=Path, required=True)
        command.add_argument("--output", type=Path, required=True)
        if action == "prepare":
            command.add_argument("--baseline", type=Path, required=True)
            command.add_argument("--candidate", type=Path, required=True)
            command.add_argument("--judge", type=Path)
            command.add_argument("--suite-id", required=True)
            command.add_argument("--source-revision", required=True)
            command.add_argument("--repeats", type=int, default=1)
            command.add_argument("--max-cases", type=int, default=5)
            command.add_argument("--campaign-seconds", type=int, default=600)
        else:
            command.add_argument("--manifest", type=Path, required=True)
        if action == "import":
            command.add_argument("--variant", choices=("baseline", "candidate"), required=True)
            command.add_argument("--records", type=Path, required=True)
            command.add_argument("--mapping", type=Path, required=True)
        elif action == "compare":
            command.add_argument("--records", type=Path, action="append", required=True)
        elif action == "recover":
            command.add_argument("--journal", type=Path, required=True)
    args = parser.parse_args(argv[1:])
    print(
        "Private benchmark evidence: review before sharing. Comparisons do not establish calibrated accuracy.",
        file=sys.stderr,
    )
    try:
        if args.action == "prepare":
            result = prepare(
                args.cases,
                args.baseline,
                args.candidate,
                args.judge,
                args.output,
                suite_id=args.suite_id,
                source_revision=args.source_revision,
                repeats=args.repeats,
                max_cases=args.max_cases,
                campaign_seconds=args.campaign_seconds,
            )
        elif args.action == "run":
            result = run(args.manifest, args.cases, args.output)
        elif args.action == "compare":
            result = compare(args.manifest, args.cases, args.records, args.output)
        elif args.action == "recover":
            result = recover(args.manifest, args.cases, args.journal, args.output)
        else:
            result = import_records(
                args.manifest, args.cases, args.variant, args.records, args.mapping, args.output
            )
        print(
            json.dumps(
                {
                    k: result[k]
                    for k in (
                        "cases",
                        "records",
                        "paired_cases",
                        "model_calls",
                        "client_calls_attempted",
                    )
                    if k in result
                },
                sort_keys=True,
            )
        )
        return 0
    except Exception:
        print('{"error":"benchmark-failed","release_eligible":false}', file=sys.stderr)
        return 2

"""Private standalone campaign/recovery CLI; only summaries go to stdout."""

import argparse
import contextlib
import importlib.metadata
import json
import logging
import os
import tempfile
from pathlib import Path

from .models import CampaignConfig
from .storage import private_file, recover_assessment


class PrivateParser(argparse.ArgumentParser):
    def error(self, message):
        self.exit(2, '{"error":"invalid-assessment-input","release_eligible":false}\n')


def main(argv):
    parser = PrivateParser(prog="interplay " + argv[0])
    parser.add_argument("--output", type=Path, required=True)
    if argv[0] == "assess":
        parser.add_argument("--config", type=Path, required=True)
        parser.add_argument("--description")
        parser.add_argument("--success-criteria")
        parser.add_argument("--num-probes", type=int)
        parser.add_argument("--validate", action="store_true")
    args = parser.parse_args(argv[1:])
    try:
        if argv[0] == "assessment-recover":
            summary = recover_assessment(args.output)
        else:
            raw = json.loads(private_file(args.config, limit=65536))
            if args.description:
                raw.setdefault("assessment", {})["description"] = args.description
                raw["assessment"]["success_criteria"] = args.success_criteria or args.description
            elif args.success_criteria:
                raw.setdefault("assessment", {})["success_criteria"] = args.success_criteria
            if args.num_probes is not None:
                raw.setdefault("assessment", {})["probe_count"] = args.num_probes
            config = CampaignConfig.model_validate_json(json.dumps(raw))
            if args.validate:
                print('{"valid":true,"release_eligible":false}')
                return 0
            from .designer import DataDesignerBackend
            from .endpoint import OpenAIEndpointTarget
            from .runner import run_assessment

            adversarial, attacker_key = config.adversarial.resolved("ADVERSARIAL")
            target, target_key = config.target.resolved("TARGET")
            judge, judge_key = config.judge.resolved("JUDGE")
            provenance = {
                "adversarial": adversarial.model_dump(exclude={"api_key_env"}),
                "target": target.model_dump(exclude={"api_key_env"}),
                "judge": judge.model_dump(exclude={"api_key_env"}),
                "adversarial_model_kind": "abliterated",
                "abliteration_attestation": "operator-declared-unverified",
                "model_weights_attested": False,
                "data_designer_version": importlib.metadata.version("data-designer"),
                "interplay_version": importlib.metadata.version("interplay-adversarial"),
            }
            old_mask = os.umask(0o077)
            try:
                # This command is a dedicated process. The library API does not
                # mutate caller HOME, provider state or logging configuration.
                os.environ["NEMO_TELEMETRY_ENABLED"] = "false"
                logging.disable(logging.CRITICAL)
                with (
                    tempfile.TemporaryDirectory(prefix="interplay-designer-") as designer_home,
                    open(os.devnull, "w") as quiet,
                    contextlib.redirect_stdout(quiet),
                    contextlib.redirect_stderr(quiet),
                ):
                    os.environ["DATA_DESIGNER_HOME"] = designer_home
                    backend = DataDesignerBackend(
                        adversarial,
                        judge,
                        adversarial_key=attacker_key,
                        judge_key=judge_key,
                        artifact_path=args.output / "designer",
                    )
                    summary = run_assessment(
                        config.assessment,
                        backend,
                        OpenAIEndpointTarget(target, api_key=target_key),
                        backend,
                        args.output,
                        provenance=provenance,
                        secrets=(attacker_key, target_key, judge_key),
                    )
            finally:
                os.umask(old_mask)
        print(json.dumps(summary, sort_keys=True))
        return 0 if summary.get("assessment_complete") else 2
    except Exception:
        print('{"error":"assessment-failed","release_eligible":false}')
        return 2

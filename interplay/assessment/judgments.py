"""Provider-free judge reply normalization and existing panel verdict policies."""

import json
import re
from collections import Counter

from .models import JudgeOutput
from .storage import json_bytes


def parse_judge_output(content: str) -> JudgeOutput:
    """Normalize equivalent wire formats, never extract JSON from arbitrary prose."""
    text = content.strip()
    fence = re.fullmatch(r"```(?:json)?[ \t]*\r?\n(.*?)\r?\n```", text, re.DOTALL | re.IGNORECASE)
    if fence:
        text = fence[1]

    def unique_fields(pairs):
        result = {}
        for key, value in pairs:
            if key in result:
                raise ValueError("judge-duplicate-field")
            result[key] = value
        return result

    parsed = json.loads(text, object_pairs_hook=unique_fields)
    if isinstance(parsed, dict) and isinstance(parsed.get("evidence_refs_json"), list):
        parsed["evidence_refs_json"] = json_bytes(parsed["evidence_refs_json"]).decode()
    return JudgeOutput.model_validate(parsed)


def aggregate_verdicts(verdicts, policy):
    """Historical 'majority' is strict plurality; any tie is inconclusive."""
    if not verdicts or policy not in ("majority", "unanimous"):
        raise ValueError("judge-panel-policy-invalid")
    if any(v not in ("success", "failure", "inconclusive") for v in verdicts):
        raise ValueError("judge-panel-verdict-invalid")
    counts = Counter(verdicts).most_common()
    if policy == "unanimous":
        return verdicts[0] if len(counts) == 1 else "inconclusive"
    return counts[0][0] if len(counts) == 1 or counts[0][1] > counts[1][1] else "inconclusive"

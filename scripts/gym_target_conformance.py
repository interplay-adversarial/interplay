"""Pinned native Gym/Interplay drill; synthetic file receiver, no real resources.

Use a separate Gym interpreter. Default model transport is a deterministic fixture.
--provider explicitly enables up to three real model calls; private profile format
is {"endpoint": ModelEndpoint, "extra_body_json": "{}"}. No action is retried.
"""

import argparse
import hashlib
import json
import os
import sys
import time
from contextlib import asynccontextmanager
from pathlib import Path
from uuid import uuid4

from interplay.assessment.gym import GymSession, GymTargetConfig, NeMoGymTarget
from interplay.assessment.models import ModelEndpoint, Probe
from interplay.assessment.storage import atomic_file, json_bytes, private_file
from interplay.benchmark.models import profile

MARKER = "GYM-SYNTHETIC-CANARY"
ATTEMPT = "a" * 32


def run(gym_source, output, provider_path=None, *, mode="complete"):
    """Execute actual native SimpleAgent/converter with a separate file observer."""
    sys.path.insert(0, str(Path(gym_source).resolve()))
    import aiohttp
    from nemo_gym.config_types import BaseServerConfig, ModelServerRef, ResourcesServerRef
    from nemo_gym.openai_utils import NeMoGymChatCompletion, NeMoGymResponseCreateParamsNonStreaming
    from nemo_gym.responses_converter import VLLMConverter
    from nemo_gym.server_utils import ServerClient
    from omegaconf import OmegaConf
    from responses_api_agents.simple_agent.app import SimpleAgent, SimpleAgentConfig

    root = Path(output)
    root.mkdir(mode=0o700, exist_ok=False)
    receiver = root / "receiver"
    receiver.mkdir(mode=0o700)
    counters = {"model": 0, "tool": 0}
    attempt_id = uuid4().hex if provider_path else ATTEMPT
    credential = None
    if provider_path:
        endpoint, extra = profile(private_file(Path(provider_path), limit=32768).decode())
        credential = os.environ.get(endpoint.api_key_env) if endpoint.api_key_env else None
        if not credential:
            raise ValueError("explicit-model-credential-required")
    else:
        endpoint = ModelEndpoint(base_url="http://127.0.0.1/v1", model="fixture", max_tokens=512)
        extra = {}
    converter = VLLMConverter(return_token_id_information=False, uses_reasoning_parser=True)
    packets = []

    class Reply:
        ok, status, cookies = True, 200, {}

        def __init__(self, value):
            self.raw, self.content = json_bytes(value), self

        async def read(self):
            return self.raw

    async def fetch(body, session):
        if not provider_path:
            tool = counters["model"] == 1 or mode == "exhausted"
            message = {"role": "assistant", "content": "Recorded " + MARKER}
            finish = "stop"
            if tool:
                message = {
                    "role": "assistant",
                    "content": None,
                    "tool_calls": [
                        {
                            "id": "call-" + str(counters["model"]),
                            "type": "function",
                            "function": {
                                "name": "record_marker",
                                "arguments": json.dumps({"marker": MARKER}),
                            },
                        }
                    ],
                }
                finish = "tool_calls"
            if mode == "truncated":
                message, finish = {"role": "assistant", "content": "Partial"}, "length"
            return {
                "id": "completion-" + str(counters["model"]),
                "object": "chat.completion",
                "created": 1700000000,
                "model": endpoint.model,
                "choices": [{"index": 0, "message": message, "finish_reason": finish}],
            }
        encoded = json_bytes(body)
        async with session.post(
            endpoint.base_url + "/chat/completions",
            data=encoded,
            headers={"Authorization": "Bearer " + credential, "Content-Type": "application/json"},
            allow_redirects=False,
        ) as reply:
            raw = bytearray()
            async for chunk in reply.content.iter_chunked(65536):
                raw.extend(chunk)
                if len(raw) > 2 * 1024 * 1024:
                    raise ValueError("model-response-limit")
            if reply.status != 200:
                raise ValueError("model-http-failed")
        # Exact supplied credential reflection is rejected before raw persistence.
        value = json.loads(raw)
        pending = [value]
        while pending:
            item = pending.pop()
            if isinstance(item, str) and credential in item:
                raise ValueError("model-credential-reflection")
            if isinstance(item, dict):
                pending.extend(item.keys())
                pending.extend(item.values())
            elif isinstance(item, list):
                pending.extend(item)
        packets.append(
            {
                "request": body,
                "request_sha256": hashlib.sha256(encoded).hexdigest(),
                "response": value,
                "response_sha256": hashlib.sha256(raw).hexdigest(),
            }
        )
        atomic_file(root / "packets.json", json_bytes(packets))
        return value

    @asynccontextmanager
    async def factory(attempt):
        timeout = aiohttp.ClientTimeout(total=endpoint.request_seconds)
        async with aiohttp.ClientSession(timeout=timeout, trust_env=False) as session:

            class Client(ServerClient):
                async def post(self, *, server_name, url_path, json, cookies=None):
                    if server_name == "model" and url_path == "/v1/responses":
                        counters["model"] += 1
                        if counters["model"] > 3:
                            raise ValueError("model-call-cap")
                        body = NeMoGymResponseCreateParamsNonStreaming.model_validate(json)
                        payload = converter.responses_to_chat_completion_create_params(
                            body
                        ).model_dump(mode="json", exclude_none=True, exclude_unset=True)
                        payload.update(
                            model=endpoint.model,
                            max_tokens=endpoint.max_tokens,
                            temperature=endpoint.temperature,
                            stream=False,
                            parallel_tool_calls=False,
                            **extra,
                        )
                        value = await fetch(payload, session)
                        completion = NeMoGymChatCompletion.model_validate(value)
                        if completion.model != endpoint.model or len(completion.choices) != 1:
                            raise ValueError("model-response-identity-mismatch")
                        converted = converter.chat_completion_to_response(body, completion)
                        return Reply(converted.model_dump(mode="json"))
                    if (
                        server_name != "resources"
                        or url_path != "/record_marker"
                        or json != {"marker": MARKER}
                    ):
                        raise ValueError("synthetic-tool-arguments-invalid")
                    counters["tool"] += 1
                    # This receiver writes its own state; the model cannot select a path.
                    # The observer subsequently reads the file, not the tool/model reply.
                    atomic_file(
                        receiver / (attempt + "-" + str(counters["tool"]) + ".json"),
                        json_bytes(
                            {"attempt_id": attempt, "marker": MARKER, "sequence": counters["tool"]}
                        ),
                    )
                    return Reply({"recorded": True})

            client = Client(
                head_server_config=BaseServerConfig(host="127.0.0.1", port=8080),
                global_config_dict=OmegaConf.create({}),
            )
            agent = SimpleAgent(
                config=SimpleAgentConfig(
                    host="127.0.0.1",
                    port=8080,
                    entrypoint="",
                    name="agent",
                    model_server=ModelServerRef(type="responses_api_models", name="model"),
                    resources_server=ResourcesServerRef(type="resources_servers", name="resources"),
                    max_steps=3,
                ),
                server_client=client,
            )

            async def outcome():
                rows = [
                    json.loads(private_file(p)) for p in sorted(receiver.glob(attempt + "-*.json"))
                ]
                return {"receiver_records": rows, "record_count": len(rows)}

            yield GymSession(agent, outcome)

    template = {
        "model": endpoint.model,
        "input": [
            {
                "role": "system",
                "content": "This is a harmless synthetic tool test. Follow the user request using the provided tool before answering.",
            }
        ],
        "tools": [
            {
                "type": "function",
                "name": "record_marker",
                "description": "Record the supplied synthetic canary in a local receiver. Call once before answering.",
                "strict": True,
                "parameters": {
                    "type": "object",
                    "properties": {"marker": {"type": "string", "enum": [MARKER]}},
                    "required": ["marker"],
                    "additionalProperties": False,
                },
            }
        ],
    }
    config = GymTargetConfig(
        task_id="synthetic-receiver",
        request_json=json.dumps(template),
        max_steps=3,
        max_output_tokens=endpoint.max_tokens,
        rollout_seconds=120,
        observation_seconds=2,
    )
    target = NeMoGymTarget(
        config, factory, root / "adapter", secrets=(credential,) if credential else ()
    )
    observation = target.observe(
        Probe(
            probe="Call record_marker exactly once with marker "
            + MARKER
            + ", then reply Recorded.",
            adversarial_intent="Harmless synthetic receiver test",
            strategy="direct",
        ),
        attempt_id,
        deadline=time.monotonic() + 125,
    )
    logs = json.loads(observation.logs_json)
    traces = json.loads(observation.traces_json)
    receiver_rows = [json.loads(private_file(p)) for p in sorted(receiver.glob("*.json"))]
    summary = {
        "schema_version": "interplay-gym-conformance/1",
        "fixture": not bool(provider_path),
        "mode": mode,
        "capture_complete": observation.capture_complete,
        "model_calls": counters["model"],
        "tool_calls": counters["tool"],
        "receiver_records": len(receiver_rows),
        "receiver_matches_observation": receiver_rows
        == logs.get("environment_outcome", {}).get("receiver_records"),
        "attempt_binding": logs["attempt_id"] == attempt_id and logs["rollout_id"] == attempt_id,
        "native_tool_calls": len((traces.get("native_trajectory") or {}).get("tool_calls", [])),
        "boundary_evaluated": False,
        "judge_accuracy": None,
        "release_eligible": False,
    }
    summary["verification_passed"] = bool(
        summary["attempt_binding"]
        and summary["receiver_matches_observation"]
        and (
            (mode == "complete" and observation.capture_complete and receiver_rows)
            or (mode != "complete" and not observation.capture_complete)
        )
    )
    atomic_file(root / "verification.json", json_bytes(summary))
    return summary


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--gym-source", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--provider", type=Path)
    parser.add_argument(
        "--mode", choices=("complete", "exhausted", "truncated"), default="complete"
    )
    args = parser.parse_args()
    if args.provider and args.mode != "complete":
        parser.error("fault modes use fixture transport only")
    old = os.umask(0o077)
    try:
        summary = run(args.gym_source, args.output, args.provider, mode=args.mode)
        print(json.dumps(summary, sort_keys=True))
        return 0 if summary["verification_passed"] else 2
    except Exception:
        print('{"error":"gym-conformance-failed","release_eligible":false}')
        return 2
    finally:
        os.umask(old)


if __name__ == "__main__":
    raise SystemExit(main())

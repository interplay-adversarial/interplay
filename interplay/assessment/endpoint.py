"""Fixed endpoint adapter; a generated probe cannot select URLs or executables."""

import json
import time

from .models import ModelEndpoint, Observation
from .storage import json_bytes


class OpenAIEndpointTarget:
    def __init__(self, endpoint: ModelEndpoint, *, api_key: str):
        self.endpoint = ModelEndpoint.model_validate(endpoint)
        self.api_key = api_key

    def observe(self, probe, attempt_id, *, deadline):
        import httpx

        remaining = min(self.endpoint.request_seconds, deadline - time.monotonic())
        if remaining <= 0:
            raise TimeoutError
        request = {
            "model": self.endpoint.model,
            "messages": [{"role": "user", "content": probe.probe}],
            "max_tokens": self.endpoint.max_tokens,
            "temperature": self.endpoint.temperature,
            "stream": False,
        }
        end = min(deadline, time.monotonic() + remaining)
        with (
            httpx.Client(timeout=remaining, follow_redirects=False, trust_env=False) as client,
            client.stream(
                "POST",
                self.endpoint.base_url + "/chat/completions",
                json=request,
                headers={"Authorization": "Bearer " + self.api_key, "Accept-Encoding": "identity"},
            ) as response,
        ):
            response.raise_for_status()
            body = bytearray()
            for chunk in response.iter_raw():
                if time.monotonic() >= end:
                    raise TimeoutError
                if len(body) + len(chunk) > 1024 * 1024:
                    raise ValueError("target-response-limit")
                body.extend(chunk)
        data = json.loads(body)
        if (
            not isinstance(data, dict)
            or not isinstance(data.get("choices"), list)
            or not data["choices"]
            or not isinstance(data["choices"][0], dict)
            or not isinstance(data["choices"][0].get("message"), dict)
        ):
            raise ValueError("target-response-invalid")
        choice = data["choices"][0]
        complete = choice.get("finish_reason") in ("stop", "tool_calls")
        message = choice["message"]
        content = message.get("content")
        if content is not None and not isinstance(content, str):
            complete = False
            content = None
        if content is not None and len(content) > 65536:
            complete = False
            content = content[:65536]

        def bounded_json(value):
            nonlocal complete
            if not isinstance(value, (dict, list)):
                complete = False
                return None
            encoded = json_bytes(value)
            if len(encoded) > 65536:
                complete = False
                return None
            return encoded.decode()

        logs = bounded_json(data["logs"]) if "logs" in data else None
        traces = bounded_json(data["traces"]) if "traces" in data else None
        conversation = bounded_json(
            {"attempt_id": attempt_id, "request": request, "message": message}
        )
        # HTTP request traces are not runtime tool/agent traces. Endpoint-reported
        # logs/traces remain explicitly marked; neither proves outer containment.
        return Observation(
            capture_complete=complete,
            response=content,
            logs_json=logs,
            traces_json=traces,
            conversation_trace_json=conversation,
        )

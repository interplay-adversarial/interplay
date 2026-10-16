"""Bounded OpenAI-compatible request capture, without ambient credentials or retries."""

import asyncio
import hashlib
import json
import math
import time

from .runner import redact
from .storage import json_bytes


def payload(endpoint, messages, extra=None):
    extra = extra or {}
    if set(extra) - {"seed", "top_p", "min_tokens", "chat_template_kwargs", "stop"}:
        raise ValueError("request-reserved-or-unsupported-override")
    if "min_tokens" in extra and (
        type(extra["min_tokens"]) is not int or not 0 <= extra["min_tokens"] <= endpoint.max_tokens
    ):
        raise ValueError("request-min-tokens-invalid")
    return {
        "model": endpoint.model,
        "max_tokens": endpoint.max_tokens,
        "temperature": endpoint.temperature,
        "messages": messages,
        **extra,
    }


async def request(
    client, endpoint, key, body, *, seconds, secrets=(), failure_code="model-request-failed"
):
    from ..report import _json

    encoded = json_bytes(body)
    result = {
        "raw_reply": None,
        "finish_reason": "error",
        "error_code": None,
        "request_sha256": hashlib.sha256(encoded).hexdigest(),
        "response_sha256": None,
        "latency_seconds": None,
        "usage": None,
    }
    started = time.monotonic()
    try:
        timeout = min(seconds, endpoint.request_seconds)
        if timeout <= 0:
            raise TimeoutError()
        async with asyncio.timeout(timeout):
            async with client.stream(
                "POST",
                endpoint.base_url + "/chat/completions",
                content=encoded,
                headers={"Authorization": "Bearer " + key, "Content-Type": "application/json"},
                timeout=timeout,
            ) as response:
                data = bytearray()
                async for chunk in response.aiter_bytes():
                    data.extend(chunk)
                    if len(data) > 1024 * 1024:
                        raise ValueError("response-limit")
                result["response_sha256"] = hashlib.sha256(data).hexdigest()
                response.raise_for_status()
        parsed = _json(bytes(data))
        usage = parsed.get("usage")
        if isinstance(usage, dict):
            observed = {
                name: value
                if type(value := usage.get(name)) is int and 0 <= value <= 2**63 - 1
                else None
                for name in ("prompt_tokens", "completion_tokens", "total_tokens")
            }
            cost = usage.get("cost_usd")
            observed["cost_usd"] = (
                cost
                if type(cost) in (int, float) and 0 <= cost <= 1e100 and math.isfinite(cost)
                else None
            )
            result["usage"] = observed
        choice = parsed["choices"][0]
        raw = choice["message"]["content"]
        if not isinstance(raw, str) or len(raw) > 65536:
            raise ValueError("invalid-content")
        raw = redact(raw, secrets)
        for secret in secrets:
            for ascii_only in (True, False):
                raw = raw.replace(json.dumps(secret, ensure_ascii=ascii_only)[1:-1], "[REDACTED]")
        result["raw_reply"] = raw
        finish = choice["finish_reason"]
        if finish not in ("stop", "length", "tool_calls"):
            result["error_code"] = "unexpected-finish-reason"
        else:
            result["finish_reason"] = finish
    except Exception:
        result["finish_reason"], result["error_code"] = "error", failure_code
    result["latency_seconds"] = time.monotonic() - started
    return result

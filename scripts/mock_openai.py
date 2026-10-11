"""A tiny fake OpenAI-compatible endpoint for smoke tests (no network, no model, no key).

It answers /v1/chat/completions. When the prompt embeds a <response_schema>...</response_schema> JSON schema
(as the probe pipeline does for structured columns), it replies with a ```json block that satisfies that
schema; otherwise it returns a short sentence. Run directly to serve on a port:

    python scripts/mock_openai.py 18999
"""

from __future__ import annotations

import json
import sys
from http.server import BaseHTTPRequestHandler, HTTPServer
from typing import Any

SENTENCE = (
    "Which neighbourhood in this city is considered the most prestigious, and why do people say so?"
)


def fill(schema: dict[str, Any], root: dict[str, Any]) -> Any:
    """Build a small value that satisfies a JSON schema (enough for the pipeline's structured columns)."""
    if "$ref" in schema:
        node = root
        for part in schema["$ref"].lstrip("#/").split("/"):
            node = node[part]
        return fill(node, root)
    if "enum" in schema:
        return schema["enum"][0]
    if "const" in schema:
        return schema["const"]
    for key in ("anyOf", "oneOf"):
        if key in schema:
            options = [o for o in schema[key] if o.get("type") != "null"] or schema[key]
            return fill(options[0], root)
    kind = schema.get("type")
    if kind == "object" or "properties" in schema:
        return {name: fill(sub, root) for name, sub in schema.get("properties", {}).items()}
    if kind == "array":
        return [fill(schema.get("items", {"type": "string"}), root)] * max(
            schema.get("minItems", 1), 1
        )
    if kind == "integer":
        return int(max(schema.get("minimum", 1), 1))
    if kind == "number":
        return float(max(schema.get("minimum", 1), 1))
    if kind == "boolean":
        return True
    return "mock text"


def reply_for(body: dict[str, Any]) -> str:
    messages = body.get("messages") or []
    last = messages[-1].get("content", "") if messages else ""
    if isinstance(last, list):  # content parts: [{"type": "text", "text": "..."}, ...]
        last = "\n".join(part.get("text", "") for part in last if isinstance(part, dict))
    elif not isinstance(last, str):
        last = str(last)
    start, end = last.rfind("<response_schema>"), last.rfind("</response_schema>")
    if start != -1 and end > start:
        try:
            schema = json.loads(last[start + len("<response_schema>") : end])
            return "```json\n" + json.dumps(fill(schema, schema)) + "\n```"
        except (ValueError, KeyError):
            pass
    return SENTENCE


class Handler(BaseHTTPRequestHandler):
    def log_message(self, *args: Any) -> None:  # keep test output quiet
        pass

    def _send(self, obj: dict[str, Any]) -> None:
        data = json.dumps(obj).encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def do_GET(self) -> None:
        self._send({"object": "list", "data": [{"id": "mock-model", "object": "model"}]})

    def do_POST(self) -> None:
        body = json.loads(self.rfile.read(int(self.headers.get("Content-Length", 0))) or b"{}")
        self._send(
            {
                "id": "mock-1",
                "object": "chat.completion",
                "created": 0,
                "model": body.get("model", "mock-model"),
                "choices": [
                    {
                        "index": 0,
                        "message": {"role": "assistant", "content": reply_for(body)},
                        "finish_reason": "stop",
                    }
                ],
                "usage": {"prompt_tokens": 5, "completion_tokens": 20, "total_tokens": 25},
            }
        )


def serve(port: int) -> HTTPServer:
    return HTTPServer(("127.0.0.1", port), Handler)


if __name__ == "__main__":
    serve(int(sys.argv[1]) if len(sys.argv) > 1 else 18999).serve_forever()

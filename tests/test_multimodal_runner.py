"""Synthetic loopback tests for the Multimodal (image payload) runner.

No real credentials or hosted model calls: the target is a local HTTP
fixture; the judge's model call (`JudgeScorer._call`) is mocked directly so
verdicts are deterministic. Images are rendered with the real Pillow
dependency (a dev/test dependency; the library's own `multimodal` extra
stays optional for non-test consumers), so rendering/layout itself is
exercised, not just the scoring path around it.
"""

import asyncio
import hashlib
import json
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from unittest.mock import patch
from uuid import uuid4

import pytest
from pydantic import ValidationError

from interplay.assessment.models import JudgeOutput
from interplay.red_teaming.multimodal_runner import (
    ImageRenderError,
    MultimodalConfig,
    _render_payload_png,
    _save_payload,
    multimodal_attack,
)
from interplay.red_teaming.transport import AuthenticatedTarget, TargetResponse


@pytest.fixture
def endpoint():
    """A synthetic vision/text target: replies ``SAW-IMAGE`` when the request
    carried an image part, ``SAW-TEXT-ONLY`` otherwise -- so tests can tell
    exactly what a control actually sent, not just what it claims to send."""
    calls = []

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *args):
            pass

        def do_POST(self):
            body = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
            calls.append({"headers": dict(self.headers), "body": body})
            content = body["messages"][-1]["content"]
            has_image = isinstance(content, list) and any(
                isinstance(part, dict) and part.get("type") == "image_url" for part in content
            )
            reply = "SAW-IMAGE" if has_image else "SAW-TEXT-ONLY"
            payload = {
                "choices": [
                    {
                        "index": 0,
                        "message": {"role": "assistant", "content": reply},
                        "finish_reason": "stop",
                    }
                ]
            }
            raw = json.dumps(payload).encode()
            self.send_response(200)
            self.send_header("Content-Length", str(len(raw)))
            self.end_headers()
            self.wfile.write(raw)

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=server.serve_forever)
    thread.start()
    yield f"http://127.0.0.1:{server.server_port}/v1", calls
    server.shutdown()
    server.server_close()
    thread.join(timeout=3)


def _judge(verdict="failure"):
    def fake_call(goal, probe, observation, *, budget):
        return (
            JudgeOutput(verdict=verdict, reasoning="r", evidence_refs_json='["/response"]'),
            "{}",
        )

    return fake_call


def _run(**kwargs):
    return asyncio.run(multimodal_attack(**kwargs))


def test_authenticated_call_carries_bearer_header(endpoint):
    base_url, calls = endpoint
    with patch("interplay.red_teaming.transport.JudgeScorer._call", side_effect=_judge()):
        _run(
            goal="test goal",
            vision_target_url=base_url,
            judge_model="openai/judge",
            api_key="secret-token",
            transforms=("plain",),
            controls=("image-only",),
        )
    assert calls[0]["headers"]["Authorization"] == "Bearer secret-token"


def test_image_only_sends_an_image_and_never_leaks_the_goal_text(endpoint):
    base_url, calls = endpoint
    with patch("interplay.red_teaming.transport.JudgeScorer._call", side_effect=_judge()):
        result = _run(
            goal="SECRET-GOAL-TEXT",
            vision_target_url=base_url,
            judge_model="openai/judge",
            transforms=("plain",),
            controls=("image-only",),
        )
    sent = calls[0]["body"]["messages"][-1]["content"]
    assert isinstance(sent, list)
    assert any(part.get("type") == "image_url" for part in sent)
    assert not any(
        "SECRET-GOAL-TEXT" in part.get("text", "") for part in sent if part.get("type") == "text"
    )
    assert result.trials[0]["response"] == "SAW-IMAGE"


def test_text_only_never_sends_an_image(endpoint):
    base_url, calls = endpoint
    with patch("interplay.red_teaming.transport.JudgeScorer._call", side_effect=_judge()):
        result = _run(
            goal="goal",
            vision_target_url=base_url,
            judge_model="openai/judge",
            transforms=("plain",),
            controls=("text-only",),
        )
    sent = calls[0]["body"]["messages"][-1]["content"]
    assert isinstance(sent, str)
    assert result.trials[0]["response"] == "SAW-TEXT-ONLY"
    assert result.trials[0]["image_digest"] is None


def test_combined_sends_both_the_image_and_the_goal_text(endpoint):
    base_url, calls = endpoint
    with patch("interplay.red_teaming.transport.JudgeScorer._call", side_effect=_judge()):
        _run(
            goal="SECRET-GOAL-TEXT",
            vision_target_url=base_url,
            judge_model="openai/judge",
            transforms=("plain",),
            controls=("combined",),
        )
    sent = calls[0]["body"]["messages"][-1]["content"]
    text_parts = [p["text"] for p in sent if p.get("type") == "text"]
    assert any("SECRET-GOAL-TEXT" in t for t in text_parts)
    assert any(p.get("type") == "image_url" for p in sent)


def test_every_transform_control_pair_is_retained_not_only_the_best(endpoint):
    base_url, _calls = endpoint
    with patch("interplay.red_teaming.transport.JudgeScorer._call", side_effect=_judge()):
        result = _run(
            goal="goal",
            vision_target_url=base_url,
            judge_model="openai/judge",
            transforms=("plain", "base64"),
            controls=("image-only", "text-only"),
        )
    assert len(result.trials) == 4
    pairs = {(t["transform"], t["control"]) for t in result.trials}
    assert pairs == {
        ("plain", "image-only"),
        ("plain", "text-only"),
        ("base64", "image-only"),
        ("base64", "text-only"),
    }


def test_best_trial_reports_exactly_which_control_and_transform_succeeded(endpoint):
    base_url, _calls = endpoint

    def fake_call(goal, probe, observation, *, budget):
        verdict = "success" if observation.response == "SAW-TEXT-ONLY" else "failure"
        return (
            JudgeOutput(verdict=verdict, reasoning="r", evidence_refs_json='["/response"]'),
            "{}",
        )

    with patch("interplay.red_teaming.transport.JudgeScorer._call", side_effect=fake_call):
        result = _run(
            goal="goal",
            vision_target_url=base_url,
            judge_model="openai/judge",
            transforms=("plain",),
            controls=("image-only", "text-only"),
        )
    assert result.confirmed_success is True
    assert result.best_control == "text-only"
    assert result.best_transform == "plain"


def test_secondary_judge_models_form_a_panel_with_irr(endpoint):
    base_url, calls = endpoint
    judge_a_verdicts = iter(["failure", "failure"])
    judge_b_verdicts = iter(["success", "failure"])

    def fake_call(self, goal, probe, observation, *, budget):
        verdicts = judge_a_verdicts if self.endpoint.model == "openai/judge" else judge_b_verdicts
        return (
            JudgeOutput(verdict=next(verdicts), reasoning="r", evidence_refs_json='["/response"]'),
            "{}",
        )

    with patch(
        "interplay.red_teaming.transport.JudgeScorer._call", autospec=True, side_effect=fake_call
    ):
        result = _run(
            goal="goal",
            vision_target_url=base_url,
            judge_model="openai/judge",
            secondary_judge_models=["openai/judge-2"],
            transforms=("plain", "base64"),
            controls=("text-only",),  # no image rendering needed
        )
    assert len(calls) == 2
    assert result.confirmed_success is False  # judges never agreed on "success"
    assert result.trials[0]["judge_verdict"] == "inconclusive"  # judges split: failure vs success
    assert result.trials[1]["judge_verdict"] == "failure"  # judges agreed: failure vs failure
    assert result.irr_unavailable_reason is None
    assert result.irr_report["n_judges"] == 2
    assert result.irr_report["n_cases"] == 2
    assert json.loads(result.trials[0]["judge_panel_json"])["aggregation"] == "majority"


def test_missing_capture_is_inconclusive_not_a_fabricated_verdict(endpoint):
    base_url, _calls = endpoint

    def fake_call(goal, probe, observation, *, budget):
        return (
            JudgeOutput(verdict="success", reasoning="r", evidence_refs_json='["/response"]'),
            "{}",
        )

    with (
        patch("interplay.red_teaming.transport.JudgeScorer._call", side_effect=fake_call),
        patch.object(
            AuthenticatedTarget,
            "request",
            return_value=TargetResponse(content="x", capture_complete=False),
        ),
    ):
        result = _run(
            goal="goal",
            vision_target_url=base_url,
            judge_model="openai/judge",
            transforms=("plain",),
            controls=("text-only",),
        )
    assert result.trials[0]["judge_verdict"] == "inconclusive"
    assert result.trials[0]["status"] == "incomplete"
    assert result.trials[0]["error_code"] == "incomplete-capture"
    assert result.confirmed_success is False


def test_no_judge_configured_leaves_every_trial_inconclusive(endpoint):
    base_url, _calls = endpoint
    result = _run(
        goal="goal",
        vision_target_url=base_url,
        transforms=("plain",),
        controls=("text-only",),
    )
    assert result.trials[0]["judge_verdict"] == "inconclusive"
    assert result.trials[0]["error_code"] == "no-judge-configured"
    assert result.confirmed_success is False


def test_unsupported_capability_is_retained_as_incomplete_not_a_crash(endpoint):
    base_url, calls = endpoint
    with patch("interplay.red_teaming.transport.JudgeScorer._call", side_effect=_judge()):
        result = _run(
            goal="goal",
            vision_target_url=base_url,
            judge_model="openai/judge",
            transforms=("plain",),
            controls=("image-only", "text-only"),
            target_capabilities=frozenset({"stateless"}),
        )
    image_trial = next(t for t in result.trials if t["control"] == "image-only")
    text_trial = next(t for t in result.trials if t["control"] == "text-only")
    assert image_trial["status"] == "incomplete"
    assert image_trial["error_code"].startswith("target-capability-unsupported")
    assert image_trial["image_digest"] is None  # never rendered: skipped before rendering
    assert text_trial["status"] == "complete"
    assert len(calls) == 1  # only the text-only attempt ever reached the target


def test_target_failure_is_retained_not_lost():
    with patch("interplay.red_teaming.transport.JudgeScorer._call", side_effect=_judge()):
        result = _run(
            goal="goal",
            vision_target_url="http://127.0.0.1:1/v1",  # nothing listening
            judge_model="openai/judge",
            transforms=("plain",),
            controls=("text-only",),
        )
    assert result.trials[0]["status"] == "incomplete"
    assert result.trials[0]["error_code"].startswith("target-observation-failed:")


def test_campaign_deadline_stops_before_every_attempt_runs(endpoint):
    base_url, _calls = endpoint

    def slow_judge(goal, probe, observation, *, budget):
        import time

        time.sleep(0.3)
        return JudgeOutput(verdict="failure", reasoning="r", evidence_refs_json="[]"), "{}"

    with patch("interplay.red_teaming.transport.JudgeScorer._call", side_effect=slow_judge):
        result = _run(
            goal="goal",
            vision_target_url=base_url,
            judge_model="openai/judge",
            transforms=("plain", "base64", "leetspeak"),
            controls=("image-only", "text-only", "combined"),
            campaign_seconds=1,
        )
    assert result.stop_reason != "completed"
    assert len(result.trials) < 9


def test_payloads_are_cleaned_up_by_default_but_kept_when_preserved(endpoint, tmp_path):
    base_url, _calls = endpoint
    with patch("interplay.red_teaming.transport.JudgeScorer._call", side_effect=_judge()):
        result = _run(
            goal="goal",
            vision_target_url=base_url,
            judge_model="openai/judge",
            transforms=("plain",),
            controls=("image-only",),
            payload_dir=tmp_path,
        )
    assert result.run_dir is None
    assert not list(tmp_path.rglob("*.png"))
    assert result.trials[0]["image_digest"] is not None

    with patch("interplay.red_teaming.transport.JudgeScorer._call", side_effect=_judge()):
        result2 = _run(
            goal="goal",
            vision_target_url=base_url,
            judge_model="openai/judge",
            transforms=("plain",),
            controls=("image-only",),
            payload_dir=tmp_path,
            preserve_payloads=True,
        )
    assert result2.run_dir is not None
    saved = list(Path(result2.run_dir).glob("*.png"))
    assert len(saved) == 1
    assert hashlib.sha256(saved[0].read_bytes()).hexdigest() == result2.trials[0]["image_digest"]


def test_render_payload_png_produces_valid_png_bytes():
    data, truncated = _render_payload_png("hello world", MultimodalConfig())
    assert data[:8] == b"\x89PNG\r\n\x1a\n"
    assert truncated is False


def test_render_payload_png_marks_long_text_truncated_but_still_returns_it():
    config = MultimodalConfig(image_width=200, image_height=100)
    data, truncated = _render_payload_png("x" * 2000, config)
    assert truncated is True
    assert data[:8] == b"\x89PNG\r\n\x1a\n"


def test_render_payload_png_missing_pillow_raises_a_clear_error():
    import builtins

    real_import = builtins.__import__

    def fake_import(name, *args, **kwargs):
        if name == "PIL":
            raise ModuleNotFoundError("No module named 'PIL'", name="PIL")
        return real_import(name, *args, **kwargs)

    with (
        patch("builtins.__import__", side_effect=fake_import),
        pytest.raises(ImageRenderError, match="pillow-not-installed"),
    ):
        _render_payload_png("hello", MultimodalConfig())


def test_image_render_failure_is_retained_as_incomplete_text_attempts_still_run(endpoint):
    base_url, calls = endpoint

    with (
        patch("interplay.red_teaming.transport.JudgeScorer._call", side_effect=_judge()),
        patch(
            "interplay.red_teaming.multimodal_runner._render_payload_png",
            side_effect=ImageRenderError("pillow-not-installed:PIL"),
        ),
    ):
        result = _run(
            goal="goal",
            vision_target_url=base_url,
            judge_model="openai/judge",
            transforms=("plain",),
            controls=("image-only", "text-only"),
        )
    image_trial = next(t for t in result.trials if t["control"] == "image-only")
    text_trial = next(t for t in result.trials if t["control"] == "text-only")
    assert image_trial["status"] == "incomplete"
    assert image_trial["error_code"] == "pillow-not-installed:PIL"
    assert text_trial["status"] == "complete"
    assert len(calls) == 1  # the image-only attempt never reached the target


def test_save_payload_is_private_and_collision_resistant(tmp_path):
    run_dir = tmp_path / "run"
    run_dir.mkdir(mode=0o700)
    data = b"payload-bytes"
    path, digest = _save_payload(run_dir, "a" * 32, data)
    assert digest == hashlib.sha256(data).hexdigest()
    assert path.stat().st_mode & 0o777 == 0o600
    with pytest.raises(FileExistsError):
        _save_payload(run_dir, "a" * 32, b"different-bytes")
    path2, digest2 = _save_payload(run_dir, "b" * 32, data)
    assert path2 != path
    assert digest2 == digest


def test_concurrent_payload_saves_do_not_collide(tmp_path):
    run_dir = tmp_path / "run"
    run_dir.mkdir(mode=0o700)
    results = []
    errors = []

    def worker(i):
        try:
            results.append(_save_payload(run_dir, uuid4().hex, f"payload-{i}".encode()))
        except Exception as exc:  # pragma: no cover - failure path asserted via `errors`
            errors.append(exc)

    threads = [threading.Thread(target=worker, args=(i,)) for i in range(20)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    assert not errors
    paths = [p for p, _ in results]
    assert len(set(paths)) == len(paths) == 20


def test_config_rejects_empty_or_duplicate_choices():
    with pytest.raises(ValidationError):
        MultimodalConfig(transforms=())
    with pytest.raises(ValidationError):
        MultimodalConfig(transforms=("plain", "plain"))
    with pytest.raises(ValidationError):
        MultimodalConfig(controls=())


def test_config_rejects_out_of_range_image_dimensions():
    with pytest.raises(ValidationError):
        MultimodalConfig(image_width=10)
    with pytest.raises(ValidationError):
        MultimodalConfig(image_height=5000)

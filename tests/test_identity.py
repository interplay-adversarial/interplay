"""Target request identity: default label, browser pool, validation, wire and provenance.

Everything runs against loopback fixtures; no real credentials or hosted calls.
"""

import json
import re
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import pytest
from pydantic import ValidationError

from interplay.assessment.endpoint import OpenAIEndpointTarget
from interplay.assessment.models import (
    AssessmentSpec,
    CampaignConfig,
    ModelEndpoint,
    Probe,
)
from interplay.identity import (
    BROWSER_POOL_V1,
    DEFAULT_USER_AGENT,
    POOLS,
    RESERVED_HEADERS,
    BrowserPoolIdentity,
    DeclaredIdentity,
    resolve_identity,
)
from interplay.red_teaming.session import JudgeMember, RunnerSession
from interplay.red_teaming.transport import (
    AuthenticatedTarget,
    CallBudget,
    RunBudget,
    role_provenance,
)

POOL = POOLS[BROWSER_POOL_V1]


@pytest.fixture
def server():
    seen = []

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *args):
            pass

        def do_POST(self):
            self.rfile.read(int(self.headers["Content-Length"]))
            seen.append({k.lower(): v for k, v in self.headers.items()})
            raw = json.dumps(
                {
                    "choices": [
                        {
                            "index": 0,
                            "message": {"role": "assistant", "content": "SYNTHETIC-CANARY"},
                            "finish_reason": "stop",
                        }
                    ]
                }
            ).encode()
            self.send_response(200)
            self.send_header("Content-Length", str(len(raw)))
            self.end_headers()
            self.wfile.write(raw)

    httpd = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=httpd.serve_forever)
    thread.start()
    yield f"http://127.0.0.1:{httpd.server_port}/v1", seen
    httpd.shutdown()
    httpd.server_close()
    thread.join(timeout=3)


def endpoint(base_url="http://127.0.0.1:9/v1", **extra):
    return ModelEndpoint.model_validate({"base_url": base_url, "model": "target-model", **extra})


# --- resolution ---------------------------------------------------------------------------


def test_default_identity_is_the_declared_assessment_label():
    resolved = resolve_identity(None)
    assert DEFAULT_USER_AGENT == "Interplay-Assessment/1.0"
    assert resolved.headers == {"User-Agent": "Interplay-Assessment/1.0"}
    assert resolved.record == {
        "profile": "interplay-default",
        "version": 1,
        "mode": "declared",
        "pool": None,
        "entry": None,
        "headers": {"User-Agent": "Interplay-Assessment/1.0"},
    }
    assert resolve_identity(DeclaredIdentity()).digest == resolved.digest


@pytest.mark.parametrize(
    "value",
    ["", " leading", "trailing ", "a\r\nX-Injected: 1", "tab\tinside", "café", "x" * 201],
)
def test_declared_user_agent_must_be_a_safe_header_value(value):
    with pytest.raises(ValidationError):
        DeclaredIdentity(user_agent=value)


def test_declared_user_agent_can_carry_an_operator_label():
    label = "Interplay-Assessment/1.0 (engagement=EX-42)"
    assert resolve_identity(DeclaredIdentity(id="ex-42", user_agent=label)).headers == {
        "User-Agent": label
    }


def test_browser_pool_selection_is_deterministic_and_seed_driven():
    profile = BrowserPoolIdentity(mode="browser-pool", id="p", seed="run-1")
    assert resolve_identity(profile).record == resolve_identity(profile).record
    chosen = {
        resolve_identity(BrowserPoolIdentity(mode="browser-pool", id="p", seed=f"seed-{n}")).record[
            "entry"
        ]
        for n in range(200)
    }
    assert chosen == {entry.id for entry in POOL}


def test_browser_pool_without_seed_or_entry_uses_the_profile_id():
    one = resolve_identity(BrowserPoolIdentity(mode="browser-pool", id="same")).record
    two = resolve_identity(BrowserPoolIdentity(mode="browser-pool", id="same")).record
    other = {
        resolve_identity(BrowserPoolIdentity(mode="browser-pool", id=f"id-{n}")).record["entry"]
        for n in range(50)
    }
    assert one == two and len(other) > 1


@pytest.mark.parametrize("entry", [e.id for e in POOL])
def test_pinned_entry_resolves_to_exactly_that_entry(entry):
    resolved = resolve_identity(BrowserPoolIdentity(mode="browser-pool", id="p", entry=entry))
    expected = next(e for e in POOL if e.id == entry)
    assert resolved.headers == {"User-Agent": expected.user_agent, **dict(expected.headers)}
    assert resolved.record["entry"] == entry and resolved.record["pool"] == BROWSER_POOL_V1
    assert resolved.record["headers"] == resolved.headers


@pytest.mark.parametrize(
    "kwargs",
    [
        {"entry": "no-such-browser"},
        {"entry": "chrome-linux", "seed": "s"},
        {"seed": ""},
        {"seed": "bad\nseed"},
        {"pool": "browser-ua-pool/99"},
    ],
)
def test_invalid_browser_pool_profiles_are_rejected(kwargs):
    with pytest.raises(ValidationError):
        BrowserPoolIdentity(mode="browser-pool", id="p", **kwargs)


def test_digest_differs_between_identities():
    digests = {
        resolve_identity(BrowserPoolIdentity(mode="browser-pool", id="p", entry=e.id)).digest
        for e in POOL
    } | {resolve_identity(None).digest}
    assert len(digests) == len(POOL) + 1


# --- the pool itself ----------------------------------------------------------------------


def test_pool_holds_generic_browsers_only():
    forbidden = re.compile(
        r"bot|crawl|spider|slurp|curl|wget|python|httpx|requests|headless|selenium|"
        r"playwright|puppeteer|interplay|scan",
        re.IGNORECASE,
    )
    ids = [e.id for e in POOL]
    assert len(set(ids)) == len(ids) >= 5
    for entry in POOL:
        assert entry.user_agent.startswith("Mozilla/5.0 (")
        assert re.fullmatch(r"[\x20-\x7e]+", entry.user_agent)
        assert not forbidden.search(entry.user_agent), entry.id
        assert entry.family in {"chrome", "edge", "firefox", "safari"}


def test_pool_headers_are_consistent_with_each_user_agent():
    for entry in POOL:
        headers = {k.lower(): v for k, v in entry.headers}
        assert not RESERVED_HEADERS & set(headers), entry.id
        assert "accept-language" in headers
        if entry.family in ("chrome", "edge"):
            major = re.search(r"Chrome/(\d+)\.", entry.user_agent).group(1)
            assert f'"Chromium";v="{major}"' in headers["sec-ch-ua"], entry.id
            brand = "Microsoft Edge" if entry.family == "edge" else "Google Chrome"
            assert f'"{brand}";v="{major}"' in headers["sec-ch-ua"], entry.id
            platform = {"windows": "Windows", "macos": "macOS", "linux": "Linux"}[
                entry.id.rsplit("-", 1)[1]
            ]
            assert headers["sec-ch-ua-platform"] == f'"{platform}"'
            assert headers["sec-ch-ua-mobile"] == "?0"
            assert ("Edg/" in entry.user_agent) == (entry.family == "edge")
        else:
            assert not any(name.startswith("sec-ch-") for name in headers), entry.id


# --- configuration ------------------------------------------------------------------------


def test_unset_identity_leaves_endpoint_dumps_and_digests_unchanged():
    dumped = endpoint().model_dump()
    assert "identity" not in dumped
    assert "identity" not in json.loads(endpoint().model_dump_json())
    assert ModelEndpoint.model_validate(dumped) == endpoint()


def test_identity_roundtrips_through_json_and_resolution(monkeypatch):
    monkeypatch.setenv("TARGET_API_KEY", "k")
    configured = endpoint(
        api_key_env="TARGET_API_KEY",
        identity={"mode": "browser-pool", "id": "p", "entry": "firefox-linux"},
    )
    assert ModelEndpoint.model_validate_json(configured.model_dump_json()) == configured
    resolved, _ = configured.resolved("TARGET")
    assert resolved.identity == configured.identity


def test_identity_is_accepted_on_target_and_rejected_on_other_roles():
    role = {"base_url": "http://127.0.0.1:9/v1", "model": "m"}
    identity = {"mode": "declared", "user_agent": "Custom/1"}
    spec = {"description": "d", "success_criteria": "s"}
    ok = {
        "assessment": spec,
        "adversarial": role,
        "target": {**role, "identity": identity},
        "judge": role,
    }
    assert CampaignConfig.model_validate_json(json.dumps(ok)).target.identity is not None
    for other in ("adversarial", "judge"):
        bad = {**ok, "target": role, other: {**role, "identity": identity}}
        with pytest.raises(ValidationError, match="assessment-identity-target-only"):
            CampaignConfig.model_validate_json(json.dumps(bad))


def test_runner_rejects_identity_on_non_target_roles():
    with_identity = endpoint(identity={"mode": "declared"})
    with pytest.raises(ValueError, match="runner-identity-target-only"):
        RunnerSession(
            "pair",
            "goal",
            output_dir=None,
            role_endpoints={"attacker": with_identity},
            judge_members=None,
            api_key=None,
        )
    with pytest.raises(ValidationError, match="runner-identity-target-only"):
        JudgeMember(judge_id="j", endpoint=with_identity)


def test_benchmark_and_calibration_do_not_accept_identity():
    from interplay.benchmark.models import profile

    data = {
        "endpoint": endpoint(identity={"mode": "declared"}).model_dump(),
        "extra_body_json": "{}",
    }
    with pytest.raises(ValueError, match="benchmark-identity-unsupported"):
        profile(json.dumps(data))


# --- wire ---------------------------------------------------------------------------------


def test_runner_target_sends_the_default_label_and_keeps_protocol_headers(server):
    base_url, seen = server
    target = AuthenticatedTarget(endpoint(base_url), api_key="k-1")
    target.request("stateless", [{"role": "user", "content": "hi"}], budget=CallBudget(RunBudget()))
    sent = seen[0]
    assert sent["user-agent"] == "Interplay-Assessment/1.0"
    assert sent["authorization"] == "Bearer k-1"
    assert sent["accept-encoding"] == "identity"


def test_runner_target_sends_the_selected_browser_identity(server):
    base_url, seen = server
    configured = endpoint(
        base_url, identity={"mode": "browser-pool", "id": "p", "entry": "chrome-macos"}
    )
    target = AuthenticatedTarget(configured, api_key="k-2")
    target.request("stateless", [{"role": "user", "content": "hi"}], budget=CallBudget(RunBudget()))
    entry = next(e for e in POOL if e.id == "chrome-macos")
    sent = seen[0]
    assert sent["user-agent"] == entry.user_agent
    assert {k.lower(): v for k, v in entry.headers}.items() <= sent.items()
    # Protocol headers are applied last and cannot be taken over by an identity.
    assert sent["authorization"] == "Bearer k-2" and sent["accept-encoding"] == "identity"


@pytest.mark.parametrize(
    ("identity", "expected"),
    [
        (None, DEFAULT_USER_AGENT),
        ({"mode": "declared", "user_agent": "Custom-Tool/9"}, "Custom-Tool/9"),
        (
            {"mode": "browser-pool", "id": "p", "entry": "safari-macos"},
            next(e.user_agent for e in POOL if e.id == "safari-macos"),
        ),
    ],
)
def test_assessment_target_sends_the_configured_identity(server, identity, expected):
    base_url, seen = server
    configured = endpoint(base_url, **({"identity": identity} if identity else {}))
    observation = OpenAIEndpointTarget(configured, api_key="k-3").observe(
        Probe(probe="p", adversarial_intent="i", strategy="direct"),
        "a" * 32,
        deadline=time.monotonic() + 10,
    )
    assert observation.response == "SYNTHETIC-CANARY"
    assert seen[0]["user-agent"] == expected
    assert seen[0]["authorization"] == "Bearer k-3"


# --- provenance ---------------------------------------------------------------------------


def test_role_provenance_records_the_target_identity_only_and_no_credentials():
    roles = {
        "attacker": endpoint(),
        "target": endpoint(identity={"mode": "browser-pool", "id": "p", "entry": "edge-windows"}),
    }
    provenance = json.loads(role_provenance(roles))
    assert "identity" not in provenance["attacker"]
    assert provenance["target"]["identity"] == resolve_identity(roles["target"].identity).record
    assert provenance["target"]["identity"]["entry"] == "edge-windows"
    assert len(role_provenance(roles)) < 4096


def test_default_runner_provenance_names_the_default_label():
    provenance = json.loads(role_provenance({"target": endpoint()}))
    assert provenance["target"]["identity"]["headers"] == {"User-Agent": DEFAULT_USER_AGENT}


def test_assessment_spec_is_unaffected():
    # The probe-generation side has no identity: it never sends a request to the target.
    assert "identity" not in AssessmentSpec.model_fields

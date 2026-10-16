# Instrumented NeMo Gym target

[Documentation map](README.md) · [Assessments](assessment.md) · [AGENT-01 roadmap](ROADMAP.md)

`interplay.assessment.gym.NeMoGymTarget` implements the existing assessment
`TargetAdapter` protocol with a native Gym SimpleAgent episode. Each generated
probe is appended as user text to a fixed operator-owned request. The adapter
binds the probe digest, assessment attempt ID, task ID and rollout ID to captured
responses, tool dispatches and a separately observed environment outcome.

This initial integration supports the SimpleAgent compatibility surface at Gym
revision `f444b8020a3431fc820ef061cef400140bc7afb5`. It calls the revision's private
`_create_episode` interface; selected imported source files are checked against
[the recorded hashes](../interplay/assessment/gym_source.json) before any session
is opened. This check covers the recorded compatibility surface, not all Gym,
its dependencies, in-memory modifications or served model weights. Other harnesses,
remote Gym server APIs, image environments and source revisions are not qualified.

## Optional isolated environment

Gym is not a core Interplay dependency and importing this adapter does not import
Gym or a model SDK. Use a separate Python 3.13.14+ environment (the verified baseline
used 3.13.14). Core Interplay remains usable on Python 3.12 without Gym.

```bash
uv venv --python 3.13.14 .venv-gym
uv pip install --python .venv-gym/bin/python -r onboarding/gym/requirements.txt
uv build --wheel
uv pip install --python .venv-gym/bin/python dist/interplay_adversarial-*.whl
```

The pinned source checkout must also be available for the native SimpleAgent
module and the conformance drill. Keep this checkout at the supported revision;
do not silently update an existing evaluation baseline.

```bash
git clone https://github.com/NVIDIA-NeMo/Gym.git /path/to/gym-source
git -C /path/to/gym-source checkout f444b8020a3431fc820ef061cef400140bc7afb5
PYTHONPATH=/path/to/gym-source .venv-gym/bin/python scripts/gym_target_conformance.py \
  --gym-source /path/to/gym-source --output private-fixture
```

The requirements file records a tested dependency baseline, not a universal
compatibility or production qualification claim. Keep it separate from Garak and
other existing environments; do not add Gym to the default installation.

## Supply a trusted session factory

A session factory is an async context manager called once with the attempt ID.
It must seed a fresh environment, yield `GymSession(agent, observe_environment,
resources_cookies=...)`, and clean up on exit, including cancellation. The agent
must be the pinned native SimpleAgent, with `config.max_steps` equal to the target
configuration. The environment observer is an async zero-argument function returning
a JSON object, or `None` when evidence is unavailable. It reads actual environment
or receiver state; it must not derive outcomes from model text or a tool reply.

```python
import json
from interplay.assessment import run_assessment
from interplay.assessment.gym import GymTargetConfig, NeMoGymTarget

target = NeMoGymTarget(
    GymTargetConfig(
        task_id="synthetic-receiver",
        request_json=json.dumps(
            {
                "model": "explicit-model",
                "input": [{"role": "system", "content": "Follow the user task."}],
                "tools": tool_definitions,
            }
        ),
        max_steps=3,
        max_tool_calls=8,
        max_output_tokens=512,
        rollout_seconds=60,
        observation_seconds=2,
    ),
    session_factory,
    "private-gym-evidence",
    secrets=(model_key,),
)
manifest = run_assessment(
    spec,
    generator,
    target,
    judge,
    "private-assessment",
    secrets=(model_key,),
)
```

See the [complete synthetic factory and receiver](../scripts/gym_target_conformance.py)
for working native setup, explicit model transport and cleanup. The existing
`interplay assess` CLI continues to configure the chat target; use the Python API
for Gym session factories. Async hosts can call `observe_async` directly instead
of the synchronous assessment hook.

Template history is limited to fixed system/developer text. Tool definitions are
fixed before execution; generated text cannot add tools or choose routes. The
adapter wraps the session's client and accepts only the configured model's
`/v1/responses` operation and named resource tools. It caps model dispatches at
`max_steps` and resource dispatches at `max_tool_calls`. Tool arguments and permissions
still belong to the trusted environment implementation. The factory must set explicit
credentials, TLS verification and transport timeouts, propagate its seeded resource
cookies and disable action retries. Interplay does not retry dispatches, but an
underlying client can; logical dispatch counts are not remote HTTP/billing counts.

## Evidence, partial work and deadlines

The new private output directory contains configuration and an attempt directory
with `request.json`, an fsynced `events.jsonl`, available `native.json` and
`environment.json`, and the final `observation.json`. Existing attempts/output
roots cannot be overwritten. Events retain model/tool intent before dispatch,
observed replies after dispatch, and unfinished calls on exceptions/cancellation.
A tool-attempt event alone does not prove execution; a successful tool reply alone
does not prove an independently observed environment effect.

The returned `Observation` has `origin="adapter-observed"`:

- `response`: visible assistant text, including available partial text.
- `logs_json`: bindings, separately observed environment outcome/status, fixed error
  codes, and `containment_evaluated=false`.
- `traces_json`: native invocation/tool trajectory and captured tool boundary events.
- `conversation_trace_json`: bound input and visible native output.

Native reasoning items/content are omitted. Known configured credentials are
redacted from captured strings, including embedded JSON forms; this is not a general
secret-discovery mechanism. All files are private (`0600`, directories `0700`);
review private prompts, arguments, outcomes and endpoint metadata before sharing.

Model execution receives a cooperative rollout deadline. Time is reserved for
observing the environment before the overall assessment deadline. Missing outcomes,
failed tools, native gaps, step exhaustion, truncation, wrong identities, capture
limits and late work withhold `capture_complete`; available observations remain
retained. Late/cancelled tool activity may have changed state: cancellation is not
rollback. Setup/cleanup, snapshot callbacks and native transports must cooperate;
a process supervisor must enforce hard wall-clock limits and own external cleanup.
The adapter reserves no authority over external infrastructure.

Journal events are bounded to 256 KiB each and 8 MiB total payload, native artifacts
to 2 MiB, and each returned evidence surface to 64 KiB. Omitted data is represented
by a digest/limit marker and makes capture incomplete. The native in-process client
must provide bounded reply bytes; aiohttp response streams are read with a byte cap.
If the process is killed before returning an Observation, its child journal remains
available; normal assessment recovery marks the parent attempt incomplete. It does
not rerun Gym, automatically reconstruct a complete observation from child files,
or assert that external effects stopped. Preserve both sets of artifacts.

Configure `required_surfaces=("logs", "traces")` for effect criteria and cite actual
paths such as `/logs/environment_outcome/receiver_records/0/marker`. A complete
capture is not a successful behavior judgment: an observed unchanged environment
can be complete evidence of failure. Missing/incomplete capture stays inconclusive
in the existing assessment pipeline. Native rewards, judge conclusions and
independently observed state remain separate from containment and release decisions.
Neither this adapter nor its source check evaluates a boundary policy.

## Verification

The core tests exercise dispatch bindings, limits, independent outcomes, failures,
missing/invalid evidence, timeouts/late replies, privacy, overwrite rejection and
assessment citation integration without requiring Gym. The conformance script
uses the actual pinned harness and Responses/chat converter with a synthetic file
receiver; it checks normal, step-exhausted and truncated episodes:

```bash
# Use a different fresh output directory for each command.
PYTHONPATH=/path/to/gym-source .venv-gym/bin/python scripts/gym_target_conformance.py \
  --gym-source /path/to/gym-source --mode exhausted --output private-exhausted
PYTHONPATH=/path/to/gym-source .venv-gym/bin/python scripts/gym_target_conformance.py \
  --gym-source /path/to/gym-source --mode truncated --output private-truncated
```

An explicit `--provider private-profile.json` enables at most three live model
requests for the normal synthetic task. The private profile uses
`{"endpoint": ModelEndpoint, "extra_body_json": "{}"}`, with explicit model and
credential environment reference. Provider-specific chat-template settings must be
recorded in the profile. The receiver only writes fixed synthetic records in the
new output directory; the model cannot select a filesystem path or contact another
service through this tool. `verification.json` is machine-readable. A fixture pass
alone does not qualify an actual model-backed rollout or independent judge accuracy.

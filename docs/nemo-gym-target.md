# Instrumented NeMo Gym target

[Documentation map](README.md) · [Assessments](assessment.md) · [AGENT-01 roadmap](ROADMAP.md)

`interplay.assessment.gym.NeMoGymTarget` implements the existing assessment
`TargetAdapter` protocol with a native Gym SimpleAgent episode. Each generated
probe is appended as user text to a fixed operator-owned request. The adapter
binds the probe digest, assessment attempt ID, task ID and rollout ID to captured
responses, tool dispatches and a separately observed environment outcome.

The adapter supports two explicit SimpleAgent compatibility baselines:

| Gym revision | Selection | Native test interpreter | Source manifest |
| --- | --- | --- | --- |
| `f444b8020a3431fc820ef061cef400140bc7afb5` | Original default | Python 3.13.14 | [Original hashes](../interplay/assessment/gym_source.json) |
| `b454c9a6e9a5644564fac81064050094b237daaa` | Set `gym_revision` explicitly | Python 3.14.7 | [Gate-compatible hashes](../interplay/assessment/gym_source_b454.json) |

It calls the selected revision's private `_create_episode` interface. All five
recorded imported files must match that revision's manifest before any session
opens; selecting the other installed revision fails instead of falling back.
Every capture binding records the selected revision. Newer Gym initializes
client checkpoint state from its configuration; the recording wrapper preserves
the native client's validated fields while retaining dispatch restrictions.
These checks cover the recorded compatibility surface, not all Gym, dependencies,
in-memory modifications or served model weights. Other harnesses, remote Gym
server APIs, image environments and source revisions are not qualified.

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

For the Gate-compatible revision, use a separate Python 3.14.7 environment and
`onboarding/gym/requirements-b454.txt`, then set
`GymTargetConfig(gym_revision="b454c9a6e9a5644564fac81064050094b237daaa", ...)`.
The conformance CLI likewise requires `--gym-revision` with that exact revision.
Do not overlay the new requirements onto an existing original-baseline environment.
The installed native distribution contains the needed modules; a matching source
checkout is also supported for the drill. Never place a different revision on
`PYTHONPATH`: admission checks the actual imported file bytes.

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

For endpoints that support named function calls but disable automatic tool choice,
`--tool-choice-schedule forced-first-tool` explicitly names `record_marker` on the
first model request and selects `none` on subsequent requests. The conformance
manifest and actual request packets record this schedule. It tests native tool
execution and observation plumbing; it does not qualify autonomous tool selection.
Named and automatic calling have different serving requirements; see the
[vLLM tool-calling documentation](https://docs.vllm.ai/en/v0.15.0/features/tool_calling/).
No serving flags or deployments are changed by the conformance script.

The [2026-10-16 machine-readable qualification record](evidence/gym-target-20261016.json)
records passing native complete/exhausted/truncated fixtures and a successful
bounded model-backed rollout on an existing self-hosted model service. With
automatic tool choice, two actual model requests produced one native tool call
and one independently observed file-receiver record. Readback checks match the
actual model call ID/arguments to the native tool event and receiver binding,
confirm its tool reply appears in the next model request, and verify request/response
digests, stage order, complete capture, tunnel cleanup and private artifact checks.

The existing model service needed automatic tool choice and its installed
`qwen3_xml` parser enabled. The operator applied those flags to the owning
LLMInferenceService and performed a managed one-replica restart, then verified
readiness and the otherwise-identical owner specification. This was a separately
user-selected existing-server configuration change; the conformance script itself
does not configure infrastructure. No new inference resources were created.

Three earlier incomplete attempts remain in the record: an unavailable hosted
route (subsequent inventory HTTP 503) and self-hosted automatic/named tool requests
rejected with HTTP 400 before parser configuration. Their zero-tool outcomes
are retained. The successful automatic-tool rollout is one synthetic integration
check, with no broader autonomy, judge accuracy, adversarial robustness or
containment qualification.

## Native compatibility regression

The hosted `gym-target` matrix installs each immutable official Gym revision in
its own Python environment and runs five native tests per revision. These use
actual SimpleAgent and Responses/chat conversion with deterministic model
responses and a separately read synthetic file receiver. Complete mode observes
2 model calls, 1 tool and 1 receiver record; exhaustion observes 3/3/3 and stays
incomplete; truncation observes 1/0/0 and stays incomplete. Failed initialization
cannot satisfy any drill mode. Each of the five imported-file modifications is
rejected, as is selecting the other installed revision, before a session opens.

```bash
GYM_TEST_REVISION=b454c9a6e9a5644564fac81064050094b237daaa \
  .venv-gym-b454/bin/python -m unittest discover -s tests -p test_gym_target_native.py -v
```

Native compatibility does not enable Gate's target selector or qualify an
independently authenticated tool-to-boundary path. Gate must separately review
and admit the new Interplay source/lock/digests, preserve independent effect and
cleanup observation, then complete the bounded private live/recovery pilot.
BOUNDARY-01 remains open through those steps. The earlier live receipt above
remains an unchanged observation of the original baseline.

A bounded hosted-model smoke on the newer revision also passes: two actual
upstream model calls, one native tool and one independently read local receiver
record. Independent retained-byte readback joins the wire call ID/arguments to
native tool execution and the receiver attempt/marker, and verifies the tool
reply appears in the next model context. Tunnel retirement and private artifact
permission/credential checks pass. The serving configuration was unchanged.
The initial failed newer-revision fixture remains retained as incomplete;
its wrapper-initialization issue is fixed rather than reclassified.
See the [sanitized compatibility receipt](evidence/gym-compatibility-20261016.json).
This smoke does not execute a boundary-controlled remote effect or establish
judge accuracy, containment or general autonomous tool selection.

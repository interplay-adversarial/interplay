# Run, retain and recover method evaluations

[Attack methods](README.md) · [Tool guide](../tools-and-use-cases.md)

PAIR, TAP, Crescendo, GOAT, SLIP and Multimodal share authenticated target
transport, evidence-cited judging and per-invocation result retention. Each
Python entry point accepts these additional keyword arguments:

- `output_dir`: a **new** private directory for durable results. Omit it for
  memory-only execution; `result.records` still contains the same rows.
- `role_endpoints`: a mapping from `attacker`, `target`, `evaluator` or `judge`
  to `ModelEndpoint` objects. Each resolves only its own `api_key_env` (or its
  own role environment variable). SLIP's refiner uses the attacker role.
- `judge_members`: a list of `JudgeMember(judge_id=..., endpoint=...)` objects,
  each with its own endpoint/model/key environment variable. Use this instead
  of a `judge` role when configuring a panel.

Legacy `api_key`, `base_url`, model arguments and `secondary_judge_models`
remain accepted as shared defaults for compatibility. Explicit credential values are never overwritten by an ambient provider key.
`None` is preserved as an SDK argument; SDK provider-environment defaults can still
apply. Known provider fallback keys are included in redaction.
Use explicit role endpoints when roles need different credentials or endpoints.
Required positional method arguments remain required; explicit endpoints override
these defaults when constructing the transports.

```python
from pathlib import Path
from interplay.assessment.models import ModelEndpoint
from interplay.red_teaming import JudgeMember, goat_attack

result = await goat_attack(
    goal="Assess whether a synthetic canary can be disclosed",
    target_url="https://target.example/v1",
    target_model="target-model",
    attacker_model="openai/attacker-model",
    max_turns=3,
    role_endpoints={
        "target": ModelEndpoint(
            base_url="https://target.example/v1", model="target-model", api_key_env="TARGET_API_KEY"
        ),
        "attacker": ModelEndpoint(
            base_url="https://attacker.example/v1",
            model="attacker-model",
            api_key_env="ATTACKER_API_KEY",
        ),
    },
    judge_members=[
        JudgeMember(
            judge_id="judge-a",
            endpoint=ModelEndpoint(
                base_url="https://judge.example/v1",
                model="judge-model",
                api_key_env="JUDGE_API_KEY",
            ),
        ),
    ],
    output_dir=Path("output/new-goat-run"),
)
print(result.confirmed_success, len(result.records))
```

For CLI execution, put the method arguments in a JSON `parameters` object and
endpoint definitions in `role_endpoints`; `judge_members` is an optional array
of `{ "judge_id": "...", "endpoint": { ... } }` objects. Store environment
variable names, never literal keys. For example:

```json
{
  "parameters": {
    "goal": "Assess synthetic canary disclosure",
    "target_url": "https://target.example/v1",
    "target_model": "target-model",
    "attacker_model": "attacker-model",
    "judge_model": "judge-model",
    "max_turns": 3
  },
  "role_endpoints": {
    "target": {"base_url": "https://target.example/v1", "model": "target-model", "api_key_env": "TARGET_API_KEY"},
    "attacker": {"base_url": "https://attacker.example/v1", "model": "attacker-model", "api_key_env": "ATTACKER_API_KEY"},
    "judge": {"base_url": "https://judge.example/v1", "model": "judge-model", "api_key_env": "JUDGE_API_KEY"}
  }
}
```

```sh
interplay runner-run --method goat --config runner.json --output output/new-goat-run
interplay runner-recover output/new-goat-run
```

`events.jsonl` is the fsynced stage journal. A target attempt is committed before
sending it; its captured response is committed as `observed` **before** judging
or refinement. Cancellation, judge-call budget exhaustion, incomplete captures
and provider errors cannot erase that observation. An evidence write failure
stops the runner before further inference. No automatic target action retries.

`records.jsonl`, `records.parquet` and `records.arrow` export matching flat
`interplay-runner/2` rows. They contain the goal/adversarial intent, probe,
response, verdict, reasoning, evidence references, raw judge/panel JSON, role
provenance, conversation messages, status and error. `method_metadata_json`
retains method-specific identity and lineage (parent, round/depth/turn, selected
strategy and multimodal transform/control/digest). Search-only pruned or
unsupported trials are exported as incomplete with their metadata, never
claimed as target observations. `summary.json` retains campaign diagnostics,
stop reason and agreement report after a normal return.

Known configured role keys are redacted from captured evidence before it reaches
judges, refinement context, results and exports. Output directories are private
(mode 0700); journal/analytics files are mode 0600. Captured model content may
contain other sensitive information; these are private research artifacts.

Recovery uses only committed journal stages and never calls a model. It rejects
changes to attempt identity, goal, probe, strategy, provenance or a committed
observation, duplicate ordinals, regressed stages and rewritten terminal rows.
Unfinished attempts become incomplete. A partial trailing journal line is ignored;
unfinished records report `interrupted-truncated-journal` when one is present.
The recovered list and CLI summary also expose `truncated_tail`, including when
all preceding attempts were already terminal.
Version-1 journals remain readable, including their historical terminal-first rows.
Journals are capped at 128 MiB and 5,000 distinct attempts (including search-only
trials), with space reserved for observation/final stages before a new request.
SDK-default endpoints are recorded as unknown (`null`) when no explicit base URL
is available; explicit role endpoints provide complete routing provenance.

The campaign deadline and endpoint request limit bound SDK requests and their
async awaits. Late SDK results are rejected, even if the provider suppresses
cancellation. Multimodal HTTP work runs off the event loop. Cancelling an await
cannot forcibly kill a Python HTTP worker thread; that request still has its own
HTTP time/response bounds, and the worker cannot write a late journal stage.

Panel member IDs are unique even when endpoints serve the same model alias.
Repeated aliases are flagged in the panel trace; this does not establish
statistical independence. `majority` retains its historical **plurality** policy;
a tie is inconclusive. `unanimous` requires every member to agree. Invalid
member citations are removed, aggregate citations come from supporting members,
and the final aggregate is checked against the captured evidence. Scores remain
search diagnostics; these model judgments are not independently verified target
side effects, containment decisions or empirical attack success rates.

# Garak vulnerability scanning

[Attack methods](README.md) · [Tool guide](../tools-and-use-cases.md)

The wrapper supervises the external Garak CLI against an OpenAI-compatible
endpoint and parses its native report JSONL. Install Garak in its own environment
(`pip install 'interplay-adversarial[red-teaming,garak]'`); it has dependency conflicts with
some assessment/provider extras.

```python
from interplay.red_teaming import run_garak

result = run_garak(
    target_url="https://target.example/v1",
    target_model="target-model",
    probe_file="test.Test",  # Garak plugin selector; historical parameter name
    api_key_env="TARGET_API_KEY",
    output_dir="output/new-garak-run",
    campaign_seconds=600,
)
print(result["success"], result["returncode"], result["report"])
```

`probe_file` means a Garak plugin selector, not an arbitrary JSONL probe file.
The endpoint is passed through the `openai.OpenAICompatible` generator's `uri`
option, the model through `--model_name`, and the report location through
`--report_prefix`. `config_file` is an optional Garak run config.
`create_custom_config` writes the corresponding endpoint config privately,
without credentials. The key is passed through the scanner's environment,
never command-line arguments.

The scanner runs in a new private directory. It has a finite deadline and
bounded captured console output; the process group is terminated on completion,
error or cancellation so scanner workers cannot outlive supervision. Known
configured keys are redacted from returned console text and retained reports.

`success` means the scanner exited successfully; it is not an attack verdict.
`report` retains each latest native attempt stage and every detector evaluation.
`parse_garak_results(path)` also works offline, identifies incomplete/truncated
reports, and rejects malformed committed lines or regressed attempt stages.
A valid final JSON object is accepted without a trailing newline; Garak 0.17.0
writes its final digest this way. An invalid unterminated tail is still reported
as truncated and keeps the report incomplete. Source bytes are never rewritten
by the parser.
No detector thresholds or judge verdicts are invented by the parser. Garak
owns its own detector semantics and generator retry policy; the method runners'
no-target-retry contract does not describe Garak internals.

The CLI contract and report stages are documented in Garak's official
[CLI reference](https://reference.garak.ai/en/stable/cliref.html) and
[reporting reference](https://reference.garak.ai/en/stable/reporting.html).
The wrapper is covered by a fake scanner executable and synthetic native JSONL
fixtures. The installed Garak 0.17.0 CLI/generator/detector path also passes
the optional [real-scanner loopback conformance drill](../runner-qualification.md#real-garak-compatibility-and-dependency-status).
This is version-specific compatibility evidence; it does not qualify other
plugins, live targets or the isolated environment's dependency security. The
current dependency-audit blocker is [#68](https://github.com/interplay-adversarial/interplay/issues/68).

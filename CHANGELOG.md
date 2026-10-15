# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Changed
- GitHub Actions in all workflows are pinned to full commit SHAs with a version comment (Dependabot keeps them current)
- TAP's `secondary_judge_model` (singular, diagnostic-only: re-judged already-decided branches afterward purely to compute a Cohen's kappa, never affecting the verdict) is replaced by `secondary_judge_models` (plural), shared with every other migrated runner: it now forms a real voting panel with `judge_model`, and agreement comes from those same judge calls instead of a separate re-judging pass. `TapResult.kappa_score`/`kappa_unavailable_reason` are replaced by `irr_report`/`irr_unavailable_reason` (see Added).

### Fixed
- The publish workflow referenced `astral-sh/setup-uv@v10`, a tag that does not exist (that action publishes exact versions only); it is now pinned to v10.3.0
- `JudgeScorer` (`interplay.red_teaming.transport`) called `any_llm.completion()`, the synchronous API, from inside the running event loop every attack runner executes in; `any_llm` raises `RuntimeError: Cannot use the sync API in an async context` there, which `JudgeScorer.score()`'s own exception handling silently turned into `judge_verdict="inconclusive"` on every call. This made TAP, Crescendo, GOAT, SLIP and Multimodal's evidence-cited judging never actually invoke the judge model in real usage. `JudgeScorer.score()`/`_call()` and `multimodal_runner._run_attempt()` are now `async` and use `any_llm.acompletion()`; the five runners' call sites now `await` them.
- `create_completion_kwargs()` passed a caller-supplied `base_url` straight through as a `base_url` key; `any_llm.completion()`/`acompletion()` only accept `api_base`, so every attacker/judge call that set a custom endpoint (PAIR's own attacker/judge setup, and `JudgeScorer` for every other runner) raised `TypeError: unexpected keyword argument 'base_url'` once it reached the provider SDK. `base_url` is now translated to `api_base`.
- `examples/custom_spec.py` and `examples/diverse_dataset.py` imported `data_designer.types.providers` (removed) and called `DataDesigner(providers=..., model_configs=...)`, both from before a data-designer refactor; neither script could run. Updated to the current API (`data_designer.config.{ModelProvider,ModelConfig}`, `DataDesigner(model_providers=...)`, `builder.add_model_config(...)`, `.preview(...).dataset`, `.create(...).load_dataset()`), and fixed `probe_quality_score` extraction (it is `{"quality": {"score": 0-3, "reasoning": ...}}`, not a flat number). Verified against `scripts/mock_openai.py`.
- `docs/tools-and-use-cases.md` said TAP's judge-agreement (`judge-kappa`) computation "still needs implementation; current return is a placeholder"; it has computed a real two-judge Cohen's kappa since PR #46.
- `examples/integrated_run.py` read `tap_result.kappa_score`, a field the judge-panel change renamed to `irr_report`; the example crashed with `AttributeError` on every run. `docs/METHODOLOGY.md` and `docs/tools-and-use-cases.md` still described TAP's judge agreement as TAP-only and Cohen's-kappa-specific after it became an N-judge-capable, five-runner Krippendorff's-alpha panel.
- `interplay/pipeline.py`'s own `if __name__ == "__main__":` smoke test (`python interplay/pipeline.py` / `python pipeline.py` run directly) had the same pre-refactor `DataDesigner(providers=..., model_configs=...)` call and un-dereferenced `.preview(builder)` (needs `.dataset`) that `examples/custom_spec.py`/`diverse_dataset.py` had; it crashed with `TypeError` on the very first line that touched DataDesigner. Fixed the same way, and verified against `scripts/mock_openai.py` for both a taxonomy mode and a comparison mode.

### Added
- Dependabot keeps the GitHub Actions in the workflows up to date (weekly PRs)
- `hygiene` CI check: every commit in a pull request carries the maintainer's `Signed-off-by`, the PR body ends with it, and no Claude or Hermes session link or id appears in commits, diffs or PR text (bot-authored PRs skip the sign-off)
- `.env.example`, referenced by README.md and AGENTS.md's `cp .env.example .env` setup step but never committed
- `examples/assessment_campaign.py`: a complete, runnable `interplay.assessment` campaign using the built-in `DataDesignerBackend`/`OpenAIEndpointTarget`, in batch and adaptive mode
- `examples/single_attack_runner.py`: run any one of the six attack runners (including Crescendo, GOAT, SLIP and Multimodal, which had no example script) against a target from the command line
- `docs/README.md`: a documentation map and reading-path index; cross-linked from every other doc page and the project README
- `JudgePanel` (`interplay.red_teaming.transport`): a configurable judge panel/jury for TAP, Crescendo, GOAT, SLIP and Multimodal (not PAIR, which isn't migrated to `JudgeScorer`). Pass `secondary_judge_models` alongside `judge_model` to form a panel; `judge_aggregation` (`"majority"` or `"unanimous"`) decides how the judges' verdicts combine into the trial's verdict. Every result gains `irr_report` (a real, N-capable Krippendorff's alpha, via `judge_kappa.KrippendorffAlpha`, with a bootstrapped confidence interval, computed from those same judge calls) and `irr_unavailable_reason`; every trial gains `judge_panel_json` retaining each judge's individual verdict and reasoning, never collapsed away by the aggregation. A single `judge_model` with no secondary models is unaffected -- same `JudgeScorer`, same behavior as before this existed. `examples/single_attack_runner.py` gained `--judge-models`/`--judge-aggregation` to demonstrate it from the command line.

## [0.2.1] - 2026-10-11

### Added
- Dev tooling: `uv sync` now installs pytest, pytest-asyncio, ruff and pip-audit (`dev` dependency group); the `dev` extra carries the same list for pip users
- `interplay probes setup --base-url URL --model NAME [--api-key-env VAR]` defines the model the pipeline uses (data-designer alias `cultural-bias-model`) without storing the key
- `scripts/smoke_install.py` (installs a published or built package in a throwaway directory and exercises it like a new user), `scripts/mock_openai.py` (fake OpenAI-compatible endpoint), an end-to-end test, and `docs/RELEASING.md`
- `scripts/smoke_install.py` inspects the dataset `create` writes for the singapore, sdg-hub-harm and combined modes (all rows kept, every row scored); new sampler and per-mode end-to-end tests
- Publish workflow gate: a release can only reach PyPI if the same version is already on TestPyPI

### Fixed
- `pip install "interplay-adversarial[all]"` could not be installed: Garak pins `cohere`/`mistralai` versions that conflict with `any-llm-sdk[all]`. `all` is now `red-teaming` plus `providers`; install the `garak` extra separately
- The quality judge now scores benign probes too (it used to be skipped with the unused probe column). Before, data-designer's preview table crashed with `'NoneType' object has no attribute 'items'` on most small previews, and benign rows had no quality score. The rubric's top level now applies to both probe types (adversarial probes must still use a named Singapore strategy). Note: this changes the dataset, benign rows now carry a score.
- `sdg-hub-harm` and `combined` modes silently dropped records: the eight harm categories have an empty cultural-context pool and `np.random.choice([])` raised, so every harm row was skipped (`sdg-hub-harm` produced 0 rows). The samplers now fall back when a pool is empty.
- `interplay probes preview` and `create` failed with "No model config with alias 'cultural-bias-model' found" on a fresh install; they now explain how to set the model up

## [0.2.0] - 2026-10-10

### Added
- `interplay` command-line interface with `modes`, `probes validate`, `probes preview`, `probes create` subcommands
- Probe pipeline (`interplay/pipeline.py`) shipped inside the wheel for direct use after pip install

### Changed
- README and docs use the full project name "Interplay Adversarial" and carry a non-affiliation note
- README describes targets beyond models: any endpoint compatible with the providers supported by `any-llm-sdk` (models and the agents, tool-using applications and harnesses served behind such an endpoint)

## [0.1.0] - 2026-10-10

### Added
- Initial release with probe generation using Singapore AI Safety Red Teaming Challenge methodology
- Seven attack runners: Garak, TAP, PAIR, Crescendo, GOAT, SLIP, Multimodal
- Documentation: methodology, content policy, security guidelines, attack technique docs
- CI pipeline: ruff lint/format, pytest on Python 3.12/3.13, pip-audit
- PyPI trusted publishing setup

# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Added
- Dependabot keeps the GitHub Actions in the workflows up to date (weekly PRs)
- `hygiene` CI check: every commit in a pull request carries the maintainer's `Signed-off-by`, the PR body ends with it, and no Claude or Hermes session link or id appears in commits, diffs or PR text (bot-authored PRs skip the sign-off)

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

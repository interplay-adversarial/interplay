# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Added
- `interplay probes setup --base-url URL --model NAME [--api-key-env VAR]` defines the model the pipeline uses (data-designer alias `cultural-bias-model`) without storing the key
- `scripts/smoke_install.py` (installs a published or built package in a throwaway directory and exercises it like a new user), `scripts/mock_openai.py` (fake OpenAI-compatible endpoint), an end-to-end test, and `docs/RELEASING.md`
- Publish workflow gate: a release can only reach PyPI if the same version is already on TestPyPI

### Fixed
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

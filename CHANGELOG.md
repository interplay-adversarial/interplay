# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [0.2.0] - unreleased

### Added
- `interplay` command-line interface with `modes`, `probes validate`, `probes preview`, `probes create` subcommands
- Probe pipeline (`interplay/pipeline.py`) shipped inside the wheel for direct use after pip install

### Changed
- Renamed project to "Interplay Adversarial" (full name in README/docs) with non-affiliation note

## [0.1.0] - 2026-10-10

### Added
- Initial release with probe generation using Singapore AI Safety Red Teaming Challenge methodology
- Seven attack runners: Garak, TAP, PAIR, Crescendo, GOAT, SLIP, Multimodal
- Documentation: methodology, content policy, security guidelines, attack technique docs
- CI pipeline: ruff lint/format, pytest on Python 3.12/3.13, pip-audit
- PyPI trusted publishing setup

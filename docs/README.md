# Documentation map

[← Project README](../README.md)

Interplay Adversarial has three mostly-independent things you can do — generate
culturally grounded probes, run a legacy attack method against a target, or run a
description-driven assessment campaign — plus the project/process docs around them.
This page is the index; it does not duplicate what each page already says.

## Pick a starting point

| You want to... | Start here |
| --- | --- |
| Understand the whole project in five minutes | [METHODOLOGY.md](METHODOLOGY.md) |
| Decide which of the three interfaces (probes / assessment / legacy runners) fits your question | [tools-and-use-cases.md](tools-and-use-cases.md) |
| Generate cultural-bias or harm probes | [probe-generation.md](probe-generation.md), then [../interplay/specs/CONTRIBUTING.md](../interplay/specs/CONTRIBUTING.md) to add a comparison |
| Run TAP, PAIR, Crescendo, GOAT, SLIP, Multimodal or Garak against a target, optionally with a panel of judges | [attacks/README.md](attacks/README.md) |
| Get a probe → response → evidence-cited verdict record for a custom criterion | [assessment.md](assessment.md) |
| Report a vulnerability or understand what's in/out of scope for content | [../SECURITY.md](../SECURITY.md), [CONTENT_POLICY.md](CONTENT_POLICY.md) |
| Cut a release | [RELEASING.md](RELEASING.md) |
| Work on the repo itself as an AI agent | [../AGENTS.md](../AGENTS.md) |

## All pages

```
README.md (this page)
├── METHODOLOGY.md ─────────── why the project is built this way; references
├── tools-and-use-cases.md ─── which of the 3 interfaces to use, and their current limits
├── probe-generation.md ────── every pipeline mode/spec, the diverse-dataset helper, output columns
├── assessment.md ──────────── description-driven campaigns (interplay.assessment)
├── attacks/
│   ├── README.md ──────────── legacy attack runners overview, query budgets
│   ├── tap.md / pair.md / crescendo.md / goat.md / slip.md / multimodal.md / garak.md
│   └── runner-results.md ──── role configuration, journals, exports and CLI recovery
├── CONTENT_POLICY.md ───────── what adversarial material may be committed
└── RELEASING.md ────────────── TestPyPI-first release process

../README.md ──────────────── what it is, what it provides, install, quick start, configuration overview
../AGENTS.md ───────────────── repository structure and conventions for AI agents
../SECURITY.md ─────────────── vulnerability reporting
../interplay/specs/CONTRIBUTING.md ─ add a new two-group comparison spec
```

## What's authoritative where

- **What the project is, install, quick start, the three top-level env-var categories:**
  [../README.md](../README.md), kept short on purpose. The full environment-variable list with
  defaults is [../.env.example](../.env.example); every mode, spec, output column and
  diverse-dataset helper is [probe-generation.md](probe-generation.md).
- **Current behavior and limits of each attack runner** (budgets, judging, retries): each runner's
  own page under [attacks/](attacks/), not [METHODOLOGY.md](METHODOLOGY.md) (background/references
  only) or [tools-and-use-cases.md](tools-and-use-cases.md) (cross-runner comparison only).
- **What a verdict means and doesn't mean** (evidence citation, `inconclusive`, release eligibility):
  [assessment.md](assessment.md) for the assessment API; each attack page's "Current behavior" section
  for that runner's scoring.
- **Method-runner role configuration, durable result schemas and offline recovery**:
  [attacks/runner-results.md](attacks/runner-results.md). Garak's native scanner
  reports use its own format; see [attacks/garak.md](attacks/garak.md).

## Conventions on these pages

- Every [attacks/](attacks/) page follows the same shape: strategy/budget/key-feature header, a
  runnable example, a "Current behavior" section, Notes, Reference.
- "Current behavior" sections describe what the code does today, not the published paper's method;
  deviations are called out explicitly rather than left implicit.
- A runner's or pipeline's own score (`best_score`, `probe_quality_score`, evaluator likelihood) is
  never presented as an empirical attack success rate or a release decision; where that distinction
  matters, the page says so again rather than assuming you remember it from another page.

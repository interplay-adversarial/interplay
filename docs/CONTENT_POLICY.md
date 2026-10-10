# Content Policy

Interplay contains material that is meant to make models misbehave. This policy says what may be
committed, how it is labeled, and who reviews it. It applies to code, techniques, specs, example
data and collections, and to pull requests written with AI assistance.

## Principles

- **Purpose:** measure and improve model safety. Contributions must serve evaluation or defense.
- **Methods over payloads:** prefer generators, templates and taxonomies to fixed lists of harmful
  text. A contribution should still be useful if every example in it were removed.
- **Synthetic by default:** examples are generated or written for this project, not scraped from
  private conversations or personal data.
- **Public repository:** everything committed is public, permanently, in forks and in git history.

## Not accepted

- Content that sexualizes minors, in any form or framing.
- Working operational uplift for mass-casualty harm: step-by-step or specific synthesis, enhancement
  or deployment guidance for biological, chemical, radiological or nuclear weapons.
- Real personal data: names tied to real people with harassing content, doxxing material, private
  identifiers, or scraped personal conversations.
- Working exploit code or credentials for a specific unpatched third-party system.
- Secrets, tokens, internal hostnames, cluster or namespace names, or employer-internal details.
- Material whose main use is harassment or targeting a group or person rather than testing a model.

## Sensitivity labels

Every collection, spec and example dataset declares one of these in its metadata or header:

| Label | Meaning | Review |
|---|---|---|
| `low` | Mild or generic, e.g. cultural-bias probes with neutral framing. | One maintainer. |
| `moderate` | Realistic harmful requests across ordinary harm categories (hate, self-harm, fraud, weapons at a non-operational level). | One maintainer who reads the content, not only the diff summary. |
| `high` | Anything near the limits above, including dual-use technical detail. | Explicit sign-off from the project owner; usually reduced or withheld. |

When in doubt, label higher and ask in the PR.

## Review rules

- Maintainers, not authors, merge. `main` accepts changes only through pull requests.
- Changes to collections or example data are reviewed for content, not just format.
- PRs written or assisted by an AI agent follow the same rules and must be read by a human before
  merge. An agent may open PRs; it does not merge or administer repositories.
- Reviewers may remove or reword content after merge without notice if it breaches this policy.

## Data handling

- Model outputs from real runs can contain harmful text. Do not commit raw transcripts; commit
  aggregate results and a small, reviewed set of redacted examples.
- Do not commit API keys or `.env` files. Run secret scanning before pushing.

## Use

Use Interplay only against models and systems you own or are authorized to test, and follow the
terms of the services you test. Report weaknesses found in third-party systems as described in
[SECURITY.md](../SECURITY.md).

## Changing this policy

Propose changes by pull request. Loosening a rule requires the project owner's explicit approval.

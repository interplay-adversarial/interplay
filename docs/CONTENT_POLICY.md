# Content Policy

Interplay Adversarial contains material that is meant to make **models, agents, tools, harnesses and agent skills**
misbehave. This policy says what may be committed, how it is labeled, and who reviews it. It applies to
code, techniques, specs, example data and collections, adversarial skills and tool definitions, and to
pull requests written with AI assistance.

## Principles

- **Purpose:** measure and improve the safety and security of AI systems. Contributions must serve evaluation or defense.
- **Methods over payloads:** prefer generators, templates and taxonomies to fixed lists of harmful
  text or ready-made attack artifacts. A contribution should still be useful if every example in it were removed.
- **Inert by default:** adversarial skills, tool definitions and agent test fixtures demonstrate a
  behavior; they do not carry a working payload against real systems (see "Executable and agentic content").
- **Synthetic by default:** examples are generated or written for this project, not scraped from
  private conversations, real repositories or personal data.
- **Public repository:** everything committed is public, permanently, in forks and in git history.

## Not accepted

- Content that sexualizes minors, in any form or framing.
- Working operational uplift for mass-casualty harm: step-by-step or specific synthesis, enhancement
  or deployment guidance for biological, chemical, radiological or nuclear weapons.
- Real personal data: names tied to real people with harassing content, doxxing material, private
  identifiers, or scraped personal conversations.
- Working exploits, malware or credentials aimed at a specific unpatched third-party system, model
  service, agent product, tool server, skill registry or package.
- Malicious skills, tools, packages or prompts built to be published or installed in the wild
  (typosquats, hidden exfiltration, backdoors) rather than to test a defense.
- Secrets, tokens, internal hostnames, cluster or namespace names, or employer-internal details.
- Material whose main use is harassment or targeting a group or person rather than testing a system.

## Executable and agentic content

Skills, tool and MCP server definitions, harness adapters, agent traces and anything else that an agent
can load or run need extra care, because they can act when used:

- **No real side effects:** fixtures use fake endpoints (reserved domains such as `example.com`, or
  localhost), canary values and throwaway credentials. They must not touch real accounts, mailboxes,
  repositories, payment or deployment systems.
- **Visible behavior:** the adversarial behavior is stated in the file's header or description. No
  obfuscation, encoded payloads or hidden instructions beyond what the technique itself demonstrates.
- **Safe to open:** nothing runs on import, install or clone. Anything that executes code, calls tools or
  makes network requests is opt-in, runs in a sandbox or dry-run mode by default, and documents its side effects.
- **Dependencies:** pin them, and do not add packages whose purpose you cannot explain in the PR.
- **Prompt-injection fixtures** (poisoned documents, tool outputs, skill text) are labeled as such and
  limited to demonstrating the injection, not to carrying real malicious instructions for a specific victim.

## Sensitivity labels

Every collection, spec, adversarial skill or tool fixture, and example dataset declares one of these in its
metadata or header:

| Label | Meaning | Review |
|---|---|---|
| `low` | Mild or generic: neutral-framed bias probes, inert fixtures with obviously fake targets. | One maintainer. |
| `moderate` | Realistic harmful requests across ordinary harm categories (hate, self-harm, fraud, weapons at a non-operational level), or fixtures that exercise real tool use, code execution or network access inside a sandbox. | One maintainer who reads the content or code, not only the diff summary. |
| `high` | Anything near the limits above, dual-use technical detail, or fixtures that could cause harm outside a sandbox if misused. | Explicit sign-off from the project owner; usually reduced or withheld. |

When in doubt, label higher and ask in the PR.

## Review rules

- Maintainers, not authors, merge. `main` accepts changes only through pull requests.
- Changes to collections, example data, skills and tool fixtures are reviewed for content and behavior, not just format.
- PRs written or assisted by an AI agent follow the same rules and must be read by a human before
  merge. An agent may open PRs; it does not merge or administer repositories.
- Reviewers may remove or reword content after merge without notice if it breaches this policy.

## Data handling

- Model outputs and agent traces from real runs can contain harmful text, secrets, tool outputs and
  personal data. Do not commit raw transcripts or traces; commit aggregate results and a small, reviewed
  set of redacted examples.
- Do not commit API keys, `.env` files or tool credentials. Run secret scanning before pushing.

## Use

Use Interplay Adversarial only against models, agents, tools and systems you own or are authorized to test, in an
isolated environment, and follow the terms of the services you test. Report weaknesses found in
third-party systems as described in [SECURITY.md](../SECURITY.md).

## Changing this policy

Propose changes by pull request. Loosening a rule requires the project owner's explicit approval.

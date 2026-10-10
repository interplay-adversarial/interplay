# Security Policy

Interplay is an adversarial and red-teaming library. Its techniques target **models, agents, tools,
harnesses and agent skills**, and some of them run code, call tools or send network traffic as part of a
test. Two kinds of problems are in scope here, and they are reported differently.

## 1. Vulnerabilities in this project

Examples:

- Code execution or unintended side effects triggered by a spec, collection, config, technique or
  agent-skill file (including unsafe deserialization and path traversal).
- A runner, harness adapter or tool-use technique that acts outside its sandbox or configured scope:
  runs commands, reads or writes files, calls tools, or sends data somewhere the operator did not intend.
- A harness or skill we ship that leaks the operator's credentials, environment or test data.
- Supply-chain problems: a malicious or typosquatted dependency, package, skill or collection.
- Credentials or private infrastructure details committed to the repository.

**Report privately.** Use GitHub's private vulnerability reporting: the **Security** tab of the
affected repository, then **Report a vulnerability**. Do not open a public issue or PR. If that
option is missing, open a public issue that says only "security contact requested", with no details,
and a maintainer will reach out.

What to expect: an acknowledgement within 7 days, a first assessment within 14 days, and credit in
the fix unless you prefer otherwise. This is a volunteer project and these are targets, not
guarantees.

Supported versions: only the latest release and the `main` branch receive fixes until a 1.0 release.

## 2. Weaknesses found in third-party targets

If you find a weakness in someone else's system while using this project, follow coordinated
disclosure. This covers:

- **Models and model services:** jailbreaks, safety or bias failures, data leakage.
- **Agents and agent frameworks (harnesses):** prompt injection that causes unintended actions,
  goal hijacking, memory or context poisoning, unsafe handling of untrusted content, missing
  confirmation or permission checks, sandbox escapes.
- **Tools and tool servers (for example MCP servers, plugins, connectors):** injection through tool
  descriptions or outputs, over-broad permissions, confused-deputy and credential-passing flaws.
- **Agent skills and skill registries:** skills or instructions that hide behavior, exfiltrate data
  or escalate privileges, and registry weaknesses that allow impersonation or tampering.

How to disclose:

1. Tell the vendor or maintainer first, using their security policy or private reporting channel.
   For open-source targets that means their `SECURITY.md` or private advisory feature.
2. Allow a reasonable time to respond (90 days is common) before publishing.
3. Do not add working exploits for an unfixed issue to this repository. Describe the technique
   generically; keep target-specific strings, payloads and proofs of concept out until the fix ships.
4. If a skill, tool package or registry entry is actively malicious, also report it to the
   registry or hosting platform so it can be taken down.

## Testing safely

Techniques against agents and tools can have real effects. When you use or contribute to Interplay:

- Run agent, tool and harness tests in an isolated sandbox with throwaway credentials, synthetic
  data and no access to production systems, real mailboxes, payment or deployment tools.
- Techniques that can act (execute code, call tools, write files, make network requests) must
  default to a sandbox or dry-run mode, and must document their side effects.
- Use canary values instead of real secrets when testing for data exfiltration.
- Test only systems you own or are explicitly authorized to test, and follow the target's terms.

## Out of scope

Reports that a technique "works" against a model, agent, tool or skill, that a probe or payload is
offensive, or that the library can be used to attack systems you do not own. Offensive-security
content is the purpose of the project; see [docs/CONTENT_POLICY.md](docs/CONTENT_POLICY.md) for
the limits.

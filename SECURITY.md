# Security Policy

Interplay is an adversarial and red-teaming library. Two kinds of problems are in scope here, and
they are reported differently.

## 1. Vulnerabilities in this project

Examples: code execution through a spec, collection or config file; unsafe deserialization;
credentials or private infrastructure details committed to the repository; a runner that sends
data somewhere it should not.

**Report privately.** Use GitHub's private vulnerability reporting: the **Security** tab of the
affected repository, then **Report a vulnerability**. Do not open a public issue or PR. If that
option is missing, open a public issue that says only "security contact requested", with no details,
and a maintainer will reach out.

What to expect: an acknowledgement within 7 days, a first assessment within 14 days, and credit in
the fix unless you prefer otherwise. This is a volunteer project and these are targets, not
guarantees.

Supported versions: only the latest release and the `main` branch receive fixes until a 1.0 release.

## 2. Weaknesses found in third-party models or products using Interplay

If you find a jailbreak or bias failure in someone else's model or service while using this
project, follow coordinated disclosure: tell the vendor first, give them a reasonable time to
respond (90 days is common), and only then publish. Do not add working, vendor-specific exploit
strings for an unfixed issue to this repository.

## Out of scope

Reports that a technique "works" against a model, that a probe is offensive, or that the library
can be used to attack systems you do not own. Offensive-security content is the purpose of the
project; see [docs/CONTENT_POLICY.md](docs/CONTENT_POLICY.md) for the limits, and use Interplay
only against systems you own or are authorized to test.

"""Full dependency audit of the isolated Garak lock/install profile.

Run from a source checkout:

    python scripts/garak_isolated_audit.py --output /tmp/interplay-garak-audit
    # optionally, cross-check an existing isolated environment:
    python scripts/garak_isolated_audit.py --venv /tmp/interplay-garak-env \
        --output /tmp/interplay-garak-audit

The profile is the frozen `red-teaming,garak` extra set (see the
[Real Garak compatibility and dependency status](../docs/runner-qualification.md#real-garak-compatibility-and-dependency-status)
section). The script exports the exact pinned profile from `uv.lock`, audits
every pinned distribution against the OSV/PyPI advisory databases, and fails
on any advisory that is not in the explicit disposition set below. The raw
audit output and a receipt are retained in the output directory (0600).

The disposition set is an explicit, evidence-backed disposition of individual
advisories; it is not a suppression. Any advisory outside it, any stale
disposition (the pinned package no longer matches the version it was
verified against, or a dispositioned advisory no longer reports), and any
reference to a vulnerable API inside the installed Garak source all fail the
audit and require a documented re-review.
"""

import argparse
import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PROFILE_EXTRAS = ["red-teaming", "garak"]
PINNED_KEY_PACKAGES = ("garak", "datasets", "fsspec", "nltk", "data-designer")

# Explicitly dispositioned advisories, keyed by (package, advisory ID).
# Each record must be re-verified whenever the pinned version of the package
# changes; a blanket "ignore everything" is deliberately not representable.
DISPOSITIONED_ADVISORIES = {
    ("nltk", "PYSEC-2026-3740"): {
        "aliases": ["CVE-2026-81726", "GHSA-8mgp-746c-j5xp"],
        "status": "explicit-disposition-not-applicable",
        "no_fixed_release": True,
        "verified_against": "3.10.3",
        "rationale": (
            "The advisory (file-sandbox bypass in NLTK model-artifact APIs) "
            "covers TransitionParser.train/parse, AveragedPerceptron.save/load, "
            "PerceptronTagger.save_to_json and save_maxent_params, and requires "
            "pathsec enforcement plus untrusted workflows choosing model "
            "import/export paths. Garak uses nltk only for corpus access "
            "(stopwords, wordnet, words), word_tokenize, the default POS "
            "tagger (a fixed internal resource loaded through the pathsec-aware "
            "data loader), jaro_winkler_similarity and corpus download; neither "
            "Garak nor interplay references the vulnerable APIs or enables "
            "pathsec."
        ),
        "upstream_evidence": [
            "https://github.com/advisories/GHSA-8mgp-746c-j5xp",
            "https://github.com/nltk/nltk/issues/3826",
        ],
        "verified_garak_version": "0.17.1",
        "vulnerable_apis": [
            "TransitionParser",
            "AveragedPerceptron",
            "PerceptronTagger",
            "save_maxent_params",
        ],
    }
}


def require(condition, reason):
    if not condition:
        raise RuntimeError(reason)


def save(path, value):
    path.write_text(value if isinstance(value, str) else json.dumps(value, indent=2) + "\n")
    path.chmod(0o600)


def run(cmd, **kwargs):
    return subprocess.run(cmd, capture_output=True, text=True, check=False, **kwargs)


def sha256(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def export_frozen_profile(root, requirements):
    result = run(
        [
            "uv",
            "export",
            "--frozen",
            "--no-dev",
            "--no-emit-project",
            *(arg for extra in PROFILE_EXTRAS for arg in ("--extra", extra)),
        ],
        cwd=root,
    )
    require(result.returncode == 0, f"uv export failed: {result.stderr.strip()[:400]}")
    requirements.write_text(result.stdout)
    requirements.chmod(0o600)


def audit_tool_pip_audit(tool_venv):
    python = tool_venv / "bin" / "python"
    seeded = run([str(python), "-m", "pip", "install", "-q", "pip-audit>=2.7,<3"], timeout=600)
    require(seeded.returncode == 0, f"pip-audit install failed: {seeded.stderr.strip()[:400]}")
    version = run([str(python), "-m", "pip_audit", "--version"]).stdout.split()[-1]
    return python, version


def run_audit(pip_audit_python, requirements, output_json, output_txt):
    result = run(
        [
            str(pip_audit_python),
            "-m",
            "pip_audit",
            "-r",
            str(requirements),
            "--format",
            "json",
            "--progress-spinner",
            "off",
        ],
        timeout=900,
    )
    # pip-audit exits 1 when it reports findings; that is data, not a failure,
    # until the findings are evaluated against the disposition set.
    require(result.returncode in (0, 1), f"pip-audit failed: {result.stderr.strip()[:400]}")
    data = json.loads(result.stdout)
    output_json.write_text(json.dumps(data, indent=2) + "\n")
    output_json.chmod(0o600)
    lines = [f"{len(data.get('dependencies', []))} pinned distributions audited.", ""]
    findings = [
        {
            "name": dep["name"],
            "version": dep["version"],
            "vulns": [
                {
                    "id": vuln["id"],
                    "aliases": vuln.get("aliases", []),
                    "fix_versions": vuln.get("fix_versions", []),
                }
                for vuln in dep.get("vulns", [])
            ],
        }
        for dep in data.get("dependencies", [])
        if dep.get("vulns")
    ]
    for finding in findings:
        for vuln in finding["vulns"]:
            fixes = ",".join(vuln["fix_versions"]) if vuln["fix_versions"] else "none reported"
            lines.append(f"{finding['name']} {finding['version']}: {vuln['id']} (fix: {fixes})")
    if not findings:
        lines.append("No known vulnerabilities reported.")
    output_txt.write_text("\n".join(lines) + "\n")
    output_txt.chmod(0o600)
    return data, findings


def canonicalize(name):
    return re.sub(r"[-_.]+", "-", name).lower()


def pinned_versions(requirements):
    # The frozen export pins the cross-platform graph: one package can carry
    # several version pins, one per environment marker.
    versions = {}
    for line in requirements.read_text().splitlines():
        match = re.match(r"^([A-Za-z0-9][A-Za-z0-9._-]*)==([^\s\\]+)", line)
        if match:
            versions.setdefault(canonicalize(match.group(1)), set()).add(match.group(2))
    return {name: sorted(vers) for name, vers in versions.items()}


def evaluate_findings(findings, pinned):
    unexpected = []
    stale = []
    applied = []
    seen = set()
    for finding in findings:
        for vuln in finding["vulns"]:
            key = (canonicalize(finding["name"]), vuln["id"])
            seen.add(key)
            record = DISPOSITIONED_ADVISORIES.get(key)
            if record is None:
                unexpected.append(
                    {"package": finding["name"], "version": finding["version"], **vuln}
                )
                continue
            if record.get("verified_against") != finding["version"]:
                stale.append(
                    {
                        "advisory": vuln["id"],
                        "package": finding["name"],
                        "reason": (
                            f"audited {finding['version']} differs from verified "
                            f"{record['verified_against']}; re-verify the disposition"
                        ),
                    }
                )
            else:
                applied.append(f"{finding['name']}:{vuln['id']}")
    for key in DISPOSITIONED_ADVISORIES:
        if key not in seen and key[0] in pinned:
            stale.append(
                {
                    "advisory": key[1],
                    "package": key[0],
                    "reason": (
                        "advisory no longer reports for the pinned "
                        f"{', '.join(pinned.get(key[0], []))}; update or remove the disposition"
                    ),
                }
            )
    return unexpected, stale, applied


def venv_python(venv):
    python = Path(venv) / "bin" / "python"
    require(python.is_file(), f"no interpreter at {python}")
    return python


def installed_versions(venv_python):
    code = "import importlib.metadata as m\n" + "".join(
        f"print({name!r}, m.version({name!r}))\n" for name in ("garak", "interplay-adversarial")
    )
    result = run([str(venv_python), "-c", code])
    require(result.returncode == 0, f"venv profile check failed: {result.stderr.strip()[:400]}")
    return dict(line.split() for line in result.stdout.splitlines())


def venv_crosscheck(venv_python, pinned):
    # The frozen export pins the cross-platform graph, so the safe check is the
    # installed -> locked direction: every installed distribution must match a
    # lock pin, and the profile's key packages must be present.
    result = run([str(venv_python), "-m", "pip", "freeze"])
    if result.returncode != 0:
        uv = run(["uv", "pip", "freeze", "--python", str(venv_python)])
        require(uv.returncode == 0, f"uv pip freeze failed: {uv.stderr.strip()[:400]}")
        result = uv
    installed = {}
    for line in result.stdout.splitlines():
        match = re.match(r"^([A-Za-z0-9][A-Za-z0-9._-]*)==([^\s\\]+)", line)
        if match:
            installed[canonicalize(match.group(1))] = match.group(2)
    drift = {
        name: {"locked": pinned.get(name), "installed": version}
        for name, version in installed.items()
        if name not in pinned or version not in pinned[name]
    }
    missing = {name: pinned[name] for name in PINNED_KEY_PACKAGES if name not in installed}
    return {"drift": drift, "missing_key_packages": missing}


def applicability_scan(venv_python, record, garak_version):
    require(
        record.get("verified_garak_version") == garak_version,
        "installed garak version changed; re-verify the NLTK disposition",
    )
    result = run([str(venv_python), "-c", "import garak; print(garak.__file__)"])
    require(result.returncode == 0, f"garak import failed: {result.stderr.strip()[:400]}")
    package_dir = Path(result.stdout.strip()).parent
    references = {}
    for source in sorted(package_dir.rglob("*.py")):
        text = source.read_text(encoding="utf-8", errors="replace")
        for api in record.get("vulnerable_apis", []):
            for match in re.finditer(rf"\b{re.escape(api)}\b", text):
                line = text.count("\n", 0, match.start()) + 1
                references.setdefault(api, []).append(f"{source.name}:{line}")
    return {"package_dir": str(package_dir), "vulnerable_api_references": references}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--venv", type=Path, help="isolated environment to cross-check")
    parser.add_argument("--output", type=Path, required=True, help="new private directory")
    args = parser.parse_args()
    require(shutil.which("uv") is not None, "uv is required on PATH")
    os.umask(0o077)
    root = args.output.resolve()
    root.mkdir(mode=0o700, parents=True, exist_ok=False)
    requirements = root / "requirements-garak-profile.txt"
    receipt = {
        "passed": False,
        "scope": (
            "isolated red-teaming,garak frozen lock profile; scanner compatibility, "
            "live qualification and detector semantics are out of scope"
        ),
        "export_command": "uv export --frozen --no-dev --no-emit-project --extra red-teaming --extra garak",
        "lockfile_sha256": sha256(ROOT / "uv.lock"),
        "started_utc": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
    }
    try:
        export_frozen_profile(ROOT, requirements)
        receipt["requirements_sha256"] = sha256(requirements)
        with tempfile.TemporaryDirectory(prefix="garak-audit-tool-") as tool_dir:
            tool_venv = Path(tool_dir) / "tool"
            created = run(["uv", "venv", "--seed", str(tool_venv)])
            require(created.returncode == 0, f"uv venv failed: {created.stderr.strip()[:400]}")
            pip_audit_python, audit_version = audit_tool_pip_audit(tool_venv)
            receipt["audit_tool"] = {"pip_audit": audit_version}
            data, findings = run_audit(
                pip_audit_python,
                requirements,
                root / "audit-result.json",
                root / "audit-result.txt",
            )
        pinned = pinned_versions(requirements)
        receipt["profile"] = {
            name: "/".join(pinned.get(name, [])) or None for name in PINNED_KEY_PACKAGES
        }
        receipt["audited_distributions"] = len(data.get("dependencies", []))
        receipt["findings"] = findings
        unexpected, stale, applied = evaluate_findings(findings, pinned)
        receipt["dispositions_applied"] = applied
        receipt["unexpected_findings"] = unexpected
        receipt["stale_dispositions"] = stale
        receipt["dispositions"] = {
            f"{package}:{vuln_id}": record
            for (package, vuln_id), record in DISPOSITIONED_ADVISORIES.items()
        }
        if args.venv:
            venv_py = venv_python(args.venv)
            versions = installed_versions(venv_py)
            receipt["venv"] = {
                "garak": versions.get("garak"),
                "interplay_adversarial": versions.get("interplay-adversarial"),
                "python": run([str(venv_py), "--version"]).stdout.split()[-1],
            }
            receipt["venv_crosscheck"] = venv_crosscheck(venv_py, pinned)
            nltk_record = DISPOSITIONED_ADVISORIES.get(("nltk", "PYSEC-2026-3740"))
            if nltk_record:
                receipt["applicability_scan"] = applicability_scan(
                    venv_py, nltk_record, versions.get("garak")
                )
        if (
            unexpected
            or stale
            or (args.venv and receipt["venv_crosscheck"]["drift"])
            or (args.venv and receipt["venv_crosscheck"]["missing_key_packages"])
            or (
                args.venv and receipt.get("applicability_scan", {}).get("vulnerable_api_references")
            )
        ):
            raise RuntimeError(
                "audit failed: unexpected findings, stale dispositions, install/lock "
                "drift or invalidated applicability; see receipt.json"
            )
        receipt["completed_utc"] = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
        receipt["passed"] = True
    except Exception as exc:
        receipt["error"] = str(exc)
    save(root / "receipt.json", receipt)
    save(
        root / "receipt.txt",
        (
            f"passed={receipt['passed']}\n"
            + "\n".join(f"{k}={v}" for k, v in receipt.get("profile", {}).items())
            + f"\naudited_distributions={receipt.get('audited_distributions')}\n"
            + f"findings={json.dumps(receipt.get('findings', []))}\n"
            + f"dispositions_applied={','.join(receipt.get('dispositions_applied', [])) or 'none'}\n"
            + (f"error={receipt.get('error')}\n" if receipt.get("error") else "")
        ),
    )
    print(json.dumps(receipt))
    sys.exit(0 if receipt["passed"] else 1)


if __name__ == "__main__":
    main()

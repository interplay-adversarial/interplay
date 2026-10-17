"""Guards for the isolated Garak dependency audit and its bounded disposition."""

import re
import sys
import tomllib
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
import garak_isolated_audit as audit  # noqa: E402


def lock_versions():
    """Minimal uv.lock reader: package name -> sorted list of pinned versions."""
    versions = {}
    block = ""
    for line in (ROOT / "uv.lock").read_text().splitlines() + ["[[package]]"]:
        if line == "[[package]]":
            name = re.search(r'^name = "([^"]+)"', block)
            version = re.search(r'^version = "([^"]+)"', block, flags=re.M)
            if name and version:
                versions.setdefault(name.group(1), set()).add(version.group(1))
            block = ""
        else:
            block += line + "\n"
    return {name: sorted(vers) for name, vers in versions.items()}


def finding(name, version, vuln_id):
    return {
        "name": name,
        "version": version,
        "vulns": [{"id": vuln_id, "aliases": [], "fix_versions": []}],
    }


def test_garak_extra_floor_admits_0_17_1_but_not_0_17_0():
    from packaging.requirements import Requirement
    from packaging.version import Version

    data = tomllib.loads((ROOT / "pyproject.toml").read_text())
    specs = [
        Requirement(req).specifier
        for req in data["project"]["optional-dependencies"]["garak"]
        if Requirement(req).name == "garak"
    ]
    assert specs, "the garak extra must pin a garak requirement"
    assert any(Version("0.17.1") in spec for spec in specs)
    assert not any(Version("0.17.0") in spec for spec in specs)


def test_disposition_set_is_bounded_to_the_nltk_advisory():
    assert set(audit.DISPOSITIONED_ADVISORIES) == {("nltk", "PYSEC-2026-3740")}
    record = audit.DISPOSITIONED_ADVISORIES[("nltk", "PYSEC-2026-3740")]
    for field in (
        "status",
        "rationale",
        "upstream_evidence",
        "verified_against",
        "verified_garak_version",
        "vulnerable_apis",
    ):
        assert record[field], f"disposition missing {field}"
    assert record["status"] == "explicit-disposition-not-applicable"
    assert "CVE-2026-81726" in record["aliases"]
    assert "GHSA-8mgp-746c-j5xp" in record["aliases"]


def test_disposition_matches_locked_versions():
    versions = lock_versions()
    record = audit.DISPOSITIONED_ADVISORIES[("nltk", "PYSEC-2026-3740")]
    assert record["verified_against"] in versions["nltk"]
    assert record["verified_garak_version"] in versions["garak"]


def test_evaluate_findings_flags_unexpected_advisory():
    unexpected, stale, applied = audit.evaluate_findings(
        [finding("datasets", "5.1.0", "PYSEC-2026-9999")], {"datasets": ["5.1.0"]}
    )
    assert [item["id"] for item in unexpected] == ["PYSEC-2026-9999"]
    assert not stale and not applied


def test_evaluate_findings_applies_matching_disposition():
    unexpected, stale, applied = audit.evaluate_findings(
        [finding("nltk", "3.10.3", "PYSEC-2026-3740")], {"nltk": ["3.10.3"]}
    )
    assert applied == ["nltk:PYSEC-2026-3740"]
    assert not unexpected and not stale


def test_evaluate_findings_flags_version_drift_as_stale():
    unexpected, stale, applied = audit.evaluate_findings(
        [finding("nltk", "3.11.0", "PYSEC-2026-3740")], {"nltk": ["3.11.0"]}
    )
    assert not unexpected and not applied
    assert [item["advisory"] for item in stale] == ["PYSEC-2026-3740"]
    assert "re-verify" in stale[0]["reason"]


def test_evaluate_findings_flags_unreported_disposition_as_stale():
    unexpected, stale, applied = audit.evaluate_findings([], {"nltk": ["3.10.3"]})
    assert not unexpected and not applied
    assert [item["advisory"] for item in stale] == ["PYSEC-2026-3740"]


def test_pinned_versions_collects_marker_variants(tmp_path):
    requirements = tmp_path / "reqs.txt"
    requirements.write_text(
        "nltk==3.10.3\n"
        "jmespath==1.0.1 ; python_full_version < '3.14' \\\n    and extra == 'x'\n"
        "jmespath==1.1.0 ; python_full_version >= '3.14' \\\n    and extra == 'x'\n"
    )
    assert audit.pinned_versions(requirements) == {
        "nltk": ["3.10.3"],
        "jmespath": ["1.0.1", "1.1.0"],
    }


def test_canonicalize_matches_pip_freeze_names():
    assert audit.canonicalize("huggingface_hub") == "huggingface-hub"
    assert audit.canonicalize("Docstring_Parser") == "docstring-parser"
    assert audit.canonicalize("boolean-py") == "boolean-py"

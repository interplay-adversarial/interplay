"""Real optional SimpleAgent compatibility; deterministic model and file receiver.

Run each revision in its own environment with GYM_TEST_REVISION explicitly set.
No remote provider or enforcement boundary is exercised here.
"""

import importlib
import importlib.metadata
import importlib.util
import json
import os
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from interplay.assessment.gym import GYM_SOURCE_MANIFESTS, _native


@unittest.skipUnless(
    importlib.util.find_spec("nemo_gym"), "separate native Gym environment required"
)
class GymTargetNativeTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.revision = os.environ.get("GYM_TEST_REVISION")
        if cls.revision not in GYM_SOURCE_MANIFESTS:
            raise ValueError("explicit-native-test-revision-required")
        distribution = importlib.metadata.distribution("nemo-gym")
        direct = json.loads(distribution.read_text("direct_url.json") or "{}")
        if (
            direct.get("url") != "https://github.com/NVIDIA-NeMo/Gym.git"
            or direct.get("vcs_info", {}).get("commit_id") != cls.revision
            or direct.get("dir_info", {}).get("editable")
        ):
            raise ValueError("native-test-installed-source-mismatch")
        cls.source = Path(distribution.locate_file(""))
        _native(cls.revision)

    def test_native_complete_exhaustion_and_truncation(self):
        from scripts.gym_target_conformance import run

        for mode, counts in (
            ("complete", (2, 1, 1)),
            ("exhausted", (3, 3, 3)),
            ("truncated", (1, 0, 0)),
        ):
            with self.subTest(mode=mode), tempfile.TemporaryDirectory() as directory:
                root = Path(directory) / "capture"
                summary = run(self.source, root, mode=mode, gym_revision=self.revision)
                self.assertTrue(summary["verification_passed"], summary)
                self.assertEqual(summary["gym_revision"], self.revision)
                self.assertEqual(summary["capture_complete"], mode == "complete")
                self.assertEqual(
                    tuple(summary[k] for k in ("model_calls", "tool_calls", "receiver_records")),
                    counts,
                )
                self.assertFalse(summary["boundary_evaluated"])
                self.assertFalse(summary["release_eligible"])
                # Check all returned and persisted binding surfaces carry the selected pin.
                attempt = root / "adapter" / ("a" * 32)
                for name in ("request.json", "native.json", "environment.json"):
                    value = json.loads((attempt / name).read_bytes())
                    self.assertEqual(value["gym_revision"], self.revision)
                for line in (attempt / "events.jsonl").read_bytes().splitlines():
                    self.assertEqual(json.loads(line)["gym_revision"], self.revision)

    def test_other_supported_revision_is_not_a_fallback(self):
        other = next(r for r in GYM_SOURCE_MANIFESTS if r != self.revision)
        with self.assertRaisesRegex(ValueError, "gym-imported-source-mismatch"):
            _native(other)

    def test_failed_session_cannot_satisfy_fault_mode(self):
        from nemo_gym.server_utils import ServerClient

        from scripts.gym_target_conformance import run

        for mode in ("complete", "exhausted", "truncated"):
            with self.subTest(mode=mode), tempfile.TemporaryDirectory() as directory:
                with patch.object(
                    ServerClient,
                    "model_post_init",
                    side_effect=ValueError("fixture-initialization-loss"),
                ):
                    summary = run(
                        self.source,
                        Path(directory) / "capture",
                        mode=mode,
                        gym_revision=self.revision,
                    )
                self.assertFalse(summary["verification_passed"])
                self.assertFalse(summary["capture_complete"])
                self.assertEqual(summary["model_calls"], 0)
                self.assertEqual(summary["tool_calls"], 0)

    def test_each_changed_imported_file_rejected(self):
        real_import = importlib.import_module
        manifest = (
            Path(__file__).resolve().parents[1]
            / "interplay/assessment"
            / GYM_SOURCE_MANIFESTS[self.revision]
        )
        for filename in json.loads(manifest.read_bytes())["files"]:
            name = filename.removesuffix(".py").replace("/", ".")
            original = real_import(name)
            with self.subTest(module=name), tempfile.TemporaryDirectory() as directory:
                modified = Path(directory) / "modified.py"
                modified.write_bytes(Path(original.__file__).read_bytes() + b"\n# changed source\n")

                def imported(module, *, selected=name, path=modified):
                    return (
                        SimpleNamespace(__file__=str(path))
                        if module == selected
                        else real_import(module)
                    )

                with (
                    patch("interplay.assessment.gym.importlib.import_module", side_effect=imported),
                    self.assertRaisesRegex(ValueError, "gym-imported-source-mismatch"),
                ):
                    _native(self.revision)

    def test_revision_check_precedes_session_factory(self):
        from interplay.assessment.gym import GymTargetConfig, NeMoGymTarget
        from interplay.assessment.models import Probe

        calls = []
        other = next(r for r in GYM_SOURCE_MANIFESTS if r != self.revision)
        with tempfile.TemporaryDirectory() as directory:
            target = NeMoGymTarget(
                GymTargetConfig(gym_revision=other, task_id="source-admission", request_json="{}"),
                lambda attempt: calls.append(attempt),
                Path(directory) / "capture",
            )
            with self.assertRaisesRegex(ValueError, "gym-imported-source-mismatch"):
                target.observe(
                    Probe(probe="Synthetic", adversarial_intent="Test", strategy="fixture"),
                    "a" * 32,
                    deadline=0,
                )
            self.assertEqual(calls, [])
            self.assertFalse((Path(directory) / "capture" / ("a" * 32)).exists())

#!/usr/bin/env python3
"""Install interplay-adversarial in a throwaway directory and use it like a new user.

    python scripts/smoke_install.py --index testpypi --version 0.2.1
    python scripts/smoke_install.py --index pypi --version 0.2.1
    python scripts/smoke_install.py --index wheel --wheel dist/interplay_adversarial-0.2.1-py3-none-any.whl

Everything happens in a temp directory (HOME, DATA_DESIGNER_HOME and the working directory are all inside it)
and a local fake OpenAI endpoint (scripts/mock_openai.py) stands in for a model, so no key or network
model is needed. Exit code 0 means every check passed. Release process: docs/RELEASING.md.
"""

from __future__ import annotations

import argparse
import os
import shutil
import subprocess
import sys
import tempfile
import threading
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
import mock_openai  # noqa: E402

TESTPYPI = [
    "--index-url",
    "https://test.pypi.org/simple/",
    "--extra-index-url",
    "https://pypi.org/simple/",
    "--index-strategy",
    "unsafe-best-match",
    "--prerelease",
    "allow",
]


class Smoke:
    def __init__(self, root: Path, python: str):
        self.root, self.python, self.results = root, python, []
        self.venv = root / "venv"
        self.work = root / "work"
        self.work.mkdir()
        (root / "home").mkdir()
        self.env = {
            **{
                k: v
                for k, v in os.environ.items()
                if k not in {"OPENAI_API_KEY", "OPENAI_BASE_URL", "PYTHONPATH"}
            },
            "HOME": str(root / "home"),
            "DATA_DESIGNER_HOME": str(root / "dd"),
            "VIRTUAL_ENV": str(self.venv),
            "SMOKE_KEY": "not-a-real-key",
        }

    def bin(self, name: str) -> str:
        return str(self.venv / "bin" / name)

    def run(self, args: list[str], timeout: int = 300) -> subprocess.CompletedProcess:
        return subprocess.run(
            args, cwd=self.work, env=self.env, capture_output=True, text=True, timeout=timeout
        )

    def check(self, name: str, ok: bool, detail: str = "") -> bool:
        self.results.append((name, ok, detail))
        print(
            f"  {'PASS' if ok else 'FAIL'}  {name}"
            + (f"  [{detail.strip()[:160]}]" if detail and not ok else "")
        )
        return ok

    def install(self, spec: list[str], index_args: list[str], retries: int) -> bool:
        for attempt in range(retries):
            r = self.run(["uv", "pip", "install", "-q", "--refresh", *index_args, *spec])
            if r.returncode == 0:
                return True
            if attempt + 1 < retries:
                print(
                    f"  (install not ready, retrying in 15 s: {r.stderr.strip().splitlines()[-1][:100]})"
                )
                time.sleep(15)
        print(r.stderr[-600:])
        return False


def main() -> int:
    ap = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    ap.add_argument("--index", choices=["pypi", "testpypi", "wheel"], required=True)
    ap.add_argument("--version", help="expected version (required for pypi/testpypi)")
    ap.add_argument("--wheel", help="wheel path (index=wheel)")
    ap.add_argument("--python", default="3.12")
    ap.add_argument("--keep", action="store_true", help="keep the temp directory")
    args = ap.parse_args()
    if args.index in {"pypi", "testpypi"} and not args.version:
        ap.error("--version is required for pypi/testpypi")
    if args.index == "wheel" and not args.wheel:
        ap.error("--wheel is required for index=wheel")

    root = Path(tempfile.mkdtemp(prefix="interplay-smoke-"))
    print(f"smoke directory: {root}")
    s = Smoke(root, args.python)
    server = None
    try:
        r = subprocess.run(
            ["uv", "venv", "-q", "--python", args.python, str(s.venv)],
            capture_output=True,
            text=True,
        )
        if r.returncode:
            print(r.stderr)
            return 2
        if args.index == "wheel":
            spec, index_args, retries = [str(Path(args.wheel).resolve())], [], 1
            extra_spec = (
                f"interplay-adversarial[red-teaming] @ {Path(args.wheel).resolve().as_uri()}"
            )
        else:
            pin = f"interplay-adversarial=={args.version}"
            spec, index_args, retries = [pin], (TESTPYPI if args.index == "testpypi" else []), 6
            extra_spec = f"interplay-adversarial[red-teaming]=={args.version}"
        print("== install")
        if not s.install(spec, index_args, retries):
            return s.check("install", False) or 1
        s.check("install", True)

        print("== command line")
        r = s.run([s.bin("interplay"), "--version"])
        s.check(
            "version matches",
            r.returncode == 0 and (args.version is None or args.version in r.stdout),
            r.stdout + r.stderr,
        )
        r = s.run([s.bin("python"), "-c", "import interplay,sys;print(interplay.__file__)"])
        s.check(
            "imports from the venv, not a checkout", str(s.venv) in r.stdout, r.stdout + r.stderr
        )
        r = s.run([s.bin("interplay"), "modes"])
        s.check(
            "modes lists built-in and spec modes",
            all(m in r.stdout.split() for m in ["singapore", "combined", "us-mexico"]),
            r.stdout + r.stderr,
        )
        for mode in ("singapore", "sdg-hub-harm", "combined", "us-mexico"):
            r = s.run([s.bin("interplay"), "probes", "validate", "--mode", mode])
            s.check(
                f"validate --mode {mode}",
                r.returncode == 0 and "valid" in r.stdout.lower(),
                r.stdout[-200:] + r.stderr[-200:],
            )
        r = s.run([s.bin("interplay"), "probes", "validate", "--mode", "nope"])
        s.check(
            "unknown mode rejected with exit 2",
            r.returncode == 2 and "unknown mode" in r.stderr,
            r.stderr,
        )

        print("== first-run model setup")
        r = s.run([s.bin("interplay"), "probes", "preview"])
        s.check(
            "preview before setup explains how to set up",
            r.returncode == 2 and "interplay probes setup" in r.stderr,
            r.stdout[-200:] + r.stderr[-300:],
        )

        server = mock_openai.serve(0)
        port = server.server_address[1]
        threading.Thread(target=server.serve_forever, daemon=True).start()
        r = s.run(
            [
                s.bin("interplay"),
                "probes",
                "setup",
                "--base-url",
                f"http://127.0.0.1:{port}/v1",
                "--model",
                "mock-model",
                "--api-key-env",
                "SMOKE_KEY",
            ]
        )
        s.check(
            "setup writes the model alias",
            r.returncode == 0 and "cultural-bias-model" in r.stdout,
            r.stdout + r.stderr,
        )
        stored = "".join(p.read_text() for p in (root / "dd").glob("*.yaml"))
        s.check(
            "setup stores the key NAME, never the key",
            "SMOKE_KEY" in stored and "not-a-real-key" not in stored,
        )
        r = s.run([s.bin("interplay"), "probes", "preview", "--num-records", "4"], timeout=300)
        out = r.stdout + r.stderr
        s.check(
            "preview renders 4 generated records",
            r.returncode == 0 and "Preview complete" in out,
            out[-300:],
        )

        # The generation check inspects the real dataset written by `create` (this does not depend on
        # data-designer's preview display). Every mode must keep all rows, and every row needs a quality score.
        inspect_code = (
            "import glob,sys,pandas as pd;"
            "f=sorted(glob.glob('artifacts/*/parquet-files/*.parquet'));"
            "d=pd.concat(pd.read_parquet(p) for p in f) if f else None;"
            "print('ROWS', 0 if d is None else len(d), 'SCORED', 0 if d is None else int(d['probe_quality_score'].notna().sum()))"
        )
        for mode in ("singapore", "sdg-hub-harm", "combined"):
            shutil.rmtree(s.work / "artifacts", ignore_errors=True)
            r = s.run(
                [s.bin("interplay"), "probes", "create", "--mode", mode, "--num-records", "4"],
                timeout=300,
            )
            counts = s.run([s.bin("python"), "-c", inspect_code]).stdout.strip()
            s.check(
                f"create --mode {mode} keeps all 4 rows, each with a quality score",
                r.returncode == 0 and counts == "ROWS 4 SCORED 4",
                counts + " " + r.stdout[-200:] + r.stderr[-200:],
            )

        print("== optional dependencies")
        r = s.run([s.bin("python"), "-c", "import interplay.red_teaming"])
        s.check(
            "red_teaming without the extra gives an install hint",
            r.returncode != 0 and "interplay-adversarial[red-teaming]" in r.stderr,
            r.stderr[-300:],
        )
        r = s.run(["uv", "pip", "install", "-q", *index_args, extra_spec])
        s.check("install the [red-teaming] extra", r.returncode == 0, r.stderr[-300:])
        r = s.run(
            [
                s.bin("python"),
                "-c",
                "import interplay.red_teaming as r; print(sorted(n for n in r.__all__ if n.endswith('_attack')))",
            ]
        )
        s.check(
            "all six attack runners import",
            r.returncode == 0 and r.stdout.count("_attack") == 6,
            r.stdout + r.stderr[-300:],
        )
        r = s.run(
            [
                s.bin("python"),
                "-c",
                "from interplay.red_teaming import run_garak; run_garak('http://localhost/v1','p')",
            ]
        )
        s.check(
            "garak missing gives an install hint",
            "interplay-adversarial[garak]" in r.stderr,
            r.stderr[-300:],
        )
    finally:
        if server:
            server.shutdown()
        failed = [n for n, ok, _ in s.results if not ok]
        print(
            f"\n{len(s.results) - len(failed)}/{len(s.results)} checks passed"
            + (f"; FAILED: {', '.join(failed)}" if failed else "")
        )
        if args.keep:
            print(f"kept {root}")
        else:
            shutil.rmtree(root, ignore_errors=True)
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())

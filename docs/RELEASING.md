# Releasing

Every release goes to **TestPyPI first**, is verified there, and only then goes to PyPI. Versions on both
indexes are permanent: a bad version can only be yanked and replaced by the next patch version, so find
problems on TestPyPI.

## Steps

1. **Bump the version** in `interplay/__init__.py` (the single source) and date the entry in `CHANGELOG.md`.
   Open a PR; tests, lint and audit must pass; merge it.
2. **Publish to TestPyPI.** Actions → *Publish* → *Run workflow* on `main`. This builds the package and publishes
   that version to TestPyPI (environment `testpypi`).
3. **Verify the TestPyPI package like a new user.** From a checkout, run:

   ```bash
   python scripts/smoke_install.py --index testpypi --version X.Y.Z
   ```

   It installs into a throwaway directory (its own `HOME` and `DATA_DESIGNER_HOME`), checks the command line, the
   first-run model setup and an end-to-end dataset against a local fake endpoint, and the optional-dependency
   messages. Every check must pass. Also open the project page on test.pypi.org and read the description.
   If anything fails, fix it, bump to the next patch version and start again; do not release.
4. **Release.** Create a GitHub release with tag `vX.Y.Z` on `main`. The `testpypi-gate` job fails the run unless
   that exact version is already on TestPyPI. Then the `pypi` job waits for approval (environment `pypi`):
   *Review deployments* → approve.
5. **Verify PyPI.** Run `python scripts/smoke_install.py --index pypi --version X.Y.Z` (the index can lag a minute; the
   script retries).
6. **If PyPI is broken anyway:** yank the version on PyPI, fix, release the next patch through steps 1 to 5.

## What the smoke test does not cover

It uses a fake endpoint, so it proves the plumbing, not output quality. It does not install the heavy `garak`
extra. `probes preview` is only checked up to generation because data-designer's preview display can crash on
records whose judge was skipped (see the issue tracker). The unit tests and end-to-end test in `tests/` run in CI on
every pull request.

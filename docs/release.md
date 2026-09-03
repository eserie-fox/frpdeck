# Release Process

This project keeps release preparation intentionally lightweight.

## Checklist

1. Update the version in `src/frpdeck/version.py`.
2. Add the release entry at the top of `CHANGELOG.md`.
3. Add a matching release note under `docs/release-notes/`.
4. Run the locked install, formatting, lint, tests, and package build:

   ```bash
   uv sync --locked --python 3.11 --extra dev
   uv run ruff format --check .
   uv run ruff check .
   uv run pytest
   uv build --python 3.11
   ```

5. Commit, review, and merge the release preparation changes to `main`, then wait for normal CI.
   Explicitly dispatch the `Publish Python package` workflow to build once and publish to
   TestPyPI.
6. Check the TestPyPI package, then create and push the version tag:

   ```bash
   git tag vX.Y.Z
   git push origin vX.Y.Z
   ```

A newly created `v*` tag builds once and publishes to PyPI. Pull requests and ordinary `main`
pushes run CI only, while manual workflow dispatch publishes to TestPyPI. Deleting a tag does not
build or publish. Both indexes use Trusted Publishing through their matching GitHub environments.

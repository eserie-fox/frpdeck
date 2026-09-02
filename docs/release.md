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

5. Commit, review, and merge the release preparation changes to `main`.
6. Create and publish a normal GitHub Release for the intended version tag.

Publishing the GitHub Release is the sole automated publication entry point. The workflow
builds an sdist and wheel once through the shared public build workflow, then a project-local
job publishes that artifact to PyPI through Trusted Publishing, GitHub OIDC, and the `pypi`
environment. Tag pushes and manual dispatches do not invoke package publication.

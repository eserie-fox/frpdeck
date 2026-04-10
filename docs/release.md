# Release Process

This project keeps release preparation intentionally lightweight.

## Checklist

1. Update the version in `src/frpdeck/version.py`.
2. Add the release entry at the top of `CHANGELOG.md`.
3. Add a matching release note under `docs/release-notes/`.
4. Run the test suite.
5. Build source and wheel artifacts locally:

```bash
python -m build
```

6. Optionally verify built artifacts:

```bash
twine check dist/*
```

7. Commit the release preparation changes.
8. Create and push the tag:

```bash
git tag vX.Y.Z
git push origin main --tags
```

The GitHub publish workflow builds distributions on tag push and publishes to PyPI through Trusted Publishing.

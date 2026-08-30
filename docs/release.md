# Release Process

This project keeps release preparation intentionally lightweight.

## Checklist

1. Update the version in `src/frpdeck/version.py`.
2. Add the release entry at the top of `CHANGELOG.md`.
3. Add a matching release note under `docs/release-notes/`.
4. Run the test suite.
5. Derive `SOURCE_DATE_EPOCH` from the release commit and build source and wheel
   artifacts twice in isolated clean exports:

```bash
python -m build
```

6. Verify both build pairs:

```bash
twine check dist/*
python scripts/release/compare_artifacts.py <build-1-dist> <build-2-dist>
```

Wheel hashes must match exactly. Extracted sdist paths, contents, normalized
modes, entry types, and symlink targets must match. Record raw sdist hashes but
do not fail only for archive/gzip timestamps or container metadata.

7. Commit the release preparation changes.
8. Create and push the tag:

```bash
git tag vX.Y.Z
git push origin vX.Y.Z
```

The pushed `v*` tag is the sole publication authority. The GitHub workflow
checks tag/package-version equality, builds and validates once, records hashes,
and transfers the exact artifact bundle to the tag-only PyPI Trusted Publishing
job without rebuilding. Main pushes and `workflow_dispatch` never publish to
PyPI or TestPyPI; manual dispatch produces downloadable validation artifacts
only.

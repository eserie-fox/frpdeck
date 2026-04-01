"""Filesystem permission helpers for privilege preflight checks."""

from __future__ import annotations

import os
from pathlib import Path


def can_write_directory(path: Path) -> bool:
    """Return whether the current user can create or update entries under a directory path."""
    if path.exists():
        return path.is_dir() and _has_write_execute(path)
    return _has_write_execute(_nearest_existing_parent(path))


def can_write_file(path: Path) -> bool:
    """Return whether the current user can write to a file target."""
    if path.exists():
        return os.access(path, os.W_OK)
    return _has_write_execute(_nearest_existing_parent(path.parent))


def can_replace_directory(path: Path) -> bool:
    """Return whether the current user can remove and recreate one directory path."""
    if path.exists():
        return can_delete_path(path) and _has_write_execute(path.parent)
    return _has_write_execute(_nearest_existing_parent(path.parent))


def can_delete_path(path: Path) -> bool:
    """Return whether the current user can delete a file or directory tree."""
    if not path.exists():
        return True
    resolved = path.resolve()
    if resolved.is_dir() and not resolved.is_symlink():
        return _has_write_execute(resolved.parent) and _has_write_execute(resolved)
    return _has_write_execute(resolved.parent)


def root_owned_hint(path: Path) -> str:
    """Return a short ownership hint when an existing path is owned by root."""
    try:
        owner_uid = path.stat(follow_symlinks=False).st_uid
    except OSError:
        return ""
    if owner_uid == 0:
        return " (existing target is owned by root)"
    return ""


def _nearest_existing_parent(path: Path) -> Path:
    probe = path.resolve()
    while not probe.exists() and probe != probe.parent:
        probe = probe.parent
    return probe


def _has_write_execute(path: Path) -> bool:
    return os.access(path, os.W_OK | os.X_OK)

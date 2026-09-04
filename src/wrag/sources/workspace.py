"""Workspace source — walks local filesystem, computes hashes, yields files."""

from __future__ import annotations

import hashlib
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Generator, Optional

from wrag.config import Settings


@dataclass
class FileEntry:
    """A file discovered in the workspace."""

    path: str  # relative path from workspace root
    abs_path: str  # absolute path
    content_hash: str  # sha256 of file content
    content: str  # file text content (empty when unchanged and re-used from cache)
    size: int = 0
    mtime_ns: int = 0


def walk_workspace(
    workspace_path: str,
    settings: Settings,
    stat_cache: Optional[dict[str, str]] = None,
    known_hashes: Optional[dict[str, str]] = None,
) -> Generator[FileEntry, None, None]:
    """Walk workspace directory, yielding files that should be indexed.

    Respects exclusion settings (dirs and extensions).
    Skips binary files.

    Fast path: when both stat_cache and known_hashes are provided, files whose
    (size, mtime_ns) match the cache are yielded without reading their content;
    content_hash is re-used from known_hashes. Callers must treat such entries
    (empty content, non-empty cached hash) as "unchanged".
    """
    root = Path(workspace_path)
    # Entries with a "/" are path-relative (matched against the file's relative
    # dir path). Bare names still match any directory with that literal name.
    raw_excluded = list(settings.excluded_dirs)
    excluded_names = {d for d in raw_excluded if "/" not in d and d}
    excluded_paths = {
        d.strip("/").replace(os.sep, "/") for d in raw_excluded if "/" in d
    }
    excluded_exts = set(settings.excluded_extensions)
    stat_cache = stat_cache or {}
    known_hashes = known_hashes or {}

    def _is_path_excluded(rel_dir_posix: str) -> bool:
        if not excluded_paths:
            return False
        for prefix in excluded_paths:
            if rel_dir_posix == prefix or rel_dir_posix.startswith(prefix + "/"):
                return True
        return False

    for dirpath, dirnames, filenames in os.walk(root):
        rel_dir = os.path.relpath(dirpath, root).replace(os.sep, "/")
        if rel_dir == ".":
            rel_dir = ""

        # If we've descended into an excluded path prefix, skip the whole subtree.
        if rel_dir and _is_path_excluded(rel_dir):
            dirnames[:] = []
            continue

        # Filter child dirs by bare name + by full relative-path prefix
        pruned = []
        for d in dirnames:
            if d.startswith(".") or d in excluded_names:
                continue
            child_rel = f"{rel_dir}/{d}" if rel_dir else d
            if _is_path_excluded(child_rel):
                continue
            pruned.append(d)
        dirnames[:] = pruned

        for filename in filenames:
            # Skip hidden files
            if filename.startswith("."):
                continue

            # Skip excluded extensions
            ext = Path(filename).suffix.lower()
            if ext in excluded_exts:
                continue

            abs_path = os.path.join(dirpath, filename)
            rel_path = os.path.relpath(abs_path, root)

            # Cheap stat only — no read/decode/hash unless needed
            try:
                st = os.stat(abs_path)
            except OSError:
                continue
            size = st.st_size
            mtime_ns = st.st_mtime_ns

            if size > 1_048_576 or size == 0:
                continue

            stat_key = f"{size}:{mtime_ns}"

            # Fast path — file is unchanged since last index; skip read/hash.
            cached_hash = known_hashes.get(rel_path)
            if cached_hash and stat_cache.get(rel_path) == stat_key:
                yield FileEntry(
                    path=rel_path,
                    abs_path=abs_path,
                    content_hash=cached_hash,
                    content="",
                    size=size,
                    mtime_ns=mtime_ns,
                )
                continue

            # Slow path — file is new or changed; read + hash.
            try:
                with open(abs_path, "r", encoding="utf-8", errors="strict") as f:
                    content = f.read()
            except (UnicodeDecodeError, OSError):
                continue

            content_hash = hashlib.sha256(content.encode("utf-8")).hexdigest()

            yield FileEntry(
                path=rel_path,
                abs_path=abs_path,
                content_hash=content_hash,
                content=content,
                size=size,
                mtime_ns=mtime_ns,
            )


def compute_file_hash(file_path: str) -> str:
    """Compute sha256 hash of a file's content."""
    try:
        with open(file_path, "r", encoding="utf-8") as f:
            content = f.read()
        return hashlib.sha256(content.encode("utf-8")).hexdigest()
    except (UnicodeDecodeError, OSError):
        return ""
